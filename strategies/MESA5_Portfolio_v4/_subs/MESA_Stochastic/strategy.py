# -*- coding: utf-8 -*-
"""MESA_Stochastic V8_2 — 戦略（最小標準・「1バーで動く」＝Pine と同じ作り）。

V8_1 からの設計変更（2026-07-18 確定・devlog 2026-07-18 参照）:
  [追加] 境界エントリー排除（config: boundary_entry_block）:
         約定バー（シグナル次バー）が「セッション最終足（6:00/15:45 の板寄せ足）」または
         「セッション跨ぎ（翌セッション寄り）」になる新規エントリーを建てない。
         - 根拠1（実運用）: 板寄せ足での約定は実運用では不可能（アラートは板寄せ後に発火→
           照会中で翌セッション持ち越し＝2026-07-17 の事故）。BT だけが約定できる虚構トレード。
         - 根拠2（成績）: 該当17件/4年は合計 −57.5万円・PF0.42（V2=板寄せ約定12件が PF0.24）。
         - 判定はデータ導出（バー間隔中央値×1.5 超のギャップ＝PSL と同じ流儀・時刻決め打ちなし）。
           BT は precompute で全系列フラグ化。live は LocalEngine session_lib の block_new
           （引け offset+interval 分前以降の新規抑止）が同等以上を常時カバー。TV は Pine 側で復元。
  [追加] タイムアウト撤退（config: timeout_exit / timeout_bars / timeout_maxfe_pct /
         timeout_require_no_floor）:
         エントリー後 timeout_bars(12) 本経過しても MaxFE（建値からの最大順行）が
         timeout_maxfe_pct(0.1)% 未満、かつ安値の切り上げが一度も無い（MinFE<0＝床なし）
         なら次バー始値で全決済（comment='timeout'）。
         - 根拠: 「即死エントリー」（最終 MaxFE<0.1%）は 90件/4年・勝率2.2%・合計−571万円。
           勝ちの91.9%は12本以内に +0.1% に到達済み＝12本が検知の実用下限（それ以前は
           誤検知コストが優越・k=2 で −440万）。床条件（MinFE<0）の併用で誤検知が 31→21件に減少。
           ハードストップは全水準（0.8〜2.5%）で4年純益を毀損し不採用（復活組の殺害コスト）。
  [根拠] 拡張4年較正BT（〜2026-07-18・74,348本）: V8_1=n=664/PF1.81/+8,745,000/DD−603,000 →
         V8_2=n=653/PF2.11/+9,840,500/DD−550,500（+109.6万・全年PF改善または同等・
         timeout 決済96件は平均−3.2万円の損小退出）。感度=timeout_bars 10〜16 で全て正。
  [不変] エントリー2枝・3Split 出口・構造損切り・約定モデル・既存全パラメータ。
         V8_1 完全復帰＝boundary_entry_block=false / timeout_exit=false。

V8 からの設計変更（2026-07-08 確定・strategies/structure_exit_analysis/README.md 参照）:
  [追加] 構造損切り（受け入れ確認型・config: struct_exit / struct_exit_grace）:
         エントリー時に PSL（直前に完了したセッションの安値＝日中にいる間は前夜間安値・
         夜間にいる間は当日日中安値。セッション境界はバー間隔中央値×1.5 超のギャップで
         データ導出＝時刻決め打ちなし）の**上**にいた場合のみ監視。終値が PSL を割ったら
         時計開始、grace(12)本以内に終値で回復すれば解除、未回復なら次バー始値で全決済。
         ★エントリー時に PSL より下で建った玉（深い逆張り）は監視対象外。この適格条件を
         外すと正常トレードを大量処刑し PF1.5 に崩壊する（実測済・絶対に外さない）。
  [追加] under 封鎖: 構造損切り後は under クロス（V8 が決済したはずの瞬間）まで新規
         エントリーを封鎖（signup の消化は通常どおり）＝再エントリー効果の排除。
  [根拠] 4年較正BT: PF 2.59→2.69 / 純益 +174,500円 / DD −34.2万→−33.6万 /
         年別ワースト1損失 2023:+46,500 2024:+66,000 2025:+103,500 2026:±0 改善・
         発動36トレード/4年。基礎分析＝作用の本体は「割れ」でなく「割れたまま戻れない
         （受け入れ）」（PSL系水準の未回復組勝率14〜15% vs 回復組51〜61%）。grace 8〜16 で滑らか。
  [不変] エントリー2枝・3Split 出口（TP1/TP2/under）・約定モデル・既存全パラメータ。

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
  V8_1 = n=628 / win 68.9% / PF 2.69 / 純益 +12,977,500 / 最大DD -336,000
  （V8 = n=628 / PF 2.59 / +12,803,000 / -342,000。struct_exit=false で V8 と完全一致）

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
  ⑤ [V8_1] 構造損切り（PSL 割れ→grace 本未回復で全決済）＋ under 封鎖（新規抑止）

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

[F] V8_2 追加分（本ファイル ④フィルター/⑦ と同一ロジック。Pine 側の書き方）:
    // 境界エントリー排除: 次バーがセッション最終足/跨ぎになる新規を出さない。
    // Pine は次バー時刻を直接読めないため「セッション引けまでの残分数」で判定する
    // （引け時刻は input・既定 日中15:45/夜間6:00。KengetsuLib の SQ 窓と同じ流儀）:
    //   mins_to_close <= 2 * interval なら新規抑止（シグナル足＋板寄せ足の2本分）
    // タイムアウト撤退:
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

[E] V8_1 構造損切り（本ファイル ⑥ と同一ロジック。Pine 側の書き方）:
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

MANIFEST = {"name": "MESA_Stochastic", "interval": 15, "warmup_bars": 300, "version": 4, "label": "V8_2"}

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
        # [V8_2] 境界エントリー排除フラグ（BT: precompute で全系列化・reset では消さない。
        # live(on_bar) は None のまま＝LocalEngine session_lib の block_new が同等以上をカバー）
        self._entry_block = None
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
        # [V8_1] 構造損切りの状態（バー index でなく経過カウンタ＝live のスライドバッファでも同一挙動）
        self._se_ok = False          # このトレードが監視適格（エントリー時に PSL の上）
        self._se_cnt = None          # 割れからの経過バー数（None=非割れ/回復済）
        self._se_blocked = False     # 構造決済後の新規封鎖（under クロスで解除）
        # [V8_2] タイムアウト撤退の走行極値（経過カウンタ方式＝live のスライドバッファでも同一挙動）
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
        # 逆張り枝: dn_bottomed は hold 版（V7_8 確定・底打ち後の新安値で無効化）
        dn_bot_K = compute_bottomed_held(fib["down_fib"], fib["down_fib_slope"], fib["cur_low"], depth, K)
        # 順張り枝: up_bottomed（slope 反転・K 窓 OR）
        up_bot_K, _ = compute_reversal_flags(fib["up_fib"], fib["up_fib_slope"], depth, K, mode="slope")
        # 弱気ダイバージェンス（順張り枝ゲート用）
        bear_div = compute_bear_divergence(ms, H, c["div_thresh"], c["div_window"])
        # [V8_1] PSL＝直前完了セッションの安値（構造損切りの監視水準）
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
        self._entry_block = self._compute_entry_block(idx)
        return self._compute_indicators(H, L, C, idx)

    # ---- [V8_2] 境界エントリー排除フラグ（シグナルバー i 基準・全系列）----
    # 約定バー(i+1)が「セッション最終足（次ギャップ）」or「セッション跨ぎ（手前ギャップ）」なら True。
    # 境界＝バー間隔中央値×1.5 超のギャップ（prev_session_low と同じ流儀・時刻決め打ちなし）。
    def _compute_entry_block(self, idx) -> np.ndarray | None:
        # cross(V1)/auction(V2) を個別フラグで制御可（boundary_entry_block=単一フラグは両方＝後方互換）
        c = self.cfg
        v1 = bool(c.get("boundary_block_cross", c.get("boundary_entry_block", False)))
        v2 = bool(c.get("boundary_block_auction", c.get("boundary_entry_block", False)))
        if not (v1 or v2):
            return None
        n = len(idx)
        blk = np.zeros(n, dtype=bool)
        if n < 3:
            blk[:] = True
            return blk
        t = np.asarray(idx.view("int64"), dtype=np.int64)
        d = np.diff(t)                        # d[i] = ts[i+1] - ts[i]
        thr = float(np.median(d)) * 1.5
        gap = d > thr
        if v1:
            blk[: n - 1] |= gap               # V1: シグナル i → 約定 i+1 がセッション跨ぎ
        if v2:
            blk[: n - 2] |= gap[1:]           # V2: 約定バー i+1 がセッション最終足（板寄せ）
        blk[n - 1] = True                     # 最終バーのシグナルは約定バーが無い
        return blk

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
        # [V8_1] under 封鎖の解除: under クロス＝V8 が決済したはずの瞬間（エントリー判定より先）
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
            # [V8_1] 監視適格＝エントリー時に PSL の上（★下で建った深い逆張りは対象外・絶対）
            psl_e = float(A["psl"][i])
            self._se_ok = se_enabled and (not np.isnan(psl_e)) and self.position_avg_price > psl_e
            self._se_cnt = None
            # [V8_2] タイムアウト走行極値の初期化（建玉発生バー＝約定バーの H/L から）
            self._to_hi = float(A["H"][i]); self._to_lo_best = float(A["L"][i])
        elif size == 0:
            self.zz_p1 = np.nan; self.tp1 = np.nan; self.tp2 = np.nan
            self._se_ok = False; self._se_cnt = None   # 封鎖 _se_blocked は under まで維持
            self._to_hi = np.nan; self._to_lo_best = np.nan
        elif size > 0:
            # [V8_2] 保有中は走行極値を更新（同一バー重複更新は max なので無害）
            self._to_hi = max(self._to_hi, float(A["H"][i]))
            self._to_lo_best = max(self._to_lo_best, float(A["L"][i]))

        # ============ ④ エントリー（flat かつ signup=1 のみ。約定は次バー始値）============
        # [V8_1] under 封鎖中は新規を出さない（signup の消化は通常どおり＝V8 と同じ消費則）
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

        # ============ ⑥ [V8_1] 構造損切り（受け入れ確認型・PSL）============
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

        # ============ ⑦ [V8_2] タイムアウト撤退（即死エントリーの時間切り）============
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

        # ============ ⑧ [V8_2] 境界エントリー排除（BT 系列フラグ。live は session_lib が代替）====
        # signup の消化（④）は変えず、注文だけ間引く＝検証ハーネスと同一の作用点。
        if self._entry_block is not None and i < len(self._entry_block) and self._entry_block[i]:
            orders = [od for od in orders if od.get("t") != "entry"]

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
