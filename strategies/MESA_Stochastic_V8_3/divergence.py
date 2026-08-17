# -*- coding: utf-8 -*-
"""弱気ダイバージェンス検知（純関数）— V8 で追加。

オシレーターの直近2山（局所max > thresh）で「価格高値は切り上げ・オシレーター山は切り下げ」
が成立している区間を True とする（次の山が立つまで持続）。判定は確定バーのみ＝因果的。

用途＝順張り枝（T1）のゲートのみ。逆張り枝には適用しない
（div 圏の逆張りは PF1.9 と弱いが年により勝ち越し・除外/減量とも equity 悪化を実測
＝内在コスト。devlog 2026-07-02 参照）。
"""
from __future__ import annotations

import numpy as np


def compute_bear_divergence(ms: np.ndarray, high: np.ndarray,
                            thresh: float = 0.4, window: int = 150) -> np.ndarray:
    """弱気ダイバージェンス持続フラグ。

    山の確定: ms[j] が局所max（ms[j]>ms[j-1] かつ ms[j]>=ms[j+1]）かつ ms[j]>thresh。
    山の価格: 山バー近傍（j-3..j）の最高値。
    直近山とその前の山が window バー以内で「価格↑・ms山↓」なら、以後次の山まで True。
    thresh/window は 0/0.3/0.4/0.5 × 50/150 の8通りで同方向を確認済（感度に鈍感）。
    """
    ms = np.asarray(ms, dtype=float)
    high = np.asarray(high, dtype=float)
    n = len(ms)
    bear = np.zeros(n, dtype=bool)
    last_peak = None          # (bar, ms値, 価格高値)
    cur = False
    for i in range(2, n):
        j = i - 1             # 山は1バー遅れで確定
        if ms[j] > ms[j - 1] and ms[j] >= ms[i] and ms[j] > thresh:
            ph = high[max(0, j - 3):j + 1].max()
            if last_peak is not None and j - last_peak[0] <= window:
                cur = (ph > last_peak[2]) and (ms[j] < last_peak[1])
            else:
                cur = False
            last_peak = (j, ms[j], ph)
        bear[i] = cur
    return bear
