# -*- coding: utf-8 -*-
"""LiveEngine — 確定足/tick を有効戦略へ fan-out（内部仕様 §2・run_one_step 相当）。

feed（OHLCManager）の on_bar_close / on_tick を受け、**有効かつ ready** な各戦略の
RealtimeBroker へ配る。2段階制御（D10 F5）= running（全体）× enabled（戦略ごと）× ready（warmup）。
複数戦略は独立インスタンス＝順次でも安全（Executor は将来 seam）。
"""
from __future__ import annotations

import queue
import threading

try:                                         # 詳細デバッグログ（無くても動く）
    from app.feed.logger import dbg
except Exception:                            # pragma: no cover
    def dbg(*a, **k):
        pass


class LiveEngine:
    def __init__(self, on_log=None):
        self._brokers: dict = {}     # name -> RealtimeBroker
        self._enabled: dict = {}     # name -> bool（戦略ごとの実行可否・段階1）
        self._ready: dict = {}       # name -> bool（warmup 充足）
        self.running = False         # 全体 自動実行/停止（段階2）
        self.on_log = on_log or (lambda m: None)
        # ★2026-07-02 ②：tick/確定足を単一ディスパッチワーカーで直列処理。
        #   - 受信系スレッド（TCP recv／バータイマー）は「積むだけ」＝重い fan-out でブロックしない。
        #   - tick と確定足が同一ワーカーで直列＝従来の「recv スレッドとバータイマースレッドが
        #     同じブローカー状態に同時侵入し得る」競合窓も解消。FIFO で到着順も保存。
        self._dispatch_q: queue.Queue = queue.Queue(maxsize=20000)
        self._dispatch_thread: threading.Thread | None = None
        self._dispatch_lock = threading.Lock()

    # ---- 登録・制御 ----
    def add(self, name: str, rb, enabled: bool = False) -> None:
        self._brokers[name] = rb
        self._enabled[name] = bool(enabled)
        self._ready[name] = False

    def remove(self, name: str) -> None:
        for d in (self._brokers, self._enabled, self._ready):
            d.pop(name, None)

    def upsert(self, name: str, rb, enabled: bool = False, ready: bool = False) -> None:
        """1戦略の原子的な追加/差替（2026-07-02 差分リロード用）。
        feed スレッドは _processing() で dict を列挙するため、サイズが変わる in-place 追加は
        「dictionary changed size during iteration」の競合窓を作る。ここでは新 dict を作って
        **参照ごと差し替える**（列挙側は旧か新のどちらかを丸ごと見る＝安全）。"""
        b = dict(self._brokers); b[name] = rb
        e = dict(self._enabled); e[name] = bool(enabled)
        r = dict(self._ready); r[name] = bool(ready)
        self._brokers, self._enabled, self._ready = b, e, r

    def set_enabled(self, name: str, val: bool) -> None:
        if name in self._enabled:
            self._enabled[name] = bool(val)

    def set_ready(self, name: str, val: bool = True) -> None:
        if name in self._ready:
            self._ready[name] = bool(val)

    def _processing(self):
        # ★記録は全戦略・常時：warmup 充足(ready)なら enabled に関係なく処理する。
        #   注文するか否かは各 RealtimeBroker の sender（enabled=BridgeSender / 無効=None）で決まる。
        return [(n, rb) for n, rb in self._brokers.items() if self._ready.get(n)]

    # ---- 配信（feed コールバック）----
    # ---- ディスパッチワーカー（2026-07-02 ②：受信系スレッドは積むだけ・処理は本ワーカーで直列）----
    def _ensure_dispatch(self) -> None:
        t = self._dispatch_thread
        if t is not None and t.is_alive():
            return
        with self._dispatch_lock:
            t = self._dispatch_thread
            if t is None or not t.is_alive():
                self._dispatch_thread = threading.Thread(target=self._dispatch_loop,
                                                         daemon=True, name="le-dispatch")
                self._dispatch_thread.start()

    def _dispatch_loop(self) -> None:
        while True:
            kind, payload, after = self._dispatch_q.get()
            try:
                if kind == "bar":
                    self._do_confirmed_bar(payload)
                else:
                    self._do_tick(*payload)
                if after is not None:
                    after()
            except Exception as e:
                try:
                    self.on_log(f"dispatch エラー({kind}): {e}")
                except Exception:
                    pass                     # ワーカーは絶対に死なない
            finally:
                self._dispatch_q.task_done()

    def on_confirmed_bar(self, candle: dict, after=None) -> None:
        """確定足をキューに積んで即返る（フィード側スレッドを fan-out でブロックしない）。
        after=fan-out 完了後にワーカー上で呼ぶコールバック（例：建玉スナップショット保存）。"""
        self._ensure_dispatch()
        try:
            self._dispatch_q.put(("bar", candle, after), timeout=2.0)   # 確定足は原則落とさない
        except queue.Full:
            self.on_log("⚠ dispatch キュー満杯：確定足を破棄（ワーカー停滞の疑い・要再起動）")

    def on_tick(self, price: float, ts, bar_open=None, bar_high=None, bar_low=None) -> None:
        self._ensure_dispatch()
        try:
            self._dispatch_q.put_nowait(("tick", (price, ts, bar_open, bar_high, bar_low), None))
        except queue.Full:
            pass                             # tick は最新性が命＝満杯なら捨てる（次 tick で追いつく）

    # ---- 実処理（ディスパッチワーカー上で実行・従来ロジックそのまま）----
    def _do_confirmed_bar(self, candle: dict) -> None:
        if not self.running:
            dbg(f"確定足 {candle.get('datetime')} を受信したが running=False → 全戦略スキップ（記録なし）")
            return
        procs = self._processing()
        try:
            dbg(f"確定足 {candle.get('datetime')} C{float(candle.get('close', 0)):.0f} "
                f"→ fan-out 処理対象 {len(procs)}/{len(self._brokers)} 戦略"
                f"（待機中={[n for n in self._brokers if not self._ready.get(n)]}）")
        except Exception:
            pass
        for n, rb in procs:
            try:
                rb.on_bar_close(candle)
            except Exception as e:
                self.on_log(f"[{n}] on_bar_close エラー: {e}")

    def _do_tick(self, price: float, ts, bar_open=None, bar_high=None, bar_low=None) -> None:
        if not self.running:
            return
        for n, rb in self._processing():
            try:
                rb.on_tick(price, ts, bar_open=bar_open, bar_high=bar_high, bar_low=bar_low)
            except Exception as e:
                self.on_log(f"[{n}] on_tick エラー: {e}")

    # ---- 状態 ----
    def status(self) -> list:
        out = []
        for n, rb in self._brokers.items():
            pos = rb.bk.position_size
            out.append({
                "name": n,
                "enabled": self._enabled.get(n, False),
                "ready": self._ready.get(n, False),
                "position": "flat" if pos == 0 else ("long" if pos > 0 else "short"),
                "size": abs(pos),
                "last_signal": rb.webhooks[-1]["strategy"] if rb.webhooks else None,
                "n_signals": len(rb.webhooks),
            })
        return out
