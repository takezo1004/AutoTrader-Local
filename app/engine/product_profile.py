# -*- coding: utf-8 -*-
"""製品プロファイル＝配布物ごとの既定値（証券会社・ブリッジの場所・LED の判定）。

kabu 版（製品3）と楽天RSS版（製品5）は同じエンジンのコードを同梱し、違いは
`engine/product_profile.json`（配布の sync が生成）だけにする＝コードを分岐させない・決め打ちしない。
ファイルが無ければ kabu 版の既定。ユーザー設定（app/state/settings.json の bridge_exe 等）が上書きできる。

キー:
  product_title      ダッシュボードのタイトル
  broker_name        "kabu" / "rakuten"
  broker_label       LED の短い表示（例 "カブ" / "楽天"）
  broker_tool_name   案内文で使う道具の名前（例 "カブステーション" / "マーケットスピード II"）
  bridge_product     ブリッジの AppData フォルダー名（passphrase の取得元）
  bridge_exe_default ブリッジ exe の既定パス（None なら開発ビルドの位置）
  broker_health      {"mode": "http", "url": ...} または {"mode": "process", "process": "MarketSpeed2.exe"}
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

_ENGINE_DIR = Path(__file__).resolve().parents[2]      # …/engine（配布）または …/N225LocalEngine（開発）
PROFILE_PATH = _ENGINE_DIR / "product_profile.json"

DEFAULT_PROFILE: dict = {
    "product_title": "AutoTrader Local",
    "broker_name": "kabu",
    "broker_label": "カブ",
    "broker_tool_name": "カブステーション",
    "bridge_product": "N225BrokerBridge",
    "bridge_exe_default": None,
    "broker_health": {"mode": "http", "url": "http://localhost:18080/kabusapi/"},
}

_cache: dict | None = None


def load_profile(path: Path | str | None = None, use_cache: bool = True) -> dict:
    """プロファイルを返す（既定 + ファイルの上書き）。壊れていても既定で動く。"""
    global _cache
    if use_cache and _cache is not None and path is None:
        return _cache
    prof = copy.deepcopy(DEFAULT_PROFILE)
    p = Path(path) if path else PROFILE_PATH
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                for k, v in data.items():
                    if k == "broker_health" and isinstance(v, dict):
                        prof["broker_health"] = {**prof["broker_health"], **v}
                    elif v is not None:
                        prof[k] = v
    except Exception:
        pass
    if path is None:
        _cache = prof
    return prof
