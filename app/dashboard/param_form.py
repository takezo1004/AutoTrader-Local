# -*- coding: utf-8 -*-
"""パラメータ編集フォーム（外部仕様 F2 / 詳細仕様 §D.2）— config.json を GUI で編集。

仕様書どおり全パラメータを表示：
  - スカラ数値：Entry／列挙：ドロップダウン／真偽：Checkbutton
  - phase 別 6マス（allow_long/allow_short=真偽×6・upper_band/lower_band=数値×6）：6×4 の表
  - `_grp_*` はグループ見出し、`_comment` は出さない。リスト値（priority 等）は読み取り専用表示（保存時保持）。

★汎用化（2026-06-29）:
  - フォルダに `_subs/` があれば、トップ config に加えて各 `_subs/<名>/config.json` を
    タブで表示・編集する（合成戦略のサブ別パラメータ）。エンジンは戦略名を一切持たない＝汎用。
  - パッケージ同梱 optimize.py があれば [🔄 再最適化] ボタンを出す（app.engine.reopt 経由・承認制）。
  これにより、新しい合成戦略を作っても **このフォーム/エンジンの改修は不要**（戦略が中身を持参）。

パラメータ調整ループ対応：保存しても閉じない＋[保存してバックテスト]で BT を開いたまま反復。
"""
from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

from .theme import BG, PANEL_BG, PANEL_BG_HI, ACCENT, FG, FG_DIM, DARK, place_near, fit

_PHASES = ["peak", "down_start", "downtrend", "bottom", "up_start", "uptrend"]
_PHASE_KEYS = ["allow_long", "allow_short", "upper_band", "lower_band"]
_PHASE_GRP = {"_grp_allow_long", "_grp_allow_short", "_grp_upperBand", "_grp_lowerBand"}
_ENUMS = {"strategy_mode": ["T", "R", "ALL"], "tp_mode": ["C", "E"]}          # 固定列挙（readonly）
_ENUMS_EDIT = {"hp_source": ["hl2", "close", "hlc3", "ohlc4"]}                 # 候補つき自由入力
_PHASE_SHORT = {"allow_long": "Long可", "allow_short": "Short可",
                "upper_band": "上限(Short)", "lower_band": "下限(Long)"}


class ParamForm(tk.Toplevel):
    def __init__(self, master, folder, on_saved=None, on_backtest=None, controller=None, name=None):
        super().__init__(master)
        self.folder = Path(folder)
        self.cfg_path = self.folder / "config.json"
        self.on_saved = on_saved
        self.on_backtest = on_backtest         # 呼ぶと当戦略の BT を開く（パラメータ調整ループ）
        self.controller = controller           # 再最適化の ctx 構築に使う（無ければボタン非表示）
        self.strategy_name = name
        self.title(f"パラメータ編集 — {self.folder.name}")
        self.configure(bg=BG)
        self.panels: list[dict] = []           # [{"path":Path,"cfg":dict,"vars":dict}]
        self.resizable(True, True)
        self._build()
        fit(self, 620, 660)                    # 画面に合わせ：収まらなければ縦に自動拡張（ボタンが必ず見える）
        place_near(self, master)

    # ── 構築 ──
    def _build(self):
        # ボタンバーを先に side=bottom で確保（必ず見える）。
        btns = ttk.Frame(self)
        btns.pack(side="bottom", fill="x", pady=6)
        self.lbl_status = ttk.Label(btns, text="", foreground=ACCENT)
        self.lbl_status.pack(side="left", padx=10)
        ttk.Button(btns, text="閉じる", command=self.destroy).pack(side="right", padx=(0, 6))
        ttk.Button(btns, text="保存", command=lambda: self._save(False)).pack(side="right", padx=6)
        if self.on_backtest is not None:
            ttk.Button(btns, text="保存してバックテスト",
                       command=lambda: self._save(True)).pack(side="right", padx=6)

        # 本体：_subs があればタブ（共通＋サブ）、無ければ単一画面（後方互換）
        #   ★[🔄 自動調整]は合成戦略のタブ列右端に置く（_build_tabbar 内・他戦略はやらない）。
        sub_dirs = []
        subs = self.folder / "_subs"
        if subs.is_dir():
            sub_dirs = sorted(d for d in subs.iterdir() if (d / "config.json").exists())
        if sub_dirs:
            entries = [("共通", self.cfg_path, "共通設定（priority / qty）")]
            for d in sub_dirs:
                entries.append((self._short(d.name), d / "config.json", d.name))
            self._build_tabbar(entries)
        else:
            host = self._scroll_host(self)
            self._render_into(host, self.cfg_path)

    @staticmethod
    def _short(name: str) -> str:
        """タブが画面幅に収まるよう短縮（MESA_Stochastic→MESA・Momentum_Combo→Momentum）。"""
        return name.split("_")[0] if "_" in name else name

    def _build_tabbar(self, entries):
        """カスタム タブバー（Tokyo Night・フラットpill・等幅・ホバー）＋ スタック型コンテンツ。

        ttk.Notebook の既定見た目（野暮ったい）を避け、アプリのフラットボタン意匠に統一。
        tk.Button(width=文字数) で全タブを等幅（ピクセル統一）にし、選択＝アクセント・ホバーで明るく。
        """
        bar = tk.Frame(self, bg=BG)
        bar.pack(side="top", fill="x", padx=8, pady=(8, 0))
        content = tk.Frame(self, bg=BG)
        content.pack(side="top", fill="both", expand=True, padx=8, pady=(6, 0))
        self._tab_btns = []
        self._tab_frames = []
        self._active_tab = 0
        wch = max(len(lbl) for lbl, _, _ in entries) + 2           # 全タブ等幅
        for i, (lbl, path, title) in enumerate(entries):
            frame = tk.Frame(content, bg=BG)
            frame.place(relx=0, rely=0, relwidth=1, relheight=1)    # スタックして tkraise で切替
            host = self._scroll_host(frame)
            self._render_into(host, path, title=title)
            b = tk.Button(bar, text=lbl, width=wch, command=lambda i=i: self._select_tab(i),
                          font=("Segoe UI Semibold", 9), relief="flat", bd=0, cursor="hand2",
                          padx=6, pady=7, bg=PANEL_BG, fg=FG_DIM,
                          activebackground=ACCENT, activeforeground=DARK)
            b.pack(side="left", padx=(0, 4))
            b.bind("<Enter>", lambda e, i=i: self._tab_hover(i, True))
            b.bind("<Leave>", lambda e, i=i: self._tab_hover(i, False))
            self._tab_btns.append(b)
            self._tab_frames.append(frame)
        # タブ列の右端に [🔄 自動調整（再最適化）]（合成戦略のみ・アクセント色で目立たせる）。
        if self.controller is not None:
            tk.Button(bar, text="🔄 自動調整（再最適化）", command=self._reoptimize,
                      font=("Segoe UI Semibold", 9), relief="flat", bd=0, cursor="hand2",
                      padx=12, pady=7, bg=ACCENT, fg=DARK,
                      activebackground=ACCENT, activeforeground=DARK).pack(side="right")
        self._select_tab(0)

    def _tab_hover(self, i, on):
        if i == self._active_tab:
            return
        self._tab_btns[i].config(bg=(PANEL_BG_HI if on else PANEL_BG), fg=(FG if on else FG_DIM))

    def _select_tab(self, i):
        self._active_tab = i
        self._tab_frames[i].tkraise()
        for j, b in enumerate(self._tab_btns):
            b.config(bg=(ACCENT if j == i else PANEL_BG), fg=(DARK if j == i else FG_DIM))

    def _scroll_host(self, parent):
        """スクロール可能な内側 frame を返す。

        ★2026-08-06 修正（説明文が長いと値が画面外に出る不具合）:
          `_grp_*` の説明文や list/dict の要約は1行が非常に長い（config の解説文＝数百文字）。
          折り返し指定が無いと grid の幅がその1行ぶんに広がり、**値の入力欄が窓の右外へ押し出されて
          見えなくなる**（窓を最大化しないと編集できない）。横スクロールバーも無いため事実上不可視。
          対策＝①内側 frame を canvas 幅にぴったり合わせる ②長文ラベルの wraplength を canvas 幅に
          追従させる（`frame._wrap_labels` に登録したものを resize のたびに更新）。
          これで既定サイズ（620px）のままでも名前と値が必ず1画面に収まる。
        """
        canvas = tk.Canvas(parent, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        frame = ttk.Frame(canvas)
        frame._wrap_labels = []                      # 幅に追従して折り返すラベル（_render_into が登録）
        frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        win = canvas.create_window((0, 0), window=frame, anchor="nw")

        def _on_resize(e):
            canvas.itemconfigure(win, width=e.width)     # 内側 frame を canvas 幅に合わせる
            for lb, margin in frame._wrap_labels:        # margin＝左に確保する幅（名前列など）
                try:
                    lb.configure(wraplength=max(160, e.width - margin))
                except tk.TclError:                      # 破棄済みラベルは無視
                    pass

        canvas.bind("<Configure>", _on_resize)
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(8, 0))
        sb.pack(side="right", fill="y")
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        frame.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        return frame

    def _render_into(self, frame, cfg_path, title=None):
        """1つの config.json を frame に描画し、panels に登録する。"""
        cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
        vars_: dict = {}
        r = 0
        if title:
            ttk.Label(frame, text=title, font=("Segoe UI Semibold", 11),
                      foreground=ACCENT).grid(row=r, column=0, columnspan=2,
                                              sticky="w", padx=4, pady=(6, 6)); r += 1
        for key, val in cfg.items():
            if key == "_comment" or key in _PHASE_GRP or key in _PHASE_KEYS:
                continue
            if key.startswith("_grp_"):
                # ★長い説明文は窓幅で折り返す（登録しておくと _scroll_host が幅に追従させる）
                lb = ttk.Label(frame, text=str(val), font=("", 9, "bold"),
                               foreground=ACCENT, justify="left", wraplength=560)
                lb.grid(row=r, column=0, columnspan=2, sticky="w", padx=4, pady=(8, 2))
                self._register_wrap(frame, lb)
                r += 1
                continue
            r = self._field(frame, r, key, val, vars_)
        phase_params = [k for k in _PHASE_KEYS if isinstance(cfg.get(k), dict)]
        if phase_params:
            ttk.Label(frame, text="Phase 別設定（採用フラグ・エントリー閾値・6 phase）",
                      font=("", 9, "bold"), foreground=ACCENT).grid(
                row=r, column=0, columnspan=2, sticky="w", pady=(12, 2)); r += 1
            self._phase_table(frame, r, phase_params, cfg, vars_); r += 1
        self.panels.append({"path": Path(cfg_path), "cfg": cfg, "vars": vars_})

    @staticmethod
    def _register_wrap(frame, label, margin: int = 44) -> None:
        """窓幅に追従して折り返すラベルとして登録する（_scroll_host の resize が更新する）。

        margin＝そのラベルの左に確保しておく幅。見出し（2列ぶち抜き）は余白だけ、
        値の要約（右列）は名前列のぶんを空けるので大きめにする。
        """
        try:
            frame._wrap_labels.append((label, margin))
        except AttributeError:                       # 単一画面など未対応の親でも壊さない
            pass

    def _field(self, frame, r, key, val, vars_):
        ttk.Label(frame, text=key).grid(row=r, column=0, sticky="w", padx=4, pady=1)
        if isinstance(val, bool):
            v = tk.BooleanVar(value=val)
            ttk.Checkbutton(frame, variable=v).grid(row=r, column=1, sticky="w")
            vars_[key] = ("bool", v)
        elif key in _ENUMS or key in _ENUMS_EDIT:
            v = tk.StringVar(value=str(val))
            opts = _ENUMS.get(key) or _ENUMS_EDIT.get(key)
            state = "readonly" if key in _ENUMS else "normal"
            ttk.Combobox(frame, textvariable=v, values=opts, state=state, width=12).grid(
                row=r, column=1, sticky="w")
            vars_[key] = ("str", v)
        elif isinstance(val, (int, float)):
            v = tk.StringVar(value=str(val))
            ttk.Entry(frame, textvariable=v, width=12).grid(row=r, column=1, sticky="w")
            vars_[key] = ("num", v)
        elif isinstance(val, (list, dict)):
            # リスト/辞書（priority・session 等）は単純フォームで編集できない複合値。読み取り専用で
            # 表示し、保存時は触らず原値を保持（vars_ に入れない）。
            #   ※ dict を str() で Entry 化すると保存時に repr 文字列（"{'enabled': True}"）として
            #     書き戻り、ロード時 .get() で 'str' object has no attribute 'get' になる（2026-06-30 修正）。
            summary = json.dumps(val, ensure_ascii=False)
            # ★entries/exits のような大きな dict は1行が数百文字になる。折り返さないと
            #   grid が横に伸び、他の行の入力欄まで画面外へ押し出される（2026-08-06 修正）。
            lb = ttk.Label(frame, text=summary, foreground=FG_DIM,
                           justify="left", wraplength=420)
            lb.grid(row=r, column=1, sticky="w", padx=4)
            self._register_wrap(frame, lb, margin=200)      # 左に名前列ぶんを空ける
        else:
            v = tk.StringVar(value=str(val))
            ttk.Entry(frame, textvariable=v, width=12).grid(row=r, column=1, sticky="w")
            vars_[key] = ("str", v)
        return r + 1

    def _phase_table(self, frame, r, phase_params, cfg, vars_):
        """行=6 phase、列=allow_long/allow_short/upper_band/lower_band の表。"""
        tbl = ttk.Frame(frame)
        tbl.grid(row=r, column=0, columnspan=2, sticky="w", padx=4)
        ttk.Label(tbl, text="phase", font=("", 8, "bold")).grid(row=0, column=0, padx=4, sticky="w")
        for j, pk in enumerate(phase_params):
            ttk.Label(tbl, text=_PHASE_SHORT.get(pk, pk), font=("", 8, "bold")).grid(
                row=0, column=j + 1, padx=6)
        for pk in phase_params:
            vars_[pk] = ("dict", {})
        for i, ph in enumerate(_PHASES):
            ttk.Label(tbl, text=ph, font=("", 8)).grid(row=i + 1, column=0, sticky="w", padx=4, pady=1)
            for j, pk in enumerate(phase_params):
                cell = cfg[pk].get(ph)
                if isinstance(cell, bool):
                    vv = tk.BooleanVar(value=cell)
                    ttk.Checkbutton(tbl, variable=vv).grid(row=i + 1, column=j + 1, padx=6)
                else:
                    vv = tk.StringVar(value=str(cell))
                    ttk.Entry(tbl, textvariable=vv, width=7).grid(row=i + 1, column=j + 1, padx=6)
                vars_[pk][1][ph] = vv

    # ── 保存 ──
    def _status(self, msg):
        try:
            self.lbl_status.config(text=msg)
            self.after(2500, lambda: self.lbl_status.config(text=""))
        except Exception:
            pass

    def _save(self, then_backtest=False):
        try:
            for panel in self.panels:
                cfg, vars_ = panel["cfg"], panel["vars"]
                for key, (kind, var) in vars_.items():
                    if kind == "bool":
                        cfg[key] = bool(var.get())
                    elif kind == "num":
                        cfg[key] = self._num(var.get())
                    elif kind == "dict":
                        for ph, vv in var.items():
                            cur = cfg[key][ph]
                            cfg[key][ph] = bool(vv.get()) if isinstance(cur, bool) else self._num(vv.get())
                    else:
                        cfg[key] = var.get()
                panel["path"].write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            if self.on_saved:
                self.on_saved()
            self._status("保存しました ✓")               # 閉じない（調整ループのため）
            if then_backtest and self.on_backtest is not None:
                self.on_backtest()
        except Exception as e:
            messagebox.showerror("保存エラー", str(e), parent=self)

    # ── 再最適化 ──
    def _reoptimize(self):
        try:
            from app.engine import reopt
            if not reopt.has_optimizer(self.folder):
                messagebox.showinfo(
                    "再最適化",
                    "この戦略は自動調整に未対応です（パッケージに optimize.py がありません）。\n"
                    f"フォルダ: {self.folder}", parent=self)
                return
            from .reopt_dialog import ReoptDialog
            ctx = reopt.build_ctx(self.controller, self.folder)
            ReoptDialog(self, self.folder, ctx, on_applied=self._after_reopt)
        except Exception as e:
            messagebox.showerror("再最適化", str(e), parent=self)

    def _after_reopt(self):
        """適用後：各 config を読み直してフォームの値を更新 → BT を再実行。"""
        for panel in self.panels:
            try:
                cfg = json.loads(panel["path"].read_text(encoding="utf-8"))
            except Exception:
                continue
            panel["cfg"] = cfg
            for key, (kind, var) in panel["vars"].items():
                if kind == "dict":
                    for ph, vv in var.items():
                        if ph in cfg.get(key, {}):
                            cell = cfg[key][ph]
                            vv.set(cell if isinstance(cell, bool) else str(cell))
                elif key in cfg:
                    var.set(bool(cfg[key]) if kind == "bool" else str(cfg[key]))
        if self.on_saved:
            self.on_saved()
        self._status("再最適化を適用しました ✓")
        if self.on_backtest is not None:
            self.on_backtest()

    @staticmethod
    def _num(s):
        s = str(s).strip()
        return float(s) if ("." in s or "e" in s.lower()) else int(s)
