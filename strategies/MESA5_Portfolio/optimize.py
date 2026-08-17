# -*- coding: utf-8 -*-
"""MESA5_Portfolio 同梱 再最適化モジュール（汎用契約形・パッケージ持参品）。

★この戦略パッケージが「自分用の再最適化ロジック」を持ち歩くためのファイル。
  LocalEngine（や Builder）は中身を知らず、下記2関数を呼ぶだけ＝エンジン無改修で動く。

契約（エンジン ↔ パッケージ）:
  propose(ctx) -> proposals
  apply(ctx, proposals) -> None
  ctx = {
    "folder": Path,                 # この戦略の登録フォルダ（_subs/<名>/config.json を読み書き）
    "df": DataFrame,                # 直近の蓄積データ（OHLCV・index=datetime）。窓はこちらで切る
    "run_backtest": callable,       # run_backtest(strategy_instance, df) -> fills（trade_id/pnl_pt/entry_ts）
    "pt_to_jpy": float,             # 1pt の円換算（既定100）
    "window_months": int (任意),    # 再最適化の窓（既定12）
  }
  proposals = {
    "title","window","note",
    "items":[{"group","param","old","new"}...],   # エンジンが old→new 表で表示
    "_payload":{sub_name: new_config_dict, ...},   # エンジンは不透明・apply にそのまま渡す
  }

再最適化ルール（design/reoptimization_rule.md）:
  直近 window_months ヶ月を train(前70%)/val(後30%) に分割。各サブを粗グリッド
  （band_scale×tp1_R×tp2_R）で探索し、★「train 非劣化(≥95%)かつ val 改善」だけ採用＝過適合棄却。
  改善が無ければそのサブは提案なし（現行維持）。
自己完結: サブ戦略は <folder>/_subs/<名>/strategy.py から importlib で読む（跨ぎ import なし）。
"""
from __future__ import annotations

import importlib.util as _ilu
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SUBS = ["MESA_Stochastic", "DT_Stochastic", "TSI_Stochastic", "Momentum_Combo"]
WINDOW_MONTHS_DEFAULT = 12
TRAIN_FRAC = 0.70
G_BAND = [0.9, 1.0, 1.1]
G_TP1 = [0.8, 1.0, 1.2]
G_TP2 = [1.5, 2.0, 2.5]
MIN_PF = 1.3


def _subs_dir(folder: Path) -> Path:
    return Path(folder) / "_subs"


def _sub_class(folder: Path, name: str):
    """<folder>/_subs/<name>/strategy.py の戦略クラス（クラス名＝name）を返す。"""
    p = _subs_dir(folder) / name / "strategy.py"
    key = f"_mp5opt__{name}"
    m = sys.modules.get(key)
    if m is None:
        spec = _ilu.spec_from_file_location(key, str(p))
        m = _ilu.module_from_spec(spec)
        sys.modules[key] = m
        spec.loader.exec_module(m)
    return getattr(m, name)


def _pf(a) -> float:
    a = np.asarray(a, dtype=float)
    pos = a[a > 0].sum()
    neg = -a[a < 0].sum()
    return float(pos / neg) if neg > 0 else 99.0


def _eval(folder, name, cfg, df, cutoff, split_ts, run_backtest, pt):
    """サブを full df で回し、直近窓に絞って train/val の net・PF を返す。"""
    inst = _sub_class(folder, name)(cfg=cfg)
    fills = run_backtest(inst, df)
    if fills is None or len(fills) == 0:
        return None
    tp = fills.groupby("trade_id").agg(pnl=("pnl_pt", "sum"), ts=("entry_ts", "first"))
    ts = pd.to_datetime(tp["ts"])
    tp = tp[ts >= cutoff]
    ts = pd.to_datetime(tp["ts"])
    if len(tp) < 20:
        return None
    tr = tp[ts < split_ts]["pnl"].values
    va = tp[ts >= split_ts]["pnl"].values
    if len(tr) < 5 or len(va) < 5:
        return None
    return dict(tr_net=tr.sum() * pt, tr_pf=_pf(tr), tr_n=len(tr),
               va_net=va.sum() * pt, va_pf=_pf(va), va_n=len(va))


def _scaled(base_cfg, band, tp1, tp2) -> dict:
    c = json.loads(json.dumps(base_cfg))
    if isinstance(c.get("upper_band"), dict):
        c["upper_band"] = {k: round(v * band, 4) for k, v in c["upper_band"].items()}
    if isinstance(c.get("lower_band"), dict):
        c["lower_band"] = {k: round(v * band, 4) for k, v in c["lower_band"].items()}
    c["tp1_R"] = tp1
    c["tp2_R"] = tp2
    return c


def _optimize_sub(folder, name, df, cutoff, split_ts, run_backtest, pt):
    base_cfg = json.loads((_subs_dir(folder) / name / "config.json").read_text(encoding="utf-8"))
    base = _eval(folder, name, base_cfg, df, cutoff, split_ts, run_backtest, pt)
    if base is None:
        return base_cfg, None, None
    best = None
    best_cfg = None
    best_score = None
    for band in G_BAND:
        for tp1 in G_TP1:
            for tp2 in G_TP2:
                if tp2 <= tp1:
                    continue
                cfg = _scaled(base_cfg, band, tp1, tp2)
                r = _eval(folder, name, cfg, df, cutoff, split_ts, run_backtest, pt)
                if r is None:
                    continue
                # ★過適合回避（厳格）：train 非劣化(≥95%)・val 改善・両 PF≥MIN_PF。
                tr_ok = r["tr_net"] >= base["tr_net"] * (0.95 if base["tr_net"] > 0 else 1.0)
                va_ok = r["va_net"] >= base["va_net"]
                if r["tr_pf"] >= MIN_PF and r["va_pf"] >= MIN_PF and tr_ok and va_ok:
                    score = r["tr_net"] + r["va_net"]
                    if best is None or score > best_score:
                        best = dict(r, band=band, tp1=tp1, tp2=tp2)
                        best_cfg = cfg
                        best_score = score
    return base_cfg, best, best_cfg


def _diff_items(group, base_cfg, best):
    """old→new の差分項目（band_scale・tp1_R・tp2_R）。"""
    items = []
    items.append({"group": group, "param": "band_scale", "old": 1.0, "new": best["band"]})
    items.append({"group": group, "param": "tp1_R", "old": base_cfg.get("tp1_R"), "new": best["tp1"]})
    items.append({"group": group, "param": "tp2_R", "old": base_cfg.get("tp2_R"), "new": best["tp2"]})
    return items


def propose(ctx) -> dict:
    """直近 window_months ヶ月で各サブを再最適化し、過適合ガードを通った提案を返す。"""
    folder = Path(ctx["folder"])
    df = ctx["df"]
    run_backtest = ctx["run_backtest"]
    pt = float(ctx.get("pt_to_jpy", 100))
    wm = int(ctx.get("window_months", WINDOW_MONTHS_DEFAULT))

    if df is None or len(df) == 0:
        return {"title": "再最適化", "window": "-", "items": [],
                "note": "データがありません（蓄積 parquet / CSV を用意してください）。", "_payload": {}}
    cutoff = df.index[-1] - pd.DateOffset(months=wm)
    win = df.index[df.index >= cutoff]
    if len(win) < 50:
        return {"title": "再最適化", "window": f"{cutoff.date()}〜{df.index[-1].date()}", "items": [],
                "note": f"窓内のバーが少なすぎます（{len(win)}本）。データを増やしてください。", "_payload": {}}
    split_ts = win[int(len(win) * TRAIN_FRAC)]

    items = []
    payload = {}
    notes = []
    for name in SUBS:
        if not (_subs_dir(folder) / name / "strategy.py").exists():
            continue
        base_cfg, best, best_cfg = _optimize_sub(folder, name, df, cutoff, split_ts, run_backtest, pt)
        if best is None:
            notes.append(f"{name}: 現行維持")
            continue
        items += _diff_items(name, base_cfg, best)
        payload[name] = best_cfg
        notes.append(f"{name}: tp1 {base_cfg.get('tp1_R')}→{best['tp1']} / tp2 {base_cfg.get('tp2_R')}→{best['tp2']}"
                     f" / band×{best['band']}（val {best['va_net']:+,.0f}円）")

    title = "再最適化（直近{}ヶ月・過適合ガード）".format(wm)
    window = f"{cutoff.date()} 〜 {df.index[-1].date()}  train<{split_ts.date()}≤val"
    note = ("提案あり：承認すると _subs の config を更新します。\n" if payload
            else "ロバスト条件を満たす改善はありませんでした（現行維持＝健全）。\n") + "  ".join(notes)
    return {"title": title, "window": window, "items": items, "note": note, "_payload": payload}


def apply(ctx, proposals) -> None:
    """承認された提案を <folder>/_subs/<名>/config.json に書き込む。"""
    folder = Path(ctx["folder"])
    for name, cfg in (proposals.get("_payload") or {}).items():
        p = _subs_dir(folder) / name / "config.json"
        p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
