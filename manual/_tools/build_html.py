# -*- coding: utf-8 -*-
"""マニュアル全体を 1 枚の HTML にまとめる（レビュー・確認用）。

★N225LocalEngine 用（N225BrokerBridge/manual/_tools/build_html.py から複製・ORDER と表題のみ変更）。

目次から各節へ飛べる形で、全ページを順番に連結する。画像は HTML の中に埋め込むため、
できあがった 1 ファイルだけで持ち運べる（メール添付・別のパソコンでも開ける）。

使い方:
    python manual/_tools/build_html.py          # manual/_preview/manual.html を作る
    python manual/_tools/build_html.py --open   # 作ってからブラウザで開く
"""
from __future__ import annotations

import base64
import re
import sys
import webbrowser
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent
MANUAL = HERE.parent
OUT = MANUAL / "_preview"
DST = OUT / "manual.html"

# 目次の順番（_INDEX.md の並びと合わせる）
ORDER = [
    ("0. はじめに", ["00_intro/01_system.md", "00_intro/02_flow.md", "00_intro/03_install.md"]),
    ("1. 導入と画面", ["01_setup/01_startup.md", "01_setup/02_mainwindow.md",
                       "01_setup/03_settings.md", "01_setup/04_bridge.md",
                       "01_setup/05_check.md"]),
    ("2. 市場データ", ["02_data/01_store.md", "02_data/02_import.md",
                       "02_data/03_sources.md", "02_data/04_candles.md",
                       "02_data/05_calendar.md"]),
    ("3. 戦略", ["03_strategy/01_register.md", "03_strategy/02_edit.md",
                 "03_strategy/03_params.md", "03_strategy/04_backtest.md",
                 "03_strategy/05_reopt.md", "03_strategy/06_remove.md"]),
    ("4. 運用", ["04_run/01_flow.md", "04_run/02_enable.md", "04_run/03_stop.md",
                 "04_run/04_records.md", "04_run/05_archive.md"]),
    ("5. 照会・応用", ["05_reference/01_led.md", "05_reference/02_files.md",
                       "05_reference/03_webhook.md", "05_reference/04_display.md"]),
    ("6. 困ったとき", ["06_trouble/01_startup.md", "06_trouble/02_record_stop.md",
                       "06_trouble/03_no_order.md", "06_trouble/04_feed.md",
                       "06_trouble/05_data.md", "06_trouble/06_calendar.md"]),
    ("付録", ["_GLOSSARY.md"]),
]

CSS = """
:root { --ink:#1a202c; --sub:#4a5568; --line:#e2e8f0; --accent:#2c5282; --bg:#ffffff; }
* { box-sizing:border-box; }
body { margin:0; background:#f7fafc; color:var(--ink);
       font-family:'Yu Gothic UI','Yu Gothic','Meiryo','Hiragino Sans',sans-serif;
       line-height:1.85; font-size:16px; }
.wrap { display:flex; align-items:flex-start; }
nav { position:sticky; top:0; width:300px; height:100vh; overflow:auto; background:#1a202c; color:#e2e8f0;
      padding:24px 20px; flex:0 0 300px; }
nav h1 { font-size:17px; margin:0 0 6px; color:#fff; }
nav .note { font-size:12px; color:#a0aec0; margin-bottom:18px; }
nav .grp { font-size:13px; color:#a0aec0; margin:16px 0 6px; letter-spacing:1px; }
nav a { display:block; color:#e2e8f0; text-decoration:none; font-size:14px; padding:5px 8px; border-radius:6px; }
nav a:hover { background:#2d3748; color:#fff; }
main { flex:1; min-width:0; padding:40px 56px 120px; background:var(--bg); }
section { max-width:1000px; margin:0 auto 72px; }
section + section { border-top:1px solid var(--line); padding-top:56px; }
h1 { font-size:28px; border-bottom:3px solid var(--accent); padding-bottom:10px; margin:0 0 22px; }
h2 { font-size:21px; margin:36px 0 12px; padding-left:12px; border-left:5px solid var(--accent); }
h3 { font-size:18px; margin:26px 0 8px; color:var(--accent); }
p { margin:10px 0; }
table { border-collapse:collapse; margin:16px 0; width:100%; font-size:15px; }
th,td { border:1px solid var(--line); padding:9px 12px; text-align:left; vertical-align:top; }
th { background:#f7fafc; }
img { max-width:100%; border:1px solid var(--line); border-radius:8px; margin:14px 0;
      box-shadow:0 3px 10px rgba(26,32,44,.08); }
blockquote { margin:14px 0; padding:12px 16px; background:#fffaf0; border-left:5px solid #dd6b20;
             color:var(--sub); }
code { background:#edf2f7; padding:2px 6px; border-radius:4px; font-size:14px; }
pre { background:#1a202c; color:#e2e8f0; padding:16px; border-radius:8px; overflow:auto; }
pre code { background:none; color:inherit; }
ul,ol { padding-left:26px; }
hr { border:0; border-top:1px solid var(--line); margin:28px 0; }
.notice { background:#f7fafc; border:1px solid var(--line); border-radius:8px; padding:14px 18px;
          color:var(--sub); font-size:14px; margin-bottom:28px; }
@media print { nav{display:none} main{padding:0} section{page-break-after:always} }
"""

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def embed_images(html: str, base: Path) -> str:
    """<img src="..."> を画像本体ごと埋め込む（1 ファイルで持ち運べるようにする）。"""
    def sub(m: re.Match) -> str:
        src = m.group(1)
        p = (base / src).resolve()
        if not p.exists():
            return m.group(0)
        data = base64.b64encode(p.read_bytes()).decode("ascii")
        ext = p.suffix.lstrip(".").lower()
        mime = "svg+xml" if ext == "svg" else ("jpeg" if ext in ("jpg", "jpeg") else ext)
        return m.group(0).replace(src, f"data:image/{mime};base64,{data}")
    return re.sub(r'<img[^>]+src="([^"]+)"', lambda m: sub(m), html)


def anchor(rel: str) -> str:
    return rel.replace("/", "-").replace(".md", "")


def main() -> None:
    md = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists"])
    nav, body = [], []
    for group, files in ORDER:
        nav.append(f'<div class="grp">{group}</div>')
        for rel in files:
            p = MANUAL / rel
            if not p.exists():
                print(f"  ・未作成: {rel}")
                continue
            text = p.read_text(encoding="utf-8")
            title = text.splitlines()[0].lstrip("# ").strip()
            md.reset()
            html = md.convert(text)
            html = embed_images(html, p.parent)
            # ページ間リンク（../06_trouble/02_connection.md など）を同一 HTML 内の移動に変える。
            # ★同じフォルダ内のリンク（08_notification.md のようにフォルダ名が付かない書き方）は、
            #   そのページのフォルダを補ってからアンカー名にする。補わないと
            #   「#08a_gmail_apppassword」のような存在しないアンカーになりリンクが効かない
            #   （2026-08-30 実測。1-8-a へのリンクが飛ばない不具合の原因）。
            page_dir = str(p.parent.relative_to(MANUAL)).replace("\\", "/")

            def to_anchor(m: re.Match) -> str:
                target = m.group(1)
                # 目次 (_INDEX) はこの HTML では左側のナビが相当するため、先頭へ戻す
                if target == "_INDEX":
                    return 'href="#top"'
                # _GLOSSARY はマニュアル直下にあるのでフォルダを補わない
                if "/" not in target and not target.startswith("_") and page_dir not in (".", ""):
                    target = f"{page_dir}/{target}"
                return f'href="#{anchor(target)}"'

            html = re.sub(r'href="(?:\.\./)?([\w/]+)\.md(#[^"]*)?"', to_anchor, html)
            # ページ内の見出しへのリンク（#記録を消す など）は、節ごとに markdown が
            # 見出し id を振らないため機能しない。リンクを外して文字だけ残す。
            # ★ここで対象にするのは「もともと .md を含まなかった素の #リンク」だけ。
            #   上の変換で作った href="#01_setup-..." まで巻き込むと、ページ間リンクが
            #   全部ただの文字になってしまう（2026-08-30 実測：1-8-a への本文リンクが消えた）。
            html = re.sub(
                r'<a href="#(?!top\b)(?![0-9]{2}[_a-z]*-)([^"]*)">([^<]*)</a>',
                r'「\2」', html)
            nav.append(f'<a href="#{anchor(rel[:-3])}">{title}</a>')
            body.append(f'<section id="{anchor(rel[:-3])}">{html}</section>')

    out = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>N225 ローカル版 操作マニュアル（レビュー版）</title>
<style>{CSS}</style></head>
<body><div class="wrap">
<nav><h1>N225 ローカル版<br>操作マニュアル</h1>
<div class="note">レビュー用（全節を 1 ページに連結）</div>
{''.join(nav)}</nav>
<main>
<div class="notice">これは確認用に全節をつないだものです。実際の配布形態は未定です。
画像はこのファイルに埋め込んであるため、単体で持ち運べます。</div>
{''.join(body)}
</main></div></body></html>"""

    OUT.mkdir(parents=True, exist_ok=True)
    DST.write_text(out, encoding="utf-8")
    mb = DST.stat().st_size / 1024 / 1024
    print(f"作成しました: {DST}（{mb:.1f} MB・{len(body)} 節）")
    if "--open" in sys.argv:
        webbrowser.open(DST.resolve().as_uri())


if __name__ == "__main__":
    main()
