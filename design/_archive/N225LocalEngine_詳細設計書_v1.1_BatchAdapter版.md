# N225LocalEngine 詳細設計書（正本 v1.0）

> 状態：**正本（authoritative）**。2026-06-14、3つのドラフト（`strategy_lifecycle_standard.md` / `local_engine_design.md` / `strategies/mesa_local/PORT_SPEC.md`）をユーザーとの設計確認を経て**本書に統合**した。以後ローカル版の設計判断は本書を唯一の基準とする（旧3ドラフトは履歴として残置・冒頭に「本書へ統合」の銘）。
> 親方針：N225TradingSystem を「**TradingView版**（外部・既存）」と「**ローカル版**（全ローカル・新規＝本書）」の2系統に分ける。

---

## 0. 確定した設計判断（サマリ・全章の前提）

| # | 判断 | 内容 |
|---|---|---|
| D1 | **別製品・コード共有禁止** | TV版とローカル版は個別販売の別製品。ローカル版 `N225LocalEngine` は**自己完結**。TV版コード（`n225_brokerbridge_dashboard.py` 等）を import しない。資産は**コピー（ベンダリング）して同梱**。[[project_localengine_separate_product]] |
| D2 | **ブリッジ結合は Webhook プロトコルのみ** | `POST localhost:8001/webhook`（確定フォーマット＝`N225BrokerBridge/docs/webhook-api-spec.md` v1.0.0）。ブリッジは別製品。HTTP 疎結合＝コード共有でない＝可。 |
| D3 | **実装方式＝BatchStrategyAdapter** | 検証済みバッチ（`simulate_v3` 等）を**無改造でコピー同梱**し、`on_bar` から毎足回す。on_bar への新規再移植（旧 PORT_SPEC の StreamingMesaV783）は**不採用**（second copy 同期地獄を避ける）。BT≡実機が構造的に保証。 |
| D4 | **戦略↔エンジンの一次プリミティブ＝PositionState** | 戦略は `on_bar(buffer) → PositionState(market_position, size)` を返すだけ。FillEvent でなく**目標ポジション（枚数つき）**。価格・執行はブリッジ。＝旧 standard §2.2(FillEvent) と design §3.1(target_pos) の対立を、確定 webhook フォーマットに合わせ **PositionState** で解決。 |
| D5 | **送出＝注文枚数＋売買シグナル** | エンジンはポジション遷移を webhook 化（spec §9 遷移表）。`order_price=0`、**対等価格(指値)はブリッジが決定**。3Split の1枚返済＝部分返済(size 3→2→1→0)で表現。 |
| D6 | **時間足は当面 15分足のみ固定** | 将来 他足を拡張。今は 15分戦略だけ。既存 `OHLCManager`(15分) をそのまま使用。 |
| D7 | **既定は順次実行・並列は opt-in** | デバッグ容易・決定的・レース無し。戦略を独立設計＋実行部を executor seam に抽象化し、将来 `sequential→ThreadPool→ProcessPool` を**戦略コード無改造で**切替可能。 |
| D8 | **外回りは既存を流用（8〜9割完成）** | tick受信/足生成/蓄積/warmup/セッション/送出は `N225StrategyAI/clone/feed,live` に as-built。**コピー同梱**して使う。 |
| D9 | **ダッシュボードは TV版と別の独立1枚** | ローカル版専用。`blog_Bridge_dashboard.py` は参考コピー元のみ（import 共有しない）。 |
| D10 | **採用条件＝golden ビット一致** | 各戦略の on_bar 経路が、検証済みバッチ golden と4年・全トレード・PnL でビット一致して初めて採用。MESA を第一号で実証。 |

---

## 1. 正本（しょうほん）の鎖 ★最重要の前提

```
TradingView Pine コード      ＝ 一次正本（実際にTVで動く・アーカイブ）
        ≡（同一でなければならない）
Python 戦略（検証済バッチ）   ＝ Pine に較正済みの忠実な等価物 ＝ ゆえに Python も正本（golden）
        ≡（4年・全トレード・PnL でビット一致を検証）
ローカル版 on_bar（本エンジン）＝ golden と一致して初めて採用
```
- ロジックは厳密同一、約定モデルは Python を Pine に較正（`next_bar_open_fills`・実機 Pine の `process_orders_on_close` に一致）。[[feedback_python_bt_vs_tv_optimistic]]
- ローカル版は **Pine/TV を経由しない**（全ローカル）。Pine は上流の一次正本として外に在るだけ。
- 検証ターゲット＝**Python golden**。BatchStrategyAdapter は「同じバッチ関数を呼ぶ」ので、構造的に golden と一致する（D3）。

---

## 2. 全体アーキテクチャ

```
┌───────────────────────────────┐
│ ローカル版ダッシュボード(独立・新規) │  制御:登録/起動停止/戦略ON-OFF  監視:ログ/LED
└───────────────┬───────────────┘
                │ 制御・状態(JSON)
                ▼
  kabu Station ──tick──► N225BrokerBridge(別製品) ──AiTickForwarder(TCP5000)──►  ┌──────────────────────┐
        ▲                                                                        │  ローカルエンジン(中核) │
        │ POST localhost:8001/webhook（確定フォーマット）                          │  ヘッドレス・15分      │
        └──────────────── BridgeSender ◄──────────────────────────────────────── │                      │
                  対等価格(指値)で執行                                              └──────────┬───────────┘
                                                                                              │
   tick(TCP5000)→ LiveFeed → OHLCManager(on_bar_close 15分) → OHLCStorage(get_latest/is_bar_completed)
                                              │ on_bar_close（確定足1本）
                                              ▼
                            run_one_step：各有効戦略.on_bar(buffer) → PositionState
                                              → prev との差分 → webhook(spec §9) → BridgeSender
```
- 足生成・蓄積・送出は**全戦略共通の外回り**（既存 `clone/feed,live` をコピー同梱）。
- 戦略は「足バッファを受け、目標ポジションを返す」だけ。中身（ルール戦略/AI）はエンジンから不可視。
- 発注の最終可否・価格・分割執行はすべて**ブリッジ**（別製品）。

---

## 3. ★中核：Python 戦略 ↔ エンジン 結合ロジック（本書の心臓部）

### 3.1 戦略コントラクト（Protocol）
```python
@dataclass
class Bar:
    ts: datetime; open: float; high: float; low: float; close: float; volume: float

@dataclass
class PositionState:
    market_position: str   # "flat" | "long" | "short"  ← 今こうありたい
    size: int              # 枚数 (3Split: 3/2/1/0)

class Strategy(Protocol):
    name: str              # = webhook の alert_name（ブリッジ登録キー）。一意。
    interval: int          # 15（当面固定）
    warmup_bars: int       # 連続最小本数（MESA系=300）
    def reset(self, mode: str) -> None: ...                  # "live"/"backtest" 初期化（モードで切替＝BT≡実機）
    def on_bar(self, buffer: pd.DataFrame) -> PositionState: ...  # 確定足ごと。buffer=直近warmup以上の確定足(古→新)
```
- **状態は戦略インスタンスが保持**（前バー値・建玉・signup 等）。
- **戦略は webhook を知らない**。返すのは「今の目標ポジション」だけ。webhook 生成・prev 管理は**エンジン側**（spec §9 を唯一の実装に集約）。
- 戦略は**独立**（自分の状態＋読み取り専用 buffer のみに依存）＝順次でも並列でも同一結果（D7）。

### 3.2 BatchStrategyAdapter（既存バッチを contract に載せる・D3 の実体）
検証済みバッチを**書き換えず**、毎足バッファ全体で回し、確定足の建玉を `PositionState` で返す：
```python
class BatchStrategyAdapter(Strategy):
    def __init__(self, name, interval, warmup_bars, build_input_fn, batch_fn, cfg):
        # build_input_fn(raw_buffer) → batch_fn が要る入力(指標済みdf / list-of-dict / +外部データ)
        # batch_fn(input, cfg) → fills_df（検証済みバッチ。例 simulate_v3）
        ...
    def on_bar(self, buffer) -> PositionState:
        inp   = self.build_input_fn(buffer)          # 生足→戦略入力（指標を毎足再計算）
        fills = self.batch_fn(inp, self.cfg)         # 検証済みバッチをそのまま実行（無改造）
        pos   = reconstruct_position_at_last_confirmed_bar(fills, inp)  # 確定足での建玉(枚数)を復元・先読み防止
        return PositionState(*pos)
```
- **戦略ごとに違うのは `build_input_fn` と `cfg` だけ**（多様性をここに閉じ込める。[[project_three_strategy_roadmap]] の各戦略は build_input が「オシレーター差替」程度）。
- **約定モデル較正値**（`next_bar_open_fills=True` 等）は cfg で戦略ごとに踏襲（[[feedback_python_bt_vs_tv_optimistic]]）。
- **先読み防止（不変条件）**：最終足は「未確定の次バー始値約定」を含めず、**確定済みバーまでで建玉判定**。
- 新規戦略は BatchStrategyAdapter を使わずネイティブ `on_bar` で書いてもよい（同じ contract）。

### 3.3 run_one_step（足確定→全戦略→送出。エンジン中核）
```
on_bar_close(確定足):                 # OHLCManager のコールバック
  buffer = storage.get_latest()       # 直近の確定足（≥warmup）
  if len(buffer) < max(warmup_bars):  # warmup ソフトゲート（300）
      return                          # 発注抑止（安全側）
  results = executor.map(strategies,  # ★既定=順次 / opt-in=ThreadPool（D7）
                lambda s: (s, s.on_bar(buffer)))
  for (s, cur) in results:
      webhook = position_diff_to_webhook(s.prev, cur, s.name, s.interval)  # spec §9 遷移表（唯一の実装）
      if webhook and dashboard.is_enabled(s.name):  # ダッシュボードの ON/OFF
          bridge_sender.post(webhook)               # POST localhost:8001
      s.prev = cur
```
- **executor は1か所の seam**：`SequentialExecutor`（既定）/ `ThreadPoolExecutor`（opt-in）/ 将来 ProcessPool。戦略コードは不変。
- prev→cur の差分判定（§4）は **spec §9 遷移表の単一実装**。戦略ごとに重複させない。

### 3.4 PositionState 差分 → webhook（spec §9 遷移表＝単一実装）
| prev | cur | order_action | 解釈(ブリッジ) | webhook 主要値 |
|---|---|---|---|---|
| flat | long | buy | 新規買 | market_position=long, prev=flat, order_contracts=size, market_position_size=size |
| flat | short | sell | 新規売 | market_position=short, prev=flat, … |
| long(n) | flat | sell | 全量返済 | market_position=flat, prev=long, order_contracts=n, market_position_size=0 |
| short(n) | flat | buy | 全量返済 | … |
| long(n) | long(m), m<n | sell | **部分返済** | market_position=long, prev=long, order_contracts=n−m, market_position_size=m |
| short(n) | short(m), m<n | buy | 部分返済 | … |
| short | long | buy | ドテン | market_position=long, prev=short |
| long | short | sell | ドテン | market_position=short, prev=long |
| 同一 | 同一 | — | 変化なし | 送出しない |
- `order_price=0`（成行意図）。**ブリッジが対等価格＝指値に変換して執行**（スリッページ＝Split 拡大の回避はブリッジ責務）。
- 3Split の TP1/TP2/ランナーは**戦略がタイミングを決め**（size を 3→2→1→0 に落とす）、各回が「部分返済」webhook になる。価格は持たない。

---

## 4. 送出フォーマット（確定・正本＝webhook-api-spec.md v1.0.0）

`POST localhost:8001/webhook`、`Content-Type: application/json`：
```json
{ "passphrase":"…", "alert_name":"<戦略name>", "interval":15, "ticker":"…(無視)",
  "strategy": {
    "order_action":"buy"|"sell",
    "market_position":"flat"|"long"|"short",
    "prev_market_position":"flat"|"long"|"short",
    "order_contracts": <注文枚数>,
    "market_position_size": <発火後の枚数>,
    "prev_market_position_size": <発火前の枚数>,
    "order_price": 0
  } }
```
- ブリッジが prev→curr を解釈し 新規/全量返済/部分返済/ドテン/Ignore を自動判定。`alert_name`＋`interval` が戦略キー（`IStrategyRegistry.IsEnabled`）。
- 詳細・サンプル・outcome は `N225BrokerBridge/docs/webhook-api-spec.md` を参照（本書は出力側仕様のみ規定）。

---

## 5. 外回り（既存資産・コピー同梱して使う・D8）

`N225StrategyAI/clone/` に as-built（`N225StrategyAI/design/data_management_design.md` v1.0）。**ローカル製品にコピー同梱**：

| 役割 | 流用元 | 主API |
|---|---|---|
| tick 受信 | `clone/live/live_feed.py` `LiveFeed` | TCP127.0.0.1:5000 受信→OHLCManager。ai_feed_status.json(LED) |
| 足生成 | `clone/feed/ohlc_processor.py` `OHLCManager`(singleton) | `update_ohlc`・セッション対応確定・**`on_bar_close` コールバック** |
| 足ストア/バッファ | `clone/feed/ohlc_storage.py` `OHLCStorage`(singleton) | `add_to_candle`・`get_latest(n)`・`is_bar_completed`・parquet 永続・**読込失敗で消さない**(損益不変条件) |
| warmup 種 | `clone/feed/history_seed.py` | kabu CSV(≈335本・cp932)を in-memory にマージ→即300本 |
| セッション | `clone/feed/market_session_manager.py` | `is_market_open()` 日中8:45-15:45/夜間17:00-翌6:00 |
| 送出 | `clone/live/bridge_sender.py` `BridgeSender` | webhook POST。**§3.4 の遷移表対応に一般化**（現行は単一 on_fill） |
| 配線の参考 | `clone/live/live_paper.py` | 単一戦略の on_bar_close 配線例（多戦略化の雛形） |

- **新規に作るのは**：①多戦略 `run_one_step`（現行 live_paper は単一戦略）②`Strategy`/`BatchStrategyAdapter` ③`BridgeSender` の §3.4 一般化 ④ローカル版ダッシュボード。

---

## 6. ウォームアップ・建玉連続性（実測確定＝warmup 300本 / 窓 W=500）

- **warmup＝300本連続**（`N225StrategyAI/experiments/measure_warmup.py` 実測。律速＝`fibo_ratio_60m`=300本）。`len(buffer)<300` は発注抑止（ソフトゲート・不変条件）。
- **建玉連続性**：BatchStrategyAdapter は warmup を満たした窓でバッチを回す。窓は指標 warmup を満たし、かつ日ばかり戦略が頻繁にフラットへ戻るので**窓内に現建玉より前のフラット点を含む**＝建玉再現が厳密。
- **★必要バッファ長 W=500（mesa_local で実測確定・M2）**：warmup 300 ＋ MESA 最大保有 138本 ＋ 余裕。`validate_mesa_local.py` で **全1717トランジション足＋連続6000足が golden とビット一致**（窓 W=500）。
  - 偶然 **既存 `OHLCStorage.MAX_CANDLE_COUNT=500` と一致**＝外回りが既に必要窓を保持（`get_latest(500)` でよい）。
  - 鍵＝reconstruct が end_of_data（窓末の強制決済＝未決済建玉の可視化）を「実決済でない」として建玉を保持する（M1 で確定）。
  - 戦略ごとに最大保有が異なるため、新戦略は同様に `validate_*` で必要 W を実測（W ≥ warmup + 最大保有 + 余裕）。
- kabu CSV 1ファイル(≈335本>300)＝1回のエクスポートで発注解禁（5日制限クリア）。

---

## 7. 実行モデル（D7）

- **既定＝順次実行（SequentialExecutor）**：デバッグ容易・決定的・レース無し。15分足では全戦略順次でも数十ms＝次足まで15分に対し余裕。
- **opt-in 並列**：`ThreadPoolExecutor`（numpy/pandas は計算中 GIL 解放＝実効並列）。戦略が独立なので安全。将来 ProcessPool も seam 差替で対応。
- **executor は1か所の抽象**（`run_one_step` 内）。設定フラグで切替、戦略コード不変。

### 7.1 約定タイミング（D11・2026-06-14 ユーザー確定）
- **ライブは「確定足（終値確定）」で webhook を出す**＝現在の Engine 挙動（建玉が変わった確定足で送出）。
- 理由：**足は終値で初めて確定**するので、確定足で判断・送出するのが自然（先読みなし・確定足のみ処理という不変条件とも一致）。
- 帰結：バックテスト golden は **next_bar_open_fills=True（次バー始値約定）** なので、実機（確定足で発注 → 市場成行/対等価格で次足始値約定）とは**約1バー分ずれ得る**＝**実機 P&L は golden と完全一致しない**（golden は基準値・上限の目安）。ユーザー承知の上で採用。
- 将来精度を上げたい選択肢（保留）：adapter が「次バー予約(pending)」を返し、サイン足で発注して次足始値に合わせる。今は採らない（シンプル優先）。

---

## 8. 戦略ライフサイクル（開発→昇格→登録→運用）

```
[戦略開発(既存)] Python開発+BT → Pine変換しTV登録（TV版の経路・完了済）
   │ 成果物 = 検証済みPython戦略(golden)
   ▼ ★ローカル版はここから
① 載せる   既存バッチを BatchStrategyAdapter(build_input+cfg) でコピー同梱・on_bar 化
② 検証     共通BTハーネスで4年実行 → golden とビット一致（採用条件・D10）
③ 昇格     昇格関門（戦略開発ガイド §7：PF≥1.5 / 取引数≥30 / OOS比≥0.5 / 4年以上 / 15分デイトレ / 3Split）
   │ ✗→棚上げ(記録) ✓→マニフェスト確定
④ 登録     マニフェスト → レジストリ → ダッシュボードで ON/OFF 運用
```
- **BT＝実機と同一コード**：BTハーネスは on_bar を履歴足でループ、実機エンジンは同じ on_bar をライブ足で呼ぶ＝乖離なし。

### 8.1 戦略マニフェスト（全戦略が出す1枚の契約）
```json
{ "name": "mesa_local", "module": "strategies.mesa_local:build", "interval": 15,
  "warmup_bars": 300, "fill_model": {"next_bar_open_fills": true},
  "cfg": { "...": "config_v7_8 等" }, "backtest_report": "reports/mesa_local_4y.json",
  "status": "promoted" }
```
- レジストリ＝昇格済みマニフェストの集合。ダッシュボードが一覧・登録・ON/OFF。`name` はブリッジ登録名と一致。

---

## 9. ローカル版ダッシュボード（独立・新規・D9）

- 機能：①戦略の登録（マニフェスト一覧から選択）②エンジン/ブリッジ起動停止 ③戦略ごと ON/OFF ④色分けログ ⑤接続/状態 LED（kabu/ブリッジ/エンジン）。
- **TV版 `n225_brokerbridge_dashboard.py` とはコード共有しない**。`blog_Bridge_dashboard.py` を**参考にコピー元**とし、ローカル版独立の1枚として実装。
- エンジンは GUI を持たない（ヘッドレス）。ダッシュボードが唯一の操作面。状態は JSON 連携（`ai_feed_status.json` 等）。

---

## 10. MESA 参照実装（第一号・本書の実証）

- **mesa_local ＝ BatchStrategyAdapter で `config_v7_8`（`simulate_v7_8_fib_v3_split.py` の `simulate_v3`）を包む**。
  - build_input＝`build_mesa_columns`（`clone/inference/live_features.py`・master と100%一致）。cfg＝`config_v7_8()`（tp=C/SL1/depth0.5/K7/dn=hold/next_bar_open_fills=True）。
  - 旧 PORT_SPEC の `StreamingMesaV783`（入口＋出口を on_bar に新規移植）は**不採用**（D3）。ただし PORT_SPEC §7-8 の loop 解析は「reconstruct_position_at_last_confirmed_bar」実装の参考に使う。
- **成功基準（D10）**：BatchStrategyAdapter(mesa_local) を4年バーに流し、golden（`strategies/mesa_local/golden/v783_golden_fills.csv`＝588トレード/PF2.400/+109,270pt）と**全トレード・PnL ビット一致**。一致→標準確定し全戦略へ展開。

---

## 11. 段階計画

- **M1**：`Strategy`/`PositionState`/`BatchStrategyAdapter`/`run_one_step`/`position_diff_to_webhook`（§3-4）＋ executor seam＋warmup ゲート。外回り（feed/live）をコピー同梱。
- **M2**：mesa_local を BatchStrategyAdapter で実装 → 共通BTハーネスで golden ビット一致検証（§10）。
- **M3**：`BridgeSender` を §3.4 に一般化 → ペーパー（ブリッジ戦略OFF）で目標ポジ・webhook を観測。
- **M4**：ローカル版ダッシュボード（登録/起動停止/ON-OFF/ログ/LED）。
- **M5**：2戦略目以降（DT/Momentum/HighVol 等は build_input+cfg を足すだけ）→ 複数同時ペーパー → 小ロット実機。
- **M6**：**配布パッケージ化**（§12）＝uv 化（`pyproject.toml`/`uv.lock`）＋ベンダリング＋`sync_to_localengine.ps1`＋`public`/`runtime` リポ。
- **M7（将来）**：ターンキー・インストーラ（埋め込み Python＋Inno Setup）＝需要を見て追加。

---

## 12. 配布・フォルダ構成（distribution & packaging）

> 配布方式の決定が構造を決める。本章は2026-06-14 ユーザー一任のもと Claude 推薦で確定。基盤＝**uv＋GitHub**、ターンキー・インストーラは将来オプション。配布コードは Claude が作る（ユーザーに配布経験は不要）。

### 12.1 方針（確定）
- **全製品「ソース＋（将来）インストーラ」の2チャネル**。同一の自己完結ツリーから2出力（乖離させない）。
- **Python 環境＝`uv`（`pyproject.toml`＋`uv.lock`）に統一**。利用者は `uv sync` 一発で Python本体＋依存を決定的に構築（**Claude 非依存・非技術者でも1コマンド**）。手動 venv は廃止。
- **ホスティング＝GitHub のみ**（Web サイト不要）：Private リポ＝ソース、**Releases＝バイナリ**。note 有料記事から招待制（既存 [[project_business_model]]）。
- **段階**：まず **B（uv source）＋GitHub**。**C（埋め込み Python ターンキー・インストーラ＋Inno）は将来の上位オプション**（同ツリーに `packaging/` を後付け）。
- ローカル版は**別製品・自己完結**（D1）。資産はベンダリング（コピー同梱）。**TV版コードは一切含めない**。
- ブリッジ（C#・別製品）はソース＋既存 Inno インストーラ。結合は webhook URL のみ。

### 12.2 開発ツリー ↔ 配布ツリーの分離
- 開発＝`N225TradingSystem/N225LocalEngine/`（現状のまま）。
- 配布＝別リポへ **`scripts/sync_to_localengine.ps1`**（allowlist＋excludelist＋dry-run＋手動 push＝既存 `sync_to_public.ps1` 方式）で**実体コピー**。
- **2リポ**：`N225LocalEngine-public`（コード）＋`N225LocalEngine-runtime`（Claude Code 命令書＝"動かす知識"）。

### 12.3 配布ツリー（自己完結）
```
N225LocalEngine-public/                 # ソース（他製品 import なし・uv で動く）
├── pyproject.toml / uv.lock            # ★uv：uv sync で環境構築
├── engine/                             # 中核：Strategy/PositionState/BatchStrategyAdapter/run_one_step/webhook化
├── feed/                               # ベンダリング元= N225StrategyAI/clone/feed,live
├── strategies/
│   ├── _engine/                        # ベンダリング元= simulate_v7_8_fib_v3_split＋simulate_v7_7_fib(.py/_v2)＋build_master_dataset＋live_features
│   └── mesa_local/                     # build_input＋cfg(config_v7_8)＋manifest＋golden
├── dashboard/                          # ローカル版ダッシュボード（独立・TV版と別）
├── README.md / LICENSE / .gitignore
└── packaging/                          # 【将来C】python-embed取得＋wheel事前解決＋Inno スクリプト
N225LocalEngine-runtime/                # 命令書（任意・補完）
└── CLAUDE.md / .claude/{commands,skills} / docs/
```

### 12.4 ベンダリング対応表（開発元 → 配布先・実体コピー）
| 開発元（`N225TradingSystem/` 内） | 配布先 | 内容 |
|---|---|---|
| `N225StrategyAI/clone/feed/*`・`clone/live/{live_feed,bridge_sender}.py` | `feed/` | tick受信/足生成/蓄積/warmup/session/送出 |
| `…/MESA_Stochastic/python/simulate_v7_8_fib_v3_split.py`＋`simulate_v7_7_fib.py`/`_v2.py`＋`build_master_dataset.py` | `strategies/_engine/` | 戦略エンジン＋基盤＋指標生成 |
| `N225StrategyAI/clone/inference/live_features.py`（build_mesa_columns） | `strategies/_engine/` | ライブ指標 |
| 各戦略 cfg/manifest/golden | `strategies/<name>/` | golden は検証基準 |
- **コピー後は自己完結**（跨ぎ import ゼロ）。原本との忠実性は golden ビット一致（D10）で担保。

### 12.5 GitHub 配布フロー
1. 開発（普段どおり `N225TradingSystem/N225LocalEngine/`）。
2. `pwsh scripts/sync_to_localengine.ps1 -DryRun` → 何が出るか確認。
3. `pwsh scripts/sync_to_localengine.ps1` → 実体コピー。
4. 配布リポで `git diff`（secrets 目視）→ 意図したファイルのみ add → commit → push（自動 push しない）。
5. リリース時：タグ付け → （将来C）`packaging/` でビルドした .exe を **GitHub Releases** に添付。

### 12.6 excludelist（絶対に配布しない・既存 distribution_plan §3.3 準拠）
`**/memory/`・`**/docs/devlog/`・`**/Business/`・`**/*.Local.json`・`**/logs/`・`**/.venv/`・`**/__pycache__/`・`**/*.pyc`・`**/history_csv/`・`**/screenshots/`・`.git/`。
- **戦略パラメータ/golden の配布範囲はビジネス判断**（distribution_plan §3.4＝「パラメータ値は温存・テンプレのみ配布」or 本番別売り）。本設計はどちらでも成立（cfg/golden はファイル単位で同梱可否を切替）。

---

## 13. 不変条件（事故防止・損益直結）

1. 検証済みバッチ・golden は**無改造**（コピーして使う。[[feedback_no_unilateral_cleanup]]）。
2. warmup 300本未充足は**発注しない**（ソフトゲート）。
3. **先読み禁止**：判断は確定済みバーまで。最終足の未確定次バー約定を建玉判定に含めない。
4. OHLCStorage は**読込失敗でファイルを消さない**。
5. TV版コードを **import・共有しない**（D1）。資産はコピー同梱。
6. 約定モデルは戦略ごとの較正値（`next_bar_open_fills`）を踏襲。

---

## 14. 残・オープン項目

- ~~`reconstruct_position` の実装詳細・必要バッファ長~~ ✅**M2 で解決**：`engine/adapter.py::reconstruct_position`、窓 **W=500** で golden ビット一致（§6）。
- **Stage2（ライブ指標パス）の検証（M3）**：生 OHLC バッファ → `build_mesa_columns` → simulate_v3 が Stage1（master 直）と一致するか（ウォームアップ充足後）。
- ~~ライブ約定タイミング~~ ✅**D11 で確定（§7.1）**：確定足（終値確定）で webhook を出す＝現挙動。golden と約1バーずれ得るが承知の上で採用。コード変更なし。
- フィード整合の本番前実測（kabu micro/mini つなぎ vs 訓練フィード・`data_management_design.md` §10）。
- `BridgeSender` 一般化時の passphrase/alert_name/interval のマニフェスト連携。
- ダッシュボードの状態 JSON スキーマ（LED・ログ・ON/OFF）。

---

## 15. 統合元ドラフト（履歴）

本書は以下を統合・置換した（各冒頭に「本書へ統合」の銘）：
- `strategy_lifecycle_standard.md`（正本の鎖・ライフサイクル・昇格関門・マニフェスト → 本書 §1,§8）
- `local_engine_design.md`（アーキテクチャ・アダプタ・ダッシュボード・再利用 → 本書 §2,§3,§5,§9）
- `strategies/mesa_local/PORT_SPEC.md`（MESA 移植 → 方式を BatchStrategyAdapter に変更。loop 解析は §10 の参考として残置）

## 改訂履歴
- **v1.0（2026-06-14）**：3ドラフトを統合し正本化。設計判断 D1-D10 確定（別製品/コード共有禁止・Webhook送出・BatchStrategyAdapter・PositionState・15分固定・順次既定/並列opt-in・外回りコピー流用・別ダッシュボード・golden一致）。中核＝戦略↔エンジン結合ロジック（§3）。
- **v1.1（2026-06-14）**：§12 配布・フォルダ構成を追加（ユーザー一任→Claude 推薦で確定）。uv（pyproject/uv.lock）統一・GitHub のみホスティング（リポ＝ソース/Releases＝バイナリ・Web不要）・2リポ・ベンダリング対応表・sync/excludelist。C（埋め込み Python インストーラ）は将来 M7。段階計画に M6/M7 追加。
