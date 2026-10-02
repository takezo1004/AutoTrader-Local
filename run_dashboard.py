# -*- coding: utf-8 -*-
"""起動①: ローカル版ダッシュボード（GUI）。

  python run_dashboard.py

戦略の登録・パラメータ調整・内蔵バックテスト・dry-run・実行/停止 を行う司令塔。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.bridge_launcher import ensure_bridge_running  # noqa: E402
from app.dashboard.dashboard import main  # noqa: E402

if __name__ == "__main__":
    # タスクバーへ独立アイコンでピン留めできるよう固有の AppUserModelID を設定（Windows）
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("N225.LocalEngineDashboard")
    except Exception:
        pass
    # 発注はブリッジが行うので、ダッシュボードを開く前に起動しておく
    # （実体は開発キットが作る。既定の導入先は Program Files・詳細＝app/bridge_launcher.py）。
    _ok, _msg = ensure_bridge_running()
    print(("[bridge] " if _ok else "[bridge][WARN] ") + _msg)
    main()
