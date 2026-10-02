# -*- coding: utf-8 -*-
"""単一インスタンスガード（ダッシュボードとヘッドレス run_live で共有）。

なぜ要るか（2026-06-23）:
  ローカル版の tick 入口は TCP :5000 を 1 つだけ bind できる。ダッシュボードとヘッドレス
  (run_live) を同時に起動すると、後発の feed.start() が「使用中」で失敗し、その engine は
  記録ゼロのまま黙って待機する（終夜「トレード履歴ができない」事故の原因）。
  ダッシュボード側には Mutex ガードがあったが run_live には無く、両者が別名で競合し得た。

  → 両エントリポイントで **同じ名前の Windows 名前付き Mutex** を取得し相互排他にする。
    これで :5000 を握る正規インスタンスは常に 1 つだけになり、競合の元を断つ。

非 Windows 等で取得不能なら True を返す（従来どおり起動＝ガードしない）。
"""

# ダッシュボードとヘッドレスで共有する単一の Mutex 名（必ず一致させる）。
MUTEX_NAME = "AutoTraderLocalEngine"


def acquire_single_instance(name: str = MUTEX_NAME):
    """Windows 名前付き Mutex で多重起動を防ぐ。

    戻り値:
      - 既に他インスタンスが起動中: None
      - 取得成功: Mutex ハンドル（プロセス存続中は呼び出し側が保持し続けること）
      - 取得不能な環境（非Windows等）: True（ガードせず従来どおり起動）
    """
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.CreateMutexW(None, False, name)
        if k.GetLastError() == 183:        # ERROR_ALREADY_EXISTS
            return None
        return h
    except Exception:
        return True
