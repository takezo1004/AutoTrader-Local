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

_LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
_BRIDGE_DIR = _LOCALAPPDATA / "N225BrokerBridge"
DEFAULT_BRIDGE_SETTINGS = _BRIDGE_DIR / "appsettings.Local.json"      # kabu 版の既定（後方互換で残す）
_ENC_PREFIX = "enc:"


def bridge_settings_path() -> Path:
    """製品プロファイル（bridge_product）に従ったブリッジ設定ファイルの場所。
    kabu 版＝%LOCALAPPDATA%/N225BrokerBridge、楽天RSS版＝%LOCALAPPDATA%/N225RssBrokerBridge。"""
    try:
        from .product_profile import load_profile
        product = str(load_profile().get("bridge_product") or "N225BrokerBridge")
    except Exception:
        product = "N225BrokerBridge"
    return _LOCALAPPDATA / product / "appsettings.Local.json"


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


def read_bridge_passphrase(path=None) -> str:
    """ブリッジ設定から webhook passphrase を復号して返す。取得不可なら ""。
    path 省略時は製品プロファイルのブリッジ（kabu 版 / 楽天RSS版）を見る。"""
    p = Path(path) if path else bridge_settings_path()
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
