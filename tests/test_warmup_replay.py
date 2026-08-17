# -*- coding: utf-8 -*-
"""ウォームアップ・リプレイ（restore 置換・TV 同一シーケンス）テスト。

起動時に履歴足を live と同一 on_bar でブローカー駆動して現在建玉・出口・指標バッファを
履歴から再構築する `RealtimeBroker.warmup_replay()` を検証する。これにより snapshot/restore
（D15）は startup から不要になった（再構築済みなので保有玉の決済が発火し続ける）。

  W1 決済済みトレード一致：warmup_replay の fills == offline BT(run_pine) の「EOD 以外の fill」。
  W2 建玉保持：warmup 末尾で保有中なら、その残建玉 == run_pine が EOD で強制決済した玉。
  W3 live 継続：warmup 後に確定足を投入してもクラッシュせず index が連続する。
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.engine.offline_driver import run_pine          # noqa: E402
from app.engine.realtime_broker import RealtimeBroker    # noqa: E402


class CycleStrat:
    """決定的に建てる/返すスタブ：flat なら 7 本ごとに Long 3 枚、保有 4 本で成行クローズ。
    driver が注入する position_size / bars_since_entry を読む（run_pine・warmup_replay 共通）。"""
    def __init__(self):
        self.qty_per_entry = 3
        self.reset()

    def reset(self):
        self.position_size = 0
        self.position_avg_price = 0.0
        self.entry_bar = -1
        self.bars_since_entry = -1
        self._n = 0

    def on_bar(self, bar):
        self._n += 1
        if self.position_size == 0:
            if self._n % 7 == 0:
                return [{"t": "entry", "dir": 1, "qty": 3, "comment": "L"}]
        elif self.bars_since_entry >= 4:
            return [{"t": "close", "qty": None, "comment": "x"}]
        return []


def _mkdf(n: int) -> pd.DataFrame:
    """決定的な合成 OHLC（DatetimeIndex・15分足）。"""
    idx = pd.date_range("2026-01-05 09:00", periods=n, freq="15min")
    base = 30000 + np.cumsum(np.sin(np.arange(n) / 3.0) * 20)
    o = base
    h = base + 15
    l = base - 15
    c = base + np.cos(np.arange(n) / 2.0) * 10
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c,
                         "volume": np.full(n, 100.0)}, index=idx)


def _split_fills(fills):
    if fills is None or len(fills) == 0:
        return fills, fills
    eod = fills[fills["exit_reason"] == "end_of_data"]
    closed = fills[fills["exit_reason"] != "end_of_data"]
    return closed, eod


def test_warmup_matches_bt_closed_and_retains_open():
    df = _mkdf(120)                                   # 末尾で保有中になる長さ（建/返サイクル）
    fbt = run_pine(CycleStrat(), df)
    closed, eod = _split_fills(fbt)

    rb = RealtimeBroker(CycleStrat(), name="X", interval=15)
    rb.reset()
    rb.warmup_replay(df)
    wf = rb.fills

    # W1: 決済済みトレード一致
    assert len(wf) == len(closed), f"closed 本数 wf={len(wf)} bt={len(closed)}"
    for col in ("trade_id", "direction", "qty", "entry_price", "exit_price", "pnl_pt"):
        a = wf[col].reset_index(drop=True)
        b = closed[col].reset_index(drop=True)
        if col in ("entry_price", "exit_price", "pnl_pt"):
            assert ((a - b).abs() < 1e-6).all(), f"{col} 不一致"
        else:
            assert (a == b).all(), f"{col} 不一致"

    # W2: 建玉保持（このフィクスチャは末尾で保有中になる設計）
    assert len(eod) > 0, "フィクスチャが末尾 flat（建玉保持を検証できない）"
    assert rb.bk.pos_dir != 0, "warmup_replay が建玉を保持していない"
    edir = 1 if eod.iloc[0]["direction"] == "Long" else -1
    assert rb.bk.pos_dir == edir
    assert rb.bk.pos_qty == int(eod["qty"].sum())
    assert abs(rb.bk.avg_price - float(eod.iloc[0]["entry_price"])) < 1e-6

    # index 連続：warmup 後 _bar_index == n-1、次 live で n に進む
    assert rb._bar_index == len(df) - 1


def test_warmup_then_live_bar_no_crash():
    df = _mkdf(120)
    rb = RealtimeBroker(CycleStrat(), name="X", interval=15)
    rb.reset()
    rb.warmup_replay(df)
    bi = rb._bar_index
    rb.sender = None
    nxt = {"datetime": df.index[-1] + pd.Timedelta(minutes=15),
           "open": 30010.0, "high": 30030.0, "low": 29990.0, "close": 30000.0, "volume": 100.0}
    rb.on_bar_close(nxt)                              # クラッシュしないこと
    assert rb._bar_index == bi + 1                    # live で 1 本進む


def test_warmup_empty_df_is_noop():
    rb = RealtimeBroker(CycleStrat(), name="X", interval=15)
    rb.reset()
    rb.warmup_replay(_mkdf(0))
    assert rb.bk.pos_dir == 0 and len(rb.fills) == 0
