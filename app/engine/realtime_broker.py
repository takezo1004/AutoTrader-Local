# -*- coding: utf-8 -*-
"""リアルタイム driver（tick ブローカー）— ライブで PineBroker を駆動（D6・詳細仕様 §B）。

二刀エンジンのライブ側。オフライン driver（履歴バー）と**同一の PineBroker ロジック**を、
形成中足の tick で駆動する。指値/逆指値が tick でレベルに触れた瞬間に約定→ webhook 注文
（イントラバー・D12＝確定足の終わりを待たない＝TradingView 忠実）。

2イベント:
  on_bar_close(candle)  確定足ごと＝戦略判断（Pine globals 注入→on_bar→submit）。
  on_tick(price, ts)    形成中足の各 tick＝成行(新バー初値)・建ち注文(イントラバー)の約定検知。

約定検知は PineBroker の _exec_pending_market / _fill_resting をそのまま使う（オフラインと同一）。
running 足（_fo/_fh/_fl）を tick で更新し、_fill_resting に渡す＝バー版と同じ判定で tick 駆動。
ポジション差分は webhook_converter で spec §9 に変換し sender へ（dry-run は sender=仮想 or None）。
"""
from __future__ import annotations

import json

import pandas as pd

from .contract import Bar
from .pine_broker import PineBroker, PT_TO_JPY, TICK_JPY
from .webhook_converter import position_diff_to_webhook

try:                                         # 詳細デバッグログ（無くても動く）
    from app.feed.logger import dbg
except Exception:                            # pragma: no cover
    def dbg(*a, **k):
        pass


def _orders_brief(orders) -> str:
    """戦略が返した注文リスト（dict・正本プロトコル t=entry/close/exit/cancel）を短く要約。例外安全。"""
    out = []
    for o in orders:
        try:
            t = o.get("t")
            if t == "entry":
                d = "L" if o.get("dir", 0) > 0 else "S"
                out.append(f"新規{d}x{o.get('qty')}")
            elif t == "close":
                q = o.get("qty")
                out.append(f"決済x{q if q is not None else '全'}")
            elif t == "exit":
                px = []
                if o.get("limit") is not None: px.append(f"指値{o['limit']}")
                if o.get("stop") is not None: px.append(f"逆指{o['stop']}")
                out.append(f"建ち[{o.get('id')}]" + ("/".join(px) if px else ""))
            elif t == "cancel":
                out.append(f"取消[{o.get('id')}]")
            else:
                out.append(str(t if t is not None else o))
        except Exception:
            out.append("?")
    return ",".join(out) if out else "なし"


class RealtimeBroker:
    def __init__(self, strategy, name: str, interval: int = 15, qty_per_entry: int | None = None,
                 sender=None, passphrase: str = "", ticker: str = "OSE:NK225M1!"):
        self.strategy = strategy
        self.name = name
        self.interval = interval
        qpe = int(qty_per_entry or getattr(strategy, "qty_per_entry", 3))
        self.bk = PineBroker(qty_per_entry=qpe, tick=TICK_JPY)   # ライブ＝呼値5円へ丸めて発注（ミニ仕様）
        self.sender = sender                # .send(webhook) を持つオブジェクト or None（None=注文しない）
        self.passphrase = passphrase
        self.ticker = ticker
        self.webhooks: list[dict] = []      # 注文した webhook（dry-run/監視・最後の close で EOD も）
        self.on_event = None                # 取引イベント記録フック: on_event(dict) を呼ぶ（新規/決済）
        self.reset()

    def reset(self) -> None:
        self.strategy.reset()
        self.bk.reset()
        self._bar_index = -1
        self._new_bar = True                # 次の入力が「新バー最初」か
        self._fo = self._fh = self._fl = None
        self._last_close = None
        self._last_ts = None
        self._last_bar = None               # 直近の確定足（webhook の bar・TradingView と同一形式）
        self._nfills = 0                    # 記録済み fill 数（新規 fill=決済イベント検出用）
        self._last_tid = self.bk.trade_id   # 新規建玉検出用（trade_id 増加＝新規エントリー）

    # ---- 内部: ポジション差分 → webhook ----
    def _snap(self):
        return (self.bk.pos_dir, self.bk.pos_qty)

    def _fill_price(self, prev, cur) -> float:
        """この遷移が **実際に約定した値段** を返す（webhook の order_price に載せる）。

        ★なぜ必要か（2026-08-18）：order_price=0 で送ると、ブリッジは「対当（BestMarket）」＝
          kabu 仕様の **指値** として FrontOrderType=20 / Price=0 を送るため、kabu が
          「パラメータ不正：値段指定エラー」(4002017) で必ず拒否する。TradingView 版は
          {{strategy.order.price}} に実値が入るので起きない。ローカル版も同じ形で値段を載せる。

        新規・ドテン＝建値（avg_price）／部分返済・全量返済＝直近 fill の exit_price。
        いずれも取れないときは直近の終値へフォールバックする。

        ★丸めは行わない。値の出どころは足の OHLC（市場の値＝もともと呼値単位）と、
          PineBroker が submit 時に `_round_tick` 済みの limit/stop だけ。ここで丸め直すと
          TradingView（{{strategy.order.price}} をそのまま送る）と挙動が変わる。
        """
        px = 0.0
        if cur[0] != 0 and (prev[0] == 0 or prev[0] != cur[0]):      # 新規・ドテン
            px = float(getattr(self.bk, "avg_price", 0.0) or 0.0)
        else:                                                         # 部分返済・全量返済
            fills = getattr(self.bk, "fills", None)
            if fills:
                px = float(fills[-1].get("exit_price", 0.0) or 0.0)
        if not px:
            px = float(self._last_close or 0.0)
        return px

    def _order_id(self, prev, cur) -> str:
        """TradingView の {{strategy.order.id}} 相当。

        決済＝発火した建ち注文の名前（TP1_C / PSTOP など＝PineBroker の exit_reason）。
        新規・ドテン＝建玉の通し番号から作る（TradingView の entry id と同じ位置づけ）。
        """
        if cur[0] != 0 and (prev[0] == 0 or prev[0] != cur[0]):
            tid = getattr(self.bk, "trade_id", 0)
            return f"entry_{tid}" if tid else "entry"
        fills = getattr(self.bk, "fills", None)
        if fills:
            return str(fills[-1].get("exit_reason", "") or "")
        return ""

    def _emit(self, prev, order_price: float = 0) -> None:
        cur = self._snap()
        if not order_price:
            order_price = self._fill_price(prev, cur)
        wh = position_diff_to_webhook(prev[0], prev[1], cur[0], cur[1], self.name, self.interval,
                                      passphrase=self.passphrase, ticker=self.ticker,
                                      order_price=order_price,
                                      bar=getattr(self, "_last_bar", None),
                                      order_id=self._order_id(prev, cur))
        if wh:
            self.webhooks.append(wh)
            sender = self.sender            # ★別スレッド(set_enabled)が None へ差し替え得るので捕捉してから判定
            try:
                # ★2026-08-18 修正：order_action / order_contracts / order_price は wh["strategy"] の
                #   中にある。トップレベルを見ていたため常に None・@- と出力され、
                #   「何を送ったか」がログから分からなかった（8/18 の不達調査で判明）。
                st = wh.get("strategy", {})
                dbg(f"[{self.name}] webhook生成 {st.get('order_action')} x{st.get('order_contracts')} "
                    f"@{st.get('order_price') or '-'} pos {prev[0]}x{prev[1]}→{cur[0]}x{cur[1]} "
                    f"→ {'送出(有効)' if sender is not None else '記録のみ(無効=送出せず)'}")
                if sender is not None:      # 送るものは全文を残す（パスフレーズは伏せる）
                    dbg(f"[{self.name}] 送出内容 "
                        f"{json.dumps({**wh, 'passphrase': '***'}, ensure_ascii=False)}")
            except Exception:
                pass
            if sender is not None:
                sender.send(wh)             # sender は .send(webhook) を持つ（BridgeSender / VirtualSink）

    def _record(self) -> None:
        """発生順に取引イベントを on_event へ通知。新規fill＝決済イベント、trade_id増加＝新規建玉。"""
        if self.on_event is None:
            return
        fills = self.bk.fills
        while self._nfills < len(fills):       # 決済（部分/全量・各レグ）
            f = fills[self._nfills]; self._nfills += 1
            self.on_event({
                "ts": str(f["exit_ts"]), "kind": "決済", "strategy": self.name,
                "dir": f["direction"], "qty": int(f["qty"]), "price": float(f["exit_price"]),
                "trade_id": int(f["trade_id"]),
                "entry_ts": str(f["entry_ts"]), "entry_price": float(f["entry_price"]),
                "pnl_pt": round(float(f["pnl_pt"]), 1),
                "pnl_jpy": int(round(float(f["pnl_pt"]) * PT_TO_JPY)),
                "reason": str(f.get("exit_reason", "")),
            })
        if self.bk.pos_dir != 0 and self.bk.trade_id != self._last_tid:   # 新規建玉
            self._last_tid = self.bk.trade_id
            self.on_event({
                "ts": str(self.bk.entry_ts), "kind": "新規", "strategy": self.name,
                "dir": "Long" if self.bk.pos_dir > 0 else "Short",
                "qty": int(self.bk.pos_qty), "price": float(self.bk.avg_price),
                "trade_id": int(self.bk.trade_id),
                "entry_ts": str(self.bk.entry_ts), "entry_price": float(self.bk.avg_price),
                "pnl_pt": None, "pnl_jpy": None, "reason": "",
            })

    # ---- イベント①: 形成中足の各 tick ----
    def on_tick(self, price: float, ts, bar_open=None, bar_high=None, bar_low=None) -> None:
        # bar_open=寄付（セッション初足のみ命中）/ bar_high,bar_low=kabu 当日高安が当バーで更新された実値。
        # 渡されない（旧ブリッジ）時は現値標本のみ＝従来動作（後方互換）。
        price = float(price)
        if self._new_bar:
            self._bar_index += 1
            self._fo = float(bar_open) if bar_open is not None else price   # ★初足の成行は寄付で約定
            self._fh = self._fl = self._fo
            self._new_bar = False
            prev = self._snap()
            self.bk._exec_pending_market(self._fo, self._bar_index, ts)   # A1: 成行を初値約定
            self._emit(prev)
        # running 高安に「現値」＋「真の高安（標本で取りこぼした touch）」を反映
        if price > self._fh:
            self._fh = price
        if price < self._fl:
            self._fl = price
        if bar_high is not None and float(bar_high) > self._fh:
            self._fh = float(bar_high)
        if bar_low is not None and float(bar_low) < self._fl:
            self._fl = float(bar_low)
        # A2: 建ち注文（指値/逆指値）を running 足でイントラバー判定（建玉バー当日は不可）
        if self.bk.pos_dir != 0 and self._bar_index > self.bk.entry_bar and self.bk._book:
            prev = self._snap()
            self.bk._fill_resting(self._fo, self._fh, self._fl, self._bar_index, ts)
            self._emit(prev)
        self._record()

    # ---- イベント②: 確定足（戦略判断）----
    def on_bar_close(self, candle: dict) -> None:
        o = float(candle["open"]); h = float(candle["high"])
        l = float(candle["low"]); c = float(candle["close"])
        ts = candle.get("datetime")
        self._last_close = c
        self._last_ts = ts
        self._last_bar = {"time": ts, "open": o, "high": h, "low": l, "close": c,
                          "volume": float(candle.get("volume", 0) or 0)}

        if self._new_bar:
            # この足は tick を1つも受けていない（ダミー足/静かな窓）→ 足 OHLC で A1 を代行
            self._bar_index += 1
            self._new_bar = False
            self._fo, self._fh, self._fl = o, h, l
            prev = self._snap()
            self.bk._exec_pending_market(o, self._bar_index, ts)          # A1
            self._emit(prev)

        # A2 フォールバック（tick 取りこぼし or tickless 足を確定 OHLC で1回・§B.6）。
        # tick で約定済みは book から消えており再約定しない（_filled_ids）。
        if self.bk.pos_dir != 0 and self._bar_index > self.bk.entry_bar and self.bk._book:
            prev = self._snap()
            self.bk._fill_resting(o, h, l, self._bar_index, ts)
            self._emit(prev)

        # 戦略判断（Pine globals 注入 → on_bar → submit）
        self.strategy.position_size = self.bk.position_size
        self.strategy.position_avg_price = self.bk.avg_price
        self.strategy.entry_bar = self.bk.entry_bar
        self.strategy.bars_since_entry = (self._bar_index - self.bk.entry_bar) if self.bk.entry_bar >= 0 else -1
        orders = self.strategy.on_bar(Bar(ts=ts, open=o, high=h, low=l, close=c,
                                          volume=float(candle.get("volume", 0)))) or []
        try:
            bse = (self._bar_index - self.bk.entry_bar) if self.bk.entry_bar >= 0 else -1
            dbg(f"[{self.name}] 確定足 {ts} C{c:.0f} pos={self.bk.pos_dir}x{self.bk.pos_qty} "
                f"bars_since_entry={bse} → 戦略判断シグナル: {_orders_brief(orders)}")
        except Exception:
            pass
        self.bk.submit(orders)
        self._new_bar = True
        self._record()

    def prime(self, df) -> None:
        """warmup: 履歴足で戦略の指標バッファを温める（broker は flat のまま・発注しない）。

        ライブ開始時、戦略の内部バッファ（指標 lookback）を満たすために直近 W 本を流す。
        建玉は持たない（実際には flat から始める）ので position_size=0 を注入し、返る注文は捨てる。
        ＝クローン AI と同じ warmup 思想（指標は温める・建玉は flat）。
        """
        o = df["open"].to_numpy(float); h = df["high"].to_numpy(float)
        l = df["low"].to_numpy(float); c = df["close"].to_numpy(float)
        ts = df.index.to_numpy()
        for i in range(len(df)):
            self.strategy.position_size = 0
            self.strategy.position_avg_price = 0.0
            self.strategy.entry_bar = -1
            self.strategy.bars_since_entry = -1
            self.strategy.on_bar(Bar(ts=ts[i], open=o[i], high=h[i], low=l[i], close=c[i],
                                     volume=0.0))
            self._bar_index += 1
        # broker は flat・_new_bar=True のまま（次の live tick が新バー初値）。

    def warmup_replay(self, df) -> None:
        """warmup＝履歴足を **live と同一 on_bar でブローカー駆動**し、現在建玉・出口・指標バッファを
        履歴から再構築する（TV と同一シーケンス＝ロードのたび履歴から戦略を再計算）。

        これにより snapshot/restore（D15）は不要：再起動しても「戦略が今保有しているはずの建玉＋
        未約定注文」と各戦略（ポートフォリオはサブ含む）の指標バッファがそのまま整い、最初の live
        足/tick から **差分のみ** webhook 送出される。BT(run_pine)≡live≡warmup が同一コードパスで一致。

        過去分は **発注も記録もしない**（_emit/_record を呼ばない＝webhook 送出ゼロ・取引イベント
        通知ゼロ）。再生後の建玉/未約定注文は live が引き継ぐ。flat 専用の prime() の置き換え。
        """
        o = df["open"].to_numpy(float); h = df["high"].to_numpy(float)
        l = df["low"].to_numpy(float); c = df["close"].to_numpy(float)
        vol = df["volume"].to_numpy(float) if "volume" in df.columns else None
        ts = df.index.to_numpy()
        n = len(df)
        for i in range(n):
            # offline_driver._run_pine と同一順序：A1 成行(前足 submit を当足始値) → A2 建ち注文 → B 決定。
            self.bk._exec_pending_market(o[i], i, ts[i])
            if self.bk.pos_dir != 0 and i > self.bk.entry_bar and self.bk._book:
                self.bk._fill_resting(o[i], h[i], l[i], i, ts[i])
            self.strategy.position_size = self.bk.position_size
            self.strategy.position_avg_price = self.bk.avg_price
            self.strategy.entry_bar = self.bk.entry_bar
            self.strategy.bars_since_entry = (i - self.bk.entry_bar) if self.bk.entry_bar >= 0 else -1
            orders = self.strategy.on_bar(Bar(ts=ts[i], open=o[i], high=h[i], low=l[i], close=c[i],
                                              volume=(float(vol[i]) if vol is not None else 0.0))) or []
            self.bk.submit(orders)
        # live 継続のための整合（★end_of_data 強制決済はしない＝建玉を保持して live へ引き継ぐ）。
        self._bar_index = n - 1                       # 次 live 足/tick で n に進む（entry_bar<n ＝ TP 発火可）
        self._new_bar = True                          # 次 live 入力＝新バー（最終 warmup 足の submit を live 始値で約定）
        self._fo = self._fh = self._fl = None
        self._last_close = float(c[-1]) if n else None
        self._last_ts = ts[-1] if n else None
        self._nfills = len(self.bk.fills)             # 過去 fill を live 決済イベントとして再通知しない
        self._last_tid = self.bk.trade_id             # 過去建玉を live 新規イベントとして再通知しない

    # ---- 建玉スナップショット（受動記録・D15 改訂 2026-06-24／復元は warmup_replay に置換）----
    def snapshot(self) -> dict | None:
        """現在の建玉＋出口状態を dict で返す（flat は None）。`app/state/positions/<name>.json` 用。"""
        bk = self.bk
        if bk.pos_dir == 0 or bk.pos_qty <= 0:
            return None

        def num(v):
            try:
                v = float(v); return None if v != v else v        # NaN→None（valid JSON）
            except (TypeError, ValueError):
                return None
        st = self.strategy
        return {
            "pos_dir": int(bk.pos_dir), "pos_qty": int(bk.pos_qty), "avg_price": float(bk.avg_price),
            "entry_ts": (str(bk.entry_ts) if bk.entry_ts is not None else None),
            "trade_id": int(bk.trade_id), "filled_ids": sorted(bk._filled_ids),
            "book": {k: {kk: (num(vv) if kk in ("limit", "stop") else vv) for kk, vv in v.items()}
                     for k, v in bk._book.items()},
            "bars_held": int(self._bar_index - bk.entry_bar) if bk.entry_bar >= 0 else 0,
            "strat": {"signup": int(getattr(st, "signup", 0)),
                      "tp1": num(getattr(st, "tp1", None)), "tp2": num(getattr(st, "tp2", None)),
                      "zz_p1": num(getattr(st, "zz_p1", None))},
        }

    def restore(self, snap) -> bool:
        """snapshot() の dict から建玉＋出口状態を broker/戦略へ注入（warmup（prime）の後に呼ぶ）。

        ★filled_ids 復元で約定済み TP の二重決済を防止。entry_bar を現在 bar_index に再アンカー
        （次の確定足から i>entry_bar が成立し TP 発火可）。prev_size=size で just_entered 再発火を抑止。
        """
        if not snap:
            return False
        bk = self.bk

        def back(v):
            return float(v) if v is not None else float("nan")
        bk.pos_dir = int(snap["pos_dir"]); bk.pos_qty = int(snap["pos_qty"])
        bk.avg_price = float(snap["avg_price"]); bk.trade_id = int(snap.get("trade_id", 1))
        bk.entry_ts = snap.get("entry_ts")
        bk._filled_ids = set(snap.get("filled_ids", []))
        bk._book = {k: {kk: (back(vv) if kk in ("limit", "stop") else vv) for kk, vv in v.items()}
                    for k, v in snap.get("book", {}).items()}
        bk.entry_bar = self._bar_index                                   # 次足から TP 発火可
        st = self.strategy
        s = snap.get("strat", {})
        if hasattr(st, "signup"): st.signup = int(s.get("signup", 0))
        for k in ("tp1", "tp2", "zz_p1"):
            if hasattr(st, k): setattr(st, k, back(s.get(k)))
        if hasattr(st, "_prev_size"): st._prev_size = bk.position_size   # just_entered 再発火防止
        st.position_size = bk.position_size; st.position_avg_price = bk.avg_price
        st.entry_bar = bk.entry_bar; st.bars_since_entry = int(snap.get("bars_held", 0))
        self._last_tid = bk.trade_id; self._nfills = len(bk.fills)        # 復元玉を新規/決済で再記録しない
        return True

    def finalize_end_of_data(self, close: float | None = None, ts=None) -> None:
        """データ終端: 建玉が残れば最終足 close で強制決済（offline と同じ EOD・主に検証用）。"""
        if self.bk.pos_dir != 0 and self.bk.pos_qty > 0:
            px = float(close) if close is not None else self._last_close
            t = ts if ts is not None else self._last_ts
            prev = self._snap()
            self.bk._reduce(px, self.bk.pos_qty, self._bar_index, t, "end_of_data")
            self._emit(prev)
            self._record()

    @property
    def fills(self) -> pd.DataFrame:
        return pd.DataFrame(self.bk.fills)
