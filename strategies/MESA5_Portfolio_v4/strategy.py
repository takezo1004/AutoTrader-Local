# -*- coding: utf-8 -*-
"""MESA5_Portfolio — 5戦略（MESA/DT/TSI/CMF/Momentum）を1戦略・同時1ポジで束ねる合成ロジック。

設計＝`../design/spec.md`。AIでなくロジック。資金3枚＝同時1ポジ。
- 入口＝5戦略のシグナルの和集合。フラット時のみ、優先順(priority)で先頭の発火を採用（first-come）。
- 保有中は新規見送り。建玉は採用戦略(active)が3Split出口で最後まで管理（＝activeの単独トレードと同一）。
- 約定・建玉は共有 _engine の PineBroker。サブ戦略は無改修。

実装：毎バー全サブの step/on_bar を呼んで指標/signupを更新（建玉状態は active にだけ注入・他は0）。

★セッション制御（実トレード制約・2026-06-29 ユーザー確定）＝共有ライブラリ `session_lib` に一元化:
  各セッション終了30分前以降は新規/決済とも約定不可・週末/祝日/大納会/SQ 直前は強制 flat。
  判定は per-bar・先読みなし・era 対応カレンダー（data/session_hours.json・data/sq_calendar.json）。
  `session_lib` は LocalEngine 提供（ZIP 非同梱・runtime は loader / dev は BT ランナーが import 解決）。
  Pine 側は KengetsuLib（同一カレンダー）。＝Pine BT＝Python BT＝ライブ が同一シーケンスで一致。
  ※ サブを内包する本ポートフォリオは「合成後の最終注文」を1回だけ gate（サブ側 gate は無効化＝二重化回避）。
"""
from __future__ import annotations

import importlib.util as _ilu
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:                                  # 共有セッションライブラリ（プラットフォーム提供・ZIP非同梱）
    import session_lib
except Exception:                     # pragma: no cover  未提供環境では従来挙動（gate せず）
    session_lib = None

_HERE = Path(__file__).resolve().parent                      # work/（開発）or 確定フォルダ
MANIFEST = {"name": "MESA5_Portfolio", "interval": 15, "warmup_bars": 500, "version": 4}  # v4=サブ現行版化＋レッグ別構造損切り(Mom/TSI=全ロング監視・DT=OFF・MESA=単独確定)・timeout=全レッグOFF実測(2026-07-20)／v3=MESAサブをV8化／v2=セッション制御込


def _load_config() -> dict:
    with open(_HERE / "config.json", encoding="utf-8") as f:
        return json.load(f)


def _sub_path(name: str) -> Path:
    """サブ戦略 strategy.py の場所。確定フォルダ同梱(_subs/<名>) があればそれ、無ければ Builder 確定版。"""
    bundled = _HERE / "_subs" / name / "strategy.py"
    if bundled.exists():
        return bundled
    # 開発（work/）：Builder 確定版 strategies/<名>/<名>/strategy.py を読む
    strats = _HERE.parents[1]                                 # work -> MESA5_Portfolio -> strategies
    return strats / name / name / "strategy.py"


def _load_sub(name: str):
    p = _sub_path(name)
    key = f"_p5sub__{name}"
    mod = sys.modules.get(key)
    if mod is None:
        spec = _ilu.spec_from_file_location(key, str(p))
        mod = _ilu.module_from_spec(spec); sys.modules[key] = mod; spec.loader.exec_module(mod)
    return mod.build()


class MESA5_Portfolio:
    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or _load_config()
        self.priority = list(self.cfg.get("priority",
                             ["MESA_Stochastic", "DT_Stochastic", "TSI_Stochastic", "Momentum_Combo"]))  # CMF除外=DD主因
        self.qty_per_entry = int(self.cfg.get("qty_per_entry", 3))
        self.stop_atr = self.cfg.get("stop_atr", None)       # 保護ストップ幅（×ATR・None=無し）
        self.interval = int(MANIFEST.get("interval", 15))
        # セッション制御（config["session"]["enabled"] 既定 True・offset 等は session_lib のカレンダー）
        self.session_enabled = bool((self.cfg.get("session") or {}).get("enabled", True))
        self.subs = {name: _load_sub(name) for name in self.priority}
        for s in self.subs.values():                         # ★二重化回避：サブの自前 gate は無効化
            s.session_enabled = False
        self.reset()
        self._ts = None                  # precompute で df.index を保持（reset では消さない）

    def reset(self) -> None:
        for s in self.subs.values():
            s.reset()
        self.active = None
        self._prev_meta = 0
        self._stop_price = float("nan")
        self.position_size = 0
        self.position_avg_price = 0.0
        self.entry_bar = -1
        self.bars_since_entry = -1

    # ---- 建玉状態を active サブにだけ注入（他は flat）----
    def _inject(self):
        ms = int(self.position_size)
        for name, s in self.subs.items():
            if ms != 0 and name == self.active:
                s.position_size = self.position_size
                s.position_avg_price = self.position_avg_price
                s.entry_bar = self.entry_bar
                s.bars_since_entry = self.bars_since_entry
            else:
                s.position_size = 0
                s.position_avg_price = 0.0
                s.entry_bar = -1
                s.bars_since_entry = -1

    def _combine(self, sub_orders: dict) -> list[dict]:
        ms = int(self.position_size)
        if ms == 0:
            self.active = None
            for name in self.priority:                       # first-come（優先順）
                ents = [o for o in sub_orders[name] if o.get("t") == "entry"]
                if ents:
                    self.active = name
                    return [ents[0]]
            return []
        # 保有中：active の全注文（出口＋ドテン）を流す。他サブの新規は無視。
        return list(sub_orders.get(self.active, []))

    # ---- 保護ストップ（損切り・×ATR）を毎バー再配置（差し値・PineBroker がイントラバー約定）----
    def _add_stop(self, orders, atr_i):
        if not self.stop_atr:
            return orders
        ms = int(self.position_size)
        if ms == 0:
            self._stop_price = float("nan"); self._prev_meta = 0
            return orders
        if self._prev_meta == 0 and atr_i is not None and np.isfinite(atr_i):   # just entered
            d = 1 if ms > 0 else -1
            self._stop_price = self.position_avg_price - self.stop_atr * atr_i * d
        self._prev_meta = ms
        if np.isfinite(self._stop_price):
            return list(orders) + [{"t": "exit", "id": "PSTOP", "qty": None, "stop": self._stop_price}]
        return orders

    # ---- セッション制御（合成後の最終注文を1回だけ gate・per-bar）----
    def _session_gate(self, orders, ts) -> list[dict]:
        if session_lib is None or not self.session_enabled or ts is None:
            return orders
        fl = session_lib.flags(ts, self.interval)
        return session_lib.gate(orders, fl, self.position_size)

    # ---- BT高速パス ----
    def precompute(self, df) -> dict:
        A = {name: s.precompute(df) for name, s in self.subs.items()}
        H = df["high"].to_numpy(float); L = df["low"].to_numpy(float); C = df["close"].to_numpy(float)
        pc = np.concatenate([[np.nan], C[:-1]])
        tr = np.maximum.reduce([H - L, np.abs(H - pc), np.abs(L - pc)])
        A["_atr"] = pd.Series(tr).rolling(14).mean().to_numpy()
        self._ts = pd.DatetimeIndex(df.index)
        return A

    def step(self, A, i) -> list[dict]:
        self._inject()
        sub_orders = {name: (s.step(A[name], i) or []) for name, s in self.subs.items()}
        orders = self._combine(sub_orders)
        atr_i = A["_atr"][i] if "_atr" in A else None
        orders = self._add_stop(orders, atr_i)
        ts = self._ts[i] if (self._ts is not None and i < len(self._ts)) else None
        return self._session_gate(orders, ts)

    # ---- live（バッファ再計算・各サブの on_bar）----
    def on_bar(self, bar) -> list[dict]:
        self._inject()
        sub_orders = {name: (s.on_bar(bar) or []) for name, s in self.subs.items()}
        orders = self._combine(sub_orders)
        # 保護ストップ用 ATR（直近バッファから）
        atr_i = None
        if self.stop_atr:
            self._h = getattr(self, "_h", []); self._l = getattr(self, "_l", []); self._c = getattr(self, "_c", [])
            self._h.append(bar.high); self._l.append(bar.low); self._c.append(bar.close)
            for b in (self._h, self._l, self._c):
                if len(b) > 30:
                    b.pop(0)
            if len(self._c) >= 15:
                H = np.asarray(self._h); L = np.asarray(self._l); C = np.asarray(self._c)
                pc = np.concatenate([[np.nan], C[:-1]])
                tr = np.maximum.reduce([H - L, np.abs(H - pc), np.abs(L - pc)])
                atr_i = np.nanmean(tr[-14:])
        orders = self._add_stop(orders, atr_i)
        return self._session_gate(orders, getattr(bar, "ts", None))


def build():
    return MESA5_Portfolio()
