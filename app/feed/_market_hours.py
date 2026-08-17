"""[vendored] 市場取引時間・祝日判定（N225SignalTrader/src/utils/market_hours.py のベンダリング）。

元は config.py（dotenv）/ loguru に依存していたが、ベンダリングで自己完結化：
  - config の時刻定数はインライン化（値は config.py と同一）。
  - loguru は clone feed の log_message に差し替え。
  - 取引停止日カレンダー（market_Calendar.csv）は共有 AppData を参照（存在しなければ土日のみ判定）。
session_manager が使う load_calendar() / is_trading_time() を提供する。
"""
import csv
from datetime import datetime, time, timedelta
from pathlib import Path

try:                                              # dual-context（パッケージ / dev=sys.path 直）
    from .logger import log_message
except ImportError:                               # pragma: no cover
    try:
        from logger import log_message  # type: ignore
    except ImportError:
        def log_message(*a, **k):  # type: ignore
            pass

# ★セッション時刻の【唯一の正本】（[[feedback_no_hardcoding]] の許容形＝定数化＋根拠コメント）。
#   LocalEngine 内でセッション時刻リテラルを書いてよいのはここだけ。is_market_open / get_bar_times /
#   板寄せ判定は全てこの定数を参照し、値を複製しない。元は config.py（dotenv）の値をインライン化。
#   JPX の制度変更（例: 夜間 16:30→17:00=2024-11-05・日中引け 15:15→15:45）時は、ここ1箇所だけ直せば
#   足窓・板寄せ・場況判定が一括追従する（複製があると静かにズレ＝損益直結）。
TRADE_START_TIME = "08:45"
TRADE_END_TIME   = "15:45"
NIGHT_START_TIME = "17:00"
NIGHT_END_TIME   = "06:00"
LOW_LIQUIDITY_START = "02:00"
LOW_LIQUIDITY_END   = "06:00"
# 取引停止日カレンダー（プロジェクト内・自己完結。共有 AppData 参照を撤去・2026-06-17）。
# 生成/更新はダッシュボードのカレンダー更新機能で行う予定（将来追加・JPX スクレイプ）。
MARKET_CALENDAR_PATH = str(Path(__file__).resolve().parents[2] / "data" / "market_Calendar.csv")


def _parse_time(t: str) -> time:
    h, m = t.split(":")
    return time(int(h), int(m))


_DAY_START     = _parse_time(TRADE_START_TIME)
_DAY_END       = _parse_time(TRADE_END_TIME)
_NIGHT_START   = _parse_time(NIGHT_START_TIME)
_NIGHT_END     = _parse_time(NIGHT_END_TIME)
_LOW_LIQ_START = _parse_time(LOW_LIQUIDITY_START)
_LOW_LIQ_END   = _parse_time(LOW_LIQUIDITY_END)

# ── セッション境界（公開・市場時間の単一ソース）──
# ohlc_processor のローソク足窓/板寄せ判定がこれを参照し、時刻を決め打ちしない（[[feedback_no_hardcoding]]）。
DAY_START, DAY_END     = _DAY_START, _DAY_END
NIGHT_START, NIGHT_END = _NIGHT_START, _NIGHT_END

_NO_TRADE_DATES: set[tuple[int, int, int]] = set()

# ★年末年始の恒久休場（JPX「当分の間、祝日取引を実施しない」＝1/1 元日・1/2,1/3 年始休業・12/31 年末休業）。
#   可変祝日（建国記念日・海の日等）はカレンダー(_NO_TRADE_DATES)が正本。ここは年をまたいでも
#   構造的に固定の休場だけを持ち、カレンダー未更新（翌年分を未取得）でも年末年始を確実に閉場にする
#   安全網（市場/データで変わる値の決め打ちではなく、制度上固定の構造定数＋根拠コメント）。
_YEAR_BOUNDARY_CLOSED: set[tuple[int, int]] = {(1, 1), (1, 2), (1, 3), (12, 31)}


def load_calendar() -> None:
    """market_Calendar.csv を読み込んで取引停止日をキャッシュ（無ければ土日のみ判定）。"""
    global _NO_TRADE_DATES
    _NO_TRADE_DATES = set()

    csv_path = Path(MARKET_CALENDAR_PATH)
    if not csv_path.exists():
        log_message(f"⚠️ market_Calendar.csv が見つかりません: {csv_path}（祝日判定は土日のみ）")
        return

    try:
        with open(csv_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if "実施しない" in row.get("status", ""):
                    date_str = row.get("date", "").strip()
                    try:
                        dt = datetime.strptime(date_str, "%Y/%m/%d")
                        _NO_TRADE_DATES.add((dt.year, dt.month, dt.day))
                    except ValueError:
                        pass
        log_message(f"カレンダー読み込み完了: {len(_NO_TRADE_DATES)} 日間の取引停止日を登録")
    except Exception as e:
        log_message(f"⚠️ market_Calendar.csv 読み込みエラー: {e}")


def is_no_trade_day(dt) -> bool:
    """その暦日の【デイ・セッション(8:45-15:45)】が立たない＝休場日か。
    週末／年末年始の恒久休場／カレンダーの「実施しない」祝日。
    ※ナイトは日付をまたぐ（前営業日 17:00→翌 6:00）ため、これは「その日のデイが休みか」の
      判定であって市場 OPEN 判定ではない。OPEN 判定は is_open_at() を使うこと。"""
    d = dt.date() if isinstance(dt, datetime) else dt
    if d.weekday() >= 5:                                   # 土日
        return True
    if (d.month, d.day) in _YEAR_BOUNDARY_CLOSED:          # 年末年始 恒久休場
        return True
    return (d.year, d.month, d.day) in _NO_TRADE_DATES     # カレンダーの「実施しない」祝日


def _day_session_held(d) -> bool:
    """日付 d のデイ・セッション(8:45-15:45)が開くか。祝日取引「実施する」日も平日も True。"""
    return not is_no_trade_day(d)


def _is_year_last_trading_day(d) -> bool:
    """d が大納会（その年の最終取引日）か。大納会は【日中のみ・ナイト・セッションを行わない】(JPX)。
    判定＝12月のデイ立会日で、同年内に d より後のデイ立会日が存在しない（年末年始休場の手前）。"""
    if d.month != 12 or not _day_session_held(d):
        return False
    e = d + timedelta(days=1)
    while e.year == d.year:                                # 同年内に後続のデイ立会日が無ければ大納会
        if _day_session_held(e):
            return False
        e += timedelta(days=1)
    return True


def _night_session_held(d) -> bool:
    """日付 d のナイト・セッション(17:00→翌6:00)が開くか。
    デイが立つ日のみ。ただし大納会はナイトを行わない（JPX 確認済）。
    祝日取引「実施する」日・通常営業日は夜間も通常どおり。「実施しない」祝日や週末の【前営業日】の
    夜間は、金→土と同様にその営業日のナイトとして翌朝6:00まで立つ＝ここで True を返す。"""
    return _day_session_held(d) and not _is_year_last_trading_day(d)


def is_open_at(dt: datetime) -> bool:
    """★厳密な市場 OPEN 判定（ナイトが日付をまたぐ構造・カレンダー・大納会を反映）。
    その時刻を所有する取引日にセッションが立つかで判定する：
      - 日中 08:45–15:45 … 当日のデイ・セッション
      - 夜間前半 17:00–24:00 … 当日のナイト・セッション
      - 夜間後半 00:00–06:00 … 【前日】のナイト・セッション（前営業日の夜間の続き）
      - それ以外（06:00–08:45 / 15:45–17:00）… 場間＝閉場
    旧実装は早朝帯を当日の暦日で判定し、金→土・祝日前→休場日の早朝にナイトを取りこぼして
    ろうそく足生成が止まっていた（損益直結のバグ）。本実装は所有取引日で判定して是正する。"""
    t = dt.time()
    if _DAY_START <= t < _DAY_END:
        return _day_session_held(dt.date())                       # 日中（当日）
    if t >= _NIGHT_START:
        return _night_session_held(dt.date())                     # 夜間前半（当日のナイト）
    if t < _NIGHT_END:
        return _night_session_held((dt - timedelta(days=1)).date())  # 夜間後半（前日のナイト）
    return False                                                  # 場間（6:00-8:45 / 15:45-17:00）


def is_trading_time(dt: datetime) -> bool:
    """後方互換エイリアス（旧名）。実体は厳密判定 is_open_at()。"""
    return is_open_at(dt)


def is_low_liquidity(dt: datetime) -> bool:
    t = dt.time()
    return _LOW_LIQ_START <= t < _LOW_LIQ_END


def get_session_name(dt: datetime) -> str:
    t = dt.time()
    if _DAY_START <= t < _DAY_END:
        return "日中"
    if t >= _NIGHT_START or t < _NIGHT_END:
        return "夜間"
    return "時間外"
