"""
ohlc_storage.py  (n225tradingAI2 の OHLCStorage を忠実流用・検査済み)
15分足キャッシュ + parquet 永続化 + 確定フラグ。
適合点: OhlcTcpSender を no-op スタブ化 (AI は OHLC を消費する側で再送不要)、logger を自己完結、
        ファイルパスを本フォルダ data/ に。
検査メモ:
  - update_candle が cache_df を無制限 concat → 長時間で肥大。get_latest(n) で読むので実害小だが、
    起動時 MAX_CANDLE_COUNT トリムに加え runtime でも末尾 MAX に保つよう微修正(肥大防止)。
  - _save_to_file_worker は毎回 parquet 全読み→全書きで O(n) (本数増で重い)。実証規模(数百本/日)では許容。
"""
import os
import shutil
import threading
from datetime import datetime
from pathlib import Path

import pandas as pd

from .logger import log_message

MAX_CANDLE_COUNT = 500
MONTHS_KEEP = 6           # ★蓄積ストア(parquet)の保持期間＝直近6ヶ月（最終足から遡る・無制限肥大を防ぐ）
# ★ライブ確定足の蓄積は「このプロジェクト内」に保存（自己完結・別製品/共有ストアと跨がない）。
#   保存先 = N225LocalEngine/data/ohlc_live.parquet（controller.parquet_path / 内蔵BT と同一ファイルに統一）。
#   旧版は外部 n225tradingAI2/data/ohlc_data.parquet を参照していたが、製品分離のため撤去（2026-06-17）。
DATA = Path(__file__).resolve().parents[2] / "data"   # = N225LocalEngine/data
DATA.mkdir(parents=True, exist_ok=True)
DEFAULT_PARQUET = str(DATA / "ohlc_live.parquet")
# 配布同梱の「6ヶ月BTシード」置き場（distribution の sync_local.ps1 が用意）。
SEED_PARQUET = str(DATA / "seed" / "ohlc_live.parquet")


def _restore_seed_if_needed(file_path):
    """初回起動の保険：live ストアが無く、配布同梱シードがある時だけ live へ展開する。
    ★既存の live があれば何もしない＝アップデートでユーザーの蓄積足を絶対に上書きしない。
    既定の live ストア(DEFAULT_PARQUET)に対してのみ働く（BT 等で別パスを指したときは対象外）。"""
    try:
        if (file_path == DEFAULT_PARQUET
                and not os.path.exists(file_path)
                and os.path.exists(SEED_PARQUET)):
            shutil.copy2(SEED_PARQUET, file_path)
            log_message(f"初回シード展開: seed → {os.path.basename(file_path)}", target="info")
    except Exception as e:
        log_message(f"シード展開スキップ: {e}", target="info")


class _NullSender:
    """OhlcTcpSender スタブ (AI は OHLC を再送しないので何もしない)。"""
    def send_ohlc(self, candle):
        return


class OHLCStorage:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.file_path = DEFAULT_PARQUET
            cls._instance.cache_df = None
            cls._instance.state = {"new_bar": 1, "last_bar": None}
            cls._instance.bar_completed = False
            cls._instance.lock = threading.Lock()
            cls._instance.ohlc_sender = _NullSender()
            cls._instance.cache_df = cls._instance.load_historical_data()
        return cls._instance

    def set_file_path(self, file_path):
        self.file_path = file_path
        self.cache_df = self.load_historical_data()

    def load_historical_data(self):
        _restore_seed_if_needed(self.file_path)   # 初回のみシード展開（既存があれば no-op）
        if self.file_path and os.path.exists(self.file_path):
            try:
                df = pd.read_parquet(self.file_path)
                if not df.empty:
                    df = df.iloc[-MAX_CANDLE_COUNT:] if len(df) > MAX_CANDLE_COUNT else df
                    log_message(f"ヒストリカルデータ読込: {len(df)} 本", target="info")
                    return df.reset_index(drop=True)
            except Exception as e:
                # ★絶対にファイルを消さない(ポート元は os.remove していたが、pyarrow 欠落等の
                #   一時的読込失敗で正常な蓄積ストアを破壊する事故が起きるため撤去)。空で続行。
                log_message(f"Parquet 読込エラー(ファイルは保持): {e}", target="info")
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])

    def get_last_bar(self):
        if self.cache_df is None or self.cache_df.empty:
            return None
        return self.cache_df.iloc[-1]

    def get_latest_time(self):
        if self.cache_df is None or self.cache_df.empty:
            return None
        lt = self.cache_df["datetime"].iloc[-1]
        return pd.to_datetime(lt) if isinstance(lt, str) else lt

    def add_to_candle(self, candle):
        """確定足をキャッシュ+parquet に追加 (+ 再送は no-op)。"""
        try:
            threading.Thread(target=self._save_to_file_worker, args=(candle,), daemon=True).start()
            self.ohlc_sender.send_ohlc(candle)
            self.update_candle(candle)
        except Exception as e:
            log_message(f"add_to_candle エラー: {e}")

    def update_candle(self, candle):
        self.cache_df = pd.concat([self.cache_df, pd.DataFrame([candle])], ignore_index=True)
        # 検査修正: runtime 肥大防止に末尾 MAX_CANDLE_COUNT に保つ
        if len(self.cache_df) > MAX_CANDLE_COUNT:
            self.cache_df = self.cache_df.iloc[-MAX_CANDLE_COUNT:].reset_index(drop=True)

    def _save_to_file_worker(self, finalized_bar):
        try:
            with self.lock:
                df = pd.DataFrame([finalized_bar])
                if os.path.exists(self.file_path):
                    existing = pd.read_parquet(self.file_path)
                    out = pd.concat([existing, df], ignore_index=True)
                else:
                    out = df
                # ★dedup（datetime 後勝ち）＋6ヶ月ローリング（最終足から遡る）。無制限肥大を防ぐ。
                out["datetime"] = pd.to_datetime(out["datetime"])
                out = (out.drop_duplicates(subset="datetime", keep="last")
                          .sort_values("datetime").reset_index(drop=True))
                if len(out):
                    cutoff = out["datetime"].iloc[-1] - pd.DateOffset(months=MONTHS_KEEP)
                    out = out[out["datetime"] >= cutoff].reset_index(drop=True)
                out.to_parquet(self.file_path, index=False, compression="snappy", engine="pyarrow")
        except Exception as e:
            # ★読込/保存失敗でファイルは消さない（不変条件）。空書きもしない。
            log_message(f"parquet 保存エラー(ファイルは保持): {e}")

    def mark_bar_completed(self):
        self.bar_completed = True

    def reset_bar_completed(self):
        self.bar_completed = False

    def is_bar_completed(self) -> bool:
        return self.bar_completed

    def get_latest(self, n=None):
        if self.cache_df is None or self.cache_df.empty:
            return pd.DataFrame()
        return self.cache_df.copy() if n is None else self.cache_df.tail(n).copy()
