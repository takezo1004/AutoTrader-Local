> ⚠️ **【統合済・履歴】本ドラフトは 2026-06-14 に正本 [`N225LocalEngine_詳細設計書.md`](N225LocalEngine_詳細設計書.md) へ統合・置換されました。** 設計判断は正本を参照。アーキテクチャ・アダプタ・ダッシュボード・再利用方針は正本 §2,§3,§5,§9 に反映（target_pos→PositionState、§4.2 アダプタは正本 §3.2 に確定）。

# ローカル版 戦略実行エンジン 設計書（ドラフト v0.1・統合済）

> 状態：**設計フェーズ（実装着手前・ドラフト）**。本書はレビュー → 合意 → 実装の順で進める。
> 親方針：N225TradingSystem を「TradingView版（外部・既存）」と「ローカル版（全ローカル・新規）」の2系統に分け、AIは別製品でなく**着脱できる戦略アドオン**とする（2026-06-13 ユーザーと確定）。

---

## 1. 目的・スコープ

### 1.1 目的
**TradingView もドメイン/トンネルも使わず、全ローカルで日経225戦略を自動売買する**実行基盤を作る。司令塔は専用ダッシュボード（ベーシック・ダッシュボード）。

### 1.2 2系統の区分け（確定）
| 版 | 環境 | 司令塔 | 状態 |
|---|---|---|---|
| **TradingView版** | TV＋ドメイン＋トンネル → ブリッジ → kabu | `n225_brokerbridge_dashboard.py` | ✅ 完成済（本書の対象外・境界のみ定義） |
| **ローカル版** | kabu ⇄ ブリッジ ⇄ Python戦略エンジン（全ローカル） | 新規ベーシック・ダッシュボード | ★本書で設計 |

- **AI戦略パック**：どちらの版にも差せるアドオン（プレミアム層）。ローカル版では「1つの登録戦略」として動く。

### 1.3 スコープ（本書で設計するもの）
1. 共通戦略インターフェース（普通の戦略もAIも同じ受け口）
2. 戦略実行エンジン（登録・ウォームアップゲート・足→判断→シグナル送出）
3. ベーシック・ダッシュボード（戦略登録／ブリッジ起動停止／戦略ON-OFF／ログ）
4. 既存資産（バッチ戦略・feed・bridge_sender・live_paper）の再利用方針

### 1.4 非スコープ
- 個々の戦略ロジックの新規開発（既存の検証済み戦略を載せる）。
- TradingView版の改修（境界の定義のみ）。
- ブリッジ本体の発注ロジック（既存を流用。必要な追加のみ別途）。

---

## 2. 全体アーキテクチャ

```
                       ローカル版（全ローカル・TV/トンネル不要）
  kabu Station
     │  tick(歩み値)
     ▼
  N225BrokerBridge ──AiTickForwarder(TCP5000)──▶ 戦略エンジン
     ▲                                              │
     │  Webhook(localhost:8001)                      ├─ ① 足生成   feed: tick→15分足→ohlcストア
     │  売買シグナル                                  ├─ ② 戦略実行 各登録戦略.on_bar(buffer)→目標ポジション
     └──────────────── bridge_sender ◀──────────────┤   (warmup未充足は発注抑止)
                                                     └─ ③ 送出     目標ポジ変化→Webhook(戦略名つき)
                       ▲
                       │ 制御(起動/停止/登録/ON-OFF)・状態(LED)・ログ
                  ベーシック・ダッシュボード
```

- **足生成・送出は全戦略共通**（クローンAIで実装済みの `feed` / `bridge_sender` を共有エンジン部品に昇格）。
- **戦略は「足を受け取り目標ポジションを返す」だけ**。中身（ルール戦略かAIか）はエンジンから見えない。
- 発注の最終可否は**ブリッジが戦略名で判断**（既存仕組み）。

---

## 3. 共通戦略インターフェース（中核）

### 3.1 契約
```python
@dataclass
class Bar:
    ts: datetime; open: float; high: float; low: float; close: float; volume: float

@dataclass
class Intent:
    """この戦略が"今"取りたい目標ポジション。エンジンが前回との差分をブリッジへ送る。"""
    target_pos: int        # +N(ロングN枚) / -N(ショート) / 0(ノーポジ)
    reason: str = ""       # ログ用（entry/tp1/tp2/exit/dohten 等）

class Strategy(Protocol):
    name: str              # ブリッジ登録名（例 "mesa_local", "ob5m"）。一意。
    warmup_bars: int       # 判断に必要な最小連続本数（普通=指標ルックバック, AI=300）
    def on_bar(self, candles: pd.DataFrame) -> Intent: ...   # 確定足ごと。candles=直近バッファ(古→新)
```

### 3.2 なぜ "目標ポジション(target_pos)" 方式か
- TradingViewのstrategy Webhookと同じ意味論（`market_position`）。**entry/部分利確/dohten/全決済をすべて"目標ポジの変化"として統一**でき、`bridge_sender` が既にこの差分送出を実装済み。
- 戦略側は「今いくつ持つべきか」を返すだけでよく、約定状態の管理をエンジン/ブリッジに委譲できる。

### 3.3 2種類の戦略の実装（同じ契約に乗る）
- **普通の戦略（ルール）**＝検証済みバッチ `simulate_v3` 等を**スライディング窓で実行するアダプタ**（§4.2）。
- **AI戦略（クローン）**＝ `live_paper` のロジック（特徴量→mE/mD→FibSync出口）を `on_bar` に整理。warmup_bars=300。

---

## 4. 戦略実行エンジン

### 4.1 責務
1. 登録戦略を保持（`name → Strategy`）。
2. `feed` から確定足を受け、各**有効**戦略の `on_bar(buffer)` を呼ぶ。
3. **ウォームアップゲート**：`len(buffer) < strategy.warmup_bars` の戦略は呼ばない/発注しない（不変条件）。
4. 各戦略の `Intent.target_pos` を前回値と比較し、**変化があれば** `bridge_sender` 経由で Webhook 送出（戦略名つき）。
5. 状態（各戦略の現在ポジ・最終足時刻・warmup充足）をダッシュボードへ公開（JSON）。

### 4.2 ★バッチ戦略アダプタ（最重要・B案）
検証済みバッチを書き換えず、毎バー実行して最新バーの目標ポジだけ取り出す：
```python
class BatchStrategyAdapter:
    def __init__(self, name, build_dataset_fn, cfg, warmup_bars):
        # build_dataset_fn(raw_ohlc) → simulate_v3 が要る指標つき DataFrame
        ...
    def on_bar(self, candles) -> Intent:
        ds = self.build_dataset_fn(candles)           # 指標を毎バー再計算(バッファ全体)
        fills, _ = simulate_v3(ds, self.cfg)          # 検証済みバッチをそのまま実行
        pos = reconstruct_position_at_last_bar(fills, len(ds)-1)  # 最終足での建玉を復元
        return Intent(target_pos=pos, reason=...)
```
- **利点**：バックテストと実機が**同一コード＝完全一致**（[[feedback_python_4y_is_authoritative]] と整合）。全戦略を書き直さない。
- **コスト**：毎バー数百本の再計算。15分間隔では無視できる（ミリ秒オーダー）。
- **留意**：`next_bar_open_fills` など約定モデルのフラグは戦略ごとに較正値を踏襲（[[feedback_python_bt_vs_tv_optimistic]]）。最終足は"未確定の次バー始値約定"を含めないよう、**確定済みバーまでで建玉を判定**する（先読み防止）。

### 4.3 ウォームアップ・蓄積（クローンAIと共通方針）
- 足は `feed`（OHLCManager＋ohlcストア）で生成・永続蓄積。warmup未充足は発注抑止（ソフトゲート）。
- 各戦略の `warmup_bars` をエンジンが集約し、「全戦略が動ける最大warmup」までは抑止。

---

## 5. ベーシック・ダッシュボード（司令塔）

### 5.1 機能（ユーザー指定の最小セット）
1. **Python戦略の登録**：利用可能な戦略一覧から選び、ブリッジへ登録名・interval で登録（`strategies.json` 連携）。
2. **ブリッジ起動／停止**。
3. **登録戦略の有効/無効（ON-OFF）**：戦略ごとに発注可否を切替（ブリッジの isEnabled ＋ 戦略エンジンの有効フラグ）。
4. **ログ表示**：エンジン・ブリッジのログを色分け表示（クローンAIダッシュボードの色分け方式を流用）。
5. **接続/状態LED**：kabu / ブリッジ / 戦略エンジン の稼働・接続表示。

### 5.2 土台
- クローンAIで作った `blog_Bridge_dashboard.py`（ブリッジ起動・ローカルAI起動・色分けログ・LED・CSV warmup）が**ベーシック版の原型に最も近い**。これを土台に「単一AI起動」→「複数戦略の登録・ON-OFF」へ一般化する。
- TradingView版 `n225_brokerbridge_dashboard.py` とはコード共有しすぎず、**ローカル版は独立した1枚**として保つ（責務混在を避ける）。

---

## 6. 既存資産の再利用・リファクタ方針

| 既存 | 再利用先 | 方針 |
|---|---|---|
| `N225StrategyAI/clone/feed/`（OHLCManager・ohlc_storage・history_seed） | エンジンの足生成 | **共有部品に昇格**（AI専用でなく汎用足生成として） |
| `N225StrategyAI/clone/live/bridge_sender.py` | エンジンの送出 | 共有（target_pos差分→Webhook） |
| `N225StrategyAI/clone/live/live_paper.py` | AI戦略の `on_bar` | `Strategy` 契約に整理して載せ替え |
| `N225StrategyBuilder/.../simulate_v3` ほかバッチ戦略 | `BatchStrategyAdapter` 経由 | **書き換えない**・アダプタで包む |
| `feature_engine_py` / `python_engine`（指標・ZigZag） | `build_dataset_fn` | バッファから指標を再計算 |

> 原則：**検証済みコードは触らない（[[feedback_no_unilateral_cleanup]]）。** 共通化は"包む（アダプタ）"で行い、戦略本体のロジックは保持する。

---

## 7. 検証プロトコル・段階計画

### 7.1 検証（実機化の受け入れ条件）
1. **アダプタ一致**：`BatchStrategyAdapter` の毎バー目標ポジ列が、同データのバッチ `simulate_v3` の建玉推移と**完全一致**（戦略ごとに4年で検証）。
2. **送出整合**：target_pos 変化 → Webhook ペイロードがブリッジで意図どおり解釈される（既存 bridge_sender の検証を流用）。
3. **ペーパー**：発注せず記録のみ（ブリッジ戦略名OFF）で一定期間、目標ポジ・ログを観測。
4. 合格 → 小ロット実機（戦略名ON）→ 段階拡大。

### 7.2 段階計画
- **M1**：共通インターフェース＋エンジン骨格（足→on_bar→target_pos→送出）＋warmupゲート。
- **M2**：`BatchStrategyAdapter` でまず1戦略（最も単純な Momentum_Combo か、本命 MESA）を載せ、§7.1-1 一致検証。
- **M3**：AI戦略（クローン）を `Strategy` 契約に載せ替え（live_paper を整理）。
- **M4**：ベーシック・ダッシュボード（登録・起動停止・ON-OFF・ログ）。
- **M5**：複数戦略同時運用・ペーパー → 小ロット実機。

---

## 8. 未決事項（レビューで詰める）
1. **配置**：本サブシステムの置き場所（`N225LocalEngine/` 新設で良いか／既存 `N225StrategyAI` を一般化するか）。
2. **戦略登録の単位**：1戦略＝1プロセスか、1エンジンプロセス内に複数戦略を同居させるか（推奨：1エンジンに複数同居＝リソース効率・足生成を共有）。
3. **target_pos の枚数表現**：3Split（3枚→1枚ずつ返済）の途中状態を target_pos の整数だけで十分表せるか、部分利確の価格情報も要るか。
4. **約定モデル**：各戦略の `next_bar_open_fills` 較正値の引き継ぎ方（戦略ごとに設定として持つ）。
5. **ダッシュボード**：`blog_Bridge_dashboard.py` を改名して土台にするか、ローカル版として新規に切るか。
6. **戦略の発見**：利用可能戦略をどう列挙するか（戦略レジストリ／プラグイン登録）。

---

## 改訂履歴
- v0.1（2026-06-13）：初版ドラフト。2系統の区分け（ローカル版/TradingView版）・共通戦略インターフェース・バッチ戦略アダプタ（B案＝検証済みバッチをスライディング窓で再利用）・戦略エンジン・ベーシックダッシュボード・再利用方針・段階計画・未決事項。**レビュー待ち**。
