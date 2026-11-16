# -*- coding: utf-8 -*-
"""足を 1 本ずつ渡す経路は、どれも出来高を live と同じく戦略へ渡す（出来高を読む戦略がある）。

対象＝offline_driver.run_pine（BT の on_bar 経路）・RealtimeBroker.warmup_replay（起動時の再生）・
RealtimeBroker.prime（flat で指標だけ温める）。df に volume 列が無いときは 0。
"""
import pandas as pd

from app.engine import RealtimeBroker, run_pine


class _VolumeRecorder:
    """受け取った出来高を記録するだけの戦略（注文は出さない）。"""
    interval = 15
    qty_per_entry = 1

    def reset(self):
        self.seen = []

    def on_bar(self, bar):
        self.seen.append(bar.volume)
        return []


def _df(with_volume=True):
    idx = pd.date_range("2026-11-16 08:45", periods=4, freq="15min")
    d = {"open": [1.0] * 4, "high": [2.0] * 4, "low": [0.5] * 4, "close": [1.5] * 4}
    if with_volume:
        d["volume"] = [10.0, 20.0, 30.0, 40.0]
    return pd.DataFrame(d, index=idx)


def test_run_pine_passes_volume():
    st = _VolumeRecorder()
    run_pine(st, _df())
    assert st.seen == [10.0, 20.0, 30.0, 40.0]


def test_run_pine_without_volume_column_is_zero():
    st = _VolumeRecorder()
    run_pine(st, _df(with_volume=False))
    assert st.seen == [0.0] * 4


def test_warmup_replay_and_prime_pass_volume():
    for method in ("warmup_replay", "prime"):
        st = _VolumeRecorder(); st.reset()
        rb = RealtimeBroker(st, name="t", interval=15)
        getattr(rb, method)(_df())
        assert st.seen == [10.0, 20.0, 30.0, 40.0], method
