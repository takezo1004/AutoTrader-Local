"""
live_feed.py  (C1: ブリッジ→AI のリアルタイム足生成・OHLCManager 駆動版)
==================================================================================
ブリッジ AiTickForwarderService が 127.0.0.1:5000 へ改行区切り JSON
  {"timestamp":"YYYY/MM/dd HH:MM:SS","close":<price>,"volume":<vol>}
を送る。本モジュールは TCP サーバとして受信し、**実証済み OHLCManager**(feed/) に流す。
OHLCManager がセッション対応で 15分足を確定 (タイマー確定/ダミー足/板寄せ特別足) する。

★責務: ここは **OHLC ローソク足の生成のみ**。ATR・vol_ratio・特徴量は一切扱わない。
精査メモ: tcp_receiver の「改行フレーミング + 必須キー(timestamp/close/volume)検査 + JSON解析」は妥当なので保持。

★N225LocalEngine v2.0 適合（2026-06-16）:
  - import を自己完結の相対 import に（sys.path ハックを撤去）。
  - on_tick を OHLCManager へ透過（リアルタイム・ブローカー seam）。
  - STATUS_FILE を app/state/ へ。
"""
import json
import socket
import threading
import time
from datetime import datetime
from pathlib import Path

from .ohlc_processor import OHLCManager
from .logger import log_message

HOST = "127.0.0.1"
PORT = 5000
STATUS_FILE = Path(__file__).resolve().parents[1] / "state" / "ai_feed_status.json"  # app/state


def _write_status(connected: bool, last_tick=None):
    """ダッシュボードが読む接続状態(ブリッジ↔AI)を書き出す。"""
    try:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATUS_FILE.write_text(json.dumps({
            "bridge_connected": bool(connected),
            "last_tick": last_tick.strftime("%Y-%m-%d %H:%M:%S") if last_tick else None,
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }), encoding="utf-8")
    except Exception:
        pass


class LiveFeed:
    def __init__(self, on_bar_close=None, on_tick=None, host=HOST, port=PORT):
        self.mgr = OHLCManager(on_bar_close=on_bar_close, on_tick=on_tick)
        self.host = host
        self.port = port
        self._running = False
        self._server = None
        self._last_status_w = 0.0

    def start(self) -> bool:
        """tick 入口（TCP待受）を開始。★ポート使用中なら接続しない（安全＝他の tick 使用を壊さない）。

        戻り: True=接続開始 / False=ポート使用中などで接続しなかった。
        """
        if self._running:                    # 二重起動防止
            return True
        # ★同期 bind で「使用中」を確実に検出（SO_REUSEADDR は使わない＝Windows の横取りを防ぐ）。
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            srv.bind((self.host, self.port))
            srv.listen()
        except OSError as e:
            try:
                srv.close()
            except Exception:
                pass
            log_message(f"ポート {self.host}:{self.port} は使用中のため接続しません"
                        f"（安全：他が tick を使用中の可能性）: {e}")
            return False
        self._server = srv
        self.mgr.start_ohlc_timer()          # セッション対応の確定タイマー
        self._running = True
        threading.Thread(target=self._serve, daemon=True).start()
        return True

    def _serve(self):
        log_message(f"TCP受信サーバ起動 {self.host}:{self.port} (ブリッジ接続待ち)")
        while self._running:
            try:
                conn, addr = self._server.accept()
            except OSError:
                break
            log_message(f"ブリッジ接続: {addr}")
            _write_status(True)
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        buf = ""
        try:
            while self._running:
                chunk = conn.recv(2048).decode("utf-8", errors="replace")
                if not chunk:
                    break
                buf += chunk
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if line:
                        self._on_line(line)
        except Exception as e:
            log_message(f"受信エラー: {e}")
        finally:
            conn.close()
            _write_status(False)
            log_message("ブリッジ切断")

    def _on_line(self, line: str):
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            return
        if not all(k in d for k in ("timestamp", "close", "volume")):
            return
        try:
            tick_time = datetime.strptime(d["timestamp"], "%Y/%m/%d %H:%M:%S")
            price = float(d["close"])
            vol = float(d["volume"])
        except (ValueError, TypeError):
            return
        if price <= 0:
            return
        # ★出来高は「売買高時刻 volume_time」のバーへ（任意・無ければ price-time 流用＝従来動作）。
        #   価格(OHLC)は timestamp(=価格時刻)、出来高は volume_time で別バー割り当て（2026-06-24）。
        vt = None
        if d.get("volume_time"):
            try:
                vt = datetime.strptime(d["volume_time"], "%Y/%m/%d %H:%M:%S")
            except (ValueError, TypeError):
                vt = None

        # ★拡張(2026-06-29): 始値/高値/安値＋各時刻。無い/null は None＝従来の close 標本動作にフォールバック。
        def _px(key):
            v = d.get(key)
            try:
                return float(v) if v is not None else None
            except (ValueError, TypeError):
                return None

        def _tm(key):
            s = d.get(key)
            if not s:
                return None
            try:
                return datetime.strptime(s, "%Y/%m/%d %H:%M:%S")
            except (ValueError, TypeError):
                return None

        op, op_t = _px("open"), _tm("open_time")
        hi, hi_t = _px("high"), _tm("high_time")
        lo, lo_t = _px("low"), _tm("low_time")
        # ※ bid/ask/vwap/tick_dir 等(歩み値系)は受信はするが現状未使用＝将来の戦略/ストアで消費する。
        self.mgr.update_ohlc(price, vol, tick_time, volume_time=vt,
                             op=op, op_t=op_t, hi=hi, hi_t=hi_t, lo=lo, lo_t=lo_t)
        now = time.time()
        if now - self._last_status_w >= 3.0:        # 3秒スロットルで last_tick 更新
            self._last_status_w = now
            _write_status(True, tick_time)

    def stop(self):
        self._running = False
        try:
            if self._server:
                self._server.close()
        except Exception:
            pass


if __name__ == "__main__":
    def _show(bar):
        log_message(f"→ 確定足受領 {bar['datetime']:%m/%d %H:%M} C{bar['close']:.0f}")
    feed = LiveFeed(on_bar_close=_show)
    feed.start()
    log_message("live_feed 起動。ブリッジ(tick転送)が接続すると足が流れます。Ctrl+C で終了。")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        feed.stop()
        log_message("終了")
