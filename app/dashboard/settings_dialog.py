# -*- coding: utf-8 -*-
"""設定ダイアログ（グローバル・手動セットアップ一式）。

手動で全て設定できるように、エンジンのグローバル設定を1画面に集約:
  - パスフレーズ（passphrase・全 webhook 共通・ブリッジと一致させる）
  - ブリッジ exe パス（外部ブリッジ起動先・配布時はインストール先）
  - ブリッジ URL（webhook 注文先）
  - 蓄積データ parquet パス（内蔵BT・warmup 用）
  - CSV取込フォルダ（内蔵BT のマージ元）
保存で settings.json に永続化。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .theme import BG, PANEL_BG_HI, FG, FG_DIM, ACCENT, GREEN, brighten, place_near, fit

_FONT_LABELS = {"標準": 1.0, "大きめ": 1.15}      # 特大は廃止（ヘッダーがあふれるため）


def _font_label(scale: float) -> str:
    return "大きめ" if scale >= 1.15 else "標準"


class SettingsDialog(tk.Toplevel):
    def __init__(self, master, controller, on_done=None):
        super().__init__(master)
        self.ctrl = controller
        self.on_done = on_done
        self.configure(bg=BG)
        self.title("設定")
        fit(self, 620, 470); self.resizable(False, False)
        self.transient(master); self.grab_set()
        s = self.ctrl.settings()
        self.v_secret = tk.StringVar(value=s["passphrase"])
        self.v_url = tk.StringVar(value=s["bridge_url"])
        self.v_exe = tk.StringVar(value=s["bridge_exe"])
        self.v_parquet = tk.StringVar(value=s["parquet_path"])
        self.v_csv = tk.StringVar(value=s["csv_dir"])
        self._orig_theme = "light" if s.get("theme") == "light" else "dark"
        self._orig_font = _font_label(float(s.get("font_scale", 1.0)))
        self.v_theme = tk.StringVar(value=("ライト" if self._orig_theme == "light" else "ダーク"))
        self.v_font = tk.StringVar(value=self._orig_font)
        self._build()
        place_near(self, master)

    def _build(self):
        tk.Label(self, text="グローバル設定（ブリッジ・データ・認証）", bg=BG, fg=ACCENT,
                 font=("Segoe UI Semibold", 11)).pack(anchor="w", padx=16, pady=(14, 8))
        g = tk.Frame(self, bg=BG); g.pack(fill="x", padx=16)
        g.columnconfigure(1, weight=1)

        def field(r, label, var, browse=None, secret=False):
            tk.Label(g, text=label, bg=BG, fg=FG, font=("Segoe UI", 9), width=18, anchor="w").grid(row=r, column=0, sticky="w", pady=5)
            # ★伏せ字は呼び出し側が secret=True で指定する（ラベル文字列で判定しない）。
            #   旧実装は label に "シークレット" を含むかで判定しており、2026-08-18 の
            #   「シークレットコード」→「パスフレーズ」改称でマスクが外れ、設定画面に
            #   パスフレーズが平文表示されていた（2026-09-03 マニュアル用の撮影で発覚）。
            show = "•" if secret else None
            e = ttk.Entry(g, textvariable=var, show=show)
            e.grid(row=r, column=1, sticky="we", pady=5)
            if browse:
                tk.Button(g, text="参照", command=browse, bg=PANEL_BG_HI, fg=FG, relief=tk.FLAT,
                          cursor="hand2", bd=0, padx=8).grid(row=r, column=2, padx=(6, 0))
            return e

        # パスフレーズ＋👁表示/非表示トグル
        self.secret_entry = field(0, "パスフレーズ", self.v_secret, secret=True)
        self._secret_shown = False
        self.eye_btn = tk.Button(g, text="👁", command=self._toggle_secret, bg=PANEL_BG_HI, fg=FG,
                                 relief=tk.FLAT, cursor="hand2", bd=0, padx=8,
                                 font=("Segoe UI Emoji", 11))
        self.eye_btn.grid(row=0, column=2, padx=(6, 0))
        self.fetch_btn = tk.Button(g, text="ブリッジから取得", command=self._fetch_secret, bg=PANEL_BG_HI, fg=FG,
                                   relief=tk.FLAT, cursor="hand2", bd=0, padx=8, font=("Segoe UI", 9))
        self.fetch_btn.grid(row=0, column=3, padx=(6, 0))
        self.secret_entry.config(state="readonly")   # ブリッジから取得＝表示専用（手入力しない）
        field(1, "ブリッジ URL", self.v_url)
        field(2, "ブリッジ exe パス", self.v_exe, self._pick_exe)
        field(3, "蓄積データ parquet", self.v_parquet, self._pick_parquet)
        field(4, "CSV取込フォルダ", self.v_csv, self._pick_csv)

        # 市場カレンダー（取引停止日）— 別の小窓で確認/更新（メイン画面は変更しない）
        tk.Label(g, text="市場カレンダー", bg=BG, fg=FG, font=("Segoe UI", 9), width=18, anchor="w").grid(
            row=5, column=0, sticky="w", pady=5)
        self.lbl_cal = tk.Label(g, text="", bg=BG, fg=FG_DIM, font=("Segoe UI", 8), anchor="w")
        self.lbl_cal.grid(row=5, column=1, sticky="we", pady=5)
        tk.Button(g, text="カレンダーを更新", command=self._open_calendar, bg=PANEL_BG_HI, fg=FG,
                  relief=tk.FLAT, cursor="hand2", bd=0, padx=8).grid(row=5, column=2, padx=(6, 0))
        self._refresh_cal_label()

        # 表示（テーマ・文字サイズ）— 再起動で反映。ラジオボタン＝全選択肢が見えて選びやすい。
        disp = tk.Frame(self, bg=BG); disp.pack(fill="x", padx=16, pady=(12, 0))
        tk.Label(disp, text="表示（見やすさ）", bg=BG, fg=ACCENT,
                 font=("Segoe UI Semibold", 10)).pack(anchor="w")
        trow = tk.Frame(disp, bg=BG); trow.pack(fill="x", pady=(4, 0))
        tk.Label(trow, text="テーマ", bg=BG, fg=FG, font=("Segoe UI", 10), width=10, anchor="w").pack(side="left")
        for val in ("ダーク", "ライト"):
            self._radio(trow, val, self.v_theme).pack(side="left", padx=(0, 14))
        frow = tk.Frame(disp, bg=BG); frow.pack(fill="x", pady=(2, 0))
        tk.Label(frow, text="文字サイズ", bg=BG, fg=FG, font=("Segoe UI", 10), width=10, anchor="w").pack(side="left")
        for val in ("標準", "大きめ"):
            self._radio(frow, val, self.v_font).pack(side="left", padx=(0, 14))
        tk.Label(disp, text="※ ライト＝白い背景（年配の方に見やすい）。テーマと文字サイズは両方選べます。変更は再起動で反映。",
                 bg=BG, fg=FG_DIM, font=("Segoe UI", 8)).pack(anchor="w", pady=(4, 0))

        tk.Label(self, text="※ パスフレーズはブリッジから取得（起動時に自動・[ブリッジから取得]で再取得）。外部ファイルには保存しません。",
                 bg=BG, fg=FG_DIM, font=("Segoe UI", 8)).pack(anchor="w", padx=16, pady=(8, 0))

        btns = tk.Frame(self, bg=BG); btns.pack(side="bottom", fill="x", pady=14, padx=16)
        self._cbtn(btns, "  キャンセル", self.destroy, PANEL_BG_HI, FG).pack(side="right")
        self._cbtn(btns, "  保存", self._save, GREEN, "#1a1b26").pack(side="right", padx=6)

    def _cbtn(self, parent, text, cmd, color, fg):
        b = tk.Button(parent, text=text, command=cmd, font=("Segoe UI", 10), bg=color, fg=fg,
                      relief=tk.FLAT, padx=14, pady=7, cursor="hand2", bd=0,
                      activebackground=color, activeforeground=fg)
        b.bind("<Enter>", lambda e, b=b, c=color: b.config(bg=brighten(c, 0.15)))
        b.bind("<Leave>", lambda e, b=b, c=color: b.config(bg=c))
        return b

    def _toggle_secret(self):
        """👁 でパスフレーズの表示/非表示を切り替え。"""
        self._secret_shown = not self._secret_shown
        self.secret_entry.config(show="" if self._secret_shown else "•")
        self.eye_btn.config(text="🙈" if self._secret_shown else "👁")

    def _fetch_secret(self):
        """[ブリッジから取得]：ブリッジの passphrase を取得して表示（メモリ反映・ファイル保存なし）。"""
        v = self.ctrl.refresh_passphrase_from_bridge()
        self.v_secret.set(v)
        if not v:
            messagebox.showwarning(
                "取得できません",
                "ブリッジからパスフレーズを取得できませんでした。\n"
                "ブリッジ側でパスフレーズを設定（保存）してから再取得してください。", parent=self)
            return
        self._secret_shown = True                      # 取得できたら見えるように
        self.secret_entry.config(show="")
        self.eye_btn.config(text="🙈")

    def _radio(self, parent, value, var):
        """全選択肢が見えるラジオボタン（ドロップダウンより年配の方に優しい）。"""
        return tk.Radiobutton(parent, text=value, value=value, variable=var,
                              bg=BG, fg=FG, font=("Segoe UI", 10), selectcolor=PANEL_BG_HI,
                              activebackground=BG, activeforeground=FG, bd=0,
                              highlightthickness=0, cursor="hand2", anchor="w")

    def _refresh_cal_label(self):
        try:
            from app.feed import calendar_fetch as cal
            recs = cal.read_calendar()
            if recs:
                self.lbl_cal.config(text=f"data/market_Calendar.csv（取引停止日 {cal.no_trade_count(recs)} 件）")
            else:
                self.lbl_cal.config(text="未取得（更新してください）")
        except Exception:
            self.lbl_cal.config(text="data/market_Calendar.csv")

    def _open_calendar(self):
        from .calendar_dialog import CalendarDialog
        dlg = CalendarDialog(self, self.ctrl)
        self.wait_window(dlg)          # 閉じたら件数表示を更新
        self._refresh_cal_label()

    def _pick_exe(self):
        p = filedialog.askopenfilename(title="ブリッジ exe", filetypes=[("実行ファイル", "*.exe"), ("すべて", "*.*")])
        if p:
            self.v_exe.set(p)

    def _pick_parquet(self):
        p = filedialog.askopenfilename(title="蓄積 parquet", filetypes=[("parquet", "*.parquet"), ("すべて", "*.*")])
        if p:
            self.v_parquet.set(p)

    def _pick_csv(self):
        p = filedialog.askdirectory(title="CSV取込フォルダ")
        if p:
            self.v_csv.set(p)

    def _save(self):
        try:
            self.ctrl.set_passphrase(self.v_secret.get())
            self.ctrl.set_bridge_url(self.v_url.get().strip())
            self.ctrl.set_bridge_exe(self.v_exe.get().strip() or None)
            self.ctrl.set_data_paths(parquet_path=self.v_parquet.get().strip(),
                                     csv_dir=self.v_csv.get().strip())
            new_theme = "light" if self.v_theme.get() == "ライト" else "dark"
            new_font = self.v_font.get()
            self.ctrl.set_ui_prefs(theme=new_theme, font_scale=_FONT_LABELS.get(new_font, 1.0))
            ui_changed = (new_theme != self._orig_theme) or (new_font != self._orig_font)
            if self.on_done:
                self.on_done()
            self.destroy()
            if ui_changed:
                messagebox.showinfo("再起動で反映",
                                    "テーマ／文字サイズの変更は、ダッシュボードを再起動すると反映されます。",
                                    parent=self.master)
        except Exception as e:
            messagebox.showerror("設定エラー", str(e))
