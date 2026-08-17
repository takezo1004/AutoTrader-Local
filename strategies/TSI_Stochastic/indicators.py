# -*- coding: utf-8 -*-
"""指標（純関数）— Pine [S]/MESA エンジン忠実移植。

すべて入力→出力の純関数（内部可変状態なし）。np.ndarray を受け取り np.ndarray を返す。
移植元の検証済み数式（mesa_engine / dt_hp_rsi_bt / build_master_dataset）と数値一致。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PI = 2 * np.arcsin(1.0)


def hl2(high: np.ndarray, low: np.ndarray) -> np.ndarray:
    """Pine hl2 = (high + low) / 2。"""
    return (np.asarray(high, dtype=float) + np.asarray(low, dtype=float)) / 2.0


def highpass48(price: np.ndarray, period: int = 48) -> np.ndarray:
    """Ehlers 2極 HighPass フィルタ（周期48）。生価格をデトレンド。

    Pine (L314-315) / mesa_engine と同一式:
      alpha1 = (cos(0.707·2π/P)+sin(0.707·2π/P)-1)/cos(0.707·2π/P)
      HP[i]  = (1-alpha1/2)²·(p[i]-2p[i-1]+p[i-2]) + 2(1-alpha1)·HP[i-1] - (1-alpha1)²·HP[i-2]
    nz(初期)=0（i<2 は 0）。
    """
    p = np.asarray(price, dtype=float)
    n = len(p)
    hp = np.zeros(n)
    a1 = (np.cos(0.707 * 2 * PI / period) + np.sin(0.707 * 2 * PI / period) - 1) / np.cos(0.707 * 2 * PI / period)
    for i in range(2, n):
        hp[i] = ((1 - a1 / 2) ** 2) * (p[i] - 2 * p[i - 1] + p[i - 2]) \
            + 2 * (1 - a1) * hp[i - 1] - ((1 - a1) ** 2) * hp[i - 2]
    return hp


def pine_rsi(src: np.ndarray, length: int) -> np.ndarray:
    """Pine ta.rsi 等価（Wilder RMA = ewm alpha=1/n, adjust=False）。

    移植元＝dt_stoch_bt.pine_rsi と完全同一（pandas ewm セマンティクス）。
    ★`fillna(50.0)`：先頭 NaN を 50.0 に埋める（後段 SuperSmoother への NaN 伝播を防ぐ）。
    """
    s = pd.Series(np.asarray(src, dtype=float))
    delta = s.diff()
    up = delta.clip(lower=0.0)
    dn = (-delta).clip(lower=0.0)
    rma_up = up.ewm(alpha=1.0 / length, adjust=False).mean()
    rma_dn = dn.ewm(alpha=1.0 / length, adjust=False).mean()
    rs = rma_up / rma_dn.replace(0.0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    return rsi.fillna(50.0).to_numpy()


def ema(x: np.ndarray, span: int) -> np.ndarray:
    """Pine ta.ema 等価（α=2/(span+1)・adjust=False）。pandas ewm セマンティクス。"""
    return pd.Series(np.asarray(x, dtype=float)).ewm(span=span, adjust=False).mean().to_numpy()


def tsi(close: np.ndarray, long: int = 25, short: int = 13) -> np.ndarray:
    """TSI（True Strength Index）= モメンタムの二重EMA平滑 / |モメンタム|の二重EMA平滑 × 100。

    移植元＝dt_osc_volume._tsi（TSI_Stochastic の基軸オシレーター前段・HP は使わない）。
      mom=close差分 → EMA(EMA(mom,long),short) / EMA(EMA(|mom|,long),short) × 100。
    Pine: mom=close-close[1] / ta.ema(ta.ema(mom,tsi_long),tsi_short) … 100*num/den。
    """
    s = pd.Series(np.asarray(close, dtype=float))
    m = s.diff()
    e1 = m.ewm(span=long, adjust=False).mean().ewm(span=short, adjust=False).mean()
    e2 = m.abs().ewm(span=long, adjust=False).mean().ewm(span=short, adjust=False).mean()
    return (100 * e1 / e2.replace(0, np.nan)).fillna(0).to_numpy()


def sma(x: np.ndarray, n: int) -> np.ndarray:
    """Pine ta.sma 等価（単純移動平均・先頭 n-1 本は NaN）。"""
    return pd.Series(np.asarray(x, dtype=float)).rolling(n).mean().to_numpy()


def highest(x: np.ndarray, n: int) -> np.ndarray:
    """Pine ta.highest 等価（直近 n 本の最高値）。Donchian 上限などに。"""
    return pd.Series(np.asarray(x, dtype=float)).rolling(n).max().to_numpy()


def momentum(x: np.ndarray, n: int = 20) -> np.ndarray:
    """モメンタム = x − x[n]（先頭 n 本は 0 埋め）。Momentum_Combo の基軸ソース前段。

    移植元＝momentum_combo_bt.make_momentum_ds（mom=(hl2-hl2[N]).fillna(0)）。
    この後 HP(48) を掛けてから SS-stoch に通す（MESA 機械・HP は使う）。
    """
    s = pd.Series(np.asarray(x, dtype=float))
    return (s - s.shift(n)).fillna(0.0).to_numpy()


def cmf(high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray, n: int = 20) -> np.ndarray:
    """CMF（Chaikin Money Flow）= Σ(MFM×vol)/Σ(vol)（n本）。出来高系オシレーター。

    移植元＝dt_osc_volume.osc_cmf（CMF_Stochastic の基軸オシレーター前段・HP は使わない）。
      MFM=((close-low)-(high-close))/(high-low)。出来高（価格と別の情報源）を使う。
    """
    s = pd.DataFrame({
        "high": np.asarray(high, dtype=float), "low": np.asarray(low, dtype=float),
        "close": np.asarray(close, dtype=float), "volume": np.asarray(volume, dtype=float)})
    hl = (s["high"] - s["low"]).replace(0, np.nan)
    mfm = ((s["close"] - s["low"]) - (s["high"] - s["close"])) / hl
    mfv = (mfm * s["volume"]).fillna(0)
    return (mfv.rolling(n).sum() / s["volume"].rolling(n).sum().replace(0, np.nan)).fillna(0).to_numpy()


def atr14(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int = 14) -> np.ndarray:
    """Pine ta.atr(14) 等価（True Range の RMA）。build_master_dataset と一致させる用途。

    ※ 本戦略の golden は pkl の atr14 列を使う。ここは LocalEngine ライブ指標パス用の参考実装。
    """
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    n = len(c)
    tr = np.zeros(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    out = np.full(n, np.nan)
    alpha = 1.0 / length
    rma = 0.0
    for i in range(n):
        rma = tr[i] if i == 0 else alpha * tr[i] + (1 - alpha) * rma
        out[i] = rma
    return out
