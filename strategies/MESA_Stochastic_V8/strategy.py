# -*- coding: utf-8 -*-
"""MESA_Stochastic V8 — 戦略（最小標準・「1バーで動く」＝Pine と同じ作り）。

V7_8 からの設計変更（2026-07-02 確定・devlog 参照）:
  [追加] 順張り枝（トレンド押し目買い）: dir60=+1 かつ up系phase（up_start/uptrend）で、
         浅バンド trend_band(-0.4) の上抜き再クロス ∧ FibSync up_bot(0.55)。
         限界品質=13本/+89.8万/PF5.69（4年）。バンドは -0.3/-0.4 で plateau。
  [追加] 弱気ダイバージェンス・ゲート（順張り枝のみ）: bear_div 中はトレンド押し目買いをしない。
         逆張り枝には適用しない（div圏の除外/減量とも equity 悪化を実測＝内在コスト）。
  [削除] ショート側全部（state2/state4・allow_short・upper側sync）: 4年5本・エッジ未証明・
         踏み上げテールのみ持ち込むため停止（2026-06-25 実損の再発防止）。
  [削除] ドテン（allow_dohten）: ロングオンリーでは発生しない。
  [削除] strategy_mode / take_signal（順張り/逆張りモード判定）: 枝を dir60 で明示ゲートに置換。
  [削除] TP モード E（ATR 基準）: C 固定が最良と確定済（devlog 2026-07-01）。ATR 計算ごと撤去。
  [変更] fib_depth 0.5 → 0.55（plateau 0.55〜0.65 の保守端。最大DD -96.6万→-34.2万の主因）。
  [不変] 基軸オシレーター・ZZ60・phase・signup・逆張りバンド(-0.8)・3Split 出口・約定モデル。

4年較正 BT（2022-12-30〜2026-07-01・73,298本）:
  V8 = n=628 / win 69.7% / PF 2.59 / 純益 +12,803,000 / 最大DD -342,000
  （V7_8 = n=638 / PF 2.35 / +12,014,500 / -966,000）年別DD 全年 -34.2万以下。

  - 確定足ごとに on_bar(bar)/step(A,i) が呼ばれ、注文リストを返す（確定足の終値で判断）。
  - 指標は on_bar 内で毎バー更新（直近 window 本のバッファを保持し _lib 純関数で再計算）。
  - パラメータは config.json（ローカルエンジンで調整）。

★約定モデル＝TV（Pine）完全忠実（2026-06-15 v3.5 確定）:
  - エントリー（strategy.entry）/ 標準決済（strategy.close）＝**成行・次バー始値**約定。
  - TP1/TP2（strategy.exit limit）＝**指値・イントラバー**約定（毎バー再配置・各 ID 一度きり）。
  - 約定は共有 `_engine` の PineBroker が行う＝戦略は注文を返すだけ。
  - TP ターゲット＝`position_avg_price + tp_R × R`、R＝|position_avg_price − 約定バーの zz60 安値|。

決定ロジック（V8・ロングオンリー2枝）:
  ① signup 更新（cu→+1 / cd→-1）
  ② 逆張り枝: dir60=-1 ∧ allow_long[phase] ∧ dn_bot(held,0.55) ∧ lowerBand(-0.8) 上抜き再クロス
  ③ 順張り枝: dir60=+1 ∧ phase∈{up_start,uptrend} ∧ up_bot(0.55) ∧ trend_band(-0.4) 上抜き再クロス
              ∧ not bear_div（トレンド枝のみのゲート）
  ④ 3Split エグジット（TP1=+1R・TP2=+2R 指値／残＝under で成行全決済／SQ は共有エンジン）

★自己完結: _lib の部品をこのフォルダにコピー同梱済（indicators/oscillator/signup/zigzag/
  phases/fibsync/divergence.py）＝跨ぎ import ゼロ・単体で動く。正本は strategies/_lib/
  （divergence.py は本戦略発の新規部品）。

================================================================================
★★ Pine 逆移植ガイド（Python → TradingView Pine 復元用）★★
--------------------------------------------------------------------------------
[A] strategy() 宣言（必ずこの値）:
    strategy('MESA Stochastic V8 FibSync 3Split', shorttitle="MESA8FS3", overlay=true, precision=2,
      margin_long=0, margin_short=0,                 // BT 必須（無いと取引が出ない）
      default_qty_type=strategy.fixed, default_qty_value=3,   // = qty_per_entry
      initial_capital=10000000, pyramiding=1,
      process_orders_on_close=false,                 // ★次バー始値約定（本 Python・PineBroker と一致）
      calc_on_every_tick=false, max_lines_count=500, max_labels_count=500, max_boxes_count=500)

[B] 限月制御 SQ（Python では戦略に入れない＝共有エンジン側。Pine では復元する）:
    import jubilantEagle98317/KengetsuLib/1 as KGL
    if KGL.is_force_close_time(time, i_force_close_offset_min)
        strategy.close_all(comment='SQ前強制クローズ')

[C] V7_8 Pine からの差分＝エントリー部のみ:
    - short/dohten の entry 分岐・strategy_mode/take_signal を削除（ロングオンリー2枝に）
    - 順張り枝: over_trend = ta.crossover(MESAStochastic, i_trend_band) を追加し
      dir_60m==1 and (phase=="up_start" or phase=="uptrend") and up_bot_K and not bear_div で採用
    - bear_div は本ファイル divergence.py と同一ロジック（ms 直近2山 vs 価格高値・thresh/window input）
    - fib_depth 既定 0.5 → 0.55

[D] 表示系（plot/label/dashboard/ZZ60 線）は V7_8 Pine のまま流用（売買に無関係）。
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
_i = _vlib("indicators"); hl2, highpass48 = _i.hl2, _i.highpass48
_o = _vlib("oscillator"); ss_stoch_inertia = _o.ss_stoch_inertia
_s = _vlib("signup"); self_crossover, self_crossunder = _s.self_crossover, _s.self_crossunder
_z = _vlib("zigzag"); compute_60m_zigzag, extract_pivots_from_zigzag = _z.compute_60m_zigzag, _z.extract_pivots_from_zigzag
_p = _vlib("phases"); compute_phase, compute_phase_thresholds = _p.compute_phase, _p.compute_phase_thresholds
_f = _vlib("fibsync"); compute_fib_pullback_v2, compute_reversal_flags, compute_bottomed_held = _f.compute_fib_pullback_v2, _f.compute_reversal_flags, _f.compute_bottomed_held
_d = _vlib("divergence"); compute_bear_divergence = _d.compute_bear_divergence

try:
    import session_lib  # 共有セッション制御（LocalEngine提供・ZIP非同梱）
except Exception:
    session_lib = None

MANIFEST = {"name": "MESA_Stochastic", "interval": 15, "warmup_bars": 300, "version": 3, "label": "V8"}

TREND_PHASES = ("up_start", "uptrend")   # 順張り枝の対象 phase（dir60=+1 でのみ出現）


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
        # upper=出口 under 判定 / lower=逆張り枝のエントリー閾値。順張り枝は trend_band（単一値）。
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
        self.zz_p1 = np.nan          # 約定バーの zz60 安値（R 計算用）
        self.tp1 = np.nan            # TP1 指値価格
        self.tp2 = np.nan            # TP2 指値価格
        self._prev_size = 0          # 前バーの position_size（just_entered 検出用）
        # エンジンが decide 前に注入する Pine globals 相当（既定値）
        self.position_size = 0       # 符号付き枚数（ロングオンリー＝0 以上）
        self.position_avg_price = 0.0
        self.entry_bar = -1
        self.bars_since_entry = -1

    # ---- TP ターゲット（約定値 position_avg_price と zz60 安値から。モード C 固定）----
    # [PINE] just_entered で R=|position_avg_price - zz60安値| から算出。
    def _tp_targets(self) -> tuple[float, float]:
        c = self.cfg
        avg = self.position_avg_price
        if np.isnan(self.zz_p1):
            return np.nan, np.nan
        R = abs(avg - self.zz_p1)
        if R <= 0:
            return np.nan, np.nan
        return avg + c["tp1_R"] * R, avg + c["tp2_R"] * R

    # ---- 指標計算（_lib 純関数・バッファ/全系列 共通）----
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
        # 逆張り枝: dn_bottomed は hold 版（V7_8 確定・底打ち後の新安値で無効化）
        dn_bot_K = compute_bottomed_held(fib["down_fib"], fib["down_fib_slope"], fib["cur_low"], depth, K)
        # 順張り枝: up_bottomed（slope 反転・K 窓 OR）
        up_bot_K, _ = compute_reversal_flags(fib["up_fib"], fib["up_fib_slope"], depth, K, mode="slope")
        # 弱気ダイバージェンス（順張り枝ゲート用）
        bear_div = compute_bear_divergence(ms, H, c["div_thresh"], c["div_window"])
        return {"ms": ms, "cu": cu, "cd": cd, "dir60": dir60, "zhigh": zhigh, "zlow": zlow,
                "phase": phase, "ub": ub, "lb": lb,
                "up_bot_K": up_bot_K, "dn_bot_K": dn_bot_K, "bear_div": bear_div,
                "H": H, "L": L, "C": C}

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
        if i < 2:        # 極小本数スキップ（on_bar の len<3 と同条件）
            return []
        orders = self._decide_at(A, i) or []
        return self._session_gate(orders, self._bt_ts[i] if (self._bt_ts is not None and i < len(self._bt_ts)) else None)

    # ---- 決定（バー i のスカラを読む。on_bar/step 共通＝二重化防止）----
    # 構造: ① signup → ② 2枝の条件 → ③ just_entered TP算出 → ④ エントリー → ⑤ 3Split エグジット。
    def _decide_at(self, A, i) -> list[dict]:
        c = self.cfg
        ms = A["ms"]; ub = A["ub"]; lb = A["lb"]
        orders: list[dict] = []
        d = int(A["dir60"][i]); cur_phase = A["phase"][i]
        # 逆張りトリガー: phase別 lowerBand(-0.8) の上抜き再クロス
        over_rev = (ms[i - 1] <= lb[i - 1]) and (ms[i] > lb[i]) if i >= 1 else False
        # 出口トリガー: phase別 upperBand(+0.8) の下抜きクロス
        under_i = (ms[i - 1] >= ub[i - 1]) and (ms[i] < ub[i]) if i >= 1 else False
        zlow_i = A["zlow"][i]
        size = int(self.position_size)      # エンジン確定の建玉（ロングオンリー＝0 以上）
        prev = int(self._prev_size)

        # ============ ① signup 更新 ============
        if bool(A["cu"][i]):
            self.signup = 1
        elif bool(A["cd"][i]):
            self.signup = -1

        # ============ ② 2枝のゲート ============
        # 逆張り枝: 下降スイングの底（deep 絶望 -0.8 からの反転）
        rev_gate = (d == -1) and bool(c["allow_long"].get(cur_phase, False)) and bool(A["dn_bot_K"][i])
        # 順張り枝: 上昇スイングの押し目（浅バンドからの再開）。弱気ダイバージェンス中は騙し＝入らない。
        trend_trig = False
        if c.get("use_trend_branch", True) and i >= 1:
            tb = c["trend_band"]
            trend_trig = (ms[i - 1] <= tb) and (ms[i] > tb) \
                and (d == 1) and (cur_phase in TREND_PHASES) and bool(A["up_bot_K"][i])
            if c.get("use_trend_div_gate", True) and trend_trig and bool(A["bear_div"][i]):
                trend_trig = False       # ゲートで棄却＝signup は消化しない

        # ============ ③ just_entered → TP ターゲット（約定値・約定バー zz60 安値から）============
        if size > 0 and prev <= 0:
            self.zz_p1 = zlow_i
            self.tp1, self.tp2 = self._tp_targets()
        elif size == 0:
            self.zz_p1 = np.nan; self.tp1 = np.nan; self.tp2 = np.nan

        # ============ ④ エントリー（flat かつ signup=1 のみ。約定は次バー始値）============
        if size == 0 and self.signup == 1:
            if over_rev and rev_gate:
                orders.append({"t": "entry", "dir": 1, "qty": self.qty_per_entry, "comment": "L_rev"})
            elif trend_trig:
                orders.append({"t": "entry", "dir": 1, "qty": self.qty_per_entry, "comment": "L_trend"})
            if over_rev or trend_trig:
                self.signup = 0            # 圏外消化（採用可否に関わらずクロスで消費）

        # ============ ⑤ 3Split エグジット（保有中は毎バー）============
        # TP1/TP2 を毎バー limit 再配置（各 ID 一度きり約定はエンジンが担保）＋ under で成行全決済。
        if size > 0:
            if not np.isnan(self.tp1):
                orders.append({"t": "exit", "id": "TP1_L", "qty": 1, "limit": self.tp1, "comment": "TP1_C"})
            if not np.isnan(self.tp2):
                orders.append({"t": "exit", "id": "TP2_L", "qty": 1, "limit": self.tp2, "comment": "TP2_C"})
            if under_i:
                orders.append({"t": "close", "qty": None, "comment": "under"})

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
