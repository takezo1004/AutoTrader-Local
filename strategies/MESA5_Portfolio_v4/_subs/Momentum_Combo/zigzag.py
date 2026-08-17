# -*- coding: utf-8 -*-
"""ZigZag（MTF・純関数）— Pine [S04]-[S10] 忠実翻訳。

移植元＝N225StrategyBuilder/python_engine/zigzag.py（compute_60m_zigzag 一式）
       ＋ build_master_dataset.extract_pivots_from_zigzag。
60分 MTF ZigZag を 15分バー上で動的 lookback により計算する。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def highest_bars_offset(values: np.ndarray, length: int) -> int:
    """直近 length 本の最高値の相対 offset（0=現在・同値タイは現在バー寄り=新しい側を採用）。

    Pine f_highestbars 厳密一致（2026-06-24 修正）。Pine は `for i=0 to len-1`（新→古）走査＋狭義 `>` で
    同値タイは最も新しい側（i 小=現在バー寄り）を最高値とする。旧実装は古→新走査で「古い側」を採っており、
    高安が同値になる足（フラット足・キリ番）で zh/zl が Pine と反転し ZZ60 の転換判定がずれていた。
    """
    if len(values) < length:
        return 0
    highest_value = -1e10
    highest_index = 0
    for i in range(0, length):          # 新(i=0=現在)→古。狭義 > なので同値タイは新しい側を保持＝Pine 一致
        v = values[-1 - i]
        if v > highest_value:
            highest_value = v
            highest_index = i
    return -highest_index


def lowest_bars_offset(values: np.ndarray, length: int) -> int:
    """直近 length 本の最安値の相対 offset（0=現在・同値タイは現在バー寄り=新しい側を採用）。

    Pine f_lowestbars 厳密一致（2026-06-24 修正）。highest_bars_offset と対称。
    """
    if len(values) < length:
        return 0
    lowest_value = 1e10
    lowest_index = 0
    for i in range(0, length):          # 新(i=0=現在)→古。狭義 < なので同値タイは新しい側を保持＝Pine 一致
        v = values[-1 - i]
        if v < lowest_value:
            lowest_value = v
            lowest_index = i
    return -lowest_index


@dataclass
class ZigZagState:
    zhigh: float
    zlow: float
    dir: int
    updata: bool = False
    dirchanged: bool = False


def zigzag_step(state: ZigZagState, high_history: np.ndarray, low_history: np.ndarray,
                bars_back_window: int, threshold: float, threshold_max: float) -> ZigZagState:
    """1 バー分の ZigZag 状態遷移。Pine f_zigzag と等価。現在バー = *_history[-1]。"""
    high = high_history[-1]
    low = low_history[-1]
    xhigh = state.zhigh
    xlow = state.zlow
    dir_ = state.dir

    zh = highest_bars_offset(high_history, bars_back_window) == 0
    zl = lowest_bars_offset(low_history, bars_back_window) == 0

    new_zhigh = xhigh
    new_zlow = xlow
    new_dir = dir_
    updata = False

    if dir_ == 1:
        if (zl and xhigh - low > threshold) or (zl and low >= xlow) or (xhigh - low > threshold_max):
            new_zlow = low
            new_dir = -1
        elif high >= xhigh:
            new_zhigh = high
            updata = True
        else:
            new_zlow = xlow
    elif dir_ == -1:
        if (zh and high - xlow > threshold) or (zh and high >= xhigh) or (high - xlow > threshold_max):
            new_zhigh = high
            new_dir = 1
        elif low <= xlow:
            new_zlow = low
            updata = True
        else:
            new_zhigh = xhigh

    dirchanged = new_dir != dir_
    return ZigZagState(zhigh=new_zhigh, zlow=new_zlow, dir=new_dir, updata=updata, dirchanged=dirchanged)


def detect_newbar_mtf(index, minutes: int) -> np.ndarray:
    """Pine ta.change(time(str(minutes))) 忠実＝minutes 分足の新バー開始フラグ。

    Pine の time('60') は取引所の正時アラインの60分足開始時刻を返す（実データで確認＝N225 の
    60分足は 08:00/09:00/… の正時始まり）。ta.change(time('60')) はその開始時刻が変わる足で true：
      ① 正時境界（minute % minutes == 0）で発火、かつ
      ② セッション開始足でも発火（例：日中08:45 は 08:00 足に属し、前夜の足から time('60') が変化）。
    ＝「正時グリッド ∪ セッション開始足」の和集合。セッション開始はデータのギャップ>バー間隔で
    導出（決め打ちなし・時代非依存）。
    """
    index = pd.DatetimeIndex(index)
    n = len(index)
    out = np.zeros(n, dtype=bool)
    if n == 0:
        return out
    grid = np.asarray(index.minute % minutes == 0)                 # ① 正時境界
    tmin = index.values.astype("int64") // 60_000_000_000          # 各バーの epoch 分
    sess = np.zeros(n, dtype=bool)
    sess[0] = True
    if n > 1:
        d = np.diff(tmin)
        pos = d[d > 0]
        vals, counts = np.unique(pos, return_counts=True)
        bar_int = int(vals[counts.argmax()]) if len(vals) else minutes   # 規則的バー間隔（最頻値=15）
        sess[1:] = d > bar_int                                       # ② セッション開始
    return grid | sess


def compute_dynamic_lookback(newbar_flags: np.ndarray, occurrence: int) -> np.ndarray:
    """各バーで occurrence 個前の newbar 発生 bar_index を返す（Pine ta.valuewhen 相当）。"""
    n = len(newbar_flags)
    out = np.full(n, np.nan)
    history: list[int] = []
    for i in range(n):
        if newbar_flags[i]:
            history.insert(0, i)
        out[i] = history[occurrence] if len(history) > occurrence else 0
    return out


def compute_60m_zigzag(high: np.ndarray, low: np.ndarray, index: pd.DatetimeIndex,
                       length: int = 7, threshold: float = 200.0, threshold_max: float = 500.0) -> dict:
    """Pine [S10] 60m MTF ZigZag。5分/15分バー上で動的 lookback により計算。

    Returns: zhigh_60m, zlow_60m, dir_60m, updata_60m, dirchanged_60m, newbar_60m, len_bars_60m。
    """
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    n = len(high)
    newbar = detect_newbar_mtf(index, 60)
    bi = compute_dynamic_lookback(newbar, occurrence=length - 1)
    bar_indices = np.arange(n)
    len_bars = np.maximum(bar_indices - bi.astype(int) + 1, 1)

    zhigh_arr = np.full(n, np.nan)
    zlow_arr = np.full(n, np.nan)
    dir_arr = np.zeros(n, dtype=np.int8)
    updata_arr = np.zeros(n, dtype=bool)
    dirchanged_arr = np.zeros(n, dtype=bool)

    state = ZigZagState(zhigh=high[0], zlow=low[0], dir=1)
    for i in range(n):
        if i == 0:
            zhigh_arr[i] = state.zhigh
            zlow_arr[i] = state.zlow
            dir_arr[i] = state.dir
            continue
        state = zigzag_step(state, high[: i + 1], low[: i + 1],
                            bars_back_window=int(len_bars[i]),
                            threshold=threshold, threshold_max=threshold_max)
        zhigh_arr[i] = state.zhigh
        zlow_arr[i] = state.zlow
        dir_arr[i] = state.dir
        updata_arr[i] = state.updata
        dirchanged_arr[i] = state.dirchanged

    return {
        "zhigh_60m": zhigh_arr, "zlow_60m": zlow_arr, "dir_60m": dir_arr,
        "updata_60m": updata_arr, "dirchanged_60m": dirchanged_arr,
        "newbar_60m": newbar, "len_bars_60m": len_bars,
    }


def extract_pivots_from_zigzag(dirchanged: np.ndarray, zhigh: np.ndarray,
                               zlow: np.ndarray, dir_arr: np.ndarray) -> dict:
    """dirchanged 系列から p1/p2/p3 価格・index・age_bars を抽出。build_master_dataset と一致。"""
    n = len(dirchanged)
    p1_price = np.full(n, np.nan); p1_index = np.full(n, np.nan)
    p2_price = np.full(n, np.nan); p2_index = np.full(n, np.nan)
    p3_price = np.full(n, np.nan); p3_index = np.full(n, np.nan)
    age_bars = np.zeros(n, dtype=np.int32)

    pivots: list[tuple[float, int]] = []
    last_change_idx = 0
    for i in range(n):
        if i > 0 and dirchanged[i]:
            prev_dir = dir_arr[i - 1]
            pivot_val = zhigh[i - 1] if prev_dir == 1 else zlow[i - 1]
            if not np.isnan(pivot_val):
                pivots.insert(0, (pivot_val, i - 1))
                pivots = pivots[:10]
            last_change_idx = i
        if pivots:
            p1_price[i], p1_index[i] = pivots[0]
        if len(pivots) >= 2:
            p2_price[i], p2_index[i] = pivots[1]
        if len(pivots) >= 3:
            p3_price[i], p3_index[i] = pivots[2]
        age_bars[i] = i - last_change_idx

    return {
        "p1_price": p1_price, "p1_index": p1_index,
        "p2_price": p2_price, "p2_index": p2_index,
        "p3_price": p3_price, "p3_index": p3_index,
        "age_bars": age_bars,
    }
