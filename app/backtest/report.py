# -*- coding: utf-8 -*-
"""内蔵BT 成績レポート（外部仕様 F2・詳細仕様 §8）。

run_pine_fast の fills から、ダッシュボードに出す成績を作る:
  - summary    : PF/勝率/純益/最大DD/平均保有/年別（offline_driver.summarize）
  - monthly    : 月別（取引数・純益pt）
  - equity     : トレード単位の累積損益（損益曲線用）
  - cost       : コスト感度（0/5/10pt・1枚1往復あたり pt をペナルティ）
"""
from __future__ import annotations

import pandas as pd

from app.engine import run_pine_fast, summarize, PT_TO_JPY


def run_backtest(strategy, df: pd.DataFrame) -> pd.DataFrame:
    """戦略を半年窓で回して fills を返す（正本 BT＝run_pine_fast）。"""
    cols = df[["open", "high", "low", "close"]].assign(
        volume=df["volume"] if "volume" in df.columns else 0)
    return run_pine_fast(strategy, cols)


def _trade_pnl(fills: pd.DataFrame) -> pd.DataFrame:
    """トレード単位（trade_id）の損益・決済時刻・枚数。"""
    g = fills.groupby("trade_id")
    out = pd.DataFrame({
        "pnl_pt": g["pnl_pt"].sum(),
        "qty": g["qty"].sum(),
        "exit_ts": g["exit_ts"].last(),
        "entry_ts": g["entry_ts"].first(),
    })
    out["exit_ts"] = pd.to_datetime(out["exit_ts"])
    return out


def monthly(fills: pd.DataFrame) -> list[dict]:
    if fills is None or len(fills) == 0:
        return []
    tp = _trade_pnl(fills)
    tp["ym"] = tp["exit_ts"].dt.strftime("%Y-%m")
    rows = []
    for ym, s in tp.groupby("ym"):
        rows.append({"month": ym, "n": int(len(s)), "pnl_jpy": int(s["pnl_pt"].sum() * PT_TO_JPY)})
    return rows


def equity_curve(fills: pd.DataFrame) -> list[dict]:
    """トレード決済順の累積損益（円）。損益曲線描画用。"""
    if fills is None or len(fills) == 0:
        return []
    tp = _trade_pnl(fills).sort_values("exit_ts")
    cum = (tp["pnl_pt"].cumsum() * PT_TO_JPY).astype(int)
    return [{"ts": str(ts), "equity_jpy": int(v)} for ts, v in zip(tp["exit_ts"], cum)]


def cost_sensitivity(fills: pd.DataFrame, pts=(0, 5, 10)) -> list[dict]:
    """コスト感度: 1枚1往復あたり pt を控除して PF/純益を再計算。"""
    if fills is None or len(fills) == 0:
        return [{"cost_pt": p, "pf": 0.0, "pnl_jpy": 0} for p in pts]
    g = fills.groupby("trade_id")
    base = g["pnl_pt"].sum()
    qty = g["qty"].sum()
    rows = []
    for p in pts:
        tp = base - p * qty                       # 1枚1往復 = p pt のコスト
        wins = tp[tp > 0].sum(); losses = tp[tp <= 0].sum()
        pf = abs(wins / losses) if losses < 0 else float("inf")
        rows.append({"cost_pt": p, "pf": round(float(pf), 2), "pnl_jpy": int(tp.sum() * PT_TO_JPY)})
    return rows


def trades_table(fills: pd.DataFrame) -> list[dict]:
    """取引一覧（TradingView の List of Trades 風）。1 行＝1 決済レグ（3Split は trade ごと最大3行）。
    決済時刻順・累積損益つき。各 fill＝entry/exit の日時・価格・方向・数量・損益・決済理由。"""
    if fills is None or len(fills) == 0:
        return []
    # trade_id ごとの建玉枚数＝その取引の全決済レグの合計（正常は qty_per_entry=3）。
    entry_qty = fills.groupby("trade_id")["qty"].sum().astype(int).to_dict()
    df = fills.sort_values(["exit_ts", "trade_id"])
    rows = []
    cum = 0
    for _, f in df.iterrows():
        pnl_jpy = int(round(float(f["pnl_pt"]) * PT_TO_JPY))
        cum += pnl_jpy
        rows.append({
            "no": int(f["trade_id"]),
            "entry_qty": int(entry_qty.get(int(f["trade_id"]), 0)),
            "dir": str(f["direction"]),
            "entry_ts": str(f["entry_ts"]), "entry_px": float(f["entry_price"]),
            "exit_ts": str(f["exit_ts"]), "exit_px": float(f["exit_price"]),
            "qty": int(f["qty"]),
            "pnl_pt": round(float(f["pnl_pt"]), 1),
            "pnl_jpy": pnl_jpy, "cum_jpy": cum,
            "reason": str(f.get("exit_reason", "")),
        })
    return rows


def performance_summary(fills: pd.DataFrame) -> dict:
    """TradingView の Performance Summary 風の集計を 全体/Long/Short 別に算出（円）。
    純損益・総利益・総損失・プロフィットファクター・期待損益(円/取引)・取引数・手数料。"""
    def stats(sf) -> dict:
        if sf is None or len(sf) == 0:
            return {"n": 0, "net": 0, "gross_profit": 0, "gross_loss": 0, "pf": 0.0, "expectancy": 0}
        tp = sf.groupby("trade_id")["pnl_pt"].sum() * PT_TO_JPY     # トレード単位の円損益
        n = int(len(tp))
        net = int(round(tp.sum()))
        gp = int(round(tp[tp > 0].sum()))
        gl = int(round(tp[tp < 0].sum()))                          # 負値
        pf = round(abs(gp / gl), 3) if gl < 0 else (float("inf") if gp > 0 else 0.0)
        return {"n": n, "net": net, "gross_profit": gp, "gross_loss": gl, "pf": pf,
                "expectancy": int(round(net / n)) if n else 0, "commission": 0}
    if fills is None or len(fills) == 0:
        return {"all": stats(None), "long": stats(None), "short": stats(None)}
    return {"all": stats(fills),
            "long": stats(fills[fills["direction"] == "Long"]),
            "short": stats(fills[fills["direction"] == "Short"])}


def full_report(strategy, df: pd.DataFrame, cost_pts=(0, 5, 10)) -> dict:
    """内蔵BT のフルレポート（ダッシュボードが表示する1枚）。"""
    fills = run_backtest(strategy, df)
    return {
        "bars": int(len(df)),
        "period": [str(df.index[0]), str(df.index[-1])] if len(df) else [None, None],
        "summary": summarize(fills),
        "monthly": monthly(fills),
        "equity": equity_curve(fills),
        "cost": cost_sensitivity(fills, cost_pts),
        "perf": performance_summary(fills),
        "trades": trades_table(fills),
    }
