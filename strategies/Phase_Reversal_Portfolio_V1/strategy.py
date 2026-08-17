# -*- coding: utf-8 -*-
"""Phase_Reversal_Portfolio — Phase_Reversal シリーズ3本を「枠1つ」で束ねる合成戦略。

【確定 V1（2026-08-14）】優先順＝S→D→M（全6通りを実測して決定・下の確定値）。
  4年 n=1,178  PF1.94  +21,182,187円  DD 含み損込み−710,464／決済ベース−693,464
  −10万46件  −20万2件  最悪−222,000  年別 +137万/+370万/+487万/+1124万（全年プラス）
  2本組（S＋D）比 +1,165,018。照合＝../work/pkg_verify.py

【何をするか】（設計の正本＝../design/spec.md）
  Stochastic V4 ／ DoubleDT V4 ／ Momentum V1 の3本は、基軸オシレーターだけが違う同じ骨格。
  **枚数を増やさずに** 3本のサインを1つの枠（証拠金1本分）で拾う。

  - 入口＝3本のサインの和集合。フラットのときだけ、優先順の先頭の発火を採用
  - ★優先順（config "priority"）は決め打ちしない＝**全6通りを測って最善を選ぶ**（ユーザー指示
    2026-08-14）。順序が効くのは複数サブが同じ足で発火したときの取り合い
  - 保有中は新規を見送る。建玉は**採用したサブが最後まで**（そのサブの3分割の出口で）管理する
  - 建玉の状態は採用中のサブにだけ渡し、他の2本には「フラット」を渡す（指標だけ更新される）
  - ★セッション制御は**サブ側のゲートに任せる**（先例と違う点・2026-08-14 実測で確定）。
    サブの step は「決定 → ゲート → 確認待ちロジック」の順で、**確認待ちの武装判定が
    ゲート後の注文を読む**＝ゲートは内部状態と絡んでいて外から肩代わりできない。
    サブ側を無効化して合成後に1回かける方式（先例）だと、締切窓のバーで武装状態がずれて
    サブ単独と1件食い違う（段階0の照合で検出・n が3本とも+1）。
    ポートフォリオ側では**二重にかけない**（サブが自分の注文を自分の建玉でゲート済み）。

【サブ戦略の置き場所】サブは凍結（1文字も変えない・spec §0-1）。
  開発（work/）＝`strategies/<戦略名>/<戦略名>_<版>/` の最新版を読む（版名フォルダ）。
  配布（確定フォルダ）＝`_subs/<戦略名>/` に同梱したものを読む（自己完結）。

★約定モデル＝TV（Pine）完全忠実。約定は共有 `_engine` の PineBroker。戦略は注文を返すだけ。
★器の出どころ＝Swing_Ride_Portfolio V1（確定・TV突合合格）。ロジックは同一で、
  サブ名・戦略名だけ差し替えた。
"""
from __future__ import annotations

import importlib.util as _ilu
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:                                  # 共有セッションライブラリ（プラットフォーム提供・ZIP非同梱）
    import session_lib
except Exception:                     # pragma: no cover
    session_lib = None

_HERE = Path(__file__).resolve().parent
# ★warmup 700＝サブの板厚バッファ・動的順位500本を live 予熱で満たすため（3本とも warmup 700）。
MANIFEST = {"name": "Phase_Reversal_Portfolio", "interval": 15, "warmup_bars": 700,
            "version": 1, "label": "V1"}


def _load_config() -> dict:
    with open(_HERE / "config.json", encoding="utf-8") as f:
        return json.load(f)


def _sub_path(name: str) -> Path:
    """サブ戦略 strategy.py の場所。確定フォルダ同梱(_subs/<名>) があればそれ、無ければ版名フォルダの最新。"""
    bundled = _HERE / "_subs" / name / "strategy.py"
    if bundled.exists():
        return bundled
    strats = _HERE.parents[1]                                  # work -> Phase_Reversal_Portfolio -> strategies
    cands = [p for p in (strats / name).glob(f"{name}_*") if (p / "strategy.py").is_file()]
    if cands:
        newest = max(cands, key=lambda p: [int(x) for x in re.findall(r"\d+", p.name[len(name):])] or [0])
        return newest / "strategy.py"
    raise FileNotFoundError(f"サブ戦略が見つからない: {name}")


def _load_sub(name: str):
    p = _sub_path(name)
    key = f"_prp_sub__{name}"
    mod = sys.modules.get(key)
    if mod is None:
        spec = _ilu.spec_from_file_location(key, str(p))
        mod = _ilu.module_from_spec(spec)
        sys.modules[key] = mod
        spec.loader.exec_module(mod)
    st = mod.build()
    # ★サブは確定パッケージの config で動かす（凍結・spec §0-1）
    cfg_p = p.parent / "config.json"
    if cfg_p.exists():
        with open(cfg_p, encoding="utf-8") as f:
            st.cfg.update(json.load(f))
        if hasattr(st, "refresh_entries"):
            st.refresh_entries()
        if hasattr(st, "refresh_exits"):
            st.refresh_exits()
    return st


class Phase_Reversal_Portfolio:
    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or _load_config()
        self.priority = list(self.cfg.get("priority", [
            "Phase_Reversal_Stochastic", "Phase_Reversal_DoubleDT", "Phase_Reversal_Momentum"]))
        self.interval = MANIFEST["interval"]
        self.qty_per_entry = int(self.cfg.get("qty_per_entry", 3))
        self.session_enabled = bool(self.cfg.get("session_enabled", True))
        self.subs = {name: _load_sub(name) for name in self.priority}
        # ★サブ側の session gate は**生かす**（無効化しない）。理由は冒頭コメント＝
        #   サブの確認待ちロジックがゲート後の注文を読むため、外から肩代わりすると状態がずれる。
        self._A = {}
        self._ts = None
        self.reset()

    # ---- 状態 ----
    def reset(self) -> None:
        for s in self.subs.values():
            s.reset()
        self.active = None
        self.position_size = 0
        self.position_avg_price = 0.0
        self.entry_bar = -1
        self.bars_since_entry = -1

    # ---- 指標（サブごとに1回だけ）----
    def precompute(self, df: pd.DataFrame) -> dict:
        self._ts = pd.DatetimeIndex(df.index)
        for name, s in self.subs.items():
            s._bt_ts = self._ts
            self._A[name] = s.precompute(df)
        return {"n": len(df)}

    # ---- 1バーの決定 ----
    def step(self, A, i) -> list[dict]:
        pos = int(self.position_size)
        out = {}
        for name in self.priority:
            s = self.subs[name]
            if pos != 0 and name == self.active:              # 建玉は採用した戦略にだけ見せる
                s.position_size = self.position_size
                s.position_avg_price = self.position_avg_price
                s.entry_bar = self.entry_bar
                s.bars_since_entry = self.bars_since_entry
            else:
                s.position_size = 0
                s.position_avg_price = 0.0
                s.entry_bar = -1
                s.bars_since_entry = -1
            out[name] = s.step(self._A[name], i) or []
        if pos == 0:
            self.active = None
            for name in self.priority:                        # 同じ足の取り合い＝優先順の先頭
                if any(o.get("t") == "entry" for o in out[name]):
                    self.active = name
                    break
        if self.active is None:
            return []
        return list(out[self.active])         # ★サブ側でゲート済み＝ここでは二重にかけない

    # ---- live: 確定足ごと（step と同順＝建玉は採用中のサブにだけ見せる）----
    #   サブの on_bar は各自のバッファ（出来高込み）で再計算する。
    #   セッション制御は step と同じくサブ側のゲートに任せる（二重がけしない）。
    def on_bar(self, bar) -> list[dict]:
        pos = int(self.position_size)
        out = {}
        for name in self.priority:
            s = self.subs[name]
            if pos != 0 and name == self.active:              # 建玉は採用した戦略にだけ見せる
                s.position_size = self.position_size
                s.position_avg_price = self.position_avg_price
                s.entry_bar = self.entry_bar
                s.bars_since_entry = self.bars_since_entry
            else:
                s.position_size = 0
                s.position_avg_price = 0.0
                s.entry_bar = -1
                s.bars_since_entry = -1
            out[name] = s.on_bar(bar) or []
        if pos == 0:
            self.active = None
            for name in self.priority:                        # 同じ足の取り合い＝優先順の先頭
                if any(o.get("t") == "entry" for o in out[name]):
                    self.active = name
                    break
        if self.active is None:
            return []
        return list(out[self.active])         # ★サブ側でゲート済み＝ここでは二重にかけない

    # ---- どの戦略が建てたか（記録・表示用）----
    def active_name(self) -> str:
        return self.active or ""


def build(cfg: dict | None = None) -> Phase_Reversal_Portfolio:
    return Phase_Reversal_Portfolio(cfg)
