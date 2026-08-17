# -*- coding: utf-8 -*-
"""汎用 再最適化フック — 戦略パッケージ同梱の optimize.py を呼ぶだけ（戦略固有を持たない）。

★設計意図（重要）: エンジンは「サブ」「tp1R」等の戦略中身を一切知らない。
  戦略パッケージが optimize.py（propose(ctx)/apply(ctx, proposals)）を持参していれば、
  ダッシュボードの[🔄 再最適化]がそれを呼ぶだけ。
  → 新しい合成戦略を作っても、その戦略が自分用 optimize.py を同梱するだけで動く＝
     **エンジン無改修・再配布不要**。

契約（package 側 optimize.py が実装）:
  propose(ctx) -> {"title","window","note","items":[{group,param,old,new}...],"_payload":{...}}
  apply(ctx, proposals) -> None        # 承認後に呼ぶ
ctx は build_ctx() がエンジン資源（蓄積データ・内蔵BT・pt換算）を詰めて渡す。
"""
from __future__ import annotations

import importlib.util as _ilu
import sys
from pathlib import Path

WINDOW_MONTHS = 12          # 再最適化の窓（直近1年）。現市場のレジームに合わせる


def optimizer_path(folder) -> Path:
    return Path(folder) / "optimize.py"


def _load(folder):
    """<folder>/optimize.py を一意キーで import（戦略ごとに独立）。"""
    folder = Path(folder).resolve()
    p = folder / "optimize.py"
    key = f"_reopt.{folder.parent.name}.{folder.name}.optimize"
    mod = sys.modules.get(key)
    if mod is None:
        spec = _ilu.spec_from_file_location(key, str(p))
        mod = _ilu.module_from_spec(spec)
        sys.modules[key] = mod
        spec.loader.exec_module(mod)
    return mod


def has_optimizer(folder) -> bool:
    """この戦略パッケージが再最適化に対応しているか（optimize.py＋propose を持つ）。"""
    if not optimizer_path(folder).exists():
        return False
    try:
        return hasattr(_load(folder), "propose")
    except Exception:
        return False


def build_ctx(controller, folder, window_months: int = WINDOW_MONTHS) -> dict:
    """エンジン資源を ctx に詰める（蓄積データ・内蔵BT・pt換算）。戦略中身は知らない。"""
    from app.backtest import data_provider, run_backtest
    from app.engine import PT_TO_JPY
    # 窓＋warmup 余裕を持って蓄積 parquet から読む（optimizer 側で正確な窓に切る）
    df = data_provider.window(data_provider.load_parquet(controller.parquet_path),
                              months=window_months + 3, warmup_bars=300)
    return {"folder": Path(folder), "df": df, "run_backtest": run_backtest,
            "pt_to_jpy": PT_TO_JPY, "window_months": window_months}


def propose(folder, ctx) -> dict:
    return _load(folder).propose(ctx)


def apply(folder, ctx, proposals) -> None:
    _load(folder).apply(ctx, proposals)
