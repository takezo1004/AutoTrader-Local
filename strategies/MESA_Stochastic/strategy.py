# -*- coding: utf-8 -*-
"""MESA_Stochastic — 戦略（最小標準・「1バーで動く」＝Pine と同じ作り）。

Pine `MESA Stochastic V7_8 FibSync 3Split`（MESA_Stochastic/pine/）の忠実移植。**主力戦略**。
基軸＝MESA Stochastic（hl2→HP→SuperSmoother→ストキャス・前段変換なし＝最小）。
DT/TSI/CMF/Momentum はこの MESA ハーネスの基軸オシレーターを差し替えた姉妹戦略。本戦略がその原型。
  - 確定足ごとに on_bar(bar)/step(A,i) が呼ばれ、注文リストを返す（確定足の終値で判断）。
  - 指標は on_bar 内で毎バー更新（直近 window 本のバッファを保持し _lib 純関数で再計算）。
  - パラメータは config.json（ローカルエンジンで調整）。

★約定モデル＝TV（Pine）完全忠実（2026-06-15 v3.5 確定。旧「同バー終値約定」は撤回）:
  - エントリー（strategy.entry）/ 標準決済・ドテン（strategy.close）＝**成行・次バー始値**約定。
  - TP1/TP2（strategy.exit limit）＝**指値・イントラバー**約定（毎バー再配置・各 ID 一度きり）。
  - 約定は共有 `_engine` の PineBroker が行う＝戦略は注文を返すだけ。
  - 戦略は Pine 同様に**エンジンが確定したポジション**を読む:
    `self.position_size`（符号付き枚数）/ `self.position_avg_price`（実約定値）/ `self.entry_bar`。
  - TP ターゲット＝`position_avg_price ± tp_R × R`、R＝|position_avg_price − 約定バーの zz60 ピボット|。

決定ロジックは Pine 本体と 1:1:
  4state エントリー（順張り/逆張り×over/under×採用フラグ×FibSync×ドテン）＋
  3Split エグジット（TP1=+1R・TP2=+2R 指値／残＝反対サイン strategy.close／SQ は共有エンジン）。

★自己完結: _lib の部品をこのフォルダにコピー同梱済（indicators/oscillator/signup/zigzag/
  phases/fibsync.py）＝跨ぎ import ゼロ・単体で動く。正本は strategies/_lib/（更新時は refresh）。
  確定版 <戦略名>/ も同じ自己完結形（work で改善 → 確定版へ refresh）。

================================================================================
★★ Pine 逆移植ガイド（Python → TradingView Pine 復元用・完成検証のため）★★
--------------------------------------------------------------------------------
この Python は「売買ロジックの本体」のみを持つ。TradingView に載せて目視チェックする
には、元 `work/strategy.pine` と同じになるよう下記の Pine 専用要素を復元する必要がある。

[A] strategy() 宣言（Pine L97-111・必ずこの値）:
    strategy('MESA Stochastic V7_8 FibSync 3Split', shorttitle="MESA783", overlay=true, precision=2,
      margin_long=0, margin_short=0,                 // BT 必須（無いと取引が出ない）
      default_qty_type=strategy.fixed, default_qty_value=3,   // = qty_per_entry
      initial_capital=10000000, pyramiding=1,
      process_orders_on_close=false,                 // ★次バー始値約定（本 Python・PineBroker と一致）
      calc_on_every_tick=false, max_lines_count=500, max_labels_count=500, max_boxes_count=500)

[B] 限月制御 SQ（Python では戦略に入れない＝共有エンジン側。Pine では復元する）:
    import jubilantEagle98317/KengetsuLib/1 as KGL
    is_force_close_time = KGL.is_force_close_time(time, i_force_close_offset_min)  // 既定30分前
    if is_force_close_time
        strategy.close_all(comment='SQ前強制クローズ')

[C] プルバック順張りサブ（config use_pullback 既定 false＝本 Python は未実装）:
    Pine L212-221 の pb_* 入力、L809-814 の pb_signal、L900-903 の PB エントリー、
    L992-1025 の PB 3分割ATR決済。既定 OFF なので売買に影響なし。

[D] 表示系（売買に無関係・TV 目視チェック用に復元する）:
    plot/label/dashboard/bgcolor/ZZ60 線（Pine L956- 以降）。本 Python では省略。

[E] 表示用だが判定に無関係な計算（Pine にあるが Python では省略可）:
    ZZ15（dir_15m 等・判定に未使用）、kengai_msg、mesa_cross。

[F] オシレーターの基軸（MESA・本 Python の前段＝Pine と同一式・最小）:
    hl2 → HP(48) → SuperSmoother(10) → Stoch(20) →
    SuperSmoother → 0.33*2*(x-0.5)+0.67*前値 → ±0.999 = MESAStochastic。
    （DT/TSI/CMF/Momentum は ① の入力を差し替えた姉妹。本戦略は hl2 直接＝原型。fib_depth=0.5）
================================================================================
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# 自己完結: 同梱部品を「戦略フォルダ単位の一意キー」で読み込む（多戦略を1プロセスで同時ロードしても衝突しない）。
import importlib.util as _ilu
_HERE = Path(__file__).resolve().parent
def _vlib(_m):
    _k = f"_v.{_HERE.parent.name}.{_HERE.name}.{_m}"
    _mod = sys.modules.get(_k)
    if _mod is None:
        _sp = _ilu.spec_from_file_location(_k, str(_HERE / (_m + ".py")))
        _mod = _ilu.module_from_spec(_sp); sys.modules[_k] = _mod; _sp.loader.exec_module(_mod)
    return _mod
_i = _vlib("indicators"); hl2, highpass48, atr14 = _i.hl2, _i.highpass48, _i.atr14
_o = _vlib("oscillator"); ss_stoch_inertia = _o.ss_stoch_inertia
_s = _vlib("signup"); self_crossover, self_crossunder = _s.self_crossover, _s.self_crossunder
_z = _vlib("zigzag"); compute_60m_zigzag, extract_pivots_from_zigzag = _z.compute_60m_zigzag, _z.extract_pivots_from_zigzag
_p = _vlib("phases"); compute_phase, compute_phase_thresholds = _p.compute_phase, _p.compute_phase_thresholds
_f = _vlib("fibsync"); compute_fib_pullback_v2, compute_reversal_flags, compute_bottomed_held = _f.compute_fib_pullback_v2, _f.compute_reversal_flags, _f.compute_bottomed_held

try:
    import session_lib  # 共有セッション制御（LocalEngine提供・ZIP非同梱）
except Exception:
    session_lib = None

MANIFEST = {"name": "MESA_Stochastic", "interval": 15, "warmup_bars": 300, "version": 2}


def _load_config() -> dict:
    with open(Path(__file__).resolve().parent / "config.json", encoding="utf-8") as f:
        return json.load(f)


class MESA_Stochastic:
    def __init__(self, cfg: dict | None = None):
        self.session_enabled = True            # ★単独稼働時 ON。ポートフォリオ内包時は親が False に。
        self.interval = MANIFEST.get("interval", 15)
        self._bt_ts = None                     # precompute で df.index 保持（セッション判定の ts）
        self.cfg = cfg or _load_config()
        self.W = int(self.cfg.get("window", 500))
        self.qty_per_entry = int(self.cfg.get("qty_per_entry", 3))
        self.reset()

    def reset(self) -> None:
        c = self.cfg
        # phase 別 over/under 閾値（Pine: upperBand_<phase> / lowerBand_<phase>・6局面ずつ）
        self.upper = dict(c["upper_band"])
        self.lower = dict(c["lower_band"])
        # バッファ（直近 W 本の確定足）
        self._ts: list = []
        self._o: list = []
        self._h: list = []
        self._l: list = []
        self._c: list = []
        # 決定状態（Pine var）
        self.signup = 0
        self.zz_p1 = np.nan          # 約定バーの zz60 反対側ピボット（R 計算用）
        self.tp1 = np.nan            # TP1 指値価格
        self.tp2 = np.nan            # TP2 指値価格
        self._prev_size = 0          # 前バーの position_size（just_entered 検出用）
        # エンジンが decide 前に注入する Pine globals 相当（既定値）
        self.position_size = 0       # 符号付き枚数（+long / -short / 0）
        self.position_avg_price = 0.0
        self.entry_bar = -1
        self.bars_since_entry = -1

    # ---- TP ターゲット（約定値 position_avg_price と zz60 ピボット / ATR から）----
    # [PINE] Pine L886-897：just_entered で R=|position_avg_price - zz60ピボット| から算出。
    def _tp_targets(self, direction: int, atr_entry: float) -> tuple[float, float]:
        c = self.cfg
        avg = self.position_avg_price
        d1 = d2 = np.nan
        if c["tp_mode"] == "C":
            if not np.isnan(self.zz_p1):
                R = abs(avg - self.zz_p1)
                if R > 0:
                    d1, d2 = c["tp1_R"] * R, c["tp2_R"] * R
        elif c["tp_mode"] == "E":
            if not np.isnan(atr_entry) and atr_entry > 0:
                d1, d2 = c["e_tp1_atr"] * atr_entry, c["e_tp2_atr"] * atr_entry
        if np.isnan(d1):
            return np.nan, np.nan
        if direction > 0:
            return avg + d1, avg + d2
        return avg - d1, avg - d2

    # ---- 指標計算（_lib 純関数・バッファ/全系列 共通）----
    # [PINE] Pine L298-642（MESA計算・ZZ60・phase・FibSync）に対応。
    def _compute_indicators(self, H, L, C, idx) -> dict:
        c = self.cfg
        # [PINE] MESA 基軸（最小・前段変換なし）: hl2 → HP(48) → SS-stoch-慣性 = MESAStochastic
        ms = ss_stoch_inertia(highpass48(hl2(H, L)), c["stoch_length"])
        cu = self_crossover(ms); cd = self_crossunder(ms)  # [PINE] changeUp/changeDown
        z = compute_60m_zigzag(H, L, idx, c["zz60_length"], c["zz60_threshold"], c["zz60_threshold_max"])
        dir60 = z["dir_60m"]; dch = z["dirchanged_60m"]
        zhigh = z["zhigh_60m"]; zlow = z["zlow_60m"]
        piv = extract_pivots_from_zigzag(dch, zhigh, zlow, dir60)
        p1 = piv["p1_price"]
        phase = compute_phase(dir60, c["n_transition_bars"])
        ub, lb = compute_phase_thresholds(phase, self.upper, self.lower)
        fib = compute_fib_pullback_v2(dir60, dch, p1, H, L, C)
        depth = c["fib_depth"]; K = c["fib_K"]
        atr = atr14(H, L, C, 14)                          # TP モード E 用（C は zz60 ピボット）
        # 上昇側は常に slope 反転（Pine に up 用 input は無い）
        up_bot_K, up_top_K = compute_reversal_flags(fib["up_fib"], fib["up_fib_slope"], depth, K, mode="slope")
        if c.get("dn_invalidate_newlow", True):           # Pine i_dn_invalidate_newlow（V7_8・既定true）
            _, dn_top_K = compute_reversal_flags(fib["down_fib"], fib["down_fib_slope"], depth, K, mode="slope")
            dn_bot_K = compute_bottomed_held(fib["down_fib"], fib["down_fib_slope"], fib["cur_low"], depth, K)
        else:                                             # V7_7 従来（新安値で無効化しない）
            dn_bot_K, dn_top_K = compute_reversal_flags(fib["down_fib"], fib["down_fib_slope"], depth, K, mode="slope")
        return {"ms": ms, "cu": cu, "cd": cd, "dir60": dir60, "zhigh": zhigh, "zlow": zlow,
                "phase": phase, "ub": ub, "lb": lb, "atr": atr,
                "up_bot_K": up_bot_K, "up_top_K": up_top_K,
                "dn_bot_K": dn_bot_K, "dn_top_K": dn_top_K, "H": H, "L": L, "C": C}

    # ---- BT 高速パス: 全系列を1回だけ計算（on_bar と同じ _lib 関数・結果同一）----
    def _session_gate(self, orders, ts):
        # 共有 session_lib で per-bar セッション制御（締切窓の新規/決済抑止・週末/SQ強制flat）。
        if session_lib is None or not getattr(self, "session_enabled", True) or ts is None:
            return orders
        fl = session_lib.flags(ts, self.interval)
        return session_lib.gate(orders, fl, self.position_size)

    def precompute(self, df) -> dict:
        self._bt_ts = pd.DatetimeIndex(df.index)
        H = df["high"].to_numpy(float); L = df["low"].to_numpy(float)
        C = df["close"].to_numpy(float); idx = pd.DatetimeIndex(df.index)
        return self._compute_indicators(H, L, C, idx)

    # ---- BT 高速パスの1ステップ（共有 PineBroker が i=0..n-1 で呼ぶ）----
    def step(self, A, i) -> list[dict]:
        if i < 2:        # 極小本数スキップ（on_bar の len<3 と同条件・golden と整合）
            return []
        orders = self._decide_at(A, i) or []
        return self._session_gate(orders, self._bt_ts[i] if (self._bt_ts is not None and i < len(self._bt_ts)) else None)

    # ---- 決定（バー i のスカラを読む。on_bar/step 共通＝二重化防止）----
    # 構造は Pine 本体と 1:1（① signup → ② 条件 → ③ just_entered TP算出 → ④ エントリー → ⑤ エグジット）。
    def _decide_at(self, A, i) -> list[dict]:
        c = self.cfg
        ms = A["ms"]; ub = A["ub"]; lb = A["lb"]
        orders: list[dict] = []
        d = int(A["dir60"][i]); cur_phase = A["phase"][i]
        over_i = (ms[i - 1] <= lb[i - 1]) and (ms[i] > lb[i]) if i >= 1 else False
        under_i = (ms[i - 1] >= ub[i - 1]) and (ms[i] < ub[i]) if i >= 1 else False
        cu_i = bool(A["cu"][i]); cd_i = bool(A["cd"][i])
        zhigh_i = A["zhigh"][i]; zlow_i = A["zlow"][i]; atr_i = A["atr"][i]

        size = int(self.position_size)      # エンジン確定の符号付き建玉
        prev = int(self._prev_size)

        # ============ ① signup 更新 ============
        if cu_i:
            self.signup = 1
        elif cd_i:
            self.signup = -1

        # ============ ② 条件 ============
        is_trend = (self.signup == 1 and d == 1) or (self.signup == -1 and d == -1)
        is_reverse = (self.signup == 1 and d == -1) or (self.signup == -1 and d == 1)
        allow_trend = c["strategy_mode"] in ("T", "ALL")
        allow_reverse = c["strategy_mode"] in ("R", "ALL")
        take_signal = (is_trend and allow_trend) or (is_reverse and allow_reverse)
        allow_long_phase = bool(c["allow_long"].get(cur_phase, False))
        allow_short_phase = bool(c["allow_short"].get(cur_phase, False))
        if c["use_sync_filter"]:
            if d == 1:
                sync_long_ok = bool(A["up_bot_K"][i]); sync_short_ok = bool(A["up_top_K"][i])
            elif d == -1:
                sync_long_ok = bool(A["dn_bot_K"][i]); sync_short_ok = bool(A["dn_top_K"][i])
            else:
                sync_long_ok = sync_short_ok = False
        else:
            sync_long_ok = sync_short_ok = True

        # ============ ③ just_entered → TP ターゲット（約定値・約定バーピボットから）============
        # [PINE] Pine L877-897：position_size の立ち上がりで R と TP を確定（avg_price は実約定値）。
        if size > 0 and prev <= 0:
            self.zz_p1 = zlow_i          # Long の SL ライン（R 計算用・約定バーの生 zz60 安値）
            self.tp1, self.tp2 = self._tp_targets(+1, atr_i)
        elif size < 0 and prev >= 0:
            self.zz_p1 = zhigh_i         # Short の SL ライン（R 計算用・約定バーの生 zz60 高値）
            self.tp1, self.tp2 = self._tp_targets(-1, atr_i)
        elif size == 0:
            self.zz_p1 = np.nan; self.tp1 = np.nan; self.tp2 = np.nan

        # ============ ④ エントリー（Pine L794-864・4階層 if。約定は次バー始値）============
        if size == 0 and self.signup == 1:                 # state1: flat→Long
            if over_i:
                if take_signal and allow_long_phase and sync_long_ok:
                    orders.append({"t": "entry", "dir": 1, "qty": self.qty_per_entry, "comment": "L"})
                self.signup = 0
        elif size == 0 and self.signup == -1:              # state2: flat→Short
            if under_i:
                if take_signal and allow_short_phase and sync_short_ok:
                    orders.append({"t": "entry", "dir": -1, "qty": self.qty_per_entry, "comment": "S"})
                self.signup = 0
        elif size < 0 and self.signup == 1:                # state3: Short保有→Longドテン
            if over_i:
                if take_signal and c["allow_dohten"] and allow_long_phase and sync_long_ok:
                    orders.append({"t": "entry", "dir": 1, "qty": self.qty_per_entry, "comment": "L_dohten"})
                self.signup = 0
        elif size > 0 and self.signup == -1:               # state4: Long保有→Shortドテン
            if under_i:
                if take_signal and c["allow_dohten"] and allow_short_phase and sync_short_ok:
                    orders.append({"t": "entry", "dir": -1, "qty": self.qty_per_entry, "comment": "S_dohten"})
                self.signup = 0

        # ============ ⑤ 3Split エグジット（Pine L929-947・保有中は毎バー）============
        # TP1/TP2 を毎バー limit 再配置（各 ID 一度きり約定はエンジンが担保）＋ 反対サインで成行全決済。
        if size > 0:
            if not np.isnan(self.tp1):
                orders.append({"t": "exit", "id": "TP1_L", "qty": 1, "limit": self.tp1, "comment": "TP1_C"})
            if not np.isnan(self.tp2):
                orders.append({"t": "exit", "id": "TP2_L", "qty": 1, "limit": self.tp2, "comment": "TP2_C"})
            if under_i:
                orders.append({"t": "close", "qty": None, "comment": "under"})
        elif size < 0:
            if not np.isnan(self.tp1):
                orders.append({"t": "exit", "id": "TP1_S", "qty": 1, "limit": self.tp1, "comment": "TP1_C"})
            if not np.isnan(self.tp2):
                orders.append({"t": "exit", "id": "TP2_S", "qty": 1, "limit": self.tp2, "comment": "TP2_C"})
            if over_i:
                orders.append({"t": "close", "qty": None, "comment": "over"})

        self._prev_size = size
        return orders

    # ---- live: 確定足ごと（バッファ再計算 → 決定。BT高速パスと同一結果）----
    def on_bar(self, bar) -> list[dict]:
        self._ts.append(bar.ts); self._o.append(bar.open); self._h.append(bar.high)
        self._l.append(bar.low); self._c.append(bar.close)
        if len(self._c) > self.W:
            self._ts.pop(0); self._o.pop(0); self._h.pop(0); self._l.pop(0); self._c.pop(0)
        if len(self._c) < 3:        # 極小本数スキップ（step の i<2 と同条件）
            return []
        H = np.asarray(self._h, float); L = np.asarray(self._l, float); C = np.asarray(self._c, float)
        A = self._compute_indicators(H, L, C, pd.DatetimeIndex(self._ts))
        orders = self._decide_at(A, len(C) - 1) or []
        return self._session_gate(orders, getattr(bar, "ts", None))


def build():
    return MESA_Stochastic()
