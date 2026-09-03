# -*- coding: utf-8 -*-
"""ブリッジ（別製品の C#/WPF アプリ・kabu 版 N225BrokerBridge / 楽天RSS版 N225RssBrokerBridge）のプロセス制御＋証券会社ツール確認。

ダッシュボードから「kabu 確認 → ブリッジ起動 → オートトレード起動」を一元操作するための土台。
既存 `n225_brokerbridge_dashboard.py` の方式を踏襲:
  - kabu Station 確認 = HTTP GET http://localhost:18080/kabusapi/（HTTPError でも到達=OK / Timeout=NG）。
  - ブリッジ起動 = subprocess.Popen([exe], cwd=exe_dir)。停止 = terminate→wait(5)→kill。
  - 実行中判定 = proc.poll() is None。
※ブリッジは別製品＝コード共有しない（D1/D2）。ここは「外部アプリのプロセス起動」だけ（import でない）。
  exe パスは設定（dev 既定＝開発ビルド・配布時はインストール先を設定）。
"""
from __future__ import annotations

import os
import socket
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

# dev 既定: N225LocalEngine の隣の N225BrokerBridge 開発ビルド（配布時は settings で上書き）。
_TS_ROOT = Path(__file__).resolve().parents[3]        # …/N225TradingSystem
DEFAULT_BRIDGE_EXE = (_TS_ROOT / "N225BrokerBridge" / "src" / "N225BrokerBridge.UI"
                      / "bin" / "Debug" / "net8.0-windows" / "N225BrokerBridge.UI.exe")
KABU_HEALTH_URL = "http://localhost:18080/kabusapi/"
KABU_TIMEOUT = 1.5


def process_running(image_name: str) -> bool:
    """Windows の tasklist でプロセスの有無を見る（追加ライブラリ無し・コンソールを出さない）。"""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/NH"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout or ""
        return image_name.lower() in out.lower()
    except Exception:
        return False


class BridgeProcess:
    def __init__(self, exe_path=None, kabu_url: str = KABU_HEALTH_URL, webhook_port: int = 8001,
                 on_log=None, health: dict | None = None):
        # health＝証券会社ツールの稼働確認方法（product_profile の broker_health）。
        #   {"mode":"http","url":...}      kabu ステーション（API 口に HTTP）
        #   {"mode":"process","process":..} 楽天 マーケットスピード II（プロセスの有無・RSS に HTTP 口は無い）
        self.exe_path = Path(exe_path) if exe_path else DEFAULT_BRIDGE_EXE
        self.health = dict(health or {"mode": "http", "url": kabu_url})
        self.kabu_url = self.health.get("url") or kabu_url
        self.webhook_port = int(webhook_port)
        self.on_log = on_log or (lambda m: None)
        self._proc: subprocess.Popen | None = None

    # ---- 証券会社ツール確認（kabu＝HTTP ヘルスチェック／楽天＝プロセス）----
    def kabu_ok(self) -> bool:
        """名前は旧来のまま（呼び出し側互換）。意味は「証券会社ツールが稼働しているか」。"""
        if str(self.health.get("mode", "http")).lower() == "process":
            return process_running(str(self.health.get("process") or "MarketSpeed2.exe"))
        try:
            req = urllib.request.Request(self.kabu_url, method="GET")
            with urllib.request.urlopen(req, timeout=KABU_TIMEOUT) as resp:
                _ = resp.status
            return True
        except urllib.error.HTTPError:
            return True                      # 404 等でも到達できている = 起動中
        except Exception:
            return False                     # Timeout/接続不可 = 未起動

    # ---- webhook ポートで「ブリッジ起動中」を判定（手動起動も検知）----
    def _port_open(self, timeout: float = 0.4) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", self.webhook_port), timeout=timeout):
                return True
        except Exception:
            return False

    def is_up(self) -> bool:
        """ブリッジが起動しているか（**手動起動を含む**・webhookポートで判定）。"""
        return self.started_by_dashboard() or self._port_open()

    def started_by_dashboard(self) -> bool:
        """このダッシュボードが起動したプロセスか（停止可否の判定に使う）。"""
        return self._proc is not None and self._proc.poll() is None

    # ---- ブリッジ起動（二重起動防止：既に up なら起動しない）----
    def start(self) -> bool:
        if self.is_up():                                  # 手動起動含め既に稼働 → 二重起動しない
            self.on_log("ブリッジは既に起動中です（手動起動含む）。二重起動しません。")
            return True
        if not self.exe_path.exists():
            self.on_log(f"ブリッジ exe が見つかりません: {self.exe_path}")
            return False
        try:
            self._proc = subprocess.Popen([str(self.exe_path)], cwd=str(self.exe_path.parent))
            self.on_log(f"ブリッジ起動: {self.exe_path.name}")
            return True
        except Exception as e:
            self.on_log(f"ブリッジ起動エラー: {e}")
            return False

    # ---- ブリッジ停止（ダッシュボード起動分のみ・手動起動は手動で停止）----
    def stop(self) -> None:
        if not self.started_by_dashboard():
            if self._port_open():
                self.on_log("ブリッジは手動起動のためダッシュボードからは停止しません（手動で停止してください）。")
            self._proc = None
            return
        p = self._proc
        try:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=3)
        except Exception:
            pass
        finally:
            self._proc = None
            self.on_log("ブリッジ停止")

    # ---- 実行中判定（旧 API 互換＝起動中か）----
    def is_running(self) -> bool:
        return self.is_up()
