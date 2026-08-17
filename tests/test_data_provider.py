# -*- coding: utf-8 -*-
"""内蔵BT データ供給テスト（詳細仕様 §F）— CSV優先マージ・半年窓・エンコーディング。"""
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.backtest import data_provider as dp  # noqa: E402


def _mk(dts, closes):
    idx = pd.to_datetime(dts)
    return pd.DataFrame({"open": closes, "high": closes, "low": closes,
                         "close": closes, "volume": 0}, index=idx).rename_axis("datetime")


def test_merge_csv_priority():
    pq = _mk(["2026-01-01 09:00", "2026-01-01 09:15", "2026-01-01 09:30"], [100, 101, 102])
    csv = _mk(["2026-01-01 09:15", "2026-01-01 09:30", "2026-01-01 09:45"], [201, 202, 203])
    m = dp.merge(pq, csv, prefer="csv")
    got = dict(zip(m.index.strftime("%H:%M"), m["close"]))
    assert got == {"09:00": 100, "09:15": 201, "09:30": 202, "09:45": 203}, got  # 重複はCSV勝ち
    # prefer=accum なら蓄積側が勝つ
    m2 = dp.merge(pq, csv, prefer="accum")
    got2 = dict(zip(m2.index.strftime("%H:%M"), m2["close"]))
    assert got2["09:15"] == 101 and got2["09:30"] == 102, got2


def test_window_half_year():
    idx = pd.date_range("2025-01-01", periods=400, freq="D")
    df = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 0},
                      index=idx).rename_axis("datetime")
    w = dp.window(df, months=6, warmup_bars=10)
    assert w.index[-1] == df.index[-1]                       # 末尾は維持
    cutoff = df.index[-1] - pd.DateOffset(months=6)
    # 先頭は cutoff より warmup(10) 本ぶん前（おおよそ）
    assert w.index[0] <= cutoff
    assert df.index[-1] - w.index[0] <= pd.Timedelta(days=200)  # 約半年強に収まる


def test_load_csv_encodings():
    rows = "datetime,open,high,low,close,volume\n2026/01/01 09:00:00,100,101,99,100,5\n"
    with tempfile.TemporaryDirectory() as d:
        for enc in ("utf-8", "cp932"):
            p = Path(d) / f"x_{enc}.csv"
            p.write_text(rows, encoding=enc)
            df = dp.load_csv(p)
            assert len(df) == 1 and float(df["close"].iloc[0]) == 100.0
            assert df.index[0] == pd.Timestamp("2026-01-01 09:00:00")


def test_tv_csv_detect_load_import():
    """★TradingView CSV の自動マージ（実時刻 +09:00・settlement 変換しない・kabu と判別）。"""
    from app.backtest import data_import as di
    tv = ("time,open,high,low,close,Volume,Ind\n"
          "2026-06-26T15:45:00+09:00,69000,69010,68990,69005,100,1.2\n"
          "2026-06-27T00:00:00+09:00,69005,69020,69000,69010,50,1.3\n")   # 土曜早朝(実時刻)
    kabu = ("日時,始値,高値,安値,終値,出来高\n"
            "2026/06/26 15:45:00,69000,69010,68990,69005,100\n")
    with tempfile.TemporaryDirectory() as d:
        dd = Path(d)
        ftv = dd / "OSE_NK225M1!, 15_test.csv"; ftv.write_text(tv, encoding="utf-8-sig")
        fkb = dd / "kabu_test.csv"; fkb.write_text(kabu, encoding="cp932")
        assert di.is_tv_csv(ftv) is True                       # TV を TV と判定
        assert di.is_tv_csv(fkb) is False                      # kabu を TV と誤判定しない
        df = di.load_tv_csv(ftv)
        assert df.index.tz is None                             # +09:00 を naive JST に落とす
        assert pd.Timestamp("2026-06-27 00:00:00") in df.index # 実時刻のまま（取引日シフトしない）
        assert float(df["close"].loc["2026-06-27 00:00:00"]) == 69010.0
        pq = dd / "store.parquet"
        r = di.import_auto(str(ftv), str(pq))                  # 自動判別で TV としてマージ
        assert r["fmt"] == "tv" and r["added_rows"] == 2, r


def _run_all():
    ok = 0
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        try:
            t(); print(f"  PASS  {t.__name__}"); ok += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:
            import traceback; traceback.print_exc(); print(f"  ERROR {t.__name__}: {e}")
    print(f"\n{ok}/{len(tests)} passed")
    return ok == len(tests)


if __name__ == "__main__":
    print("内蔵BT データ供給テスト")
    sys.exit(0 if _run_all() else 1)
