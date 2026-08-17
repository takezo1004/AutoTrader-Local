# -*- coding: utf-8 -*-
"""60分 ZigZag v2（MTF・純関数）— Pine `f_zigzag_v2`（正本＝zigzag60_v2.pine）と同一遷移。

★旧名 zigzag.py から改名（2026-08-02）。旧 MESA 系フォルダの zigzag.py は v2 なし（旧仕様）で、
  同名だと仕様違いを混同するため、本戦略では Pine 正本に合わせ zigzag60_v2.py とする。
  v2 ＝ 転換確認（confirm_bars）＋ 上昇脚の起点割れ対称化（fix_sym）。confirm_bars=0 かつ
  fix_sym=False で旧仕様と1円まで一致（比較基準として保全）。

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
    cand: float | None = None      # 保留中の転換候補の極値（v2・None = 候補なし）
    cand_age: int = 0              # 候補が立ってからの経過バー数（v2）


def zigzag_step(state: ZigZagState, high_history: np.ndarray, low_history: np.ndarray,
                bars_back_window: int, threshold: float, threshold_max: float,
                confirm_bars: int = 0, fix_sym: bool = False) -> ZigZagState:
    """1 バー分の ZigZag 状態遷移。Pine f_zigzag / f_zigzag_v2 と等価。現在バー = *_history[-1]。

    v2（スパイク改善・2026-07-27）。正本＝`work/zigzag60_v2.pine`。
      fix_sym      : 上昇脚の起点割れを対称形に直す（low >= xlow → low <= xlow）
      confirm_bars : 転換の確認本数。反転条件が成立した足で即転換せず候補として保留し、
                     confirm_bars 本もったら確定。保留中に脚が新極値を付けたら候補を破棄。
                     ピボット価格は保留中の極値（真の高安）を使うので頂点の位置はズレない。
    ★ confirm_bars=0 かつ fix_sym=False で旧 V8_3 と完全一致（比較基準）。
    """
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
    cand = state.cand
    cand_age = state.cand_age
    has_cand = cand is not None

    if dir_ == 1:
        retr = xhigh - low
        # 修正A: 起点割れ。旧は low >= xlow（押し幅ゼロでも成立＝スパイク源）
        brk = (low <= xlow) if fix_sym else (low >= xlow)
        # 転換条件（3経路とも同じ扱い。threshold_max 超えも例外にしない）
        seed = (zl and retr > threshold) or (zl and brk) or (retr > threshold_max)
        newhi = high >= xhigh

        if has_cand and newhi:
            # 上昇脚が新高値 ＝ あの押しは否定された（スパイクだった）。候補を捨てて脚を継続
            new_zhigh = high
            updata = True
            cand = None
            cand_age = 0
        elif has_cand:
            if low < cand:
                cand = low
            cand_age += 1
            if cand_age >= confirm_bars:
                new_zlow = cand          # ピボット価格は保留中の最安値＝真の安値
                new_dir = -1
                cand = None
                cand_age = 0
        elif seed:
            if confirm_bars <= 0:
                new_zlow = low           # 確認なし＝旧と同じ即時転換
                new_dir = -1
            else:
                cand = low
                cand_age = 0
        elif newhi:
            new_zhigh = high
            updata = True

    elif dir_ == -1:
        rally = high - xlow
        # 下降側の起点割れは旧から正しい（起点の高値を上抜き＝脚の否定）。修正不要
        brk = high >= xhigh
        seed = (zh and rally > threshold) or (zh and brk) or (rally > threshold_max)
        newlo = low <= xlow

        if has_cand and newlo:
            new_zlow = low
            updata = True
            cand = None
            cand_age = 0
        elif has_cand:
            if high > cand:
                cand = high
            cand_age += 1
            if cand_age >= confirm_bars:
                new_zhigh = cand
                new_dir = 1
                cand = None
                cand_age = 0
        elif seed:
            if confirm_bars <= 0:
                new_zhigh = high
                new_dir = 1
            else:
                cand = high
                cand_age = 0
        elif newlo:
            new_zlow = low
            updata = True

    dirchanged = new_dir != dir_
    return ZigZagState(zhigh=new_zhigh, zlow=new_zlow, dir=new_dir, updata=updata,
                       dirchanged=dirchanged, cand=cand, cand_age=cand_age)


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
                       length: int = 7, threshold: float = 200.0, threshold_max: float = 500.0,
                       confirm_bars: int = 0, fix_sym: bool = False,
                       threshold_series: np.ndarray | None = None,
                       threshold_max_series: np.ndarray | None = None) -> dict:
    """Pine [S10] 60m MTF ZigZag。5分/15分バー上で動的 lookback により計算。

    confirm_bars / fix_sym は v2（スパイク改善）。既定は旧 V8_3 と完全一致。詳細＝zigzag_step。

    threshold_series / threshold_max_series（任意・2026-07-27 追加）:
      閾値を「絶対円の固定値」ではなくバーごとの候補系列（例 close×k / ATR×m）で与える。
      **脚の開始時（dirchanged が発生したバー）の値を採り、その脚が終わるまで固定して保持する**
      ＝脚の途中で閾値を変えない（価格が動かなくても閾値の伸縮だけでピボットが確定するのを防ぐ）。
      None（既定）＝従来どおりスカラ固定値を全期間で使う。NaN のバーはスカラ固定値へフォールバック。

    Returns: zhigh_60m, zlow_60m, dir_60m, updata_60m, dirchanged_60m, newbar_60m, len_bars_60m,
             threshold_applied, threshold_max_applied（各バーで実際に使われた閾値）。
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

    thr_app = np.full(n, float(threshold))
    thrmax_app = np.full(n, float(threshold_max))

    def _pick(series, i, fallback):
        """脚の開始バーの候補値。NaN/範囲外は固定値へフォールバック。"""
        if series is None or i >= len(series):
            return fallback
        v = float(series[i])
        return fallback if (np.isnan(v) or v <= 0) else v

    cur_thr = _pick(threshold_series, 0, float(threshold))
    cur_thr_max = _pick(threshold_max_series, 0, float(threshold_max))

    state = ZigZagState(zhigh=high[0], zlow=low[0], dir=1)
    for i in range(n):
        thr_app[i] = cur_thr
        thrmax_app[i] = cur_thr_max
        if i == 0:
            zhigh_arr[i] = state.zhigh
            zlow_arr[i] = state.zlow
            dir_arr[i] = state.dir
            continue
        state = zigzag_step(state, high[: i + 1], low[: i + 1],
                            bars_back_window=int(len_bars[i]),
                            threshold=cur_thr, threshold_max=cur_thr_max,
                            confirm_bars=confirm_bars, fix_sym=fix_sym)
        zhigh_arr[i] = state.zhigh
        zlow_arr[i] = state.zlow
        dir_arr[i] = state.dir
        updata_arr[i] = state.updata
        dirchanged_arr[i] = state.dirchanged
        # 新しい脚の開始 → ここで閾値を確定し、次の転換までこの値を保持する
        if state.dirchanged and threshold_series is not None:
            cur_thr = _pick(threshold_series, i, float(threshold))
            cur_thr_max = _pick(threshold_max_series, i, float(threshold_max))

    return {
        "zhigh_60m": zhigh_arr, "zlow_60m": zlow_arr, "dir_60m": dir_arr,
        "updata_60m": updata_arr, "dirchanged_60m": dirchanged_arr,
        "newbar_60m": newbar, "len_bars_60m": len_bars,
        "threshold_applied": thr_app, "threshold_max_applied": thrmax_app,
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
