# -*- coding: utf-8 -*-
"""市場データ管理ダイアログ（蓄積ストアの確認・CSV/xlsx 取込・書き出し・6ヶ月トリム）。

下段 [📁 データ管理] ボタンから開く独立小窓。メイン画面のレイアウトには影響しない。
取込は3形式（拡張子＋内容で自動判別）：
  ① 実時刻CSV（kabu Station 等）   … 変換なし・直近ギャップ補完
  ② 225Labo xlsx（取引日→実時刻） … 6ヶ月以上の履歴
  ③ TradingView CSV（実時刻+09:00）… TV 保有者向け。実時刻なので変換なし・CSV優先でマージ（TV足で補正）
蓄積ストア＝`data/ohlc_live.parquet`（ライブ確定足＋取込・6ヶ月ローリング・BT/warmup兼用）。
取込はネットワーク/重い処理になり得るため別スレッドで実行し GUI を固めない。
"""
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

from app.backtest import data_import as di
from .theme import BG, PANEL_BG, PANEL_BG_HI, FG, FG_DIM, ACCENT, GREEN, YELLOW, RED, brighten, place_near, fit


class DataDialog(tk.Toplevel):
    def __init__(self, master, parquet_path, on_changed=None):
        super().__init__(master)
        self.parquet_path = str(parquet_path)
        self.on_changed = on_changed
        self._busy = False
        self.configure(bg=BG)
        self.title("市場データ管理")
        fit(self, 560, 290); self.resizable(False, False)
        self.transient(master); self.grab_set()
        self._build()
        self._refresh()
        place_near(self, master)

    def _build(self):
        tk.Label(self, text="市場データ管理（蓄積ストア・6ヶ月ローリング）", bg=BG, fg=ACCENT,
                 font=("Segoe UI Semibold", 11)).pack(anchor="w", padx=16, pady=(14, 6))
        info = tk.Frame(self, bg=BG); info.pack(fill="x", padx=16)
        self.lbl_n = tk.Label(info, text="", bg=BG, fg=FG, font=("Segoe UI", 9), anchor="w", justify="left")
        self.lbl_n.pack(anchor="w")
        self.lbl_chk = tk.Label(info, text="", bg=BG, fg=FG, font=("Segoe UI", 9), anchor="w", justify="left")
        self.lbl_chk.pack(anchor="w", pady=(2, 0))
        self.lbl_path = tk.Label(info, text="", bg=BG, fg=FG_DIM, font=("Consolas", 8), anchor="w")
        self.lbl_path.pack(anchor="w", pady=(2, 8))

        g = tk.Frame(self, bg=BG); g.pack(fill="x", padx=16)
        self.btn_imp = self._row(g, "📥 ファイルを取り込み", "CSV（kabu / TradingView）/ xlsx（225Labo）を自動判別・6ヶ月で自動整形", self._imp, ACCENT)
        self._row(g, "🕯 ろうそく足を表示", "蓄積ストアの中身を表で確認（CSV保存も可）", self._show, PANEL_BG_HI, fg=FG)

        tk.Label(self, text="※ 取込＝CSV（kabu 等の実時刻 / TradingView の +09:00 実時刻）または 225Labo xlsx（取引日は自動変換）。"
                           "TV を持っていれば TV CSV で蓄積足を補正できます（CSV優先マージ）。6ヶ月超は自動で切詰。長期履歴＝225Labo。",
                 bg=BG, fg=FG_DIM, font=("Segoe UI", 8), anchor="w", justify="left", wraplength=520).pack(
            anchor="w", padx=16, pady=(8, 0))
        btns = tk.Frame(self, bg=BG); btns.pack(side="bottom", fill="x", padx=16, pady=12)
        self._cbtn(btns, "  閉じる", self.destroy, PANEL_BG_HI, FG).pack(side="right")

    def _row(self, parent, title, desc, cmd, color, fg="#1a1b26"):
        r = tk.Frame(parent, bg=BG); r.pack(fill="x", pady=3)
        b = self._cbtn(r, f"  {title}", cmd, color, fg)
        b.config(width=22); b.pack(side="left")
        tk.Label(r, text="  " + desc, bg=BG, fg=FG_DIM, font=("Segoe UI", 8), anchor="w").pack(side="left")
        return b

    def _cbtn(self, parent, text, cmd, color, fg):
        b = tk.Button(parent, text=text, command=cmd, font=("Segoe UI", 10), bg=color, fg=fg,
                      relief=tk.FLAT, padx=12, pady=6, cursor="hand2", bd=0,
                      activebackground=color, activeforeground=fg, anchor="w")
        b.bind("<Enter>", lambda e, b=b, c=color: b.config(bg=brighten(c, 0.15)))
        b.bind("<Leave>", lambda e, b=b, c=color: b.config(bg=c))
        return b

    def _refresh(self):
        st = di.store_status(self.parquet_path)
        self.lbl_path.config(text=self.parquet_path)
        if st["n"] == 0:
            self.lbl_n.config(text="蓄積ストア: まだデータがありません")
            self.lbl_chk.config(text="warmup ⚠ / BT(6ヶ月) ⚠ … データを取り込んでください", fg=YELLOW)
            return
        self.lbl_n.config(text=f"蓄積ストア: {st['n']:,} 本 ・ {st['first']:%Y/%m/%d %H:%M} 〜 {st['last']:%Y/%m/%d %H:%M}")
        wu = "✅" if st["warmup_ok"] else "⚠ 不足"
        bt = "✅" if st["bt_ok"] else "⚠ 不足（履歴を取り込んでください）"
        self.lbl_chk.config(text=f"warmup(≥300本): {wu}    BT({st['bt_months']}ヶ月): {bt}",
                            fg=(GREEN if (st["warmup_ok"] and st["bt_ok"]) else YELLOW))

    # ── 操作（別スレッド・処理中表示＋完了ダイアログ）──
    def _run(self, fn, label, busy_btn=None, busy_text="処理中…"):
        if self._busy:
            return
        self._busy = True
        self._busy_btn = busy_btn
        if busy_btn is not None:
            self._busy_orig = busy_btn.cget("text")
            busy_btn.config(text=f"  ⏳ {busy_text}", state=tk.DISABLED)
        try:
            self.config(cursor="watch")
        except Exception:
            pass

        def work():
            try:
                res = fn()
                self.after(0, lambda: self._done(label, res, None))
            except Exception as e:
                self.after(0, lambda: self._done(label, None, e))
        threading.Thread(target=work, daemon=True).start()

    def _done(self, label, res, err):
        self._busy = False
        try:
            self.config(cursor="")
        except Exception:
            pass
        if getattr(self, "_busy_btn", None) is not None:
            try:
                self._busy_btn.config(text=self._busy_orig, state=tk.NORMAL)
            except Exception:
                pass
            self._busy_btn = None
        if err is not None:
            messagebox.showerror(f"{label}エラー", f"❌ 失敗しました。\n\n{err}", parent=self)
            return
        try:
            self._refresh()
            if self.on_changed:
                self.on_changed()
        except Exception:
            pass
        messagebox.showinfo(f"{label}完了", f"✅ {label}が完了しました。\n\n{res or ''}", parent=self)

    def _imp(self):
        # ★Explorer は data/csv_import を既定で開く（ダウンロードデータの保存先・推奨）。
        csv_dir = Path(self.parquet_path).parent / "csv_import"
        csv_dir.mkdir(parents=True, exist_ok=True)
        p = filedialog.askopenfilename(
            title="取り込むファイルを選択（CSV / 225Labo xlsx / ZIP）",
            initialdir=str(csv_dir),
            filetypes=[("対応ファイル", "*.csv *.xlsx *.zip"), ("CSV", "*.csv"),
                       ("Excel", "*.xlsx"), ("ZIP（225Labo）", "*.zip"), ("すべて", "*.*")])
        if not p:
            return
        self._run(lambda: self._import_and_tidy(p, csv_dir),
                  "取り込み", busy_btn=self.btn_imp, busy_text="取込中…")

    def _import_and_tidy(self, p, csv_dir):
        """取込→csv_import フォルダを最新5本に整理（古い CSV を _archive へ退避）。"""
        r = di.import_auto(p, self.parquet_path)
        arc = di.archive_old_csvs(csv_dir)          # 既定 CSV_KEEP=5 本を保持
        return self._fmt_import(r, arc)

    @staticmethod
    def _fmt_import(r, arc=None):
        kind = "225Labo（取引日→実時刻）" if r.get("fmt") == "labo" else "CSV"
        msg = (f"[{kind}] 取込 {r['added_rows']:,} 本 → 蓄積 {r['before']:,}→{r['after']:,} 本"
               + (f"（{r['first']:%Y/%m/%d}〜{r['last']:%Y/%m/%d}）" if r['last'] is not None else "")
               + "\n（6ヶ月超は自動で切り詰め済）")
        if arc and arc.get("moved"):
            msg += f"\n🗂 古い CSV {len(arc['moved'])} 本を _archive へ退避（最新5本を保持）"
        return msg

    def _show(self):
        CandleViewer(self, self.parquet_path)


class CandleViewer(tk.Toplevel):
    """蓄積ストアのローソク足を表で表示（直近 SHOW 本）＋ 全件 CSV 保存。"""
    SHOW = 1000

    def __init__(self, master, parquet_path):
        super().__init__(master)
        self.parquet_path = str(parquet_path)
        self.configure(bg=BG)
        self.title("ろうそく足（蓄積ストア）")
        fit(self, 580, 540); self.resizable(False, False)
        self.transient(master); self.grab_set()
        self._build()
        place_near(self, master)

    def _build(self):
        from app.backtest import data_provider as dp
        df = dp.load_parquet(self.parquet_path)
        n = len(df)
        tk.Label(self, text="ろうそく足（蓄積ストア）", bg=BG, fg=ACCENT,
                 font=("Segoe UI Semibold", 11)).pack(anchor="w", padx=16, pady=(14, 4))
        head = (f"{n:,} 本 ・ {df.index[0]:%Y/%m/%d %H:%M} 〜 {df.index[-1]:%Y/%m/%d %H:%M}"
                if n else "データがありません")
        tk.Label(self, text=head, bg=BG, fg=FG, font=("Segoe UI", 9)).pack(anchor="w", padx=16)
        tk.Label(self, text=f"（新しい順・直近 {min(n, self.SHOW):,} 本を表示／全件は[CSVで保存]）",
                 bg=BG, fg=FG_DIM, font=("Segoe UI", 8)).pack(anchor="w", padx=16, pady=(0, 6))

        body = tk.Frame(self, bg=PANEL_BG); body.pack(fill="both", expand=True, padx=16)
        cols = ("dt", "o", "h", "l", "c", "v")
        tv = ttk.Treeview(body, columns=cols, show="headings", style="Dark.Treeview", height=15)
        for c, (t, w, a) in zip(cols, [("日時", 140, tk.W), ("始値", 70, tk.E), ("高値", 70, tk.E),
                                        ("安値", 70, tk.E), ("終値", 70, tk.E), ("出来高", 80, tk.E)]):
            tv.heading(c, text=t); tv.column(c, width=w, anchor=a)
        sb = ttk.Scrollbar(body, orient="vertical", command=tv.yview); tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        for idx, row in df.tail(self.SHOW).iloc[::-1].iterrows():
            tv.insert("", "end", values=(f"{idx:%Y/%m/%d %H:%M}", f"{row['open']:.0f}",
                                          f"{row['high']:.0f}", f"{row['low']:.0f}",
                                          f"{row['close']:.0f}", f"{row['volume']:.0f}"))

        btns = tk.Frame(self, bg=BG); btns.pack(side="bottom", fill="x", padx=16, pady=12)
        self._cbtn(btns, "  閉じる", self.destroy, PANEL_BG_HI, FG).pack(side="right")
        self._cbtn(btns, "  CSVで保存", self._save, ACCENT, "#1a1b26").pack(side="right", padx=6)

    def _cbtn(self, parent, text, cmd, color, fg):
        b = tk.Button(parent, text=text, command=cmd, font=("Segoe UI", 10), bg=color, fg=fg,
                      relief=tk.FLAT, padx=14, pady=7, cursor="hand2", bd=0,
                      activebackground=color, activeforeground=fg)
        b.bind("<Enter>", lambda e, b=b, c=color: b.config(bg=brighten(c, 0.15)))
        b.bind("<Leave>", lambda e, b=b, c=color: b.config(bg=c))
        return b

    def _save(self):
        p = filedialog.asksaveasfilename(title="ローソク足の CSV 保存先", defaultextension=".csv",
                                         initialfile="ohlc_store.csv", filetypes=[("CSV", "*.csv")])
        if not p:
            return
        try:
            n = di.export_store_csv(self.parquet_path, p)
            messagebox.showinfo("CSV保存", f"{n:,} 本を保存しました:\n{p}", parent=self)
        except Exception as e:
            messagebox.showerror("CSV保存エラー", str(e), parent=self)
