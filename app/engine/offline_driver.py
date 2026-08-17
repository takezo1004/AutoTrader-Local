# -*- coding: utf-8 -*-
"""オフライン driver（内蔵BT）— 履歴 OHLC バーで PineBroker を駆動（D6・golden 一致）。

StrategyBuilder `_engine/backtest.py` の run_pine / run_pine_fast / summarize を無傷ベンダリング。
  - run_pine      : live と同一 on_bar（バッファ再計算）で回す（BT≡実機の確認用）。
  - run_pine_fast : precompute で全系列1回計算 → step(A,i)。**正本 BT**（run_pine と結果同一・高速）。
  - summarize     : トレード単位（trade_id）の成績（PF/勝率/純益/DD/平均保有/年別）。

リアルタイム driver（tick）は別（app/engine/realtime_broker.py・M3）。両者とも PineBroker を母体に
同一ロジックで駆動する（D6 二刀エンジン）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .contract import Bar
from .pine_broker import PineBroker, PT_TO_JPY, TICK_JPY


def _run_pine(strategy, df: pd.DataFrame, get_orders) -> pd.DataFrame:
    """Pine ブローカーで戦略を回す共通ドライバ（get_orders(i,bar)→注文リスト）。"""
    strategy.reset()
    qpe = int(getattr(strategy, "qty_per_entry", 0)) or \
        int(getattr(strategy, "cfg", {}).get("qty_per_entry", 3) if hasattr(strategy, "cfg") else 3)
    bk = PineBroker(qty_per_entry=qpe, tick=TICK_JPY)   # 呼値5円へ丸め＝realtime と同一（二刀の等価性）
    o = df["open"].to_numpy(float); h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float); c = df["close"].to_numpy(float)
    ts = df.index.to_numpy()
    n = len(df)
    for i in range(n):
        # Phase A1: 前バー発注の成行を当バー始値で約定
        bk._exec_pending_market(o[i], i, ts[i])
        # Phase A2: 建ち注文（指値/逆指値）を当バーでイントラバー約定（建玉バー当日は不可）
        if bk.pos_dir != 0 and i > bk.entry_bar:
            bk._fill_resting(o[i], h[i], l[i], i, ts[i])
        # 戦略へ Pine globals 相当を渡す（次の decide が読む）
        strategy.position_size = bk.position_size
        strategy.position_avg_price = bk.avg_price
        strategy.entry_bar = bk.entry_bar
        strategy.bars_since_entry = (i - bk.entry_bar) if bk.entry_bar >= 0 else -1
        # Phase B: 戦略決定 → 注文登録
        orders = get_orders(i, (o[i], h[i], l[i], c[i], ts[i]))
        bk.submit(orders)
    # データ終端: 建玉が残れば最終足 close で強制決済（end_of_data）
    if bk.pos_dir != 0 and bk.pos_qty > 0:
        bk._reduce(c[n - 1], bk.pos_qty, n - 1, ts[n - 1], "end_of_data")
    return pd.DataFrame(bk.fills)


def run_pine(strategy, df: pd.DataFrame) -> pd.DataFrame:
    """TV 忠実約定で戦略を回す（live と同一 on_bar・バッファ再計算）。"""
    def get(i, bar_tuple):
        o, h, l, c, t = bar_tuple
        return strategy.on_bar(Bar(ts=t, open=o, high=h, low=l, close=c,
                                   volume=0.0)) or []
    return _run_pine(strategy, df, get)


def run_pine_fast(strategy, df: pd.DataFrame) -> pd.DataFrame:
    """TV 忠実約定の高速パス（precompute で全系列1回計算 → step(A,i) で注文）。run_pine と結果同一。"""
    A = strategy.precompute(df)
    def get(i, bar_tuple):
        return strategy.step(A, i) or []
    return _run_pine(strategy, df, get)


def summarize(fills: pd.DataFrame) -> dict:
    """トレード単位（trade_id でグループ）の成績。golden compute_summary_v3 と同方式。"""
    if fills is None or len(fills) == 0:
        return dict(n=0, win=0.0, pf=0.0, pnl=0, dd=0, avg_hold=0.0, yearly={})
    tp = fills.groupby("trade_id")["pnl_pt"].sum()
    first = fills.groupby("trade_id").first()
    wins = tp[tp > 0].sum()
    losses = tp[tp <= 0].sum()
    pf = abs(wins / losses) if losses < 0 else float("inf")
    cum = tp.cumsum()
    dd = float((cum - cum.cummax()).min())
    hold = (fills["exit_bar"] - fills["entry_bar"])
    yr = pd.to_datetime(first["entry_ts"]).dt.year
    yearly = {}
    for y in sorted(yr.unique()):
        s = tp[yr.values == y]
        w = s[s > 0].sum(); ll = s[s <= 0].sum()
        yearly[int(y)] = (len(s), round(abs(w / ll) if ll < 0 else 99.0, 2))
    return dict(
        n=int(len(tp)),
        win=round(100 * (tp > 0).mean(), 1),
        pf=round(float(pf), 2),
        pnl=int(tp.sum() * PT_TO_JPY),
        dd=int(dd * PT_TO_JPY),
        avg_hold=round(float(hold.mean()), 1),
        yearly=yearly,
    )
