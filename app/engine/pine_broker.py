# -*- coding: utf-8 -*-
"""共有 約定ブローカー（PineBroker）— TV 忠実約定（ホスト共有1本・D9）。

StrategyBuilder `strategies/_engine/backtest.py` の PineBroker を**無傷ベンダリング**。
Pine（process_orders_on_close=false）の標準ブローカーを忠実に再現する:
  - 成行（entry / close / EOD / ドテン）＝次バー始値約定。
  - 指値（limit）＝イントラバー約定。始値が既に越えていれば始値（ギャップ）。
  - 逆指値（stop）＝イントラバー約定。始値が既に割れていれば始値（ギャップ）。
  - 3Split は TP1=指値1枚・TP2=指値1枚・runner=逆指値 残全部を個別に建てる（OCO）。
  バー内で指値と逆指値が同時に届く時の順序＝TV 標準ブローカー既定:
    始値が高値寄り → 上昇先行（指値が先）／安値寄り → 下落先行（逆指値が先）。

戦略が返す注文（種別つき）:
  {"t":"entry","dir":+1/-1,"qty":N}          成行・次バー始値（逆方向はドテン）
  {"t":"close","qty":N|None}                 成行・次バー始値（None=全部）
  {"t":"exit","id":S,"qty":N|None,"limit":P,"stop":P}  建ち注文（OCO・毎バー上書き）
  {"t":"cancel","id":S}                       建ち注文の取消

オフライン driver（履歴バー）＝offline_driver.run_pine/run_pine_fast。
リアルタイム driver（tick）＝realtime_broker（M3）。いずれも本 PineBroker を母体に駆動。
★ホスト共有＝app/engine/。戦略フォルダには置かない（D9）。
"""
from __future__ import annotations

import math
from typing import List

import numpy as np

PT_TO_JPY = 100

# 日経225ミニの呼値単位（JPX 仕様＝5円）。取引所には 5円刻みの価格しか出せないため、
# realtime_broker（ライブ）・offline_driver（内蔵BT）とも tick=TICK_JPY で構築し発注価格を丸める
# （二刀エンジンの等価性維持）。tick=None は丸めなし（本家 StrategyBuilder と同じ従来動作）。
TICK_JPY = 5.0


class PineBroker:
    """Pine 標準ブローカーの忠実エミュレータ（次バー始値・指値/逆指値イントラバー・OCO・3Split）。

    tick: 呼値単位（円）。指定時、建ち注文（exit の limit/stop）の価格を submit 時に
    最近接の呼値へ丸める（★2026-07-09 追加＝本家 StrategyBuilder backtest.py との差分。
    ミニは 5円刻みでしか発注できないのに戦略計算値が 1円未満の端数を持ち、
    取引記録の約定値・損益が実発注と食い違っていたため）。None=丸めなし（従来動作）。
    """

    def __init__(self, qty_per_entry: int = 3, tick: float | None = None):
        self.qty_per_entry = qty_per_entry
        self.tick = tick
        self.fills: List[dict] = []
        self.reset()

    def _round_tick(self, px):
        """発注価格を呼値単位へ丸める（最近接）。tick 未指定・非数はそのまま返す。"""
        if self.tick is None or px is None:
            return px
        try:
            if np.isnan(px):
                return px
        except TypeError:
            return px
        return math.floor(px / self.tick + 0.5) * self.tick

    def reset(self) -> None:
        self.pos_dir = 0           # +1 long / -1 short / 0 flat
        self.pos_qty = 0
        self.avg_price = 0.0
        self.entry_bar = -1        # 約定した（建った）バーの絶対 index
        self.entry_ts = None
        self.trade_id = 0
        self._pending: list[dict] = []   # 次バー始値で約定する成行（close→entry の順で保持）
        self._book: dict[str, dict] = {} # 建ち注文 id→{qty,limit,stop,comment}
        self._filled_ids: set[str] = set()  # 現トレードで約定済みの exit id（Pine: 同 ID は再約定しない）
        self.fills = []

    # ---- 状態の公開（戦略へ Pine globals 相当を渡す）----
    @property
    def position_size(self) -> int:
        return self.pos_dir * self.pos_qty

    # ---- 約定の記録（建玉を qty 枚 px で返済）----
    def _reduce(self, px: float, qty: int, bar_idx: int, ts, reason: str) -> None:
        if self.pos_dir == 0 or self.pos_qty <= 0 or qty <= 0:
            return
        q = min(qty, self.pos_qty)
        pnl_pt = (px - self.avg_price) * self.pos_dir * q
        self.fills.append({
            "trade_id": self.trade_id,
            "entry_bar": self.entry_bar,
            "entry_ts": self.entry_ts,
            "entry_price": self.avg_price,
            "direction": "Long" if self.pos_dir > 0 else "Short",
            "exit_bar": bar_idx,
            "exit_ts": ts,
            "exit_price": px,
            "qty": q,
            "exit_reason": reason,
            "pnl_pt": pnl_pt,
            "pnl_jpy": pnl_pt * PT_TO_JPY,
        })
        self.pos_qty -= q
        if self.pos_qty <= 0:
            self._flat()

    def _flat(self) -> None:
        self.pos_dir = 0
        self.pos_qty = 0
        self.avg_price = 0.0
        self.entry_bar = -1
        self.entry_ts = None
        self._book.clear()      # 建玉が無くなれば建ち注文は全消滅（Pine と同じ）
        self._filled_ids.clear()

    def _open(self, direction: int, qty: int, px: float, bar_idx: int, ts) -> None:
        self.trade_id += 1
        self.pos_dir = direction
        self.pos_qty = qty
        self.avg_price = px
        self.entry_bar = bar_idx
        self.entry_ts = ts
        self._book.clear()
        self._filled_ids.clear()    # 新トレード = exit 約定履歴をリセット

    # ---- Phase A1: 前バー発注の成行を当バー始値で約定（close 群→entry 群の順）----
    def _exec_pending_market(self, o: float, bar_idx: int, ts) -> None:
        if not self._pending:
            return
        # ★close 群を entry 群より先に約定（同バーに両方ある＝ドテンで、entry を先にすると
        #   反転で建てた新玉を後続 close が即閉じる「ゴーストトレード」になる。close→entry が正）。
        for od in self._pending:
            if od["t"] == "close":
                qty = self.pos_qty if od.get("qty") is None else int(od["qty"])
                self._reduce(o, qty, bar_idx, ts, od.get("comment", "close"))
        for od in self._pending:
            if od["t"] == "entry":
                d = int(od["dir"]); qty = int(od.get("qty", self.qty_per_entry))
                if self.pos_dir != 0 and self.pos_dir != d:
                    # ドテン: 反対玉を成行始値で全清算してから建てる（close が既に閉じていれば no-op）
                    self._reduce(o, self.pos_qty, bar_idx, ts, "reverse")
                if self.pos_dir == 0:
                    self._open(d, qty, o, bar_idx, ts)
                # 同方向で建玉あり = pyramiding=1 → 無視（追加建てしない）
        self._pending = []

    # ---- Phase A2: 建ち注文（指値/逆指値）を当バーのイントラバーで約定（TV 標準順）----
    def _fill_resting(self, o: float, h: float, l: float, bar_idx: int, ts) -> None:
        if self.pos_dir == 0 or not self._book:
            return
        up_first = (h - o) < (o - l)   # 始値が高値寄り→上昇先行（TV 既定）。安値寄り/同距離→下落先行。
        d = self.pos_dir
        triggered: list[tuple] = []    # (sortkey, id, qty, fill_px)
        for oid, od in self._book.items():
            lim = od.get("limit"); stp = od.get("stop")
            leg = None; px = None
            # 指値（利確方向）: long は上・short は下
            if lim is not None and not np.isnan(lim):
                if d > 0:
                    if o >= lim: leg, px = "gap", o
                    elif h >= lim: leg, px = "up", lim
                else:
                    if o <= lim: leg, px = "gap", o
                    elif l <= lim: leg, px = "down", lim
            # 逆指値（損切/トレール方向）: long は下・short は上
            if leg is None and stp is not None and not np.isnan(stp):
                if d > 0:
                    if o <= stp: leg, px = "gap", o
                    elif l <= stp: leg, px = "down", stp
                else:
                    if o >= stp: leg, px = "gap", o
                    elif h >= stp: leg, px = "up", stp
            if leg is None:
                continue
            # 約定順: gap(始値)=最先 → 進行方向の先行レグ → 後行レグ。各レグ内は始値に近い順。
            if leg == "gap":
                rank = (0, 0.0)
            elif up_first:
                rank = (1, abs(px - o)) if leg == "up" else (2, abs(px - o))
            else:
                rank = (1, abs(px - o)) if leg == "down" else (2, abs(px - o))
            triggered.append((rank, oid, od.get("qty"), px, od.get("comment")))
        triggered.sort(key=lambda x: x[0])
        for rank, oid, qty, px, comment in triggered:
            if self.pos_dir == 0 or self.pos_qty <= 0:
                break
            if oid not in self._book:
                continue
            q = self.pos_qty if qty is None else int(qty)
            self._reduce(px, q, bar_idx, ts, comment or oid)
            self._book.pop(oid, None)   # 約定した建ち注文は消す（残注文の None qty は残枚数に自動追従）
            self._filled_ids.add(oid)   # 現トレードでは同 ID を再約定させない（Pine 仕様）

    # ---- Phase B: 戦略が当バー終値で出した注文を登録（次バー以降に効く）----
    def submit(self, orders: list[dict]) -> None:
        for od in orders or []:
            t = od.get("t")
            if t in ("entry", "close"):
                self._pending.append(od)        # 次バー始値で約定
            elif t == "exit":
                oid = od["id"]
                if oid in self._filled_ids:
                    continue   # 現トレードで約定済み = 再アームしない（毎バー無条件再送出でも一度きり）
                self._book[oid] = {"qty": od.get("qty"), "limit": self._round_tick(od.get("limit")),
                                   "stop": self._round_tick(od.get("stop")), "comment": od.get("comment")}
            elif t == "cancel":
                self._book.pop(od["id"], None)
