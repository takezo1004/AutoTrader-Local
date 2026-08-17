# -*- coding: utf-8 -*-
"""MESA オシレーター後段（純関数）— SuperSmoother→stoch→SuperSmoother→[-1,1]+67%慣性。

DT/MESA ファミリー共通。入力 x（MESA は hl2、DT は RSI(HP)）に対して同一機械を通す。
移植元＝dt_hp_rsi_bt._ss_stoch_inertia（mesa_engine.mesa_stochastic の HP 以降と完全同一）。
係数は Pine 厳密一致（a1 は 3.14159 リテラル、b1 は π=2·asin(1) を使用）。
"""
from __future__ import annotations

import numpy as np

PI = 2 * np.arcsin(1.0)


def ss_stoch_inertia(x: np.ndarray, length: int = 20, ss_period: int = 10) -> np.ndarray:
    """SuperSmoother(10) → length 本ストキャス → SuperSmoother → [-1,1]＋67%慣性 → ±0.999 clamp。

    Pine L321-346 / dt_hp_rsi_bt._ss_stoch_inertia と一致。
    """
    x = np.asarray(x, dtype=float)
    n = len(x)
    a1 = np.exp(-1.414 * 3.14159 / ss_period)
    b1 = 2 * a1 * np.cos(1.414 * PI / ss_period)
    c2 = b1
    c3 = -a1 * a1
    c1 = 1 - c2 - c3

    filt = np.zeros(n)
    for i in range(1, n):
        filt[i] = c1 * (x[i] + x[i - 1]) / 2.0 + c2 * filt[i - 1] + c3 * filt[i - 2]

    stoc = np.zeros(n)
    for i in range(n):
        start = max(0, i - length + 1)
        w = filt[start: i + 1]
        if len(w) < 2:
            stoc[i] = 0.5
            continue
        hc = w.max()
        lc = w.min()
        stoc[i] = 0.5 if hc == lc else (filt[i] - lc) / (hc - lc)

    mesa_stoc = np.zeros(n)
    for i in range(1, n):
        mesa_stoc[i] = c1 * (stoc[i] + stoc[i - 1]) / 2.0 + c2 * mesa_stoc[i - 1] + c3 * mesa_stoc[i - 2]

    ms = np.zeros(n)
    for i in range(1, n):
        raw = 0.33 * 2 * (mesa_stoc[i] - 0.5) + 0.67 * ms[i - 1]
        ms[i] = 0.999 if raw > 0.99 else (-0.999 if raw < -0.99 else raw)
    return ms
