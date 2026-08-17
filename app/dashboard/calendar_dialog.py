# -*- coding: utf-8 -*-
"""市場カレンダー管理ダイアログ（祝日取引の実施/非実施の確認・JPX から更新・取得元URLの手動設定）。

操作ボタン行の[📅 カレンダー]から開く独立小窓。メイン画面のレイアウトには影響しない。
保存先＝`data/market_Calendar.csv`（自己完結・[`calendar_fetch`](../feed/calendar_fetch.py)）。
取得はネットワーク処理のため別スレッドで実行し、GUI を固めない。

★設計（2026-06-27）:
  - 取得元URL（JPX）は settings.json（controller）に保存し、ここで手動編集できる。
    将来 JPX がURL/ページ構造を変えても、コード変更なしでここを直せば取得が復帰する。
  - 取得失敗（URL変更の可能性）は「取得元URLを手動で設定してください」と明示し、既存CSVは壊さない。
  - 鮮度（最終更新・取得済み年・確定/予定）をダイアログ内に表示（メイン画面には専用行を作らない）。
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox

from app.feed import calendar_fetch as cal
from .theme import BG, PANEL_BG, PANEL_BG_HI, FG, FG_DIM, ACCENT, GREEN, RED, brighten, place_near, fit


class CalendarDialog(tk.Toplevel):
    def __init__(self, master, controller=None, on_done=None):
        super().__init__(master)
        self.ctrl = controller
        self.on_done = on_done                 # 閉じる/更新後にダッシュボードへ再評価を促すコールバック
        self._busy = False
        self.configure(bg=BG)
        self.title("市場カレンダー（祝日取引の実施/非実施）")
        fit(self, 600, 540); self.resizable(False, False)
        self.transient(master); self.grab_set()
        self._build()
        self._refresh()
        place_near(self, master)
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ───────────────── 取得元URL（settings 由来・既定フォールバック）─────────────────
    def _current_url(self) -> str:
        try:
            if self.ctrl is not None:
                u = (self.ctrl.settings().get("jpx_calendar_url") or "").strip()
                if u:
                    return u
        except Exception:
            pass
        return cal.DEFAULT_JPX_URL

    def _build(self):
        tk.Label(self, text="市場カレンダー（祝日取引の実施/非実施）", bg=BG, fg=ACCENT,
                 font=("Segoe UI Semibold", 11)).pack(anchor="w", padx=16, pady=(14, 6))

        # 鮮度サマリ（色分け：要更新=赤／正常=淡色）。メイン画面に行を作らず、ここに集約。
        self.lbl_stat = tk.Label(self, text="", bg=BG, fg=FG, font=("Segoe UI", 9), anchor="w", justify="left")
        self.lbl_stat.pack(anchor="w", padx=16)
        self.lbl_path = tk.Label(self, text="", bg=BG, fg=FG_DIM, font=("Consolas", 8), anchor="w", justify="left")
        self.lbl_path.pack(anchor="w", padx=16, pady=(2, 6))

        body = tk.Frame(self, bg=PANEL_BG); body.pack(fill="both", expand=True, padx=16)
        cols = ("date", "name", "status", "confirmed")
        self.tree = ttk.Treeview(body, columns=cols, show="headings", style="Dark.Treeview", height=11)
        for c, (t, w, a) in zip(cols, [("日付", 96, tk.CENTER), ("名称", 188, tk.W),
                                       ("取引", 150, tk.W), ("確定/予定", 80, tk.CENTER)]):
            self.tree.heading(c, text=t); self.tree.column(c, width=w, anchor=a)
        self.tree.tag_configure("no", foreground=RED)      # 取引停止日＝赤
        self.tree.tag_configure("yes", foreground=FG_DIM)  # 実施する＝淡色
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")

        # 取得元URL（手動設定）
        urow = tk.Frame(self, bg=BG); urow.pack(fill="x", padx=16, pady=(8, 0))
        tk.Label(urow, text="取得元URL（JPX）:", bg=BG, fg=FG_DIM, font=("Segoe UI", 9)).pack(side="left")
        self.url_var = tk.StringVar(value=self._current_url())
        self.ent_url = tk.Entry(urow, textvariable=self.url_var, bg=PANEL_BG, fg=FG,
                                insertbackground=FG, relief=tk.FLAT, font=("Consolas", 8))
        self.ent_url.pack(side="left", fill="x", expand=True, padx=(6, 0), ipady=3)

        tk.Label(self, text="※ JPX 祝日取引ページから対象日（祝日＋年末年始休業）を取得し data/market_Calendar.csv に"
                           "蓄積します（複数年・既存は保持）。赤＝取引停止日。土日・年末年始・大納会の夜間は内部の"
                           "構造ルールで扱うため一覧には出ません。",
                 bg=BG, fg=FG_DIM, font=("Segoe UI", 8), anchor="w", justify="left", wraplength=560).pack(
            anchor="w", padx=16, pady=(6, 0))

        btns = tk.Frame(self, bg=BG); btns.pack(side="bottom", fill="x", padx=16, pady=12)
        self._cbtn(btns, "  閉じる", self._close, PANEL_BG_HI, FG).pack(side="right")
        self.btn_update = self._cbtn(btns, "  ↻ JPXから取得して更新", self._update, GREEN, "#1a1b26")
        self.btn_update.pack(side="right", padx=6)

    def _cbtn(self, parent, text, cmd, color, fg):
        b = tk.Button(parent, text=text, command=cmd, font=("Segoe UI", 10), bg=color, fg=fg,
                      relief=tk.FLAT, padx=14, pady=7, cursor="hand2", bd=0,
                      activebackground=color, activeforeground=fg)
        b.bind("<Enter>", lambda e, b=b, c=color: b.config(bg=brighten(c, 0.15)))
        b.bind("<Leave>", lambda e, b=b, c=color: b.config(bg=c))
        return b

    def _refresh(self):
        recs = cal.read_calendar()
        self.tree.delete(*self.tree.get_children())
        for r in recs:
            no = "実施しない" in r.get("status", "")
            self.tree.insert("", "end",
                             values=(r["date"], r["name"], r["status"], r.get("confirmed", "")),
                             tags=("no" if no else "yes",))
        self.lbl_path.config(text=str(cal.SAVE_PATH))
        st = cal.ui_status()
        self.lbl_stat.config(text=st["message"],
                             fg=(RED if st["need_update"] else FG_DIM))

    def _update(self):
        if self._busy:
            return
        self._busy = True
        self.btn_update.config(state=tk.DISABLED, text="  取得中…")
        url = (self.url_var.get() or "").strip()
        # 入力されたURLを settings に保存（次回以降この取得元を使う）
        if self.ctrl is not None:
            try:
                self.ctrl.set_calendar_url(url)
            except Exception:
                pass

        def work():
            try:
                recs = cal.update_calendar(url=url or None)
                # ライブ判定（is_open_at）が使う取引停止日キャッシュも更新する
                try:
                    from app.feed import _market_hours as mh
                    mh.load_calendar()
                except Exception:
                    pass
                self.after(0, lambda: self._done(len(recs), cal.no_trade_count(recs), None))
            except Exception as e:
                self.after(0, lambda: self._done(0, 0, e))

        threading.Thread(target=work, daemon=True).start()

    def _done(self, total, no_trade, err):
        self._busy = False
        self.btn_update.config(state=tk.NORMAL, text="  ↻ JPXから取得して更新")
        if err is not None:
            if isinstance(err, cal.CalendarFetchError):
                messagebox.showerror(
                    "カレンダー取得エラー",
                    f"{err}\n\nJPX のURLが変わった可能性があります。上の「取得元URL」欄に正しいURLを"
                    f"手動で設定してから、もう一度［更新］してください。\n（既存のカレンダーは保持されています）",
                    parent=self)
            else:
                messagebox.showerror("カレンダー更新エラー",
                                     f"取得に失敗しました:\n{err}\n\n（既存のカレンダーは保持されています）",
                                     parent=self)
            return
        self._refresh()
        if callable(self.on_done):
            try:
                self.on_done()                 # ダッシュボードのボタン色/ログを再評価
            except Exception:
                pass
        messagebox.showinfo("カレンダー更新",
                            f"更新しました（{total} 件・取引停止日 {no_trade} 件）。", parent=self)

    def _close(self):
        if callable(self.on_done):
            try:
                self.on_done()
            except Exception:
                pass
        self.destroy()
