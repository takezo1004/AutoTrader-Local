# -*- coding: utf-8 -*-
"""ブリッジの webhook passphrase をブリッジ設定から取得する（DPAPI 復号）。

ブリッジ(N225BrokerBridge)は `%LOCALAPPDATA%\\N225BrokerBridge\\appsettings.Local.json` に
`Webhook.Passphrase` を **DPAPI（CurrentUser・エントロピーなし）** で暗号化し `enc:<base64>` 形式で保存する
（`LocalSettingsStore.cs`）。同一 Windows ユーザーなら復号できる。

★方針：passphrase は webhook の両端（送り手＝ローカル版／受け手＝ブリッジ）で一致必須の共有値。
  ローカル版は**起動時にブリッジから取得してメモリ保持**し、**外部ファイルには保存しない**。
  取得できない時（ブリッジ未導入・未設定・別ユーザー）は "" を返す。
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path

_BRIDGE_DIR = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "N225BrokerBridge"
DEFAULT_BRIDGE_SETTINGS = _BRIDGE_DIR / "appsettings.Local.json"
_ENC_PREFIX = "enc:"


class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi_unprotect(blob: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    buf = ctypes.create_string_buffer(blob, len(blob))
    bin_ = _BLOB(len(blob), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    bout = _BLOB()
    if not crypt32.CryptUnprotectData(ctypes.byref(bin_), None, None, None, None, 0, ctypes.byref(bout)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(bout.pbData, bout.cbData)
    finally:
        kernel32.LocalFree(bout.pbData)


def read_bridge_passphrase(path=DEFAULT_BRIDGE_SETTINGS) -> str:
    """ブリッジ設定から webhook passphrase を復号して返す。取得不可なら ""。"""
    p = Path(path)
    if not p.exists():
        return ""
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        stored = (d.get("Webhook") or {}).get("Passphrase")
        if not stored:
            return ""
        if isinstance(stored, str) and stored.startswith(_ENC_PREFIX):
            return _dpapi_unprotect(base64.b64decode(stored[len(_ENC_PREFIX):])).decode("utf-8")
        return str(stored)        # 平文保存（旧/サンプル）の場合はそのまま
    except Exception:
        return ""
