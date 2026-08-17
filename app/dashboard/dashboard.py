# -*- coding: utf-8 -*-
"""ローカル版ダッシュボード（司令塔・独立1枚・外部仕様 §3・D9/D10）。

商用配布品質の UI（Tokyo Night テーマ・カード・DataGrid）。既存 `n225_brokerbridge_dashboard.py`
のデザイン言語（配色・カード・ホバーボタン・LED・ログ）を踏襲し、戦略一覧は ttk.Treeview（DataGrid）。

運用フロー（ダッシュボードで全てコントロール）:
  ① 戦略を登録 → ② カブステーション確認 → ③ ブリッジ起動（接続）。
  自動運用は起動と同時に始まる（feed待受＝記録開始）。**記録は全戦略・常時／注文は戦略の「有効」のみ**。
  停止は「戦略の有効を外す／ブリッジ停止／ダッシュボードを閉じる」（オートトレード用の起動/停止ボタンは無し）。

機能: 複数戦略登録 / パラメータGUI＋内蔵BT / 戦略ごと注文ON/OFF / 取引記録(全戦略常時) /
      ブリッジ起動停止 / モニター（カブ・ブリッジ・オートトレード・feed 稼働 LED）。
"""
from __future__ import annotations

import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk, filedialog, messagebox, scrolledtext

from app.engine import LocalEngineController, validate_folder
from .param_form import ParamForm
from .bt_view import BacktestView
from .register_dialog import RegisterDialog
from .settings_dialog import SettingsDialog
from .theme import apply_theme, BG, PANEL_BG, PANEL_BG_HI, FG, FG_DIM, ACCENT, GREEN, YELLOW, RED, PURPLE, LED_ON, LED_OFF, LED_ERR, LOG_BG, brighten, place_near, fit

ROOT = Path(__file__).resolve().parents[2]            # N225LocalEngine/


class Dashboard:
    def __init__(self, root: tk.Tk, controller: LocalEngineController,
                 parquet_path=None, csv_dir=None, warmup_provider=None, auto_start: bool = True):
        self.root = root
        self.ctrl = controller
        self.parquet_path = parquet_path
        self.csv_dir = csv_dir
        self.warmup_provider = warmup_provider or self._warmup_df
        self.ctrl.on_log = self._log
        # feed/OHLCManager のログ（TCP待受/ブリッジ接続/ポート使用中/確定足 等）をログ欄へ流す
        try:
            from app.feed import logger as _flog
            _flog.add_sink(self._log)
            self._feed_logger = _flog
        except Exception:
            self._feed_logger = None
        self._closed = False
        self._feed = None

        root.title("N225AutoTrader-Local")
        fit(root, 880, 520); root.minsize(820, 480)
        root.configure(bg=BG)
        apply_theme(root)
        self._build()
        self._refresh_rows()
        self._check_calendar_status()             # ★起動時にカレンダー鮮度を判定（ログ＋📅ボタン色）
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._start_poller()
        self._tick_clock()
        self._tick_status()
        if auto_start:
            # ★画面を先に完全表示してから warmup（5戦略・重い）を始める＝起動が一度に出て速く見える。
            #   after で初回描画後に回す（warmup は _auto_start 内でさらに別スレッド＝UI を固めない）。
            root.after(120, self._auto_start)    # 自動運用（feed待受＝記録開始）は描画後に開始

    # ═════════════════════════ レイアウト ═════════════════════════
    def _build(self):
        self._build_header()
        self._build_banner()
        self._build_cards()
        self._build_grid()
        self._build_log()

    def _build_banner(self):
        """記録停止などの重大状態を常時表示する赤バナー（既定は不可視）。
        feed が tick を受けていても記録していない、という"静かな障害"を見落とさないため。"""
        self._banner = tk.Frame(self.root, bg=BG)
        self._banner.pack(fill=tk.X, padx=16, pady=(0, 0))
        self._banner_lbl = tk.Label(self._banner, text="", bg=BG, fg="#ffffff",
                                     font=("Segoe UI Semibold", 10), justify=tk.LEFT,
                                     anchor="w", wraplength=820)
        self._banner_lbl.pack(fill=tk.X)

    def _build_header(self):
        # サブタイトルは廃止。タイトルを縮小し、設定・LED を左寄せにして横幅を詰める。
        h = tk.Frame(self.root, bg=BG, height=46); h.pack(fill=tk.X, padx=16, pady=(10, 6)); h.pack_propagate(False)
        tk.Label(h, text="N225AutoTrader-Local", font=("Segoe UI Semibold", 14), bg=BG, fg=ACCENT).pack(side=tk.LEFT)
        # 設定・LED・時計はまとめて右側（時間表示の隣）に寄せる。
        self.lbl_clock = tk.Label(h, text="--:--:--", font=("Consolas", 13), bg=BG, fg=FG_DIM)
        self.lbl_clock.pack(side=tk.RIGHT, padx=(8, 0))
        leds = tk.Frame(h, bg=BG); leds.pack(side=tk.RIGHT, padx=8)
        self.leds = {}
        for key, cap in (("kabu", "カブ"), ("bridge", "ブリッジ"), ("auto", "オートトレード"), ("feed", "feed")):
            self.leds[key] = self._make_led(leds, cap)
        self._cbtn(h, "  ⚙ 設定", self._open_settings, PANEL_BG_HI, fg=FG, pad=4).pack(side=tk.RIGHT, padx=8)

    def _build_cards(self):
        cards = tk.Frame(self.root, bg=BG); cards.pack(fill=tk.X, padx=16, pady=(4, 8))

        c1 = self._card(cards, "① 戦略", PURPLE); c1.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        brow1 = tk.Frame(c1, bg=PANEL_BG); brow1.pack(fill=tk.X, padx=10, pady=(8, 4))
        self._cbtn(brow1, "  ＋  追加", self._add, ACCENT, pad=6).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        self._cbtn(brow1, "  −  削除", self._remove, PANEL_BG_HI, fg=FG, pad=6).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(3, 0))
        tk.Label(c1, text="戦略を追加／選択を削除（下の一覧に表示）", font=("Segoe UI", 9),
                 bg=PANEL_BG, fg=FG_DIM).pack(padx=10, pady=(0, 8), anchor="w")

        c2 = self._card(cards, "② ブリッジ", ACCENT); c2.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))
        brow2 = tk.Frame(c2, bg=PANEL_BG); brow2.pack(fill=tk.X, padx=10, pady=(8, 4))
        self.bridge_start_btn = self._cbtn(brow2, "  ▶  起動", self._start_bridge, ACCENT, pad=6)
        self.bridge_start_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        self.bridge_stop_btn = self._cbtn(brow2, "  ■  停止", self._stop_bridge, RED, pad=6)
        self.bridge_stop_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(3, 0))
        tk.Label(c2, text="KABUステーション→ブリッジ起動／注文は戦略有効✓のみ",
                 font=("Segoe UI", 9), bg=PANEL_BG, fg=FG_DIM, justify=tk.LEFT,
                 wraplength=360).pack(padx=10, pady=(0, 8), anchor="w")
        # ★③オートトレードカード（起動/停止/仮想トグル）は廃止＝削除。注文は戦略一覧の「有効」で切替。

    def _build_grid(self):
        wrap = tk.Frame(self.root, bg=BG); wrap.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 8))
        bar = tk.Frame(wrap, bg=PANEL_BG_HI, height=26); bar.pack(fill=tk.X); bar.pack_propagate(False)
        tk.Frame(bar, bg=GREEN, width=3).pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(bar, text="  登録戦略", font=("Segoe UI Semibold", 10), bg=PANEL_BG_HI, fg=FG).pack(side=tk.LEFT)
        tk.Label(bar, text="「有効」をクリックで実行ON/OFF・行ダブルクリックで編集", font=("Segoe UI", 8),
                 bg=PANEL_BG_HI, fg=FG_DIM).pack(side=tk.RIGHT, padx=8)

        cols = ("on", "name", "alert", "ivl", "pos", "signal")
        body = tk.Frame(wrap, bg=PANEL_BG); body.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(body, columns=cols, show="headings", style="Dark.Treeview", height=6)
        for c, (t, w, anc) in zip(cols, [("有効", 60, tk.CENTER), ("戦略名", 180, tk.W), ("ショートネーム", 160, tk.W),
                                          ("足", 50, tk.CENTER), ("建玉", 100, tk.CENTER), ("直近シグナル", 180, tk.W)]):
            self.tree.heading(c, text=t); self.tree.column(c, width=w, anchor=anc)
        self.tree.tag_configure("on", foreground=GREEN)
        self.tree.tag_configure("off", foreground=FG_DIM)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<Button-1>", self._on_grid_click)
        self.tree.bind("<Double-1>", lambda e: self._edit())

        # ★操作行は grid 均等幅(uniform)で配置＝現在の画面幅のまま各ボタンが等分に縮んで全6個収まる
        #   （pack だと自然幅で6個目が溢れるため。統合ダッシュボードと同方式）。
        act = tk.Frame(wrap, bg=BG); act.pack(fill=tk.X, pady=(6, 0))
        items = [(" ✎ 登録の編集", self._edit), (" ⚙ パラメータ", self._params),
                 (" 📊 バックテスト", self._backtest), (" 📁 データ管理", self._open_data),
                 (" 📒 取引記録", self._open_records)]
        for i, (cap, cmd) in enumerate(items):
            self._cbtn(act, cap, cmd, PANEL_BG_HI, fg=FG, pad=7
                       ).grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 4))
            act.columnconfigure(i, weight=1, uniform="ops")
        # 📅 カレンダー：要更新（起動時判定）なら fg=赤＋⚠ で強調（hover は bg のみ変えるので維持される）
        ci = len(items)
        self.cal_btn = self._cbtn(act, " 📅 カレンダー", self._open_calendar, PANEL_BG_HI, fg=FG, pad=7)
        self.cal_btn.grid(row=0, column=ci, sticky="ew", padx=(4, 0))
        act.columnconfigure(ci, weight=1, uniform="ops")

    def _build_log(self):
        wrap = tk.Frame(self.root, bg=BG); wrap.pack(fill=tk.BOTH, expand=False, padx=16, pady=(0, 14))
        bar = tk.Frame(wrap, bg=PANEL_BG_HI, height=24); bar.pack(fill=tk.X); bar.pack_propagate(False)
        tk.Label(bar, text="  ログ", font=("Segoe UI Semibold", 9), bg=PANEL_BG_HI, fg=FG_DIM, anchor=tk.W).pack(side=tk.LEFT, fill=tk.Y)
        self.logbox = scrolledtext.ScrolledText(wrap, bg=LOG_BG, fg=FG, font=("Consolas", 9),
                                                insertbackground=FG, borderwidth=0, wrap=tk.WORD, height=6)
        self.logbox.pack(fill=tk.BOTH, expand=True)
        for tag, col in (("info", FG), ("dim", FG_DIM), ("send", GREEN), ("dry", YELLOW),
                         ("err", RED), ("trade", GREEN)):
            self.logbox.tag_config(tag, foreground=col)

    # ═════════════════════════ UI 部品 ═════════════════════════
    def _card(self, parent, title, color):
        outer = tk.Frame(parent, bg=PANEL_BG, bd=0, highlightthickness=0)
        head = tk.Frame(outer, bg=PANEL_BG_HI, height=28); head.pack(fill=tk.X); head.pack_propagate(False)
        tk.Frame(head, bg=color, width=3).pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(head, text=f"  {title}", font=("Segoe UI Semibold", 10), bg=PANEL_BG_HI, fg=FG, anchor=tk.W).pack(side=tk.LEFT, fill=tk.Y, expand=True)
        return outer

    def _cbtn(self, parent, text, cmd, color, fg="#1a1b26", pad=10):
        b = tk.Button(parent, text=text, command=cmd, font=("Segoe UI", 11), bg=color, fg=fg,
                      activebackground=color, activeforeground=fg, relief=tk.FLAT, padx=10, pady=pad,
                      cursor="hand2", anchor=tk.W, bd=0)
        b.bind("<Enter>", lambda e, b=b, c=color: b.config(bg=brighten(c, 0.15)))
        b.bind("<Leave>", lambda e, b=b, c=color: b.config(bg=c))
        b._base = color
        return b

    def _make_led(self, parent, cap):
        f = tk.Frame(parent, bg=BG); f.pack(side=tk.LEFT, padx=(0, 14))
        c = tk.Canvas(f, width=12, height=12, bg=BG, highlightthickness=0); c.pack(side=tk.LEFT, padx=(0, 5))
        c.create_oval(2, 2, 11, 11, fill=LED_OFF, outline="")
        tk.Label(f, text=cap, font=("Segoe UI", 9), bg=BG, fg=FG).pack(side=tk.LEFT)
        return c

    def _set_led(self, key, on, err=False):
        c = self.leds.get(key)
        if c:
            c.delete("all")
            c.create_oval(2, 2, 11, 11, fill=(LED_ERR if err else (LED_ON if on else LED_OFF)), outline="")

    def _btn_state(self, btn, enabled):
        btn.config(state=tk.NORMAL if enabled else tk.DISABLED)

    # ═════════════════════════ DataGrid ═════════════════════════
    def _refresh_rows(self):
        self.tree.delete(*self.tree.get_children())
        for r in self.ctrl._registered:
            on = r.get("enabled", False)
            self.tree.insert("", "end", iid=r["name"],
                             values=("☑" if on else "☐", r["name"], r.get("alert_name", r["name"]),
                                     r.get("interval", 15), "flat", "—"),
                             tags=("on" if on else "off",))

    def _selected(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _on_grid_click(self, event):
        col = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if row and col == "#1":                       # 「有効」チェックボックス列
            r = self.ctrl.get_entry(row)
            if r:
                self.ctrl.set_enabled(row, not r.get("enabled", False))
                self._refresh_rows(); self.tree.selection_set(row)
            return "break"

    # ═════════════════════════ 戦略操作 ═════════════════════════
    def _add(self):
        """① 配布パッケージを選択（ZIP 直接 or 解凍済フォルダ）→ ② 登録ダイアログ。"""
        win = tk.Toplevel(self.root); win.configure(bg=BG); win.title("戦略を追加")
        fit(win, 300, 150); win.resizable(False, False)
        win.transient(self.root); win.grab_set()
        tk.Label(win, text="配布された戦略パッケージを選択", bg=BG, fg=FG,
                 font=("Segoe UI", 10)).pack(pady=(16, 10))

        def from_zip():
            win.destroy()
            p = filedialog.askopenfilename(title="戦略 ZIP を選択",
                                           filetypes=[("戦略パッケージ", "*.zip"), ("すべて", "*.*")])
            if p:
                self._do_add(p)

        def from_folder():
            win.destroy()
            p = filedialog.askdirectory(title="解凍済み戦略フォルダを選択（strategy.py を含む）")
            if p:
                self._do_add(p)

        self._cbtn(win, "  📦  ZIP から（自動解凍）", from_zip, ACCENT).pack(fill=tk.X, padx=20, pady=4)
        self._cbtn(win, "  📁  解凍済フォルダから", from_folder, PANEL_BG_HI, fg=FG).pack(fill=tk.X, padx=20, pady=4)
        place_near(win, self.root)

    def _do_add(self, path):
        try:
            folder = self.ctrl.resolve_package(path)          # ZIP は自動解凍
        except Exception as e:
            messagebox.showerror("登録エラー", str(e)); return
        ok, why = validate_folder(folder)
        if not ok:
            messagebox.showerror("登録エラー", why); return
        RegisterDialog(self.root, self.ctrl, folder=folder, on_done=self._refresh_rows)

    def _edit(self):
        name = self._selected()
        if not name:
            messagebox.showinfo("編集", "編集する戦略を一覧で選択してください。"); return
        RegisterDialog(self.root, self.ctrl, edit_name=name, on_done=self._refresh_rows)

    def _remove(self):
        name = self._selected()
        if not name:
            messagebox.showinfo("削除", "一覧から削除する戦略を選択してください。"); return
        if not messagebox.askyesno("確認", f"「{name}」を登録解除しますか？（実体は消えません）"):
            return
        # ①A案：この戦略の取引記録があれば、まとめて削除するか確認（使わない戦略の記録は不要）。
        entry = self.ctrl.get_entry(name)
        alert = (entry or {}).get("alert_name", name)
        n_rec = sum(1 for r in self.ctrl.read_trade_log() if r.get("strategy") == alert)
        drop = False
        if n_rec:
            drop = messagebox.askyesno(
                "取引記録の削除",
                f"「{name}」の取引記録が {n_rec} 件あります。\nこの記録も一緒に削除しますか？\n"
                "（いいえ＝記録は残す。後で取引記録画面からも削除できます）")
        self.ctrl.unregister(name, drop_records=drop)
        self._refresh_rows()

    def _params(self):
        name = self._selected()
        if not name:
            messagebox.showinfo("パラメータ", "パラメータを編集する戦略を一覧で選択してください。")
            return
        folder = next((r["folder"] for r in self.ctrl._registered if r["name"] == name), None)
        if folder:
            # ★パラメータ調整ループ：保存しても閉じず、[保存してバックテスト]で当戦略のBTを開いたまま反復。
            #   controller/name を渡す＝パッケージ同梱 optimize.py があれば[🔄再最適化]を出す（汎用）。
            ParamForm(self.root, folder, on_saved=lambda n=name: self.ctrl.reload_one(n),  # ★差分（他戦略は無停止）
                      on_backtest=lambda n=name: self._run_bt(n),
                      controller=self.ctrl, name=name)
        else:
            messagebox.showwarning("パラメータ", f"「{name}」のフォルダが見つかりません。")

    def _backtest(self):
        name = self._selected()
        if not name:
            messagebox.showinfo("バックテスト", "戦略を選択してください。"); return
        self._run_bt(name)

    def _run_bt(self, name):
        """指定戦略のバックテスト。BT結果窓が既にあれば**閉じずに同じ窓で再計算・表示更新**する
        （パラメータ調整ループで閉じ開きの明滅をしない）。"""
        if not name:
            return
        win = getattr(self, "_bt_win", None)
        alive = bool(win is not None and win.winfo_exists())
        # 既に同じ戦略の窓が開いている → その場で再実行（表示だけ更新）
        if alive and getattr(win, "name", None) == name:
            win.rerun()
            return
        # 新規に開く（or 別戦略へ切替）。初回のみデータ量を確認して忠告（ブロックしない）。
        try:
            from app.backtest import data_import as di
            st = di.store_status(self.ctrl.parquet_path)
            if not st["bt_ok"]:
                messagebox.showwarning(
                    "データが少なめ",
                    f"バックテストの推奨は約{st['bt_months']}ヶ月です（少なくても実行はできます）。\n"
                    f"現在の蓄積: {st['n']:,} 本"
                    + (f"（{st['first']:%Y/%m/%d}〜{st['last']:%Y/%m/%d}・約{st.get('span_days', 0) // 30}ヶ月）"
                       if st['n'] else "")
                    + "\n\n[📁 データ管理]→[📥 ファイルを取り込み]で前年分も取り込めます。")
        except Exception:
            pass
        if alive:
            try:
                win.destroy()
            except Exception:
                pass
        self._bt_win = BacktestView(self.root, self.ctrl, name, parquet_path=self.ctrl.parquet_path,
                                    csv_dir=Path(self.ctrl.csv_dir))

    def _open_data(self):
        from .data_dialog import DataDialog
        DataDialog(self.root, self.ctrl.parquet_path)

    def _open_records(self):
        from .trade_record_view import TradeRecordView
        TradeRecordView(self.root, self.ctrl)

    def _open_calendar(self):
        from .calendar_dialog import CalendarDialog
        CalendarDialog(self.root, self.ctrl, on_done=self._check_calendar_status)

    def _check_calendar_status(self):
        """市場カレンダーの鮮度を判定し、ログ（色分け）＋📅ボタン（要更新で赤＋⚠）に反映。
        ★起動時に1回／カレンダー更新後に呼ぶ（定期チェックはしない）。"""
        try:
            from app.feed import calendar_fetch as cf
            st = cf.ui_status()
        except Exception:
            return
        self._log(st["message"], "err" if st["need_update"] else "dim")    # ログにも色分けで表示
        b = getattr(self, "cal_btn", None)
        if b is not None and b.winfo_exists():
            if st["need_update"]:
                b.config(text=" ⚠ 📅 カレンダー", fg=RED)
            else:
                b.config(text=" 📅 カレンダー", fg=FG)

    def _open_settings(self):
        SettingsDialog(self.root, self.ctrl, on_done=self._refresh_rows)

    def _warmup_df(self):
        """蓄積 parquet ＋ CSV から直近 W 本を読み warmup に使う（無ければ None）。"""
        try:
            import glob
            from app.backtest import data_provider
            pq = data_provider.load_parquet(self.ctrl.parquet_path)
            csvs = [data_provider.load_csv(p) for p in glob.glob(str(Path(self.ctrl.csv_dir) / "*.csv"))]
            df = data_provider.merge(pq, csvs)
            return df.tail(500) if df is not None and len(df) else None
        except Exception as e:
            self._log(f"warmup 読込エラー: {e}")
            return None

    # ═════════════════════════ 自動運用 / ブリッジ ═════════════════════════
    def _ensure_feed(self):
        """tick 入口（LiveFeed・TCP5000 待受）を1つ用意（再利用）。"""
        if getattr(self, "_feed", None) is None:
            from app.feed.live_feed import LiveFeed
            self._feed = LiveFeed()
        return self._feed

    def _auto_start(self):
        """★ウィンドウを先に表示し、warmup（重い）はバックグラウンドで実行＝起動を待たせない。
        warmup 完了まで running=False のため、その間に tick が来ても発注しない（安全）。
        feed(TCP5000)が使用中なら接続せず中止（本番tick経路を壊さない）。"""
        self._log("自動運用 起動中…（warmup を準備しています）")

        def run():
            try:
                ok = self.ctrl.start(warmup_df=self.warmup_provider(), feed=self._ensure_feed())
            except Exception as e:
                self._log(f"自動運用の起動でエラー: {e}")
                return
            if not ok:
                self._feed = None
                self._log("tick入口(5000)が使用中のため接続できませんでした（記録/注文は行われません）。")
            else:
                self._log("自動運用 準備完了：記録は全戦略・常時／注文は「有効」の戦略のみ。")
        threading.Thread(target=run, daemon=True).start()

    def _start_bridge(self):
        if not self.ctrl._kabu_ok and not messagebox.askyesno(
                "確認", "カブステーションが未確認です。ブリッジを起動しますか？"):
            return
        self.ctrl.start_bridge()

    def _stop_bridge(self):
        self.ctrl.stop_bridge()

    def _on_close(self):
        self._closed = True
        if getattr(self, "_feed_logger", None) is not None:
            self._feed_logger.remove_sink(self._log)            # feed スレッドからの呼出を断つ
        try:
            self.ctrl.stop()
            if getattr(self, "_feed", None) is not None:
                self._feed.stop()
        finally:
            self.root.destroy()

    # ═════════════════════════ ログ / 時計 / モニター ═════════════════════════
    def _log(self, msg, tag=None):
        if self._closed:
            return
        ts = datetime.now().strftime("%H:%M:%S")
        if tag is None:                              # 明示タグが無ければ内容から色を推定（従来動作）
            tag = "info"
            if "[売買" in msg: tag = "trade"        # 売買シグナル＝緑
            elif "エラー" in msg or "失敗" in msg or "見つかりません" in msg: tag = "err"
            elif "注文" in msg: tag = "send"
            elif "dry-run" in msg: tag = "dry"
        def append():
            self.logbox.insert(tk.END, f"[{ts}] ", "dim")
            self.logbox.insert(tk.END, msg + "\n", tag)
            self.logbox.see(tk.END)
        self.root.after(0, append)

    def _tick_clock(self):
        if self._closed:
            return
        self.lbl_clock.config(text=datetime.now().strftime("%H:%M:%S"))
        self.root.after(1000, self._tick_clock)

    def _start_poller(self):
        def loop():
            while not self._closed:
                try:
                    self.ctrl.poll_external()
                except Exception:
                    pass
                time.sleep(3.0)
        threading.Thread(target=loop, daemon=True).start()

    def _tick_status(self):
        if self._closed:
            return
        st = self.ctrl.status()
        # ★記録停止などの重大状態は赤バナーで常時可視化（静かな記録ゼロを見落とさない）。
        err = st.get("start_error")
        if err:
            self._banner.config(bg=RED); self._banner_lbl.config(bg=RED, text="⚠ 記録停止中: " + err)
        else:
            self._banner.config(bg=BG); self._banner_lbl.config(bg=BG, text="")
        self._set_led("kabu", st["kabu"]); self._set_led("bridge", st["bridge"])
        # オートトレードLED＝信号チャンネル稼働＝「有効な戦略が1つ以上ある」ときに点灯（注文経路が動いている）。
        any_enabled = any(s.get("enabled") for s in st["strategies"])
        self._set_led("auto", any_enabled)
        self._set_led("feed", st.get("feed", False))
        # ブリッジ: 起動は未稼働時のみ（手動起動含め稼働中は二重起動防止）／停止はダッシュボード起動分のみ
        self._btn_state(self.bridge_start_btn, not st["bridge"])
        self._btn_state(self.bridge_stop_btn, st.get("bridge_self", False))
        # DataGrid: 有効/建玉/シグナルを更新
        emap = {r["name"]: r for r in self.ctrl._registered}
        for s in st["strategies"]:
            n = s["name"]
            if self.tree.exists(n):
                e = emap.get(n, {})
                sig = s.get("last_signal")
                sigtxt = f'{sig["order_action"]} x{sig["order_contracts"]}' if sig else "—"
                self.tree.item(n, values=("☑" if s["enabled"] else "☐", n, e.get("alert_name", n),
                                          e.get("interval", 15), f'{s["position"]} {s["size"]}', sigtxt),
                               tags=("on" if s["enabled"] else "off",))
        self.root.after(1000, self._tick_status)


# ═════════════════════════ 二重起動防止（シングルトン）═════════════════════════
# ★ガードはヘッドレス run_live と共有（同じ Mutex 名）。dashboard と run_live を相互排他にして
#   tick ポート :5000 の競合（→黙って記録ゼロ）を根絶する（2026-06-23）。
from app.instance_lock import acquire_single_instance as _acquire_single_instance  # noqa: E402


def _focus_existing(title: str = "N225AutoTrader-Local") -> None:
    """既存ダッシュボードのウィンドウを前面化する（タイトル一致）。"""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def _cb(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd):
                ln = user32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(ln + 1)
                user32.GetWindowTextW(hwnd, buf, ln + 1)
                if title in buf.value:
                    found.append(hwnd)
                    return False
            return True

        user32.EnumWindows(_cb, 0)
        if found:
            user32.ShowWindow(found[0], 9)         # SW_RESTORE
            user32.SetForegroundWindow(found[0])
    except Exception:
        pass


def main():
    # ★二重起動防止：既に起動中なら新規ウィンドウを開かず、既存を前面化して終了。
    _mtx = _acquire_single_instance()
    if _mtx is None:
        _focus_existing()
        try:
            r = tk.Tk(); r.withdraw()                 # tk/messagebox はモジュール先頭で import 済
            messagebox.showinfo("N225AutoTrader-Local",
                                "ダッシュボードは既に起動しています。（二重起動はできません）")
            r.destroy()
        except Exception:
            pass
        return

    parquet = ROOT / "data" / "ohlc_live.parquet"
    csv_dir = ROOT / "data" / "csv_import"; csv_dir.mkdir(parents=True, exist_ok=True)
    # ★起動時の自動整形：蓄積ストアが6ヶ月超なら自動で切り詰める（手動トリム不要）。
    try:
        from app.backtest import data_import as _di
        _r = _di.trim_store(str(parquet))
        if _r.get("changed"):
            print(f"[起動整形] 蓄積を6ヶ月にトリム: {_r['before']:,}→{_r['after']:,} 本")
    except Exception as _e:
        print(f"[起動整形] スキップ: {_e}")
    ctrl = LocalEngineController(strategies_dir=ROOT / "strategies",
                                 state_dir=ROOT / "app" / "state")
    # ★②C案：起動時、6ヶ月より古い取引記録を data/history の四半期CSVへ自動退避（直近6ヶ月は残す）。
    try:
        _n, _w = ctrl.archive_old_records(months=6)
        if _n:
            print(f"[起動整形] 取引記録 {_n} 件を history へアーカイブ")
    except Exception as _e:
        print(f"[起動整形] 取引記録アーカイブ スキップ: {_e}")
    # ★古いアーカイブCSVの自動削除：直近8四半期（約2年分）だけ残し、それ以前は完全削除（data/history の無限増加を防ぐ）。
    try:
        _d = ctrl.prune_old_archives(keep_quarters=8)
        if _d:
            print(f"[起動整形] 古い取引アーカイブ {len(_d)} 四半期分を削除")
    except Exception as _e:
        print(f"[起動整形] アーカイブ削除 スキップ: {_e}")
    root = tk.Tk()
    root.withdraw()                              # ★構築完了まで隠す（白窓→順次描画のちらつき防止）
    Dashboard(root, ctrl, parquet_path=str(parquet), csv_dir=csv_dir)
    try:
        root.update_idletasks()                 # レイアウトを確定（880×520）させてから
        root.deiconify()                        # 完成状態のメイン画面を一度に表示
    except Exception:
        root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()
