"""
history_seed.py  (ヒストリカル足を OHLCStorage に warmup として投入)
==================================================================================
ライブの確定足だけでは特徴量のウォームアップ(連続≥300本)が足りない。
kabu Station CSV(直近・現月・約5日≈335本)を読み込み正規化して OHLCStorage の cache に
事前投入する → ライブ確定足が追記され「過去 + ライブ」が連続になる。

kabu CSV 形式(確定済): Shift-JIS / 日付,始値,高値,安値,終値,出来高 / 日時=YYYY/MM/dd HH:MM:SS / バー開始時刻。
★前提: ライブ開始直前に最新の kabu CSV をエクスポートし、最終足がライブ初足と隣接していること
   (gap があると warmup の連続性が壊れる)。セッション隙間(15:45-17:00 等)は master と同じ正常 gap。
"""
import pandas as pd
from pathlib import Path

from .ohlc_storage import OHLCStorage, MAX_CANDLE_COUNT
from .logger import log_message


def load_kabu_csv(path) -> pd.DataFrame:
    """kabu Station CSV → candle DataFrame(datetime/open/high/low/close/volume)。"""
    df = pd.read_csv(path, encoding="cp932")
    cols = ["datetime", "open", "high", "low", "close", "volume"]
    df = df.iloc[:, :6]
    df.columns = cols[:df.shape[1]]
    df["datetime"] = pd.to_datetime(df["datetime"], format="%Y/%m/%d %H:%M:%S")
    for c in ("open", "high", "low", "close"):
        df[c] = df[c].astype(float)
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
    else:
        df["volume"] = 0.0
    df = df.dropna(subset=["datetime"]).drop_duplicates(subset=["datetime"], keep="last")
    return df.sort_values("datetime").reset_index(drop=True)


def seed_storage_from_kabu(csv_path, storage: OHLCStorage = None, max_bars=MAX_CANDLE_COUNT) -> int:
    """kabu CSV を OHLCStorage の warmup cache として投入。戻り: 投入本数。"""
    storage = storage or OHLCStorage()
    p = Path(csv_path)
    if not p.exists():
        log_message(f"⚠️ warmup CSV が見つかりません: {p}")
        return 0
    hist = load_kabu_csv(p)
    # ★蓄積を活かす: 既存cache(parquetから読込んだ蓄積)とCSVをマージ(datetime重複は新しい方)。
    #   上書きしない → 貯めたリアルタイム足が消えない。直近 max_bars に保つ。
    existing = storage.cache_df if storage.cache_df is not None else pd.DataFrame(columns=hist.columns)
    merged = (pd.concat([existing, hist], ignore_index=True)
              .drop_duplicates(subset=["datetime"], keep="last")
              .sort_values("datetime")
              .tail(max_bars).reset_index(drop=True))
    storage.cache_df = merged               # ライブ確定足はこの後 update_candle で追記・parquetに永続化
    last = merged["datetime"].iloc[-1] if len(merged) else None
    log_message(f"✅ warmup マージ後 {len(merged)} 本 (CSV {len(hist)}本 ＋ 蓄積 {len(existing)}本, 最終 {last})")
    return len(merged)
