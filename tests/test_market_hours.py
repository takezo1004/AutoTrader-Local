# -*- coding: utf-8 -*-
"""市場 OPEN 判定（_market_hours.is_open_at）とカレンダー取得（calendar_fetch）の厳密回帰。

背景（損益直結のバグ）: 旧実装は早朝 0:00–6:00 を【当日の暦日】で判定していたため、夜間が
日付をまたぐ金→土・祝日前→休場日の早朝でナイト・セッションを取りこぼし、ろうそく足生成が
停止していた（2026-06-26→27 の金夜→土早朝で実際に発生）。本テストは JPX 公式仕様どおりの
所有取引日ベース判定（早朝＝前日の夜間の続き／大納会はナイト無し／祝日取引は通常どおり）を固定する。

JPX 公式（出典: jpx.co.jp 祝日取引・取引時間）:
  - 日中 08:45–15:45 / 夜間 17:00–翌06:00。
  - 祝日取引「実施する」日＝日中・夜間とも通常どおり。
  - 「実施しない」祝日・週末の【前営業日】の夜間は翌朝6:00まで立つ（金→土と同様）。
  - 大納会（年末最終営業日）は日中のみ・ナイト無し。1/1〜1/3・12/31 は休場。
"""
import csv
from datetime import datetime

import pytest

from app.feed import _market_hours as mh
from app.feed import calendar_fetch as cf


def dt(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi)


@pytest.fixture(autouse=True)
def calendar_2026(monkeypatch):
    """2026 の「実施しない」祝日のみ注入（年末年始 1/1-1/3,12/31 は構造ルール側）。
    2026/11/23 勤労感謝の日＝実施しない（注6）＝JPX 固有判断（規則からは導けない代表例）。"""
    monkeypatch.setattr(mh, "_NO_TRADE_DATES", {(2026, 1, 2), (2026, 11, 23), (2026, 12, 31)})
    yield


# ───────────────── is_open_at（所有取引日ベース・最重要）─────────────────

@pytest.mark.parametrize("when,expected,why", [
    # 金(2026-06-26)→土(06-27): バグの再現ケース
    (dt(2026, 6, 26, 23, 30), True,  "金 夜間前半=OPEN"),
    (dt(2026, 6, 27, 2, 0),   True,  "★土 早朝=前日(金)の夜間の続き=OPEN（旧実装はここで凍結）"),
    (dt(2026, 6, 27, 5, 59),  True,  "土 早朝(夜間引け直前)=OPEN"),
    (dt(2026, 6, 27, 6, 0),   False, "06:00ちょうど=夜間引け後の場間=CLOSED"),
    (dt(2026, 6, 27, 8, 45),  False, "土 日中=週末=CLOSED"),
    (dt(2026, 6, 27, 17, 0),  False, "土 夜間=土に夜間は無い=CLOSED"),
    # 平日跨ぎ(水→木)は通常どおり OPEN
    (dt(2026, 6, 24, 23, 0),  True,  "水 夜間=OPEN"),
    (dt(2026, 6, 25, 2, 0),   True,  "木 早朝=前日(水)夜間=OPEN"),
    # 日→月: 日曜に夜間は無い→月曜早朝は CLOSED（重要な非自明ケース）
    (dt(2026, 6, 28, 2, 0),   False, "日 早朝=前日(土)夜間無し=CLOSED"),
    (dt(2026, 6, 29, 2, 0),   False, "★月 早朝=前日(日)夜間無し=CLOSED"),
    (dt(2026, 6, 29, 9, 0),   True,  "月 日中=OPEN"),
    # 祝日取引「実施する」(海の日 2026-07-20 月)= 通常営業日と同じ
    (dt(2026, 7, 20, 9, 0),   True,  "実施する祝日 日中=OPEN"),
    (dt(2026, 7, 20, 23, 0),  True,  "実施する祝日 夜間=OPEN"),
    (dt(2026, 7, 21, 2, 0),   True,  "翌火 早朝=実施する祝日の夜間の続き=OPEN"),
    # 祝日取引「実施しない」(勤労感謝の日 2026-11-23 月・注6)= 完全休場
    (dt(2026, 11, 23, 9, 0),  False, "実施しない祝日 日中=CLOSED"),
    (dt(2026, 11, 23, 23, 0), False, "実施しない祝日 夜間=CLOSED"),
    (dt(2026, 11, 24, 2, 0),  False, "翌火 早朝=実施しない祝日に夜間無し=CLOSED"),
    # 大納会(2026-12-30 水)= 日中のみ・ナイト無し
    (dt(2026, 12, 30, 9, 0),  True,  "大納会 日中=OPEN"),
    (dt(2026, 12, 30, 17, 0), False, "★大納会 夜間=ナイト無し=CLOSED"),
    (dt(2026, 12, 31, 2, 0),  False, "12/31 早朝=大納会にナイト無し=CLOSED"),
    (dt(2026, 12, 29, 23, 0), True,  "大納会前日(火) 夜間=OPEN（大納会の朝6:00まで立つ）"),
    (dt(2026, 12, 30, 2, 0),  True,  "大納会 早朝=前日(火)の夜間の続き=OPEN"),
    # 年末年始の休場（構造ルール）
    (dt(2026, 12, 31, 9, 0),  False, "12/31 日中=休場"),
    (dt(2027, 1, 1, 9, 0),    False, "1/1 元日=休場"),
    (dt(2026, 1, 2, 9, 0),    False, "1/2 年始休業=休場"),
    # 場間
    (dt(2026, 6, 24, 7, 0),   False, "06:00-08:45 場間=CLOSED"),
    (dt(2026, 6, 24, 16, 0),  False, "15:45-17:00 場間=CLOSED"),
])
def test_is_open_at(when, expected, why):
    assert mh.is_open_at(when) is expected, why


@pytest.mark.parametrize("when,expected,why", [
    # ★板寄せ（セッション末足）の前提：is_open_at は「終了時刻ちょうど」以降を必ず CLOSED にする。
    #   ohlc_processor の引け板寄せ tick 経路は not now_open かつ _is_session_close かつ tick>=bar_end の時だけ
    #   発火するため（+α で実引け値/出来高を取得）、この境界契約が崩れると板寄せ足が出ない/重複する。
    (dt(2026, 6, 24, 15, 44), True,  "日中引け直前(15:44)=OPEN"),
    (dt(2026, 6, 24, 15, 45), False, "★日中引け(15:45ちょうど)=CLOSED＝板寄せ tick 受入の前提"),
    (dt(2026, 6, 24, 15, 46), False, "引け後(+α)=CLOSED＝この間に届く実引け tick を板寄せ足にする"),
    (dt(2026, 6, 25, 5, 59),  True,  "夜間引け直前(5:59)=OPEN"),
    (dt(2026, 6, 25, 6, 0),   False, "★夜間引け(6:00ちょうど)=CLOSED＝板寄せ tick 受入の前提"),
    (dt(2026, 6, 25, 6, 1),   False, "夜間引け後(+α)=CLOSED"),
])
def test_session_close_boundary_for_auction(when, expected, why):
    """板寄せ（引け値・出来高は +α で確定）が動くための境界契約を固定。"""
    assert mh.is_open_at(when) is expected, why


def test_is_trading_time_is_alias():
    assert mh.is_trading_time(dt(2026, 6, 27, 2, 0)) is True   # 後方互換エイリアス


def test_oosame_detection():
    from datetime import date
    assert mh._is_year_last_trading_day(date(2026, 12, 30)) is True    # 大納会
    assert mh._is_year_last_trading_day(date(2026, 12, 29)) is False   # その前日は通常
    assert mh._is_year_last_trading_day(date(2026, 6, 30)) is False    # 年央は当然 False


# ───────────────── calendar_fetch（複数年マージ・鮮度・自動更新日）─────────────────

def _write(path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cf.FIELDNAMES)
        w.writeheader()
        w.writerows(rows)


def test_read_backward_compatible(tmp_path):
    """旧スキーマ（date,name,status のみ）も読める（後方互換）。"""
    p = tmp_path / "cal.csv"
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["date", "name", "status"])
        w.writeheader()
        w.writerow({"date": "2026/11/23", "name": "勤労感謝の日", "status": "実施しない（注6）"})
    recs = cf.read_calendar(p)
    assert recs[0]["date"] == "2026/11/23"
    assert recs[0]["confirmed"] == ""          # 欠損列は空
    assert cf.no_trade_count(recs) == 1


def test_save_records_fetched_at(tmp_path):
    """fetched_at（更新日）が自動付与される。"""
    p = tmp_path / "cal.csv"
    cf.save_calendar([{"date": "2026/7/20", "name": "海の日", "status": "実施する",
                       "confirmed": "確定", "source": "jpx"}], p)
    recs = cf.read_calendar(p)
    assert recs[0]["fetched_at"]               # 空でない
    assert cf.last_updated(p) is not None


def test_covered_years_and_merge_preserves_other_years(tmp_path):
    """マージで他年を消さない（複数年蓄積）。"""
    p = tmp_path / "cal.csv"
    _write(p, [{"date": "2026/7/20", "name": "海の日", "status": "実施する",
                "confirmed": "確定", "source": "jpx", "fetched_at": "2026-01-01T00:00:00"}])
    # 2027 を取得した体で手動マージ相当（update_calendar の merge ロジックを read+save で再現）
    existing = {cf._norm_date_key(r["date"]): r for r in cf.read_calendar(p)}
    existing[cf._norm_date_key("2027/7/19")] = {"date": "2027/7/19", "name": "海の日",
                                                "status": "実施する", "confirmed": "予定",
                                                "source": "jpx", "fetched_at": "2026-12-01T00:00:00"}
    cf.save_calendar(sorted(existing.values(), key=lambda r: cf._norm_date_key(r["date"])), p)
    assert cf.covered_years(p) == [2026, 2027]


def test_ui_status_severities(tmp_path):
    p = tmp_path / "cal.csv"
    # 未取得 → error
    s = cf.ui_status(datetime(2026, 6, 27), p)
    assert s["severity"] == "error" and s["need_update"] is True
    # 当年あり・年央 → ok
    _write(p, [{"date": "2026/7/20", "name": "海の日", "status": "実施する",
                "confirmed": "確定", "source": "jpx", "fetched_at": "2026-06-01T09:00:00"}])
    s = cf.ui_status(datetime(2026, 6, 27), p)
    assert s["severity"] == "ok" and s["need_update"] is False
    # 11月以降で翌年が無い → warn
    s = cf.ui_status(datetime(2026, 11, 15), p)
    assert s["severity"] == "warn" and s["need_update"] is True
    # 当年が無い（翌年に進んだ）→ warn
    s = cf.ui_status(datetime(2027, 1, 5), p)
    assert s["severity"] == "warn" and s["need_update"] is True
