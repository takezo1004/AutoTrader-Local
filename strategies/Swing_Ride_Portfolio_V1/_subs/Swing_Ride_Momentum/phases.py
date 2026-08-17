# -*- coding: utf-8 -*-
"""ZZ60 6局面 phase（純関数）— V7_7 仕様。移植元＝simulate_v7_7_fib。"""
from __future__ import annotations

import numpy as np

PHASES = ["peak", "down_start", "downtrend", "bottom", "up_start", "uptrend"]

# tuned_v2_strict（STRICT 採用フラグ）
STRICT_LONG = {
    "peak": True, "down_start": True, "downtrend": True,
    "bottom": True, "up_start": True, "uptrend": False,
}
STRICT_SHORT = {
    "peak": False, "down_start": False, "downtrend": False,
    "bottom": True, "up_start": False, "uptrend": False,
}


def compute_phase(dir_60m: np.ndarray, n_transition_bars: int) -> np.ndarray:
    """dir_60m（±1）から6局面を判定。転換瞬間=peak/bottom、転換後 N 本=○○中、以降=○○トレンド。"""
    dir_60m = np.asarray(dir_60m)
    n = len(dir_60m)
    phase = np.full(n, "none", dtype=object)
    bars_since_change = 0
    prev_d = 0
    for i in range(n):
        d = int(dir_60m[i])
        if d == 0:
            phase[i] = "none"
            bars_since_change = 0
            prev_d = d
            continue
        if i > 0 and d != prev_d and prev_d != 0:
            phase[i] = "peak" if d == -1 else "bottom"
            bars_since_change = 0
        else:
            bars_since_change += 1
            if d == 1:
                phase[i] = "up_start" if bars_since_change <= n_transition_bars else "uptrend"
            elif d == -1:
                phase[i] = "down_start" if bars_since_change <= n_transition_bars else "downtrend"
        prev_d = d
    return phase


def compute_phase_thresholds(phase_arr, upper_dict, lower_dict):
    """phase 別 over/under 閾値配列（既定 ±0.8）。"""
    n = len(phase_arr)
    ub = np.full(n, 0.8, dtype=float)
    lb = np.full(n, -0.8, dtype=float)
    for i in range(n):
        p = phase_arr[i]
        if p in upper_dict:
            ub[i] = upper_dict[p]
            lb[i] = lower_dict[p]
    return ub, lb
