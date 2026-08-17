# -*- coding: utf-8 -*-
"""市場データ取込 — 蓄積ストア(parquet)へ CSV/xlsx をマージし 6ヶ月ローリングに保つ。

固定された2形式のみ受け付ける（取扱説明書に明記・全ユーザー共通の基準）：
  形式A（CSV）         : kabu Station 等。先頭6列＝日時,O,H,L,C,V。
                         ★タイムスタンプ規約を自動判定（セッションまたぎ＝土曜足の有無）。
                         取引日(settlement)規約なら settlement_to_actual で実時刻化、実時刻ならそのまま。
  形式B（225Labo xlsx）: 225Labo（Gatorobo）の履歴。「15min」シート・列＝日付,時間,O,H,L,C,V。
                         「日付」は取引日(settlement)・「時間」は時計時刻 → settlement_to_actual で実時刻化。
  形式C（TradingView CSV）: TV エクスポート。先頭列 'time'(+09:00 実時刻)＋英語 OHLC。実時刻なので
                         settlement 変換しない（+09:00 は naive JST へ）。TV 保有者向けの自動マージ。
                         .csv は内容で TV/kabu を自動判別（is_tv_csv）。

★内部標準＝実時刻（TradingView 規約）に統一。日本の先物データ提供元（kabu/225Labo/JPX）は
  取引所公式の取引日(settlement)規約で配信するため、取込時に実時刻へ変換するのが恒久運用。
  ユーザーは規約を意識せず DL→取込でよい（自動判定）。

タイムスタンプ変換ロジックは **N225DataPipeline/n225_timestamp.py（正本）** を
**ベンダリング**（コピー同梱・跨ぎ import しない・[[feedback_no_cross_project_imports]]）。
下の settlement_to_actual / previous_business_day / is_business_day は正本と同一実装。
"""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from .data_provider import load_csv, load_parquet, merge, _normalize, _COLS

MONTHS_KEEP = 6          # 蓄積ストアの保持期間（ohlc_storage.MONTHS_KEEP と一致）
LABO_SHEET = "15min"     # 225Labo xlsx の 15分足シート名
CSV_KEEP = 5             # csv_import フォルダに残す CSV 本数（古いものは _archive へ退避）


# ─────────────────────────────────────────────────────────────
# タイムスタンプ変換（load_data_4y.py のベンダリング・取引日→実時刻）
# ─────────────────────────────────────────────────────────────
def is_business_day(d) -> bool:
    """OSE 営業日（月-金、年末年始 12/31〜1/3 除外）。祝日は取引制度上 取引あり。"""
    if d.weekday() >= 5:
        return False
    if (d.month, d.day) in [(12, 31), (1, 1), (1, 2), (1, 3)]:
        return False
    return True


def previous_business_day(d):
    cur = d - timedelta(days=1)
    while not is_business_day(cur):
        cur -= timedelta(days=1)
    return cur


def settlement_to_actual(settlement_date, clock_time) -> datetime:
    """取引日(settlement) + 時計時刻 → 実時刻に変換（3セッション規則）。
      17:00〜23:59 → (取引日の前営業日) + 時刻        （ナイト前半）
      00:00〜06:30 → (取引日の前営業日 + 1暦日) + 時刻 （ナイト後半）
      08:00〜15:59 → 取引日 + 時刻                     （日中）
      その他        → 取引日 + 時刻                     （フォールバック）
    """
    if not hasattr(clock_time, "hour"):
        return settlement_date
    h, m = clock_time.hour, clock_time.minute
    s = getattr(clock_time, "second", 0)
    base = settlement_date if isinstance(settlement_date, datetime) else pd.to_datetime(settlement_date).to_pydatetime()
    base = base.replace(hour=0, minute=0, second=0, microsecond=0)
    if 17 <= h <= 23:
        return previous_business_day(base).replace(hour=h, minute=m, second=s)
    elif h <= 6 or (h == 7 and m == 0):
        return (previous_business_day(base) + timedelta(days=1)).replace(hour=h, minute=m, second=s)
    else:
        return base.replace(hour=h, minute=m, second=s)


# ─────────────────────────────────────────────────────────────
# 取込（2固定形式）
# ─────────────────────────────────────────────────────────────
def is_settlement_indexed(df: pd.DataFrame) -> bool:
    """セッションまたぎで規約判定：土曜の足があれば実時刻(False)、無ければ取引日(True)。

    夜間セッションは金 17:00→土 06:00 まで動く。実時刻なら深夜0:00で日付が翌日に増え
    **土曜(00:00-06:00)の足が出る**。取引日規約は夜間全体を翌営業日(月)に付けるため
    **土曜足が無く・月曜ラベルに00:00-06:00が出る**。→ 土曜足の有無で判定可能。
    既定（週をまたがない極短ファイル等で判別不能）＝取引日とみなす（提供元実績＝settlement・安全側）。
    """
    if df is None or len(df) == 0:
        return False
    idx = pd.to_datetime(pd.Series(df.index))
    if (idx.dt.dayofweek == 5).any():           # 土曜の足あり → 実時刻
        return False
    return True                                  # 土曜足なし → 取引日(settlement)


def settlement_index_to_actual(df: pd.DataFrame) -> pd.DataFrame:
    """取引日ラベル index の df を実時刻 index に変換（settlement_to_actual を全行に適用）。"""
    idx = pd.to_datetime(pd.Series(df.index))
    new = [settlement_to_actual(ts.normalize().to_pydatetime(), ts.time()) for ts in idx]
    out = df.copy()
    out.index = pd.to_datetime(new)
    out.index.name = "datetime"
    return out[~out.index.duplicated(keep="last")].sort_index()


def load_realtime_csv(path) -> pd.DataFrame:
    """形式A：CSV（kabu 等）。先頭6列＝日時,O,H,L,C,V。エンコ自動判定。
    タイムスタンプ規約を自動判定し、取引日規約なら実時刻へ変換して返す。"""
    df = load_csv(path)              # data_provider が datetime index に正規化
    if is_settlement_indexed(df):
        df = settlement_index_to_actual(df)
    return df


def is_tv_csv(path) -> bool:
    """TradingView エクスポート CSV か（先頭列 'time' ＋ 英語 OHLC 列・時刻は実時刻 +09:00）。
    kabu Station CSV（日本語ヘッダ／取引日 settlement 規約）と区別するための判定。
    TV を kabu と誤判定すると settlement 変換が誤適用される（短期ファイルで特に危険）ため明示分岐する。"""
    p = Path(path)
    for enc in ("utf-8-sig", "utf-8", "cp932"):
        try:
            head = pd.read_csv(p, nrows=1, encoding=enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception:
            return False
    else:
        return False
    cols = [str(c).strip().lower() for c in head.columns]
    if not cols or cols[0] != "time":
        return False
    return {"open", "high", "low", "close"}.issubset(set(cols))


def load_tv_csv(path) -> pd.DataFrame:
    """形式C：TradingView CSV（先頭6列＝time,O,H,L,C,Volume・時刻は +09:00 実時刻）。
    TV は最初から実時刻なので **settlement 変換しない**。+09:00 は _normalize が naive JST に落とす。
    （load_csv が先頭6列を取り datetime index に正規化＝余分なインジ列は無視される。）"""
    return load_csv(path)            # 実時刻のまま（取引日変換をかけない）


def load_225labo_xlsx(path, sheet: str = LABO_SHEET) -> pd.DataFrame:
    """形式B：225Labo xlsx の「15min」シートを実時刻化して返す。"""
    df = pd.read_excel(path, sheet_name=sheet, header=0)
    cols = ["date", "time", "open", "high", "low", "close", "volume"]
    df = df.iloc[:, :7]
    df.columns = cols[:df.shape[1]]

    def _conv(row):
        d, t = row["date"], row["time"]
        if pd.isna(d) or pd.isna(t):
            return pd.NaT
        try:
            dd = d if isinstance(d, datetime) else pd.to_datetime(d)
            tt = t if hasattr(t, "hour") else pd.to_datetime(str(t)).time()
            return settlement_to_actual(dd, tt)
        except Exception:
            return pd.NaT

    df["datetime"] = df.apply(_conv, axis=1)
    df = df.dropna(subset=["datetime"])[["datetime", "open", "high", "low", "close", "volume"]]
    return _normalize(df)            # datetime を index 化・OHLCV float・dedup・昇順


# ─────────────────────────────────────────────────────────────
# マージ・トリム・書き出し・状態
# ─────────────────────────────────────────────────────────────
def trim_months(df: pd.DataFrame, months: int = MONTHS_KEEP) -> pd.DataFrame:
    """最終足から遡って months か月分に保つ（日付基準）。"""
    if df is None or len(df) == 0:
        return df
    cutoff = df.index[-1] - pd.DateOffset(months=months)
    return df[df.index >= cutoff]


def merge_into_store(new_df: pd.DataFrame, parquet_path, months: int = MONTHS_KEEP) -> pd.DataFrame:
    """取り込んだ足を蓄積ストアにマージ（新しい方優先・dedup）→6ヶ月トリム→保存。戻り＝保存後の df。"""
    store = load_parquet(parquet_path)
    merged = merge(store, [new_df], prefer="csv")        # 取込分(new)を優先
    merged = trim_months(merged, months)
    out = merged.reset_index()                           # datetime 列 + OHLCV（ohlc_storage と同形式）
    Path(parquet_path).parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(parquet_path, index=False, compression="snappy", engine="pyarrow")
    return merged


def import_file(path, parquet_path, fmt: str, months: int = MONTHS_KEEP) -> dict:
    """ファイルを形式指定で取込→ストアへマージ。fmt='realtime'(A) / 'labo'(B)。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"ファイルが見つかりません: {p}")
    if fmt == "labo":
        new_df = load_225labo_xlsx(p)
    elif fmt == "tv":
        new_df = load_tv_csv(p)                       # TradingView CSV（実時刻・変換なし）
    elif fmt == "realtime":
        new_df = load_realtime_csv(p)
    else:
        raise ValueError(f"未知の形式: {fmt}（'realtime' / 'tv' / 'labo'）")
    added = len(new_df)
    before = len(load_parquet(parquet_path))
    merged = merge_into_store(new_df, parquet_path, months)
    return {"fmt": fmt, "added_rows": added, "before": before, "after": len(merged),
            "first": merged.index[0] if len(merged) else None,
            "last": merged.index[-1] if len(merged) else None}


def import_auto(path, parquet_path, months: int = MONTHS_KEEP) -> dict:
    """拡張子で形式を自動判別して取込。
      .zip → 自動解凍して中の .xlsx/.csv を取込（225Labo は ZIP のままで可）
      .xlsx → 225Labo（取引日→実時刻変換） / .csv → 実時刻（kabu 等）
    """
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".zip":
        import shutil
        import tempfile
        import zipfile
        tmpd = Path(tempfile.mkdtemp(prefix="n225data_"))
        try:
            with zipfile.ZipFile(p) as z:
                names = [n for n in z.namelist() if not n.endswith("/")]
                target = (next((n for n in names if n.lower().endswith(".xlsx")), None)
                          or next((n for n in names if n.lower().endswith(".csv")), None))
                if not target:
                    raise ValueError("ZIP 内に .xlsx / .csv が見つかりません。")
                z.extract(target, tmpd)
                inner = tmpd / target
            ie = inner.suffix.lower()
            if ie in (".xlsx", ".xls"):
                fmt = "labo"
            else:                                    # .csv → TV か kabu かを内容で自動判別
                fmt = "tv" if is_tv_csv(inner) else "realtime"
            return import_file(inner, parquet_path, fmt=fmt, months=months)
        finally:
            shutil.rmtree(tmpd, ignore_errors=True)
    if ext in (".xlsx", ".xls"):
        fmt = "labo"
    elif ext == ".csv":
        fmt = "tv" if is_tv_csv(p) else "realtime"   # ★TradingView CSV を自動判別してマージ
    else:
        raise ValueError("対応ファイルは .zip / .xlsx（225Labo） / .csv（kabu・TradingView）です。")
    return import_file(p, parquet_path, fmt=fmt, months=months)


def trim_store(parquet_path, months: int = MONTHS_KEEP) -> dict:
    """蓄積ストアを 6ヶ月に自動整形（起動時の保守）。変化が無ければ書き込まない。"""
    if not Path(parquet_path).exists():
        return {"before": 0, "after": 0, "changed": False}
    store = load_parquet(parquet_path)                  # _normalize で dedup 済
    before = len(store)
    if before == 0:
        return {"before": 0, "after": 0, "changed": False}
    trimmed = trim_months(store, months)
    if len(trimmed) == before:
        return {"before": before, "after": before, "changed": False}   # 6ヶ月以内＝無変更・書込なし
    out = trimmed.reset_index()
    out.to_parquet(parquet_path, index=False, compression="snappy", engine="pyarrow")
    return {"before": before, "after": len(trimmed), "changed": True}


def archive_old_csvs(csv_dir, keep: int = CSV_KEEP, archive_subdir: str = "_archive") -> dict:
    """csv_import フォルダに最新 keep 本の .csv を残し、それ以前を _archive へ移動（退避）する。

    - 並びは更新時刻（mtime）の新しい順。keep 本を超えた古いものを移動。
    - 削除はしない（移動のみ）。退避先＝csv_dir/archive_subdir。
    - 同名衝突時は末尾に _YYYYMMDD_HHMMSS（必要なら連番）を付与して衝突回避。
    - 対象は .csv のみ（225Labo の .xlsx/.zip は対象外＝別管理）。
    戻り＝{"kept": 残した本数, "moved": [退避したファイル名], "archive_dir": 退避先 or None}。
    """
    d = Path(csv_dir)
    if not d.exists():
        return {"kept": 0, "moved": [], "archive_dir": None}
    csvs = [f for f in d.iterdir() if f.is_file() and f.suffix.lower() == ".csv"]
    csvs.sort(key=lambda f: f.stat().st_mtime, reverse=True)   # 新しい順
    to_move = csvs[keep:]                                       # keep 本を超えた古いもの
    if not to_move:
        return {"kept": len(csvs), "moved": [], "archive_dir": None}
    arc = d / archive_subdir
    arc.mkdir(parents=True, exist_ok=True)
    moved = []
    for f in to_move:
        dest = arc / f.name
        if dest.exists():
            ts = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y%m%d_%H%M%S")
            dest = arc / f"{f.stem}_{ts}{f.suffix}"
            i = 1
            while dest.exists():
                dest = arc / f"{f.stem}_{ts}_{i}{f.suffix}"
                i += 1
        shutil.move(str(f), str(dest))
        moved.append(f.name)
    return {"kept": min(len(csvs), keep), "moved": moved, "archive_dir": str(arc)}


def export_store_csv(parquet_path, out_path) -> int:
    """蓄積ストアを CSV で書き出す（ろうそく足の確認用・utf-8-sig）。戻り＝行数。"""
    df = load_parquet(parquet_path)
    out = df.reset_index()
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    return len(out)


def store_status(parquet_path, warmup_target: int = 500, warmup_min: int = 300,
                 bt_months: int = MONTHS_KEEP) -> dict:
    """蓄積ストアの状態（本数・期間・warmup/BT 充足判定）。"""
    df = load_parquet(parquet_path)
    n = len(df)
    if n == 0:
        return {"n": 0, "first": None, "last": None, "warmup_ok": False,
                "warmup_target": warmup_target, "bt_ok": False, "bt_months": bt_months}
    first, last = df.index[0], df.index[-1]
    span_days = (last - first).days
    # BT 充足判定：6ヶ月(≈180日)に対し約1ヶ月の余裕を許容（年初開始・休場・6ヶ月トリムの端数で
    # ぴったり6ヶ月にはならないため。実質「直近約半年」あれば可）。≈150日以上で OK。
    bt_ok = span_days >= (bt_months * 30 - 30)
    return {"n": n, "first": first, "last": last, "span_days": span_days,
            "warmup_ok": n >= warmup_min, "warmup_target": warmup_target,
            "bt_ok": bt_ok, "bt_months": bt_months}
