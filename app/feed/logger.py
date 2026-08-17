"""簡易ロガー (n225tradingAI2 の log_message 互換・自己完結版)。cp932 コンソールでも落ちない。

★ダッシュボード連携: add_sink(fn) で登録した関数にも生メッセージを渡す
  （feed/OHLCManager の「TCP待受/ブリッジ接続/ポート使用中/確定足」等をダッシュボードのログ欄へ流す）。
"""
import sys
import threading
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")   # 絵文字でクラッシュ回避
except Exception:
    pass

_sinks = []          # ダッシュボード等のログ表示先（callable(str)）

# ★永続ファイルログ：pythonw 下では stdout が消え、GUI ログ欄も閉じれば消えるため、
#   稼働ログを必ずファイルに残す（日次ローテーション・data/logs 配下＝ユーザーデータ扱い）。
#   2026-06-23: ローカル版が「黙って記録ゼロ」になった夜、見るべきログが無かった反省で追加。
_LOG_DIR = Path(__file__).resolve().parents[2] / "data" / "logs"   # N225LocalEngine/data/logs
_file_lock = threading.Lock()
_file_logging = True


def set_file_logging(enabled: bool) -> None:
    """ファイルログの ON/OFF（テスト等で抑止したいとき用）。"""
    global _file_logging
    _file_logging = bool(enabled)


def log_file_path() -> Path:
    """当日のログファイルパス（data/logs/localengine_YYYY-MM-DD.log）。"""
    return _LOG_DIR / f"localengine_{datetime.now():%Y-%m-%d}.log"


def _write_file(line: str) -> None:
    if not _file_logging:
        return
    try:
        with _file_lock:
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(log_file_path(), "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass   # ログ書込み失敗で本処理を止めない


def persist(msg) -> None:
    """ファイルにだけ残す（print / sink には流さない）。
    controller 等が on_log 経由で出すメッセージ（start / ポート使用中 / start_error 等）を、
    GUI ログ欄だけでなく必ず永続ファイルにも残すために使う。"""
    _write_file(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")


# ★詳細デバッグログ（2026-06-29）: ろうそく足→戦略判断→シグナル送出→記録 の流れを追うための
#   粒度の細かいログ。settings.json の "debug_log"（既定 True）で ON/OFF（決め打ちしない）。
#   ファイル(data/logs)＋登録シンク(GUIログ欄)の両方へ出す。例外は握りつぶし本処理を止めない。
_debug_enabled = True


def set_debug(enabled: bool) -> None:
    global _debug_enabled
    _debug_enabled = bool(enabled)


def debug_enabled() -> bool:
    return _debug_enabled


def dbg(msg) -> None:
    """詳細デバッグ行。set_debug(False) で抑止。ファイル＋GUIシンクへ（[DBG] 接頭辞）。"""
    if not _debug_enabled:
        return
    try:
        _write_file(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [DBG] {msg}")
    except Exception:
        pass
    for s in list(_sinks):
        try:
            s(f"[DBG] {msg}")
        except Exception:
            pass


def add_sink(fn):
    """ログの転送先を登録（重複登録しない）。fn(msg:str) が呼ばれる。"""
    if callable(fn) and fn not in _sinks:
        _sinks.append(fn)


def remove_sink(fn):
    try:
        _sinks.remove(fn)
    except ValueError:
        pass


def log_message(msg, target="debug"):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"), flush=True)
    _write_file(line)                       # ★永続ファイルへ必ず残す
    # 登録された表示先（ダッシュボード等）へ生メッセージを転送（例外は握りつぶす）
    for s in list(_sinks):
        try:
            s(str(msg))
        except Exception:
            pass
