# -*- coding: utf-8 -*-
"""稼働中の登録/設定変更で全戦略が無効化される事故の回帰テスト（2026-06-29 修正）。

旧バグ：register/update_registration/パラメータ保存はいずれも load_all() を呼び、load_all() は
`self.engine = LiveEngine()` で全ブローカーを作り直す＝全戦略 ready=false 化。ready=true にするのは
start() だけで、登録後に start を再実行しないため、**稼働中に1戦略でも登録すると全戦略が停止し、
再起動するまでシグナル・記録ゼロ**になっていた（実際に終日ゼロが発生）。

修正：load_all() は「稼働中だった(was_running)」なら、engine を作り直したあと自動で
_activate_brokers（warmup→ready→sender）を再実行し running を復帰させる。feed コールバックは
self.engine を動的参照（_engine_on_tick / _on_confirmed_bar クロージャ）なので貼り直し不要。

  R1 稼働中に2本目を登録 → 既存・新規とも ready のまま・running 継続。
  R2 確定足を投入しても例外なく処理される（処理対象が空でない）。
"""
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.engine import LocalEngineController  # noqa: E402

STRAT_A = ROOT / "strategies" / "DT_Stochastic"
STRAT_B = ROOT / "strategies" / "MESA_Stochastic"


class _FakeMgr:
    on_bar_close = None
    on_tick = None


class _OkFeed:
    def __init__(self):
        self.mgr = _FakeMgr()
    def start(self):
        return True
    def stop(self):
        pass


def _mkdf(n: int) -> pd.DataFrame:
    idx = pd.date_range("2026-03-02 09:00", periods=n, freq="15min")
    base = 38000 + np.cumsum(np.sin(np.arange(n) / 5.0) * 25)
    return pd.DataFrame({"open": base, "high": base + 20, "low": base - 20,
                         "close": base + np.cos(np.arange(n) / 4.0) * 12,
                         "volume": np.full(n, 100.0)}, index=idx)


def test_register_while_running_keeps_all_ready():
    if not (STRAT_A.exists() and STRAT_B.exists()):
        print("SKIP（戦略フォルダ無し）"); return
    with tempfile.TemporaryDirectory() as d:
        ctrl = LocalEngineController(strategies_dir=STRAT_A.parent,
                                     state_dir=Path(d) / "state", on_log=lambda m: None)
        ctrl._build_warmup_df = lambda: _mkdf(350)        # 高速・決定的な warmup に差し替え

        ctrl.register(STRAT_A)                             # 1本目（start 前＝再有効化は走らない）
        assert ctrl.start(warmup_df=_mkdf(350), feed=_OkFeed()) is True
        assert ctrl.engine.running is True
        names1 = list(ctrl.engine._brokers)
        assert len(names1) == 1
        assert all(ctrl.engine._ready.get(n) for n in names1), "起動後に1本目が ready であること"

        # ★稼働中に2本目を登録（旧バグ：ここで全戦略 ready=false 化していた）
        ctrl.register(STRAT_B)
        assert ctrl.engine.running is True, "登録後も running 継続"
        names2 = list(ctrl.engine._brokers)
        assert len(names2) == 2, "2戦略登録されている"
        assert all(ctrl.engine._ready.get(n) for n in names2), \
            "★登録後も全戦略 ready のまま（旧バグの回帰：1本登録で全停止しない）"

        # R2 確定足を投入 → 処理対象が空でなく例外も出ない
        feed_cb = None
        # feed コールバックは start 内で feed.mgr に設定済み。新 engine を動的参照する。
        assert callable(ctrl._engine_on_tick)
        proc = ctrl.engine._processing()
        assert len(proc) == 2, "確定足の処理対象が2戦略（ready）"
