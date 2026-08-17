# -*- coding: utf-8 -*-
"""内蔵バックテスト ビュー（外部仕様 F2）— 半年BTを実行し成績を表示。

データ＝蓄積 parquet ＋ 取込 CSV を data_provider.build() でマージ（半年窓）。
controller.backtest(name, df) → full_report を summary/月別/コスト感度で表示。
損益曲線は簡易にテキスト/Canvas で（matplotlib 非依存）。
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox

from app.backtest import data_provider
from .theme import BG, PANEL_BG, PANEL_BG_HI, FG, FG_DIM, ACCENT, GREEN, YELLOW, RED, brighten, place_near, fit


class BacktestView(tk.Toplevel):
    def __init__(self, master, controller, name, parquet_path=None, csv_dir=None,
                 months=6, warmup_bars=300):
        super().__init__(master)
        self.controller = controller
        self.name = name
        self.parquet_path = parquet_path
        self.csv_dir = csv_dir
        self.months = months
        self.warmup_bars = warmup_bars
        self.title(f"バックテスト — {name}（直近{months}か月）")
        fit(self, 660, 640)
        self.configure(bg=BG)
        self._build()
        place_near(self, master)
        self.after(100, self._run)

    def _build(self):
        self._rep = None
        top = ttk.Frame(self); top.pack(fill="x", padx=8, pady=6)
        self.status = ttk.Label(top, text="データ準備中…")
        self.status.pack(side="left")
        ttk.Button(top, text="再実行", command=lambda: self.after(10, self._run)).pack(side="right")
        ttk.Button(top, text="取引一覧", command=self._open_trades).pack(side="right", padx=(0, 6))
        # ★集計（TradingView Performance Summary 風・全体/Long/Short）
        pcols = ("m", "all", "lng", "sht")
        self.perf = ttk.Treeview(self, columns=pcols, show="headings", style="Dark.Treeview", height=7)
        for c, (t, w, a) in zip(pcols, [("集計", 168, tk.W), ("全体", 138, tk.E),
                                         ("Long", 130, tk.E), ("Short", 120, tk.E)]):
            self.perf.heading(c, text=t); self.perf.column(c, width=w, anchor=a)
        self.perf.tag_configure("pos", foreground=GREEN)
        self.perf.tag_configure("neg", foreground=RED)
        self.perf.pack(fill="x", padx=8, pady=(0, 4))
        self.txt = tk.Text(self, wrap="none", font=("Consolas", 10), height=10)
        self.txt.pack(fill="both", expand=True, padx=8, pady=4)
        self.canvas = tk.Canvas(self, height=120, bg="#0b1021")
        self.canvas.pack(fill="x", padx=8, pady=(0, 8))

    def rerun(self):
        """既存の窓を閉じずに、その場で再計算して表示だけ更新する（パラメータ調整ループ用）。"""
        try:
            self.deiconify(); self.lift()
        except Exception:
            pass
        self.after(10, self._run)

    def _run(self):
        self.status.config(text="バックテスト実行中…")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            # ★BT は「作成済みローソク足（生 parquet ストア）」だけで行う（2026-06-23）。
            #   実行時の csv_import 再マージは廃止：取込は [データ管理] が parquet に書き込む設計なので
            #   再マージは冗長、かつ csv_import に置きっぱなしの別銘柄/古い CSV で BT が汚染される事故の元。
            #   （例: 別限月 161090019 の CSV が正しい足を上書きし、TV と不一致になっていた。）
            df = data_provider.window(data_provider.load_parquet(self.parquet_path),
                                      months=self.months, warmup_bars=self.warmup_bars)
            if df is None or len(df) == 0:
                self.after(0, lambda: self.status.config(text="データがありません（parquet/CSV を用意）"))
                return
            rep = self.controller.backtest(self.name, df)
            self.after(0, lambda: self._show(rep))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("BTエラー", str(e)))

    def _open_trades(self):
        if not self._rep or not self._rep.get("trades"):
            messagebox.showinfo("取引一覧", "先にバックテストを実行してください（取引がありません）。", parent=self)
            return
        TradeListView(self, self.name, self._rep["trades"])

    def _fill_perf(self, perf):
        self.perf.delete(*self.perf.get_children())
        if not perf:
            return
        a, l, s = perf["all"], perf["long"], perf["short"]

        def money_row(label, key):
            vals = (label, f"{a[key]:+,}", f"{l[key]:+,}", f"{s[key]:+,}")
            tag = "pos" if a[key] >= 0 else "neg"
            self.perf.insert("", "end", values=vals, tags=(tag,))

        money_row("純損益", "net")
        money_row("総利益", "gross_profit")
        money_row("総損失", "gross_loss")
        self.perf.insert("", "end", values=("プロフィットファクター", a["pf"], l["pf"], s["pf"]))
        money_row("期待損益(円/取引)", "expectancy")
        self.perf.insert("", "end", values=("取引数", a["n"], l["n"], s["n"]))
        self.perf.insert("", "end", values=("支払い済手数料", 0, 0, 0))

    def _show(self, rep):
        self._rep = rep
        self._fill_perf(rep.get("perf"))
        s = rep["summary"]
        self.status.config(text=f"{rep['bars']}本  {rep['period'][0]} 〜 {rep['period'][1]}")
        lines = [
            f"取引数  {s['n']}    勝率 {s['win']}%    PF {s['pf']}",
            f"純益    {s['pnl']:+,} 円    最大DD {s['dd']:+,} 円    平均保有 {s['avg_hold']} 本",
            "",
            "年別(n/PF):  " + "   ".join(f"{y}:{v[0]}/{v[1]}" for y, v in s["yearly"].items()),
            "",
            "コスト感度(1枚1往復pt):  " + "   ".join(
                f"{c['cost_pt']}pt→PF{c['pf']}/{c['pnl_jpy']:+,}円" for c in rep["cost"]),
            "",
            "月別(n / 純益円):",
        ]
        for m in rep["monthly"]:
            lines.append(f"  {m['month']}   n={m['n']:>3}   {m['pnl_jpy']:+,}")
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", "\n".join(lines))
        self._draw_equity(rep["equity"])

    def _draw_equity(self, equity):
        c = self.canvas
        c.delete("all")
        if not equity:
            return
        w = int(c.winfo_width()) or 600
        h = int(c.winfo_height()) or 120
        ys = [e["equity_jpy"] for e in equity]
        lo, hi = min(ys + [0]), max(ys + [0])
        rng = (hi - lo) or 1
        pts = []
        for i, y in enumerate(ys):
            x = 4 + i * (w - 8) / max(1, len(ys) - 1)
            yy = h - 4 - (y - lo) * (h - 8) / rng
            pts += [x, yy]
        zero_y = h - 4 - (0 - lo) * (h - 8) / rng
        c.create_line(0, zero_y, w, zero_y, fill="#334155")
        if len(pts) >= 4:
            c.create_line(*pts, fill="#34d399", width=2)


class TradeListView(tk.Toplevel):
    """取引一覧（TradingView の List of Trades 風）。1 行＝1 決済レグ。CSV 保存も可。"""

    def __init__(self, master, name, trades):
        super().__init__(master)
        self.name = name
        self.trades = trades or []
        self.configure(bg=BG)
        self.title(f"取引一覧 — {name}")
        fit(self, 980, 560); self.resizable(True, True)     # 全列（決済まで）が見える幅
        self.transient(master); self.grab_set()
        self._build()
        place_near(self, master)

    @staticmethod
    def _dt(s):
        s = str(s)
        return s[:16].replace("-", "/").replace("T", " ")    # YYYY/MM/DD HH:MM

    def _build(self):
        n = len(self.trades)
        total = self.trades[-1]["cum_jpy"] if n else 0
        wins = sum(1 for t in self.trades if t["pnl_jpy"] > 0)
        head = (f"{n} 決済レグ ・ 勝ち {wins} / 負け {n - wins} ・ 合計 {total:+,} 円"
                if n else "取引がありません")
        # ボタンバーを先に下へ確保（スクロール領域に隠されない）
        btns = tk.Frame(self, bg=BG); btns.pack(side="bottom", fill="x", padx=12, pady=10)
        self._cbtn(btns, "  閉じる", self.destroy, PANEL_BG_HI, FG).pack(side="right")
        self._cbtn(btns, "  CSVで保存", self._save_csv, ACCENT, "#1a1b26").pack(side="right", padx=6)

        tk.Label(self, text=head, bg=BG, fg=FG, font=("Segoe UI", 10)).pack(anchor="w", padx=12, pady=(12, 4))

        body = tk.Frame(self, bg=PANEL_BG); body.pack(fill="both", expand=True, padx=12)
        cols = ("no", "dir", "ein", "epx", "exo", "xpx", "qty", "ppt", "pjy", "cum", "rsn")
        heads = [("取引#", 56, tk.CENTER), ("方向", 56, tk.CENTER),
                 ("エントリー日時", 130, tk.W), ("建値", 78, tk.E),
                 ("決済日時", 130, tk.W), ("決済値", 78, tk.E),
                 ("数量", 48, tk.CENTER), ("損益(pt)", 80, tk.E),
                 ("損益(円)", 90, tk.E), ("累積(円)", 100, tk.E), ("決済", 90, tk.W)]
        tv = ttk.Treeview(body, columns=cols, show="headings", style="Dark.Treeview", height=16)
        for c, (t, w, a) in zip(cols, heads):
            tv.heading(c, text=t); tv.column(c, width=w, anchor=a)
        tv.tag_configure("win", foreground=GREEN)
        tv.tag_configure("loss", foreground=RED)
        sb = ttk.Scrollbar(body, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y"); tv.pack(side="left", fill="both", expand=True)
        # マウスホイールでもスクロール（このウィンドウにフォーカスがある間）
        self.bind("<MouseWheel>", lambda e: tv.yview_scroll(int(-e.delta / 120), "units"))
        for t in reversed(self.trades):          # ★最新（新しい決済）を頭に表示。累積は時系列のまま。
            tv.insert("", "end", values=(
                t["no"], t["dir"], self._dt(t["entry_ts"]), f"{t['entry_px']:.0f}",
                self._dt(t["exit_ts"]), f"{t['exit_px']:.0f}", t["qty"],
                f"{t['pnl_pt']:+.1f}", f"{t['pnl_jpy']:+,}", f"{t['cum_jpy']:+,}", t["reason"]),
                tags=("win" if t["pnl_jpy"] > 0 else "loss",))

    def _cbtn(self, parent, text, cmd, color, fg):
        b = tk.Button(parent, text=text, command=cmd, font=("Segoe UI", 10), bg=color, fg=fg,
                      relief=tk.FLAT, padx=14, pady=7, cursor="hand2", bd=0,
                      activebackground=color, activeforeground=fg)
        b.bind("<Enter>", lambda e, b=b, c=color: b.config(bg=brighten(c, 0.15)))
        b.bind("<Leave>", lambda e, b=b, c=color: b.config(bg=c))
        return b

    def _save_csv(self):
        from tkinter import filedialog
        import csv
        p = filedialog.asksaveasfilename(title="取引一覧の CSV 保存先", defaultextension=".csv",
                                         initialfile=f"trades_{self.name}.csv",
                                         filetypes=[("CSV", "*.csv")])
        if not p:
            return
        try:
            cols = ["no", "dir", "entry_ts", "entry_px", "exit_ts", "exit_px",
                    "qty", "pnl_pt", "pnl_jpy", "cum_jpy", "reason"]
            with open(p, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=cols)
                w.writeheader()
                w.writerows({k: t[k] for k in cols} for t in self.trades)
            messagebox.showinfo("CSV保存", f"{len(self.trades)} 行を保存しました:\n{p}", parent=self)
        except Exception as e:
            messagebox.showerror("CSV保存エラー", str(e), parent=self)
