# -*- coding: utf-8 -*-
"""開発キットで作成した AutoTrader Bridge を起動する。

ローカルエンジンは発注をブリッジへ Webhook で依頼するので、ダッシュボードを起動したら
ブリッジも動いている必要がある。ここはその起動だけを行う（発注のロジックは持たない）。

**ブリッジの置き場所は決め打ちしない。** 実体は開発キットが作り、既定の導入先は
``C:\\Program Files\\AutoTrader\\Bridge\\AutoTraderBridge.exe``（キットのユーザーマニュアル）。
ただし導入先はキットが ``%LOCALAPPDATA%\\AutoTraderBridge\\install.json`` の ``bridgeExe`` に
書くので、まずそれを読み、読めないときだけ既定の導入先を使う。
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

# キットが導入時に書く記録（正本）。ここに実際の導入先が入る。
INSTALL_JSON = Path(os.environ.get("LOCALAPPDATA", "")) / "AutoTraderBridge" / "install.json"

# install.json が読めないときだけ使う既定の導入先（キットのユーザーマニュアルの既定値）。
DEFAULT_BRIDGE_EXE = Path(r"C:\Program Files\AutoTrader\Bridge\AutoTraderBridge.exe")

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def resolve_bridge_exe() -> Path | None:
    """ブリッジの実行ファイルを返す。見つからなければ None。"""
    try:
        with open(INSTALL_JSON, encoding="utf-8-sig") as f:
            path = json.load(f).get("bridgeExe")
        if path:
            exe = Path(path)
            if exe.exists():
                return exe
    except Exception:
        pass
    return DEFAULT_BRIDGE_EXE if DEFAULT_BRIDGE_EXE.exists() else None


def is_bridge_running(exe_name: str) -> bool:
    """同じ名前のプロセスが既に動いているか（二重起動の防止）。"""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {exe_name}", "/NH"],
            capture_output=True, text=True, timeout=10,
            creationflags=_NO_WINDOW,
        ).stdout
    except Exception:
        return False
    return exe_name.lower() in (out or "").lower()


def ensure_bridge_running() -> tuple[bool, str]:
    """ブリッジが動いていなければ起動する。

    戻り値＝(動いているか, 画面やログに出す 1 行)。
    **ここで例外を外に出さない**（ブリッジが無くてもダッシュボードは開けるようにする）。
    """
    exe = resolve_bridge_exe()
    if exe is None:
        return False, (
            "AutoTrader Bridge が見つかりません。開発キットでブリッジを作成・インストールしてください"
            f"（探した場所: {INSTALL_JSON} の bridgeExe ／ {DEFAULT_BRIDGE_EXE}）"
        )
    if is_bridge_running(exe.name):
        return True, f"AutoTrader Bridge は既に動いています: {exe}"
    try:
        subprocess.Popen([str(exe)], cwd=str(exe.parent), creationflags=_NO_WINDOW)
    except Exception as e:
        return False, f"AutoTrader Bridge を起動できません: {exe} ({e})"
    return True, f"AutoTrader Bridge を起動しました: {exe}"
