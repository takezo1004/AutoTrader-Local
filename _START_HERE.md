# N225LocalEngine — _START_HERE（ローカル版・全ローカル戦略実行基盤）

> ⛔ **この文書の決まり（2026-09-01）**：**「現在地」の見出しは 1 つだけ**。更新するときは**上書き**し、
> 追記しない。古い記録は下の「経緯」へ送る（履歴は `docs/devlog/` にある）。基準＝ルート `CLAUDE.md`。

## ⛔ 作業前の絶対ルール

> 🚫 **【最優先】発注に関わる修正は、実トレードでテストしてから GitHub を更新する**（2026-08-18 ユーザー指示）
> 順序＝**①修正 → ②再起動して実トレードで確認 → ③合格したら push → ④Release まで通す**。
> **③④はセット。**ソースだけ push して Release を作らないのは中途半端で、ソースと配布物が食い違う。
> ローカル版の完了までの流れ（**2026-10-02 に変更。`sync_local.ps1`・`release_local.ps1`・`runtime-local/` は廃止・削除**）＝
> ①`manual/_tools/build_html.py`（マニュアルを直したとき） →②`installer/build.ps1`（Setup を作る） →
> ③この木を commit → push（`AutoTrader-Local`・**Public**。**`strategies/` は追跡しない＝公開リポに戦略を入れない**。戦略は別売・別配布） →④DevConsole「GitHub公開（Release）」の
> ［③ ローカル版を Release 公開／更新］。**配布仕様の正本＝ルート `DISTRIBUTION_MAP.md`「ローカル版の配布仕様（D15）」。**
> 追随漏れは DevConsole「配布」タブの［★ ずれを見張る］で確認する（D18）。

> 📌 **保留**：ブリッジ操作マニュアルの記述変更（webhook の設定を説明している節・場所は `N225BrokerBridge/manual/` を見る）は、**すべての作成が終わったあとに行う**（ユーザー指示）。それまで現状のまま。

> ★**設計の正本＝[`design/N225LocalEngine_詳細設計書.md`](design/N225LocalEngine_詳細設計書.md) v2.0（マスター）**
> ＋ 3 仕様書＝[`01_外部仕様書`](design/01_外部仕様書.md)（機能）／[`02_内部仕様書`](design/02_内部仕様書.md)（アーキテクチャ）／
> [`03_詳細仕様書`](design/03_詳細仕様書.md)（アルゴリズム）。ユーザーマニュアル骨子＝[`docs/USER_MANUAL.md`](docs/USER_MANUAL.md)。
> ★**ろうそく足生成は無傷保持。セッション末足（板寄せ特別足・15:45 / 6:00・10 秒待ち・executed_time 戻し・
> 境界クランプ）は一字一句変えない**（D13）。※**プロジェクト同士は跨がない**（import しない・共有はコピー同梱）。

> 📝 **2026-10-05：リアルタイム売買ブログのフックが外側に付いた。このツリーは無変更。**
> 注文 ON の戦略の webhook を、私用の統合ダッシュボードが `sender_factory`（`app/engine/controller.py:114`
> の既存引数）経由で二股にし、ブリッジとブログ役の両方へ流す。**`N225LocalEngine/` のコードは 1 行も変えていない。**
> 正本＝[`../N225LLMAdvisor/hatenaBlog/design/リアルタイム売買ブログ_設計書.md`](../N225LLMAdvisor/hatenaBlog/design/リアルタイム売買ブログ_設計書.md)。
> ★ここを変えるとき＝**sender に `.send(webhook)` 以外を求めるようにすると、そのフックが壊れる**（設計書 §2-3）。

> 📝 **2026-10-21：`strategies/Phase_DoubleDT_V4/` の `strategy.py`・`config.json` を Phase_DoubleDT 4.1（締切窓の持ち越し・週末は夜間だけ）に差し替えた。名前は V4 のまま。**
> 正本＝`../N225StrategyBuilder/strategies/Phase_DoubleDT/Phase_DoubleDT_V4_1/`（label 以外同じ・spec §15）。V4_1 の ZIP の登録はユーザー。`app/` は無変更・commit／push／Release はしていない。

## やってはいけない（正本 §12 不変条件）
- 検証済みバッチ・golden を**改変しない**（コピーして使う）。close モデル(False)に戻さない。
- **TV版コードを import・共有しない**（別製品・コピー同梱）。
- warmup 300本未充足で発注しない／先読み禁止（確定足まで）。
- 指標ヘルパーは import して使う（再実装禁止）。

## 現在地（インストーラー方式。2.1.2＝取込の守り・欠けの表示・16:00。2.1.1＝引けの板寄せ tick の修正。実機確認は次の 06:00／08:45）

**配布の形を変えた**＝ZIP ＋ 起動バット → **インストーラー 1 本＋デスクトップアイコン**。利用者に Python・uv・.NET は要らない。

| もの | 実物 |
|---|---|
| 製品名 | **AutoTrader Local**（旧「N225AutoTrader-Local」「N225AutoTrader ローカル版」は廃止） |
| 版 | `pyproject.toml` **2.1.2**。**2.1.2**＝取込の守り（未完成バーを落とす・重なりの仕分けを表示・取引日→実時刻の夜間前半 16:00）と欠けの表示（`data_provider.find_gaps`・データ管理・起動ログ）。設計＝`N225TradingViewEngine/A_author/design/履歴データ管理_設計書.md`。**2.1.1**＝`app/engine/realtime_broker.py` `on_tick` の先頭で、場が開いていない時刻の tick（引けの板寄せ約定値・プレオープン）では何もしない（判定＝`_market_hours.is_open_at`）。セッション最後の足で予約した成行は次のセッションの最初の tick（寄付）で 1 回だけ約定・送出する＝BT・TradingView と同じ（詳細仕様 §B.3 (0)・テスト `tests/test_close_auction_tick.py`）。私用の統合ダッシュボードは `N225LocalEngine/` を直接 import するので、次回起動から効く |
| Setup | `installer/output/AutoTrader-Local-Setup-2.1.2.exe`（**37.4 MB**・SHA256 `9976970c…b80133`） |
| GitHub | `AutoTrader-Local`（Public）。**Release `v2.1.2`** 公開／push 済み（2026-11-10）。**`strategies/` は入れない**（`.gitignore`・`DISTRIBUTION_MAP.md`「ローカル版の配布仕様」） |
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

---

## 次の一手

### ★① エンジンのろうそく足が TradingView と違う

**登録している戦略が、TradingView 側（Pine）では発火しないバーで一斉にエントリーした。**
Python と Pine のエントリー条件は現在の config では等価（コード差は既知の 1 点＝Pine が
`se_blocked`/`w_skip` を再確認する分だけ）で、ロジックでは説明できない。
**エンジンが作っている 15 分足が TradingView と違う**（ユーザー判断）。同じスクリプトを動かしているので、
入力データしか違いようがない。

**済み＝蓄積足の欠損の補填。** `data/ohlc_live.parquet` を 15 分足 4 年正本
（`N225DataPipeline/datasets/n225_15m_4y.pkl`）と突き合わせ、欠損 892 本を正本から埋めた
（**9,851 → 10,743 本**・2026-04-10 06:00 〜 2026-10-10 06:00・退避 `ohlc_live.parquet.bak_20261011`）。
欠損区間だけを埋め、**既存のライブ足は 1 行も変えていない**（ユーザー決定）。
補填後は正本に対して欠損 0・余剰 0。

**残り＝両方に存在する足の「値」が正本と違う部分。未着手。**
両方にある 9,851 本の完全一致率＝open 92.5% / high 98.0% / low 97.8% / close 93.0% / volume 71.8%、
最大差は open 195 円・low 190 円・close 60 円・volume 12,982 枚。
225Labo ↔ TradingView の 1 ティック差（最大 60 円）より大きい差が open / low に出ている。

- 蓄積足の保存は `app/feed/ohlc_storage.py::_save_to_file_worker`＝**毎回ファイルを読み直して 1 本追記 →
  `datetime` で重複排除 → 6 ヶ月ローリング**。手で埋めた行が後の保存で消えることはない。

### ② 配布

1. **実機でインストールと起動の確認**（Setup を実行 → デスクトップのアイコン → 画面が出るか →
   ブリッジが起動するか）。**未実施**
2. 無料公開だが**発注には有料の開発キットで作ったブリッジが必要**。この案内のしかたは
   **現状のままでよい**（2026-10-02 ユーザー判断＝README とマニュアル 0-2 で足りる）

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

過去の経緯は [`_archive/_START_HERE_history_2026-10-06.md`](_archive/_START_HERE_history_2026-10-06.md) と [`_archive/2026-10-09_START_HERE_旧版.md`](_archive/2026-10-09_START_HERE_旧版.md) にある。
