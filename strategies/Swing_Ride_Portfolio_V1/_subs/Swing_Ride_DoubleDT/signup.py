# -*- coding: utf-8 -*-
"""signup 状態機械とクロス検出（純関数）— V7_1/V7_7 仕様。

移植元＝build_master_dataset._self_crossover/_crossover ＋ dt_hp_rsi_bt._signup_machine。
オシレーター値 ms（≈±1）から change_up/down・over/under・signup を再現（下流完全一致）。
"""
from __future__ import annotations

import numpy as np


def crossover(s: np.ndarray, level: float) -> np.ndarray:
    """Pine ta.crossover(s, level): s[i-1] <= level AND s[i] > level。"""
    s = np.asarray(s, dtype=float)
    out = np.zeros(len(s), dtype=bool)
    for i in range(1, len(s)):
        if s[i - 1] <= level and s[i] > level:
            out[i] = True
    return out


def crossunder(s: np.ndarray, level: float) -> np.ndarray:
    """Pine ta.crossunder(s, level): s[i-1] >= level AND s[i] < level。"""
    s = np.asarray(s, dtype=float)
    out = np.zeros(len(s), dtype=bool)
    for i in range(1, len(s)):
        if s[i - 1] >= level and s[i] < level:
            out[i] = True
    return out


def self_crossover(s: np.ndarray) -> np.ndarray:
    """Pine ta.crossover(ms, ms[1]) 等価: s[i-1] <= s[i-2] AND s[i] > s[i-1]（山谷の上転換）。"""
    s = np.asarray(s, dtype=float)
    out = np.zeros(len(s), dtype=bool)
    for i in range(2, len(s)):
        if s[i - 1] <= s[i - 2] and s[i] > s[i - 1]:
            out[i] = True
    return out


def self_crossunder(s: np.ndarray) -> np.ndarray:
    """Pine ta.crossunder(ms, ms[1]) 等価: s[i-1] >= s[i-2] AND s[i] < s[i-1]（山谷の下転換）。"""
    s = np.asarray(s, dtype=float)
    out = np.zeros(len(s), dtype=bool)
    for i in range(2, len(s)):
        if s[i - 1] >= s[i - 2] and s[i] < s[i - 1]:
            out[i] = True
    return out


def build_signal_columns(ms: np.ndarray) -> dict:
    """ms から change_up/down・over(±-0.8)・under(±0.8)・signup（V7_1 状態機械）を再現。

    build_master_dataset.compute_mesa_features / dt_hp_rsi_bt._signup_machine と一致。
    ※ simulate_v3 はループ内で signup を再計算するため、ここの signup は検証/参考用。
      simulate_v3 が ds から読むのは mesa_stochastic / change_up / change_down のみ。
    """
    ms = np.asarray(ms, dtype=float)
    n = len(ms)
    change_up = self_crossover(ms)
    change_down = self_crossunder(ms)
    over = crossover(ms, -0.8)
    under = crossunder(ms, 0.8)

    signup = np.zeros(n, dtype=np.int8)
    cur = 0
    for i in range(n):
        if cur == 0:
            if change_up[i]:
                cur = 1
            elif change_down[i]:
                cur = -1
        if cur == 1 and over[i]:
            cur = 0
        elif cur == -1 and under[i]:
            cur = 0
        signup[i] = cur

    return {
        "mesa_stochastic": ms,
        "change_up": change_up,
        "change_down": change_down,
        "over": over,
        "under": under,
        "signup": signup,
    }
