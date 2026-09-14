# -*- coding: utf-8 -*-
"""図（SVG）を PNG に書き出す。

マニュアルの図は SVG を正本にして手で直せるようにしておき（images/src/*.svg）、
表示用の PNG をここで生成する（images/*.png）。
変換にはインストール済みのブラウザ（Chrome / Edge）のヘッドレス機能を使う。

使い方:
    python manual/_tools/render_svg.py            # images/src の全 SVG
    python manual/_tools/render_svg.py system     # 1 枚だけ
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANUAL = HERE.parent
SRC = MANUAL / "images" / "src"
OUT = MANUAL / "images"
SCALE = 1.0

BROWSERS = [
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def browser() -> str | None:
    for b in BROWSERS:
        if Path(b).exists():
            return b
    return None


def size_of(svg: Path) -> tuple[int, int]:
    t = svg.read_text(encoding="utf-8")
    m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', t)
    if m:
        return int(float(m.group(1))), int(float(m.group(2)))
    return 1520, 700


def render(name: str, exe: str) -> None:
    svg = SRC / f"{name}.svg"
    if not svg.exists():
        print(f"  NG  {name}: {svg} がありません")
        return
    w, h = size_of(svg)
    dst = OUT / f"{name}.png"
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [exe, "--headless", "--disable-gpu", "--hide-scrollbars",
               f"--screenshot={dst}", f"--window-size={int(w * SCALE)},{int(h * SCALE)}",
               f"--force-device-scale-factor={SCALE}",
               f"--user-data-dir={tmp}", svg.resolve().as_uri()]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if dst.exists():
        print(f"  OK  {dst.name}（{w}x{h}）")
    else:
        print(f"  NG  {name}: 変換に失敗しました\n{p.stderr[-400:]}")


def main() -> None:
    exe = browser()
    if exe is None:
        print("Chrome / Edge が見つかりません。SVG のまま使ってください。")
        return
    names = sys.argv[1:] or [p.stem for p in sorted(SRC.glob("*.svg"))]
    print(f"SVG → PNG（{Path(exe).name} を使用）")
    for n in names:
        render(n, exe)


if __name__ == "__main__":
    main()
