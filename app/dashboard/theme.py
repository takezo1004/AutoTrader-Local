# -*- coding: utf-8 -*-
"""ダッシュボード テーマ（Tokyo Night）— 配色・ttk ダークスタイル・DataGrid スタイル。

既存 `n225_brokerbridge_dashboard.py` の配色に統一。apply_theme(root) を1回呼べば、
ttk（Treeview/Frame/Label/Button/Entry/Checkbutton/Scrollbar）が全てダークになる。
"""
from __future__ import annotations

import json
from pathlib import Path
from tkinter import ttk

# ─── UI 設定（テーマ・文字サイズ）を起動時に settings.json から読む ───
#   theme: "dark"（既定）/ "light"     font_scale: 1.0(標準)/1.15(大きめ)/1.3(特大)
#   ※変更は再起動で反映（全ウィジェットが起動時にこの定数を取り込むため）。
_STATE = Path(__file__).resolve().parents[1] / "state" / "settings.json"


def _read_ui_prefs():
    try:
        s = json.loads(_STATE.read_text(encoding="utf-8"))
        th = "light" if str(s.get("theme", "dark")).lower() == "light" else "dark"
        fs = min(1.15, max(1.0, float(s.get("font_scale", 1.0))))   # 特大は廃止＝最大1.15(大きめ)
        return th, fs
    except Exception:
        return "dark", 1.0


THEME, FONT_SCALE = _read_ui_prefs()

# ダーク（Tokyo Night）/ ライト（白系・高コントラスト）の2パレット
_DARK = dict(BG="#1a1b26", PANEL_BG="#24283b", PANEL_BG_HI="#2f344d", FG="#c0caf5",
             FG_DIM="#9aa2c4", ACCENT="#7aa2f7", GREEN="#9ece6a", YELLOW="#e0af68",
             RED="#f7768e", PURPLE="#bb9af7", LOG_BG="#16161e", LED_OFF="#3b4261")
_LIGHT = dict(BG="#eef1f7", PANEL_BG="#ffffff", PANEL_BG_HI="#dfe4f0", FG="#1a1b26",
              FG_DIM="#566076", ACCENT="#2f6fed", GREEN="#2e9e4f", YELLOW="#9a7400",
              RED="#d6336c", PURPLE="#7a4fd0", LOG_BG="#ffffff", LED_OFF="#c4c8d4")
_P = _LIGHT if THEME == "light" else _DARK

BG          = _P["BG"]
PANEL_BG    = _P["PANEL_BG"]
PANEL_BG_HI = _P["PANEL_BG_HI"]
FG          = _P["FG"]
FG_DIM      = _P["FG_DIM"]
ACCENT      = _P["ACCENT"]
GREEN       = _P["GREEN"]
YELLOW      = _P["YELLOW"]
RED         = _P["RED"]
PURPLE      = _P["PURPLE"]
LOG_BG      = _P["LOG_BG"]
DARK        = BG                       # 旧称（選択行などの前景に使用・両テーマで成立）

LED_ON  = GREEN
LED_OFF = _P["LED_OFF"]
LED_ERR = RED


def brighten(hex_color: str, ratio: float) -> str:
    """16進色を ratio(0..1) 分明るく（ボタンのホバー演出）。"""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r = min(255, int(r + (255 - r) * ratio))
    g = min(255, int(g + (255 - g) * ratio))
    b = min(255, int(b + (255 - b) * ratio))
    return f"#{r:02x}{g:02x}{b:02x}"


def fit(win, w: int, h: int) -> None:
    """初期サイズは基本サイズ（w×h）。文字を大きくしても無闇に拡大しないが、
    中身が収まらない（保存ボタン等が隠れる）ときだけ、構築後に必要分だけ縦に伸ばす。
    ＝収まるなら固定・収まらない時だけ高さ確保（保存ボタンが必ず見える）。"""
    try:
        win.geometry(f"{w}x{h}")
    except Exception:
        return

    def _autoheight():
        try:
            win.update_idletasks()
            need = win.winfo_reqheight()
            cur = win.winfo_height()
            cap = win.winfo_screenheight() - 70
            if need > cur:                       # 中身があふれる時だけ縦に伸ばす（横は固定）
                win.geometry(f"{w}x{min(need, cap)}")
        except Exception:
            pass

    try:
        win.after(0, _autoheight)                # 中身を組み立てた後に判定
    except Exception:
        pass


def place_near(win, master, dx: int = 54, dy: int = 64) -> None:
    """サブウィンドウを master（ダッシュボード）の左上から少し下にずらして表示する。
    画面左端ではなく、親ウィンドウの近くに出す（全ダイアログ共通）。画面外は補正。"""
    try:
        win.update_idletasks()
        mx, my = master.winfo_rootx(), master.winfo_rooty()
        x, y = mx + dx, my + dy
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        w, h = win.winfo_width(), win.winfo_height()
        x = max(0, min(x, sw - w)); y = max(0, min(y, sh - h))
        win.geometry(f"+{x}+{y}")
    except Exception:
        pass


def apply_theme(root) -> ttk.Style:
    # ★文字サイズ：tk scaling を FONT_SCALE 倍（point 指定フォントが全体拡大される）。
    try:
        base = float(root.tk.call("tk", "scaling"))
        root.tk.call("tk", "scaling", base * FONT_SCALE)
    except Exception:
        pass
    style = ttk.Style(root)
    try:
        style.theme_use("clam")               # bg 指定が効くテーマ
    except Exception:
        pass

    style.configure(".", background=BG, foreground=FG, fieldbackground=PANEL_BG,
                    bordercolor=PANEL_BG_HI, font=("Segoe UI", 9))
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=FG)
    style.configure("TLabelframe", background=BG, foreground=FG, bordercolor=PANEL_BG_HI)
    style.configure("TLabelframe.Label", background=BG, foreground=FG_DIM, font=("Segoe UI Semibold", 9))
    style.configure("TButton", background=PANEL_BG_HI, foreground=FG, borderwidth=0, padding=6)
    style.map("TButton", background=[("active", ACCENT)], foreground=[("active", DARK)])
    style.configure("TEntry", fieldbackground=PANEL_BG_HI, foreground=FG, insertcolor=FG, borderwidth=1)
    style.configure("TCheckbutton", background=BG, foreground=FG)
    style.map("TCheckbutton", background=[("active", BG)], foreground=[("active", FG)])
    style.configure("TMenubutton", background=PANEL_BG_HI, foreground=FG, borderwidth=0)
    # Combobox（プルダウン）— readonly でも値が読めるよう濃い地＋明るい文字に。
    style.configure("TCombobox", fieldbackground=PANEL_BG_HI, background=PANEL_BG_HI,
                    foreground=FG, arrowcolor=FG_DIM, bordercolor=PANEL_BG_HI, padding=4)
    style.map("TCombobox",
              fieldbackground=[("readonly", PANEL_BG_HI), ("disabled", PANEL_BG)],
              foreground=[("readonly", FG), ("disabled", FG_DIM)],
              selectbackground=[("readonly", PANEL_BG_HI), ("focus", PANEL_BG_HI)],
              selectforeground=[("readonly", FG), ("focus", FG)],
              arrowcolor=[("active", FG)])
    # ドロップダウンのリスト部分（内部 Listbox）も配色を合わせる
    root.option_add("*TCombobox*Listbox.background", PANEL_BG)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", DARK)
    style.configure("Vertical.TScrollbar", background=PANEL_BG_HI, troughcolor=BG,
                    borderwidth=0, arrowcolor=FG_DIM)
    style.configure("Horizontal.TScrollbar", background=PANEL_BG_HI, troughcolor=BG,
                    borderwidth=0, arrowcolor=FG_DIM)

    # DataGrid（戦略一覧）
    style.configure("Dark.Treeview", background=PANEL_BG, fieldbackground=PANEL_BG, foreground=FG,
                    rowheight=28, borderwidth=0, font=("Segoe UI", 10))
    style.configure("Dark.Treeview.Heading", background=PANEL_BG_HI, foreground=FG_DIM,
                    font=("Segoe UI Semibold", 9), borderwidth=0, relief="flat", padding=(6, 4))
    style.map("Dark.Treeview", background=[("selected", ACCENT)], foreground=[("selected", DARK)])
    style.map("Dark.Treeview.Heading", background=[("active", PANEL_BG_HI)])

    # Notebook（タブ）— clam 既定は明るい地＋淡色文字で見えない。ダーク配色に上書き。
    #   未選択タブ=パネル地＋淡色文字（視認可）、選択タブ=濃いパネル地＋アクセント文字、ホバー=濃い地＋通常文字。
    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(4, 4, 4, 0))
    style.configure("TNotebook.Tab", background=PANEL_BG, foreground=FG_DIM,
                    padding=(12, 6), borderwidth=0, font=("Segoe UI", 9))
    style.map("TNotebook.Tab",
              background=[("selected", PANEL_BG_HI), ("active", PANEL_BG_HI)],
              foreground=[("selected", ACCENT), ("active", FG)])
    return style
