# -*- coding: utf-8 -*-
"""共有エンジン — 戦略コントラクト（全 Python 戦略で共有）。

戦略は「1バーで動く」＝確定足ごとに on_bar(bar)/step(A,i) が呼ばれ、注文リストを返す。

★正本プロトコル（TV 忠実約定 PineBroker・2026-06-15〜・authoring標準 v3.6 §8.1）:
  {"t": "entry", "dir": +1|-1, "qty": int}              成行・次バー始値（逆方向はドテン）
  {"t": "close", "qty": int|None}                       成行・次バー始値（None=全部）
  {"t": "exit",  "id": str, "qty": int|None, "limit": px|None, "stop": px|None}
                                                        建ち注文（OCO・毎バー上書き・各 ID 一度きり約定）
  {"t": "cancel","id": str}                             建ち注文の取消
  約定（次バー始値・指値/逆指値イントラバー）はエンジン（PineBroker）の仕事＝戦略は注文を返すだけ。
  戦略はエンジン注入の position_size / position_avg_price / entry_bar / bars_since_entry を読む。
  正本 BT＝run_pine_fast、live 相当＝run_pine（_engine/backtest.py）。

（旧プロトコル {"action":"buy"|"sell"|"close"} は非正本・未使用＝廃止。正本は上記 t 付きプロトコル）。

★この契約・エンジンは戦略フォルダに置かない（共有＝strategies/_engine/）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class Bar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class Strategy(Protocol):
    """全戦略が満たす最小契約（reset / on_bar / build）。"""
    def reset(self) -> None: ...
    def on_bar(self, bar: Bar) -> list[dict]: ...
