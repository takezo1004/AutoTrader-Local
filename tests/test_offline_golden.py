# -*- coding: utf-8 -*-
"""J-2 オフライン DT 確定スナップショット 回帰テスト（詳細仕様 §J-2）。

ローカルエンジンの戦略ローダ＋オフライン driver（run_pine_fast）で、登録戦略 DT_Stochastic を
4年データで回し、**現行 config.json（＝現行 TradingView と同じパラメータ）での確定出力**に
トレード単位で一致することを確認する＝今後コード変更で約定/移植が壊れたら検知する回帰ガード。

パラメータは strategies/DT_Stochastic/config.json（現行 TradingView と同じ値）。較正値へ戻す判断は要らない。

現行スナップショット（正本 n225_15m_4y.pkl を終点 2026-10-30 06:00 で切った 80,579 本・セッション制御込み・決定論的）:
  n=680 / PF=1.51 / 純益=+7,287,500
  年別n  2023:192  2024:181  2025:166  2026:141
  照合値を取り直すのは「基準を取り直す」と決めたときだけ（そのとき DATA_END と G_* を一緒に書き換える）。

データ＝N225DataPipeline の正本 n225_15m_4y.pkl（読取のみ）。正本は毎朝伸びるので DATA_END で切って本数を固定する
（_STRUCTURE.md「BT は終点を固定して比べる」）。
製品の内蔵BTは app/backtest/data_provider（parquet+CSV・半年）で供給する（M4）。
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]            # N225LocalEngine/
sys.path.insert(0, str(ROOT))
from app.engine import load_strategy, run_pine_fast, summarize  # noqa: E402

DATA = ROOT.parent / "N225DataPipeline" / "datasets" / "n225_15m_4y.pkl"  # データ正本=DataPipeline（15 分足・4 年）
DATA_END = "2026-10-30 06:00"           # 照合値を測った終点（その足まで）。正本が伸びても同じ本数で比べる
STRAT_FOLDER = ROOT / "strategies" / "DT_Stochastic"

# 確定スナップショット（セッション制御込み・終点 DATA_END・決定論的）
G_N = 680
G_PNL = 7_287_500
G_PF = 1.51
G_YEARLY_N = {2023: 192, 2024: 181, 2025: 166, 2026: 141}


def test_dt_config_snapshot():
    assert DATA.exists(), f"テストデータが無い: {DATA}"
    ds = pd.read_pickle(DATA)
    ds = ds[ds.index <= pd.Timestamp(DATA_END)]       # 終点で切る（正本は毎朝伸びる）
    cols = ds[["open", "high", "low", "close"]].assign(
        volume=ds["volume"] if "volume" in ds.columns else 0)

    loaded = load_strategy(STRAT_FOLDER)
    assert loaded.name == "DT_Stochastic"
    assert loaded.manifest.get("interval") == 15

    s = summarize(run_pine_fast(loaded.instance, cols))
    print(f"  [{len(ds)} bars]  n={s['n']} win={s['win']}% PF={s['pf']} "
          f"純益={s['pnl']:+,} DD={s['dd']:+,} 平均保有={s['avg_hold']}")
    print(f"  年別(n/PF): " + "  ".join(f"{y}:{v[0]}/{v[1]}" for y, v in s["yearly"].items()))

    assert s["n"] == G_N, f"取引数 {s['n']} != 確定 {G_N}"
    assert s["pnl"] == G_PNL, f"純益 {s['pnl']:+,} != 確定 {G_PNL:+,}"
    assert s["pf"] == G_PF, f"PF {s['pf']} != 確定 {G_PF}"
    for y, n in G_YEARLY_N.items():
        assert s["yearly"].get(y, (0,))[0] == n, f"{y} 取引数 {s['yearly'].get(y)} != {n}"
    print("  → 現行 config の確定スナップショットに完全一致")


def _run_all():
    ok = 0
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        try:
            t(); print(f"  PASS  {t.__name__}"); ok += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{ok}/{len(tests)} passed")
    return ok == len(tests)


if __name__ == "__main__":
    print("J-2 オフライン golden 一致テスト（DT_Stochastic）")
    sys.exit(0 if _run_all() else 1)
