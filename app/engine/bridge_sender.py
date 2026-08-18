# -*- coding: utf-8 -*-
"""注文層 — webhook をブリッジへ POST（ライブ）／仮想シンク（dry-run）。

- BridgeSender : POST localhost:8001/webhook（ブリッジが忠実に発注・D7）。
- VirtualSink  : POST せず webhook を記録（dry-run シミュレーション・外部仕様 F4）。
  仮想 P&L は各 RealtimeBroker の fills（bk.fills）から読む（シグナルは本シンクが保持）。
両者とも send(webhook) インターフェース（RealtimeBroker.sender に渡す）。
"""
from __future__ import annotations

import json
import queue
import threading
import urllib.request

_POS_JA = {"flat": "flat", "long": "long", "short": "short"}


def fmt_trade(webhook: dict, kind: str, suffix: str = "") -> str:
    """売買シグナルの統一ログ形式。kind='仮想'/'本番'。ダッシュボードで緑表示（'[売買' 検出）。"""
    s = webhook["strategy"]
    act = "買い" if s.get("order_action") == "buy" else "売り"
    prev = _POS_JA.get(s.get("prev_market_position"), s.get("prev_market_position"))
    cur = _POS_JA.get(s.get("market_position"), s.get("market_position"))
    line = f"[売買・{kind}] {webhook.get('alert_name')}  {act}×{s.get('order_contracts')}  ({prev}→{cur})"
    return line + (f" → {suffix}" if suffix else "")


class BridgeSender:
    """★2026-07-02 送信キュー化：HTTP POST（timeout 5秒）をフィード/ディスパッチスレッドから分離。

    従来は send() が呼び出しスレッド上で同期 POST しており、ブリッジが遅い/落ちている瞬間に
    シグナルが出ると feed 側が最大 timeout×件数だけ停止するテールリスクがあった。
    全インスタンス共有の**単一キュー＋単一ワーカー**で送信＝全戦略の送信順序を完全保存（FIFO）。
    send() は積んで即返る。結果は従来どおり on_log（[売買・本番]/注文エラー）で通知。
    """
    _queue: queue.Queue | None = None
    _worker_lock = threading.Lock()

    def __init__(self, url: str = "http://localhost:8001/webhook", timeout: float = 5.0,
                 on_log=None):
        self.url = url
        self.timeout = timeout
        self.on_log = on_log or (lambda m: None)
        self.last_outcome = None
        self._ensure_worker()

    # ---- 共有ワーカー ----
    @classmethod
    def _ensure_worker(cls) -> None:
        with cls._worker_lock:
            if cls._queue is None:
                cls._queue = queue.Queue()
                threading.Thread(target=cls._drain, daemon=True, name="bridge-send").start()

    @classmethod
    def _drain(cls) -> None:
        while True:
            sender, webhook = cls._queue.get()
            try:
                sender._send_sync(webhook)
            except Exception:
                pass                      # _send_sync 内で通知済み。ワーカーは絶対に死なない。
            finally:
                cls._queue.task_done()

    @classmethod
    def flush(cls, timeout: float = 6.0) -> None:
        """未送信分の掃き出しを待つ（アプリ終了時のベストエフォート）。"""
        import time as _t
        if cls._queue is None:
            return
        deadline = _t.time() + timeout
        while cls._queue.unfinished_tasks and _t.time() < deadline:
            _t.sleep(0.05)

    # ---- 送信 ----
    def send(self, webhook: dict) -> None:
        """キューに積んで即返る（呼び出しスレッドをブロックしない）。"""
        self._ensure_worker()
        self._queue.put((self, webhook))

    # ★ブリッジは「発注しなかった」場合も HTTP 200 を返す（本文に理由の名前が入る）。
    #   200 を成功と扱うと、自動売買 OFF・パスフレーズ不一致・戦略未登録でも
    #   「[売買・本番]」と記録され、実際には無い建玉を持ったことになる（2026-08-18 判明）。
    DISPATCHED = ("NewOrderDispatched_", "ExitOrderDispatched_", "DotenDispatched_")
    NOT_ORDERED = {
        "AutoTradeDisabled_":     "ブリッジの自動売買が OFF",
        "Authenticated_Failed":   "パスフレーズ不一致",
        "Interpretation_Failed":  "ブリッジが内容を解釈できず",
        "Ignored_":               "ブリッジが見送り（戦略未登録・無効など）",
    }

    def _send_sync(self, webhook: dict) -> str | None:
        try:
            data = json.dumps(webhook).encode("utf-8")
            req = urllib.request.Request(self.url, data=data,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", "replace")
            self.last_outcome = body
            name = (body or "").strip()
            if name in self.DISPATCHED:
                self.on_log(fmt_trade(webhook, "本番", suffix=name))
            else:
                reason = self.NOT_ORDERED.get(name, f"不明な応答: {name}")
                self.on_log(f"⚠ 未発注 {webhook.get('alert_name')}: {reason}"
                            f"（ブリッジは受信したが発注していません）")
            return body
        except Exception as e:
            self.on_log(f"注文エラー {webhook.get('alert_name')}: {e}")
            return None


class VirtualSink:
    """dry-run: POST せず webhook（シグナル）を記録するだけ。"""
    def __init__(self, on_log=None):
        self.signals: list[dict] = []
        self.on_log = on_log or (lambda m: None)

    def send(self, webhook: dict) -> None:
        self.signals.append(webhook)
        self.on_log(fmt_trade(webhook, "仮想"))
