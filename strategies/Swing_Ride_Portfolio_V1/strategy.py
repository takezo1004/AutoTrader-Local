# -*- coding: utf-8 -*-
"""Swing_Ride_Portfolio — Swing_Ride シリーズ3本を「枠1つ・早い者勝ち」で束ねる合成戦略。

【何をするか】
  ストキャス／ダブルDT／モメンタムの3本は、基軸オシレーターだけが違う同じ骨格の戦略。
  4年の測定で、**保有時間が重なるのは全体の1割**（3本とも同時に持つ足は 9.8%）で、
  **58.5% の足はどれも建玉を持っていない**＝枠が空いている。
  そこで **枚数を増やさずに** 3本のサインを1つの枠で拾う。

  - 入口＝3本のサインの和集合。フラットのときだけ、優先順の先頭の発火を採用（早い者勝ち）
  - 保有中は新規を見送る。建玉は**採用した戦略が最後まで**（その戦略の3分割の出口で）管理する
  - 建玉の状態は採用中の戦略にだけ渡し、他の2本には「フラット」を渡す（指標だけ更新される）
  - セッション制御は**合成後の注文に1回だけ**かける（サブ側の gate は無効化＝二重がけを避ける）

【4年較正バックテスト（work/v1_bt.py の EXPECT・毎回照合）】
  n=1192 PF1.77 純益+17,431,035円 最大DD−855,250円
  ワースト−222,000円・−30万以下0件・−10万以下26件
  年別 +124.8/+417.7/+432.6/+768.1 万円（全年プラス）
  枠を取った回数＝ストキャス454（PF1.97 +746万）／モメンタム371（PF1.79 +575万）／
                  ダブルDT367（PF1.55 +422万）＝きれいに3等分

  単独との比較: ストキャス +1,382万／ダブルDT +976万／モメンタム +1,149万。
  **単独最良より +351万、しかも最大DDは −95.3万 → −85.5万と小さい**（全年で単独最良を上回る）。

【サブ戦略の置き場所】
  開発（work/）＝`strategies/<戦略名>/<戦略名>_<版>/` の最新版を読む（版名フォルダ）。
  配布（確定フォルダ）＝`_subs/<戦略名>/` に同梱したものを読む（自己完結）。

★約定モデル＝TV（Pine）完全忠実。約定は共有 `_engine` の PineBroker。戦略は注文を返すだけ。
"""
from __future__ import annotations

import importlib.util as _ilu
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:                                  # 共有セッションライブラリ（プラットフォーム提供・ZIP非同梱）
    import session_lib
except Exception:                     # pragma: no cover
    session_lib = None

_HERE = Path(__file__).resolve().parent
# ★warmup 700＝サブの板厚バッファ（thick_win 500 + 100 = 600）を live 予熱で満たすため
#   （2026-08-06 ライブ経路の出来高対応 ＋ thick_win 1000→500 短縮）。
#   エンジンはこの値ぶん履歴を先に流してから live に入る。
MANIFEST = {"name": "Swing_Ride_Portfolio", "interval": 15, "warmup_bars": 700,
            "version": 1, "label": "V1"}


def _load_config() -> dict:
    with open(_HERE / "config.json", encoding="utf-8") as f:
        return json.load(f)


def _sub_path(name: str) -> Path:
    """サブ戦略 strategy.py の場所。確定フォルダ同梱(_subs/<名>) があればそれ、無ければ版名フォルダの最新。"""
    bundled = _HERE / "_subs" / name / "strategy.py"
    if bundled.exists():
        return bundled
    strats = _HERE.parents[1]                                  # work -> Swing_Ride_Portfolio -> strategies
    cands = [p for p in (strats / name).glob(f"{name}_*") if (p / "strategy.py").is_file()]
    if cands:
        newest = max(cands, key=lambda p: [int(x) for x in re.findall(r"\d+", p.name[len(name):])] or [0])
        return newest / "strategy.py"
    p = strats / name / "work" / "strategy.py"                 # 最後の手段＝開発中の work
    if p.is_file():
        return p
    raise FileNotFoundError(f"サブ戦略が見つからない: {name}")


def _load_sub(name: str):
    p = _sub_path(name)
    key = f"_srp_sub__{name}"
    mod = sys.modules.get(key)
    if mod is None:
        spec = _ilu.spec_from_file_location(key, str(p))
        mod = _ilu.module_from_spec(spec)
        sys.modules[key] = mod
        spec.loader.exec_module(mod)
    return mod.build()


class Swing_Ride_Portfolio:
    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or _load_config()
        self.priority = list(self.cfg.get("priority", [
            "Swing_Ride_Stochastic_Long", "Swing_Ride_DoubleDT", "Swing_Ride_Momentum"]))
        self.interval = MANIFEST["interval"]
        self.qty_per_entry = int(self.cfg.get("qty_per_entry", 3))
        self.session_enabled = bool(self.cfg.get("session_enabled", True))
        self.subs = {name: _load_sub(name) for name in self.priority}
        for s in self.subs.values():          # ★二重がけ回避：サブ側の gate は無効化
            s.session_enabled = False
        self._A = {}
        self._ts = None
        self.reset()

    # ---- 状態 ----
    def reset(self) -> None:
        for s in self.subs.values():
            s.reset()
        self.active = None
        self.position_size = 0
        self.position_avg_price = 0.0
        self.entry_bar = -1
        self.bars_since_entry = -1

    # ---- 指標（サブごとに1回だけ）----
    def precompute(self, df: pd.DataFrame) -> dict:
        self._ts = pd.DatetimeIndex(df.index)
        for name, s in self.subs.items():
            s._bt_ts = self._ts
            self._A[name] = s.precompute(df)
        return {"n": len(df)}

    # ---- 1バーの決定 ----
    def step(self, A, i) -> list[dict]:
        pos = int(self.position_size)
        out = {}
        for name in self.priority:
            s = self.subs[name]
            if pos != 0 and name == self.active:              # 建玉は採用した戦略にだけ見せる
                s.position_size = self.position_size
                s.position_avg_price = self.position_avg_price
                s.entry_bar = self.entry_bar
                s.bars_since_entry = self.bars_since_entry
            else:
                s.position_size = 0
                s.position_avg_price = 0.0
                s.entry_bar = -1
                s.bars_since_entry = -1
            out[name] = s.step(self._A[name], i) or []
        if pos == 0:
            self.active = None
            for name in self.priority:                        # 早い者勝ち（優先順）
                if any(o.get("t") == "entry" for o in out[name]):
                    self.active = name
                    break
        if self.active is None:
            return []
        orders = list(out[self.active])
        ts = self._ts[i] if (self._ts is not None and i < len(self._ts)) else None
        return self._gate(orders, ts)

    # ---- live: 確定足ごと（step と同順＝建玉は採用中のサブにだけ見せる → 早い者勝ち）----
    #   サブの on_bar は各自のバッファ（出来高込み・2026-08-06）で再計算する。
    #   セッション制御は step と同じく合成後に1回だけ（サブ側は __init__ で無効化済み）。
    def on_bar(self, bar) -> list[dict]:
        pos = int(self.position_size)
        out = {}
        for name in self.priority:
            s = self.subs[name]
            if pos != 0 and name == self.active:              # 建玉は採用した戦略にだけ見せる
                s.position_size = self.position_size
                s.position_avg_price = self.position_avg_price
                s.entry_bar = self.entry_bar
                s.bars_since_entry = self.bars_since_entry
            else:
                s.position_size = 0
                s.position_avg_price = 0.0
                s.entry_bar = -1
                s.bars_since_entry = -1
            out[name] = s.on_bar(bar) or []
        if pos == 0:
            self.active = None
            for name in self.priority:                        # 早い者勝ち（優先順）
                if any(o.get("t") == "entry" for o in out[name]):
                    self.active = name
                    break
        if self.active is None:
            return []
        return self._gate(list(out[self.active]), getattr(bar, "ts", None))

    # ---- セッション制御（合成後に1回だけ・step/on_bar 共用）----
    def _gate(self, orders, ts):
        if session_lib is None or not self.session_enabled or ts is None:
            return orders
        fl = session_lib.flags(ts, self.interval)
        return session_lib.gate(orders, fl, self.position_size)

    # ---- どの戦略が建てたか（記録・表示用）----
    def active_name(self) -> str:
        return self.active or ""


def build(cfg: dict | None = None) -> Swing_Ride_Portfolio:
    return Swing_Ride_Portfolio(cfg)
