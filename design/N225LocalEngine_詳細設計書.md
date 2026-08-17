# N225LocalEngine 設計書（マスター・正本 v2.0）

> 状態：**正本（authoritative）**。2026-06-16、ユーザーとの設計すり直しにより全面改訂。
> 旧 v1.1（BatchStrategyAdapter 方式）は `design/_archive/N225LocalEngine_詳細設計書_v1.1_BatchAdapter版.md` に退避（履歴・無破壊）。
> 本書はマスター（概要・設計判断・全体像・段階計画）。詳細は下記3仕様書に分割：
>
> - **外部仕様** → [`01_外部仕様書.md`](01_外部仕様書.md)（ダッシュボード5機能・I/O・配布・ユーザー視点の振る舞い）
> - **内部仕様** → [`02_内部仕様書.md`](02_内部仕様書.md)（二刀エンジン・モジュール構成・ろうそく足サブシステム・ブローカー・webhook変換・データ管理）
> - **詳細仕様** → [`03_詳細仕様書.md`](03_詳細仕様書.md)（アルゴリズム・データ構造・★ろうそく足/セッション末足・リアルタイムtickブローカー・config schema・内蔵BT・不変条件・エッジケース）
> - ユーザー使用マニュアル（準備中・骨子）→ [`../docs/USER_MANUAL.md`](../docs/USER_MANUAL.md)

---

## 0. 何を作るか（一行）

**StrategyBuilder で作った自己完結 Python 戦略を、ローカルだけで「1ステップ（1確定足）ずつ」動かし、ダッシュボードを司令塔に複数戦略を並行運用する基盤。** 約定はブリッジ（完成済・別製品）が TradingView と同じく忠実に執行する。エンジンは TradingView の「戦略＋アラート」役に徹し、ブリッジが「ブローカー」役を担う。

---

## 1. 2系統の区分け（親方針）

| 版 | 環境 | 司令塔 | 状態 |
|---|---|---|---|
| **TradingView版** | TV＋ドメイン＋トンネル → ブリッジ → kabu | `n225_brokerbridge_dashboard.py` | ✅ 完成済（本書の対象外・境界のみ） |
| **ローカル版** | kabu ⇄ ブリッジ ⇄ Python戦略エンジン（全ローカル） | ローカル版ダッシュボード（新規） | ★本書で設計 |

- 両版は**別製品・個別販売**。コードを共有しない（D1）。結合はブリッジへの **Webhook プロトコルのみ**（D2）。

---

## 2. 確定した設計判断（D1–D14・全章の前提）

| # | 判断 | 内容 |
|---|---|---|
| D1 | **別製品・自己完結** | TV版とローカル版は別製品。ローカル版は自己完結＝他プロジェクトを import しない。資産はコピー同梱（ベンダリング）。[[project_localengine_separate_product]] |
| D2 | **結合は Webhook のみ** | `POST localhost:8001/webhook`（確定フォーマット＝[`../../N225BrokerBridge/docs/webhook-api-spec.md`](../../N225BrokerBridge/docs/webhook-api-spec.md) v1.0.0）。HTTP 疎結合。 |
| D3 | **戦略は新仕様 on_bar（旧 BatchStrategyAdapter は破棄）** | 戦略は「1バーで動く」＝確定足ごとに `on_bar(bar)` が呼ばれ**注文リストを返す**。指標も毎バー内蔵再計算。バッチ engine も4年データも持ち込まない。正本＝StrategyBuilder `strategies/<戦略名>/`。 |
| D4 | **戦略は注文を返す（broker へ）／約定はエンジン** | 注文プロトコル `{"t":"entry"/"close"/"exit"/"cancel"}`。戦略はエンジン注入の `position_size`/`position_avg_price`/`entry_bar` を読む（Pine の strategy.* 相当）。 |
| D5 | **約定の正本＝PineBroker** | 成行=次バー始値・指値=イントラバー・逆指値=イントラバー・3Split OCO・exit ID 一度きり・stop は次バーから有効・成行 pending は close→entry 順。共有 `_engine/backtest.py`。 |
| D6 | **★二刀エンジン（オフライン／リアルタイム）** | 同一の PineBroker ロジックを2つの足供給源で駆動。**オフライン＝履歴 OHLC バー（内蔵BT・golden一致）／リアルタイム＝形成中足の tick（ライブ・イントラバー指値を実現）**。戦略判断は両方とも確定足ごと（TV の `calc_on_every_tick=false`）。＝**TradingView の Strategy Tester／ライブと同じ二重構造**。 |
| D7 | **ブリッジ＝TVブローカー（完成済・忠実執行）** | ブリッジは出たシグナルを**バーに関係なく忠実に発注**する。ローカルは fill 通知・kabu 同期を作り込まない。ローカルが自前の建玉モデルを持ち（TV と同じ）、シグナルを正しいタイミングで出すことに専念。 |
| D8 | **時間足 15分固定** | 当面 15分のみ。将来拡張。 |
| D9 | **戦略は自己完結（ロジック+指標）・1フォルダ1戦略・ZIP配布／約定エンジンは共有** | 戦略フォルダ＝`strategy.py`＋`config.json`＋`manifest.json`＋`_lib`部品（指標）。**戦略の「ロジックと指標」が自己完結**（他戦略・他プロジェクトに依存しない）。**約定エンジン（PineBroker）はホスト共有＝戦略フォルダに入れない**（StrategyBuilder `_STRUCTURE.md` と同一思想＝バックテストは共有 `_engine`）。＝戦略は LocalEngine という土台の上で動く（TV 戦略が TV 上で動くのと同じ）。配布＝ZIP。登録＝Explorer でフォルダ選択（ZIPなら解凍→その場所を指定）。 |
| D10 | **ダッシュボード中心** | ①複数戦略登録 ②パラメータGUI＋**内蔵バックテスト（半年）** ③戦略ごと送出可否（「有効」チェックボックス）④**取引記録＝発火ベース（全戦略・常時・送出/enabled/約定の有無に無関係＝「発火したか」だけが基準・理想トレードの監査）** ⑤**自動運用**（起動＝記録開始／送出は「有効」のみ／起動・停止・仮想の各ボタンは廃止＝2026-06-18 改訂）。 |
| D15 | **★再起動はウォームアップ・リプレイで復元（TV 同一シーケンス）・記録は発火ベース（2026-06-29 改訂）** | 起動時に**履歴足を live と同一 `on_bar` でブローカー駆動（`warmup_replay`）し、現在建玉・出口（部分約定含む）・指標バッファを履歴から再構築**する＝TV がロードのたび履歴から戦略を再計算するのと同じ。これにより **BT(run_pine)≡live≡warmup が一致**し「BT／取引履歴／復元が噛み合わない」三者不一致を解消。snapshot/restore（旧 D15・2026-06-24 改訂）は**起動経路から不要**＝メソッドは残すが復元には使わず、建玉 JSON は受動記録（診断用）のみ。記録は発火ベース（送出/enabled/約定に無関係）。取引一覧は発火記録（新規↔決済）を建値時刻でペアリング。詳細＝[`2026-06-29_warmup_replay_session_ohlc_reactivate.md`](2026-06-29_warmup_replay_session_ohlc_reactivate.md) ①・[`03`](03_詳細仕様書.md) §E。 |
| D16 | **★セッション制御＝共通ライブラリ `session_lib`（プラットフォーム提供・2026-06-29）** | 「いつ約定してよいか」（締切窓の新規/決済停止・週末/祝日/大納会/SQ 直前の強制 flat）を per-bar・先読みなしで判定する単一ソース＝`app/feed/session_lib.py`（`flags`/`gate`）。戦略は `import session_lib`（ZIP 非同梱＝loader が `sys.modules` へ注入・一元管理・跨ぎ無し）。カレンダーは全外部化（`data/session_hours.json` era 対応＝15:15→15:45・16:30→17:00 込み＋`sq_calendar.json`＋`_market_hours`）。Pine 側は同一カレンダーの `KengetsuLib/2`＝**Pine BT＝Python BT＝ライブが同一シーケンスで一致**。ts は `_to_dt` で datetime/Timestamp/numpy.datetime64/str を統一（numpy.datetime64 で gating が静かに抜ける不具合を是正）。詳細＝[`2026-06-29_…md`](2026-06-29_warmup_replay_session_ohlc_reactivate.md) ②。 |
| D17 | **★登録/設定変更の自動再有効化（稼働中も止めない・2026-06-29）** | `register`/`update_registration`/パラメータ保存は `load_all()` で engine を作り直す（全戦略 ready=false 化）。旧版は `start()` のみが ready 化したため**稼働中に1戦略でも登録すると全戦略が再起動まで停止**＝ゼロの主因。改訂版は `load_all()` が「稼働中(was_running)」なら自動で `_activate_brokers`（warmup→ready→sender）を再実行し `running` 復帰＝**再起動不要で即反映**。feed コールバックは `self.engine` 動的参照（`_engine_on_tick`/`_on_confirmed_bar`）に統一し engine 差し替えに追従。enabled トグルは `set_enabled`＝sender 切替のみ（load_all 非実行＝安全）。詳細＝[`2026-06-29_…md`](2026-06-29_warmup_replay_session_ohlc_reactivate.md) ④。 |
| D11 | **BTデータ＝ローカル蓄積＋CSVマージ・半年** | 蓄積 parquet（full-time）を基本、不足分は外部 CSV をマージ。BT 期間は半年程度（直近市場で十分）。 |
| D12 | **ライブ約定タイミング** | 成行＝シグナル確定足で送出（≒次の約定機会）。**指値/逆指値＝形成中足の tick がレベルに触れた瞬間に送出**（イントラバー）。＝確定足の終わりを待たない。 |
| D13 | **★ろうそく足生成の観測挙動を正確保持** | tick→15分足の確定足／ダミー足／**板寄せ特別足（セッション末足）**／セッション境界クランプは観測挙動を保持。ロジック変更時もセッション末足だけは絶対に正確に（[`03_詳細仕様書.md`](03_詳細仕様書.md) §C・ユーザーが最も苦労した箇所）。**※2026-06-26：①板寄せ特別足（15:45/6:00）が実機で一度も出ない欠陥を是正（引け時クローズ扱いでも確定）／②板寄せ価格を実際の引け板寄せ約定値にする（ユーザー当初設計＝戦略が見る引け値を本物に）／③セッション時刻の単一ソース化。旧「一字一句保持」は本是正で更新（旧版は忠実再現の前提が崩れていた）。詳細＝§C。**　**※2026-06-27：市場OPEN判定を所有取引日ベース `is_open_at` に是正（早朝0-6時=前日の夜間／大納会は夜間なし／カレンダー駆動）＝「深夜0時以降ろうそく足が作られない」凍結バグの解消。`ohlc_processor` 本体は無傷（CLOSEDにする境界15:45/6:00は不変＝板寄せ+α と整合）。カレンダーは複数年マージ＋取得元URL外出し（§C.1.1/§C.1.2）。**　**※2026-06-29：OHLC 実値化＝ブリッジが board の始値(寄付)/高値/安値＋各時刻・気配数量・VWAP・前値比較を転送し、`live_feed`→`update_ohlc(op,op_t,hi,hi_t,lo,lo_t)`→各時刻が当バー内なら**真の寄付/高安**を採用（標本 close が逃す寄付・push 間の山谷を補正）。`on_tick(bar_open/high/low)` で初足成行を寄付約定・建ち注文を真の高安でイントラバー判定。未提供は従来動作（後方互換）。D13 のセッション末足/板寄せ/境界/executed_time は無傷。詳細＝[`2026-06-29_…md`](2026-06-29_warmup_replay_session_ohlc_reactivate.md) ③。** |
| D14 | **採用条件＝golden 一致＋実機可能** | 各戦略の BT が共有 golden（`run_pine_fast`）とトレード単位一致。trail（毎バー変わる出口）は先読み混入に注意・実機で取れる出口のみ（HighVol_Breakout は除外）。 |

---

## 3. 正本（しょうほん）の鎖

```
TradingView Pine（一次正本・TVで動く）
      ≡ ロジック厳密同一・約定は較正
Python 戦略（StrategyBuilder・golden）   ＝ run_pine_fast で4年/半年 BT・トレード単位一致
      ≡ 同一 on_bar・同一 PineBroker ロジック
ローカル実行（本エンジン）              ＝ オフライン=golden 再現／リアルタイム=tick 駆動で同等
```
- ローカル版は **Pine/TV を経由しない**（全ローカル）。Pine は上流の一次正本として外に在るだけ。
- リアルタイムは tick 粒度のため golden と完全一致はしない（D12・golden は基準値）。**同一価格パスを与えればオフライン＝リアルタイムが一致**することを検証で担保（[`03_詳細仕様書.md`](03_詳細仕様書.md) §B.5）。

---

## 4. 全体アーキテクチャ（要約・詳細は内部仕様）

```
┌───────────────────────── ローカル版ダッシュボード（司令塔・独立1枚）─────────────────────────┐
│  登録: Explorer で戦略フォルダ選択 → registered.json                                          │
│  設定: 戦略ごと config.json を GUI 編集                                                       │
│  検証: 内蔵バックテスト（半年・蓄積+CSV）→ 成績表                                              │
│  制御: 戦略ごと注文可否(「有効」✓)  ／  記録は全戦略・常時  ／  自動運用(起動と同時)            │
└───────────────┬───────────────────────────────────────────────────────┬───────────────────┘
                │ 制御・状態(JSON)                                        │ 成績(BTレポート)
                ▼                                                        ▼
  kabu ──tick──► ブリッジ ──TCP5000──► ┌──────────────── ローカルエンジン（ヘッドレス）──────────────┐
       ▲  (別製品・完成)                │ feed: tick→15分足(確定足/ダミー足/板寄せ特別足)              │
       │ Webhook(8001)                  │   ├─ on_bar_close(確定足) ─► ready全戦略.on_bar → 記録(常時)  │
       └──── web 注文 ◄──────────────── │   └─ on_tick(形成中足) ───► リアルタイム・ブローカー         │
              忠実執行                  │ broker(PineBroker): 成行=次足始値 / 指値・逆指値=tick イントラバー │
                                        │ webhook 変換: ポジ差分 → spec §9 →「有効」戦略のみブリッジへ注文 │
                                        └──────────────────────────────────────────────────────────────┘
                                                          ▲ オフライン駆動（内蔵BT）
                                                          └ 履歴OHLCバー → run_pine_fast → 成績
```

- **戦略は「足を受けて注文を返す」だけ**。約定（成行=次足始値・指値=イントラバー）はエンジン（broker）。記録（全戦略・常時）・ブリッジへの注文（有効戦略のみ）・並行はエンジン。
- **二刀**：内蔵BT＝オフライン（履歴バー）／ライブ＝リアルタイム（形成中足 tick）。**ロジックは1つ**。

---

## 5. モジュール構成（本拠・ベンダリング）

> 要約。**完全なフォルダ構成（製品ツリー・各ファイルの責務・ベンダリング配置・旧レイアウト移行）は [`02_内部仕様書.md`](02_内部仕様書.md) §12**。

```
N225LocalEngine/                    （製品ツリー・自己完結）
├── app/                            ローカルエンジン本体（ホスト）
│   ├── feed/                       ★ろうそく足生成（tick→15分足）＝ clone/feed をベンダリング・無傷保持
│   ├── engine/                     二刀エンジン（戦略ローダ・リアルタイムブローカー・webhook変換・並行）
│   ├── backtest/                   内蔵BT（オフライン駆動・半年・データマージ）
│   ├── dashboard/                  ローカル版ダッシュボード（独立1枚）
│   └── state/                      状態 JSON（registered.json / engine_state.json 等）
├── strategies/                     登録された戦略の置き場（各フォルダ＝戦略の自己完結ロジック・D9）
│   └── <戦略名>/                   strategy.py + config.json + manifest.json + _lib部品（指標）
├── design/                         本設計書一式
├── docs/                           ユーザー使用マニュアル等
└── pyproject.toml / uv.lock        uv（配布・将来 M6）
```
- **約定エンジン（PineBroker）はホスト共有＝`app/engine/` に1本**（オフライン driver＝内蔵BT／リアルタイム driver＝ライブ、いずれも同じ PineBroker ロジック）。**戦略フォルダには入れない**（StrategyBuilder `_STRUCTURE.md` と同一＝バックテストは共有）。
- ベンダリング元：`StrategyBuilder/strategies/_engine`（PineBroker＝ホストへ1本）・`_lib`（指標＝各戦略フォルダへコピー）／`N225StrategyAI/clone/feed,live`（feed・送出＝ホストへ）。**跨ぎ import ゼロ**（D1）。

---

## 6. 段階計画（マイルストン）

| M | 内容 | 完了条件 |
|---|---|---|
| **M1** | feed ベンダリング＋ろうそく足の無傷移植 | tick→15分足・確定足/ダミー足/**板寄せ特別足**が既存と同一挙動（[`03`](03_詳細仕様書.md) §C のテスト） |
| **M2** | 戦略ローダ＋オフライン driver（内蔵BTの中核） | 登録戦略を `run_pine_fast` で回し golden 一致（DT/MESA 等） |
| **M3** | リアルタイム driver（tickブローカー）＋webhook変換 | 履歴バーを合成 tick で流し **オフライン＝リアルタイム一致**／spec §9 webhook 正当 |
| **M4** | ダッシュボード（5機能） | 登録・パラメータGUI・内蔵BT・実行可否・dry-run・2段階実行/停止が動作 |
| **M5** | 複数戦略 並行運用＋dry-run ペーパー | 複数戦略同時・順次≡並列・dry-run で仮想売買ログ |
| **M6** | 配布パッケージ化（uv・物理ベンダリング・ZIP戦略） | `uv sync` 一発・戦略 ZIP 単体で登録動作 |
| **M7（将来）** | ターンキー・インストーラ | 埋め込み Python＋Inno（需要を見て） |

- 並行して **ユーザー使用マニュアル**（[`../docs/USER_MANUAL.md`](../docs/USER_MANUAL.md)）を各 M の完了ごとに追記（D10 の各機能を操作手順化）。

---

## 7. 不変条件（事故防止・損益直結・要約／詳細は §III）

1. **ろうそく足生成は無傷**。特に**セッション末足（板寄せ特別足）・境界クランプ・executed_time 戻し**を改変しない（D13・[`03`](03_詳細仕様書.md) §C）。
2. 検証済み戦略・golden・PineBroker を**改変しない**（コピーして使う）。
3. warmup が戦略の宣言本数（manifest warmup_bars・2026-08-10 改訂＝戦略ごとにリプレイ本数を変える）未充足は**発注しない**（ソフトゲート）。
4. **先読み禁止**：戦略判断は確定足まで。リアルタイムの tick fill は「実際にレベルへ触れた」事実のみ（未来を見ない）。
5. TV版コードを **import・共有しない**（D1）。資産はコピー同梱。
6. OHLCStorage は**読込失敗でファイルを消さない**。

---

## 8. 改訂履歴

- **v2.2（2026-06-29）**：実トレード運用の是正4点。**①建玉復元を `warmup_replay`（起動時に履歴を live と同一 on_bar で再生し建玉・出口・指標を再構築＝TV 同一シーケンス）へ置換**し snapshot/restore（D15）を起動経路から廃止＝BT≡live≡warmup 一致。**②セッション制御を共通ライブラリ `session_lib` 化（D16）**（締切窓/週末/SQ 強制 flat・カレンダー外部化・ts を numpy.datetime64 含め統一）。**③ろうそく足 OHLC 実値化（D13 追補）**（ブリッジが寄付/高安+時刻・歩み値を転送→真の寄付/高安・on_tick 拡張）。**④登録/設定変更の自動再有効化（D17）**＝`load_all` が稼働中なら自動で再 warmup→ready 復帰（旧版は稼働中の登録で全戦略が再起動まで停止＝終日ゼロの主因）。詳細＝[`2026-06-29_warmup_replay_session_ohlc_reactivate.md`](2026-06-29_warmup_replay_session_ohlc_reactivate.md)。回帰＝`tests/test_warmup_replay.py`・`test_register_while_running.py`・`test_offline_eq_realtime.py`・`test_trade_list_eq_bt.py`。01/02/03 同期。
- **v2.1（2026-06-23）**：**取引記録を発火ベースに明確化**（送出/enabled/約定の有無に無関係＝「発火したか」だけが基準）。**再起動はリセット＝建玉/TP を復元しない**（旧 `prime_with_trading`／`_record_reconstructed_open` を撤去・D15）。取引一覧は発火記録のペアリング（建玉記録なし＝計算不可・未決済＝open 表示）。BT 取引一覧 ≡ 取引記録の取引一覧 を回帰テストで担保（`tests/test_trade_list_eq_bt.py`）。設計ドラフトの整理＝旧 v0.1（`strategy_lifecycle_standard.md`／`local_engine_design.md`）を `design/_archive/` へ集約（現役の正本は master＋01/02/03 の4点のみ）。01/02/03・USER_MANUAL を同期。
- **v2.0（2026-06-16）**：全面改訂。設計すり直し（ユーザー）。BatchStrategyAdapter 破棄→**新仕様 on_bar 戦略**（D3）。**二刀エンジン（オフライン/リアルタイム・D6）**で**イントラバー指値**を実現（TV忠実）。**ブリッジ＝TVブローカー（完成済・D7）**。**戦略は完全自己完結・ZIP配布（D9）**。**ダッシュボード中心・5機能（D10）**＝複数登録/パラメータGUI＋内蔵BT(半年)/実行可否/dry-run/2段階実行制御。**ろうそく足・セッション末足の無傷保持（D13）**。外部/内部/詳細の3仕様書に分割。
- v1.1（2026-06-14）：BatchStrategyAdapter 版（`design/_archive/` に退避）。
- v1.0（2026-06-14）：3ドラフト統合・初版正本。


---

## 追記 2026-07-02：稼働中 load_all の再warmup 非同期化（GUIフリーズ修正）＋運用ボタン監査
- **症状**：稼働中に［＋追加］［✎登録の編集］［⚙パラメータ保存］を行うと GUI が約42秒「応答なし」（全戦略再warmup＝実測42秒・うち MESA5_Portfolio 27秒 が GUI スレッドで同期実行されていた。2026-06-29 の「再起動不要化」パスのみスレッド化漏れ）。
- **修正**（`app/engine/controller.py`）：
  1. `load_all` の再有効化ブロックをワーカースレッド化（起動時 warmup と同じパターン）。warmup 完了まで `engine.running=False`＝発注しない安全動作は従来どおり。`_rewarm_lock` で直列化＋世代チェック（最後の load_all が勝つ）＋ `_rewarm_active` フラグ（進行中の連続保存でも「稼働中」と判定＝再有効化の取りこぼし防止。ヘッドレステストで検出した事故モード）。
  2. `stop_bridge` をスレッド化（terminate→wait が最悪約8秒 GUI を止めるため）。
- **検証**（ヘッドレス・隔離 state・VirtualSink）：load_all 呼出 23ms（旧42,000ms）／再warmup 56秒後に running=True・6/6 ready／連打（二連続 load_all）でも最終世代が正しく有効化。
- **運用8ボタン監査の結論**：BT・データ管理・起動時warmup・カレンダー・再最適化は既にスレッド化済＝設計思想は正しく、漏れは本パスのみ。残課題（後日）＝①注文送信の同期HTTP(timeout5s)がフィードスレッド上→送信キュー化（最優先）②確定足ファンアウトのワーカー化（戦略数スケール）③差分warmup（42s→3s）。


## 追記 2026-07-02（第2弾）：差分リロード reload_one（42秒→数秒・他戦略無停止）
- **動機**：稼働中の登録/設定/パラメータ変更が「全戦略再構築＋全戦略再warmup（42秒・その間 全戦略の判定停止）」だった。
- **実装**：
  - `LiveEngine.upsert(name, rb, enabled, ready)`＝1戦略の**原子的差替**（新 dict を作って参照スワップ。feed スレッドの `_processing()` 列挙と「dictionary changed size during iteration」競合を作らない）。
  - `controller._warm_one()`＝`_activate_brokers` から per-broker 処理を抽出（load_all と差分で共用）。
  - `controller.reload_one(name)`＝当該1戦略だけフレッシュ読込→**旧実体が生きたまま裏で warmup**→完成後に upsert で瞬間差替（`_rewarm_lock` で全体再warmupと直列化）。engine 未稼働時は load_all に委譲。
  - 呼出側：`register()`／`update_registration()`／ParamForm の on_saved を reload_one へ変更。
- **効果（ヘッドレス実測）**：呼出1ms・差替完了 6.8秒（DT）・**他5戦略の実体維持＝無停止・running=True 維持**。load_all 経路の回帰なし（再テストパス）。


## 追記 2026-07-02（第3弾）：①送信キュー化 ②tick/確定足ディスパッチワーカー化
- **①送信キュー**（`bridge_sender.py`）：`BridgeSender.send()` を「共有キューに積んで即返る」に変更。
  単一ワーカー（daemon・例外で死なない）が同期 POST を実行＝**全戦略の送信順序を FIFO で完全保存**。
  従来はフィード系スレッド上の同期 POST（timeout5秒）で、ブリッジ遅延時に tick/確定足処理が最大
  5秒×シグナル数停止するテールリスクがあった。`flush(timeout)` を `controller.stop()` から呼び
  終了時の未送出を掃き出す（ベストエフォート）。ログ通知（[売買・本番]/注文エラー）は従来同一。
- **②ディスパッチワーカー**（`engine.py`）：`on_confirmed_bar`/`on_tick` は**キューに積むだけ**
  （確定足 enqueue 実測1ms・tick 0.005ms）。単一ワーカー `le-dispatch` が直列処理＝
  受信系スレッド（TCP recv／バータイマー）を fan-out でブロックしない＋**従来の
  「recv スレッドとバータイマースレッドが同一ブローカーへ同時侵入し得る競合窓」も解消**（直列化）。
  建玉スナップショット保存は after コールバックで fan-out 完了後に実行（順序維持）。
  キュー満杯時：確定足は2秒待って警告ログ（原則落とさない）・tick は破棄（最新性優先）。
- **検証**（ヘッドレス・全パス）：遅いブリッジ（2秒応答）でも send×3 が 0ms・順序保存・全件配送／
  確定足 enqueue 1ms・fan-out 191ms はワーカー実行・after 順序正常／tick200件 enqueue 1ms／
  回帰＝rewarm・reload_one 両テスト再パス。py_compile OK。
- これで受信＝積むだけ・計算＝le-dispatch・送信＝bridge-send・保守＝le-rewarm/le-reload の
  **責務分離が完成**（戦略数スケールとブリッジ遅延の両テールに耐性）。
