# -*- coding: utf-8 -*-
"""建玉復元（再起動でスナップショットから建玉＋TP復元・D15 改訂 2026-06-24）テスト。

方針転換：旧版は「flat＝建玉/TP を復元しない」だったが、それだと夜建てた玉が翌朝の再起動で
決済発火せず管理不能になる。→ `RealtimeBroker.snapshot()/restore()` で建玉＋出口状態を復元する。
  R1 round-trip：建玉→snapshot→（新 broker）restore で broker/戦略状態が一致。
  R2 filled_ids 復元で TP 二重決済を防ぐ（約定済み TP は再アームされない）。
  R3 flat は snapshot=None。
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.engine.realtime_broker import RealtimeBroker  # noqa: E402


class FakeStrat:
    """最小の戦略スタブ（snapshot/restore が読む属性＋on_bar）。"""
    def __init__(self):
        self.reset()

    def reset(self):
        self.signup = 0
        self.tp1 = np.nan; self.tp2 = np.nan; self.zz_p1 = np.nan
        self._prev_size = 0
        self.position_size = 0; self.position_avg_price = 0.0
        self.entry_bar = -1; self.bars_since_entry = -1

    def on_bar(self, bar):
        return []


def _rb():
    return RealtimeBroker(FakeStrat(), name="X", interval=15)


# ───────────────────────────── R3 ─────────────────────────────
def test_snapshot_none_when_flat():
    assert _rb().snapshot() is None


# ───────────────────────────── R1 ─────────────────────────────
def test_round_trip():
    rb = _rb(); bk = rb.bk
    bk.pos_dir = 1; bk.pos_qty = 2; bk.avg_price = 70000.0; bk.entry_bar = 5
    bk.trade_id = 3; bk.entry_ts = "2026-06-24 02:45:00"
    bk._filled_ids = {"TP1_L"}
    bk._book = {"TP2_L": {"qty": 1, "limit": 70200.0, "stop": np.nan, "comment": "TP2_C"}}
    rb._bar_index = 10
    rb.strategy.tp1 = 70100.0; rb.strategy.tp2 = 70200.0; rb.strategy.zz_p1 = 69900.0
    rb.strategy.signup = 1

    snap = rb.snapshot()
    assert snap is not None and snap["pos_dir"] == 1 and snap["pos_qty"] == 2
    assert "TP1_L" in snap["filled_ids"] and snap["strat"]["tp1"] == 70100.0

    rb2 = _rb(); rb2._bar_index = 30          # warmup 後の bar index 相当
    assert rb2.restore(snap)
    b2 = rb2.bk
    assert (b2.pos_dir, b2.pos_qty, b2.avg_price, b2.trade_id) == (1, 2, 70000.0, 3)
    assert b2._filled_ids == {"TP1_L"}
    assert b2.entry_bar == 30                  # 現在 bar_index に再アンカー（次足から TP 発火可）
    assert "TP2_L" in b2._book
    assert (rb2.strategy.tp1, rb2.strategy.tp2, rb2.strategy.zz_p1) == (70100.0, 70200.0, 69900.0)
    assert rb2.strategy._prev_size == b2.position_size      # just_entered 再発火防止
    assert rb2._last_tid == 3                                # 復元玉を新規/決済で再記録しない


# ───────────────────────────── R2 ─────────────────────────────
def test_filled_ids_prevents_double_tp():
    """TP1 約定済みを復元 → 戦略が毎バー TP1/TP2 を再 emit しても broker は TP1 を再アームしない。"""
    rb = _rb(); rb._bar_index = 5
    snap = {"pos_dir": 1, "pos_qty": 2, "avg_price": 70000.0, "entry_ts": "t",
            "trade_id": 1, "filled_ids": ["TP1_L"], "book": {}, "bars_held": 3,
            "strat": {"signup": 0, "tp1": 70100.0, "tp2": 70200.0, "zz_p1": 69900.0}}
    rb.restore(snap)
    rb.bk.submit([{"t": "exit", "id": "TP1_L", "qty": 1, "limit": 70100.0},
                  {"t": "exit", "id": "TP2_L", "qty": 1, "limit": 70200.0}])
    assert "TP1_L" not in rb.bk._book     # 約定済み → 再アームしない（二重決済防止）
    assert "TP2_L" in rb.bk._book          # 未約定 → アーム


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    ok = 0
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
    print("建玉復元（snapshot/restore・D15改訂）テスト")
    sys.exit(0 if _run_all() else 1)
