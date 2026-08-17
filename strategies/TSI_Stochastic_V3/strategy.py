# -*- coding: utf-8 -*-
"""TSI_Stochastic V3 — 戦略（最小標準・「1バーで動く」＝Pine と同じ作り）。

★前提データ形式＝TV 新形式（板寄せ統合・2026-07-24 全製品統一）。
V2 からの変更（V3・2026-07-24）:
  [削除] 境界エントリー排除: 旧形式の板寄せ足での虚構約定を防ぐ機構＝新形式では対象の足が
         存在せず session_lib が全ケースを覆うため撤去（fills 完全一致を実証・_STRUCTURE.md 修正①）。
  [不変] エントリー・3Split 出口・タイムアウト撤退・約定モデル。

基軸＝TSI（True Strength Index・HP 不使用）→ ストキャス慣性 = MESAStochastic。
MESA V7_8 ハーネスの基軸オシレーターを TSI に差し替えた姉妹戦略（ハーネスは MESA/DT/CMF/Momentum と同一）。
  - 確定足ごとに on_bar(bar)/step(A,i) が呼ばれ、注文リストを返す（確定足の終値で判断）。
  - パラメータは config.json（ローカルエンジンで調整）。

★約定モデル＝TV（Pine）完全忠実（2026-06-15 v3.5 確定。旧「同バー終値約定」は撤回）:
  - エントリー（strategy.entry）/ 標準決済・ドテン（strategy.close）＝**成行・次バー始値**約定。
  - TP1/TP2（strategy.exit limit）＝**指値・イントラバー**約定（毎バー再配置・各 ID 一度きり）。
  - 約定は共有 `_engine` の PineBroker が行う＝戦略は注文を返すだけ。
  - 戦略は Pine 同様に**エンジンが確定したポジション**を読む:
    `self.position_size` / `self.position_avg_price`（実約定値）/ `self.entry_bar`。
  - TP ターゲット＝`position_avg_price ± tp_R × R`、R＝|position_avg_price − 約定バーの zz60 ピボット|。

決定ロジックは Pine 本体と 1:1（4state エントリー＋3Split エグジット。SQ は共有エンジン）。

★自己完結: _lib の部品をこのフォルダにコピー同梱済（indicators/oscillator/signup/zigzag/phases/fibsync.py）。

================================================================================
★★ Pine 逆移植ガイド（Python → TradingView Pine 復元用）★★
[A] strategy() 宣言（必ずこの値）:
    strategy('N225 TSI Stoch 3Split', shorttitle="TSIStoch3", overlay=true, precision=2,
      margin_long=0, margin_short=0, default_qty_type=strategy.fixed, default_qty_value=3,
      initial_capital=10000000, pyramiding=1,
      process_orders_on_close=false,                 // ★次バー始値約定（本 Python・PineBroker と一致）
      calc_on_every_tick=false, max_lines_count=500, max_labels_count=500, max_boxes_count=500)
[B] 限月制御 SQ（Python では戦略に入れない＝共有エンジン側。Pine は KengetsuLib ライブ参照で復元）。
[C] プルバック順張りサブ（config use_pullback 既定 false＝本 Python は未実装・売買に無関係）。
[D] 表示系（plot/label/dashboard/bgcolor/ZZ60 線）＝TV 目視チェック用に Pine ソースから復元。
[E] 表示用だが判定に無関係な計算（ZZ15・kengai_msg・mesa_cross）＝省略可。
[F] オシレーター基軸（TSI・本 Python の前段＝Pine と同一式）:
    TSI(close, tsi_long, tsi_short)（HP 不使用）→ SuperSmoother(10) → Stoch(20) →
    SuperSmoother → 0.33*2*(x-0.5)+0.67*前値 → ±0.999 = MESAStochastic。
================================================================================
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import importlib.util as _ilu
_HERE = Path(__file__).resolve().parent
def _vlib(_m):
    _k = f"_v.{_HERE.parent.name}.{_HERE.name}.{_m}"
    _mod = sys.modules.get(_k)
    if _mod is None:
        _sp = _ilu.spec_from_file_location(_k, str(_HERE / (_m + ".py")))
        _mod = _ilu.module_from_spec(_sp); sys.modules[_k] = _mod; _sp.loader.exec_module(_mod)
    return _mod
_i = _vlib("indicators"); tsi, atr14 = _i.tsi, _i.atr14
_o = _vlib("oscillator"); ss_stoch_inertia = _o.ss_stoch_inertia
_s = _vlib("signup"); self_crossover, self_crossunder = _s.self_crossover, _s.self_crossunder
_z = _vlib("zigzag"); compute_60m_zigzag, extract_pivots_from_zigzag = _z.compute_60m_zigzag, _z.extract_pivots_from_zigzag
_p = _vlib("phases"); compute_phase, compute_phase_thresholds = _p.compute_phase, _p.compute_phase_thresholds
_f = _vlib("fibsync"); compute_fib_pullback_v2, compute_reversal_flags, compute_bottomed_held = _f.compute_fib_pullback_v2, _f.compute_reversal_flags, _f.compute_bottomed_held

try:
    import session_lib  # 共有セッション制御（LocalEngine提供・ZIP非同梱）
except Exception:
    session_lib = None

MANIFEST = {"name": "TSI_Stochastic", "interval": 15, "warmup_bars": 500, "version": 4, "label": "V3"}


def _load_config() -> dict:
    with open(Path(__file__).resolve().parent / "config.json", encoding="utf-8") as f:
        return json.load(f)


class TSI_Stochastic:
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
        self.upper = dict(c["upper_band"])
        self.lower = dict(c["lower_band"])
        self._ts: list = []
        self._o: list = []
        self._h: list = []
        self._l: list = []
        self._c: list = []
        self.signup = 0
        self.zz_p1 = np.nan
        self.tp1 = np.nan
        self.tp2 = np.nan
        self._prev_size = 0
        # [V8_2共通] タイムアウト撤退の走行極値（経過カウンタ方式・ロング/ショート対称）
        self._to_fav = np.nan        # 建玉発生バー以降の順行極値（L:最高値 / S:最安値）
        self._to_floor = np.nan      # 床の極値（L:最も高い安値 / S:最も低い高値）
        self.position_size = 0
        self.position_avg_price = 0.0
        self.entry_bar = -1
        self.bars_since_entry = -1

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

    def _compute_indicators(self, H, L, C, idx) -> dict:
        c = self.cfg
        # [PINE] TSI 前段（HP 不使用）: TSI(close,long,short) → SS-stoch-慣性 = MESAStochastic
        ms = ss_stoch_inertia(tsi(C, c["tsi_long"], c["tsi_short"]), c["stoch_length"])
        cu = self_crossover(ms); cd = self_crossunder(ms)
        z = compute_60m_zigzag(H, L, idx, c["zz60_length"], c["zz60_threshold"], c["zz60_threshold_max"])
        dir60 = z["dir_60m"]; dch = z["dirchanged_60m"]
        zhigh = z["zhigh_60m"]; zlow = z["zlow_60m"]
        piv = extract_pivots_from_zigzag(dch, zhigh, zlow, dir60)
        p1 = piv["p1_price"]
        phase = compute_phase(dir60, c["n_transition_bars"])
        ub, lb = compute_phase_thresholds(phase, self.upper, self.lower)
        fib = compute_fib_pullback_v2(dir60, dch, p1, H, L, C)
        depth = c["fib_depth"]; K = c["fib_K"]
        atr = atr14(H, L, C, 14)
        up_bot_K, up_top_K = compute_reversal_flags(fib["up_fib"], fib["up_fib_slope"], depth, K, mode="slope")
        if c.get("dn_invalidate_newlow", True):
            _, dn_top_K = compute_reversal_flags(fib["down_fib"], fib["down_fib_slope"], depth, K, mode="slope")
            dn_bot_K = compute_bottomed_held(fib["down_fib"], fib["down_fib_slope"], fib["cur_low"], depth, K)
        else:
            dn_bot_K, dn_top_K = compute_reversal_flags(fib["down_fib"], fib["down_fib_slope"], depth, K, mode="slope")
        return {"ms": ms, "cu": cu, "cd": cd, "dir60": dir60, "zhigh": zhigh, "zlow": zlow,
                "phase": phase, "ub": ub, "lb": lb, "atr": atr,
                "up_bot_K": up_bot_K, "up_top_K": up_top_K,
                "dn_bot_K": dn_bot_K, "dn_top_K": dn_top_K, "H": H, "L": L, "C": C}

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

    def step(self, A, i) -> list[dict]:
        if i < 2:
            return []
        orders = self._decide_at(A, i) or []
        return self._session_gate(orders, self._bt_ts[i] if (self._bt_ts is not None and i < len(self._bt_ts)) else None)

    def _decide_at(self, A, i) -> list[dict]:
        c = self.cfg
        ms = A["ms"]; ub = A["ub"]; lb = A["lb"]
        orders: list[dict] = []
        d = int(A["dir60"][i]); cur_phase = A["phase"][i]
        over_i = (ms[i - 1] <= lb[i - 1]) and (ms[i] > lb[i]) if i >= 1 else False
        under_i = (ms[i - 1] >= ub[i - 1]) and (ms[i] < ub[i]) if i >= 1 else False
        cu_i = bool(A["cu"][i]); cd_i = bool(A["cd"][i])
        zhigh_i = A["zhigh"][i]; zlow_i = A["zlow"][i]; atr_i = A["atr"][i]

        size = int(self.position_size)
        prev = int(self._prev_size)

        # ① signup
        if cu_i:
            self.signup = 1
        elif cd_i:
            self.signup = -1

        # ② 条件
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

        # ③ just_entered → TP ターゲット（約定値・約定バーピボットから）
        if size > 0 and prev <= 0:
            self.zz_p1 = zlow_i
            self.tp1, self.tp2 = self._tp_targets(+1, atr_i)
        elif size < 0 and prev >= 0:
            self.zz_p1 = zhigh_i
            self.tp1, self.tp2 = self._tp_targets(-1, atr_i)
        elif size == 0:
            self.zz_p1 = np.nan; self.tp1 = np.nan; self.tp2 = np.nan

        # ④ エントリー（4階層 if・約定は次バー始値）
        if size == 0 and self.signup == 1:
            if over_i:
                if take_signal and allow_long_phase and sync_long_ok:
                    orders.append({"t": "entry", "dir": 1, "qty": self.qty_per_entry, "comment": "L"})
                self.signup = 0
        elif size == 0 and self.signup == -1:
            if under_i:
                if take_signal and allow_short_phase and sync_short_ok:
                    orders.append({"t": "entry", "dir": -1, "qty": self.qty_per_entry, "comment": "S"})
                self.signup = 0
        elif size < 0 and self.signup == 1:
            if over_i:
                if take_signal and c["allow_dohten"] and allow_long_phase and sync_long_ok:
                    orders.append({"t": "entry", "dir": 1, "qty": self.qty_per_entry, "comment": "L_dohten"})
                self.signup = 0
        elif size > 0 and self.signup == -1:
            if under_i:
                if take_signal and c["allow_dohten"] and allow_short_phase and sync_short_ok:
                    orders.append({"t": "entry", "dir": -1, "qty": self.qty_per_entry, "comment": "S_dohten"})
                self.signup = 0

        # ⑤ 3Split エグジット（保有中は毎バー・TP 指値再配置＋反対サインで成行全決済）
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

        # ============ [V8_2共通] タイムアウト撤退（即死エントリーの時間切り・L/S対称）============
        # timeout_bars 本経過しても順行 < timeout_maxfe_pct% かつ（床条件時）床なしなら次バー始値で全決済。
        # ハードストップは全水準で4年純益毀損＝不採用（MESA V8_2 検証・devlog 2026-07-18）。
        if size > 0 and prev <= 0:
            self._to_fav = float(A["H"][i]); self._to_floor = float(A["L"][i])
        elif size < 0 and prev >= 0:
            self._to_fav = float(A["L"][i]); self._to_floor = float(A["H"][i])
        elif size == 0:
            self._to_fav = np.nan; self._to_floor = np.nan
        elif size > 0:
            self._to_fav = max(self._to_fav, float(A["H"][i]))
            self._to_floor = max(self._to_floor, float(A["L"][i]))
        else:
            self._to_fav = min(self._to_fav, float(A["L"][i]))
            self._to_floor = min(self._to_floor, float(A["H"][i]))
        if (bool(c.get("timeout_exit", False)) and size != 0
                and self.bars_since_entry >= int(c.get("timeout_bars", 12))
                and not np.isnan(self._to_fav)):
            _avg = self.position_avg_price
            _f = float(c.get("timeout_maxfe_pct", 0.1)) / 100
            if size > 0:
                _dead = self._to_fav < _avg * (1 + _f)
                if _dead and bool(c.get("timeout_require_no_floor", True)):
                    _dead = self._to_floor < _avg
            else:
                _dead = self._to_fav > _avg * (1 - _f)
                if _dead and bool(c.get("timeout_require_no_floor", True)):
                    _dead = self._to_floor > _avg
            if _dead and not any(od.get("t") == "close" for od in orders):
                orders.append({"t": "close", "qty": None, "comment": "timeout"})

        self._prev_size = size
        return orders

    def on_bar(self, bar) -> list[dict]:
        self._ts.append(bar.ts); self._o.append(bar.open); self._h.append(bar.high)
        self._l.append(bar.low); self._c.append(bar.close)
        if len(self._c) > self.W:
            self._ts.pop(0); self._o.pop(0); self._h.pop(0); self._l.pop(0); self._c.pop(0)
        if len(self._c) < 3:
            return []
        H = np.asarray(self._h, float); L = np.asarray(self._l, float); C = np.asarray(self._c, float)
        A = self._compute_indicators(H, L, C, pd.DatetimeIndex(self._ts))
        orders = self._decide_at(A, len(C) - 1) or []
        return self._session_gate(orders, getattr(bar, "ts", None))


def build():
    return TSI_Stochastic()
