# -*- coding: utf-8 -*-
"""欠けの判定（data_provider.find_gaps・履歴データ管理_設計書 D4）テスト。

  G1 セッションの中で足が飛んでいれば欠け（本数も合う）。
  G2 場間（15:45 → 17:00・06:00 → 08:45）と週末の空きは欠けではない。
  G3 板寄せ特別足（15:45／06:00）が無くても欠けに数えない（市場が開いている時刻ではない）。
  G4 間隔は足から導く（最頻値）。2 本未満なら空。
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.backtest import data_provider as dp  # noqa: E402


def _bars(times) -> pd.DataFrame:
    idx = pd.DatetimeIndex(pd.to_datetime(list(times)))
    return pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 0.0}, index=idx).rename_axis("datetime")


def _session(day: str, start: str, end: str):
    """start 〜 end の 15 分足の開始時刻（end は含まない）。"""
    return list(pd.date_range(f"{day} {start}", f"{day} {end}", freq="15min", inclusive="left"))


def test_g1_gap_inside_session():
    bars = _session("2026-11-10", "08:45", "15:45")                    # 火曜の日中 28 本
    removed = [b for b in bars if pd.Timestamp("2026-11-10 10:00") <= b <= pd.Timestamp("2026-11-10 11:30")]
    df = _bars([b for b in bars if b not in removed])
    gaps = dp.find_gaps(df)
    assert len(gaps) == 1
    assert gaps[0]["from"] == pd.Timestamp("2026-11-10 10:00") and gaps[0]["to"] == pd.Timestamp("2026-11-10 11:30")
    assert gaps[0]["bars"] == len(removed) == 7
    assert dp.format_gaps(gaps) == ["2026-11-10 10:00 〜 2026-11-10 11:30（7 本）"]


def test_g2_session_breaks_and_weekend_are_not_gaps():
    fri_day = _session("2026-11-06", "08:45", "15:45") + [pd.Timestamp("2026-11-06 15:45")]      # 金曜の日中＋板寄せ
    fri_night = list(pd.date_range("2026-11-06 17:00", "2026-11-07 05:45", freq="15min")) + [pd.Timestamp("2026-11-07 06:00")]   # 夜間は日付をまたぐ
    mon_day = _session("2026-11-09", "08:45", "15:45")
    df = _bars(fri_day + fri_night + mon_day)                           # 15:45→17:00・土曜 06:00→月曜 08:45 の空き
    assert dp.find_gaps(df) == []


def test_g3_missing_auction_bar_is_not_a_gap():
    day = _session("2026-11-10", "08:45", "15:45")                     # 15:45 の板寄せ足なし
    night = list(pd.date_range("2026-11-10 17:00", "2026-11-10 23:45", freq="15min"))
    df = _bars(day + night)
    assert dp.find_gaps(df) == []


def test_g4_interval_from_data():
    df = _bars(_session("2026-11-10", "08:45", "15:45"))
    assert dp.bar_interval(df) == pd.Timedelta(minutes=15)
    assert dp.find_gaps(_bars(["2026-11-10 09:00"])) == []
