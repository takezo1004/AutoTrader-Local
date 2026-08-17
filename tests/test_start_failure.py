# -*- coding: utf-8 -*-
"""起動失敗の可視化＆永続ログの回帰テスト（2026-06-23 の「黙って記録ゼロ」事故の再発防止）。

夜間、tick ポート :5000 が別インスタンス/ゾンビに握られ feed.start() が False を返したため、
controller.start() が静かに中止し終夜「記録ゼロ」になった。しかも永続ログが無く気づけなかった。
ここでは「失敗を engine_state / start_error / 永続ログで必ず可視化する」ことを保証する。
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.engine import LocalEngineController  # noqa: E402
from app.feed import logger as flog           # noqa: E402

STRAT = ROOT / "strategies" / "DT_Stochastic"


class _FakeMgr:
    on_bar_close = None
    on_tick = None


class _BusyFeed:
    """tick ポートが使用中で接続できないフィード（start→False）。"""
    def __init__(self):
        self.mgr = _FakeMgr()
    def start(self):
        return False
    def stop(self):
        pass


class _OkFeed:
    """正常に接続できるフィード（start→True）。"""
    def __init__(self):
        self.mgr = _FakeMgr()
    def start(self):
        return True
    def stop(self):
        pass


def test_feed_busy_is_loud_not_silent():
    """feed.start()==False のとき、黙って止まらず start_error / recording:false を残す。"""
    with tempfile.TemporaryDirectory() as d:
        state = Path(d) / "state"
        ctrl = LocalEngineController(strategies_dir=STRAT.parent, state_dir=state, on_log=lambda m: None)
        ctrl.register(STRAT)

        ok = ctrl.start(warmup_df=None, feed=_BusyFeed())
        assert ok is False, "ポート使用中は起動失敗"
        assert ctrl.start_error, "失敗理由が start_error に残る"
        assert ctrl.engine.running is False

        st = ctrl.status()
        assert st["recording"] is False
        assert st["start_error"], "status に失敗理由が出る（ダッシュボード赤バナー用）"

        # ★engine_state.json に即座に永続化されている（後から状態ファイルだけ見ても分かる）
        data = json.loads((state / "engine_state.json").read_text(encoding="utf-8"))
        assert data["recording"] is False
        assert data["start_error"], "engine_state.json に start_error が書かれる"


def test_feed_ok_clears_start_error():
    """正常接続できれば start_error は解除され recording:true になる。"""
    with tempfile.TemporaryDirectory() as d:
        state = Path(d) / "state"
        ctrl = LocalEngineController(strategies_dir=STRAT.parent, state_dir=state, on_log=lambda m: None)
        ctrl.register(STRAT)

        # まず失敗させて start_error を立てる
        assert ctrl.start(warmup_df=None, feed=_BusyFeed()) is False
        assert ctrl.start_error

        # 次に正常接続 → 解除
        ok = ctrl.start(warmup_df=None, feed=_OkFeed())
        assert ok is True
        assert ctrl.start_error is None
        assert ctrl.status()["recording"] is True


def test_warmup_exception_stops_feed_and_is_loud():
    """warmup 等で start() が例外 → feed を止め、start_error/recording:false を残す
    （「足は流れるのに記録ゼロ」を黙って残さない）。"""
    import pandas as pd
    with tempfile.TemporaryDirectory() as d:
        state = Path(d) / "state"
        ctrl = LocalEngineController(strategies_dir=STRAT.parent, state_dir=state, on_log=lambda m: None)
        ctrl.register(STRAT)

        def _boom(_df):
            raise RuntimeError("warmup boom")
        for rb in ctrl.engine._brokers.values():
            rb.warmup_replay = _boom                   # warmup・リプレイを強制失敗させる

        warm = pd.DataFrame({"open": [1.0] * 5, "high": [1.0] * 5, "low": [1.0] * 5, "close": [1.0] * 5},
                            index=pd.date_range("2026-01-01", periods=5, freq="15min"))
        feed = _OkFeed()
        ok = ctrl.start(warmup_df=warm, feed=feed)

        assert ok is False
        assert ctrl.engine.running is False
        assert ctrl.feed is None, "失敗時は feed を止め、足だけ流れる状態を残さない"
        assert ctrl.start_error and "起動に失敗" in ctrl.start_error
        st = ctrl.status()
        assert st["recording"] is False and st["start_error"]


def test_controller_logs_persist_to_file():
    """controller の on_log 経由メッセージが永続ファイルに残る（pythonw でも消えない）。"""
    with tempfile.TemporaryDirectory() as d:
        logdir = Path(d) / "logs"
        old_dir, old_flag = flog._LOG_DIR, flog._file_logging
        try:
            flog._LOG_DIR = logdir
            flog.set_file_logging(True)
            state = Path(d) / "state"
            ctrl = LocalEngineController(strategies_dir=STRAT.parent, state_dir=state, on_log=lambda m: None)
            ctrl.register(STRAT)
            ctrl.start(warmup_df=None, feed=_BusyFeed())   # ⚠ start_error を on_log → 永続化

            p = flog.log_file_path()
            assert p.exists(), "永続ログファイルが作られる"
            text = p.read_text(encoding="utf-8")
            assert "記録停止中" in text or "使用中" in text, "起動失敗が永続ログに残る"
        finally:
            flog._LOG_DIR, flog._file_logging = old_dir, old_flag


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
