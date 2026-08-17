# -*- coding: utf-8 -*-
"""テスト共通セットアップ。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# テスト中は永続ファイルログを抑止（data/logs を汚さない）。個別テストで必要なら再有効化する。
try:
    from app.feed import logger as _flog
    _flog.set_file_logging(False)
except Exception:
    pass


@pytest.fixture(autouse=True)
def forbid_real_bridge_io(monkeypatch):
    """テストが実ブリッジ／実ネットワークへ出ることを構造的に禁止する安全網（全テスト自動・多層防御）。

    背景：2026-06-24、ライブ取引中に pytest を走らせたところ test_controller が
    稼働中の本物ブリッジ(localhost:8001)へ実 webhook を 42 件 POST してしまった。
    どのテストからも・将来のどんなテストからも実送信が起きないことを autouse で保証する。

    ① BridgeSender.send → 捕捉スタブ（送らずに記録）。テストは BridgeSender.sent で内容検証できる。
    ② bridge_sender 内の urllib urlopen を遮断（BridgeSender を経由しない別経路の実 POST も止める）。
    monkeypatch なのでテストごとに自動復元。実ネットワークは一切使わない。
    """
    from app.engine import bridge_sender as _bs

    _bs.BridgeSender.sent = []                      # 捕捉箱（クラス共有・各テスト先頭でクリア）

    def _capture(self, webhook):
        _bs.BridgeSender.sent.append(webhook)
        return '{"status": "captured-in-test"}'

    def _blocked(*a, **k):
        raise RuntimeError("テスト中の実ネットワーク送信は禁止です（conftest forbid_real_bridge_io）")

    monkeypatch.setattr(_bs.BridgeSender, "send", _capture, raising=True)
    monkeypatch.setattr(_bs.urllib.request, "urlopen", _blocked, raising=True)
    yield
    _bs.BridgeSender.sent = []
