# -*- coding: utf-8 -*-
"""ブリッジ・プロセス制御テスト（実ブリッジは起動しない・安全に検証）。"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.engine import BridgeProcess, LocalEngineController  # noqa: E402

STRAT = ROOT / "strategies" / "DT_Stochastic"


def test_bridge_process_basic():
    logs = []
    # 環境非依存：閉じているポートで判定（実ブリッジの 8001 を踏まない）
    bp = BridgeProcess(exe_path=ROOT / "does_not_exist.exe", webhook_port=59999, on_log=logs.append)
    assert bp.is_up() is False
    assert bp.started_by_dashboard() is False
    assert bp.is_running() is False
    assert isinstance(bp.kabu_ok(), bool)           # 接続不可でも bool を返す（例外を出さない）
    assert bp.start() is False                       # port 閉＆exe 無し → False＋ログ
    assert any("見つかりません" in m for m in logs)
    bp.stop()                                        # 起動していなくても安全


def test_controller_bridge_wiring():
    with tempfile.TemporaryDirectory() as d:
        ctrl = LocalEngineController(strategies_dir=STRAT.parent, state_dir=Path(d) / "state",
                                     bridge_url="http://localhost:59999/webhook",
                                     bridge_exe=ROOT / "nope.exe", on_log=lambda m: None)
        assert hasattr(ctrl, "bridge")
        st = ctrl.status()
        for k in ("running", "kabu", "bridge", "bridge_self", "feed", "strategies"):
            assert k in st, f"status に {k} が無い"
        ext = ctrl.poll_external()
        assert {"kabu", "bridge", "bridge_self", "feed"} <= set(ext)
        assert st["bridge"] is False
        assert ctrl.start_bridge() is False          # port 閉＆exe 無し
        ctrl.stop_bridge()


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
    print("ブリッジ・プロセス制御テスト")
    sys.exit(0 if _run_all() else 1)
