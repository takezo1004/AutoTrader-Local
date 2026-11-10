# -*- coding: utf-8 -*-
"""引けの板寄せ tick で成行を約定させない（RealtimeBroker.on_tick の場間ガード）テスト。

セッション最後の足（06:00／15:45 の板寄せ特別足）で戦略が予約した成行は、
その直後に届く引けの板寄せ約定値の tick（場間）では約定せず、次のセッションの最初の tick（寄付）で
1 回だけ約定・送出する＝BT（次足始値）・TradingView（06:00 の足の確定は 08:45 の最初の tick）と同じ。

  C1 夜間引け：06:00 の足で予約 → 06:00:03 の板寄せ tick では約定しない → 08:45:00 の寄付 tick で寄付値で 1 回。
  C2 再起動：06:00 の足まで warmup_replay した新しいブローカーでも、08:45:00 の tick で 1 回だけ。プレオープンの tick は無視。
  C3 日中引け：15:45 の足で予約 → 15:45:05 の tick では約定しない → 17:00:00 の tick で 1 回。
  C4 場中の tick は従来どおり（新バー最初の tick で約定）。
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.engine.realtime_broker import RealtimeBroker    # noqa: E402


class EnterAtStrat:
    """決定的な stub：flat で、足の時刻が enter_at のときだけ Long 3 枚を予約する。保有 4 本で成行クローズ。"""
    def __init__(self, enter_at: str):
        self.enter_at = enter_at                 # "06:00" など
        self.qty_per_entry = 3
        self.reset()

    def reset(self):
        self.position_size = 0
        self.position_avg_price = 0.0
        self.entry_bar = -1
        self.bars_since_entry = -1

    def on_bar(self, bar):
        ts = pd.Timestamp(bar.ts)
        if self.position_size == 0:
            if ts.strftime("%H:%M") == self.enter_at:
                return [{"t": "entry", "dir": 1, "qty": 3, "comment": "L"}]
        elif self.bars_since_entry >= 4:
            return [{"t": "close", "qty": None, "comment": "x"}]
        return []


def _bars(times: list[str], base: float = 60000.0) -> pd.DataFrame:
    """与えた時刻の 15 分足を決定的に作る（単調に 5 円ずつ上げる・特別足は 4 値同一）。"""
    rows = []
    for i, t in enumerate(times):
        ts = pd.Timestamp(t)
        px = base + 5 * i
        special = ts.strftime("%H:%M") in ("06:00", "15:45")
        rows.append({"datetime": ts, "open": px, "high": px if special else px + 10,
                     "low": px if special else px - 10, "close": px, "volume": 100.0})
    return pd.DataFrame(rows).set_index("datetime")


def _feed(rb: RealtimeBroker, df: pd.DataFrame) -> None:
    """各足＝始値 tick → 確定足、の順で流す（形成中足の tick は始値だけで足りる）。"""
    for ts, r in df.iterrows():
        rb.on_tick(r["open"], ts)
        rb.on_bar_close({"datetime": ts, "open": r["open"], "high": r["high"],
                         "low": r["low"], "close": r["close"], "volume": r["volume"]})


def _entries(rb: RealtimeBroker) -> list[dict]:
    return [w for w in rb.webhooks if w.get("strategy", {}).get("order_action") == "buy"]


NIGHT = ["2026-11-10 05:15", "2026-11-10 05:30", "2026-11-10 05:45", "2026-11-10 06:00"]   # 火曜の早朝（夜間の終わり）
DAY = ["2026-11-10 15:15", "2026-11-10 15:30", "2026-11-10 15:45"]                           # 火曜の日中の終わり


def test_c1_night_close_auction_tick_does_not_fill():
    rb = RealtimeBroker(EnterAtStrat("06:00"), name="t", interval=15)
    _feed(rb, _bars(NIGHT))
    assert rb.bk.pos_dir == 0 and not _entries(rb)                       # 06:00 の足では予約だけ
    rb.on_tick(60940.0, pd.Timestamp("2026-11-10 06:00:03"))             # 引けの板寄せ約定値の tick（場間）
    assert rb.bk.pos_dir == 0 and not _entries(rb), "板寄せ tick で約定してはいけない"
    rb.on_tick(60810.0, pd.Timestamp("2026-11-10 08:45:00"), bar_open=60805.0)   # 次のセッションの最初の tick
    ents = _entries(rb)
    assert rb.bk.pos_dir == 1 and len(ents) == 1
    assert float(ents[0]["strategy"]["order_price"]) == 60805.0, "寄付値で約定する"


def test_c2_restart_warmup_then_opening_tick_fills_once():
    rb = RealtimeBroker(EnterAtStrat("06:00"), name="t", interval=15)
    rb.warmup_replay(_bars(NIGHT))                                       # 再起動＝06:00 の足まで再生（送出なし）
    assert rb.bk.pos_dir == 0 and not rb.webhooks
    rb.on_tick(60700.0, pd.Timestamp("2026-11-10 08:30:00"))             # プレオープンの tick（場間）
    assert rb.bk.pos_dir == 0 and not _entries(rb)
    rb.on_tick(60810.0, pd.Timestamp("2026-11-10 08:45:00"), bar_open=60805.0)
    rb.on_tick(60820.0, pd.Timestamp("2026-11-10 08:45:07"))
    ents = _entries(rb)
    assert rb.bk.pos_dir == 1 and len(ents) == 1
    assert float(ents[0]["strategy"]["order_price"]) == 60805.0


def test_c3_day_close_auction_tick_does_not_fill():
    rb = RealtimeBroker(EnterAtStrat("15:45"), name="t", interval=15)
    _feed(rb, _bars(DAY))
    rb.on_tick(60300.0, pd.Timestamp("2026-11-10 15:45:05"))             # 日中引けの板寄せ tick
    assert rb.bk.pos_dir == 0 and not _entries(rb)
    rb.on_tick(60350.0, pd.Timestamp("2026-11-10 17:00:00"), bar_open=60345.0)   # 夜間の最初の tick
    ents = _entries(rb)
    assert rb.bk.pos_dir == 1 and len(ents) == 1
    assert float(ents[0]["strategy"]["order_price"]) == 60345.0


def test_c4_intraday_ticks_unchanged():
    rb = RealtimeBroker(EnterAtStrat("10:00"), name="t", interval=15)
    _feed(rb, _bars(["2026-11-10 09:30", "2026-11-10 09:45", "2026-11-10 10:00"]))
    assert rb.bk.pos_dir == 0 and not _entries(rb)
    rb.on_tick(60020.0, pd.Timestamp("2026-11-10 10:15:01"))             # 場中＝新バー最初の tick で約定
    ents = _entries(rb)
    assert rb.bk.pos_dir == 1 and len(ents) == 1
    assert float(ents[0]["strategy"]["order_price"]) == 60020.0
