# -*- coding: utf-8 -*-
"""セッション制御ライブラリ（LocalEngine 常設・プラットフォーム提供）。

Pine の KengetsuLib に相当する Python 側の単一ソース。各戦略はこれを `import session_lib` で
使い、**戦略 ZIP には同梱しない**（LocalEngine が提供＝一元管理・跨ぎ無し）。runtime は
strategy_loader が import パスに載せ、dev(Builder) は BT ランナーが app/feed を載せて解決する。

責務＝「いつ約定してよいか」だけを per-bar・先読みなしで判定（TradingView と同一シーケンス）:
  - cutoff      : セッション終了 offset 分前以降＝新規・決済とも約定不可。
  - block_new   : この足の注文は次足＝cutoff 約定になる（新規破棄・建ち注文キャンセル）。
  - pre_no_hold : この足のセッションは「持ち越し不可」（週末/祝日/大納会/SQ）の直前。
  - force_close : 持ち越し不可セッションの「約定可能な最後の足」＝ここで成行 flat。

カレンダー（決め打ちなし・全部外部 JSON/CSV）:
  - セッション時刻＝`data/session_hours.json`（era 対応：日中/夜間 引け・制度変更込み）＋カットオフ。
  - SQ（取引最終日）＝`data/sq_calendar.json`（`sq_fetch` が JPX から生成）。
  - 祝日/大納会＝`_market_hours`（market_Calendar.csv）。未導入の素コピーでは週末のみにフォールバック。

flags() は ts と interval/offset とカレンダーだけで決まる純関数＝BT(offline)・warmup・ライブで同一。
"""
from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from pathlib import Path

# ── dual-context import（runtime=パッケージ / dev=sys.path 直）──
try:                                              # 祝日・大納会判定（あれば使う）
    from . import _market_hours as _mh
except ImportError:                               # pragma: no cover
    try:
        import _market_hours as _mh  # type: ignore
    except ImportError:
        _mh = None
try:
    from .logger import log_message
except ImportError:                               # pragma: no cover
    try:
        from logger import log_message  # type: ignore
    except ImportError:
        def log_message(*a, **k):  # type: ignore
            pass

DATA_DIR = Path(__file__).resolve().parents[2] / "data"   # = N225LocalEngine/data
HOURS_PATH = DATA_DIR / "session_hours.json"
SQ_PATH = DATA_DIR / "sq_calendar.json"

DEFAULT_OFFSET_MIN = 30
# 3Split の建ち注文 ID（cutoff 窓でキャンセル）＋保護ストップ。
DEFAULT_EXIT_IDS = ("TP1_L", "TP2_L", "TP1_S", "TP2_S", "PSTOP")

_hours: dict | None = None
_sq_dates: set | None = None
_calendar_loaded = False


def refresh() -> None:
    """カレンダー/SQ/時刻 更新後に呼ぶ（キャッシュ破棄）。"""
    global _hours, _sq_dates, _calendar_loaded
    _hours = _sq_dates = None
    _calendar_loaded = False


def _load_hours() -> dict:
    global _hours
    if _hours is None:
        try:
            _hours = json.loads(HOURS_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            log_message(f"session_lib: session_hours.json 読込失敗→現行 era 既定: {e}", target="info")
            _hours = {"default_offset_min": 30, "offset_min_by_interval": {},
                      "regimes": [{"from": "1900-01-01", "day_open": "08:45", "day_close": "15:45",
                                   "night_open": "17:00", "night_close": "06:00"}]}
    return _hours


def _sq_set() -> set:
    global _sq_dates
    if _sq_dates is None:
        ds = set()
        try:
            obj = json.loads(SQ_PATH.read_text(encoding="utf-8"))
            for e in obj.get("entries", []):
                ds.add(datetime.fromisoformat(e["last_trading_day"]).date())
        except Exception:
            pass
        _sq_dates = ds
    return _sq_dates


def _t(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _to_dt(ts):
    """ts を datetime に頑健変換（datetime / pd.Timestamp / numpy.datetime64 / 文字列 を統一）。

    ★重要：numpy.datetime64 を datetime.fromisoformat(str(...)) に通すと 'YYYY-...Txx:xx:xx.000000000'
    （ナノ秒9桁）で Python 3.10 が解析失敗→None→gating 無効、という静かな抜けが起きる。offline は
    pd.Timestamp（datetime 派生）を渡すが run_pine/warmup_replay/一部 live は numpy.datetime64 を渡すため、
    ここで吸収して **どの入力でもセッション判定が同一**になるようにする（BT≡live≡warmup の一致条件）。
    """
    if isinstance(ts, datetime):
        return ts
    if ts is None:
        return None
    try:
        import pandas as pd                         # BT/engine 環境に常在（遅延 import で素環境も劣化動作）
        t = pd.Timestamp(ts)
        return None if pd.isna(t) else t.to_pydatetime()
    except Exception:
        try:
            return datetime.fromisoformat(str(ts))
        except Exception:
            return None


def _regime_for(d) -> dict:
    """日付 d に有効な regime（from <= d の最新）。"""
    regimes = _load_hours().get("regimes", [])
    best = None
    for r in regimes:
        try:
            frm = datetime.fromisoformat(r["from"]).date()
        except Exception:
            continue
        if d >= frm and (best is None or frm > best[0]):
            best = (frm, r)
    return best[1] if best else regimes[-1]


def offset_for(interval_min) -> int:
    h = _load_hours()
    by = h.get("offset_min_by_interval", {})
    return int(by.get(str(int(interval_min)), h.get("default_offset_min", DEFAULT_OFFSET_MIN)))


def _is_no_trade_day(d) -> bool:
    if _mh is not None:
        return _mh.is_no_trade_day(d)
    return d.weekday() >= 5                         # フォールバック＝週末のみ


def _night_held(d) -> bool:
    if _mh is not None:
        return _mh._night_session_held(d)
    return d.weekday() < 5                          # フォールバック＝平日は夜間あり（大納会無視）


def _ensure_calendar() -> None:
    global _calendar_loaded
    if not _calendar_loaded:
        if _mh is not None:
            try:
                _mh.load_calendar()
            except Exception:
                pass
        _calendar_loaded = True


def _session_close(ts: datetime, reg: dict):
    """ts が属するセッションの引け datetime と種別。場間は (None, None)。"""
    t = ts.time()
    d0 = ts.replace(hour=0, minute=0, second=0, microsecond=0)
    d_open, d_close = _t(reg["day_open"]), _t(reg["day_close"])
    n_open, n_close = _t(reg["night_open"]), _t(reg["night_close"])
    if d_open <= t < d_close:                                   # 日中
        return d0.replace(hour=d_close.hour, minute=d_close.minute), "day"
    if t >= n_open:                                             # 当日夜間 → 翌日 night_close
        return (d0 + timedelta(days=1)).replace(hour=n_close.hour, minute=n_close.minute), "night"
    if t < n_close:                                            # 早朝＝前日夜間の続き → 当日 night_close
        return d0.replace(hour=n_close.hour, minute=n_close.minute), "night"
    return None, None                                          # 場間


def flags(ts, interval_min: float, offset_min: int | None = None) -> dict:
    """per-bar・先読みなしのセッション可否フラグ。offset_min 省略時は interval から表引き。"""
    _ensure_calendar()
    ts = _to_dt(ts)                                  # datetime/Timestamp/numpy.datetime64/str を統一
    none = {"cutoff": False, "block_new": False, "pre_no_hold": False,
            "force_close": False, "mins_to_end": None}
    if ts is None:
        return none
    if offset_min is None:
        offset_min = offset_for(interval_min)
    reg = _regime_for(ts.date())
    close, kind = _session_close(ts, reg)
    if close is None:
        return none
    mins = (close - ts).total_seconds() / 60.0
    cutoff = mins <= offset_min
    block_new = mins <= offset_min + interval_min
    if kind == "night":
        pre = _is_no_trade_day(close.date())                   # 翌朝引け先が休場＝週末/祝日
    else:                                                      # day
        # 大納会 or SQ取引最終日 or 「翌日が休場（週末/祝日）」＝夜間に持ち越さず日中で flat。
        # ★翌日休場時に日中で閉じる＝金曜夜間がデータ上 消失/短縮（3連休前など）でも週末跨ぎを確実に防ぐ
        #   （calendar のみ・先読みなし）。通常の平日夜間（翌日が立会日）は従来どおり持ち越し可。
        nxt = close.date() + timedelta(days=1)
        pre = (not _night_held(close.date())) or (close.date() in _sq_set()) or _is_no_trade_day(nxt)
    force_close = pre and (offset_min + interval_min < mins <= offset_min + 2 * interval_min)
    return {"cutoff": cutoff, "block_new": block_new, "pre_no_hold": pre,
            "force_close": force_close, "mins_to_end": mins}


def gate(orders, fl: dict, position_size, exit_ids=DEFAULT_EXIT_IDS) -> list:
    """flags の可否で注文を間引き/強制flat（MESA5 で検証済みロジック）。"""
    ms = int(position_size)
    if fl["force_close"] and ms != 0:
        return [{"t": "close", "qty": None, "comment": "weekend_sq"}]
    if fl["pre_no_hold"] and fl["block_new"] and ms != 0:       # 安全網（取りこぼし対策）
        return [{"t": "close", "qty": None, "comment": "weekend_sq_late"}]
    if fl["block_new"]:
        return [{"t": "cancel", "id": x} for x in exit_ids] if ms != 0 else []
    if fl["force_close"]:                                       # flat の force 足 → 新規だけ抑止
        return [o for o in orders if o.get("t") != "entry"]
    return orders
