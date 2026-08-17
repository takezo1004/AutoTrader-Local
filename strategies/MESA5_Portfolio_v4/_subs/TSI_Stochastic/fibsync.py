# -*- coding: utf-8 -*-
"""FibSync（純関数）— V7_7 FibSync v2。移植元＝simulate_v7_7_fib_v2。

ZZ60 ピボットからの fib pullback・反転フラグ（slope/cross）・K 窓 OR・
下降側 dn_bottomed の新安値無効化（V7_8 hold 版）。
"""
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np


def compute_fib_pullback_v2(dir_60m: np.ndarray, dirchanged: np.ndarray, p1_price: np.ndarray,
                            high: np.ndarray, low: np.ndarray, close: np.ndarray) -> Dict[str, np.ndarray]:
    """up_fib/down_fib（swing 内位置 -1..+1）と slope・running 高安を計算。dir 転換まで frozen。"""
    high = np.asarray(high, dtype=float); low = np.asarray(low, dtype=float); close = np.asarray(close, dtype=float)
    n = len(close)
    up_fib = np.zeros(n); dn_fib = np.zeros(n)
    cur_low_arr = np.full(n, np.nan); cur_high_arr = np.full(n, np.nan)

    bottm = np.nan; top = np.nan; cur_high = np.nan; cur_low = np.nan
    trend_up = 0; trend_dn = 0; cur_up = 0.0; cur_dn = 0.0

    for i in range(n):
        if i > 0 and dirchanged[i] and dir_60m[i] == 1:
            trend_up = 1; trend_dn = 0; bottm = p1_price[i]; cur_high = high[i]
        elif i > 0 and dirchanged[i] and dir_60m[i] == -1:
            trend_dn = -1; trend_up = 0; top = p1_price[i]; cur_low = low[i]

        if trend_up == 1 and not np.isnan(bottm):
            if np.isnan(cur_high) or cur_high < high[i]:
                cur_high = high[i]
            diff = cur_high - bottm
            if diff > 0:
                cur_up = max(-1.0, min(1.0, 2 * (close[i] - bottm) / diff - 1))

        if trend_dn == -1 and not np.isnan(top):
            if np.isnan(cur_low) or cur_low > low[i]:
                cur_low = low[i]
            diff = top - cur_low
            if diff > 0:
                cur_dn = max(-1.0, min(1.0, 2 * (close[i] - cur_low) / diff - 1))

        up_fib[i] = cur_up; dn_fib[i] = cur_dn
        cur_low_arr[i] = cur_low; cur_high_arr[i] = cur_high

    up_slope = np.zeros(n); dn_slope = np.zeros(n)
    up_slope[1:] = np.diff(up_fib); dn_slope[1:] = np.diff(dn_fib)

    return {"up_fib": up_fib, "down_fib": dn_fib, "up_fib_slope": up_slope,
            "down_fib_slope": dn_slope, "cur_low": cur_low_arr, "cur_high": cur_high_arr}


def compute_reversal_flags(fib: np.ndarray, slope: np.ndarray, depth: float, K: int,
                           mode: str = "slope") -> Tuple[np.ndarray, np.ndarray]:
    """bottomed/topped を判定し直近 K バー OR を返す。mode="slope"（既定）/"cross"。"""
    fib = np.asarray(fib, dtype=float); slope = np.asarray(slope, dtype=float)
    n = len(fib)
    bottomed = np.zeros(n, dtype=bool); topped = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if mode == "cross":
            if fib[i] >= -depth and fib[i - 1] < -depth:
                bottomed[i] = True
            if fib[i] <= +depth and fib[i - 1] > +depth:
                topped[i] = True
        else:
            if slope[i] > 0 and slope[i - 1] <= 0 and fib[i - 1] < -depth:
                bottomed[i] = True
            if slope[i] < 0 and slope[i - 1] >= 0 and fib[i - 1] > +depth:
                topped[i] = True

    bottomed_K = np.zeros(n, dtype=bool); topped_K = np.zeros(n, dtype=bool)
    for i in range(n):
        lo = max(0, i - K + 1)
        bottomed_K[i] = bottomed[lo:i + 1].any()
        topped_K[i] = topped[lo:i + 1].any()
    return bottomed_K, topped_K


def compute_bottomed_held(fib: np.ndarray, slope: np.ndarray, extreme_low: np.ndarray,
                          depth: float, K: int) -> np.ndarray:
    """下降側 dn_bottomed の hold 版（V7_8）。底打ち発火後、新安値（extreme_low 更新）で即無効化。失効は K バー。"""
    fib = np.asarray(fib, dtype=float); slope = np.asarray(slope, dtype=float)
    extreme_low = np.asarray(extreme_low, dtype=float)
    n = len(fib)
    raw = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if slope[i] > 0 and slope[i - 1] <= 0 and fib[i - 1] < -depth:
            raw[i] = True

    held = np.zeros(n, dtype=bool)
    active = False; ref_low = np.nan; age = 0
    for i in range(n):
        if raw[i]:
            active = True; ref_low = extreme_low[i]; age = 0
        elif active:
            if not np.isnan(extreme_low[i]) and extreme_low[i] < ref_low - 1e-9:
                active = False
            else:
                age += 1
                if age >= K:
                    active = False
        held[i] = active
    return held
