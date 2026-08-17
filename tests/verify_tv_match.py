# -*- coding: utf-8 -*-
"""TV照合テスト — Builder の Python 戦略 vs TradingView（データ差/移植差の切り分け）。

本日の目的（Pine↔Python は既知ロジック差ゼロ・残差がデータ差か移植差かを決着）:
  テストA（戦略の正しさ）: TV の15分足OHLCV を Python 戦略（LocalEngine の run_pine_fast＝TV忠実
    PineBroker・成行=次バー始値）に流し、TV の Strategy Tester トレード一覧と
    **エントリー/決済イベント（時刻・方向）** を照合。一致=Python戦略は正しい／差=データ差。
  テストB（ろうそく足の精度）: TV の OHLCV と エンジン蓄積足（ohlc_live.parquet）を同一期間で
    **バー単位 OHLCV 差分**。エンジンが tick から作った足が TV とどれだけ違うかを定量化。

★ルール順守（[[feedback_no_cross_project_imports]]）:
  - これはテスト（配布物に含まれない）。
  - 外部データは **パスで読むだけ**（N225DataPipeline/csv_input/ の CSV）＝他プロジェクトのコードは import しない。
  - 約定/戦略は **LocalEngine 自身の app.engine** を使う（StrategyBuilder/StrategyAI を import しない）。
  - LocalEngine 内にファイル/フォルダを作らない（tests/ に本1ファイルのみ・出力は標準出力）。

入力（N225DataPipeline/csv_input/）:
  OHLCV    : 'OSE_NK225M1!, 15*.csv'（最新を自動採用・全戦略共通）
  TV取引一覧: '<Pine名>_OSE_NK225M1!_*.csv'（戦略ごと・utf-8-sig・最新）

実行:
  python tests/verify_tv_match.py            # 全戦略 + 足差分
  python tests/verify_tv_match.py --only DT_Stochastic
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]                 # N225LocalEngine
REPO = ROOT.parent                                          # N225TradingSystem
CSV_IN = REPO / "N225DataPipeline" / "csv_input"           # 外部データ（パス読みのみ）
PARQUET = ROOT / "data" / "ohlc_live.parquet"              # エンジン蓄積足
sys.path.insert(0, str(ROOT))

from app.engine import load_strategy, run_pine_fast, summarize  # noqa: E402  ★LocalEngine 自身

# LocalEngine 戦略フォルダ名 → TV Pine 名（トレード一覧ファイルの接頭辞）
STRAT_MAP = {
    "DT_Stochastic":   "DTStoch3",
    "MESA_Stochastic": "MESAstoch78FS3",
    "Momentum_Combo":  "MomCombo2",
    "TSI_Stochastic":  "TSIStoch3",
    "CMF_Stochastic":  "CMFStoch3",
}

BAR = pd.Timedelta(minutes=15)


# ─────────────────────────── データ読み込み ───────────────────────────

def _latest(pattern: str) -> Path | None:
    cands = sorted(CSV_IN.glob(pattern), key=lambda p: p.stat().st_mtime)
    return cands[-1] if cands else None


def load_tv_ohlcv() -> pd.DataFrame:
    """TV の15分足 OHLCV（最新）。time(+09:00) → naive JST、open..close を float、datetime index。"""
    f = _latest("OSE_NK225M1!, 15*.csv")
    if f is None:
        raise FileNotFoundError(f"TV OHLCV が無い: {CSV_IN}/'OSE_NK225M1!, 15*.csv'")
    raw = pd.read_csv(f)
    df = raw.iloc[:, :5].copy()
    df.columns = ["time", "open", "high", "low", "close"]
    ts = pd.to_datetime(df["time"], utc=False)
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_localize(None)                       # +09:00 を外して naive JST に
    df = df.drop(columns=["time"]).astype(float)
    df.index = ts
    vol = raw["Volume"] if "Volume" in raw.columns else (raw["volume"] if "volume" in raw.columns else 0)
    df["volume"] = pd.to_numeric(vol, errors="coerce").fillna(0).values if hasattr(vol, "values") else 0
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df, f.name


def load_tv_trades(pine: str):
    """TV Strategy Tester トレード一覧（最新）→ エントリー/決済イベント集合。
    列は位置で解釈（日本語ヘッダ・utf-8-sig）: 0=番号 1=タイプ 2=日時 3=シグナル 4=価格。
    返り: entries=set[(Timestamp, dir±1)], exits=set[Timestamp], 期間(min,max)。"""
    f = _latest(f"{pine}_OSE_NK225M1!_*.csv")
    if f is None:
        return None
    t = pd.read_csv(f, encoding="utf-8-sig")
    typ = t.iloc[:, 1].astype(str)
    dts = pd.to_datetime(t.iloc[:, 2], errors="coerce")
    entries, exits = set(), set()
    for ty, d in zip(typ, dts):
        if pd.isna(d):
            continue
        d = d.tz_localize(None) if getattr(d, "tz", None) is not None else d
        if "エントリー" in ty:
            entries.add((d, +1 if "ロング" in ty else -1))
        elif "決済" in ty:
            exits.add(d)
    return {"entries": entries, "exits": exits, "min": dts.min(), "max": dts.max(),
            "file": f.name, "n_rows": len(t)}


def _dir_sign(v) -> int:
    if isinstance(v, str):
        return +1 if "long" in v.lower() or "ロング" in v else -1
    try:
        return 1 if float(v) > 0 else -1
    except Exception:
        return 0


def python_events(folder_name: str, df: pd.DataFrame):
    """LocalEngine 戦略を OHLCV で回し、エントリー/決済イベント集合を返す（TV忠実 run_pine_fast）。"""
    loaded = load_strategy(ROOT / "strategies" / folder_name)
    fills = run_pine_fast(loaded.instance, df[["open", "high", "low", "close", "volume"]])
    s = summarize(fills)
    entries, exits = set(), set()
    if len(fills):
        ecol = "entry_ts" if "entry_ts" in fills.columns else None
        xcol = "exit_ts" if "exit_ts" in fills.columns else None
        dcol = "direction" if "direction" in fills.columns else None
        for _, r in fills.iterrows():
            if ecol:
                d = pd.to_datetime(r[ecol])
                entries.add((d, _dir_sign(r[dcol]) if dcol else 0))
            if xcol and pd.notna(r[xcol]):
                exits.add(pd.to_datetime(r[xcol]))
    return entries, exits, s


# ─────────────────────────── 照合 ───────────────────────────

def _cmp(py: set, tv: set, label: str, warmup_end=None):
    matched = py & tv
    py_only = py - tv
    tv_only = tv - py
    rate = (100.0 * len(matched) / len(tv)) if tv else 0.0
    line = (f"    {label:8s}: TV={len(tv):3d}  PY={len(py):3d}  一致={len(matched):3d} ({rate:5.1f}%)"
            f"  PYのみ={len(py_only):3d}  TVのみ={len(tv_only):3d}")
    # warmup 後（公平区間）の取りこぼし
    if warmup_end is not None:
        def _aft(s):
            return {x for x in s if (x[0] if isinstance(x, tuple) else x) >= warmup_end}
        m2, t2, p2 = _aft(matched), _aft(tv), _aft(py)
        r2 = (100.0 * len(m2) / len(t2)) if t2 else 0.0
        line += f"   |warmup後 一致={len(m2)}/{len(t2)} ({r2:4.1f}%) PYのみ={len(_aft(py_only))} TVのみ={len(_aft(tv_only))}"
    print(line)
    return py_only, tv_only


def test_a(only=None):
    df, ohlcv_name = load_tv_ohlcv()
    warmup_end = df.index[min(540, len(df) - 1)]           # WMA540 等が安定するまで（公平区間の起点）
    print(f"\n■ テストA（戦略 vs TV）  OHLCV={ohlcv_name}  {len(df)}本 "
          f"{df.index[0]:%Y-%m-%d %H:%M}..{df.index[-1]:%Y-%m-%d %H:%M}  warmup後起点={warmup_end:%Y-%m-%d}")
    for folder, pine in STRAT_MAP.items():
        if only and folder != only:
            continue
        tv = load_tv_trades(pine)
        if tv is None:
            print(f"  {folder}: TVトレード一覧が見つかりません（{pine}_OSE_NK225M1!_*.csv）"); continue
        try:
            py_e, py_x, s = python_events(folder, df)
        except Exception as e:
            print(f"  {folder}: Python実行エラー: {e}"); continue
        print(f"  {folder}  (Python n={s['n']} PF={s['pf']} 純益={s['pnl']:+,} / TV {tv['n_rows']//2}取引)")
        _cmp(py_e, tv["entries"], "エントリー", warmup_end)
        _cmp(py_x, tv["exits"], "決済", warmup_end)


def test_b():
    df, ohlcv_name = load_tv_ohlcv()
    if not PARQUET.exists():
        print(f"\n■ テストB: エンジン蓄積足が無い: {PARQUET}"); return
    eng = pd.read_parquet(PARQUET)
    ecol = "datetime" if "datetime" in eng.columns else eng.columns[0]
    eng.index = pd.to_datetime(eng[ecol])
    j = df.join(eng[["open", "high", "low", "close"]], how="inner", rsuffix="_eng")
    print(f"\n■ テストB（足の精度: TV vs エンジン蓄積足）  共通バー {len(j)}本  "
          f"{j.index[0]:%Y-%m-%d %H:%M}..{j.index[-1]:%Y-%m-%d %H:%M}")
    if not len(j):
        print("    共通バーなし（期間が重ならない）"); return
    for c in ["open", "high", "low", "close"]:
        d = (j[c] - j[f"{c}_eng"]).abs()
        nz = (d > 1e-9).sum()
        print(f"    {c:5s}: 差≠0 {nz:4d}/{len(j)}本  平均|差|={d.mean():6.2f}  最大|差|={d.max():7.1f}")
    alldiff = (j[["open", "high", "low", "close"]].values
               != j[[f"{c}_eng" for c in ["open", "high", "low", "close"]]].values).any(axis=1)
    print(f"    → OHLCのいずれかが食い違うバー: {int(alldiff.sum())}/{len(j)} 本")


def main():
    args = sys.argv[1:]
    only = args[args.index("--only") + 1] if "--only" in args else None
    print("=" * 78)
    print("TV照合テスト（Python戦略 vs TradingView / ろうそく足精度）")
    test_a(only)
    if not only:
        test_b()
    print("=" * 78)
    print("解釈: エントリー/決済が高一致＝Python戦略は正しい。warmup後も食い違う＝データ差。")
    print("      テストB で TV とエンジン足の OHLC 差が大きいほど、ライブ足生成の精度差が大きい。")


if __name__ == "__main__":
    main()
