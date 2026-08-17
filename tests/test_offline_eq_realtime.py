# -*- coding: utf-8 -*-
"""J-3 オフライン＝リアルタイム 一致テスト（詳細仕様 §J-3・★二刀エンジンの核）。

同一の価格パスを与えれば、オフライン driver（履歴バー・run_pine_fast）と
リアルタイム driver（形成中足 tick・RealtimeBroker）が**同じ fills** を出すことを確認。
＝指値イントラバー約定を tick 駆動で行っても、バー駆動と結果が一致する（先読み無し・実機可能）。

合成 tick 展開（§B.5）: バー (o,h,l,c) を [o → 先行extreme → 後行extreme → c] の tick 列に。
  up_first=(h-o)<(o-l) なら 先行=高値→[o,h,l,c]、そうでなければ [o,l,h,c]。
リアルタイムは on_tick で A1/A2 を tick 駆動、on_bar_close で戦略判断。最後に EOD 強制決済。

比較対象＝run_pine_fast（正本 BT・step）。devlog で on_bar≡step は実証済なので、
realtime(on_bar) == run_pine_fast(step) が一致すれば「tick 駆動の約定 == バー駆動の約定」を実証。
スライスで実行（on_bar バッファ再計算は重いため・既定 2500本）。
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.engine import load_strategy, run_pine_fast, RealtimeBroker  # noqa: E402

DATA = ROOT.parent / "N225DataPipeline" / "datasets" / "master_dataset_4y.pkl"  # データ正本=DataPipeline
STRAT_FOLDER = ROOT / "strategies" / "DT_Stochastic"
# ★pytest 自動実行用の既定本数（軽量・指値イントラバー約定を含む十分量）。フル検証はスクリプト実行：
#   python tests/test_offline_eq_realtime.py [本数]
# （旧：モジュール冒頭で sys.argv[1] を読み pytest 収集が落ちて自動回帰から漏れていたのを是正・2026-06-27）
NROWS = 1000
NROWS_FULL = 2500


def _bar_to_ticks(o, h, l, c):
    """バー → 合成 tick 列（先行レグの極値を先に）。"""
    up_first = (h - o) < (o - l)
    mid = [h, l] if up_first else [l, h]
    return [o] + mid + [c]


def _run_realtime(strategy, df):
    rb = RealtimeBroker(strategy, name="DT_Stochastic", interval=15)
    o = df["open"].to_numpy(float); h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float); c = df["close"].to_numpy(float)
    ts = df.index.to_numpy()
    n = len(df)
    for i in range(n):
        for px in _bar_to_ticks(o[i], h[i], l[i], c[i]):
            rb.on_tick(px, ts[i])
        rb.on_bar_close({"datetime": ts[i], "open": o[i], "high": h[i],
                         "low": l[i], "close": c[i], "volume": 0})
    rb.finalize_end_of_data(c[n - 1], ts[n - 1])      # offline と同じ EOD 強制決済
    return rb


def _cmp_fills(a: pd.DataFrame, b: pd.DataFrame) -> tuple[bool, str]:
    if len(a) != len(b):
        return False, f"fills 件数 {len(a)} != {len(b)}"
    cols = ["trade_id", "entry_bar", "exit_bar", "qty", "exit_reason"]
    for col in cols:
        if not (a[col].reset_index(drop=True) == b[col].reset_index(drop=True)).all():
            return False, f"列 {col} に差"
    for col in ["entry_price", "exit_price", "pnl_pt"]:
        if not np.allclose(a[col].to_numpy(float), b[col].to_numpy(float), atol=1e-6):
            return False, f"列 {col} に数値差"
    return True, "OK"


def _run(nrows):
    assert DATA.exists(), f"テストデータが無い: {DATA}"
    ds = pd.read_pickle(DATA).iloc[:nrows]
    cols = ds[["open", "high", "low", "close"]].assign(
        volume=ds["volume"] if "volume" in ds.columns else 0)

    t0 = time.time()
    off = run_pine_fast(load_strategy(STRAT_FOLDER).instance, cols)
    t_off = time.time() - t0

    t0 = time.time()
    rb = _run_realtime(load_strategy(STRAT_FOLDER).instance, cols)
    rt = rb.fills
    t_rt = time.time() - t0

    print(f"  [{len(ds)} bars]  offline fills={len(off)} ({t_off:.1f}s)  "
          f"realtime fills={len(rt)} ({t_rt:.1f}s)  webhooks={len(rb.webhooks)}")
    same, why = _cmp_fills(off, rt)
    assert same, f"オフライン≠リアルタイム: {why}"
    print(f"  → fills 完全一致（trade_id/entry_bar/exit_bar/qty/価格/pnl）・取引数 "
          f"{off['trade_id'].nunique()}・指値イントラバーを tick 駆動で再現")

    # webhook の健全性（spec §9）: 再構成した最終ポジションが broker と一致
    pos = 0
    for w in rb.webhooks:
        s = w["strategy"]
        cur = {"flat": 0, "long": 1, "short": -1}[s["market_position"]] * s["market_position_size"]
        pos = cur
    assert pos == rb.bk.position_size, f"webhook 再構成ポジ {pos} != broker {rb.bk.position_size}"


def test_offline_eq_realtime():
    """★pytest 自動実行（引数なし＝NROWS 本）。指値の tick 発火が確定足BT（run_pine_fast）と
    一致することを毎回自動でガードする（手動フル検証は下記スクリプト実行）。"""
    _run(NROWS)


if __name__ == "__main__":
    nrows = int(sys.argv[1]) if len(sys.argv) > 1 else NROWS_FULL
    print(f"J-3 オフライン＝リアルタイム一致テスト（DT・{nrows}本）")
    try:
        _run(nrows)
        print("  PASS  test_offline_eq_realtime"); sys.exit(0)
    except AssertionError as e:
        print(f"  FAIL  {e}"); sys.exit(1)
