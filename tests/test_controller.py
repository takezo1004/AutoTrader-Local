# -*- coding: utf-8 -*-
"""コントローラ統合テスト（J-5/J-6 相当・外部仕様 F1/F3/F4/F5）。

実フィードの代わりに master データのスライスを「確定足＋合成tick」で直接 LiveEngine に流し、
登録/実行可否(段階1)/全体実行停止(段階2)/dry-run(仮想売買)/内蔵BT が動くことを確認。
"""
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.engine import LocalEngineController  # noqa: E402

DATA = ROOT.parent / "N225DataPipeline" / "datasets" / "master_dataset_4y.pkl"  # データ正本=DataPipeline
STRAT = ROOT / "strategies" / "DT_Stochastic"


class _CaptureSink:
    """テスト用の注文チャネル＝実ブリッジへ出さず webhook を記録するだけ（実 I/O ゼロ）。

    controller に sender_factory として注入し、有効化で「送出経路が付く／実際に送出が起きる」を
    実ネットワーク無しで検証する。直接実行（python test_controller.py）でも安全。
    """
    def __init__(self):
        self.sent = []

    def send(self, webhook):
        self.sent.append(webhook)
        return '{"status": "captured-in-test"}'


def _ticks(o, h, l, c):
    up = (h - o) < (o - l)
    return [o] + ([h, l] if up else [l, h]) + [c]


def _feed(ctrl, df):
    o = df["open"].to_numpy(float); h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float); c = df["close"].to_numpy(float)
    ts = df.index.to_numpy()
    for i in range(len(df)):
        for px in _ticks(o[i], h[i], l[i], c[i]):
            ctrl.engine.on_tick(px, ts[i])
        ctrl.engine.on_confirmed_bar({"datetime": ts[i], "open": o[i], "high": h[i],
                                      "low": l[i], "close": c[i], "volume": 0})


def test_controller_session():
    assert DATA.exists(), f"テストデータが無い: {DATA}"
    ds = pd.read_pickle(DATA).iloc[:1600]
    cols = ds[["open", "high", "low", "close"]].assign(volume=0)
    warm = cols.iloc[:400]        # warmup（指標暖機）
    live = cols.iloc[400:]        # ライブ相当（約1200本）

    with tempfile.TemporaryDirectory() as d:
        state = Path(d) / "state"
        # ★注文チャネルは捕捉シンクを注入＝実ブリッジ/実ネットワークへ絶対に出さない。
        #   bridge_url も到達不能値にして二重に安全側へ倒す（万一 factory を経由しない経路があっても無害）。
        sink = _CaptureSink()
        ctrl = LocalEngineController(strategies_dir=STRAT.parent, state_dir=state,
                                     bridge_url="http://127.0.0.1:9/webhook",
                                     on_log=lambda m: None,
                                     sender_factory=lambda: sink)

        # F1 登録（既に strategies/ 内 → コピーなし参照）
        name = ctrl.register(STRAT)
        assert name == "DT_Stochastic"
        assert any(r["name"] == "DT_Stochastic" for r in ctrl._registered)

        # ★記録は常時・全戦略：enabled=False でも処理・記録される。送出はしない(sender=None)。
        ctrl.start(warmup_df=warm)
        _feed(ctrl, live)
        rb = ctrl.engine._brokers["DT_Stochastic"]
        assert rb.sender is None, "無効戦略は送出経路を持たない（送出しない）"
        assert len(sink.sent) == 0, "無効中は1件も送出しない（実ブリッジへ出ない）"
        rec_off = ctrl.read_trade_log()
        print(f"  無効時の記録 {len(rec_off)} 件 / 送出 {len(sink.sent)} 件 / fills={len(rb.bk.fills)}")
        assert len(rec_off) > 0, "記録は常時（無効でも記録される）"
        assert all(r["mode"] == "仮想" for r in rec_off), "無効＝記録のみ(仮想)"

        # F3 有効化 → 送出経路が即時に注文チャネル(注入シンク)になる
        ctrl.set_enabled("DT_Stochastic", True)
        assert rb.sender is sink, "有効化で送出経路ON（注入した注文チャネルが付く）"
        ctrl.clear_trade_log()
        ctrl.start(warmup_df=warm)                 # 再 warmup（reset）
        rb = ctrl.engine._brokers["DT_Stochastic"]
        assert rb.sender is sink
        _feed(ctrl, live)
        rec_on = ctrl.read_trade_log()
        print(f"  有効時の記録 {len(rec_on)} 件 / 送出 {len(sink.sent)} 件")
        assert len(rec_on) > 0, "有効でも記録される"
        assert all(r["mode"] == "本番" for r in rec_on), "有効＝本番(送出)"
        assert len(sink.sent) > 0, "有効化で実際に送出が起きる（捕捉シンクに届く）"

        # 停止すると running=False（オートトレード用の停止ボタンは無いが内部 stop は機能）
        ctrl.stop()
        assert ctrl.status()["running"] is False

        # 状態 JSON が書かれている
        assert (state / "registered.json").exists()
        assert (state / "engine_state.json").exists()


def test_controller_backtest():
    assert DATA.exists()
    ds = pd.read_pickle(DATA).iloc[:2000]
    cols = ds[["open", "high", "low", "close"]].assign(volume=0)
    with tempfile.TemporaryDirectory() as d:
        ctrl = LocalEngineController(strategies_dir=STRAT.parent, state_dir=Path(d) / "state",
                                     on_log=lambda m: None)
        ctrl.register(STRAT)
        rep = ctrl.backtest("DT_Stochastic", cols, cost_pts=(0, 5, 10))
        print(f"  内蔵BT: n={rep['summary']['n']} PF={rep['summary']['pf']} "
              f"純益={rep['summary']['pnl']:+,} 月数={len(rep['monthly'])} "
              f"コスト感度={[c['pf'] for c in rep['cost']]}")
        assert rep["summary"]["n"] > 0
        assert len(rep["cost"]) == 3 and rep["cost"][0]["cost_pt"] == 0
        assert rep["cost"][0]["pf"] >= rep["cost"][2]["pf"]   # コスト増でPFは下がる（または同）
        assert len(rep["equity"]) == rep["summary"]["n"]


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
    print("コントローラ統合テスト（登録/2段階制御/dry-run/内蔵BT）")
    sys.exit(0 if _run_all() else 1)
