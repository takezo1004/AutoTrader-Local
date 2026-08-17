# -*- coding: utf-8 -*-
"""再最適化ダイアログ（汎用・old→new 差分を表示して承認制で適用）。

戦略パッケージ同梱 optimize.py の propose(ctx) を呼んで提案を取得 → old→new 表で表示 →
[承認して適用]で apply(ctx, proposals) を呼ぶ。エンジンは戦略中身を知らない（汎用）。
propose は重い（グリッド探索）ためスレッドで実行し、UI はブロックしない。
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox

from .theme import BG, ACCENT, FG, GREEN, RED, place_near, fit


class ReoptDialog(tk.Toplevel):
    def __init__(self, master, folder, ctx, on_applied=None):
        super().__init__(master)
        self.folder = folder
        self.ctx = ctx
        self.on_applied = on_applied
        self.proposals = None
        self.title("再最適化（提案 → 承認で適用）")
        self.configure(bg=BG)
        fit(self, 620, 520)
        self._build()
        place_near(self, master)
        self.after(100, self._run_propose)

    def _build(self):
        self.status = ttk.Label(self, text="提案を計算中…（直近データでグリッド探索＋過適合ガード）",
                                foreground=ACCENT)
        self.status.pack(anchor="w", padx=12, pady=(12, 4))

        cols = ("group", "param", "old", "new")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", style="Dark.Treeview", height=12)
        for c, (t, w, a) in zip(cols, [("戦略/グループ", 200, tk.W), ("パラメータ", 130, tk.W),
                                       ("現行(old)", 110, tk.E), ("提案(new)", 110, tk.E)]):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor=a)
        self.tree.tag_configure("chg", foreground=GREEN)     # 変更あり
        self.tree.tag_configure("same", foreground=FG)       # 変更なし
        self.tree.pack(fill="both", expand=True, padx=12, pady=4)

        self.note = tk.Text(self, height=5, wrap="word", font=("Consolas", 9))
        self.note.pack(fill="x", padx=12, pady=(0, 6))

        btns = ttk.Frame(self)
        btns.pack(side="bottom", fill="x", pady=8)
        ttk.Button(btns, text="閉じる", command=self.destroy).pack(side="right", padx=(0, 10))
        self.btn_apply = ttk.Button(btns, text="承認して適用", command=self._apply, state="disabled")
        self.btn_apply.pack(side="right", padx=6)

    # ── propose（重い・スレッド）──
    def _run_propose(self):
        threading.Thread(target=self._propose_worker, daemon=True).start()

    def _propose_worker(self):
        try:
            from app.engine import reopt
            prop = reopt.propose(self.folder, self.ctx)
            self.after(0, lambda: self._show(prop))
        except Exception as e:
            self.after(0, lambda: self.status.config(text=f"エラー: {e}"))

    def _show(self, prop):
        self.proposals = prop
        self.status.config(text=f"{prop.get('title', '再最適化')}    期間: {prop.get('window', '-')}")
        self.tree.delete(*self.tree.get_children())
        for it in prop.get("items", []):
            old, new = it.get("old"), it.get("new")
            changed = str(old) != str(new)
            self.tree.insert("", "end",
                             values=(it.get("group", ""), it.get("param", ""), old, new),
                             tags=("chg" if changed else "same",))
        self.note.delete("1.0", "end")
        self.note.insert("1.0", prop.get("note", ""))
        has_change = bool(prop.get("_payload"))
        self.btn_apply.config(state=("normal" if has_change else "disabled"))
        if not has_change:
            self.status.config(text=self.status.cget("text") + "  — 変更なし（現行維持）")

    # ── apply（承認・スレッド）──
    def _apply(self):
        if not self.proposals or not self.proposals.get("_payload"):
            return
        if not messagebox.askyesno("再最適化の適用",
                                   "提案された new の値を config に書き込みます。よろしいですか？",
                                   parent=self):
            return
        self.btn_apply.config(state="disabled")
        self.status.config(text="適用中…")
        threading.Thread(target=self._apply_worker, daemon=True).start()

    def _apply_worker(self):
        try:
            from app.engine import reopt
            reopt.apply(self.folder, self.ctx, self.proposals)
            self.after(0, self._done)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("適用エラー", str(e), parent=self))

    def _done(self):
        if self.on_applied:
            try:
                self.on_applied()
            except Exception:
                pass
        messagebox.showinfo("再最適化", "適用しました。パラメータ画面に反映し、バックテストで確認してください。",
                            parent=self)
        self.destroy()
