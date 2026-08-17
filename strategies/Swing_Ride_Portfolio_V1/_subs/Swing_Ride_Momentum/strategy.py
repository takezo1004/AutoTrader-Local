# -*- coding: utf-8 -*-
"""Swing_Ride_Momentum V1 — モメンタム基軸の4場面振り子（ロング専用）＋ 円建てハードストップ。

【この戦略の成り立ち（2026-08-05 新設）】
  土台＝Swing_Ride_Stochastic_Long V5 のコピー（4場面・確認待ち・場面別の出口）。
  違いは **基軸オシレーターの材料だけ**＝2つの DT を別の役割で使う:
    ・基軸（サイン）  … HP(hl2,48) → RSI(rsi_len=26) → SuperSmoother → ストキャス正規化
                        ＝ DT_Stochastic V3 の基軸と同じ材料（メサタイプの DT）
    ・サブ確認        … 生 DT（原典 DTOSC: RSI21 → StochRSI13 → SMA8・dt_raw.py）
                        ＝ 入口のふるいと浅い損切りの判定に使う（Swing_Ride と同じ）
  土台の基軸は hl2 をそのまま入れていた（＝MESA Stochastic）。ここが唯一の違い。

【現行の照合値（work/v1_bt.py の EXPECT・毎回照合する）】
  ★DD 優先の構成（2026-08-05 ユーザー判断）
    4年 n=737 勝率57.3% PF1.74 純益+10,261,205円 最大DD−591,000円
    ワースト−222,000円・−30万以下0件・−10万以下13件
    年別 +69.3/+152.1/+289.3/+515.4 万円（全年プラス）
    場面別 ①n=95 PF1.98 +126.3万／②n=291 PF1.92 +529.5万／
           ③n=185 PF1.34 +131.6万／④n=166 PF1.80 +238.7万

  ・利益を優先するなら `entries.P1L.dt_alt_pull` を true に戻す:
      n=827 PF1.74 +11,474,785円 最大DD−800,000円・−10万以下21件
      ＝純益 +121.4万 と引き換えに、最大DD +26%・−10万以下 +8件。
      土台（Swing_Ride）では ON が最善だったが、基軸が変わると評価も変わった。

  ・土台との比べ方: 土台 V5＝+1,382万/DD−95.3万・主力は①上げ脚と③下げ脚。
    こちらは +1,026万/DD−59.1万・**主力は②押し目と④戻り**＝得意な場面が分かれている。

【調整の経緯（2026-08-05・詳細は README.md）】
  ① rsi_len   … 26 が最良（21〜30 の台地の頂点・DD も最小。54 は純益 +12.9万だが DD 悪化）
  ② しきい値   … −0.8 が最良（−0.85 は −84万／−0.75 は −204万＝両隣より良い頂点）
  ③ 出口       … 場面別に測り直して +194.8万（1年隠しテストは4年とも改善・合計+187.3万）
  ④ 入口条件   … 現行が最善（外すと利益は増えても裾・DD・年別が崩れる）

【この戦略は何か】
  本体は「しきい値まで沈んでから戻った瞬間に買う逆張り振り子」:
    発火 = signup=+1 ∧ ms が band（既定 −0.8）を上抜き返した足（底圏からの折り返し）
  区分（trend_state±1 × dir60±1 ＝ P1〜P4）は文脈ラベル＝「どの局面で発動を許すか」だけ。
  4局面 = P1L / P2L / P3L / P4L。入口の設定は config の `entries` に1局面＝1ブロックで集約
  （局面ごとに「その局面で意味のある条件だけ」を持つ。未採用の条件はキーごと削除してある）。

  ★2026-08-04 ロング専用に分離。売り4局面・ドテンは別戦略 Swing_Ride_Stochastic_Short へ。
  ★版ごとの改善・修正の履歴は design/改善修正履歴/（Pine ヘッダーからも同じ場所を指している）。

【設計の最重要目標】
  1トレードの損失を 30〜50万円級に膨らませない。裾の原因はギャップでなく「出口が全部遅い」
  こと（跨ぎ逆ギャップの寄与は裾の3%のみ）。前提反証型の早い損切りは4年BTですべて
  「含み損の底で投げる」ことが実証済み＝ノイズ圏の外（700円）に置く床だけが安く正確に
  暴走を遮断する（PSTOP の発火は4年38回＝トレードの4%）。

【現行の照合値（work/v1_bt.py の EXPECT・毎回照合する）】
  4年 n=881 勝率58.8% PF1.83 純益+11,773,017円 最大DD−954,017円
  ワースト−222,000円・−30万以下0件・−10万以下16件

【入口の項目（config の entries）】
  use          … この局面で仕掛けるか
  band         … しきい値（ms がここまで沈んでから戻ったら仕掛ける）
  fib          … 押し・戻りの深さ（FibSync）。材料は脚で自動選択（上げ脚=up_bot_K / 下げ脚=dn_bot_act）
  div          … ダイバージェンス（強気 bull_act）。P3L のみ・既定ON＝必須
  div_alt_dt   … ★P3L: div が無くても「DT 発火が近い ∧ ATR14 が div_alt_atr_max 以下」なら拾う
  dt_filter    … P1L: DT 発火が dt_gate_k 本以内のときだけ入る
  dt_alt_pull  … ★P1L: DT が遠くても「当セッション走行高値から min〜max ATR 下」なら拾う
  thick_filter … 板厚（出来高をこなしても動かない足）の発火は入らない
  wait         … 確認待ち（発火足が下降足なら上昇足/陽転包み足を待つ）。現在は P1L のみ
  band_long は入口には使われない予備値（局面未確定の足のフォールバック）。

★約定モデル＝TV（Pine）完全忠実:
  - entry / close ＝ 成行・次バー始値。TP1/TP2（exit limit）・PSTOP（exit stop）＝イントラバー。
  - 約定は共有 `_engine` の PineBroker。戦略は注文を返すだけ。
  - 引け際・週末/SQ の可否は共有 session_lib が gate する。

★自己完結: _lib の部品をこのフォルダにコピー同梱（indicators/oscillator/signup/zigzag/fibsync）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# 自己完結: 同梱部品を「戦略フォルダ単位の一意キー」で読み込む（多戦略同時ロードでも衝突しない）。
import importlib.util as _ilu
_HERE = Path(__file__).resolve().parent
def _vlib(_m):
    _k = f"_v.{_HERE.parent.name}.{_HERE.name}.{_m}"
    _mod = sys.modules.get(_k)
    if _mod is None:
        _sp = _ilu.spec_from_file_location(_k, str(_HERE / (_m + ".py")))
        _mod = _ilu.module_from_spec(_sp); sys.modules[_k] = _mod; _sp.loader.exec_module(_mod)
    return _mod
_i = _vlib("indicators"); hl2, highpass48, wma = _i.hl2, _i.highpass48, _i.wma
momentum = _i.momentum                                    # ★モメンタム: 基軸の材料
pine_rsi = _i.pine_rsi; roc = _i.roc                      # ★サブ確認の候補（RSI型・ROC型）
_o = _vlib("oscillator"); ss_stoch_inertia = _o.ss_stoch_inertia
_s = _vlib("signup"); self_crossover, self_crossunder = _s.self_crossover, _s.self_crossunder
# ★zigzag60_v2 ＝ v2 仕様（転換確認・起点割れ対称化）。旧 MESA 系の zigzag.py（v2 なし）とは
#   別物なので、混同防止のためファイル名を Pine 正本 zigzag60_v2.pine に揃えた（2026-08-02）。
_z = _vlib("zigzag60_v2"); compute_60m_zigzag, extract_pivots_from_zigzag = _z.compute_60m_zigzag, _z.extract_pivots_from_zigzag
_f = _vlib("fibsync"); compute_fib_pullback_v2, compute_reversal_flags, compute_bottomed_held_ref = _f.compute_fib_pullback_v2, _f.compute_reversal_flags, _f.compute_bottomed_held_ref

try:
    import session_lib  # 共有セッション制御（LocalEngine提供・ZIP非同梱）
except Exception:
    session_lib = None

# 旧称 MESA_TrendSplit →（2026-08-02）Swing_Ride_Stochastic →（2026-08-04）Swing_Ride_Stochastic_Long
# ★2026-08-04 ロング専用に分離。ショートは別戦略 Swing_Ride_Stochastic_Short。
# ★クラス名は Swing_Ride_Stochastic のまま（フォルダ内で一意・測定スクリプトが参照するため据え置き）
MANIFEST = {"name": "Swing_Ride_Momentum", "interval": 15, "warmup_bars": 700, "version": 1, "label": "V1"}

TREND_UP, TREND_DOWN, TREND_NONE = 1, -1, 0

# 8局面（Pine の入口グループと1対1）。P1=上昇×上げ脚 / P2=上昇×下げ脚(押し目) /
# P3=下降×下げ脚 / P4=下降×上げ脚(戻り)、末尾 L=買い・S=売り。
CELLS = ("P1L", "P2L", "P3L", "P4L")

# 局面ごとの既定（config の entries が無い/欠けている場合に使う）。確定構成と同値。
# ★2026-08-02 ユーザー採用決定＝DT と板厚を局面ごとのスイッチで搭載:
#   dt_filter    … 入口: DT 発火（生DT の SK が 10 を上抜き）が3本以内に無い発火は入らない
#   dt_stop      … 出口: DT 発火が3本以内に無い玉はハードストップを dt_stop_pt 円に浅くする
#   thick_filter … 入口: 板厚（(高値−安値)/出来高 が直近の下位2割）の発火は入らない
#   thick_stop   … 出口: 板厚で建った玉はハードストップを thick_stop_pt 円に浅くする
#   既定＝4年BT最良形（P1L=DT+板厚で入口厳選 / P2L・P3L・P4L=DT浅stop / P4L=板厚入口も遮断。
#   4年 n=688 PF1.70 +843.5万 DD−82.7万 −10万以下16件）
#   ★2026-08-03 パラメーター整理（ユーザー指示）: 入口は局面ごとに「意味のあるキーだけ」を持つ。
#     4年測定で選別力が無い/未採用の入口条件はその局面から削除（機構は共有部品として残る）:
#       P1L … dt_filter・thick_filter（採用中）＋確認待ち wait
#             ＋dt_alt_pull / _min / _max（★2026-08-04 採用＝DT の代替条件）
#       P2L … fib（下げ脚の戻り底＝この局面の材料。既定OFF）
#       P3L … fib＋div（div は既定ON＝必須）
#             ＋div_alt_dt / div_alt_atr_max（★2026-08-04 採用＝強気div の代替条件）
#       P4L … thick_filter（採用中）
#       ★連続陰線 dnrun と P2L/P3L/P4L の wait は 2026-08-04 に削除（4年で一貫せず未採用）
#   ★出口の浅い損切り（dt_stop）は entries から分離＝DEFAULT_EXITS（局面別出口）へ。
#     thick_stop は全局面未採用のため削除。
DEFAULT_ENTRIES = {
    "P1L": {"use": True,  "band": -0.8, "dt_filter": True, "thick_filter": True, "wait": True,
            "dt_alt_pull": True, "dt_alt_pull_min": 1.0, "dt_alt_pull_max": 3.0},
    "P2L": {"use": True,  "band": -0.8, "fib": False},
    "P3L": {"use": True,  "band": -0.8, "fib": False, "div": True,
            "div_alt_dt": True, "div_alt_atr_max": 150.0},
    "P4L": {"use": True,  "band": -0.8, "thick_filter": True},
}

# 局面別の出口（入口とパラメーターを分ける・2026-08-03 ユーザー指示）。
#   ★2026-08-05 拡張＝入口と同じく「場面ごとに違う出口」を持てるようにした（ユーザー指示）。
#     出口の当たり方は場面でまるで違う（4年測定: 損切りに当たる割合は P3L 3.3% ／ P4L 28.3%）。
#   値が None のキーは共通値（cfg のトップレベル）を使う＝既定は全場面で従来と同一。
#     dt_stop            … DT 発火が遠い玉は損切りを dt_stop_pt 円に浅くする（P2L/P3L/P4L 採用中）
#                          ※P1L は入口で DT・板厚を弾くため対象玉が存在しない＝指定不可
#     hard_stop_pt       … この場面の損切り幅（円）
#     tp1_R / tp2_R      … この場面の1枚目/2枚目の利確（R の倍数）
#     exit_band          … この場面の3枚目の決済しきい値
#     timeout            … この場面で時間切れ決済を使うか
#     timeout_bars       … 経過本数
#     timeout_maxfe_pct  … 「動いていない」とみなす含み益の上限（％）
#     struct_exit        … この場面で前セッション安値の構造損切りを使うか
_EXIT_COMMON = {"hard_stop_pt": None, "tp1_R": None, "tp2_R": None, "exit_band": None,
                "timeout": None, "timeout_bars": None, "timeout_maxfe_pct": None,
                "struct_exit": None}
DEFAULT_EXITS = {
    "P1L": dict(_EXIT_COMMON),
    "P2L": {"dt_stop": True, **_EXIT_COMMON},
    "P3L": {"dt_stop": True, **_EXIT_COMMON},
    "P4L": {"dt_stop": True, **_EXIT_COMMON},
}

# 測定スクリプトだけが entries に差し込める探索フック（config.json には置かない）
_SCRIPT_ONLY_KEYS = ("hill", "block_off", "psh", "max_hi_atr", "no_bull_leg")


def build_entries(cfg: dict) -> dict:
    """入口テーブルを組み立てる（局面ごとに許可キーが違う・未知キーは明示エラー）。

    ①既定 → ②config の entries → ③旧掃引キー の順に上書きする。
    ★旧キー（dt_stop/thick_stop/thick_filter を持たない局面への指定など）は
      ValueError（静かな無視の防止。2026-08-03 パラメーター整理）。
    """
    tbl = {c: dict(DEFAULT_ENTRIES[c]) for c in CELLS}
    for c, e in (cfg.get("entries") or {}).items():
        if c not in tbl or not isinstance(e, dict):
            continue
        allowed = set(DEFAULT_ENTRIES[c]) | set(_SCRIPT_ONLY_KEYS)
        for k, v in e.items():
            if k.startswith("_"):
                continue                                  # コメントキー
            if k not in allowed:
                raise ValueError(
                    f"entries['{c}'] の '{k}' は不正（2026-08-03 パラメーター整理）。"
                    f"許可キー={sorted(allowed)}。dt_stop は 'exits' へ移動・thick_stop は廃止")
            tbl[c][k] = v
    if "cells" in cfg:                                   # 旧: 使う局面のリスト
        on = set(cfg.get("cells") or [])
        for c in tbl:
            tbl[c]["use"] = c in on
    if "band_cells" in cfg:                              # 旧: 局面別しきい値
        for c, v in (cfg.get("band_cells") or {}).items():
            if c in tbl:
                tbl[c]["band"] = float(v)
    if "fibsync_gate_on" in cfg:                         # 旧: FibSync ゲート（全体＋局面）
        gon = bool(cfg.get("fibsync_gate_on"))
        gc = cfg.get("fibsync_gate_cells") or {}
        for c in tbl:
            if "fib" in DEFAULT_ENTRIES[c]:
                tbl[c]["fib"] = gon and bool(gc.get(c, True))
    return tbl


def build_exits(cfg: dict) -> dict:
    """局面別の出口テーブル（許可キーは場面ごとに固定・未知キー/未知局面は明示エラー）。"""
    tbl = {c: dict(DEFAULT_EXITS[c]) for c in DEFAULT_EXITS}
    for c, e in (cfg.get("exits") or {}).items():
        if c.startswith("_") or not isinstance(e, dict):
            continue                                          # コメントキー
        if c not in tbl:
            raise ValueError(f"exits['{c}'] は不正（場面は {sorted(tbl)} のみ）")
        for k, v in e.items():
            if k.startswith("_"):
                continue
            if k not in DEFAULT_EXITS[c]:
                raise ValueError(
                    f"exits['{c}'] の '{k}' は不正（許可キー={sorted(DEFAULT_EXITS[c])}）"
                    + ("。P1L は入口で DT・板厚を弾くため dt_stop の対象玉が無い"
                       if k == "dt_stop" and c == "P1L" else ""))
            tbl[c][k] = v
    return tbl


def compute_hill_len(H, L, k: int) -> np.ndarray:
    """直前に完成した「小さな山」（谷 → 頂点）を作るのにかかった本数を各足について返す。

    山の頂点＝左右 k 本より高い足／谷＝左右 k 本より安い足。頂点は k 本あとにならないと
    確定しないので、足 i では「i−k 以前で確定した」ピボットしか使わない（未来を見ない）。

    2026-08-01 の P1L 分析で見つかった性質: 直前の小さな山が 3 本（45分）以内で一気に
    作られた急な山なら、その押し目買いは4年すべてプラス。1〜2.5時間かけてダラダラ作った
    山（4〜10本）は4年中3年マイナス＝レンジの山。高さ（円）では分かれず、長さで分かれる。

    戻り値: hill_bars（-1 = まだ山が確定していない）
    """
    n = len(H)
    out = np.full(n, -1, dtype=np.int32)
    if n == 0 or k < 1:
        return out
    hs = pd.Series(H); ls = pd.Series(L)
    rmax = hs.rolling(2 * k + 1, center=True).max().to_numpy()
    rmin = ls.rolling(2 * k + 1, center=True).min().to_numpy()
    is_peak = np.zeros(n, dtype=bool); is_vall = np.zeros(n, dtype=bool)
    is_peak[k:n - k] = H[k:n - k] >= rmax[k:n - k]
    is_vall[k:n - k] = L[k:n - k] <= rmin[k:n - k]
    last_vall = -1; cur = -1
    for i in range(n):
        j = i - k                                   # 足 i の時点で確定済みなのは i−k まで
        if j >= 0:
            if is_vall[j]:
                last_vall = j
            if is_peak[j] and 0 <= last_vall < j:
                cur = j - last_vall                 # 谷 → 頂点 の本数
        out[i] = cur
    return out


def compute_swing_ref(H, L, k: int):
    """★R（リスク単位）の基準＝「いま買った押しの底 / いま売った戻りの天井」（2026-08-01 修正）。

    【なぜ直したか】旧実装は R = |建値 − ZZ60 のピボット| だった。ZZ60 のピボットは
    「その脚の起点」なので、上げ脚で入る局面（P1L・P4L）では建値のはるか下になり、
    R が 450〜555円に膨らんでいた（下げ脚の P2L・P3L は 120円）。結果:
      ・TP1(1.5R) が 675〜832円先 ＝ 実際の伸び（中央140円）に対して到達率 5〜14%
      ・ハードストップ 700円のほうが TP1 より近い ＝ 1枚も利確できずに3枚まとめて逆行
      ・4年の取引の63%（587件）で 3分割返済が成立していなかった
    （ショートは 2026-08-04 に別戦略へ分離済み）

    【直した内容】R の基準を「その脚の起点」から「いま買った押しそのものの底」に変える。
      ref_low  … 直近に確定した山の頂点から現在までの最安値（買いの R 基準）
      ref_high … 直近に確定した谷の底から現在までの最高値（売りの R 基準）
    どちらも過去のみで確定する（頂点/谷は k 本あとに確定。以降は走行の最安/最高を更新）。
    下げ脚では従来とほぼ同じ値になり（機能していた P2L・P3L は壊さない）、上げ脚だけが
    「脚の起点」から「直近の押し安値」に縮む。

    戻り値: (ref_low, ref_high)  ※ 山/谷が未確定の先頭は NaN（呼び出し側で ZZ60 に退避）
    """
    n = len(H)
    ref_lo = np.full(n, np.nan); ref_hi = np.full(n, np.nan)
    if n == 0 or k < 1:
        return ref_lo, ref_hi
    rmax = pd.Series(H).rolling(2 * k + 1, center=True).max().to_numpy()
    rmin = pd.Series(L).rolling(2 * k + 1, center=True).min().to_numpy()
    is_p = np.zeros(n, dtype=bool); is_v = np.zeros(n, dtype=bool)
    is_p[k:n - k] = H[k:n - k] >= rmax[k:n - k]
    is_v[k:n - k] = L[k:n - k] <= rmin[k:n - k]
    cur_lo = np.nan; cur_hi = np.nan
    for i in range(n):
        j = i - k                                  # 足 i で確定済みなのは i−k まで
        if j >= 0:
            if is_p[j]:                            # 新しい山の頂点が確定 → 押しの底を測り直す
                cur_lo = float(L[j:i + 1].min())
            if is_v[j]:                            # 新しい谷が確定 → 戻りの天井を測り直す
                cur_hi = float(H[j:i + 1].max())
        if not np.isnan(cur_lo):
            cur_lo = min(cur_lo, float(L[i]))
        if not np.isnan(cur_hi):
            cur_hi = max(cur_hi, float(H[i]))
        ref_lo[i] = cur_lo; ref_hi[i] = cur_hi
    return ref_lo, ref_hi


def compute_peak_off(H, k: int) -> np.ndarray:
    """各足について「直近に確定した小さな山の頂点から何本経ったか」を返す。

    頂点＝左右 k 本より高い足。頂点 p は p+k で確定するので、この値は必ず k 以上になる。
    ＝「頂点の1本前・頂点そのもの」で入った玉は入口では判別できず（結果でしか分からない）、
      「頂点の k 本後以降」で入った玉だけが入口でも判別できる、という非対称がある。

    2026-08-01 の P1L 分析: 頂点2本後で入った 62 件は勝率56.5%と高いのに PF0.87・−32万。
    平均の負けが −8.95万と突出（他の位置は −5〜6万台）＝勝率が高くても負ける典型。

    戻り値: peak_off（-1 = まだ頂点が確定していない）
    """
    n = len(H)
    out = np.full(n, -1, dtype=np.int32)
    if n == 0 or k < 1:
        return out
    rmax = pd.Series(H).rolling(2 * k + 1, center=True).max().to_numpy()
    is_peak = np.zeros(n, dtype=bool)
    is_peak[k:n - k] = H[k:n - k] >= rmax[k:n - k]
    last = -1
    for i in range(n):
        j = i - k                          # 足 i で確定済みなのは i−k まで
        if j >= 0 and is_peak[j]:
            last = j
        out[i] = (i - last) if last >= 0 else -1
    return out


def _session_ids(idx) -> np.ndarray:
    """セッション通番。境界＝バー間隔の中央値の1.5倍超のギャップ（時刻を決め打ちしない）。

    prev_session_low / prev_session_high と同じ規則。夜間 16:30→17:00 のような
    制度変更・時代混在に耐えるため、時刻そのものは使わない（[[feedback_no_hardcoding]]）。
    """
    t = np.asarray(idx.view("int64"), dtype=np.int64)
    if len(t) < 2:
        return np.zeros(len(t), dtype=np.int64)
    d = np.diff(t)
    step = float(np.median(d))
    return np.concatenate([[0], np.cumsum(d > step * 1.5)])


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


def prev_session_high(H, idx) -> np.ndarray:
    """PSH＝直前に完了したセッションの高値（SE_PSH 用・prev_session_low の鏡像）。"""
    n = len(H)
    if n < 2:
        return np.full(n, np.nan)
    t = np.asarray(idx.view("int64"), dtype=np.int64)
    d = np.diff(t)
    step = float(np.median(d))
    sid = np.concatenate([[0], np.cumsum(d > step * 1.5)])
    hi = pd.Series(np.asarray(H, float)).groupby(sid).max()
    return hi.shift(1).reindex(sid).to_numpy()


def compute_divergence_v3(ms, H, L, dirchanged, dir60,
                          thresh_hi: float, thresh_lo: float,
                          window: int, expiry: int) -> dict:
    """V3 ダイバージェンス（ゾーン方式）。V4 でもそのまま使用（cell_filters の材料）。

    山谷の確定＝changeUp/changeDown（crossover/crossunder＝±0.999 飽和プラトー明けでも発火）。
    re-arm 内蔵＝閾値を一度離れてから次の山谷（同一ゾーン内のより高い山/深い谷は現在側を更新して再評価）。
    山（谷）の価格＝山バー近傍4本の最高値（最安値）。同一ゾーン内更新は max（min）に広げる。
    Returns:
      bear_act / bull_act / hidden_act … 失効付き（評価バーから expiry 本）
      bull_leg / hidden_leg            … 脚の記憶ラッチ（新しい下げ脚の開始でリセット）
    """
    ms = np.asarray(ms, float); n = len(ms)
    cu = self_crossover(ms); cd = self_crossunder(ms)
    hi4p = pd.Series(np.asarray(H, float)).rolling(4).max().shift(1).to_numpy()   # ta.highest(high,4)[1]
    lo4p = pd.Series(np.asarray(L, float)).rolling(4).min().shift(1).to_numpy()   # ta.lowest(low,4)[1]

    bear_act = np.zeros(n, bool); bull_act = np.zeros(n, bool); hidden_act = np.zeros(n, bool)
    bull_leg_a = np.zeros(n, bool); hidden_leg_a = np.zeros(n, bool)

    pk_prev = (np.nan, np.nan, None); pk_cur = (np.nan, np.nan, None); pk_armed = True
    bear = False; bear_bar = None
    tr_prev = (np.nan, np.nan, None); tr_cur = (np.nan, np.nan, None); tr_armed = True
    bull = False; hid = False; bull_bar = None
    bull_leg = False; hidden_leg = False

    for i in range(2, n):
        # --- 山: bear（regular 弱気 = 価格 HH ∧ ms LH）---
        if cd[i] and ms[i - 1] > thresh_hi:
            ev = False
            if pk_armed:
                pk_prev = pk_cur
                pk_cur = (ms[i - 1], hi4p[i], i - 1)
                pk_armed = False; ev = True
            elif ms[i - 1] > pk_cur[0]:
                base = pk_cur[1]
                pk_cur = (ms[i - 1], hi4p[i] if np.isnan(base) else max(base, hi4p[i]), i - 1)
                ev = True
            if ev:
                if pk_prev[2] is not None and pk_cur[2] - pk_prev[2] <= window:
                    bear = (pk_cur[1] > pk_prev[1]) and (pk_cur[0] < pk_prev[0])
                else:
                    bear = False
                bear_bar = i
        if ms[i] < thresh_hi:
            pk_armed = True

        # --- 脚の記憶ラッチのリセット（新しい下げ脚の開始）。谷評価より先＝同バーの新証拠は生かす ---
        if dirchanged[i] and dir60[i] == -1:
            bull_leg = False; hidden_leg = False

        # --- 谷: bull（regular 強気 = 価格 LL ∧ ms HL）/ hidden（価格 HL ∧ ms LL）---
        if cu[i] and ms[i - 1] < thresh_lo:
            ev = False
            if tr_armed:
                tr_prev = tr_cur
                tr_cur = (ms[i - 1], lo4p[i], i - 1)
                tr_armed = False; ev = True
            elif ms[i - 1] < tr_cur[0]:
                base = tr_cur[1]
                tr_cur = (ms[i - 1], lo4p[i] if np.isnan(base) else min(base, lo4p[i]), i - 1)
                ev = True
            if ev:
                if tr_prev[2] is not None and tr_cur[2] - tr_prev[2] <= window:
                    bull = (tr_cur[1] < tr_prev[1]) and (tr_cur[0] > tr_prev[0])
                    hid = (tr_cur[1] > tr_prev[1]) and (tr_cur[0] < tr_prev[0])
                else:
                    bull = False; hid = False
                bull_bar = i
                if bull:
                    bull_leg = True
                if hid:
                    hidden_leg = True
        if ms[i] > thresh_lo:
            tr_armed = True

        bear_act[i] = bear and bear_bar is not None and (i - bear_bar) <= expiry
        bull_act[i] = bull and bull_bar is not None and (i - bull_bar) <= expiry
        hidden_act[i] = hid and bull_bar is not None and (i - bull_bar) <= expiry
        bull_leg_a[i] = bull_leg
        hidden_leg_a[i] = hidden_leg

    return {"bear_act": bear_act, "bull_act": bull_act, "hidden_act": hidden_act,
            "bull_leg": bull_leg_a, "hidden_leg": hidden_leg_a}


def _load_config() -> dict:
    with open(Path(__file__).resolve().parent / "config.json", encoding="utf-8") as f:
        return json.load(f)


class Swing_Ride_Stochastic:
    def __init__(self, cfg: dict | None = None):
        self.session_enabled = True            # ★単独稼働時 ON。ポートフォリオ内包時は親が False に。
        self.interval = MANIFEST.get("interval", 15)
        self._bt_ts = None
        self.cfg = cfg or _load_config()
        # ★旧キーの静かな無視を防ぐ（2026-08-02 局面別スイッチ化・2026-08-03 整理で廃止。明示エラー）
        for _legacy in ("dt_gate_on", "dt_gate_mode", "dt_gate_cells", "dt_gate_qty_fail",
                        "dt_gate_stop_fail", "thick_on", "thick_filter_cells", "thick_stop_cells",
                        "thick_stop_pt"):
            if _legacy in self.cfg:
                raise ValueError(
                    f"旧キー '{_legacy}' は廃止（2026-08-02 局面別スイッチ化 / 2026-08-03 整理）。"
                    "入口は entries（局面ごとの許可キーのみ）・浅い損切りは exits の dt_stop を使うこと")
        self.W = int(self.cfg.get("window", 500))
        self.qty_per_entry = int(self.cfg.get("qty_per_entry", 3))
        self.refresh_entries()
        # ★板厚（thick）を使う構成では、分位の窓（thick_win）ぶんのバッファが要る。
        #   live の on_bar 経路は直近 W 本で再計算するため、W < thick_win だと分位の
        #   母集団が BT より短くなる（2026-08-06 ライブ経路の出来高対応と同時に修正）。
        if any((e or {}).get("thick_filter") for e in self.entries.values()):
            self.W = max(self.W, int(self.cfg.get("thick_win", 1000)) + 100)
        self.reset()

    def refresh_entries(self) -> None:
        """入口・出口テーブルを cfg から組み直す。cfg を差し替え/書き換えた後は必ず呼ぶ
        （precompute の先頭でも自動で呼ぶので、BT の掃引は意識しなくてよい）。"""
        self.entries = build_entries(self.cfg)
        self.exits = build_exits(self.cfg)
        self._cells_on = {c for c, e in self.entries.items() if e.get("use")}

    def reset(self) -> None:
        # バッファ（直近 W 本の確定足）
        self._ts: list = []
        self._o: list = []
        self._h: list = []
        self._l: list = []
        self._c: list = []
        self._v: list = []
        # 決定状態（Pine var）
        self.signup = 0
        self.trend = TREND_NONE          # trend_state（+1/-1/0・close ブレイクで確定・sticky）
        self.entry_kind = ""             # 直近エントリーの局面（"P1L"〜"P4L"）
        self._stop_pt = None             # この玉のハードストップ距離（建てた時点で確定・2026-08-01）
        self._r_floor = 0.0               # R の下限（ATR14 × r_min_atr・建てた時点で確定）
        self._run_stop = np.nan           # ランナー決済ライン（ラチェット・単調に切り上げ/切り下げ）
        self._tp1_done = False            # TP1 が約定済みか（段階引き上げ用）
        self._tp2_done = False
        self.zz_p1 = np.nan              # 約定バーの R 基準（Long=ZZ60 安値 / Short=ZZ60 高値）
        self.tp1 = np.nan
        self.tp2 = np.nan
        self._prev_size = 0
        # 底圏 滞在中の最安値（DIPLOW 用・買った押しの底）
        # 前提反証SL（PRSL・既定OFF）
        # 構造損切り（SE_PSL）
        self._se_ok = False              # 建値 > PSL の玉のみ監視
        self._se_cnt = None
        # 新規封鎖（出口クロスまで）
        self._blk_long = False
        self._gate_blk_long = False       # ゲート棄却によるエピソード封鎖（SE/PRSL の封鎖とは独立）
        self._run_armed = False          # ランナー決済ラインを出している最中か（封鎖判定用）
        # タイムアウト走行極値
        self._to_hi = np.nan             # 最高値（MaxFE）
        self._to_lo = np.nan             # 最安値（MAE）
        self._to_lo_best = np.nan        # 最も高い安値（床）
        # ★V2 確認待ち（2026-08-03 採用・買い側のみ）
        self._v2_armed = False           # 確認待ち中（発火済み・上昇足待ち）
        self._v2_runmin = np.nan         # 発火足の1本前からの走行最安値（構造損切りの基準）
        self._v2_cell = ""               # 発火した局面
        self._v2_pend_level = None       # 発注足で確定した構造損切り水準（None=なし）
        self._v2_pend_bar = -1           # 発注した足（次バーで約定しなかった pend を捨てる安全弁）
        # エンジン注入（Pine globals 相当）
        self.position_size = 0
        self.position_avg_price = 0.0
        self.entry_bar = -1
        self.bars_since_entry = -1

    # ---- 場面別の出口の値（exits[場面] に指定が無ければ共通値・2026-08-05）----
    def _x(self, key: str, default=None, cell: str | None = None):
        """いま持っている玉の場面の出口設定を読む。None なら cfg の共通値へ落ちる。"""
        e = (getattr(self, "exits", {}) or {}).get(cell or self.entry_kind) or {}
        v = e.get(key)
        return v if v is not None else self.cfg.get(key, default)

    # ---- TP ターゲット（買いのみ。R = |建値 − 押しの底|）----
    def _tp_targets(self) -> tuple[float, float]:
        avg = self.position_avg_price
        if np.isnan(self.zz_p1):
            return np.nan, np.nan
        R = max(abs(avg - self.zz_p1), float(getattr(self, "_r_floor", 0.0) or 0.0))
        if R <= 0:
            return np.nan, np.nan
        return (avg + float(self._x("tp1_R")) * R,
                avg + float(self._x("tp2_R")) * R)

    # ---- 指標計算（純関数・バッファ/全系列 共通）----
    #   V（出来高）は任意。BT は precompute が渡し、live は on_bar のバッファが渡す
    #   （2026-08-06 対応済み＝板厚は BT・live の両経路で有効）。
    def _compute_indicators(self, H, L, C, idx, V=None, O=None) -> dict:
        c = self.cfg
        # ★モメンタムの基軸（2026-08-05）: (hl2 − hl2[mom_len]) → HP(48) → SS-stoch-慣性。
        #   Momentum_Combo V3 の基軸と同じ材料。サブ確認は config の sub_kind で選ぶ
        #   （"dt"＝生DT／"mom2"＝2つ目のモメンタム）。
        ms = ss_stoch_inertia(highpass48(momentum(hl2(H, L), int(c["mom_len"]))), c["stoch_length"])
        cu = self_crossover(ms); cd = self_crossunder(ms)
        # ZZ60 v2（正本＝work/zigzag60_v2.pine。confirm_bars=3 / fix_sym=true）
        z = compute_60m_zigzag(H, L, idx, c["zz60_length"], c["zz60_threshold"], c["zz60_threshold_max"],
                               confirm_bars=int(c.get("zz60_confirm_bars", 3)),
                               fix_sym=bool(c.get("zz60_fix_sym", True)))
        dir60 = z["dir_60m"]; dch = z["dirchanged_60m"]
        zhigh = z["zhigh_60m"]; zlow = z["zlow_60m"]
        piv = extract_pivots_from_zigzag(dch, zhigh, zlow, dir60)
        p1 = piv["p1_price"]; p2 = piv["p2_price"]
        # 直近の「確定」スイング（Pine: array.get(zz_price_60m, 1)/(…, 2)）。進行中 slot0 は使わない。
        swing_low = np.where(dir60 == 1, p1, p2)
        swing_high = np.where(dir60 == 1, p2, p1)
        # FibSync（cell_filters の材料）
        fib = compute_fib_pullback_v2(dir60, dch, p1, H, L, C)
        depth = c["fib_depth"]; K = c["fib_K"]
        dn_bot_act, dn_bot_ref = compute_bottomed_held_ref(fib["down_fib"], fib["down_fib_slope"],
                                                           fib["cur_low"], depth, K)
        # 上げ脚側は K 窓 OR（bottomed=買い材料 / topped=売り材料）。
        up_bot_K, up_top_K = compute_reversal_flags(fib["up_fib"], fib["up_fib_slope"], depth, K, mode="slope")
        # 下げ脚側の売り材料（戻りの頭打ち）。買い側 dn_bot_act は hold 版（新安値で即無効化＝V7_8 確定）
        # だが、売り材料に対応する hold 版（新高値で無効化）は原典に無いため K 窓 OR を使う。
        _, dn_top_K = compute_reversal_flags(fib["down_fib"], fib["down_fib_slope"], depth, K, mode="slope")
        # ダイバージェンス（cell_filters の材料）
        dv = compute_divergence_v3(ms, H, L, dch, dir60,
                                   float(c.get("div_thresh", 0.4)), float(c.get("div_thresh_lo", -0.4)),
                                   int(c.get("div_window", 150)), int(c.get("div_expiry", 12)))
        # 小さな山の長さ／頂点からの経過（条件⑤ hill・出口の局面別ストップの材料・2026-08-01）
        hill_bars = compute_hill_len(H, L, int(c.get("hill_k", 2)))
        peak_off = compute_peak_off(H, int(c.get("hill_k", 2)))
        ref_low, ref_high = compute_swing_ref(H, L, int(c.get("hill_k", 2)))   # ★R 基準（2026-08-01 修正）
        # ATR14 と 当セッション走行高値からの距離（入口条件⑦の材料・2026-08-01）
        _pc = np.concatenate([[C[0]], C[:-1]])
        _tr = np.maximum(H - L, np.maximum(np.abs(H - _pc), np.abs(L - _pc)))
        atr14 = pd.Series(_tr).rolling(14, min_periods=1).mean().to_numpy()
        _sid = _session_ids(idx)
        ses_hi = pd.Series(np.asarray(H, float)).groupby(_sid).cummax().to_numpy()
        ses_lo = pd.Series(np.asarray(L, float)).groupby(_sid).cummin().to_numpy()
        d_seshi = (ses_hi - C) / np.maximum(atr14, 1e-9)
        # PSL / PSH（構造損切りの監視水準）
        psl = prev_session_low(L, idx)
        psh = prev_session_high(H, idx)
        # WMA 束（表示・分析用）
        wl = c.get("wma_lengths", [90, 180, 270, 360])
        wmas = {f"wma{n_}": wma(C, int(n_)) for n_ in wl}
        # ★DT 距離ゲートの材料（2026-08-02・既定OFF＝dt_gate_on が false なら計算も参照もしない）。
        #   生 DT（dt_raw.py・原典 DTOSC）の SK が level を上抜いた足（買い側の DT 発火）からの
        #   経過本数。因果的（過去方向のみ）。売り側は 100−level の下抜きの鏡像。
        #   根拠＝work/dt_distance_ledger.py（距離≤3〜5 で平均 ride 約3倍・MAE 約3割減・4年全プラス）。
        # ★上位足（60分）位相ゲートの材料（2026-08-02・既定OFF）。60分足（境界＝ZigZag60 と同一）で
        #   同じ MESA ストキャスを計算し、**完了足の値のみ**（直近完了 bin＝先読みなし）を写す。
        #   mtf_since_up＝ms60 の −0.8 クロスアップからの経過（60分足の本数）／mtf_val＝ms60 の値。
        #   根拠＝work/mtf_phase_ledger.py（dist≤6 平均+75・ms60>0.8 圏は平均+0.6 の無価値層・
        #   DT ゲートとの重なり 74/594＝独立）。
        mtf_gate = {}
        if bool(c.get("mtf_gate_on", False)) or (c.get("mtf_ceiling_cells") or []):
            _zzm = _vlib("zigzag60_v2")
            nbf = _zzm.detect_newbar_mtf(idx, 60)
            bin_id = np.cumsum(nbf) - 1
            nb = int(bin_id[-1]) + 1
            h60 = np.full(nb, -np.inf); l60 = np.full(nb, np.inf)
            for i2 in range(len(H)):
                b2 = bin_id[i2]
                if H[i2] > h60[b2]:
                    h60[b2] = H[i2]
                if L[i2] < l60[b2]:
                    l60[b2] = L[i2]
            ms60 = ss_stoch_inertia(highpass48(momentum((h60 + l60) / 2.0, int(c["mom_len"]))),
                                    int(c.get("stoch_length", 20)))
            up_b = np.full(nb, -1, dtype=np.int64); dn_b = np.full(nb, -1, dtype=np.int64)
            last_u = last_d = -1
            for b2 in range(1, nb):
                if ms60[b2 - 1] <= -0.8 < ms60[b2]:
                    last_u = b2
                if ms60[b2 - 1] >= 0.8 > ms60[b2]:
                    last_d = b2
                up_b[b2] = b2 - last_u if last_u >= 0 else -1
                dn_b[b2] = b2 - last_d if last_d >= 0 else -1
            nn = len(H)
            m_up = np.full(nn, -1, dtype=np.int64)
            m_dn = np.full(nn, -1, dtype=np.int64)
            m_val = np.full(nn, np.nan)
            for i2 in range(nn):
                lb = int(bin_id[i2]) - 1                 # 直近の完了60分足（因果的）
                if lb >= 1:
                    m_up[i2] = up_b[lb]; m_dn[i2] = dn_b[lb]; m_val[i2] = ms60[lb]
            mtf_gate = {"mtf_since_up": m_up, "mtf_since_dn": m_dn, "mtf_val": m_val}
        # ★板の厚さゲートの材料（2026-08-02・既定OFF・ユーザーの発想の定式化）。
        #   imp = (H−L)/出来高（値幅あたり出来高の逆）。直近 win 本内の分位（因果的・時代非依存）。
        #   分位 < thick_lo ＝「出来高をこなしても動かない（吸収されている）」状態。
        #   台帳実測（work/candle_vol_ledger.py）＝下位20%の買い発火は ALL −28.6・MAE307、
        #   P1L −89.7・MAE366／P4L −29.0・MAE402 に集中。DT と独立（DT通過でも板厚だと +4.1）。
        # ★計算の要否は entries の局面別スイッチから自動判定（2026-08-02 採用・スイッチ化）
        _ent = getattr(self, "entries", {}) or {}
        _ext = getattr(self, "exits", {}) or {}
        _need_dt = (any(e.get("dt_filter") for e in _ent.values())
                    or any(e.get("div_alt_dt") for e in _ent.values())   # div の代替条件（2026-08-04）
                    or any(x.get("dt_stop") for x in _ext.values()))
        _need_thick = any(e.get("thick_filter") for e in _ent.values())
        thick_gate = {}
        if V is not None and _need_thick:
            _Va = np.asarray(V, dtype=float)
            with np.errstate(invalid="ignore", divide="ignore"):
                _imp = np.where(_Va > 0, (H - L) / np.maximum(_Va, 1e-9), np.nan)
            _tw = int(c.get("thick_win", 1000))
            thick_pct = (pd.Series(_imp).rolling(_tw, min_periods=_tw // 2)
                         .rank(pct=True) * 100).to_numpy()
            thick_gate = {"thick_pct": thick_pct}
        # ★ATR レジームゲートの材料（2026-08-02・既定OFF）。ATR14 の「直近 win 本内パーセンタイル」
        #   （0-100・因果的・固定閾値なし＝時代非依存）。台帳実測＝分位20%未満の発火は平均−6.0 の
        #   無価値層（work/tsi_atr_ledger.py）。
        atr_gate = {}
        if bool(c.get("atr_regime_on", False)):
            _w = int(c.get("atr_regime_win", 1000))
            atr_pct = (pd.Series(atr14).rolling(_w, min_periods=_w // 2)
                       .rank(pct=True) * 100).to_numpy()
            atr_gate = {"atr_pct": atr_pct}
        dt_gate = {}
        if _need_dt:
            # ★サブ確認をどちらにするか（2026-08-05・この戦略の未確定点）:
            #   sub_kind="dt"   … 生DT（原典 DTOSC）＝他の戦略と同じ
            #   sub_kind="mom2" … 2つ目のモメンタム（基軸より長い期間）。基軸と同じ機械に通し、
            #                     0〜100 に直してから「下から水準を上抜いた足」をサインとする。
            _sub = str(c.get("sub_kind", "dt"))
            _sl = int(c.get("sub_mom_len", 60))
            _mach = None
            if _sub == "mom2":            # 2つ目のモメンタム（差）
                _mach = momentum(hl2(H, L), _sl)
            elif _sub == "roc":           # ROC（変化率）を同じ機械に通す
                _mach = roc(C, _sl)
            elif _sub == "rsi":           # RSI 型（DoubleDT の基軸をサブに回す）
                _mach = pine_rsi(highpass48(hl2(H, L)), _sl)
            elif _sub == "mesa":          # MESA 型（Swing_Ride の基軸をサブに回す）
                _mach = highpass48(hl2(H, L))
            if _mach is not None:
                _m2 = ss_stoch_inertia(_mach if _sub in ("rsi", "mesa") else highpass48(_mach),
                                       int(c.get("stoch_length", 20)))
                sk = (np.asarray(_m2, dtype=float) + 1.0) * 50.0      # −1〜+1 → 0〜100
            elif _sub == "roc_raw":       # 生の変化率をそのまま（絶対的な大きさで見る）
                sk = np.asarray(roc(C, _sl), dtype=float)
            else:
                _dtm = _vlib("dt_raw")
                dtv = _dtm.dt_osc(C, int(c.get("dt_gate_rsi", 21)), int(c.get("dt_gate_stoch", 13)),
                                  int(c.get("dt_gate_sk", 8)), int(c.get("dt_gate_sd", 8)))
                sk = dtv["sk"]
            lvl = (float(c.get("sub_roc_level", -0.3)) if _sub == "roc_raw"
                   else float(c.get("dt_gate_level", 10.0)))
            nn = len(sk)
            su = np.full(nn, -1, dtype=np.int64)
            sd_ = np.full(nn, -1, dtype=np.int64)
            last = -1
            for i2 in range(1, nn):
                if not np.isnan(sk[i2]) and not np.isnan(sk[i2 - 1]) and sk[i2 - 1] <= lvl < sk[i2]:
                    last = i2
                su[i2] = i2 - last if last >= 0 else -1
            last = -1
            for i2 in range(1, nn):
                if not np.isnan(sk[i2]) and not np.isnan(sk[i2 - 1]) and sk[i2 - 1] >= 100 - lvl > sk[i2]:
                    last = i2
                sd_[i2] = i2 - last if last >= 0 else -1
            dt_gate = {"dt_since_up": su, "dt_since_dn": sd_}
        out = {"ms": ms, "cu": cu, "cd": cd, "dir60": dir60, "zhigh": zhigh, "zlow": zlow,
               "swing_high": swing_high, "swing_low": swing_low,
               "dn_bot_act": dn_bot_act, "dn_bot_ref": dn_bot_ref,
               "up_bot_K": up_bot_K, "up_top_K": up_top_K, "dn_top_K": dn_top_K,
               "bear_act": dv["bear_act"], "bull_act": dv["bull_act"], "hidden_act": dv["hidden_act"],
               "bull_leg": dv["bull_leg"], "hidden_leg": dv["hidden_leg"],
               "hill_bars": hill_bars, "peak_off": peak_off,
               "atr14": atr14, "ses_hi": ses_hi, "ses_lo": ses_lo, "d_seshi": d_seshi,
               "ref_low": ref_low, "ref_high": ref_high,
               "psl": psl, "psh": psh, "H": H, "L": L, "C": C,
               "O": (np.asarray(O, dtype=float) if O is not None else C)}
        out.update(wmas)
        out.update(dt_gate)
        out.update(mtf_gate)
        out.update(atr_gate)
        out.update(thick_gate)
        return out

    # ---- 板の厚さ（2026-08-02 ユーザー採用・局面別スイッチ）----
    #   「板厚」＝(高値−安値)/出来高 が直近 thick_win 本の中で小さい方から thick_lo % に入る状態
    #   （＝出来高をこなしても値が動かない・吸収されている）。
    def _thick_now(self, A, i) -> bool:
        if "thick_pct" not in A:
            return False
        v = float(A["thick_pct"][i])
        return (not np.isnan(v)) and v < float(self.cfg.get("thick_lo", 20.0))

    def _thick_ok(self, A, i, cell: str) -> bool:
        """入口: その局面の thick_filter スイッチが ON なら、板厚の発火は入らない。"""
        if not (self.entries.get(cell, {}) or {}).get("thick_filter"):
            return True
        return not self._thick_now(A, i)

    # ---- ATR レジームゲート（既定OFF。分位 < atr_regime_lo の低ボラ発火を filter/stop で扱う）----
    def _atr_regime_ok(self, A, i) -> bool:
        if "atr_pct" not in A or str(self.cfg.get("atr_regime_mode", "filter")) != "filter":
            return True
        v = float(A["atr_pct"][i])
        if np.isnan(v):
            return True
        return v >= float(self.cfg.get("atr_regime_lo", 20.0))

    # ---- DT（2026-08-02 ユーザー採用・局面別スイッチ）----
    #   「DT 発火が近い」＝生DT の SK が dt_gate_level を上抜いた足（買い側。売りは鏡像）が
    #   過去 dt_gate_k 本以内にあること。
    def _dt_pass(self, A, i, is_long: bool = True) -> bool:
        key = "dt_since_up"
        if key not in A:                       # スイッチ全OFF → 計算されていない＝制約なし
            return True
        v = int(A[key][i])
        return 0 <= v <= int(self.cfg.get("dt_gate_k", 3))

    # ---- 上位足位相ゲート（既定OFF。mtf_since_up ≤ k・単位は60分足本数）----
    def _mtf_gate_ok(self, A, i, is_long: bool = True) -> bool:
        key = "mtf_since_up"
        if key not in A or not bool(self.cfg.get("mtf_gate_on", False)):
            return True
        v = int(A[key][i])
        return 0 <= v <= int(self.cfg.get("mtf_gate_k", 6))

    # ---- サブ指標の「新しい発火」（エピソード封鎖 confirm 解除用。当バーで発火したか）----
    def _sub_fresh(self, A, i, is_long: bool = True) -> bool:
        if "dt_since_up" in A and int(A["dt_since_up"][i]) == 0:
            return True
        if "mtf_since_up" in A and bool(self.cfg.get("mtf_gate_on", False)) \
                and int(A["mtf_since_up"][i]) == 0:
            return True
        return False

    # ---- 上位足の天井圏除外（有害層の除去・局面限定）。買い＝ms60 > level で入らない／売りは鏡像 ----
    def _mtf_ceiling_ok(self, A, i, cell: str, is_long: bool = True) -> bool:
        cells = self.cfg.get("mtf_ceiling_cells") or []
        if "mtf_val" not in A or cell not in cells:
            return True
        v = float(A["mtf_val"][i])
        if np.isnan(v):
            return True
        lvl = float(self.cfg.get("mtf_ceiling_level", 0.8))
        return v <= lvl

    # ---- DT 入口フィルター（局面別スイッチ dt_filter）----
    def _dt_entry_filter_ok(self, A, i, cell: str, is_long: bool = True) -> bool:
        """入口: その局面の dt_filter スイッチが ON なら、DT 発火が k 本以内に無い発火は入らない。

        ★代替条件（2026-08-04 ユーザー採用・P1L）: DT の発火が遠くても、
          「当セッションの走行高値から dt_alt_pull_min〜dt_alt_pull_max ATR 下」で発火した
          ものは入る。＝浅すぎる押し（まだ押していない）と深すぎる押し（落ちるナイフ）を
          外し、ちゃんと押したが崩れてはいない位置だけを拾う。板厚の遮断は別ゲート
          （_thick_ok）のまま効くので、代替で拾う玉も板厚では入らない。
          4年 +143.2万（+1,034.1万→+1,177.3万）・PF1.78→1.83・最大DD −97.5万→−95.4万・
          最大の負け −22.2万のまま・−10万以下 15→16件。追加86件のうち78件は DT が完全に
          遠い側（13本超/未発火）＝利益のほぼ全部がそこから出る。DT を必須にすると
          追加7件・+11.0万しか残らない（P3L とは逆＝局面ごとに効く条件が違う）。
          台地＝下限0.9〜1.15・上限2.75〜3.5 で +124〜+143万（段差は下限0.85）。
          1年隠しテスト＝合計+122万・3勝1敗（2024 のみ −3万）。
          測定＝work/p1l_pickup.py・p1l_band_sweep.py（2026-08-04）。
        """
        e = self.entries.get(cell, {}) or {}
        if not e.get("dt_filter"):
            return True
        if self._dt_pass(A, i, is_long):
            return True
        if is_long and e.get("dt_alt_pull"):
            v = float(A["d_seshi"][i])
            if not np.isnan(v):
                lo = float(e.get("dt_alt_pull_min", 1.0))
                hi = float(e.get("dt_alt_pull_max", 3.0))
                if lo < v <= hi:
                    return True
        return False

    # ---- BT 高速パス ----
    def _session_gate(self, orders, ts):
        if session_lib is None or not getattr(self, "session_enabled", True) or ts is None:
            return orders
        fl = session_lib.flags(ts, self.interval)
        return session_lib.gate(orders, fl, self.position_size)

    # ---- ★V2 確認待ち（2026-08-03 採用・買い側のみ。セッションゲート後の注文列に適用）----
    #   発火足が「下降足」（high<=high[1] ∧ low<low[1]）なら発注せず監視し、
    #   「上昇足」（high>high[1] ∧ low>=low[1]）か「アウトサイド陽転」（包み足かつ陽線）が
    #   出た足で発注する。仕切り直し＝ms が band_long 以下へ再沈み / exit_band を上から割る。
    #   構造損切り＝待った玉（wait_stop="waited"・既定）は損切りを
    #   「押しの走行最安値 − wait_margin_atr×ATR14」へ（既存の損切りと損失が小さい方）。
    #   ★適用局面は entries の "wait"（採用＝P1L のみ true）。ショート側は未実装（S は未開発）。
    #   ★検証: 4年 +64.8万（+843.5万→+908.3万）・700円ストップ 11→9件・余白0〜0.5ATRは台地
    #     （work/wait_nolow_bt.py・work/p1l_wait_robust.py・2026-08-03）。
    #   ★測定ハーネス（wait_nolow_bt の Waiter）と同一の層・同一の順序で適用＝数値一致を担保。
    def _wait_gate(self, orders, A, i, ts):
        c = self.cfg
        # --- 構造損切り: 約定バーで幅を差し替え（発注足で確定した押しの安値基準）---
        if (self._v2_pend_level is not None and int(self.position_size) > 0
                and int(self.entry_bar) == i):
            if self._v2_pend_bar == i - 1:                 # 直前の足で発注した玉に限る（安全弁）
                lvl = (float(self._v2_pend_level)
                       - float(c.get("wait_margin_atr", 0.25)) * float(A["atr14"][i]))
                w = float(self.position_avg_price) - lvl
                if w > 0:
                    self._stop_pt = min(float(self._stop_pt or 1e9), w)
                    for od in orders:                       # 当バーの PSTOP も新水準に置き直す
                        if od.get("t") == "exit" and od.get("id") == "PSTOP":
                            od["stop"] = max(float(od["stop"]), float(self.position_avg_price) - w)
            self._v2_pend_level = None
        scope = str(c.get("wait_stop", "waited"))
        out = []
        entry_od = None
        for od in orders:
            if od.get("t") == "entry" and od.get("dir") == 1:
                entry_od = od
            else:
                out.append(od)
        L = A["L"]; H = A["H"]; ms = A["ms"]
        li = float(L[i]); hi = float(H[i])
        pl = float(L[i - 1]) if i >= 1 else li
        ph = float(H[i - 1]) if i >= 1 else hi
        if entry_od is not None:
            cell = str(entry_od.get("comment", "")).split()[0]
            w_on = bool((self.entries.get(cell, {}) or {}).get("wait"))
            # ★長大陰線（2026-08-03 ユーザー採用）: 発火足か1本前に「陰線かつ値幅が
            #   ATR14 の wait_bigdn_atr 倍以上」の足があれば、局面に関係なく確認待ちを発動。
            #   根拠＝裁量なら絶対に入らない場面（大陰線直後の買い）を機械にも入らせない。
            #   4年コスト＝2.5ATR で −5.3万（保険料）。0 で無効。
            bd = float(c.get("wait_bigdn_atr", 0.0) or 0.0)
            if not w_on and bd > 0:
                Cl = A["C"]; Oa = A["O"]; Ha = A["H"]; La = A["L"]; at = A["atr14"]
                for j in (i, i - 1):
                    if j >= 0 and float(Cl[j]) < float(Oa[j]) \
                            and (float(Ha[j]) - float(La[j])) >= bd * float(at[j]):
                        w_on = True
                        break
            fire_dn = (li < pl) and (hi <= ph)              # 発火足が下降足
            if w_on and fire_dn and int(self.position_size) == 0:
                self._v2_armed = True                       # 武装（見送り）。ドテンは待ち非対応＝即時
                self._v2_runmin = min(pl, li)               # 走行最安値は発火足の1本前から
                self._v2_cell = cell
            else:                                           # 即エントリー（従来どおり）
                out.append(entry_od)
                self._v2_armed = False
                if scope == "all":
                    self._v2_pend_level = min(pl, li)
                    self._v2_pend_bar = i
            return out
        if self._v2_armed:
            if int(self.position_size) > 0:
                self._v2_armed = False
            else:
                bl = float(c.get("band_long", -0.8))
                xb = float(c.get("exit_band", 0.8))
                redip = float(ms[i]) <= bl                  # 再沈み＝押しの継続
                missed = i >= 1 and float(ms[i - 1]) >= xb and float(ms[i]) < xb  # 一往復の終了
                if redip or missed:
                    self._v2_armed = False                  # 仕切り直し（次の発火で再開）
                else:
                    self._v2_runmin = min(self._v2_runmin, li)
                    up = hi > ph and li >= pl               # 上昇足
                    out_bull = (hi > ph and li < pl
                                and float(A["C"][i]) > float(A["O"][i]))  # 陽転の包み足
                    if up or out_bull:
                        od = {"t": "entry", "dir": 1, "qty": int(self.qty_per_entry),
                              "comment": self._v2_cell + " 確認"}
                        gated = self._session_gate([od], ts)
                        if gated:
                            out.extend(gated)
                            self.entry_kind = self._v2_cell
                            if scope != "off":
                                self._v2_pend_level = min(self._v2_runmin, li)
                                self._v2_pend_bar = i
                            self._v2_armed = False
        return out

    def precompute(self, df) -> dict:
        self.refresh_entries()                 # cfg を書き換えてから BT する掃引に追随する
        self._bt_ts = pd.DatetimeIndex(df.index)
        H = df["high"].to_numpy(float); L = df["low"].to_numpy(float)
        C = df["close"].to_numpy(float); idx = pd.DatetimeIndex(df.index)
        V = df["volume"].to_numpy(float) if "volume" in df.columns else None
        O = df["open"].to_numpy(float) if "open" in df.columns else None
        return self._compute_indicators(H, L, C, idx, V=V, O=O)

    def step(self, A, i) -> list[dict]:
        if i < 2:
            return []
        ts = self._bt_ts[i] if (self._bt_ts is not None and i < len(self._bt_ts)) else None
        orders = self._decide_at(A, i) or []
        orders = self._session_gate(orders, ts)
        return self._wait_gate(orders, A, i, ts)

    # ---- 局面のしきい値（entries[cell]["band"]。局面未確定は予備値へフォールバック）----
    def _cell_band(self, cell: str, is_long: bool = True) -> float:
        c = self.cfg
        dflt = float(c.get("band_long", -0.8))
        if not cell:
            return dflt
        try:
            return float(self.entries.get(cell, {}).get("band", dflt))
        except (TypeError, ValueError):
            return dflt

    # ---- 局面の入口条件（③FibSync / ④ダイバージェンス。どちらも既定OFF）----
    def _cell_pass(self, A, i, cell: str) -> bool:
        e = self.entries.get(cell, {})
        up_leg = int(A["dir60"][i]) == 1
        is_long = True                                   # この戦略はロング専用（2026-08-04）
        # ③ 押し・戻りの深さ（FibSync）。材料は脚と売買方向で自動選択:
        #    買い×上げ脚=押しの底打ち(K窓) / 買い×下げ脚=戻り底(hold版・新安値で無効化)
        #    売り×上げ脚=脚の頭打ち(K窓)   / 売り×下げ脚=戻りの頭打ち(K窓)
        if e.get("fib"):
            if is_long:
                ok = bool(A["up_bot_K"][i]) if up_leg else bool(A["dn_bot_act"][i])
            else:
                ok = bool(A["up_top_K"][i]) if up_leg else bool(A["dn_top_K"][i])
            if not ok:
                return False
        # ④ ダイバージェンス（買い=強気 / 売り=弱気。どちらも失効付き *_act）
        #   ★代替条件（2026-08-04 ユーザー採用・P3L）: ダイバージェンスが出ていなくても
        #     「DT（原典 DTOSC）の発火が dt_gate_k 本以内 ∧ ATR14 が div_alt_atr_max 円以下」
        #     なら入る。＝別のオシレーターも底を打ったと言っている発火だけを拾い足す。
        #     div で入っている玉（P3L 82件・PF2.24）はそのまま・追加は100件。
        #     4年 +132.2万（+901.9万→+1,034.1万）・PF1.75→1.78・最大の負け −22.2万のまま・
        #     −10万以下 15件のまま・最大DD −89.1万→−98.0万（42通りのスイープで −86〜−106万に
        #     ばらつく＝この幅は誤差）。1年隠しテスト＝3勝1敗・合計+117万（2023 のみ −18万）。
        #     ★ATR の上限は構造（大負けは高ボラで出る）＝110〜200円のどこで切っても
        #       最大の負け −22.2万・−10万以下15件で平ら。下限は台地が無いので付けない。
        #     測定＝work/p3l_pickup.py・p3l_pickup2.py・p3l_atr_sweep.py（2026-08-04）。
        if e.get("div"):
            ok = bool(A["bull_act"][i] if is_long else A["bear_act"][i])
            if not ok and is_long and e.get("div_alt_dt"):
                ok = self._dt_pass(A, i, True)
                amax = e.get("div_alt_atr_max")
                if ok and amax:
                    av = float(A["atr14"][i])
                    ok = (not np.isnan(av)) and av <= float(amax)
            if not ok:
                return False
        # ⑤ 小さな山の急さ（2026-08-01・既定OFF）。直前に完成した谷→頂点が
        #    hill_max_bars 本以内で作られた「急な山」のときだけ仕掛ける。
        #    ダラダラ作った山＝レンジの山を外すための条件（P1L の負けの正体）。
        if e.get("hill"):
            hb = int(A["hill_bars"][i])
            if hb < 0 or hb > int(self.cfg.get("hill_max_bars", 3)):
                return False
        # ⑥ 頂点からの位置で弾く（2026-08-01・既定 []＝無効）。block_off に入れた
        #    「頂点から何本後」で発火した玉を見送る。頂点は k 本後に確定するので
        #    判別できるのは k 本後以降だけ（それより前は結果でしか分からない）。
        bo = e.get("block_off")
        if bo:
            if int(A["peak_off"][i]) in {int(x) for x in bo}:
                return False
        # ⑦ 前セッション高値 PSH との位置（2026-08-01・既定 None＝無効）。
        #    "below"=PSH を超えていないときだけ / "above"=超えているときだけ。
        #    4年測定（P1L 素 417件）: PSH より下 221件 PF1.24・平均負け−4.9万・全年プラス、
        #    PSH より上 196件 PF1.22・平均負け−7.9万・2025マイナス＝負けの大きさが違う。
        ps = e.get("psh")
        if ps:
            above = float(A["C"][i]) > float(A["psh"][i])
            if (ps == "below" and above) or (ps == "above" and not above):
                return False
        # ⑧ 当セッション走行高値からの距離の上限（ATR倍・既定 None＝無効）。
        #    3ATR 以上下で買った 53件は PF0.65・−56.4万（4年中3年マイナス）＝深すぎる押しを外す。
        mx = e.get("max_hi_atr")
        if mx:
            v = float(A["d_seshi"][i])
            if not np.isnan(v) and v >= float(mx):
                return False
        # ⑨ 強気div の脚ラッチが立っていないこと（既定 False＝無効）。
        #    立っている179件 PF1.02 / 立っていない238件 PF1.39（div 分析 2026-08-01）。
        if e.get("no_bull_leg") and bool(A["bull_leg"][i]):
            return False
        # 旧 cell_filters（スクリプトからの明示指定のみ。config.json には置かない）
        for f in self.cfg.get("cell_filters", {}).get(cell, []):
            if f == "fib_bot" and not bool(A["dn_bot_act"][i]):
                return False
            if f == "fib_up" and not bool(A["up_bot_K"][i]):
                return False
            if f == "bull_div" and not bool(A["bull_act"][i]):
                return False
            if f == "bear_div" and not bool(A["bear_act"][i]):
                return False
            if f == "bull_leg" and not bool(A["bull_leg"][i]):
                return False
            if f == "hidden_leg" and not bool(A["hidden_leg"][i]):
                return False
            if f == "not_bear" and bool(A["bear_act"][i]):
                return False
            if f == "not_bull" and bool(A["bull_act"][i]):
                return False
        return True

    # ---- 決定（バー i のスカラを読む。on_bar/step 共通・評価順を保つ）----
    # 順序: ①signup → ②trend_state/phase4 → ③発火（振り子×局面×フィルター）→ 封鎖解除
    #       → ④エントリー → ⑤just_entered 記録 → ⑥PRSL → ⑥b REDIP/DIPLOW → ⑦FLIP
    #       → ⑧SE_PSL/PSH → ⑨タイムアウト → ⑨b ハードストップ → ⑩3Split。
    def _decide_at(self, A, i) -> list[dict]:
        c = self.cfg
        ms = A["ms"]
        orders: list[dict] = []
        d = int(A["dir60"][i])
        C_i = float(A["C"][i]); H_i = float(A["H"][i]); L_i = float(A["L"][i])
        size = int(self.position_size)
        prev = int(self._prev_size)

        # ============ ① signup（Latest トグル）============
        if bool(A["cu"][i]):
            self.signup = 1
        elif bool(A["cd"][i]):
            self.signup = -1

        # ============ ② trend_state（close ブレイク・sticky）と 4 区分 ============
        ts_fire_up = ts_fire_dn = False
        if i >= 1:
            sh = float(A["swing_high"][i]); sl = float(A["swing_low"][i])
            ts_fire_up = (d == 1 and not np.isnan(sh) and sh > 0 and C_i > sh)
            ts_fire_dn = (d == -1 and not np.isnan(sl) and sl > 0 and C_i < sl)
            if ts_fire_up and self.trend != TREND_UP:
                self.trend = TREND_UP
            elif ts_fire_dn and self.trend != TREND_DOWN:
                self.trend = TREND_DOWN
        phase4 = 0
        if self.trend == TREND_UP:
            phase4 = 1 if d == 1 else 2
        elif self.trend == TREND_DOWN:
            phase4 = 3 if d == -1 else 4

        # ============ ③ 発火（裸の振り子 × 局面 × フィルター）============
        # ★発火バンドは局面別（band_cells）。同一バーの前後2本を同じ band で比較する
        #   （Pine の ta.crossover に series を渡すと前バーは前バーの band で比較され、
        #     局面が変わった瞬間に定義が揺れるため、両言語とも「現バーの band」で明示比較する）。
        cells = self._cells_on
        cell_L = f"P{phase4}L" if phase4 else ""
        bl = self._cell_band(cell_L, True)
        xb = float(c.get("exit_band", 0.8))
        trig_L = i >= 1 and ms[i - 1] <= bl and ms[i] > bl      # 底圏からの折り返し
        under_i = i >= 1 and ms[i - 1] >= xb and ms[i] < xb     # 出口クロス

        base_L = (bool(cell_L) and (cell_L in cells) and self.signup == 1
                  and trig_L and self._cell_pass(A, i, cell_L))
        gate_L = (self._dt_entry_filter_ok(A, i, cell_L, True)
                  and self._mtf_ceiling_ok(A, i, cell_L, True) and self._atr_regime_ok(A, i)
                  and self._thick_ok(A, i, cell_L))
        sig_long = base_L and gate_L
        # ★エピソード封鎖（2026-08-02 ユーザー指示「潰すごとに次が出るのを、出なくする」）：
        #   ゲートで潰した発火は1本でなく「同じ押しから連発する次の発火」ごと封鎖する。
        #   解除＝gate_block: "cross"（決済クロス＝振り子の一往復でエピソード終端）／
        #        "confirm"（サブ指標の新しい発火＝確認が出たら再武装。決済クロスでも解除）／"off"
        if str(c.get("gate_block", "off")) != "off" and base_L and not gate_L:
            self._gate_blk_long = True

        # 封鎖の解除（出口クロス＝標準出口が決済したはずの瞬間。エントリー判定より先）
        if self._blk_long and under_i:
            self._blk_long = False
        # エピソード封鎖の解除（cross＝決済クロス／confirm＝サブ指標の新しい発火でも解除）
        _gb = str(c.get("gate_block", "off"))
        if self._gate_blk_long and (under_i or (_gb == "confirm" and self._sub_fresh(A, i, True))):
            self._gate_blk_long = False

        # ============ ④ エントリー（買いのみ・2026-08-04 ロング専用化）============
        # ★この戦略はロング専用（ユーザー確定 2026-08-04）。ショートは別戦略
        #   `Swing_Ride_Stochastic_Short` として一から条件を設計する。
        #   採用済みの条件（確認待ち・長大陰線・構造損切り・DT／板厚・各代替条件）はすべて
        #   買い専用に作り込んであり、同居させると建玉枠を奪い合ってロング側が測れなくなるため。
        #   ★ドテンも同時に廃止（反対サインが発火しないので、そもそも起こらなかった）。
        # 締切窓（block_new）の抑止は共有 session_lib の gate が担う。
        want_L = bool(sig_long) and not self._blk_long and not self._gate_blk_long
        if want_L and size == 0:
            self.entry_kind = cell_L
            orders.append({"t": "entry", "dir": 1, "qty": int(self.qty_per_entry),
                           "comment": cell_L})

        # ============ ⑤ just_entered → TP・PRSL・SE・タイムアウトの初期化 ============
        just_long = size > 0 and prev <= 0
        if just_long:
            # ★R 基準（2026-08-01 修正）。r_basis="swing"（既定）＝いま買った押しの底。
            #   "zz60"＝旧実装（脚の起点。上げ脚で R が膨らみ TP が届かない）。
            #   TP と PRSL は同じ水準を使う（対称）。
            if str(c.get("r_basis", "swing")) == "zz60":
                self.zz_p1 = float(A["zlow"][i])
            else:
                _ref = float(A["ref_low"][i])
                if np.isnan(_ref):                       # 山が未確定（先頭）→ 旧基準へ退避
                    _ref = float(A["zlow"][i])
                self.zz_p1 = _ref
            # R の下限＝ノイズ幅（ATR14 × r_min_atr）。押しの底が建値に近すぎるとき、
            # TP1 が建値同然になって1枚を無意味に投げるのを防ぐ。0 で無効。
            self._r_floor = float(A["atr14"][i]) * float(c.get("r_min_atr", 1.0))
            self._run_stop = np.nan; self._tp1_done = False; self._tp2_done = False
            self.tp1, self.tp2 = self._tp_targets()
            # SE 適格（建値 > PSL の玉だけ監視。★適格条件は絶対に外さない）
            se_enabled = bool(self._x("struct_exit", True))
            psl_e = float(A["psl"][i])
            self._se_ok = se_enabled and (not np.isnan(psl_e)) and self.position_avg_price > psl_e
            self._se_cnt = None
            # ★この玉のハードストップ距離を建てた時点で決める（2026-08-01・既定は共通値）。
            #   優先順: ①頂点からの位置別 hard_stop_off → ②局面別 hard_stop_cells → ③共通 hard_stop_pt。
            #   位置は発火足（約定バーの1本前）で読む。負けの大きさは位置ではなくストップが決めている
            #   （4年測定: どの位置でも平均負け −5.8〜6.8万・最悪は一律 −21万＝700円×3枚）ため、
            #   負けを小さくする操作はここに置くのが筋。
            self._stop_pt = float(self._x("hard_stop_pt", 0.0))   # 場面別 → 無ければ共通
            so = c.get("hard_stop_off") or {}
            sc = c.get("hard_stop_cells") or {}
            if sc and self.entry_kind in sc:                      # 旧キー（保全）
                self._stop_pt = float(sc[self.entry_kind])
            if so:
                po = int(A["peak_off"][max(i - 1, 0)])
                for _k in (f"{self.entry_kind}:{po}", str(po)):   # 局面指定が優先
                    if _k in so:
                        self._stop_pt = float(so[_k])
                        break
            # ★出口の浅い損切り（2026-08-02 採用・2026-08-03 整理で exits へ分離）。判定は
            #   発火足（約定バーの1本前）＝入口の時点で分かっている情報を出口の深さに使う。
            #   dt_stop … DT 発火が k 本以内に無い玉 → ハードストップを dt_stop_pt 円に浅くする
            #   （thick_stop は全局面未採用のため廃止・2026-08-03）
            _x_ent = self.exits.get(self.entry_kind, {}) or {}
            _j = max(i - 1, 0)
            if _x_ent.get("dt_stop") and "dt_since_up" in A and not self._dt_pass(A, _j, True):
                self._stop_pt = min(float(self._stop_pt or 1e9), float(c.get("dt_stop_pt", 300.0)))
            # ★ATR レジーム mode="stop"（検証済み不採用・既定OFFの保全機構）
            if "atr_pct" in A and str(c.get("atr_regime_mode", "filter")) == "stop":
                _v = float(A["atr_pct"][_j])
                if not np.isnan(_v) and _v < float(c.get("atr_regime_lo", 20.0)):
                    self._stop_pt = float(c.get("atr_regime_stop", 300.0))
            # タイムアウト走行極値
            self._to_hi = H_i; self._to_lo = L_i
            self._to_lo_best = L_i
        elif size == 0:
            # ★ランナー決済で建玉が空いたとき、出口クロスが来るまで新規を封鎖する（既定OFF）。
            #   封鎖しないと「ベースラインなら保有中で入れなかった別のトレード」が入り込み、
            #   ランナー方式そのものの良し悪しが見えなくなる（2026-07-08 に特定した再エントリー効果）。
            if bool(c.get("runner_block", False)) and self._run_armed and prev != 0:
                self._blk_long = True
            self._run_armed = False
            self.zz_p1 = np.nan; self.tp1 = np.nan; self.tp2 = np.nan
            self._se_ok = False; self._se_cnt = None
            self._stop_pt = None
            self._run_stop = np.nan; self._tp1_done = False; self._tp2_done = False
            self._to_hi = np.nan; self._to_lo = np.nan
            self._to_lo_best = np.nan
        else:
            self._to_hi = max(self._to_hi, H_i)
            self._to_lo = min(self._to_lo, L_i)
            self._to_lo_best = max(self._to_lo_best, L_i)

        # ※ 検証済み不採用だった出口（PRSL / REDIP / DIPLOW / FLIP）は 2026-08-04 に削除した。
        #    何をする機構で、なぜ採らなかったかは design/改善修正履歴/V1.md に残してある。

        # ============ ⑧ 構造損切り（受け入れ確認型・SE_PSL）============
        if size > 0 and self._se_ok:
            psl_i = float(A["psl"][i])
            if np.isnan(psl_i) or C_i > psl_i:
                self._se_cnt = None
            elif self._se_cnt is None:
                if C_i < psl_i:
                    self._se_cnt = 0
            else:
                self._se_cnt += 1
                if C_i < psl_i and self._se_cnt >= int(c.get("struct_exit_grace", 8)):
                    orders.append({"t": "close", "qty": None, "comment": "SE_PSL"})
                    self._blk_long = True
                    self._se_ok = False

        # ============ ⑨ タイムアウト撤退（動かない玉を時間で切る）============
        _to_on = self._x("timeout", None)
        if _to_on is None:
            _to_on = c.get("timeout_exit", True)
        if (bool(_to_on) and size > 0
                and self.bars_since_entry >= int(self._x("timeout_bars", 12))
                and not np.isnan(self._to_hi)):
            avg = self.position_avg_price
            pct = float(self._x("timeout_maxfe_pct", 0.1)) / 100
            req_floor = bool(c.get("timeout_require_no_floor", True))
            dead = self._to_hi < avg * (1 + pct)
            if dead and req_floor:
                dead = self._to_lo_best < avg
            if dead and not any(od.get("t") == "close" for od in orders):
                orders.append({"t": "close", "qty": None, "comment": "timeout"})

        # ============ ⑨a-2 ランナー（3枚目）決済 — 方式を総当たりで選べる（2026-08-01）============
        # 【背景】設計書では「残1枚＝反対閾値クロス（under/over）で成行全決済」（V7_7 §9.2）だが、
        #   別系統の設計書には「3枚目＝ランナー(トレーリング)」と書かれており文書が食い違っていた。
        #   過去のトレール検証（2026-04-30・2026-07-08）はどれも R が壊れていた頃のもので、
        #   R を「押しの底」基準に直した今は前提が変わっている＝全方式を測り直す。
        # 【方式】runner_mode: under(既定・従来) / atr / R / pct / struct / seslow / be / tp3
        #   runner_k     … 方式ごとの係数
        #   runner_arm_R … 含み益が arm×R を超えてから発動（0=常時）
        #   runner_size  … この枚数以下になったら発動（既定1＝3枚目だけ。2 で 2枚局面から）
        #   runner_with_under … true なら under/over も残す（早い方で決済）
        #   runner_block … ランナー決済のあと、出口クロスが来るまで新規を封鎖
        #                  （建玉枠が早く空いて別の玉が入る「再エントリー効果」を遮断する）
        rmode = str(c.get("runner_mode", "under"))
        if rmode != "under" and size > 0:
            avg = self.position_avg_price
            R = max(abs(avg - self.zz_p1), float(getattr(self, "_r_floor", 0.0) or 0.0))                 if not np.isnan(self.zz_p1) else np.nan
            k = float(c.get("runner_k", 1.0))
            arm = float(c.get("runner_arm_R", 0.0))
            rsize = int(c.get("runner_size", 1))
            if size <= rsize and not np.isnan(R) and R > 0:
                peak = self._to_hi
                armed = (arm <= 0) or (not np.isnan(peak) and (peak - avg) >= arm * R)
                lvl = np.nan
                if armed:
                    if rmode == "atr":
                        lvl = peak - k * float(A["atr14"][i])
                    elif rmode == "R":
                        lvl = peak - k * R
                    elif rmode == "pct":
                        lvl = peak * (1 - k / 100.0)
                    elif rmode == "struct":
                        lvl = float(A["ref_low"][i])
                    elif rmode == "seslow":
                        lvl = float(A["ses_lo"][i])
                    elif rmode == "be":
                        # 段階引き上げ: TP1 約定後(2枚)=建値 / TP2 約定後(1枚)=TP1 の水準
                        done2 = size <= max(self.qty_per_entry - 2, 1)
                        lvl = (self.tp1 if (done2 and not np.isnan(self.tp1)) else avg)
                    elif rmode == "tp3":
                        t3 = avg + k * R
                        orders.append({"t": "exit", "id": "TP3", "qty": None, "limit": t3, "comment": "TP3"})
                if not np.isnan(lvl):
                    # ラチェット（一度上げた線は下げない）
                    self._run_stop = lvl if np.isnan(self._run_stop) else max(self._run_stop, lvl)
                    px = self._run_stop
                    ok_ = px < float(A["C"][i])
                    if ok_:                       # 既に割れている線は出さない（次バー成行と等価になるため）
                        orders.append({"t": "exit", "id": "RUNSTOP", "qty": None, "stop": px,
                                       "comment": "RUNSTOP"})
                        self._run_armed = True

        # ============ ⑨b 円建てハードストップ（既定 700円・PSTOP・イントラバー）============
        # ★設計の最重要目標「1回の負けを30〜50万に膨らませない」の実装。建値から hard_stop_pt 円
        #   逆行の位置に残玉全量の stop 注文。3枚×700円=−21万が上限（ギャップ余地込み実測 −25.5万）。
        #   600〜800円は成績の台地＝700は過適合の1点ではない。発火は4年38回（トレードの4%）。
        # ★0 は「損切り幅なし」＝有効な指定。`or` で共通値に落とさない（2026-08-05 修正）
        _sp = getattr(self, "_stop_pt", None)
        hs = float(_sp if _sp is not None else c.get("hard_stop_pt", 0.0))
        if hs > 0 and size > 0:
            px = self.position_avg_price - hs
            orders.append({"t": "exit", "id": "PSTOP", "qty": None, "stop": px, "comment": "PSTOP"})

        # ============ ⑩ 3Split エグジット（TP1/TP2 指値 再配置 ＋ 出口クロス全決済）============
        if size > 0:
            if not np.isnan(self.tp1):
                orders.append({"t": "exit", "id": "TP1_L", "qty": 1, "limit": self.tp1, "comment": "TP1_C"})
            if not np.isnan(self.tp2):
                orders.append({"t": "exit", "id": "TP2_L", "qty": 1, "limit": self.tp2, "comment": "TP2_C"})
            # 3枚目の決済しきい値は場面別に持てる（指定が無ければ共通の exit_band）
            _xbc = float(self._x("exit_band", 0.8))
            under_c = under_i if _xbc == xb else (i >= 1 and ms[i - 1] >= _xbc and ms[i] < _xbc)
            if under_c and (rmode == "under" or bool(c.get("runner_with_under", True))
                            or size > int(c.get("runner_size", 1))):
                orders.append({"t": "close", "qty": None, "comment": "under"})

        self._prev_size = size
        return orders

    # ---- live: 確定足ごと（バッファ再計算 → 決定。BT高速パスと同一結果）----
    def on_bar(self, bar) -> list[dict]:
        self._ts.append(bar.ts); self._o.append(bar.open); self._h.append(bar.high)
        self._l.append(bar.low); self._c.append(bar.close)
        self._v.append(float(getattr(bar, "volume", 0.0) or 0.0))
        if len(self._c) > self.W:
            self._ts.pop(0); self._o.pop(0); self._h.pop(0); self._l.pop(0); self._c.pop(0)
            self._v.pop(0)
        if len(self._c) < 3:
            return []
        H = np.asarray(self._h, float); L = np.asarray(self._l, float); C = np.asarray(self._c, float)
        O = np.asarray(self._o, float)
        V = np.asarray(self._v, float)
        A = self._compute_indicators(H, L, C, pd.DatetimeIndex(self._ts), V=V, O=O)
        i = len(C) - 1
        ts = getattr(bar, "ts", None)
        orders = self._decide_at(A, i) or []
        orders = self._session_gate(orders, ts)
        return self._wait_gate(orders, A, i, ts)


# 互換エイリアス（旧名で参照する測定スクリプト・旧ランナーが動くように）
MESA_TrendSplit = Swing_Ride_Stochastic
MESA_Stochastic = Swing_Ride_Stochastic


def build():
    return Swing_Ride_Stochastic()
