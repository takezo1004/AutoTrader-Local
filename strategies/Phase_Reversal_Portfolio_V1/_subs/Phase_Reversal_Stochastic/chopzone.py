# -*- coding: utf-8 -*-
"""Chop Zone — 純関数（TradingView ビルトイン指標の忠実な移植）。

原典＝ユーザーが自身のチャートから提供した Pine v6 の実物（2026-08-07 に照合済み）。
推測ではなく、そのコードをそのまま写している。

    avg  = hlc3
    span = 25 / (直近30本の高値の最高 − 直近30本の安値の最低) * 直近30本の安値の最低
    ema  = EMA(close, 34)                    ← ★元は close（hlc3 ではない。hlc3 は分母だけ）
    y    = (ema[1] − ema) / avg * span
    角度 = round(180 * acos(1 / sqrt(1 + y^2)) / pi)      ← ★整数に四捨五入される
    符号 = y > 0（EMA が下向き）なら −、それ以外は ＋

原典は acos で書いているが、x 方向の歩幅が 1 に固定されているため
    c = sqrt(1 + y^2),  acos(1/c) = atan(|y|)
と恒等。ここでは数値的に安定な atan で計算する（値は完全に一致する）。

★角度が整数に丸められるので、色のしきい値 0.71 / 2.14 / 3.57 / 5 は
  実質「整数の度数そのもの」になる。9 色 ＝ 整数 −5〜+5 の区切り：

      ≧+5 / +4 / +3 / +1〜+2 / 0 / −1〜−2 / −3 / −4 / ≦−5

★助走本数 = 34（EMA）と 30（正規化窓）の大きい方。それ以前は NaN を返す。
  Pine の ta.ema は最初から値を出すが、立ち上がりは信用しないので NaN で潰す。

★符号の向き（EMA が上向きなら正）は原典どおり。良し悪しのラベルは貼らない。
"""
from __future__ import annotations

import numpy as np

EMA_LENGTH = 34          # 原典の既定値
SPAN_PERIODS = 30        # 正規化窓（ta.highest/ta.lowest の長さ）

# 帯の定義（原典の色分岐と 1 対 1）。key は表示順。
ZONE_ORDER = ["+5以上", "+4", "+3", "+1〜+2", "0", "−1〜−2", "−3", "−4", "−5以下"]
ZONE_COLOR = {
    "+5以上": "シアン", "+4": "緑", "+3": "薄緑", "+1〜+2": "ティール",
    "0": "黄(チョップ)",
    "−1〜−2": "薄橙", "−3": "橙", "−4": "ピンク", "−5以下": "濃赤",
}


def ema(x: np.ndarray, length: int) -> np.ndarray:
    """Pine の ta.ema と同じ再帰 EMA（初期値＝最初の値）。"""
    x = np.asarray(x, dtype=float)
    n = len(x)
    out = np.full(n, np.nan)
    if n == 0:
        return out
    alpha = 2.0 / (length + 1.0)
    prev = x[0]
    out[0] = prev
    for i in range(1, n):
        if not np.isfinite(x[i]):
            out[i] = prev
            continue
        prev = alpha * x[i] + (1.0 - alpha) * prev
        out[i] = prev
    return out


def rolling_max(x: np.ndarray, length: int) -> np.ndarray:
    """直近 length 本の最大（窓が埋まらない位置は NaN）。"""
    x = np.asarray(x, dtype=float)
    n = len(x)
    out = np.full(n, np.nan)
    for i in range(length - 1, n):
        out[i] = float(np.max(x[i - length + 1: i + 1]))
    return out


def rolling_min(x: np.ndarray, length: int) -> np.ndarray:
    """直近 length 本の最小（窓が埋まらない位置は NaN）。"""
    x = np.asarray(x, dtype=float)
    n = len(x)
    out = np.full(n, np.nan)
    for i in range(length - 1, n):
        out[i] = float(np.min(x[i - length + 1: i + 1]))
    return out


def compute_chop_angle(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                       ema_length: int = EMA_LENGTH,
                       periods: int = SPAN_PERIODS) -> np.ndarray:
    """Chop Zone の角度（整数・度）。上向きが正。助走ぶんは NaN。"""
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    n = len(close)
    out = np.full(n, np.nan)
    if n == 0:
        return out

    avg = (high + low + close) / 3.0
    hh = rolling_max(high, periods)
    ll = rolling_min(low, periods)
    with np.errstate(divide="ignore", invalid="ignore"):
        rng = hh - ll
        span = np.where(rng > 0, 25.0 / np.where(rng > 0, rng, np.nan) * ll, np.nan)

    e = ema(close, ema_length)
    y = np.full(n, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        y[1:] = (e[:-1] - e[1:]) / np.where(avg[1:] != 0, avg[1:], np.nan) * span[1:]

    deg = np.degrees(np.arctan(np.abs(y)))
    ang = np.round(deg)
    out = np.where(y > 0, -ang, ang)

    warm = max(ema_length, periods)          # 立ち上がりは信用しない
    out[:warm] = np.nan
    return out


def to_zone(angle: float) -> str:
    """整数角度 → 帯名。判定不能は "-"。原典の色分岐と同じ切り方。"""
    if angle is None or not np.isfinite(angle):
        return "-"
    a = float(angle)
    if a >= 5:
        return "+5以上"
    if a >= 3.57:
        return "+4"
    if a >= 2.14:
        return "+3"
    if a >= 0.71:
        return "+1〜+2"
    if a <= -5:
        return "−5以下"
    if a <= -3.57:
        return "−4"
    if a <= -2.14:
        return "−3"
    if a <= -0.71:
        return "−1〜−2"
    return "0"


def to_zones(angles: np.ndarray) -> np.ndarray:
    """配列版。"""
    return np.array([to_zone(a) for a in np.asarray(angles, dtype=float)], dtype=object)


# ---------------------------------------------------------------- 向きの取り出し
_RANK_CACHE: dict = {}      # 同じ系列・同じ窓を何度も計算しないため（掃引で効く）


def rolling_rank(x: np.ndarray, window: int) -> np.ndarray:
    """直近 window 本の中での順位（0〜1・自分を含む）。窓が埋まるまで NaN。

    しきい値を持たないので、時代にも価格水準にも依存しない（volswitch.py と同じ考え方）。
    """
    x = np.asarray(x, dtype=float)
    n = len(x)
    # ★キーは系列全体の要約で作る（2026-08-08 強化）。先頭/末尾 50 本だけだと、
    #   帯のもとになる系列を差し替えて比べるとき（fine_src）に別系列へ誤ヒットしうる。
    key = (n, window, float(np.nansum(x)), float(np.nanstd(x)),
           int(np.isnan(x).sum()))
    hit = _RANK_CACHE.get(key)
    if hit is not None and len(hit) == n:
        return hit
    out = np.full(n, np.nan)
    for i in range(window - 1, n):
        if not np.isfinite(x[i]):
            continue
        w = x[i - window + 1: i + 1]
        w = w[np.isfinite(w)]
        if len(w) < window // 2:
            continue
        out[i] = float((w <= x[i]).sum()) / float(len(w))
    # ★上限（2026-08-10）: live の on_bar はバッファが毎足変わり必ずキャッシュミスする
    #   ＝溜まる一方なので、一定件数で払う（BT 掃引での使い回しはキー数が少なく影響なし）。
    if len(_RANK_CACHE) > 64:
        _RANK_CACHE.clear()
    _RANK_CACHE[key] = out
    return out


def dir_from_sign(angle: np.ndarray) -> np.ndarray:
    """角度の符号そのもの（ビルトインの色分けと同じ 2 値）。0 は 0 のまま。"""
    a = np.asarray(angle, dtype=float)
    return np.where(np.isnan(a), 0, np.sign(a)).astype(int)


def compute_band(angle: np.ndarray, window: int = 1000, k: int = 5) -> np.ndarray:
    """角度の順位を k 等分した帯番号 1〜k（第1＝最も下向き、第k＝最も上向き）。0＝判定不能。"""
    r = rolling_rank(np.asarray(angle, dtype=float), window)
    b = np.zeros(len(r), dtype=int)
    fin = np.isfinite(r)
    b[fin] = np.minimum((r[fin] * k).astype(int), k - 1) + 1
    return b


def dir_from_band(angle: np.ndarray, window: int = 1000, k: int = 5) -> np.ndarray:
    """直近 window 本の中での角度の順位を k 等分し、上位/下位の帯だけ向きを返す。

    k=5 なら 第4・第5 → +1、第1・第2 → −1、真ん中の 第3 → 0（＝どちらでもない）。
    ビルトインの ±5 度は日経225ミニ15分では 88.6% が両端に入ってしまい何も分けないため、
    分位で切り直す（決め打ち回避）。
    """
    b = compute_band(angle, window, k) - 1        # 0 起点に戻す（−1 は判定不能）
    out = np.zeros(len(b), dtype=int)
    out[b >= (k - (k // 2))] = 1          # k=5 なら第4・第5
    out[(b >= 0) & (b < (k // 2))] = -1   # k=5 なら第1・第2
    return out
