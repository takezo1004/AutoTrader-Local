# -*- coding: utf-8 -*-
"""BT 取引一覧 ≡ 取引記録の取引一覧 の一致テスト（2026-06-23・ユーザー要望）。

同じデータ・同じ戦略なら、
  ① 内蔵BT（run_pine_fast の fills）から作る取引一覧
  ② ライブ記録経路（RealtimeBroker.on_bar_close で駆動 → 発火記録 → pair_trades）から作る取引一覧
は**一致**するはず。一致しなければ記録/ペアリングのロジックが BT とズレている＝バグ。

ライブ側は確定足を on_bar_close で1本ずつ駆動（tick 無し＝確定足の高安で約定＝offline と同じ A1/A2）。
最終足で finalize_end_of_data を呼び、BT の end_of_data 強制決済と条件を合わせる。
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.engine.offline_driver import run_pine_fast            # noqa: E402
from app.engine.realtime_broker import RealtimeBroker          # noqa: E402
from app.engine.strategy_loader import load_strategy           # noqa: E402
from app.engine.controller import pair_trades                  # noqa: E402

DATA = ROOT.parent / "N225DataPipeline" / "datasets" / "master_dataset_4y.pkl"
STRAT = ROOT / "strategies" / "MESA_Stochastic"


def _slice(n0, n1):
    ds = pd.read_pickle(DATA).iloc[n0:n1]
    return ds[["open", "high", "low", "close"]].assign(
        volume=ds["volume"] if "volume" in ds.columns else 0)


def _nt(s):
    """時刻文字列を正規化（表記差 'T'/' ' を吸収して突合）。"""
    return str(s).strip().replace("T", " ")[:19]


def _bt_legs(df):
    """内蔵BT（run_pine_fast）の fills を取引一覧レグ（決済単位）に。"""
    fills = run_pine_fast(load_strategy(STRAT).instance, df)
    legs = []
    for _, f in fills.iterrows():
        legs.append((_nt(f["entry_ts"]), _nt(f["exit_ts"]),
                     round(float(f["exit_price"]), 1), int(f["qty"]),
                     round(float(f["pnl_pt"]), 1)))
    return legs


def _live_legs(df):
    """ライブ記録経路（on_bar_close 駆動 → 発火記録 → pair_trades）の取引一覧レグ。"""
    rec = []
    rb = RealtimeBroker(load_strategy(STRAT).instance, name="mesa78s3", interval=15)
    rb.on_event = lambda ev: rec.append(ev)
    o = df["open"].to_numpy(float); h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float); c = df["close"].to_numpy(float)
    ts = df.index.to_numpy(); vol = df["volume"].to_numpy(float)
    for i in range(len(df)):
        rb.on_bar_close({"datetime": ts[i], "open": o[i], "high": h[i],
                         "low": l[i], "close": c[i], "volume": vol[i]})
    rb.finalize_end_of_data(close=float(c[-1]), ts=ts[-1])     # BT の end_of_data と条件を合わせる
    closed = pair_trades(rec)["closed"]
    legs = []
    for r in closed:
        legs.append((_nt(r["entry_ts"]), _nt(r["ts"]),
                     round(float(r["price"]), 1), int(r["qty"]),
                     round(float(r["pnl_pt"]), 1)))
    return legs


def test_trade_list_matches_backtest():
    if not DATA.exists():
        print("  SKIP (DATA 無し)"); return
    df = _slice(0, 2200)
    bt = sorted(_bt_legs(df))
    live = sorted(_live_legs(df))
    bt_pnl = round(sum(x[4] for x in bt), 1)
    live_pnl = round(sum(x[4] for x in live), 1)
    print(f"  BT レグ={len(bt)} 損益={bt_pnl:+.1f}pt ／ ライブ記録 レグ={len(live)} 損益={live_pnl:+.1f}pt")
    assert len(bt) == len(live), f"レグ数不一致: BT {len(bt)} != ライブ {len(live)}"
    diff = [(b, v) for b, v in zip(bt, live) if b != v]
    assert not diff, f"レグ内容不一致（先頭3件）: {diff[:3]}"
    assert abs(bt_pnl - live_pnl) < 0.05, f"合計損益不一致: BT {bt_pnl} != ライブ {live_pnl}"
    print("  ✅ BT 取引一覧 ≡ 取引記録の取引一覧（完全一致）")


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
    sys.exit(0 if _run_all() else 1)
