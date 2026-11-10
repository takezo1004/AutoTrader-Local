# -*- coding: utf-8 -*-
"""取込の守り（履歴データ管理_設計書 D5）テスト。

  I1 drop_unfinished：いまの足の区切り以降（まだ閉じていない足）を落とし、本数を返す。
  I2 classify_overlap：次の足が新側に続き・出来高が既存以上なら「既存が古い足」、そうでなければ「原因不明」。
  I3 settlement_to_actual：16:30 の足（2024-11-04 以前の夜間開始）は前営業日の実時刻になる（正本 n225_timestamp.py と同じ）。
  I4 import_file：未完成バーを落とし、重なりの件数を結果に返し、取込分で置き換える（D3）。
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.backtest import data_provider as dp   # noqa: E402
from app.backtest import data_import as di     # noqa: E402


def _bars(times, close=100.0, vol=10.0) -> pd.DataFrame:
    idx = pd.DatetimeIndex(pd.to_datetime(list(times)))
    return pd.DataFrame({"open": close, "high": close + 5, "low": close - 5, "close": close, "volume": vol},
                        index=idx).rename_axis("datetime")


def test_i1_drop_unfinished():
    df = _bars(pd.date_range("2026-11-10 09:00", "2026-11-10 10:30", freq="15min"))   # 09:00〜10:30 の 7 本
    out, n = dp.drop_unfinished(df, now=pd.Timestamp("2026-11-10 10:37"))             # いまの区切り＝10:30 → 10:30 の足は未完成
    assert n == 1 and out.index[-1] == pd.Timestamp("2026-11-10 10:15")
    out2, n2 = dp.drop_unfinished(df, now=pd.Timestamp("2026-11-10 11:00"))
    assert n2 == 0 and len(out2) == 7


def test_i2_classify_overlap():
    times = pd.date_range("2026-11-10 09:00", "2026-11-10 09:45", freq="15min")
    base = _bars(times, close=100.0, vol=10.0)
    new = base.copy()
    # 09:15：既存が古い足＝新側の終値 110 に次の足の始値が近く、出来高も多い
    new.loc[pd.Timestamp("2026-11-10 09:15"), ["close", "volume"]] = [110.0, 15.0]
    new.loc[pd.Timestamp("2026-11-10 09:30"), "open"] = 110.0
    base.loc[pd.Timestamp("2026-11-10 09:30"), "open"] = 110.0        # 09:30 自体は両側で同じ（不一致は 09:15 と 09:45 だけ）
    # 09:45：原因不明＝次の足が無い
    new.loc[pd.Timestamp("2026-11-10 09:45"), "close"] = 95.0
    r = dp.classify_overlap(base, new)
    assert list(r["stale"]) == [pd.Timestamp("2026-11-10 09:15")]
    assert list(r["unexplained"]) == [pd.Timestamp("2026-11-10 09:45")]
    assert len(r["lines"]) == 2


def test_i3_settlement_to_actual_1630_is_previous_business_day():
    from datetime import date, time
    # 取引日 2024-10-16（水）の 16:30 の足＝前営業日 10-15（火）の 16:30
    assert di.settlement_to_actual(pd.Timestamp("2024-10-16"), time(16, 30)) == pd.Timestamp("2024-10-15 16:30").to_pydatetime()
    assert di.settlement_to_actual(pd.Timestamp("2024-10-16"), time(17, 0)) == pd.Timestamp("2024-10-15 17:00").to_pydatetime()
    assert di.settlement_to_actual(pd.Timestamp("2024-10-16"), time(9, 0)) == pd.Timestamp("2024-10-16 09:00").to_pydatetime()


def test_i4_import_file_guards(tmp_path):
    pq = tmp_path / "store.parquet"
    store = _bars(pd.date_range("2026-11-10 09:00", "2026-11-10 09:45", freq="15min"), close=100.0)
    store.reset_index().to_parquet(pq, index=False)
    csv = tmp_path / "tv.csv"
    new = _bars(pd.date_range("2026-11-10 09:30", "2026-11-10 10:30", freq="15min"), close=120.0, vol=20.0)
    new.loc[pd.Timestamp("2026-11-10 09:45"), "open"] = 120.0                  # 09:30 を「既存が古い足」にする
    tv = new.reset_index().rename(columns={"datetime": "time"})
    tv["time"] = tv["time"].dt.strftime("%Y-%m-%dT%H:%M:%S+09:00")
    tv.to_csv(csv, index=False)
    now = pd.Timestamp("2026-11-10 10:37")
    orig = di.drop_unfinished                                   # data_import は名前で import しているのでそちらを差し替える
    di.drop_unfinished = lambda df, interval=None, now_=now: orig(df, interval, now_)   # いまの時刻を固定
    try:
        r = di.import_file(csv, pq, fmt="tv")
    finally:
        di.drop_unfinished = orig
    assert r["dropped_unfinished"] == 1                       # 10:30 の足は未完成
    assert r["overlap"] == 2 and r["stale"] + r["unexplained"] == 2
    merged = dp.load_parquet(pq)
    assert merged.loc[pd.Timestamp("2026-11-10 09:30"), "close"] == 120.0   # 取込分で置き換え（D3）
    assert merged.index[-1] == pd.Timestamp("2026-11-10 10:15")
