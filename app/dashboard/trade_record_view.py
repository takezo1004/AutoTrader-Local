# -*- coding: utf-8 -*-
"""取引記録ビュー — 仮想/本番の取引イベント（新規建玉・決済）を発生順に記録したものを表示。

2つの表示：
  ① 記録通り（log）  : 全イベントを時系列で（新規/決済・方向・数量・価格・損益）。
  ② 取引一覧（trade）: 決済イベントをバックテストの取引一覧風に（エントリー/決済/損益）。
フィルタ：戦略（全戦略/各戦略）・期間（全期間/当日/今週/今月）。[クリア][CSVで保存]。
データ＝controller.read_trade_log()（app/state/trade_log.jsonl）。
"""
from __future__ import annotations

import csv
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

from .theme import BG, PANEL_BG, PANEL_BG_HI, FG, FG_DIM, ACCENT, GREEN, RED, brighten, place_near, fit


def _date_of(s):
    s = str(s).strip().replace("T", " ")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None


def _dt(s, full=False):
    s = str(s).strip().replace("T", " ")
    return s[:16].replace("-", "/") if full else s[5:16].replace("-", "/")


class TradeRecordView(tk.Toplevel):
    def __init__(self, master, controller):
        super().__init__(master)
        self.ctrl = controller
        self.configure(bg=BG)
        self.title("取引記録")
        fit(self, 1220, 600); self.resizable(True, True)   # 取引一覧の全列(累計まで・計1,160px)+スクロールバーが一画面に収まる幅
        self.transient(master); self.grab_set()
        self.view = tk.StringVar(value="記録通り")
        self.period = "all"
        self.strategy = tk.StringVar(value="全戦略")
        self.records = self.ctrl.read_trade_log()
        self._build()
        self._refresh()
        place_near(self, master)

    def _build(self):
        bar = tk.Frame(self, bg=BG); bar.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(bar, text="戦略", bg=BG, fg=FG, font=("Segoe UI", 9)).pack(side="left")
        # 登録済みの全戦略（alert_name）を列挙＋記録にある戦略も補完（過去に登録解除した分も見える）。
        reg = [(r.get("alert_name") or r.get("name")) for r in getattr(self.ctrl, "_registered", [])]
        rec = [r.get("strategy") for r in self.records if r.get("strategy")]
        names = ["全戦略"] + list(dict.fromkeys([n for n in (reg + rec) if n]))
        ttk.Combobox(bar, textvariable=self.strategy, values=names, state="readonly",
                     width=16).pack(side="left", padx=(4, 12))
        tk.Label(bar, text="表示", bg=BG, fg=FG, font=("Segoe UI", 9)).pack(side="left")
        ttk.Combobox(bar, textvariable=self.view, values=["記録通り", "取引一覧"], state="readonly",
                     width=10).pack(side="left", padx=(4, 12))
        for label, key in (("全期間", "all"), ("当日", "day"), ("今週", "week"), ("今月", "month")):
            self._pbtn(bar, label, key).pack(side="left", padx=2)
        self.strategy.trace_add("write", lambda *_: self._refresh())
        self.view.trace_add("write", lambda *_: self._refresh())

        self.lbl = tk.Label(self, text="", bg=BG, fg=FG, font=("Segoe UI", 10), anchor="w")
        self.lbl.pack(fill="x", padx=12, pady=(2, 4))
        self.holder = tk.Frame(self, bg=PANEL_BG); self.holder.pack(fill="both", expand=True, padx=12)

        btns = tk.Frame(self, bg=BG); btns.pack(side="bottom", fill="x", padx=12, pady=10)
        self._cbtn(btns, "  閉じる", self.destroy, PANEL_BG_HI, FG).pack(side="right")
        self._cbtn(btns, "  CSVで保存", self._save_csv, ACCENT, "#1a1b26").pack(side="right", padx=6)
        self._cbtn(btns, "  この戦略の記録を削除", self._del_strategy, RED, "#1a1b26").pack(side="right", padx=6)
        self._cbtn(btns, "  全削除", self._clear, RED, "#1a1b26").pack(side="right", padx=6)
        self._cbtn(btns, "  再読込", self._reload, PANEL_BG_HI, FG).pack(side="left")
        self._cbtn(btns, "  アーカイブを開く", self._open_archive, PANEL_BG_HI, FG).pack(side="left", padx=6)

    def _pbtn(self, parent, label, key):
        def on():
            self.period = key; self._refresh()
        return self._cbtn(parent, label, on, PANEL_BG_HI, FG)

    def _cbtn(self, parent, text, cmd, color, fg):
        b = tk.Button(parent, text=text, command=cmd, font=("Segoe UI", 9), bg=color, fg=fg,
                      relief=tk.FLAT, padx=10, pady=5, cursor="hand2", bd=0,
                      activebackground=color, activeforeground=fg)
        b.bind("<Enter>", lambda e, b=b, c=color: b.config(bg=brighten(c, 0.15)))
        b.bind("<Leave>", lambda e, b=b, c=color: b.config(bg=c))
        return b

    # ── データ ──
    def _filtered(self):
        st = self.strategy.get()
        rows = []
        for r in self.records:
            if st != "全戦略" and r.get("strategy") != st:
                continue
            d = _date_of(r.get("ts"))
            if self.period != "all" and d is not None:
                today = datetime.now().date()
                if self.period == "day" and d != today:
                    continue
                if self.period == "month" and not (d.year == today.year and d.month == today.month):
                    continue
                if self.period == "week" and not (today - timedelta(days=today.weekday()) <= d <= today):
                    continue
            rows.append(r)
        return rows

    def _refresh(self):
        for w in self.holder.winfo_children():
            w.destroy()
        rows = self._filtered()
        if self.view.get() == "取引一覧":
            self._show_trade(rows)
        else:
            self._show_log(rows)

    def _make_tree(self, cols, heads):
        tv = ttk.Treeview(self.holder, columns=cols, show="headings", style="Dark.Treeview", height=16)
        for c, (t, w, a) in zip(cols, heads):
            # stretch=False＝列幅を固定し、合計が窓幅を超えたら横スクロールで見せる。
            tv.heading(c, text=t); tv.column(c, width=w, anchor=a, stretch=False)
        tv.tag_configure("buy", foreground=GREEN)
        tv.tag_configure("sell", foreground=RED)
        tv.tag_configure("win", foreground=GREEN)
        tv.tag_configure("loss", foreground=RED)
        tv.tag_configure("flat", foreground=FG)
        vsb = ttk.Scrollbar(self.holder, orient="vertical", command=tv.yview)
        hsb = ttk.Scrollbar(self.holder, orient="horizontal", command=tv.xview)
        tv.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        # grid 配置：本体(0,0)＋縦バー(0,1)＋横バー(1,0)。本体だけ伸縮させる。
        tv.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.holder.rowconfigure(0, weight=1)
        self.holder.columnconfigure(0, weight=1)
        self.bind("<MouseWheel>", lambda e: tv.yview_scroll(int(-e.delta / 120), "units"))
        self.bind("<Shift-MouseWheel>", lambda e: tv.xview_scroll(int(-e.delta / 120), "units"))
        return tv

    def _show_log(self, rows):
        cols = ("ts", "mode", "stg", "kind", "dir", "qty", "px", "pnl")
        heads = [("時刻", 140, tk.W), ("仮/本", 50, tk.CENTER), ("戦略", 130, tk.W),
                 ("種別", 56, tk.CENTER), ("方向", 56, tk.CENTER), ("数量", 48, tk.CENTER),
                 ("価格", 84, tk.E), ("損益(円)", 100, tk.E)]
        tv = self._make_tree(cols, heads)
        n = len(rows)
        pnl = sum(r["pnl_jpy"] for r in rows if r.get("pnl_jpy") is not None)
        self.lbl.config(text=f"記録通り（時系列）　{n} 件　決済損益 合計 {pnl:+,} 円")
        for r in reversed(rows):                   # 最新が上
            pj = r.get("pnl_jpy")
            tag = "win" if (pj or 0) > 0 else ("loss" if (pj or 0) < 0 else "flat")
            if r.get("kind") == "新規":
                tag = "buy" if r.get("dir") == "Long" else "sell"
            tv.insert("", "end", values=(
                _dt(r.get("ts"), full=True), r.get("mode", ""), r.get("strategy", ""),
                r.get("kind", ""), r.get("dir", ""), r.get("qty", ""),
                f"{r.get('price', 0):.0f}" if r.get("price") is not None else "",
                f"{pj:+,}" if pj is not None else "—"), tags=(tag,))

    def _show_trade(self, rows):
        """取引一覧＝決済レグ（損益は決済レコード自身の記録値）＋未決済＋計算不可を表示する。

        ・損益が記録された決済 → 決済レグとして表示。累計＝時系列昇順の走行合計
          （新規との対応付けには依存しない＝記録さえあれば必ず累計に入る）。
        ・損益が記録されていない決済 → スキップせず載せ、「計算不可（損益記録なし）」と理由表示。
        ・決済し切っていない新規 → 「未決済(open)」として表示（こちらだけ新規↔決済の照合を使う）。
        """
        from app.engine.controller import pair_trades, _norm_ts
        # 列: 建玉側(エントリー/建値)と決済側(決済日時/決済値)の間に空スペーサ列 "sp" を挟む。
        #     末尾に「累計(円)」＝決済レグを時系列で積み上げた実現損益の走行合計。
        cols = ("ts", "mode", "stg", "dir", "ein", "epx", "sp", "exo", "xpx", "qty", "ppt", "pjy", "cum")
        heads = [("決済時刻", 138, tk.W), ("仮/本", 50, tk.CENTER), ("戦略", 120, tk.W),
                 ("方向", 52, tk.CENTER), ("エントリー", 116, tk.W), ("建値", 74, tk.E),
                 ("", 20, tk.CENTER),
                 ("決済日時", 116, tk.W), ("決済値", 74, tk.E), ("数量", 44, tk.CENTER),
                 ("損益(pt)", 76, tk.E), ("損益(円)/状態", 130, tk.E), ("累計(円)", 150, tk.E)]
        tv = self._make_tree(cols, heads)

        res = pair_trades(rows)                            # ★ビューとBT突合で同一のペアリング
        items = []                                         # (並べ替えts, values[累計は後埋め], tag, 損益 or None)
        for r in res["closed"]:
            pj = r.get("pnl_jpy", 0) or 0
            items.append((_norm_ts(r.get("ts")), [
                _dt(r.get("ts"), full=True), r.get("mode", ""), r.get("strategy", ""), r.get("dir", ""),
                _dt(r.get("entry_ts")), f"{r.get('entry_price', 0):.0f}",
                "",
                _dt(r.get("ts")), f"{r.get('price', 0):.0f}", r.get("qty", ""),
                f"{r.get('pnl_pt', 0):+.1f}", f"{pj:+,}",
                ""], "win" if pj > 0 else "loss", pj))
        for r in res["orphan"]:                            # 損益未記録＝計算不可（載せる・理由表示）
            items.append((_norm_ts(r.get("ts")), [
                _dt(r.get("ts"), full=True), r.get("mode", ""), r.get("strategy", ""), r.get("dir", ""),
                _dt(r.get("entry_ts")) if r.get("entry_ts") else "—",
                f"{r.get('entry_price', 0):.0f}" if r.get("entry_price") is not None else "—",
                "", _dt(r.get("ts")), f"{r.get('price', 0):.0f}", r.get("qty", ""),
                "—", "計算不可（損益記録なし）", "—"], "flat", None))
        for r in res["open"]:                              # 未決済(open)
            items.append((_norm_ts(r.get("ts")), [
                "未決済", r.get("mode", ""), r.get("strategy", ""), r.get("dir", ""),
                _dt(r.get("entry_ts")), f"{r.get('entry_price', 0):.0f}",
                "", "—", "—", r.get("open_qty", r.get("qty", "")), "—", "(保有中)", "—"], "flat", None))

        pnl = sum((r.get("pnl_jpy") or 0) for r in res["closed"])
        wins = sum(1 for r in res["closed"] if (r.get("pnl_jpy") or 0) > 0)
        items.sort(key=lambda x: x[0], reverse=True)       # 最新が上
        # 累計＝表示リストの一番下の行から上へ、決済レグの損益をそのまま積み上げる。
        # （時刻で別ソートしない＝同時刻の決済が複数あっても、表示行の損益と累計が必ず整合する）
        _cum = 0
        for _ts, values, tag, pj in reversed(items):
            if pj is not None:
                _cum += pj
                values[-1] = f"{_cum:+,}"
        for _ts, values, tag, _pj in items:
            tv.insert("", "end", values=values, tags=(tag,))
        self.lbl.config(text=(f"取引一覧　決済 {len(res['closed'])} レグ（勝ち {wins}）　"
                              f"未決済 {len(res['open'])}　計算不可 {len(res['orphan'])}　"
                              f"決済損益 合計 {pnl:+,} 円"))

    # ── 操作 ──
    def _reload(self):
        self.records = self.ctrl.read_trade_log()
        self._refresh()

    def _clear(self):
        if not messagebox.askyesno("確認", "取引記録をすべて削除しますか？（元に戻せません）", parent=self):
            return
        self.ctrl.clear_trade_log()
        self.records = []
        self._refresh()

    def _del_strategy(self):
        """①B案：選択中の戦略の記録だけ削除（使わなくなった戦略の記録を消す）。"""
        st = self.strategy.get()
        if st == "全戦略":
            messagebox.showinfo("この戦略の記録を削除",
                                "上の「戦略」で記録を削除したい戦略を選んでください。\n"
                                "（すべて消す場合は「全削除」。戦略そのものは消えません）", parent=self)
            return
        n = sum(1 for r in self.records if r.get("strategy") == st)
        if not n:
            messagebox.showinfo("この戦略の記録を削除", f"「{st}」の記録はありません。", parent=self)
            return
        if not messagebox.askyesno(
                "確認",
                f"「{st}」の取引記録 {n} 件を削除しますか？（元に戻せません）\n"
                "※記録（データ）だけ消えます。戦略そのものは削除されません。",
                parent=self):
            return
        self.ctrl.delete_strategy_records(st)
        self.records = self.ctrl.read_trade_log()
        self._refresh()

    def _open_archive(self):
        """②C案：data/history に退避された四半期アーカイブCSVを読み取り専用で開く。"""
        files = self.ctrl.list_archives()
        if not files:
            messagebox.showinfo("アーカイブ",
                                "退避済みのアーカイブはまだありません。\n"
                                "6ヶ月より古い記録は起動時に data/history へ自動退避されます。",
                                parent=self)
            return
        p = filedialog.askopenfilename(title="アーカイブCSVを開く",
                                       initialdir=str(self.ctrl.history_dir()),
                                       filetypes=[("CSV", "*.csv")])
        if p:
            ArchiveView(self, p)

    def _save_csv(self):
        rows = self._filtered()
        if self.view.get() == "取引一覧":
            rows = [r for r in rows if r.get("kind") == "決済"]
        if not rows:
            messagebox.showinfo("CSV保存", "保存する記録がありません。", parent=self)
            return
        p = filedialog.asksaveasfilename(title="取引記録の CSV 保存先", defaultextension=".csv",
                                         initialfile="trade_record.csv", filetypes=[("CSV", "*.csv")])
        if not p:
            return
        cols = ["ts", "mode", "strategy", "kind", "dir", "qty", "price",
                "entry_ts", "entry_price", "pnl_pt", "pnl_jpy", "reason", "trade_id"]
        try:
            with open(p, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
            messagebox.showinfo("CSV保存", f"{len(rows)} 件を保存しました:\n{p}", parent=self)
        except Exception as e:
            messagebox.showerror("CSV保存エラー", str(e), parent=self)


class ArchiveView(tk.Toplevel):
    """退避済みアーカイブCSV（trade_archive_YYYY-Qn.csv）の読み取り専用ビュー（記録通り・時系列）。"""

    def __init__(self, master, path):
        super().__init__(master)
        self.configure(bg=BG)
        self.title(f"アーカイブ — {Path(path).name}")
        fit(self, 980, 560); self.resizable(True, True)
        self.transient(master)
        try:
            with open(path, encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
        except Exception as e:
            messagebox.showerror("アーカイブ", str(e), parent=self)
            self.destroy(); return

        def _pnl(r):
            try:
                return int(float(r.get("pnl_jpy") or 0))
            except Exception:
                return 0

        pnl = sum(_pnl(r) for r in rows if r.get("kind") == "決済")
        tk.Label(self, text=f"{Path(path).name}　{len(rows)} 件　決済損益 合計 {pnl:+,} 円　（読み取り専用）",
                 bg=BG, fg=FG, font=("Segoe UI", 10), anchor="w").pack(fill="x", padx=12, pady=(12, 4))
        body = tk.Frame(self, bg=PANEL_BG); body.pack(fill="both", expand=True, padx=12)
        cols = ("ts", "mode", "stg", "kind", "dir", "qty", "px", "pnl")
        heads = [("時刻", 140, tk.W), ("仮/本", 50, tk.CENTER), ("戦略", 130, tk.W),
                 ("種別", 56, tk.CENTER), ("方向", 56, tk.CENTER), ("数量", 48, tk.CENTER),
                 ("価格", 84, tk.E), ("損益(円)", 100, tk.E)]
        tv = ttk.Treeview(body, columns=cols, show="headings", style="Dark.Treeview", height=18)
        for c, (t, w, a) in zip(cols, heads):
            tv.heading(c, text=t); tv.column(c, width=w, anchor=a)
        tv.tag_configure("win", foreground=GREEN); tv.tag_configure("loss", foreground=RED)
        tv.tag_configure("buy", foreground=GREEN); tv.tag_configure("sell", foreground=RED)
        tv.tag_configure("flat", foreground=FG)
        sb = ttk.Scrollbar(body, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y"); tv.pack(side="left", fill="both", expand=True)
        self.bind("<MouseWheel>", lambda e: tv.yview_scroll(int(-e.delta / 120), "units"))
        for r in reversed(rows):                  # 最新が上
            pj = _pnl(r)
            tag = "win" if pj > 0 else ("loss" if pj < 0 else "flat")
            if r.get("kind") == "新規":
                tag = "buy" if r.get("dir") == "Long" else "sell"
            try:
                px = f"{float(r.get('price')):.0f}" if r.get("price") not in (None, "") else ""
            except Exception:
                px = str(r.get("price", ""))
            tv.insert("", "end", values=(
                _dt(r.get("ts"), full=True), r.get("mode", ""), r.get("strategy", ""),
                r.get("kind", ""), r.get("dir", ""), r.get("qty", ""), px,
                f"{pj:+,}" if r.get("kind") == "決済" else "—"), tags=(tag,))

        bar = tk.Frame(self, bg=BG); bar.pack(side="bottom", fill="x", padx=12, pady=10)
        b = tk.Button(bar, text="  閉じる", command=self.destroy, font=("Segoe UI", 9),
                      bg=PANEL_BG_HI, fg=FG, relief=tk.FLAT, padx=10, pady=5, cursor="hand2", bd=0)
        b.pack(side="right")
        place_near(self, master)
