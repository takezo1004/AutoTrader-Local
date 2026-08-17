# -*- coding: utf-8 -*-
"""生 DT オシレーター（原典 DTOSC・Robert C. Miner）— 純関数・自己完結。

★「生」の意味（2026-08-02 ユーザー指定）：DT_Stochastic 戦略の基軸（HP48→RSI→MESA パイプライン）
  ではなく、**原典の式そのまま**を使う。メサ仕様の加工（HP・SuperSmoother・慣性混合）は一切通さない。
  サブ指標の価値は MESA との平滑特性の「違い」（転回が少ない＝位相差の情報）にあるため。

原典式（High Probability Trading Strategies, R.C. Miner）:
  StochRSI = 100 × (RSI(n_rsi) − LLV(RSI, n_stoch)) / (HHV(RSI, n_stoch) − LLV(RSI, n_stoch))
  SK = MA(StochRSI, n_sk)        ← シグナル本体
  SD = MA(SK, n_sd)              ← シグナル線
  パラメータ組（時間足の目安）: (8,5,3,3) / (13,8,5,5) / (21,13,8,8) / (34,21,13,13)
  OB/OS の慣例 = 75 / 25。値域 0〜100。

注意：RSI は Wilder 平滑（Pine ta.rsi と同方式）。先頭の種は逐次平滑の初期値＝最初の変化量
（ウォームアップ後は Pine と収束一致。戦略採用時に Pine 対を作る段階で厳密照合する）。
"""
from __future__ import annotations

import numpy as np


def wilder_rsi(src: np.ndarray, n: int) -> np.ndarray:
    """Wilder RSI（Pine ta.rsi と同じ RMA 平滑・逐次）。先頭 n 本は収束途中の参考値。"""
    src = np.asarray(src, dtype=float)
    N = len(src)
    out = np.full(N, np.nan)
    if N < 2:
        return out
    alpha = 1.0 / n
    au = 0.0
    ad = 0.0
    for i in range(1, N):
        d = src[i] - src[i - 1]
        up = d if d > 0 else 0.0
        dn = -d if d < 0 else 0.0
        if i == 1:
            au, ad = up, dn
        else:
            au = alpha * up + (1 - alpha) * au
            ad = alpha * dn + (1 - alpha) * ad
        if au + ad == 0:
            out[i] = 50.0
        else:
            out[i] = 100.0 * au / (au + ad)
    return out


def _sma(x: np.ndarray, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        c = np.convolve(np.nan_to_num(x, nan=0.0), np.ones(n), mode="valid") / n
        # NaN を含む窓は NaN のまま（先頭のウォームアップ）
        valid = np.convolve((~np.isnan(x)).astype(float), np.ones(n), mode="valid") == n
        out[n - 1:] = np.where(valid, c, np.nan)
    return out


def _ema(x: np.ndarray, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    alpha = 2.0 / (n + 1)
    prev = np.nan
    for i, v in enumerate(x):
        if np.isnan(v):
            out[i] = prev
            continue
        prev = v if np.isnan(prev) else alpha * v + (1 - alpha) * prev
        out[i] = prev
    return out


def dt_osc(close: np.ndarray, rsi_len: int = 13, stoch_len: int = 8,
           sk_len: int = 5, sd_len: int = 5, ma: str = "sma") -> dict:
    """原典 DTOSC。Returns: {rsi, stoch_rsi, sk, sd}（0〜100）。"""
    close = np.asarray(close, dtype=float)
    rsi = wilder_rsi(close, rsi_len)
    n = len(close)
    st = np.full(n, np.nan)
    for i in range(n):
        s = max(0, i - stoch_len + 1)
        w = rsi[s: i + 1]
        w = w[~np.isnan(w)]
        if len(w) == 0 or np.isnan(rsi[i]):
            continue
        hh, ll = w.max(), w.min()
        st[i] = 50.0 if hh == ll else 100.0 * (rsi[i] - ll) / (hh - ll)
    f = _sma if ma == "sma" else _ema
    sk = f(st, sk_len)
    sd = f(sk, sd_len)
    return {"rsi": rsi, "stoch_rsi": st, "sk": sk, "sd": sd}
