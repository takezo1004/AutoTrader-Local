# -*- coding: utf-8 -*-
"""戦略ローダ — 自己完結フォルダから戦略を読み込む（内部仕様 §4・D9）。

戦略フォルダ（`<戦略名>/`）＝ strategy.py + config.json + _lib部品（指標）。約定エンジンは
ホスト共有なので含まれない（D9）。strategy.py 自身が `_vlib` 一意キーで自分の部品を読むので、
ローダは strategy.py を**戦略フォルダ単位の一意キー**で import するだけでよい（多戦略同梱の衝突回避）。

戻り: LoadedStrategy(name, folder, instance, manifest, config)。
  - instance ＝ strategy.build() の返すインスタンス（reset/on_bar/precompute/step を持つ）。
  - manifest ＝ manifest.json があればそれ、無ければ module.MANIFEST。
  - config   ＝ config.json（GUI 編集対象・パラメータ）。
"""
from __future__ import annotations

import importlib.util as _ilu
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ★共有セッション制御ライブラリをプラットフォーム提供する（戦略の `import session_lib` を解決）。
#   戦略 ZIP には同梱しない（一元管理・跨ぎ無し）。エンジンが top-level 名 'session_lib' に束ねる。
try:
    from ..feed import session_lib as _session_lib
    sys.modules.setdefault("session_lib", _session_lib)
except Exception:
    pass


@dataclass
class LoadedStrategy:
    name: str
    folder: Path
    instance: Any
    manifest: dict
    config: dict
    module: Any


def _import_strategy_module(folder: Path):
    """folder/strategy.py を一意キーで import（__file__ を正しく設定し _vlib を解決可能に）。"""
    folder = Path(folder).resolve()
    sp = folder / "strategy.py"
    if not sp.exists():
        raise FileNotFoundError(f"strategy.py が見つかりません: {sp}")
    key = f"_strat.{folder.parent.name}.{folder.name}.strategy"
    mod = sys.modules.get(key)
    if mod is None:
        spec = _ilu.spec_from_file_location(key, str(sp))
        mod = _ilu.module_from_spec(spec)
        sys.modules[key] = mod
        spec.loader.exec_module(mod)
    return mod


def load_strategy(folder) -> LoadedStrategy:
    """戦略フォルダを読み込んで LoadedStrategy を返す。"""
    folder = Path(folder).resolve()
    mod = _import_strategy_module(folder)

    if not hasattr(mod, "build"):
        raise AttributeError(f"{folder.name}/strategy.py に build() がありません")
    instance = mod.build()

    # manifest: manifest.json 優先、無ければ module.MANIFEST
    mpath = folder / "manifest.json"
    if mpath.exists():
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
    else:
        manifest = dict(getattr(mod, "MANIFEST", {}))
    manifest.setdefault("name", folder.name)

    cpath = folder / "config.json"
    config = json.loads(cpath.read_text(encoding="utf-8")) if cpath.exists() else {}

    return LoadedStrategy(name=manifest.get("name", folder.name), folder=folder,
                          instance=instance, manifest=manifest, config=config, module=mod)


def validate_folder(folder) -> tuple[bool, str]:
    """登録前チェック（外部仕様 F1 の受け入れ条件）。戻り: (ok, 理由)。"""
    folder = Path(folder)
    if not folder.is_dir():
        return False, f"フォルダがありません: {folder}"
    if not (folder / "strategy.py").exists():
        return False, "strategy.py がありません"
    if not (folder / "config.json").exists():
        return False, "config.json がありません"
    return True, "OK"
