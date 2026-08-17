# -*- coding: utf-8 -*-
"""戦略登録ダイアログ（F1②＝ブリッジへ投げる情報）。

配布フォルダ取り込み後（または既存編集時）に、ブリッジ登録仕様に合わせて入力させる:
  - ショートネーム（alert_name）… webhook の戦略名（ブリッジのキー1）
  - インターバル（interval・分）  … 足（ブリッジのキー2）。(alert_name, interval) で一意。
  - 説明（description・任意）
  - 有効（enabled）… 実行可否
  - シークレットコード（passphrase）… ブリッジ全体共通（全 webhook 付与・設定として保存）
新規時は manifest から alert_name/interval を既定にする。
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

from app.engine import load_strategy
from .theme import BG, PANEL_BG, PANEL_BG_HI, FG, FG_DIM, ACCENT, GREEN, brighten, place_near, fit


class RegisterDialog(tk.Toplevel):
    def __init__(self, master, controller, folder=None, edit_name=None, on_done=None):
        super().__init__(master)
        self.ctrl = controller
        self.folder = Path(folder).resolve() if folder else None
        self.edit_name = edit_name
        self.on_done = on_done
        self.configure(bg=BG)
        self.title("戦略登録" if folder else f"登録の編集 — {edit_name}")
        fit(self, 440, 340); self.resizable(False, False)
        self.transient(master); self.grab_set()

        # 既定値
        alert, ivl, desc, enabled = "", 15, "", False
        if edit_name:
            e = self.ctrl.get_entry(edit_name) or {}
            alert, ivl = e.get("alert_name", edit_name), e.get("interval", 15)
            desc, enabled = e.get("description", ""), e.get("enabled", False)
            self._folder_label = e.get("folder", "")
        elif self.folder:
            try:
                mf = load_strategy(self.folder).manifest
                alert, ivl = mf.get("name", self.folder.name), mf.get("interval", 15)
            except Exception:
                alert = self.folder.name
            self._folder_label = str(self.folder)

        self.v_alert = tk.StringVar(value=alert)
        self.v_ivl = tk.StringVar(value=str(ivl))
        self.v_desc = tk.StringVar(value=desc)
        self.v_secret = tk.StringVar(value=self.ctrl.passphrase)
        self.v_enabled = tk.BooleanVar(value=enabled)
        self._build()
        place_near(self, master)

    def _build(self):
        pad = dict(padx=14, pady=4)
        tk.Label(self, text=("① 配布データ: " + Path(self._folder_label).name),
                 bg=BG, fg=FG_DIM, font=("Segoe UI", 9)).pack(anchor="w", padx=14, pady=(12, 2))
        tk.Frame(self, bg=PANEL_BG_HI, height=1).pack(fill="x", padx=14, pady=(2, 8))
        tk.Label(self, text="② ブリッジへ投げる情報", bg=BG, fg=ACCENT,
                 font=("Segoe UI Semibold", 10)).pack(anchor="w", padx=14)

        grid = tk.Frame(self, bg=BG); grid.pack(fill="x", **pad)
        def row(r, label, widget, hint=""):
            tk.Label(grid, text=label, bg=BG, fg=FG, font=("Segoe UI", 9), width=16, anchor="w").grid(row=r, column=0, sticky="w", pady=3)
            widget.grid(row=r, column=1, sticky="we", pady=3)
            if hint:
                tk.Label(grid, text=hint, bg=BG, fg=FG_DIM, font=("Segoe UI", 8)).grid(row=r, column=2, sticky="w", padx=6)
        grid.columnconfigure(1, weight=1)
        row(0, "ショートネーム", ttk.Entry(grid, textvariable=self.v_alert), "ブリッジの戦略名")
        row(1, "インターバル(分)", ttk.Entry(grid, textvariable=self.v_ivl, width=8), "足")
        row(2, "説明", ttk.Entry(grid, textvariable=self.v_desc), "任意")
        row(3, "シークレットコード", ttk.Entry(grid, textvariable=self.v_secret, show="•"), "ブリッジ共通")
        ttk.Checkbutton(grid, text="有効（登録後すぐ実行可否を ON）", variable=self.v_enabled).grid(row=4, column=1, sticky="w", pady=6)

        btns = tk.Frame(self, bg=BG); btns.pack(side="bottom", fill="x", pady=12, padx=14)
        self._cbtn(btns, "  キャンセル", self.destroy, PANEL_BG_HI, FG).pack(side="right")
        self._cbtn(btns, "  保存して登録" if not self.edit_name else "  更新", self._save, GREEN, "#1a1b26").pack(side="right", padx=6)

    def _cbtn(self, parent, text, cmd, color, fg):
        b = tk.Button(parent, text=text, command=cmd, font=("Segoe UI", 10), bg=color, fg=fg,
                      relief=tk.FLAT, padx=12, pady=7, cursor="hand2", bd=0, activebackground=color, activeforeground=fg)
        b.bind("<Enter>", lambda e, b=b, c=color: b.config(bg=brighten(c, 0.15)))
        b.bind("<Leave>", lambda e, b=b, c=color: b.config(bg=c))
        return b

    def _save(self):
        try:
            alert = self.v_alert.get().strip()
            if not alert:
                messagebox.showwarning("入力", "ショートネームは必須です。"); return
            ivl = int(self.v_ivl.get().strip())
            desc, secret, enabled = self.v_desc.get().strip(), self.v_secret.get(), self.v_enabled.get()
            if secret != self.ctrl.passphrase:
                self.ctrl.set_passphrase(secret)               # グローバル共通
            if self.edit_name:
                self.ctrl.update_registration(self.edit_name, alert_name=alert, interval=ivl,
                                              description=desc, enabled=enabled)
            else:
                self.ctrl.register(self.folder, alert_name=alert, interval=ivl,
                                   description=desc, enabled=enabled)
            if self.on_done:
                self.on_done()
            self.destroy()
        except ValueError:
            messagebox.showwarning("入力", "インターバルは整数で入力してください。")
        except Exception as e:
            messagebox.showerror("登録エラー", str(e))
