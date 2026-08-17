> ⚠️ **【統合済・履歴】本ドラフトは 2026-06-14 に正本 [`N225LocalEngine_詳細設計書.md`](N225LocalEngine_詳細設計書.md) へ統合・置換されました。** 設計判断は正本を参照。本書は履歴として残置（正本の鎖・ライフサイクル・昇格関門は正本 §1,§8 に反映）。

# 戦略ライフサイクル標準（Pine→Python→BT→昇格→登録）設計書 v0.1【ドラフト・統合済】

> 状態：**設計フェーズ・ドラフト**。レビュー → 合意 → MESA で実証 → 確定、の順で進める。
> 位置づけ：本書はローカル版の**最上位ルール（正本）**。`local_engine_design.md`（エンジン/ダッシュボード）は本標準の"出力（マニフェスト）"を消費する側。
> 確定方針（2026-06-13 ユーザー）：**最上級の MESA を最初の参照実装**として本標準で実証する。**現行 MESA（バッチ）は無傷で残し、別フォルダに on_bar 版を作る**。バッチと一致しなければ採用しない／再考する。狙い＝**全戦略を一つのルールのエンジンで動かす（将来価値）**。

---

## 正本（しょうほん）の定義 ★最重要・全章の前提
戦略開発の本体は **Python**（開発・バックテスト）。Pine/TradingView は最終の実行先（戦略開発ガイド `N225StrategyBuilder/docs/strategy_development_guide.md` §1–§3・§7 で確認）。正しさの鎖：
```
TradingView Pine コード   ＝ 一次正本（実際にTVで動く・アーカイブ・ガイド§6.4）
        ≡（同一でなければならない）
Python 戦略（検証済バッチ）＝ Pine に較正済みの忠実な等価物 ＝ ゆえに Python も正本
        ≡（4年・全トレード・PnL でビット一致を検証）
ローカル on_bar 版         ＝ Python と一致して初めて採用
```
- **Pine ≡ Python ≡ ローカル on_bar**。ローカル版が勝手に正本になるのではなく、**Pine正本に連なる等価物**として正しさを担保する。
- 技術的事実：Pine(TV) と Python は約定の細部（手数料/スリッページ/バー確定）まで完全一致しない（ガイド§7）。**ロジックは厳密同一、約定モデルは Python を TV に較正**（`next_bar_open_fills`・[[feedback_python_bt_vs_tv_optimistic]]）。＝「Python も正本」＝**較正済みでPineと整合した状態を維持**する意味。
- ローカル版の検証ターゲット＝**Python golden（＝Pine等価物）**。on_bar はこれにビット一致。
- ★ローカル版は **Pine/TV を経由しない**（全ローカル）。Pineは"上流の一次正本"として外に在るだけ。

---

## 0. なぜ"流れ全体"をルールにするのか
これまで戦略ごとに開発・BT・スクリプトが**バラバラ**（`backtest()` / `run_strategy()` / `simulate_v3()` … 35戦略が各々別物）。このまま増やすと**辻褄の合わないシステム**になる。
→ **既存の検証済みPython戦略 → ローカル実行形(on_bar)化 → 自分のバッチBTと一致検証 → 昇格 → システム登録** の一連を、各段の入口・出口・関門まで標準化する。これが本書。
※入口は「Pineコード」ではなく**既存のPython戦略**（開発・BTの成果物）。Pine変換はTradingView版だけの経路で、ローカル版のループには入らない。

**辻褄を合わせる核心：** ①移植標準により **バックテストしたコード(on_bar)がそのまま実機で動く**＝BTと実機が乖離しない。②全戦略が**同一のBTハーネス・同一のマニフェスト**を通る＝ad-hoc が入り込めない。

---

## 1. 戦略ライフサイクル全体図
```
[戦略開発] 既存の2手法(方法A新規/方法B改造)で Python開発＋BT → Pine変換しTV登録   ← 既に完了・TV版の経路
   │  成果物 = 検証済みPython戦略(バッチ・golden) ＝ Pine正本の較正済み等価物
   ▼  ★ローカル版で作るのはここから
① on_bar化  既存Python戦略 → ローカル実行形(on_bar)（on_bar骨格 ＋ 逐次ヘルパー）
              出力 = 規約準拠の戦略モジュール（on_bar を実装）
   ▼
② BT     共通BTハーネス（全戦略を同じ1本のツールで回す）＋ golden とビット一致検証
              出力 = 標準レポート（PF / 年別 / 取引数 / 平均保有 / DD …固定様式）
   ▼
③ 昇格   昇格関門（ガイド§7の合格基準）を満たすか判定
              ✗ → 棚上げ（記録は残す）   ✓ → 戦略マニフェスト確定
   ▼
④ 登録   マニフェスト → カタログ/エンジン/ブリッジ登録 → ダッシュボードで ON/OFF 運用
※Pine/TVは経由しない（ローカル版は全ローカル）。
```

---

## 2. ①on_bar 標準（既存Python戦略の逐次実行規約）

> 対象は**既存の検証済みPython戦略**を「1バーずつ動く on_bar 形」に表すこと。元の Pine も Python も本来 **1バーずつ評価**の構造（Pineは元来バー単位、Pythonバッチは for ループで潰しているだけ）。その構造を活かして on_bar 化し、**自分のバッチBT(golden)と一致**させる。

### 2.1 戦略コントラクト
```python
class Strategy(Protocol):
    name: str               # 一意。ブリッジ登録名（例 "mesa_local"）
    interval: int           # 足の分（15 等）
    warmup_bars: int        # 判断に必要な最小連続本数（指標ルックバック／MESA系=300）
    def reset(self) -> None: ...                       # 状態初期化（BT開始時・再起動時）
    def on_bar(self, bar: Bar) -> list[FillEvent]: ... # 確定足ごと。内部状態は次バーへ持ち越し（Pineの[1]）
```
- **状態（state）は戦略インスタンスが保持**（前バー値・建玉・signup 等）。`on_bar` は「1本の確定足」を受け、必要な指標更新・エントリー/エグジット判定をして**この足で発生した約定イベント**を返す。
- **入力はOHLCのみ**を原則（指標は戦略内部で計算）。重い共有指標はエンジンが1回計算して渡す最適化は可（§後述・MESA一族のみ）。

### 2.2 約定イベント（FillEvent）＝送出/集計の共通プリミティブ
既に実証済みの `StreamingV78Exit` / `bridge_sender` の形に合わせる：
```python
@dataclass
class FillEvent:
    reason: str        # "ENTRY" / "TP1" / "TP2" / "exit" / "dohten" 等
    direction: str     # "Long" / "Short"
    qty: int           # 枚数（3Split は 1 枚ずつ）
    price: float       # 約定価格（成行=始値, 指値=TP価格 等）
    ts: datetime
```
- **なぜ target_pos でなく FillEvent か**：MESA の TP1/TP2 は**イントラバー指値**で、整数の目標ポジだけでは表せない。`bridge_sender` は既に FillEvent からポジション遷移を内部計算する（実証済み）。よって**FillEvent を一次プリミティブ**にする。

### 2.3 Pine→Python 対応・規約（テンプレートの中身）
| Pine | Python（逐次） | 備考 |
|---|---|---|
| スクリプト全体＝1バー1回 | `on_bar(bar)` 1呼び出し | 構造を保つ |
| `x[1]`（前バー参照） | 戦略インスタンスの `self.prev_*` | 状態として持ち越し |
| `ta.crossover/sma/atr/rsi` 等 | **Pine互換ヘルパー**（逐次更新） | 半分既存（`feature_engine_py/pine_port.py`, `python_engine/zigzag.py::ZigZagState`, `pivots.py::PivotArray`） |
| `strategy.entry/exit` | `FillEvent` を返す | 約定はエンジン/ブリッジ側 |
| barstate.isconfirmed | **確定足のみ処理**（先読み禁止） | 未確定の次バーを見ない |
- **先読み禁止（不変条件）**：判断は**確定済みバーまで**の情報だけ。
- ★**約定モデル規約（2026-06-13 確定）**：ローカル版は**実機Pineの `process_orders_on_close` に一致**させる。
  - Pine `process_orders_on_close=false`（既定・**全戦略の23/25**）⟺ Python `next_bar_open_fills=True`（**次バー始値約定**）。
  - Pine `process_orders_on_close=true`（2/25 のみ）⟺ Python `next_bar_open_fills=False`（シグナルバー終値約定）。
  - **MESA V7_8 の実機Pineは `process_orders_on_close=false`＝次バー始値**。よって golden は **`next_bar_open_fills=True`**（旧 False は誤較正・撤回）。再ベースライン値＝**588トレード/PF2.400/+109,270pt**（[[project_bar_close_execution_model]]／[[feedback_python_bt_vs_tv_optimistic]] と一致）。
  - 取り込み時、各戦略の Pine を本パラメータで確認し、golden をそのモデルで再ベースラインしてから on_bar 化する。

### 2.4 移植テンプレート（雛形）
- **アダプタ雛形（コード）**：`Strategy` を実装する骨格1ファイル。新戦略はこれを埋める。
- **レシピ（設定）**：MESA一族（オシレーター＋Config違い）は **JSON で生成**（コード不要・利用者も微調整可）。
- 既存 `N225StrategyBuilder/strategies/_TEMPLATE`（Pine開発雛形）に、本ランタイム雛形を追加する形で拡張。

---

## 3. ②共通BTハーネス（1本に集約）
- **役割**：任意の `Strategy`(on_bar) を**履歴バーでループ実行**し、返る FillEvent を集計して**標準レポート**を出す。＝戦略ごとのBTスクリプト乱立を解消。
- **BT＝実機と同一コード**：ハーネスは on_bar をループするだけ。実機エンジンは同じ on_bar をライブ足で呼ぶ。→ 乖離なし。
- **約定シミュ**：FillEvent を OHLC に対して標準ルール（次バー始値／イントラバー指値）で約定させ、トレード列を構築。較正フラグは戦略マニフェストに持つ。
- **標準レポート（固定様式）**：PF・総PnL・期待値・取引数/年・平均保有時間・最大DD・**年別内訳**・コスト感度（0/5/10pt）。
- **権威ある数字**：新戦略＝本ハーネス。既存検証済み（MESAバッチ等）＝そのゴールデンバッチ（[[feedback_python_4y_is_authoritative]]）。

---

## 4. ③昇格関門（既存ルールを流用・新設しない）
**数値基準＝戦略開発ガイド §7**（`strategy_development_guide.md`）に明示的に揃える：
- PF ≥ 1.5（優秀 ≥ 2.0）／勝率 ≥ 45%（≥ 55%）／取引数 ≥ 30（≥ 50）／OOS-TRAIN PF比 ≥ 0.5（≥ 0.7）／最大DD ≤ 20,000pt（≤ 10,000pt）。
- **取り込み前チェック（正本整合）**：そのPythonが**現行Pine正本と整合（較正済み）か**を確認してから on_bar 化する（[[reference_history_csv_quality]]／[[feedback_python_bt_vs_tv_optimistic]]）。
加えて運用上の必須：
- **4年以上のBT必須**（[[feedback_long_term_bt_required]]）。半年で良成績は過適合疑い。
- **デイトレ/15分・年間取引数と平均保有を必ず提示**（[[feedback_daytrade_15min_frequency]]）。
- **約定モデル較正**（[[feedback_python_bt_vs_tv_optimistic]]）。`next_bar_open_fills` 較正値を踏襲。
- **3枚立て1枚ずつ返済**（[[feedback_3split_base_design]]）。
- **まず平易なトレード記述**（[[feedback_strategy_plain_spec_first]]）＝回数×エッジ/必要資本で実用判定。
- 関門 ✓ → マニフェスト確定。✗ → 棚上げ（devlog/戦略フォルダに記録、否定しない）。

---

## 5. ④戦略マニフェスト・登録
全戦略が必ず出す**1枚の契約**。エンジン・ブリッジ登録・ダッシュボードは**これだけを読む**。
```json
{
  "name": "mesa_local",
  "module": "N225LocalEngine.strategies.mesa_local:MesaLocal",
  "interval": 15,
  "warmup_bars": 300,
  "fill_model": {"next_bar_open_fills": true},
  "params": { "...": "戦略固有(レシピ含む)" },
  "backtest_report": "reports/mesa_local_4y.json",
  "status": "promoted"
}
```
- **レジストリ（カタログ）**＝昇格済みマニフェストの集合。ダッシュボードはこれを一覧表示し、登録/ON-OFF する。
- **ブリッジ登録名**は本 `name` と一致（既存 strategies.json 連携）。

---

## 6. MESA 参照実装（本標準の実証・第一号）
### 6.1 方針
- **現行 MESA（`simulate_v3` バッチ・4年較正）は無傷で温存**＝ゴールデン基準。
- **別フォルダに on_bar 版 `mesa_local` を新規作成**（例 `N225LocalEngine/strategies/mesa_local/`）。
- 構成＝**入口の状態機械を on_bar 移植**（signup 武装→発火・ZZ60 6フェーズ・allow_long/short ゲート・fib sync・バンド）＋**既存 `StreamingV78Exit`（出口・588/588検証済み）を結合**。
### 6.2 成功基準（不変条件）
- 共通BTハーネスで4年実行し、**ゴールデンバッチ `simulate_v3`(LIVE config) と 全トレード・PnL がビット一致**。
- 一致 → 本標準を確定し、以後全戦略へ適用。**不一致 → 採用せず原因を詰めるか方針再考**（ユーザー方針）。
### 6.3 既存資産
- 出口＝`N225StrategyAI/clone/inference/exit_manager.py::StreamingV78Exit`（流用）。
- 指標逐次化の素材＝`feature_engine_py` / `python_engine`（ZigZagState/PivotArray）。
- ゴールデン＝`N225StrategyBuilder/strategies/MESA_Stochastic/python/simulate_v7_8_fib_v3_split.py`。

---

## 7. 既存戦略の扱い・段階計画
- **既存検証済み戦略は破壊しない**（[[feedback_no_unilateral_cleanup]]）。golden を残し、on_bar 版は**別フォルダの新実装**として並走・検証。
- **新戦略は最初から on_bar 標準**で書く（移植時にテンプレを埋める）。
- 段階：
  - **S1**：本標準を確定ドラフト化（本書）。
  - **S2**：MESA `mesa_local` を on_bar 移植（入口移植＋検証済み出口結合）。
  - **S3**：共通BTハーネスで golden と**ビット一致検証**（成功基準）。
  - **S4**：成功なら標準確定 → マニフェスト/レジストリ → エンジン/ダッシュボードが消費（`local_engine_design.md` を整合）。
  - **S5**：2戦略目以降を同フローで展開。

---

## 8. 未決事項（レビューで詰める）
1. **実機の約定フィデリティ**：イントラバー指値（TP1/TP2 を指値注文でブリッジへ）か、検出バーで成行近似か。BTハーネスは golden 一致のためイントラバー指値を再現するが、**実機側の注文方式**を別途決める（現クローンは成行近似）。
2. **指標の逐次計算 vs バッファ再計算**：on_bar 内で増分更新（速い・Pine忠実）か、毎バー直近バッファから再計算（実装容易・クローンAIの現方式）か。MESA移植で実地に選ぶ。
3. **配置**：`N225LocalEngine/strategies/<name>/` に統一するか、各 `N225StrategyBuilder/strategies/<name>/` 配下に `live/` を足すか。
4. **レシピ DSL の範囲**：オシレーター種別・Config のどこまでを JSON 化するか。

## 改訂履歴
- v0.1（2026-06-13）：初版ドラフト。Pine→Python→BT→昇格→登録の一連を標準化。on_bar規約（FillEvent一次）・共通BTハーネス・昇格関門（既存ルール流用）・戦略マニフェスト/レジストリ・MESA参照実装（golden温存・別フォルダ・ビット一致が成功基準）・段階計画。**レビュー待ち**。
