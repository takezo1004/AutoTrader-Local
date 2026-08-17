# -*- coding: utf-8 -*-
"""内蔵BT データ供給 — ローカル蓄積 parquet ＋ 外部 CSV マージ（詳細仕様 §F・D11）。

- 蓄積 parquet（full-time ストア）を基本に、不足分は外部 CSV をマージ。
- 重複 datetime は **CSV 優先（上書き）が既定**（公式 CSV はクリーンな正本・蓄積は tick 集計近似）。
- BT は半年程度（直近市場で十分）＝ window() で「直近 months か月 ＋ warmup」を切り出す。
- 戻りは datetime 昇順・index=datetime・列 open/high/low/close/volume の DataFrame。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_COLS = ["open", "high", "low", "close", "volume"]


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """datetime を index に・列を OHLCV に正規化（datetime は列でも index でも可）。"""
    df = df.copy()
    if "datetime" in df.columns:
        df = df.set_index("datetime")
    idx = pd.DatetimeIndex(pd.to_datetime(df.index))
    # ★TradingView CSV は時刻が +09:00（tz-aware）。蓄積ストア（naive JST 実時刻）と揃えるため
    #   tz を外して naive JST にする（+09:00 の壁時計＝JST なので値は不変）。kabu は naive のまま。
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    df.index = idx
    df.index.name = "datetime"
    for c in _COLS:
        if c not in df.columns:
            df[c] = 0.0
    df = df[_COLS].astype(float)
    return df[~df.index.duplicated(keep="last")].sort_index()


def load_parquet(path) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return pd.DataFrame(columns=_COLS).rename_axis("datetime")
    return _normalize(pd.read_parquet(p))


def load_csv(path) -> pd.DataFrame:
    """15分足 CSV を読む（kabu=Shift-JIS / TV=UTF-8 を自動吸収・列名は位置で解釈）。"""
    p = Path(path)
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            raw = pd.read_csv(p, encoding=enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    else:
        raise ValueError(f"CSV エンコーディングを判別できません: {p}")
    # 1列目=日時, 2..5=OHLC（kabu/TV とも先頭5列がこの並び）。
    # ★出来高（2026-07-02）：TV エクスポートは「出来高」インジの列がチャート上の指標の後ろに
    #   付くため位置が不定。**列名（Volume/出来高・大小無視）で探し、無ければ従来どおり6列目**。
    #   指標列が挟まった CSV でも指標値を出来高と誤読しない（DataPipeline datastore.load_tv_csv と同方式）。
    out = raw.iloc[:, :5].copy()
    out.columns = ["datetime", "open", "high", "low", "close"][:out.shape[1]]
    vcol = next((c for c in raw.columns
                 if str(c).strip().lower() in ("volume", "vol", "出来高")), None)
    # 6列目フォールバックは「ヘッダが無名（OHLC を名前で判別できない）」場合のみ。
    # 名前付きヘッダ（TV/kabu）で出来高列が見つからない＝出来高インジ未搭載の TV エクスポート等
    # → 6列目は指標値の可能性が高いので誤読せず 0 とする（★出来高インジは載せたままにする運用）。
    _names = {str(c).strip().lower() for c in raw.columns}
    _named_ohlc = ({"open", "high", "low", "close"} <= _names) or ({"始値", "高値", "安値", "終値"} <= _names)
    if vcol is None and not _named_ohlc and raw.shape[1] >= 6:
        vcol = raw.columns[5]                     # 無名ヘッダのみ従来互換＝6列目
    out["volume"] = pd.to_numeric(raw[vcol], errors="coerce").values[:len(out)] \
        if vcol is not None else 0.0
    return _normalize(out)


def merge(parquet_df: pd.DataFrame, csv_dfs, prefer: str = "csv") -> pd.DataFrame:
    """蓄積 ＋ 外部 CSV をマージ。prefer='csv'（既定）＝重複 datetime は CSV 優先。"""
    if isinstance(csv_dfs, pd.DataFrame):
        csv_dfs = [csv_dfs]
    csv_all = pd.concat([c for c in csv_dfs if c is not None and len(c)], axis=0) \
        if csv_dfs else pd.DataFrame(columns=_COLS).rename_axis("datetime")
    # 後勝ち（keep='last'）になるよう、優先する側を後ろに concat する。
    if prefer == "csv":
        merged = pd.concat([parquet_df, csv_all], axis=0)
    else:
        merged = pd.concat([csv_all, parquet_df], axis=0)
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    return merged


def window(df: pd.DataFrame, months: int = 6, warmup_bars: int = 300) -> pd.DataFrame:
    """直近 months か月 ＋ 先頭 warmup_bars 本を切り出す（半年BT用・指標の暖機を含める）。"""
    if df is None or len(df) == 0:
        return df
    last = df.index[-1]
    cutoff = last - pd.DateOffset(months=months)
    start_pos = int(df.index.searchsorted(cutoff))
    start_pos = max(0, start_pos - warmup_bars)
    return df.iloc[start_pos:].copy()


def build(parquet_path=None, csv_paths=None, months: int = 6, warmup_bars: int = 300,
          prefer: str = "csv") -> pd.DataFrame:
    """蓄積＋CSV をマージし半年窓を返す（内蔵BT のワンショット供給）。"""
    pq = load_parquet(parquet_path) if parquet_path else \
        pd.DataFrame(columns=_COLS).rename_axis("datetime")
    csvs = [load_csv(p) for p in (csv_paths or [])]
    merged = merge(pq, csvs, prefer=prefer)
    return window(merged, months=months, warmup_bars=warmup_bars)
