# -*- coding: utf-8 -*-
"""MESA_Stochastic V8_3 — 戦略（最小標準・「1バーで動く」＝Pine と同じ作り）。

★前提データ形式＝TV 新形式（板寄せ統合・2026-07-24 全製品統一）:
  セッション引けの板寄せは独立した1本足ではなく、セッション最終足の close/high/low/volume に
  統合されている（DataPipeline 正本・TradingView・LocalEngine すべて同一構造）。
  セッション境界の判定は本ファイル内すべて「バー間隔中央値×1.5 超のギャップ」のデータ導出
  （時刻決め打ちなし）。引け際の新規/決済の可否は共有 session_lib（時計・カレンダー基準）に一任する。

V8_2 からの変更（V8_3・2026-07-24）:
  [削除] 境界エントリー排除（boundary_entry_block）: 旧形式の板寄せ足（セッション時刻定義の外に
         あり session_lib のゲートが効かない足）での虚構約定を防ぐ機構だった。新形式では対象の
         足自体が存在せず、session_lib の block_new が全ケースを覆うため撤去（実測で成績完全一致）。
  [不変] エントリー2枝・3Split 出口・構造損切り・タイムアウト撤退・約定モデル・全パラメータ。

決定ロジック（ロングオンリー2枝）:
  ① signup 更新（cu→+1 / cd→-1）
  ② 逆張り枝: dir60=-1 ∧ allow_long[phase] ∧ dn_bot(held,fib_depth) ∧ lowerBand 上抜き再クロス
  ③ 順張り枝: dir60=+1 ∧ phase∈{up_start,uptrend} ∧ up_bot(fib_depth) ∧ trend_band 上抜き再クロス
              ∧ not bear_div（トレンド枝のみのゲート）
  ④ 3Split エグジット（TP1=+tp1_R×R・TP2=+tp2_R×R 指値／残＝under で成行全決済）
  ⑤ 構造損切り SE_PSL（受け入れ確認型）: エントリー時に PSL（直前に完了したセッションの安値）の
     **上**にいた玉のみ監視。終値が PSL を割ったら時計開始、grace 本以内に終値回復で解除、
     未回復なら次バー始値で全決済し、under クロスまで新規封鎖。
     ★PSL より下で建った玉（深い逆張り）は監視対象外。この適格条件を外すと正常トレードを
     大量処刑し PF が崩壊する（実測済・絶対に外さない）。
  ⑥ タイムアウト撤退: timeout_bars 本経過しても MaxFE（建値からの最大順行）< timeout_maxfe_pct%
     かつ床なし（最も高い安値 < 建値）なら次バー始値で全決済（即死エントリーの時間切り。
     ハードストップは全水準で純益毀損＝不採用が確定済み。時間×床で切るのが本戦略の正解）。

実行の作り:
  - 確定足ごとに on_bar(bar)/step(A,i) が呼ばれ、注文リストを返す（確定足の終値で判断）。
  - 指標は on_bar 内で毎バー更新（直近 window 本のバッファを保持し同梱純関数で再計算）。
  - パラメータの意味と設定方法＝config.json の各 _grp コメント（そちらが正本）。

★約定モデル＝TV（Pine）完全忠実:
  - エントリー（strategy.entry）/ 標準決済（strategy.close）＝**成行・次バー始値**約定。
  - TP1/TP2（strategy.exit limit）＝**指値・イントラバー**約定（毎バー再配置・各 ID 一度きり）。
  - 約定は共有 `_engine` の PineBroker が行う＝戦略は注文を返すだけ。
  - TP ターゲット＝`position_avg_price + tp_R × R`、R＝|position_avg_price − 約定バーの zz60 安値|。
  - 引け際・週末/祝日/SQ の新規・決済可否は共有 session_lib が gate する（本戦略は判定しない）。

★自己完結: _lib の部品をこのフォルダにコピー同梱済（indicators/oscillator/signup/zigzag/
  phases/fibsync/divergence.py）＝跨ぎ import ゼロ・単体で動く。正本は strategies/_lib/
  （divergence.py は本戦略発の新規部品）。

================================================================================
★★ Pine 逆移植ガイド（Python → TradingView Pine 復元用）★★
--------------------------------------------------------------------------------
[A] strategy() 宣言（必ずこの値）:
    strategy('MESA Stochastic V8_3 FibSync 3Split', shorttitle="MESA8FS3", overlay=true, precision=2,
      margin_long=0, margin_short=0,                 // BT 必須（無いと取引が出ない）
      default_qty_type=strategy.fixed, default_qty_value=3,   // = qty_per_entry
      initial_capital=10000000, pyramiding=1,
      process_orders_on_close=false,                 // ★次バー始値約定（本 Python・PineBroker と一致）
      calc_on_every_tick=false, max_lines_count=500, max_labels_count=500, max_boxes_count=500)

[B] 限月制御 SQ（Python では戦略に入れない＝共有エンジン側。Pine では復元する）:
    import jubilantEagle98317/KengetsuLib/1 as KGL
    if KGL.is_force_close_time(time, i_force_close_offset_min)
        strategy.close_all(comment='SQ前強制クローズ')

[C] エントリー部（ロングオンリー2枝）:
    - 逆張り枝: over_rev = ta.crossover(MESAStochastic, i_lower_band_<phase>) を
      dir_60m==-1 and allow_long_<phase> and dn_bot_K で採用
    - 順張り枝: over_trend = ta.crossover(MESAStochastic, i_trend_band) を
      dir_60m==1 and (phase=="up_start" or phase=="uptrend") and up_bot_K and not bear_div で採用
    - bear_div は本ファイル divergence.py と同一ロジック（ms 直近2山 vs 価格高値・thresh/window input）
    - short/dohten/strategy_mode/take_signal は存在しない（書かない）

[D] 表示系（plot/label/dashboard/ZZ60 線）は既存 Pine のまま流用（売買に無関係）。

[E] 構造損切り SE_PSL（本ファイル ⑥ と同一ロジック。Pine 側の書き方）:
    // PSL: セッション境界＝バー間の時間差が通常間隔の1.5倍超（時刻決め打ちなし）
    step = timeframe.in_seconds() * 1000
    new_ses = (time - time[1]) > step * 1.5
    var float ses_lo = na, var float psl = na
    if new_ses
        psl := ses_lo, ses_lo := low
    else
        ses_lo := math.min(nz(ses_lo, low), low)
    // 適格判定（建玉発生バー）と受け入れ時計
    just_entered = strategy.position_size > 0 and strategy.position_size[1] <= 0
    var bool se_ok = false, var int se_cnt = na, var bool se_blocked = false
    if just_entered
        se_ok := not na(psl) and strategy.position_avg_price > psl, se_cnt := na
    if strategy.position_size > 0 and se_ok and not na(psl)
        if close > psl
            se_cnt := na
        else
            se_cnt := na(se_cnt) ? (close < psl ? 0 : na) : se_cnt + 1
            if not na(se_cnt) and se_cnt >= i_se_grace and close < psl
                strategy.close_all(comment='SE_PSL')   // 次バー始値約定
                se_blocked := true, se_ok := false
    if se_blocked and under   // under＝既存の出口クロス
        se_blocked := false
    // エントリー条件に and not se_blocked を追加（signup 消化は変えない）

[F] タイムアウト撤退（本ファイル ⑦ と同一ロジック。Pine 側の書き方）:
    var float to_hi = na, var float to_lo_best = na
    if just_entered
        to_hi := high, to_lo_best := low
    else if strategy.position_size > 0
        to_hi := math.max(to_hi, high), to_lo_best := math.max(to_lo_best, low)
    bars_held = strategy.position_size > 0 ? bar_index - strategy.opentrades.entry_bar_index(0) : 0
    avgp = strategy.position_avg_price
    dead = to_hi < avgp * (1 + i_timeout_maxfe / 100) and to_lo_best < avgp
    if strategy.position_size > 0 and bars_held >= i_timeout_bars and dead
        strategy.close_all(comment='timeout')   // 次バー始値約定
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

MANIFEST = {"name": "MESA_Stochastic", "interval": 15, "warmup_bars": 500, "version": 5, "label": "V8_3"}

TREND_PHASES = ("up_start", "uptrend")   # 順張り枝の対象 phase（dir60=+1 でのみ出現）


def prev_session_low(L, idx) -> np.ndarray:
    """PSL＝直前に完了したセッションの安値（バーごと）。

    セッション境界＝バー間の時間差が通常間隔（差分の中央値）の 1.5 倍を超えるギャップ。
    時刻を決め打ちしない＝夜間 16:30→17:00 等の制度変更・時代混在に耐える。
    先頭セッション中は前セッションが無いため NaN（構造損切りは自動的に不作動）。
    """
    n = len(L)
    if n < 2:
        return np.full(n, np.nan)
    t = np.asarray(idx.view("int64"), dtype=np.int64)
    d = np.diff(t)
    step = float(np.median(d))
    sid = np.concatenate([[0], np.cumsum(d > step * 1.5)])
    lo = pd.Series(np.asarray(L, float)).groupby(sid).min()
    return lo.shift(1).reindex(sid).to_numpy()


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
        # 構造損切りの状態（バー index でなく経過カウンタ＝live のスライドバッファでも同一挙動）
        self._se_ok = False          # このトレードが監視適格（エントリー時に PSL の上）
        self._se_cnt = None          # 割れからの経過バー数（None=非割れ/回復済）
        self._se_blocked = False     # 構造決済後の新規封鎖（under クロスで解除）
        # タイムアウト撤退の走行極値（経過カウンタ方式＝live のスライドバッファでも同一挙動）
        self._to_hi = np.nan         # 建玉発生バー以降の最高値（MaxFE 判定用）
        self._to_lo_best = np.nan    # 建玉発生バー以降の「最も高い安値」（MinFE 床判定用）
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
        # 逆張り枝: dn_bottomed は hold 版（底打ち後の新安値で無効化）
        dn_bot_K = compute_bottomed_held(fib["down_fib"], fib["down_fib_slope"], fib["cur_low"], depth, K)
        # 順張り枝: up_bottomed（slope 反転・K 窓 OR）
        up_bot_K, _ = compute_reversal_flags(fib["up_fib"], fib["up_fib_slope"], depth, K, mode="slope")
        # 弱気ダイバージェンス（順張り枝ゲート用）
        bear_div = compute_bear_divergence(ms, H, c["div_thresh"], c["div_window"])
        # PSL＝直前完了セッションの安値（構造損切りの監視水準）
        psl = prev_session_low(L, idx)
        return {"ms": ms, "cu": cu, "cd": cd, "dir60": dir60, "zhigh": zhigh, "zlow": zlow,
                "phase": phase, "ub": ub, "lb": lb,
                "up_bot_K": up_bot_K, "dn_bot_K": dn_bot_K, "bear_div": bear_div,
                "psl": psl, "H": H, "L": L, "C": C}

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
        # under 封鎖の解除: under クロス＝標準出口が決済したはずの瞬間（エントリー判定より先）
        se_enabled = bool(c.get("struct_exit", False))
        if self._se_blocked and under_i:
            self._se_blocked = False

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
            # 監視適格＝エントリー時に PSL の上（★下で建った深い逆張りは対象外・絶対）
            psl_e = float(A["psl"][i])
            self._se_ok = se_enabled and (not np.isnan(psl_e)) and self.position_avg_price > psl_e
            self._se_cnt = None
            # タイムアウト走行極値の初期化（建玉発生バー＝約定バーの H/L から）
            self._to_hi = float(A["H"][i]); self._to_lo_best = float(A["L"][i])
        elif size == 0:
            self.zz_p1 = np.nan; self.tp1 = np.nan; self.tp2 = np.nan
            self._se_ok = False; self._se_cnt = None   # 封鎖 _se_blocked は under まで維持
            self._to_hi = np.nan; self._to_lo_best = np.nan
        elif size > 0:
            # 保有中は走行極値を更新（同一バー重複更新は max なので無害）
            self._to_hi = max(self._to_hi, float(A["H"][i]))
            self._to_lo_best = max(self._to_lo_best, float(A["L"][i]))

        # ============ ④ エントリー（flat かつ signup=1 のみ。約定は次バー始値）============
        # under 封鎖中は新規を出さない（signup の消化は通常どおり）
        if size == 0 and self.signup == 1:
            if over_rev and rev_gate and not self._se_blocked:
                orders.append({"t": "entry", "dir": 1, "qty": self.qty_per_entry, "comment": "L_rev"})
            elif trend_trig and not self._se_blocked:
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

        # ============ ⑥ 構造損切り（受け入れ確認型・PSL）============
        # 終値が PSL を割ったら経過カウンタ開始（回復で解除）。grace 本経過してなお終値が
        # PSL 未満なら「受け入れ」＝次バー始値で全決済し、under クロスまで新規封鎖。
        if size > 0 and self._se_ok:
            psl_i = float(A["psl"][i])
            c_i = float(A["C"][i])
            if np.isnan(psl_i) or c_i > psl_i:
                self._se_cnt = None                    # 非割れ / 終値で回復 → 解除
            elif self._se_cnt is None:
                if c_i < psl_i:
                    self._se_cnt = 0                   # 割れ確定 → 時計開始
            else:
                self._se_cnt += 1                      # 割れ継続（同値含む）＝経過を数える
                if c_i < psl_i and self._se_cnt >= int(c.get("struct_exit_grace", 12)):
                    orders.append({"t": "close", "qty": None, "comment": "SE_PSL"})
                    self._se_blocked = True
                    self._se_ok = False

        # ============ ⑦ タイムアウト撤退（即死エントリーの時間切り）============
        # timeout_bars 本経過しても MaxFE < timeout_maxfe_pct% かつ（require_no_floor 時）
        # 安値の切り上げが一度も無い（最も高い安値 < 建値）なら次バー始値で全決済。
        # ハードストップは全水準で4年純益毀損＝不採用（復活組の殺害コスト）。時間×床で切る。
        if (bool(c.get("timeout_exit", False)) and size > 0
                and self.bars_since_entry >= int(c.get("timeout_bars", 12))
                and not np.isnan(self._to_hi)):
            avg = self.position_avg_price
            dead = self._to_hi < avg * (1 + float(c.get("timeout_maxfe_pct", 0.1)) / 100)
            if dead and bool(c.get("timeout_require_no_floor", True)):
                dead = self._to_lo_best < avg
            if dead and not any(od.get("t") == "close" for od in orders):
                orders.append({"t": "close", "qty": None, "comment": "timeout"})

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
