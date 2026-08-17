# -*- coding: utf-8 -*-
"""MESA5_Portfolio パラメータ再最適化ツール（AIアシスト・ルール化）。

★定期再最適化ルール（design/reoptimization_rule.md の実装）:
  - 窓＝直近 WINDOW_MONTHS ヶ月（既定12）。現レジーム（高ボラ）に合わせる。
  - train/val 分割（前 TRAIN_FRAC ／後 1-TRAIN_FRAC）。**両方で良い値だけ採用＝過適合を棄却**。
  - 各サブ戦略を粗グリッド（band_scale × tp1_R × tp2_R）で最適化。
  - 提案を report＋proposals.json に出力。`--apply` で同梱 _subs/<名>/config.json に書き込み（承認制）。
  - 適用後にポートフォリオを窓で再BT（old↔new 比較）。
- 確定戦略（標準版）は無傷＝調整は同梱 _subs に対して行う。
- LocalEngine 登録後は、戦略バンドル同梱の本ツールを LocalEngine 上で実行（同じ run_pine_fast・蓄積データ）。

実行: 共有 venv で `python work/optimize.py`（提案のみ）／`python work/optimize.py --apply`（_subs に適用）
"""
from __future__ import annotations

import importlib.util as _ilu
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
STRATS = HERE.parents[1]
ENG = STRATS / "_engine"
SUBS_DIR = HERE / "_subs"
sys.path.insert(0, str(ENG))


def _load(name, path):
    spec = _ilu.spec_from_file_location(name, str(path)); m = _ilu.module_from_spec(spec)
    sys.modules[name] = m; spec.loader.exec_module(m); return m


_eng = _load("_o_engine_bt", ENG / "backtest.py")
run_pine_fast = _eng.run_pine_fast
PT = _eng.PT_TO_JPY
load_4y = _load("_o_engine_data", ENG / "data.py").load_4y
meta_mod = _load("_o_meta_strategy", HERE / "strategy.py")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SUBS = ["MESA_Stochastic", "DT_Stochastic", "TSI_Stochastic", "Momentum_Combo"]
WINDOW_MONTHS = 12
TRAIN_FRAC = 0.70
# 粗グリッド（過適合回避）
G_BAND = [0.9, 1.0, 1.1]          # upper/lower band を一律スケール
G_TP1 = [0.8, 1.0, 1.2]
G_TP2 = [1.5, 2.0, 2.5]
MIN_PF = 1.3                      # train/val 両方でこれ以上（ロバスト条件）


def _sub_class(name):
    p = SUBS_DIR / name / "strategy.py"
    key = f"_o_sub__{name}"
    m = sys.modules.get(key) or _load(key, p)
    return getattr(m, name)


def _eval(name, cfg, df, cutoff, split_ts):
    """sub を full df で回し、直近窓に絞って train/val の net・PF を返す。"""
    inst = _sub_class(name)(cfg=cfg)
    fills = run_pine_fast(inst, df)
    if fills is None or len(fills) == 0:
        return None
    tp = fills.groupby("trade_id").agg(pnl=("pnl_pt", "sum"), ts=("entry_ts", "first"))
    tp = tp[pd.to_datetime(tp["ts"]) >= cutoff]
    if len(tp) < 20:
        return None
    tr = tp[pd.to_datetime(tp["ts"]) < split_ts]["pnl"].values
    va = tp[pd.to_datetime(tp["ts"]) >= split_ts]["pnl"].values

    def pf(a):
        a = np.asarray(a); pos = a[a > 0].sum(); neg = -a[a < 0].sum()
        return pos / neg if neg > 0 else 99.0
    return dict(tr_net=tr.sum() * PT, tr_pf=pf(tr), tr_n=len(tr),
               va_net=va.sum() * PT, va_pf=pf(va), va_n=len(va))


def _scaled(base_cfg, band, tp1, tp2):
    c = json.loads(json.dumps(base_cfg))
    c["upper_band"] = {k: round(v * band, 4) for k, v in c["upper_band"].items()}
    c["lower_band"] = {k: round(v * band, 4) for k, v in c["lower_band"].items()}
    c["tp1_R"] = tp1; c["tp2_R"] = tp2
    return c


def optimize_sub(name, df, cutoff, split_ts):
    base_cfg = json.loads((SUBS_DIR / name / "config.json").read_text(encoding="utf-8"))
    base = _eval(name, base_cfg, df, cutoff, split_ts)
    best = None; best_cfg = base_cfg; best_score = None
    for band in G_BAND:
        for tp1 in G_TP1:
            for tp2 in G_TP2:
                if tp2 <= tp1:
                    continue
                cfg = _scaled(base_cfg, band, tp1, tp2)
                r = _eval(name, cfg, df, cutoff, split_ts)
                if r is None:
                    continue
                # ★過適合回避（厳格）：train を劣化させず（≥95%）・val を改善・両 PF≥MIN_PF。
                tr_ok = r["tr_net"] >= base["tr_net"] * (0.95 if base["tr_net"] > 0 else 1.0)
                va_ok = r["va_net"] >= base["va_net"]
                if r["tr_pf"] >= MIN_PF and r["va_pf"] >= MIN_PF and tr_ok and va_ok:
                    score = r["tr_net"] + r["va_net"]          # 両期間の合計で頑健に選ぶ
                    if best is None or score > best_score:
                        best = (r, dict(band=band, tp1=tp1, tp2=tp2)); best_cfg = cfg; best_score = score
    return base, best, best_cfg


def main():
    apply = "--apply" in sys.argv
    df = load_4y(ohlcv_only=True)
    cutoff = df.index[-1] - pd.DateOffset(months=WINDOW_MONTHS)
    win = df.index[df.index >= cutoff]
    split_ts = win[int(len(win) * TRAIN_FRAC)]
    print(f"=== 再最適化（直近{WINDOW_MONTHS}ヶ月）窓={cutoff.date()}〜{df.index[-1].date()}"
          f"  train<{split_ts.date()}≤val ===\n")

    proposals = {}
    for name in SUBS:
        base, best, best_cfg = optimize_sub(name, df, cutoff, split_ts)
        if base is None:
            print(f"[{name}] データ不足"); continue
        print(f"[{name}]")
        print(f"  現行: train net={base['tr_net']:+,.0f}円/PF{base['tr_pf']:.2f}(n{base['tr_n']})"
              f"  val net={base['va_net']:+,.0f}円/PF{base['va_pf']:.2f}(n{base['va_n']})")
        if best is None:
            print("  → 提案なし（ロバスト条件を満たす改善なし＝現行維持）")
            proposals[name] = None
            continue
        r, p = best
        print(f"  提案: band×{p['band']} tp1={p['tp1']} tp2={p['tp2']}")
        print(f"        train net={r['tr_net']:+,.0f}円/PF{r['tr_pf']:.2f}"
              f"  val net={r['va_net']:+,.0f}円/PF{r['va_pf']:.2f}  ← val改善={r['va_net']-base['va_net']:+,.0f}円")
        proposals[name] = {"params": p, "config": best_cfg, "val_gain": r["va_net"] - base["va_net"]}
        if apply:
            (SUBS_DIR / name / "config.json").write_text(json.dumps(best_cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    (HERE / "out_proposals.json").mkdir(exist_ok=True) if False else None
    (HERE / "reopt_proposals.json").write_text(
        json.dumps({k: (v and {"params": v["params"], "val_gain": v["val_gain"]}) for k, v in proposals.items()},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n提案を reopt_proposals.json に保存。{'★ _subs に適用しました（--apply）' if apply else '（--apply で適用）'}")

    if apply:
        print("\n=== ポートフォリオ 再BT（直近窓・提案適用後）===")
        meta = meta_mod.MESA5_Portfolio()
        fills = run_pine_fast(meta, df)
        tp = fills.groupby("trade_id").agg(pnl=("pnl_pt", "sum"), ts=("entry_ts", "first"))
        tp = tp[pd.to_datetime(tp["ts"]) >= cutoff]
        a = tp["pnl"].values

        def pf(x):
            x = np.asarray(x); return x[x > 0].sum() / max(1e-9, -x[x < 0].sum())
        cum = np.cumsum(a); dd = (cum - np.maximum.accumulate(cum)).min() * PT
        print(f"  直近{WINDOW_MONTHS}ヶ月: 取引={len(a)} PF={pf(a):.2f} 純益={a.sum()*PT:+,.0f}円 最大DD={dd:+,.0f}円")


if __name__ == "__main__":
    main()
