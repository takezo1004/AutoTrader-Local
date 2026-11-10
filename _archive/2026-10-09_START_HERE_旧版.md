# _START_HERE.md 旧版（2026-10-09 に 146 行から整理したときの全文）

退避の理由＝120 行を超えたため（基準＝`docs/start_here_policy.md`）。現役は [`../_START_HERE.md`](../_START_HERE.md)。

---

# N225LocalEngine — _START_HERE（ローカル版・全ローカル戦略実行基盤）

> ⛔ **この文書の決まり（2026-09-01）**：**「現在地」の見出しは 1 つだけ**。更新するときは**上書き**し、
> 追記しない。古い記録は下の「経緯」へ送る（履歴は `docs/devlog/` にある）。基準＝ルート `CLAUDE.md`。

## ⛔ 作業前の絶対ルール

> 🚫 **【最優先】発注に関わる修正は、実トレードでテストしてから GitHub を更新する**（2026-08-18 ユーザー指示）
> 順序＝**①修正 → ②再起動して実トレードで確認 → ③合格したら push → ④Release まで通す**。
> **③④はセット。**ソースだけ push して Release を作らないのは中途半端で、ソースと配布物が食い違う。
> ローカル版の完了までの流れ（**2026-10-02 に変更。`sync_local.ps1`・`release_local.ps1`・`runtime-local/` は廃止・削除**）＝
> ①`manual/_tools/build_html.py`（マニュアルを直したとき） →②`installer/build.ps1`（Setup を作る） →
> ③この木を commit → push（`AutoTrader-Local`・**Public**） →④DevConsole「GitHub公開（Release）」の
> ［③ ローカル版を Release 公開／更新］。**配布仕様の正本＝ルート `DISTRIBUTION_MAP.md`「ローカル版の配布仕様（D15）」。**
> 追随漏れは DevConsole「配布」タブの［★ ずれを見張る］で確認する（D18）。


> ✅ **2026-08-18 実施：「シークレットコード」→「パスフレーズ」に改称**（ユーザー決定・ブリッジ側の名称に統一）
> 同じ 1 つの値を、ブリッジは「パスフレーズ」、TradingView 版はアラート本文の `passphrase`、
> ローカル版だけ「シークレットコード」と呼んでいたため統一した。**戦略ごとではなくエンジン全体で 1 つ**
> の値である点は変更なし。設定キー（`passphrase`）・取得経路（ブリッジから DPAPI 復号）も変更していない。
> 画面表示・ログ文言のみの変更で、**反映はローカルエンジンの再起動後**。
> 変更＝`app/dashboard/{settings,register}_dialog.py`・`app/engine/controller.py`・`design/01_外部仕様書.md`。
> **残：ブリッジ操作マニュアルの記述変更**（webhook の設定を説明している節。場所は `N225BrokerBridge/manual/` を見る）は
> **すべての作成が終わったあとに行う**（ユーザー指示）。それまで現状のまま。


> ★★**2026-07-02：スレッド/並行性の大改修（3点セット・検証済・反映は再起動時）。**
> ①稼働中 load_all の再warmup **非同期化**＋**差分リロード reload_one**（登録/編集/パラメータ保存＝対象戦略のみ背景再構築・他戦略無停止・GUI固まらない。旧＝42秒フリーズ「応答なし」の根治）
> ②**注文送信キュー化**（BridgeSender→共有FIFO＋bridge-sendワーカー。ブリッジ遅延でもfeed不停止・送信順序保存）
> ③**tick/確定足ディスパッチワーカー化**（受信系は積むだけ→le-dispatchが直列fan-out。recv/タイマー両スレッドの同一ブローカー同時侵入の競合窓も解消）
> ＋CSV取込の出来高を**列名解決**（TVエクスポートで指標列が挟まっても誤読しない。運用＝15分タブに出来高インジ載せっぱなし）。
> 記録＝`design/N225LocalEngine_詳細設計書.md` 追記3本／`docs/devlog/2026-07-02.md`／mydocs 5冊改訂／USER_MANUAL v0.3。

> ★★**2026-06-16：設計 v2.0 確定（最優先で読む）。** ユーザーと設計をすり直し、**詳細設計を全面改訂**した。
> **正本＝[`design/N225LocalEngine_詳細設計書.md`](design/N225LocalEngine_詳細設計書.md) v2.0（マスター）** ＋ 3仕様書：
> [`design/01_外部仕様書.md`](design/01_外部仕様書.md)（機能）／[`design/02_内部仕様書.md`](design/02_内部仕様書.md)（アーキテクチャ）／[`design/03_詳細仕様書.md`](design/03_詳細仕様書.md)（アルゴリズム・★ろうそく足/セッション末足）。ユーザーマニュアル骨子＝[`docs/USER_MANUAL.md`](docs/USER_MANUAL.md)。
>
> **v2.0 の要点（確定）**：
> - **戦略＝新仕様 on_bar（注文を返す）・完全自己完結・1フォルダ1戦略・ZIP配布**（StrategyBuilder の `strategies/<戦略名>/`）。
> - **二刀エンジン**＝1つの PineBroker ロジックを **オフライン（履歴バー＝内蔵BT）／リアルタイム（形成中足 tick＝ライブ）** で駆動。**イントラバー指値**を実現（確定足の終わりを待たない）＝**TradingView 忠実**。
> - **ブリッジ（完成済・別製品）＝TVブローカー**。出たシグナルをバーに関係なく忠実発注。ローカルは fill 同期を作らず自前建玉モデルを持つ。
> - **ダッシュボード中心・5機能**：複数登録／パラメータGUI＋**内蔵BT(半年・蓄積+CSVマージ)**／実行可否(✓)／**dry-run仮想売買**／**2段階実行制御**(個別＋全体)。
> - **★ろうそく足生成は無傷保持。特にセッション末足（板寄せ特別足・15:45/6:00・10秒待ち・executed_time 戻し・境界クランプ）は一字一句変えない**（ユーザーが最も苦労した箇所・D13）。
>
> ★**旧 M1〜M5（BatchStrategyAdapter 方式）と `_vendor/mesa`・`strategies/mesa_local,dt_local`・旧 dashboard/controller/registry は破棄対象**。流用するのは **feed（ろうそく足・無傷）** と **webhook 変換の考え方**のみ。旧設計書 v1.1 は [`design/_archive/`](design/_archive/) に退避（無破壊）。
> ※ 大原則：**プロジェクト同士は跨がない**（各自己完結・他プロジェクトを import しない・共有はコピー同梱）。

> 📝 **2026-10-05：リアルタイム売買ブログのフックが外側に付いた。このツリーは無変更。**
> 注文 ON の戦略の webhook を、私用の統合ダッシュボードが `sender_factory`（`app/engine/controller.py:114`
> の既存引数）経由で二股にし、ブリッジとブログ役の両方へ流す。**`N225LocalEngine/` のコードは 1 行も変えていない。**
> 正本＝[`../N225LLMAdvisor/hatenaBlog/design/リアルタイム売買ブログ_設計書.md`](../N225LLMAdvisor/hatenaBlog/design/リアルタイム売買ブログ_設計書.md)。
> ★ここを変えるとき＝**sender に `.send(webhook)` 以外を求めるようにすると、そのフックが壊れる**（設計書 §2-3）。

## やってはいけない（正本 §12 不変条件）
- 検証済みバッチ・golden を**改変しない**（コピーして使う）。close モデル(False)に戻さない。
- **TV版コードを import・共有しない**（別製品・コピー同梱）。
- warmup 300本未充足で発注しない／先読み禁止（確定足まで）。
- 指標ヘルパーは import して使う（再実装禁止）。

## 現在地（インストーラー方式の 2.1.0 を無料公開）

**配布の形を変えた**＝ZIP ＋ 起動バット → **インストーラー 1 本＋デスクトップアイコン**。利用者に Python・uv・.NET は要らない。

| もの | 実物 |
|---|---|
| 製品名 | **AutoTrader Local**（旧「N225AutoTrader-Local」「N225AutoTrader ローカル版」は廃止） |
| 版 | `pyproject.toml` **2.1.0**。★**2026-10-09 にコメント（docstring）2 か所だけ直したが、版は上げていない。**次に中身を変えたときに上げる（ユーザー決定） |
| Setup | `installer/output/AutoTrader-Local-Setup-2.1.0.exe`（**37.3 MB**・SHA256 `e97ed447…64aa91`） |
| GitHub | **`AutoTrader-Local` を Public に変更**。**Release `v2.1.0`** 公開／push 済み `976c381` |
| 組み立て | **`installer/build.ps1` 1 本だけ**（ランチャー → 依存 → 削り → payload → ISCC）。`distribution/` 側の一式（`runtime-local/`・`sync_local.ps1`・`release_local.ps1`）は**廃止・削除** |
| 中身 | ランチャー `AutoTrader-Local.exe`（8.1 MB）＋ソースの `.py`＋`lib\`（131.6 MB）＋`manual\manual.html`。インストール先 `C:\Users\<名前>\AutoTraderLocal\` 固定・**UAC なし** |

- ★**`installer/payload/app/` は本体 `app/` と md5 が一致していない**（2026-10-09 の docstring 修正分。
  `app/feed/_market_hours.py` と `app/feed/market_session_manager.py` のコメントだけの差）。
  payload は `installer/build.ps1` の robocopy が作る**生成物**なので手で直さない。
  **次に `build.ps1` を回したときに自動で揃う。**
- 市場カレンダー（`data/market_Calendar.csv`）の休日判定は `app/feed/_market_hours.py:90`
  `is_no_trade_day()` の **1 か所集約**（土日 ＋ `_YEAR_BOUNDARY_CLOSED`＝1/1・1/2・1/3・12/31 ＋
  CSV の「実施しない」）。**1/1 は JPX の表に載らない**（注 1 で対象外）ので構造で持っている。
  消費側（`ohlc_processor` / `session_lib` / `market_session_manager` / `controller` /
  `calendar_dialog`）はすべてこれを呼ぶ。**ここを増やさない。**
- **ダッシュボードの起動時に、開発キットで作った AutoTrader Bridge も起動する**（`app/bridge_launcher.py`。導入先は決め打ちせず `%LOCALAPPDATA%\AutoTraderBridge\install.json` の `bridgeExe` から解決）
- マニュアルは **0-3 ダウンロードとインストール（新規・Assets の画像つき）**を追加し、**執筆規約を全ページに適用**（見出し 58 件・本文 20 件）。TradingView 版（別製品）の説明は削除
- 配布仕様の正本＝ルート [`DISTRIBUTION_MAP.md`](../DISTRIBUTION_MAP.md)「ローカル版の配布仕様（D15）」。公開の決定＝D16

**次の一手**

1. **実機でインストールと起動の確認**（Setup を実行 → デスクトップのアイコン → 画面が出るか → ブリッジが起動するか）。**未実施**
2. 無料公開だが**発注には有料の開発キットで作ったブリッジが必要**。この案内のしかたは**現状のままでよい**（2026-10-02 ユーザー判断＝README とマニュアル 0-2 に書いてある内容で足りる）

---

## 次の一手

### ★エンジンのろうそく足が TradingView と違う（2026-10-09 引け後に突き合わせる）

**2026-10-05 20:15 に、登録している 10 戦略すべてが同じバーで一斉にエントリーした。**
同じロジックを TradingView 側（Pine）では発火していない。調べた結果は次のとおり。

- Python（`strategies/Phase_DoubleDT_V4`）と Pine の**エントリー条件は現在の config では等価**
  （コード差は既知の 1 点＝Pine が `se_blocked`/`w_skip` を再確認する分だけ）
- 20:15 の時点で**どちらのバーでも発火しない**＝TV バーで振り子 ms −0.5755／エンジンのバーで −0.7185
  （しきい値は −0.8）。つまりロジックでは説明できない
- **結論（ユーザー判断）＝エンジンが作っている 15 分足が TradingView と違う。**同じスクリプトを動かしているので、
  入力データしか違いようがない

**対応＝建玉がフラットになってから（2026-10-09 引け後・weekend_sq）データを突き合わせ、エンジンを正常化する。**
それまで **`data/ohlc_live.parquet` と `app/state/` には触らない**（実トレードに影響するため・ユーザー決定）。
リアルタイム売買ブログが動いているので、決済のタイミングもそれを考慮して決める。

## 確定した設計（正本）
- ★**正本＝[design/N225LocalEngine_詳細設計書.md](design/N225LocalEngine_詳細設計書.md)（v1.0・2026-06-14）**。3ドラフトを統合した唯一の基準。設計判断 D1-D10（別製品/コード共有禁止・Webhook送出・**BatchStrategyAdapter**・PositionState・15分固定・順次既定/並列opt-in・外回りコピー流用・別ダッシュボード・golden一致）を確定。
  - 正本の鎖：**Pine(一次正本) ≡ Python(較正済み golden) ≡ ローカルon_bar(ビット一致検証)**。
  - 実装方式＝**BatchStrategyAdapter**（検証済み `simulate_v3` 等をコピー同梱・無改造で毎足回す。on_bar 新規再移植は不採用）。
  - 送出＝確定 Webhook フォーマット（`N225BrokerBridge/docs/webhook-api-spec.md`）。枚数＋売買シグナル、価格と執行はブリッジ。
- 旧3ドラフト（[_archive/strategy_lifecycle_standard.md](design/_archive/strategy_lifecycle_standard.md) / [_archive/local_engine_design.md](design/_archive/local_engine_design.md)）は**正本へ統合済**（`design/_archive/` にある）。現役の正本は **詳細設計書（master）＋ 01/02/03 の4点のみ**。

## ★後半：戦略オーサリング標準へ方針転換（次セッションはここから）
- **登録の仕組みを作る前に、Python 戦略の「書き方・置き方」を標準化する**必要が判明（N225StrategyBuilder の根本改善）。詳細は **devlog `docs/devlog/2026-06-14.md` ⑩** と **`N225StrategyBuilder/strategies/_STRUCTURE.md`**（構造正本）。
- 確定：①戦略＝ロジックだけ（BT/データ/レポートは持たない）②broker（Pine strategy.* と1対1）③共有BTエンジン本拠＝`N225StrategyBuilder/strategies/_engine`（live はコピー・backtest 無し）④フォルダ＝`work/`＋`release/<strategy_name>/`（配布・登録単位）⑤一貫性の軸＝戦略名・版は MANIFEST.version。
- **Sample1/Sample2 を実作成済**（標準フォルダ雛形）。
- **次セッションの手順**：(a) `_engine` 本拠化の移設＋broker 実装 → (b) `_TEMPLATE` 更新 → (c) **Pine→Python 変換テスト1本** → (d) registry/dashboard を「フォルダ指定登録＋ブリッジ strategies.json モニター」に作り直す。
- ★既存 M1-M5・dashboard第一版・registry/controller は**ハードコード版**＝標準で作り直す前段。engine 中核（contract/adapter/executor/webhook/core）と golden 検証は流用可。
## 関連

**仕様・設計（実装する人が読む）**
- `design/01_外部仕様書.md`（機能）／`design/02_内部仕様書.md`（内部）／`design/03_詳細仕様書.md`（詳細）
- `design/N225LocalEngine_詳細設計書.md`（全体）

**中身の解説（開発用・配布しない）**＝[`docs/architecture/`](docs/architecture/README.md)
- ランタイムフロー／スレッド並行性／Python 戦略とエンジンの関係／周辺サブシステム／運用とダッシュボード
  （2026-10-05 に `mydocs/` から移した。マニュアルではない）

**利用者向け**＝`manual/`（章立て → `manual/_preview/manual.html`）。旧単一ファイル＝`docs/USER_MANUAL.md`

**外部の正本**
- 配布・公開の区分＝ルート [`DISTRIBUTION_MAP.md`](../DISTRIBUTION_MAP.md)「ローカル版の配布仕様（D15）」
- Webhook の形式＝[`../N225BrokerBridge/docs/webhook-api-spec.md`](../N225BrokerBridge/docs/webhook-api-spec.md)
- 戦略の作り方＝[`../N225StrategyBuilder/strategies/_STRUCTURE.md`](../N225StrategyBuilder/strategies/_STRUCTURE.md)
- 横断ロードマップ＝memory `project_three_strategy_roadmap`／別製品制約＝`project_localengine_separate_product`

**登録している戦略**＝`strategies/` 配下 18 本（実物を見る。ここに一覧を書くと必ず食い違う）
---

過去の経緯は [`_archive/_START_HERE_history_2026-10-06.md`](_archive/_START_HERE_history_2026-10-06.md) にある。
