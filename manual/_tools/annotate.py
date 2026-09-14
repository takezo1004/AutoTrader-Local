# -*- coding: utf-8 -*-
"""画面キャプチャに①②③…の番号を焼き込む。

【なぜ座標を JSON に分けるか】画面を撮り直しても、番号の位置だけ直せば済むようにするため。
  元画像（images/raw/）は変更せず、番号入りを images/ に書き出す。

使い方:
    python manual/_tools/annotate.py            # callouts.json の全画像を処理
    python manual/_tools/annotate.py main       # 1 枚だけ処理
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
MANUAL = HERE.parent
RAW = MANUAL / "images" / "raw"
OUT = MANUAL / "images"
CONF = HERE / "callouts.json"

# 全画面で統一する見た目（執筆規約 §4）
FILL = (217, 48, 37)          # 赤
TEXT = (255, 255, 255)        # 白
RING = (255, 255, 255)        # 白フチ
RADIUS = 15
RING_W = 3
FONT_PATH = r"C:\Windows\Fonts\meiryob.ttc"
FONT_SIZE = 19

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def label_of(spec) -> str:
    """番号（1..20 → ①..⑳）。'7a' のような子番号にも対応。"""
    s = str(spec)
    if s.isdigit():
        return CIRCLED[int(s) - 1]
    head = "".join(c for c in s if c.isdigit())
    tail = "".join(c for c in s if not c.isdigit())
    return CIRCLED[int(head) - 1] + tail


def annotate(name: str, conf: dict) -> None:
    """番号を焼き込む。

    ・"side" 未指定 … 画面の中（空いている場所）に円を置く
    ・"side": "left" / "right" … **余白に円を置き、指した場所まで細い線を引く**
      （文字の上に円が重なって読めなくなるのを避けるため。余白幅は margin で指定）
    """
    # "source" 指定で別の元画像を使える。"crop" 指定でその一部だけを切り出す
    # （手順ごとに必要な場所だけを見せるため。番号の座標は切り出し後の座標で書く）
    src = RAW / f"{conf.get('source', name)}.png"
    if not src.exists():
        print(f"  NG  {name}: 元画像がありません（{src}）")
        return
    base = Image.open(src).convert("RGB")
    if "crop" in conf:
        base = base.crop(tuple(conf["crop"]))
    # ★実口座の金額を隠す（執筆規約 §5）。デモモードでもポジション履歴だけは実データを読むため、
    #   損益・合計などの数字はぼかしてから使う。画面の作りは残るので説明には支障がない。
    for mk in conf.get("masks", []):
        box = (mk["x1"], mk["y1"], mk["x2"], mk["y2"])
        base.paste(base.crop(box).filter(ImageFilter.GaussianBlur(7)), box)
    m = conf.get("margin", {})
    ml, mr = int(m.get("left", 0)), int(m.get("right", 0))
    img = Image.new("RGB", (base.width + ml + mr, base.height), (255, 255, 255))
    img.paste(base, (ml, 0))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    for c in conf["callouts"]:
        ax, ay = c["x"] + ml, c["y"]            # 指し示す点（画面内の座標）
        side = c.get("side")
        if side == "left":
            x, y = ml // 2, ay
            d.line([(x + RADIUS + RING_W, y), (ax, ay)], fill=FILL, width=2)
        elif side == "right":
            x, y = img.width - mr // 2, ay
            d.line([(x - RADIUS - RING_W, y), (ax, ay)], fill=FILL, width=2)
        else:
            x, y = ax, ay
        lab = label_of(c["n"])
        d.ellipse([x - RADIUS - RING_W, y - RADIUS - RING_W,
                   x + RADIUS + RING_W, y + RADIUS + RING_W], fill=RING)
        d.ellipse([x - RADIUS, y - RADIUS, x + RADIUS, y + RADIUS], fill=FILL)
        bbox = d.textbbox((0, 0), lab, font=font)
        d.text((x - (bbox[2] - bbox[0]) / 2 - bbox[0],
                y - (bbox[3] - bbox[1]) / 2 - bbox[1]), lab, font=font, fill=TEXT)
    OUT.mkdir(parents=True, exist_ok=True)
    dst = OUT / f"{name}.png"
    img.save(dst)
    print(f"  OK  {dst.name}（{len(conf['callouts'])} 個・{img.width}x{img.height}）")


def main() -> None:
    conf = json.loads(CONF.read_text(encoding="utf-8"))
    targets = sys.argv[1:] or list(conf.keys())
    print("番号を焼き込みます（元画像は変更しません）")
    for name in targets:
        if name not in conf:
            print(f"  NG  {name}: callouts.json に定義がありません")
            continue
        annotate(name, conf[name])


if __name__ == "__main__":
    main()
