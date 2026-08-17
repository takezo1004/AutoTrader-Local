# -*- coding: utf-8 -*-
"""市場カレンダー（祝日取引の実施/非実施）取得 — 自己完結（ベンダリング）。

元: `N225SignalTrader/scripts/fetch_market_calendar.py`。**import せずコピー**し、保存先を
プロジェクト内 `data/market_Calendar.csv`（`_market_hours.MARKET_CALENDAR_PATH` と同一）に変更。
JPX 祝日取引ページから「祝日取引の対象日（国民の祝日＋年末年始休業）」を取得する。
requests / beautifulsoup4 が必要。

★設計（2026-06-27 確定・正本＝design/calendar_lifecycle_design.md）:
  - このCSVが持つのは【JPXが個別に決めた方針】だけ＝祝日ごとの「実施する/実施しない」。
    JPX 固有判断（例: 2026/11/23 勤労感謝の日＝実施しない（注6））は規則から導けないため
    JPX ページが唯一の権威。jpholiday 等での自動導出は採用しない。
  - 構造的な休み（土日・1/1〜1/3・12/31・大納会の夜間なし）は CSV に入れず、_market_hours の
    構造ルールで扱う（毎年不変・JPX 非掲載）。CSV は JPX ページと 1:1 で監査できる状態に保つ。
  - カレンダーは毎年変わるため【複数年を蓄積】する：取得は当年限定にせず、ページ上の全年×
    確定/予定を取り込み、既存CSVへ【日付キーでマージ】する（他年を消さない）。翌年が JPX で
    公開され次第、更新を押せば追加される。

CSV 形式（utf-8-sig・後方互換＝旧 date,name,status も読める）:
  date,name,status,confirmed,source,fetched_at
    date      … YYYY/M/D
    name      … 名称（例: 海の日 / 年末休業日）
    status    … 「実施する」/「実施しない（注n）」（取引停止日＝status に「実施しない」を含む）
    confirmed … 「確定」/「予定」（JPX のページ表記）
    source    … 取得元（jpx / manual）
    fetched_at… 取得日時 ISO8601（★更新日を自動記録）
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from ._market_hours import MARKET_CALENDAR_PATH

# 取得元URL（既定）。★将来 JPX がURL/ページ構造を変えても困らないよう、実運用URLは settings.json に
#   外出しして手動で差し替え可能にする（コード変更不要）。本定数は未設定時のフォールバック既定。
DEFAULT_JPX_URL = "https://www.jpx.co.jp/derivatives/rules/holidaytrading/index.html"
JPX_URL = DEFAULT_JPX_URL                       # 後方互換エイリアス
SAVE_PATH = Path(MARKET_CALENDAR_PATH)


class CalendarFetchError(RuntimeError):
    """取得失敗（ネットワーク/404/ページ構造変更＝URLが変わった可能性）。既存CSVは壊さない。"""

FIELDNAMES = ["date", "name", "status", "confirmed", "source", "fetched_at"]


# ─────────────────────────── 取得（JPX スクレイプ）───────────────────────────

def fetch_calendar(url: str | None = None) -> list[dict]:
    """JPX の祝日取引ページから対象日を取得（list[{date,name,status,confirmed,source}]）。
    ★当年限定にしない：ページ上の全年×確定/予定を取り込む（翌年公開分も拾う）。
    年は行グループ先頭セル（rowspan）に入り、以降の行は省略されるため直前の年を引き継ぐ。
    ★url 未指定なら DEFAULT_JPX_URL。取得失敗（404/通信不可/表が無い＝URL変更の可能性）は
      CalendarFetchError を送出（呼び出し側が「URLを手動設定してください」と案内する）。"""
    import requests
    from bs4 import BeautifulSoup

    target = url or DEFAULT_JPX_URL
    try:
        resp = requests.get(target, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        raise CalendarFetchError(
            f"JPX ページを取得できませんでした（URLが変わった可能性があります）。\n"
            f"取得元URL: {target}\n理由: {e}")

    resp.encoding = resp.apparent_encoding
    soup = BeautifulSoup(resp.text, "html.parser")

    tables = soup.find_all("table", class_="overtable")
    if not tables:
        raise CalendarFetchError(
            f"JPX ページにカレンダー表が見つかりません（URL/ページ構造が変わった可能性があります）。\n"
            f"取得元URL: {target}")

    records: list[dict] = []
    current_year: str | None = None
    for row in tables[0].find_all("tr")[1:]:
        cols = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
        if len(cols) == 6:                       # 年あり行（行グループ先頭）: 年/月日/曜日/名称/実施/確定
            current_year = cols[0].replace("年", "").strip()
            dp = cols[1].replace("月", "/").replace("日", "")
        elif len(cols) == 5:                     # 年なし行: 月日/曜日/名称/実施/確定（年は直前を継承）
            dp = cols[0].replace("月", "/").replace("日", "")
        else:
            continue
        if not (current_year and current_year.isdigit()):
            continue
        date_str = f"{current_year}/{dp}"
        name, status, confirmed = cols[-3], cols[-2], cols[-1]
        # 日付が妥当な行だけ採用（ヘッダ・注記行などを除外）
        try:
            datetime.strptime(date_str, "%Y/%m/%d")
        except ValueError:
            continue
        records.append({"date": date_str, "name": name, "status": status,
                        "confirmed": confirmed, "source": "jpx"})
    return records


# ─────────────────────────── 保存・マージ ───────────────────────────

def _norm_date_key(date_str: str) -> str:
    """マージ用の日付キー（YYYY/M/D を YYYY-MM-DD に正規化）。"""
    try:
        return datetime.strptime(date_str.strip(), "%Y/%m/%d").strftime("%Y-%m-%d")
    except ValueError:
        return date_str.strip()


def save_calendar(records: list[dict], path=SAVE_PATH) -> None:
    """CSV に保存（utf-8-sig・FIELDNAMES）。fetched_at が無い行は現在時刻を補完。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    now_iso = datetime.now().isoformat(timespec="seconds")
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        for r in records:
            w.writerow({
                "date": r.get("date", ""),
                "name": r.get("name", ""),
                "status": r.get("status", ""),
                "confirmed": r.get("confirmed", ""),
                "source": r.get("source", ""),
                "fetched_at": r.get("fetched_at") or now_iso,
            })


def update_calendar(path=SAVE_PATH, url: str | None = None) -> list[dict]:
    """JPX から取得し【既存CSVへ年（日付キー）単位でマージ】して保存（他年を消さない）。
    戻り＝マージ後の全レコード。取得が空なら既存を壊さず例外。url は取得元（settings 由来）。"""
    fetched = fetch_calendar(url)
    if not fetched:
        raise CalendarFetchError("取得したデータが空でした（更新を中止・既存は保持）")

    now_iso = datetime.now().isoformat(timespec="seconds")
    merged: dict[str, dict] = {}
    # 既存を土台に（手動行・他年を保持）
    for r in read_calendar(path):
        merged[_norm_date_key(r["date"])] = r
    # 取得分で上書き（同一日付＝最新の確定/予定・fetched_at を更新）
    for r in fetched:
        r = dict(r)
        r["fetched_at"] = now_iso
        merged[_norm_date_key(r["date"])] = r

    out = sorted(merged.values(), key=lambda r: _norm_date_key(r["date"]))
    save_calendar(out, path)
    return out


# ─────────────────────────── 読み出し・状態 ───────────────────────────

def read_calendar(path=SAVE_PATH) -> list[dict]:
    """保存済 CSV を読み出す（後方互換＝旧 date,name,status のみでも可。欠損列は ''）。"""
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict] = []
    try:
        with open(p, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                out.append({k: row.get(k, "") for k in FIELDNAMES})
    except Exception:
        return []
    return out


def last_updated(path=SAVE_PATH):
    """カレンダーの最終更新時刻（datetime）。CSV の fetched_at 最大値を優先、無ければファイル mtime。
    無ければ None。"""
    recs = read_calendar(path)
    stamps = []
    for r in recs:
        s = (r.get("fetched_at") or "").strip()
        if s:
            try:
                stamps.append(datetime.fromisoformat(s))
            except ValueError:
                pass
    if stamps:
        return max(stamps)
    p = Path(path)
    return datetime.fromtimestamp(p.stat().st_mtime) if p.exists() else None


def no_trade_count(records: list[dict]) -> int:
    """取引停止日（status に「実施しない」）の件数。"""
    return sum(1 for r in records if "実施しない" in r.get("status", ""))


def covered_years(path=SAVE_PATH) -> list[int]:
    """CSV が含む年の昇順リスト（カバレッジ判定用）。"""
    years = set()
    for r in read_calendar(path):
        try:
            years.add(datetime.strptime(r["date"].strip(), "%Y/%m/%d").year)
        except ValueError:
            pass
    return sorted(years)


def ui_status(now: datetime | None = None, path=SAVE_PATH) -> dict:
    """ダッシュボード表示用の鮮度サマリ（★ボタン上の更新メッセージ）。
    返り値 = {severity: 'ok'|'warn'|'error', message: str, need_update: bool,
              last_updated: datetime|None, covered_years: list[int]}。
      - error : カレンダー未取得（ファイル無し/空）。
      - warn  : 当年が未カバー、または 11月以降で翌年が未カバー（年明け前に更新が必要）。
      - ok    : 当年（必要なら翌年）まで取得済み。
    時刻リテラルは持たない（カバレッジは年単位の構造判定）。"""
    now = now or datetime.now()
    years = covered_years(path)
    lu = last_updated(path)
    if not years:
        return {"severity": "error", "need_update": True, "last_updated": lu,
                "covered_years": years,
                "message": "⚠ 市場カレンダー未取得です。[カレンダー] から JPX 取得してください。"}

    cur = now.year
    if cur not in years:
        return {"severity": "warn", "need_update": True, "last_updated": lu,
                "covered_years": years,
                "message": f"⚠ {cur}年のカレンダー未取得です。[カレンダー] から更新してください。"}
    # 年末が近い（11月以降）のに翌年が未カバー → 年明け前に更新を促す
    if now.month >= 11 and (cur + 1) not in years:
        return {"severity": "warn", "need_update": True, "last_updated": lu,
                "covered_years": years,
                "message": f"⚠ {cur + 1}年のカレンダーが未取得です。年明け前に [カレンダー] から更新してください。"}

    span = f"{years[0]}–{years[-1]}年" if len(years) > 1 else f"{years[0]}年"
    lu_s = f"{lu:%Y/%m/%d %H:%M}" if lu else "不明"
    return {"severity": "ok", "need_update": False, "last_updated": lu,
            "covered_years": years,
            "message": f"カレンダー最終更新 {lu_s}（{span} 取得済）"}
