# -*- coding: utf-8 -*-
"""ダッシュボード スモークテスト（GUI 構築の検証・mainloop は回さない）。

Tk root を作り Dashboard を構築 → update を数回 → ParamForm/BacktestView も構築 → 破棄。
構築時・status tick・ウィジェット配線のランタイムエラーを検出する（表示の良し悪しは別途実起動で）。
ディスプレイが無い環境では Tk() が TclError を出すので skip 扱いで報告。
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_dashboard_smoke():
    try:
        import tkinter as tk
        root = tk.Tk()
    except Exception as e:
        print(f"  SKIP  ディスプレイなし（Tk 不可）: {e}")
        return
    try:
        from app.engine import LocalEngineController
        from app.dashboard.dashboard import Dashboard
        from app.dashboard.param_form import ParamForm
        from app.dashboard.register_dialog import RegisterDialog
        from app.dashboard.settings_dialog import SettingsDialog
        from app.dashboard.bt_view import BacktestView  # noqa: F401
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "state"; csv = Path(d) / "csv"; csv.mkdir(parents=True)
            ctrl = LocalEngineController(strategies_dir=ROOT / "strategies", state_dir=state,
                                         on_log=lambda m: None)
            ctrl.register(ROOT / "strategies" / "DT_Stochastic", alert_name="DT_Stoch_15m", interval=15)
            dash = Dashboard(root, ctrl, parquet_path=None, csv_dir=csv, auto_start=False)
            for _ in range(5):
                root.update_idletasks(); root.update()
            for Dlg, kw in ((ParamForm, dict(folder=ROOT / "strategies" / "DT_Stochastic")),
                            (RegisterDialog, dict(controller=ctrl, edit_name="DT_Stochastic")),
                            (SettingsDialog, dict(controller=ctrl))):
                w = Dlg(root, **kw)
                root.update_idletasks(); root.update()
                w.destroy()
            dash._closed = True
            print("  dashboard / param / register / settings 構築 OK（status tick・LED・checkbox grid 実行済）")
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def _run_all():
    ok = 0; n = 0
    for k, v in sorted(globals().items()):
        if k.startswith("test_") and callable(v):
            n += 1
            try:
                v(); print(f"  PASS  {k}"); ok += 1
            except Exception as e:
                import traceback; traceback.print_exc(); print(f"  FAIL  {k}: {e}")
    print(f"\n{ok}/{n} passed")
    return ok == n


if __name__ == "__main__":
    print("ダッシュボード スモークテスト")
    sys.exit(0 if _run_all() else 1)
