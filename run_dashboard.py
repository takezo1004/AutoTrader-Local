# -*- coding: utf-8 -*-
"""起動①: ローカル版ダッシュボード（GUI）。

  python run_dashboard.py

戦略の登録・パラメータ調整・内蔵バックテスト・dry-run・実行/停止 を行う司令塔。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.dashboard.dashboard import main  # noqa: E402

if __name__ == "__main__":
    # タスクバーへ独立アイコンでピン留めできるよう固有の AppUserModelID を設定（Windows）
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("N225.LocalEngineDashboard")
    except Exception:
        pass
    main()
