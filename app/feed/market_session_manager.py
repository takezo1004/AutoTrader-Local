"""
market_session_manager.py
プロジェクト共有の市場カレンダー/取引時間 (`N225SignalTrader/src/utils/market_hours.py`) を
そのまま使う薄いラッパー。新規にカレンダーを作らず共有版を再利用する。
  - 祝日/取引停止日 = %LOCALAPPDATA%/N225TradingSystem/data/market_Calendar.csv (共有・fetch_market_calendar.py が更新)
  - セッション = 日中 08:45–15:45 / 夜間 17:00–翌06:00 (config 由来)
ohlc_processor が期待する is_market_open() インターフェースを提供する。
"""
from datetime import datetime, timedelta

from .logger import log_message

# [vendored] 元: N225SignalTrader/src/utils/market_hours を sys.path 経由で import。
# ベンダリングで自己完結化 — 同梱の _market_hours（constants インライン・loguru 除去）を使う。
_shared_ok = False
try:
    from . import _market_hours as _mh
    _shared_ok = True
except Exception as e:
    log_message(f"⚠️ 同梱 market_hours を読めず session時刻のみで判定: {e}")


class MarketSessionManager:
    def __init__(self):
        if _shared_ok:
            try:
                _mh.load_calendar()
                log_message("✅ 共有市場カレンダー読込 (market_hours)")
            except Exception as e:
                log_message(f"⚠️ load_calendar 失敗(土日のみ判定): {e}")

    def is_market_open(self) -> bool:
        now = datetime.now()
        if _shared_ok:
            try:
                return bool(_mh.is_trading_time(now))
            except Exception as e:
                log_message(f"⚠️ is_trading_time エラー→fallback: {e}")
        return self._fallback(now)

    @staticmethod
    def _fallback(now: datetime) -> bool:
        """共有版 _market_hours が is_open_at で例外を出した時のみの保険（カレンダー無し・週末のみ）。
        ★セッション時刻は決め打ちしない（[[feedback_no_hardcoding]]）：正本 _market_hours の定数を使い、
        値を複製しない。正本ごと読めない（_shared_ok=False）場合は時刻の根拠が無いため安全側＝閉場扱い。
        ★ナイトが日付をまたぐ構造（早朝 0:00–6:00＝前営業日の夜間の続き）だけは保険でも正しく扱う：
          金→土の夜間は OPEN、日→月の早朝は CLOSED（前日が週末で夜間が無いため）。"""
        if not _shared_ok:
            return False                      # 正本が無い＝時刻の根拠なし → 閉場（spurious 判定を出さない）
        tt = now.time()

        def _weekday_open(d) -> bool:         # 週末でなければデイ/ナイトの母体あり（カレンダーは保険では見ない）
            return d.weekday() < 5

        if _mh.DAY_START <= tt < _mh.DAY_END:
            return _weekday_open(now.date())                       # 日中（当日）
        if tt >= _mh.NIGHT_START:
            return _weekday_open(now.date())                       # 夜間前半（当日のナイト）
        if tt < _mh.NIGHT_END:
            return _weekday_open((now - timedelta(days=1)).date())  # 夜間後半（前日のナイト）
        return False                                               # 場間
