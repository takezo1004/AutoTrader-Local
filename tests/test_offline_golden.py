# -*- coding: utf-8 -*-
"""J-2 オフライン DT 確定スナップショット 回帰テスト（詳細仕様 §J-2）。

ローカルエンジンの戦略ローダ＋オフライン driver（run_pine_fast）で、登録戦略 DT_Stochastic を
4年データで回し、**現行 config.json（＝現行 TradingView と同じパラメータ）での確定出力**に
トレード単位で一致することを確認する＝今後コード変更で約定/移植が壊れたら検知する回帰ガード。

★パラメータは確定済み（蒸し返さない）:
  2026-06-22 に各戦略の config.json を「現行 TradingView と同じパラメータ」へ変更＝**最終確定**。
  理由＝4年較正で決めた旧値は現状の相場ではズレる（現在のボラティリティが4年前より非常に大きい）。
  ＝旧4年 golden（n=599・config_v7_8 較正）は現行 config に置き換え済みで**役目を終えた**。
  本テストの基準は下記「現行 config の確定スナップショット」であり、旧 n=599 へ戻す判断は不要。

旧4年 golden（参考・履歴／旧 config 較正値・もう使わない）:
  n=599 / PF=2.29 / 純益=+10,756,500 / 出典 N225StrategyBuilder/strategies/DT_Stochastic/work/result.md

現行スナップショット（2026-06-29 再ベースライン③・セッション制御込み・master_dataset_4y.pkl 72,815本・決定論的）:
  n=604 / win=65.1% / PF=2.25 / 純益=+10,258,500 / DD=-341,500 / 平均保有=18.0
  年別n  2023:194  2024:168  2025:165  2026:77（全年 PF≥1.99）
  ※ 2026-06-29 セッション制御（共有 session_lib・各セッション終了30分前以降の新規/決済停止・週末/
    祝日/大納会/SQ 直前の強制 flat）導入で、約定不可だった取引（6時建玉・週末跨ぎ・締切窓）が剥がれ
    n=1005→604・PF1.72→2.25・全年プラスへ。＝実運用可能な正味成績への正当な再ベースライン。
    あわせて session_lib の ts 変換頑健化（numpy.datetime64/Timestamp/str 統一）で offline=on_bar=step が
    同一 gating になった（旧は on_bar 経路で numpy.datetime64 が解析失敗し gating 抜けしていた）。
  旧（2026-06-24・セッション制御前）: n=1005 / PF=1.72 / 純益=+12,927,633（役目を終えた・参考）。

データ＝StrategyBuilder の master_dataset_4y.pkl（テスト用フィクスチャ・読取のみ）。
製品の内蔵BTは app/backtest/data_provider（parquet+CSV・半年）で供給する（M4）。
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]            # N225LocalEngine/
sys.path.insert(0, str(ROOT))
from app.engine import load_strategy, run_pine_fast, summarize  # noqa: E402

DATA = ROOT.parent / "N225DataPipeline" / "datasets" / "master_dataset_4y.pkl"  # データ正本=DataPipeline
STRAT_FOLDER = ROOT / "strategies" / "DT_Stochastic"

# 確定スナップショット（セッション制御込み・2026-06-29 再ベースライン③・決定論的）
G_N = 604
G_PNL = 10_258_500
G_PF = 2.25
G_YEARLY_N = {2023: 194, 2024: 168, 2025: 165, 2026: 77}


def test_dt_config_snapshot():
    assert DATA.exists(), f"テストデータが無い: {DATA}"
    ds = pd.read_pickle(DATA)
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
