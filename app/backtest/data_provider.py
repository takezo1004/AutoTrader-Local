# -*- coding: utf-8 -*-
"""内蔵BT データ供給 — ローカル蓄積 parquet ＋ 外部 CSV マージ（詳細仕様 §F・D11）。

- 蓄積 parquet（full-time ストア）を基本に、不足分は外部 CSV をマージ。
- 重複 datetime は **CSV 優先（上書き）が既定**（公式 CSV はクリーンな正本・蓄積は tick 集計近似）。
- BT は半年程度（直近市場で十分）＝ window() で「直近 months か月 ＋ warmup」を切り出す。
- 戻りは datetime 昇順・index=datetime・列 open/high/low/close/volume の DataFrame。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_COLS = ["open", "high", "low", "close", "volume"]


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """datetime を index に・列を OHLCV に正規化（datetime は列でも index でも可）。"""
    df = df.copy()
    if "datetime" in df.columns:
        df = df.set_index("datetime")
    idx = pd.DatetimeIndex(pd.to_datetime(df.index))
    # ★TradingView CSV は時刻が +09:00（tz-aware）。蓄積ストア（naive JST 実時刻）と揃えるため
    #   tz を外して naive JST にする（+09:00 の壁時計＝JST なので値は不変）。kabu は naive のまま。
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    df.index = idx
    df.index.name = "datetime"
    for c in _COLS:
        if c not in df.columns:
            df[c] = 0.0
    df = df[_COLS].astype(float)
    return df[~df.index.duplicated(keep="last")].sort_index()


def load_parquet(path) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return pd.DataFrame(columns=_COLS).rename_axis("datetime")
    return _normalize(pd.read_parquet(p))


def load_csv(path) -> pd.DataFrame:
    """15分足 CSV を読む（kabu=Shift-JIS / TV=UTF-8 を自動吸収・列名は位置で解釈）。"""
    p = Path(path)
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            raw = pd.read_csv(p, encoding=enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    else:
        raise ValueError(f"CSV エンコーディングを判別できません: {p}")
    # 1列目=日時, 2..5=OHLC（kabu/TV とも先頭5列がこの並び）。
    # ★出来高（2026-07-02）：TV エクスポートは「出来高」インジの列がチャート上の指標の後ろに
    #   付くため位置が不定。**列名（Volume/出来高・大小無視）で探し、無ければ従来どおり6列目**。
    #   指標列が挟まった CSV でも指標値を出来高と誤読しない（DataPipeline datastore.load_tv_csv と同方式）。
    out = raw.iloc[:, :5].copy()
    out.columns = ["datetime", "open", "high", "low", "close"][:out.shape[1]]
    vcol = next((c for c in raw.columns
                 if str(c).strip().lower() in ("volume", "vol", "出来高")), None)
    # 6列目フォールバックは「ヘッダが無名（OHLC を名前で判別できない）」場合のみ。
    # 名前付きヘッダ（TV/kabu）で出来高列が見つからない＝出来高インジ未搭載の TV エクスポート等
    # → 6列目は指標値の可能性が高いので誤読せず 0 とする（★出来高インジは載せたままにする運用）。
    _names = {str(c).strip().lower() for c in raw.columns}
    _named_ohlc = ({"open", "high", "low", "close"} <= _names) or ({"始値", "高値", "安値", "終値"} <= _names)
    if vcol is None and not _named_ohlc and raw.shape[1] >= 6:
        vcol = raw.columns[5]                     # 無名ヘッダのみ従来互換＝6列目
    out["volume"] = pd.to_numeric(raw[vcol], errors="coerce").values[:len(out)] \
        if vcol is not None else 0.0
    return _normalize(out)


def merge(parquet_df: pd.DataFrame, csv_dfs, prefer: str = "csv") -> pd.DataFrame:
    """蓄積 ＋ 外部 CSV をマージ。prefer='csv'（既定）＝重複 datetime は CSV 優先。"""
    if isinstance(csv_dfs, pd.DataFrame):
        csv_dfs = [csv_dfs]
    csv_all = pd.concat([c for c in csv_dfs if c is not None and len(c)], axis=0) \
        if csv_dfs else pd.DataFrame(columns=_COLS).rename_axis("datetime")
    # 後勝ち（keep='last'）になるよう、優先する側を後ろに concat する。
    if prefer == "csv":
        merged = pd.concat([parquet_df, csv_all], axis=0)
    else:
        merged = pd.concat([csv_all, parquet_df], axis=0)
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    return merged


def window(df: pd.DataFrame, months: int = 6, warmup_bars: int = 300) -> pd.DataFrame:
    """直近 months か月 ＋ 先頭 warmup_bars 本を切り出す（半年BT用・指標の暖機を含める）。"""
    if df is None or len(df) == 0:
        return df
    last = df.index[-1]
    cutoff = last - pd.DateOffset(months=months)
    start_pos = int(df.index.searchsorted(cutoff))
    start_pos = max(0, start_pos - warmup_bars)
    return df.iloc[start_pos:].copy()


def build(parquet_path=None, csv_paths=None, months: int = 6, warmup_bars: int = 300,
          prefer: str = "csv") -> pd.DataFrame:
    """蓄積＋CSV をマージし半年窓を返す（内蔵BT のワンショット供給）。"""
    pq = load_parquet(parquet_path) if parquet_path else \
        pd.DataFrame(columns=_COLS).rename_axis("datetime")
    csvs = [load_csv(p) for p in (csv_paths or [])]
    merged = merge(pq, csvs, prefer=prefer)
    return window(merged, months=months, warmup_bars=warmup_bars)


# ─────────────────────────────────────────────────────────────
# 欠けの判定（履歴データ管理_設計書 D4・私用と配布版で共用）
# ─────────────────────────────────────────────────────────────
try:                                          # 市場の開いている時刻の正本（時刻を決め打ちしない）
    from app.feed import _market_hours as _mh
except Exception:                             # pragma: no cover
    _mh = None


def bar_interval(df: pd.DataFrame) -> pd.Timedelta | None:
    """足の間隔＝隣り合う足の時間差の最頻値。2 本未満なら None。"""
    if df is None or len(df) < 2:
        return None
    diffs = pd.Series(pd.DatetimeIndex(df.index).sort_values()).diff().dropna()
    diffs = diffs[diffs > pd.Timedelta(0)]
    return diffs.mode().iloc[0] if len(diffs) else None


def find_gaps(df: pd.DataFrame, interval: pd.Timedelta | None = None) -> list[dict]:
    """セッションの中で足が飛んでいる区間を返す。場間・週末・休日の空きは欠けではない。

    隣り合う足の差が間隔より大きいとき、その間にあるべき足の時刻を 1 本ずつ見て、
    市場が開いている時刻（_market_hours.is_open_at）なら「無い足」と数える。
    _market_hours が読めないときは場間を区別できないので、空きをすべて返す（保守側）。
    戻り＝[{"after": 直前にある足, "before": 直後にある足, "from": 最初の無い足, "to": 最後の無い足, "bars": 本数}, …]
    """
    if df is None or len(df) < 2:
        return []
    idx = pd.DatetimeIndex(df.index).sort_values()
    step = interval or bar_interval(df)
    if step is None:
        return []
    out = []
    for prev, nxt in zip(idx[:-1], idx[1:]):
        if nxt - prev <= step:
            continue
        missing = []
        ts = prev + step
        while ts < nxt:
            if _mh is None or _mh.is_open_at(ts.to_pydatetime()):
                missing.append(ts)
            ts += step
        if missing:
            out.append({"after": prev, "before": nxt, "from": missing[0], "to": missing[-1], "bars": len(missing)})
    return out


def format_gaps(gaps: list[dict]) -> list[str]:
    """欠けの一覧を人が読む行にする。"""
    return [f"{g['from']:%Y-%m-%d %H:%M} 〜 {g['to']:%Y-%m-%d %H:%M}（{g['bars']} 本）" for g in gaps]


# ─────────────────────────────────────────────────────────────
# 取込の守り（履歴データ管理_設計書 D5）＝未完成バーを落とす・重なる区間の不一致を仕分ける
# ─────────────────────────────────────────────────────────────
def drop_unfinished(df: pd.DataFrame, interval: pd.Timedelta | None = None, now=None) -> tuple[pd.DataFrame, int]:
    """まだ閉じていない足（いまの足の区切り以降）を落とす。戻り＝(落としたあとの df, 落とした本数)。

    TradingView や kabu の書き出しは形成途中の足もそのまま出すため、そのまま入れると
    最終の足の高値・終値が確定値と食い違う（正本 N225DataPipeline/tools/datastore.py と同じ守り）。
    """
    if df is None or not len(df):
        return df, 0
    step = interval or bar_interval(df) or pd.Timedelta(minutes=15)
    bucket = pd.Timestamp(now or pd.Timestamp.now()).floor(step)
    keep = df.index < bucket
    return df[keep], int((~keep).sum())


def classify_overlap(base: pd.DataFrame, new: pd.DataFrame, interval: pd.Timedelta | None = None) -> dict:
    """重なる区間の四本値の不一致を「既存が古い足」と「原因不明」に仕分ける。

    正本 N225DataPipeline/tools/datastore.py::classify_overlap の実装を写した（跨ぎ import しない）。
    既存に前回の未完成バーが残っていると、取り直したファイルと食い違う。その足には次の 3 つが揃う：
      ① 次の足が new 側にある ② 次の足の始値が new の終値のほうに近い ③ new の出来高が base 以上。
    3 つ揃えば「既存が古い足」、1 つでも欠ければ「原因不明」。配布版の取込は取込分で置き換える（D3）ので、
    この仕分けは止めるためではなく、何が起きたかを利用者に見せるためのもの。
    戻り＝{"stale": DatetimeIndex, "unexplained": DatetimeIndex, "lines": [人が読む行]}
    """
    o = ["open", "high", "low", "close"]
    empty = pd.DatetimeIndex([])
    if base is None or new is None or not len(base) or not len(new):
        return {"stale": empty, "unexplained": empty, "lines": []}
    ov = base.index.intersection(new.index)
    if not len(ov):
        return {"stale": empty, "unexplained": empty, "lines": []}
    step = interval or bar_interval(new) or pd.Timedelta(minutes=15)
    d = base.loc[ov, o].to_numpy() - new.loc[ov, o].to_numpy()
    bad = ov[(abs(d).sum(axis=1) > 1e-6)]
    stale, unexp, lines = [], [], []
    for ts in bad:
        b, n = base.loc[ts], new.loc[ts]
        nxt = ts + step
        has_next = nxt in new.index
        no = float(new.loc[nxt, "open"]) if has_next else float("nan")
        cont = has_next and abs(no - float(n["close"])) < abs(no - float(b["close"]))
        vol_ok = float(n["volume"]) >= float(b["volume"])
        is_stale = bool(cont and vol_ok)
        (stale if is_stale else unexp).append(ts)
        lines.append(f"  {ts}  既存 C={b['close']:.0f} V={b['volume']:.0f}  /  新 C={n['close']:.0f} V={n['volume']:.0f}"
                     f"  → {'既存が古い足' if is_stale else '原因不明'}")
    return {"stale": pd.DatetimeIndex(stale), "unexplained": pd.DatetimeIndex(unexp), "lines": lines}
