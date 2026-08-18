# N225LocalEngine — _START_HERE（ローカル版・全ローカル戦略実行基盤・2026-06-13 新設）

> 🚫 **【最優先】発注に関わる修正は、実トレードでテストしてから GitHub を更新する**（2026-08-18 ユーザー指示）
> 順序＝**①修正 → ②再起動して実トレードで確認 → ③合格したら push → ④Release まで通す**。
> **③④はセット。**ソースだけ push して Release を作らないのは中途半端で、ソースと配布物が食い違う。
> ローカル版の完了までの流れ＝`sync_local.ps1` → `runtime-local` commit → push →
> `release_local.ps1` → DevConsole「GitHub公開（Release）」で新版公開。


> ✅ **2026-08-18 実施：「シークレットコード」→「パスフレーズ」に改称**（ユーザー決定・ブリッジ側の名称に統一）
> 同じ 1 つの値を、ブリッジは「パスフレーズ」、TradingView 版はアラート本文の `passphrase`、
> ローカル版だけ「シークレットコード」と呼んでいたため統一した。**戦略ごとではなくエンジン全体で 1 つ**
> の値である点は変更なし。設定キー（`passphrase`）・取得経路（ブリッジから DPAPI 復号）も変更していない。
> 画面表示・ログ文言のみの変更で、**反映はローカルエンジンの再起動後**。
> 変更＝`app/dashboard/{settings,register}_dialog.py`・`app/engine/controller.py`・`design/01_外部仕様書.md`
> ＋配布版 `distribution/runtime-local/engine/`。
> **残：ブリッジ操作マニュアルの記述変更**（`manual/01_setup/06_webhook.md` の対応表ほか）は
> **すべての作成が終わったあとに行う**（ユーザー指示）。それまで現状のまま。


> ★★**2026-07-02：スレッド/並行性の大改修（3点セット・検証済・反映は再起動時）。**
> ①稼働中 load_all の再warmup **非同期化**＋**差分リロード reload_one**（登録/編集/パラメータ保存＝対象戦略のみ背景再構築・他戦略無停止・GUI固まらない。旧＝42秒フリーズ「応答なし」の根治）
> ②**注文送信キュー化**（BridgeSender→共有FIFO＋bridge-sendワーカー。ブリッジ遅延でもfeed不停止・送信順序保存）
> ③**tick/確定足ディスパッチワーカー化**（受信系は積むだけ→le-dispatchが直列fan-out。recv/タイマー両スレッドの同一ブローカー同時侵入の競合窓も解消）
> ＋CSV取込の出来高を**列名解決**（TVエクスポートで指標列が挟まっても誤読しない。運用＝15分タブに出来高インジ載せっぱなし）。
> 記録＝`design/N225LocalEngine_詳細設計書.md` 追記3本／`docs/devlog/2026-07-02.md`／mydocs 5冊改訂／USER_MANUAL v0.3。
> 旧 `docs/ロジック解説書.md` は削除（mydocs に集約）。

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
> ※ 大原則：**プロジェクト同士は跨がない**（各自己完結・他プロジェクトを import しない・共有はコピー同梱）。以下の旧記述（M1-M5 完了報告）は破棄前提で読むこと。

## ★現在地（2026-06-30）— warmup 5/6 問題＝MESA5_Portfolio ロード失敗を修正（param_form の dict 文字列化バグ）
> 詳細＝`docs/devlog/2026-06-30.md`（root）。LocalEngine のみ（自己完結）。
- **症状**：起動時、6戦略登録なのに **warmup メッセージが5戦略分**しか出ない（MESA5_Portfolio だけ無い）。
- **真因（連鎖）**：`config.json` の `"session"` が **repr 文字列 `"{'enabled': True}"`** に化けていた→`strategy.py:71` が dict 前提で `.get()`→`'str' object has no attribute 'get'`→`load_all` が `読込失敗 … continue`→ブローカー未生成→`engine._brokers` に入らず warmup 行も出ない（engine_state.json も5戦略）。
- **発生源**：GUI パラメータフォーム `param_form.py` の `_field` が **dict を `else`（文字列）分岐で `str()` 化**し、保存時に文字列で書き戻していた。＝**MESA5_Portfolio のパラメータ画面を一度「保存」しただけで config が壊れる**。Builder 正本コピーは正常＝運用コピーのみ GUI 保存で破損と確定。
- **修正（3点・全て LocalEngine 内）**：①`config.json` を `{ "enabled": true }` へ即復旧。②`param_form._field` で **dict も list 同様「読み取り専用・保存時は原値保持」**（ネスト dict を将来にわたり壊さない）。③`strategy.py:71` は session が dict でなければ既定 `True` フォールバック（堅牢化）。検証＝load 成功（session_enabled=True・サブ4戦略）・py_compile OK。
- **解説ドキュメント整備（同日午後）**：`mydocs/` に LocalEngine 解説 **4部作**を作成・拡充（①ランタイムフロー＝前日／②Python戦略⇄エンジン＝新規／③周辺サブシステム＝新規／④運用・ダッシュボード＝新規）。②には**エンジン視点**の §5-0（戦略3部分の所在）＋§6（戦略ライフサイクル＝エンジンが戦略に触れるのは生成/reset/属性注入/on_bar/orders回収の5種だけ）を追補。詳細＝`docs/devlog/2026-06-30.md`。
- **次の一手（引き継ぎ・優先順）**：
  1. **【最優先】LocalEngine 再起動**（or GUI「登録/設定変更を反映」）で MESA5_Portfolio が warmup→**6戦略すべて記録対象**になる。**現状は5戦略のまま稼働中**（config 修正はディスク反映済だがプロセス未反映）。
  2. **配布反映（保留中）**：同 param_form バグが `distribution/runtime-local/engine/app/dashboard/param_form.py` にも存在。**ユーザー判断で「まだ修正が続く見込み」のため保留**。今後の修正とまとめて `distribution/sync_local.ps1`＋販売リポ（`N225AutoTrader-Local`）push を実施（push は外部公開なので要確認・[[feedback_bridge_fix_always_commit]]）。
  3. 解説の残：各図の粒度調整・特定戦略（DT/TSI/CMF/Momentum・MESA5合成）の掘り下げは要望ベース。

## ★現在地（2026-06-27 午後）— TV照合で「Python戦略=TV Pine 一致」確認＋TV CSV自動マージ復活
> 詳細＝`docs/devlog/2026-06-27.md`（root・16:00〜）。今週はデータ整備、来週から本格テスト。
- **★Builder Python戦略 vs TradingView 照合（新規 `tests/verify_tv_match.py`）**：TVの15分足OHLCV→`run_pine_fast`→TVのStrategy Testerトレード一覧とエントリー/決済イベント照合。**全5戦略でentries/exits 97〜100%一致＝Python戦略はTV Pineと実質一致（移植は忠実）**。当初 DT/MESA の決済が乖離→**原因は config の `tp_mode` がE(ATR)のままだった**（ユーザーがTV合わせにC へ手動修正→99%へ）。＝食い違いは戦略バグでなく**パラメータ設定差**。config値はユーザーがTV合わせに調整する前提（[[feedback_config_params_intentionally_tuned]]）。
- **★ライブ指値発火(tick)の検証**：`live_feed→ohlc_processor.on_tick→engine.on_tick→RealtimeBroker→_fill_resting` は完全配線。**J-3（offline≡realtime）スクリプト実行で62 fills完全一致（指値intrabar36件再現）＝指値tick発火の仕組みは正しい**。ライブで食い違うとすれば**足データ精度**（指値は高安に最敏感・昨日の足修正の範疇）。※`test_offline_eq_realtime.py` はpytest収集バグで自動実行されていない＝要pytest化。
- **★TradingView CSV 自動マージ復活**（データ整備・ユーザー依頼）：取込3形式＝①kabu CSV ②225Labo xlsx ③**TV CSV**（先頭列`time`+09:00実時刻・**settlement変換しない**・`is_tv_csv`で自動判別）。`_normalize`が`+09:00`をnaive JSTに正規化。TV足は正本→**CSV優先で重複バーを上書き**＝tick由来の蓄積足をTV精度に補正（TV保有者向け・非保有はkabu/225Labo）。変更＝`data_provider/data_import/data_dialog`＋`USER_MANUAL §5.5`＋`design 03 §F.0`。テスト`test_data_provider.py`4 passed。
- **次の一手**：(1) 来週＝TVマージした蓄積足でBT精度確認・ライブ通し。(2) ✅済＝`test_offline_eq_realtime.py` をpytest化（指値発火の自動回帰が復活・全72テスト収集OK）。(3) 観測「MESAがTVにない取引」＝kabu足のデータ差→TV CSVマージで蓄積足をTV値に補正すれば解消方向。(4) 配布反映は保留（ユーザー判断＝もう少しリアルタイムで実践してから）。

## ★現在地（2026-06-27）— 深夜0時以降ろうそく足が作られない凍結バグ是正＋カレンダー仕様確定
> 詳細＝`docs/devlog/2026-06-27.md`（root）。LocalEngine のみ（自己完結）。設計反映済＝design 01/02/03/master・USER_MANUAL §5.6。
- **★真因**：市場OPEN判定が**早朝0:00–6:00を当日の暦日で判定**＝夜間が日付をまたぐ**金→土・祝日前→休場日**の早朝にナイトを取りこぼし、`update_ohlc` が全tick破棄＋タイマー不発で足窓が[23:45,00:00]凍結（平日夜は翌日平日で露見せず・金夜→土が初顕在化）。tick受信自体は朝6時まで生きていた。
- **切り分け**：**大元のバグ**（統合は大元を直import・配布版も関数本体一致＝3経路共通）。**昨日(06-26)の修正とは無関係**（昨日は判定ロジック不変・木夜→金は正常）。
- **修正①**＝`_market_hours.is_open_at`（所有取引日ベース・JPX公式準拠）：早朝0-6時=前日の夜間／大納会は夜間なし（派生）／年末年始(1/1-1/3,12/31)／土日／カレンダーの実施しない。`ohlc_processor`本体は無傷＝CLOSEDにする境界(15:45/6:00)不変で**板寄せ+α（AUCTION_WAIT_SEC=12秒・実引け値/出来高）と整合**。むしろ凍結で出ていなかった土6:00板寄せ足も出る。
- **修正②＝カレンダー・ライフサイクル確定**：取得元=JPX祝日取引（唯一の権威・jpholiday不採用）／**複数年マージ取得**（実測2026+2027・旧は当年限定で2027を捨てていた）／CSV=`date,name,status,confirmed,source,fetched_at`（更新日自動・後方互換）／**取得元URLをsettings.jsonへ外出し**（将来のURL変更は[📅カレンダー]ダイアログで手動設定・失敗時は「URLが変わった可能性…」案内）／**起動時のみ鮮度判定→[📅]ボタン赤+⚠＋ログ色分け**。両ダッシュボード（単体・統合）に[📅カレンダー]追加。
- **検証**：pytest 53 passed（test_market_hours 39＋test_candle 14無傷）・py_compile 7ファイル OK・実JPX取得確認。実`market_Calendar.csv`を新スキーマ+2027へ更新（旧=`.pre_2027_bak`）。
- **次の一手**：(1) 安全帯で **LocalEngine 再起動**＝修正の有効化。(2) 配布版 `runtime-local` へ `sync_local.ps1` 同期（販売リリース・指示待ち）。(3) 任意＝`design/calendar_lifecycle_design.md` 正式文書化・`.pre_2027_bak` 削除。

## ★現在地（2026-06-26）— ろうそく足 板寄せ特別足（15:45/6:00）欠落バグ修正＋セッション時刻の決め打ち撤去
> 詳細＝`docs/devlog/2026-06-26.md`。LocalEngine のみ（自己完結・他プロジェクト非依存＝StrategyBuilder へは展開しない）。
- **★15:45/6:00 足が出ていなかった真因**：板寄せ特別足の生成が壁時計 `finalize_candle` だけにあり、かつ `bar_timer_loop` が `is_market_open()` でゲート＝引けの瞬間は市場クローズ扱いで確定処理が走らず（データ時刻ロールも市場ゲートで引け以降 tick を弾く）→ セッション末足がどちらの経路でも確定されず板寄せが永久に出なかった。テスト T4 は実機経路を通らず緑のままで回帰がすり抜けていた。
- **修正（[app/feed/ohlc_processor.py](app/feed/ohlc_processor.py)）**：壁時計ループを `_timer_check` に分離し、`is_market_open()` **または `_is_session_close(bar_end)`** で確定＝**引けでクローズ扱いでもセッション末足を確定→板寄せ特別足を発火→窓前進**。板寄せ生成を `_emit_closing_auction` に分離・`_last_auction_dt` で二重発火防止。引け値は `latest_price`（T4 契約どおり）。
- **★決め打ち撤去（[[feedback_no_hardcoding]]）**：`get_bar_times` の 8:45/15:45/17:00/6:00 を撤去し、市場時間の**単一ソース** `_market_hours`（公開定数 `DAY_START/DAY_END/NIGHT_START/NIGHT_END` を追加・`MarketSessionManager` と同一定義）から取得。板寄せ判定時刻も同ソース由来。制度変更は単一ソース1箇所で全箇所追従。
- **★板寄せ特別足の価格＝実際の引け板寄せ約定値／出来高＝引け板寄せ tick の volume**（V=0固定にしない・2026-06-26）。`update_ohlc` に引け板寄せ tick 経路を追加（クローズ扱いでも1本受け入れ）・`AUCTION_WAIT_SEC`=12秒待ち・`finalize_candle` の `sleep(10)` 撤去。引け tick 無しの静かな引けのみ V=0（日次マージで kabu 実出来高に上書き）。テスト T13/T14 で固定（14/14 PASS）。
- **★板寄せ価格を実際の引け板寄せ約定値に（完全版・ユーザー当初設計）**：`update_ohlc` に引け板寄せ tick 経路を追加し、引け後最初に届く約定をクローズ扱いでも1本だけ受け入れて実引け値で特別足を立てる（通常足 close=引け直前値・板寄せ足=実引け値の別2本）。`_timer_check` は `AUCTION_WAIT_SEC`=12秒 待ち、来ない静かな引けのみ `latest_price` フォールバック。`finalize_candle` の `sleep(10)`（lock 保持で待ちが空振り）は撤去。
- **検証**：`tests/test_candle.py` **14/14 PASS**（T13 実引け値・T14 二重発火なし／T10 クローズ中フォールバック・T11 ゲート過拡張防止・T12 二重発火防止）。`py_compile` OK。**フル pytest はライブ中ゆえ未実行**（test_controller の送出回避＝2026-06-24 教訓）。
- **次の一手**：反映は次回 LocalEngine 再起動から（稼働中プロセス無影響）。残＝(1) kabu が引け板寄せを post-15:45/6:00 tick で送るかライブログ確認（送れば実引け値・無ければ自動フォールバック＝どちらでも板寄せ足は1本出る）／(2) 安全帯でフル pytest 回帰。配布は 2026-06-24 一括スケジュールに合流。

## ★現在地（2026-06-24 夜）— Pine↔Python 照合完了・ZigZag/over-under を Pine 厳密一致に修正・次は実トレード＆休日データ比較
> 詳細＝`docs/devlog/2026-06-24.md` 末尾。MESA 解析書＝`N225StrategyBuilder/strategies/MESA_Stochastic/design/V7_8_FibSync_3Split_Pythonロジック解析.md`。
- **ユーザー指摘「Python が Pine と一致していない」を全面照合**：MESA 7-8-3 Pine と Python（strategy.py＋_lib）を1:1 でコード突合し、5戦略×5 Pine を照合。
- **修正した実ロジック差（2件・5戦略共通基盤に反映）**：
  - **① ZigZag 同値タイ**：`_lib/zigzag.py` の `highest/lowest_bars_offset` を Pine `f_highestbars/f_lowestbars`（新→古走査・狭義比較＝タイは現在バー寄り）に厳密一致（旧は古い側＝高安同値足で zh/zl が反転）。4y BT：MESA 626/2.40→633/2.49 等、全5戦略でトレード変化・全年+維持（commit d9402b3）。
  - **② over/under クロス前バー比較**：`lb[i]/ub[i]`→`lb[i-1]/ub[i-1]`＝Pine `ta.crossover/crossunder` 厳密一致。phase 転換足の縁ケースで 4y BT 不変（commit 9989374）。
- **差でなかった（一致確認）**：MESA計算/signup/phase/**FibSync（V7_8 dn 新安値無効化含む・5 Pine 一字一句同一）**/4-state/3Split/fib基準ピボット/zz_p1。共有 fibsync/oscillator/signup/phases.py は正当。**前段オシレーターのみ設計どおり戦略別**（HP48：MESA/DT/Mom 有・TSI/CMF 無）。
- **★既知のロジック差はゼロ**。`tests/test_offline_golden.py` 再ベース（DT n=1005/PF1.72）。5戦略 ZIP 再生成・work=確定版=LocalEngine 同期。休日検証ツール `strategies/_engine/verify_tv.py` 新設。
- **★config の"値"差は指摘・修正しない**（ユーザーが BT で現市場に調整。Pine 既定/golden と違って当然）＝memory [[feedback_config_params_intentionally_tuned]]。照合は"ロジック/パラメータ集合"のみ。
- **★次の一手（スケジュール・ユーザー確定）**：(1) **平日：実トレードでテスト**（LocalEngine 再起動で修正コード反映＝config はユーザー値のまま）。(2) **休日：同一データ比較**＝TV 6ヶ月バー＋kabu 6ヶ月で `verify_tv.py` 出力を TV Strategy Tester と1件ずつ照合→残差は「データ差」と断定。(3) 照合OK後に配布反映（ブリッジ足分離＋Release ZIP 版上げ）。

## ★現在地（2026-06-24）— ローソク足 価格時刻/売買高時刻 分離・Momentum移植は忠実（残差=データ差）
> 詳細＝`docs/devlog/2026-06-24.md`。設計＝[`design/candle_price_volume_decouple_2026-06-24.md`](design/candle_price_volume_decouple_2026-06-24.md)。
- **★建玉復元を再設計（D15 改訂・6/23 の「復元しない」を撤回）**：夜に建てた玉を翌朝の再起動でリセットすると決済（TP/反対サイン）が二度と発火せず管理不能になる欠陥。→ **永続スナップショット（`app/state/positions/<name>.json`）から建玉＋出口状態を復元**。ブリッジ突合なし（実建玉を読む手段がない・自分の永続モデルを信頼。停止中の外部決済はブリッジ側建玉管理が安全処理）・**enabled/disabled 両方**・**filled_ids 復元で TP 二重決済防止**・履歴再生しない・size≠0 で新規再発火なし。`RealtimeBroker.snapshot()/restore()`＋`controller`（on_event/確定足ごと保存・warmup 後に復元）。設計＝[`design/position_restore_redesign_2026-06-24.md`](design/position_restore_redesign_2026-06-24.md)・テスト `tests/test_reconstruction.py`（round-trip/二重決済防止）GREEN。D13 無傷。
- **★60m忠実化を全5戦略へ展開済**（DT/MESA/TSI/CMF/Momentum・和集合newbar・各 BT PF≥1.5全年+・格上げ→ZIP→LocalEngine）。※ZIP デプロイで config が確定値へ上書き＝ユーザーが TV 合わせに再設定（後 test_offline_golden 再ベース）。
- **★ローソク足の40円ズレ＝根本原因特定・修正（設計＋実装）**：ブリッジが価格と出来高を1つの timestamp で兼用し、出来高ある tick を**売買高時刻**でバー割り当て→正時境界で**始値/終値も隣バーへ誤配置**（kabu と15〜155円差）。**修正＝価格(OHLC)は価格時刻バー・出来高は売買高時刻バーへ分離**。LocalEngine 実装済（`ohlc_processor.update_ohlc(..., volume_time=None)`＋`live_feed`・**後方互換・D13無傷・test_candle T8/T9 追加で全9 PASS**）。ブリッジ `.cs` 編集済（`timestamp`=価格時刻＋`volume_time` 追加）。
  - **★2026-06-24 早朝（3:45窓）でブリッジ Debug 再ビルド完了（0 Warn/0 Err）**＝私用ダッシュボードが起動する Debug exe に反映済み。**ソースは3製品とも push 済み**（dev: bridge `517bb42`／SB `9f77776`(ローカルのみ)・runtime: simulator `c1281f4`／production `5019a21`／local `474b38f`）。`sync_local.ps1` を「docs は USER_MANUAL のみ同梱」へ修正し私用 `ロジック解説書.md` の配布混入を停止。**配布 ZIP（購読者DL）は未更新＝昨日版（kabu 足照合 OK 後に版上げ＋`-BuildBridge` で Release）**。次セッションで kabu CSV と再照合（境界±5円以内）。詳細＝devlog/2026-06-24 末尾。
- **Momentum_Combo 移植検証＝Pine 忠実と確定**：オシレーター/signup/エントリー4state/3Split/sync/TP/`f_zigzag`/`len_60m_bars` すべて Pine 一致。**残差は移植でなくデータソース差（kabu vs TV の OHLC 5〜40円差）**。60m `newbar_60m` を `ta.change(time('60'))` 忠実＝**「正時 ∪ セッション開始足」の和集合**へ修正（TV 60分足は正時アライン・実データ確認）。`_lib`/Momentum/LocalEngine 同梱に適用済。
- **共有エンジン**：StrategyBuilder `_engine` ≡ LocalEngine `app/engine`（PineBroker/driver/contract 同一・検証済）。旧 close-fill `BacktestRunner`（dead code）削除。ルール＝authoring標準 §7.1（汎用・同一性）。
- **教訓**：乖離の原因を移植コードと決めつけず A/B・実データで切り分ける／**原因確定前に格上げ・配布しない**（60m で順序違反→是正）。

## ★現在地（2026-06-23 夜 確定）— 発火ベース記録に確定・建玉/TP復元を撤去 ※建玉復元は 2026-06-24 に再導入（下の「復元しない」は撤回）
> ⚠️ この節の「再起動はリセット・建玉/TP 復元しない（D15）」は **2026-06-24 に改訂・撤回**。現行＝永続スナップショットから復元（上の 2026-06-24 ブロック参照）。発火ベース記録の原則は維持。
> 詳細＝`docs/devlog/2026-06-23.md`（22:00〜22:42 セッション・※当日はセッション断で未記録→2026-06-24 復元追記）。私用の内部解説＝**mydocs の LocalEngine 解説5冊に集約**（旧 `docs/ロジック解説書.md` は 2026-07-02 に削除・重複解消）。
- **設計確定（蒸し返さない）**：LocalEngine は**ポジション管理をしない**。TradingView の「戦略＋アラート」役として、**発火（シグナル）を忠実にブリッジへ出し、その発火を記録するだけ**。実弾の建玉整合は**ブリッジ（別製品）が吸収**。
- **再起動はリセット**＝建玉も TP も**復元しない**。理由＝停止中に価格が動くと旧 TP 値が現在値とズレて**誤発火**するため（リセットが正）。持ち越し玉の TP は発火させない＝記録もしない。記録は「発火したか」だけ。
- **撤去**：同日午後に入れた「建玉復元 A案」（旧 `prime_with_trading`／`_record_reconstructed_open`）をユーザー指示で撤去。`controller.start` の warmup は**指標バッファを温めるだけ（flat）**に戻した（[controller.py:581-586](app/engine/controller.py#L581)）。
- **新規テスト** [`tests/test_trade_list_eq_bt.py`](tests/test_trade_list_eq_bt.py)：内蔵BT取引一覧 ≡ ライブ記録経路の取引一覧（MESA・確定足の高安約定＝offline と同条件）。2026-06-24 実走 **22 passed / 1 failed**（fail は既知・意図的な DT golden 不一致のみ＝回帰なし）。
- **ドキュメント整合済**：設計 01/02/03/master・USER_MANUAL・本書・ロジック解説書。
- **未反映（次の一手）**：**配布反映**＝runtime-local の head は v2.0.1（`4d73e97`・午後の復元版）で、**この夜の撤去変更は未 sync/未 push**。ライブ動作確認後に `sync_local.ps1`→runtime-local push（必要なら版 bump）。
- **確定（蒸し返さない）＝DT パラメータ／golden**：全5戦略の config.json は 2026-06-22 に**現行 TradingView 合わせへ変更＝最終確定**。旧4年 golden（DT n=599）は役目を終え、`tests/test_offline_golden.py` は **2026-06-24 に現行 config の確定スナップショット（DT n=984/PF1.69）へ再ベースライン済み＝PASS**。**「DT golden 貼り直し判断」は解決済みで、今後この件を未決事項として持ち出さない。**

## ★現在地（2026-06-22 追記）— ブランド名整合＋データ自動管理2件
> 詳細＝`docs/devlog/2026-06-22.md`。
- **ローカル版**：`_focus_existing` 既定タイトルの変更漏れ修正（旧`ローカル戦略実行`→`N225AutoTrader-Local`・[dashboard.py:461](app/dashboard/dashboard.py#L461)）。タイトル名は全箇所一致。
- **TV版ダッシュボード**（別製品・`n225_brokerbridge_dashboard.py`）：表示名 `N225BrokerBridge`→**`N225AutoTrader-TradingView`**＋LED群を右寄せ（重なり防止）。内部名（AppUserModelID/クラス/exeパス）は不変保護。**残＝`sync_production.ps1` で配布反映→push 未実施**。
- **③CSV取込フォルダ自動退避**：取込時に `data/csv_import/` の `.csv` を**最新5本残し**古いものを `_archive/` へ移動（[data_import.archive_old_csvs](app/backtest/data_import.py)・`CSV_KEEP=5`）。
- **④取引アーカイブ自動削除**：起動時に四半期アーカイブ `trade_archive_*.csv` を**直近8四半期（約2年）残し**それ以前を完全削除（[controller.prune_old_archives](app/engine/controller.py#L197)・[dashboard.py:516](app/dashboard/dashboard.py#L516)）。これで `data/history/` の無限増加を解消。
- USER_MANUAL §5.5/§8.5 追記済。保持数（5本・8四半期）は定数で変更可。

## ★現在地（2026-06-21 追記）— ブリッジ出来高（Volume）追加・ミニ運用確定・確定足 OHLCV 表示
> 詳細＝`docs/devlog/2026-06-21.md`（夜の継続セッション）。
- **データ＝常に日経225ミニ1本**（執行はミニ/マイクロ独立）＝運用の決定事項。kabu CSV はミニチャートから出力（マイクロと混ぜない）＝`docs/USER_MANUAL.md §5.5` に明記。
- **ブリッジ出来高修正（実装・ビルド・dev commit 済 `b1c03af`）**：board の `TradingVolume`(当日累積)/`TradingVolumeTime` を抽出し、**ミニのみ転送＋売買高時刻が進んだ時だけ累積増分を計上**（受信側 `OHLCManager` は無変更で既に出来高対応）。発注経路は無影響。ノウハウ＝`N225BrokerBridge/docs/adapters/kabu.md §10`。
- **確定足 OHLCV 表示**：`app/engine/controller.py` の on_bar_close ラッパで「確定足 … 始値/高値/安値/終値/出来高」をダッシュボード表示（`ohlc_processor` は D13 無傷）。
- **次の一手**：①**ライブ検証**＝場中にダッシュボード確定足の出来高が妥当か目視（CMF は出来高使用／MESA/DT/Momentum/TSI は不使用）②問題なければブリッジを `distribution/sync_*.ps1` で配布へ → 各リポ push（それまで配布は保留）。③`N225LocalEngine` は **2026-08-18 にローカル git 管理下へ**（初回コミット `d8f78d8`・StrategyBuilder と同方針＝ローカルのみ・GitHub へは push しない）。除外＝`.venv`/`app/state`/`data/logs`/`data/csv_import`/`ohlc_live.parquet`。

## ★現在地（2026-06-16 実装・最優先で読む）— M1〜M4＋ダッシュボード 完成
> 詳細は `docs/devlog/2026-06-16.md`。**新コードは全て `app/` 配下**（旧トップレベルは破棄候補）。
- **M1** feed・ろうそく足（★セッション末足）無傷移植＋on_tick seam（`app/feed/`）。
- **M2** 戦略ローダ＋オフラインdriver＝PineBroker（`app/engine/{contract,pine_broker,offline_driver,strategy_loader}.py`）→ DT golden 一致（n=599/PF2.29）。
- **M3** リアルタイムtickブローカー＋webhook変換（`app/engine/{realtime_broker,webhook_converter}.py`）→ オフライン＝リアルタイム一致（J-3）。**指値イントラバー実証**。
- **M4** 内蔵BT（`app/backtest/`）＋送出（`bridge_sender`＝BridgeSender/VirtualSink）＋`engine.py`(LiveEngine)＋`controller.py`＋ダッシュボード（`app/dashboard/`）＋`run_dashboard.py`/`run_live.py`。
- **ブリッジ制御** `app/engine/bridge_process.py`＋ダッシュボード②③ボタン＋モニターLED4種。
- **戦略登録（ブリッジ仕様準拠）**：2段階＝①配布ZIP/フォルダ取込（`resolve_package`・自動解凍）→②ショートネーム(alert_name)/インターバル/シークレット(passphrase・全体共通)/有効。`registered.json`＋`settings.json`。
- **設定画面**（`settings_dialog.py`）・**UI刷新**（Tokyo Night・DataGrid☑チェックボックス・`theme.py`）。
- **全テスト GREEN**（`tests/` 7ファイル）。起動＝`python run_dashboard.py`（共有venv）or **デスクトップ `N225LocalEngine.lnk`（アイコン・pythonw）**。
- ★**午後追加（実用化・詳細＝devlog/2026-06-16 続き）**：アイコン起動（`launch_localengine_dashboard.bat`+ico）／**配布ZIPツール**（`N225StrategyBuilder/distribution/package_strategy.py`＝GUIでフォルダ選択→ZIP・manifest自動生成・`packages/`保存・LocalEngine互換検証済）／登録時 manifest.json 自動生成で一貫化／**ブリッジ二重起動防止**（8001で is_up・手動起動検知）／**★feed接続＝[オートトレード起動]時に接続・ポート使用中なら接続しない安全制御**（本番tick経路を壊さない）／**仮想トレードON/OFFトグル**（②ブリッジと同配置・ON=tickのみ送出なし/OFF=本番自動）／feedログをダッシュボードへ流す sink。
- ★**2026-06-17（A作業）：旧破棄ファイルを退避→完全削除済み**。`engine/`・`_vendor/`(約31MB)・root `dashboard.py`/`controller.py`/`test_controller.py`・`strategies/{dt_local,mesa_local,registry.py,test_registry.py}` を一旦 `_archive_legacy_v1/` へ移動退避→**無使用を確認の上 削除**（約31MB回収）。安全確認＝新`app/`・`tests/`・全戦略フォルダから import 参照ゼロ（grep）／旧パス参照の実コード無し（ヒットはdoc言及のみ）／30MB `master_dataset_4y.pkl` は**正本が `N225StrategyBuilder/strategies/MESA_Stochastic/python/data/` に現存**＋再生成元 `build_master_dataset.py` も同所＝失う固有資産なし。退避後 全16テスト GREEN、削除後 py_compile OK（稼働中の仮想トレード=TCP5000占有を乱さぬためソケット接触テストは非実行）。**top-level＝app/strategies/data/design/docs/tests/run_dashboard.py/run_live.py/_START_HERE.md のみのクリーン構成**。
  - ※**strategies/ に新・自己完結戦略が計5本存在**（CMF/DT/MESA/Momentum/TSI_Stochastic）。docs の例示はDT中心だが実体は5本そろっている。
- ★**2026-06-17（午後）：保存先を自己完結化（外部共有ストア撤去）**。別パッケージ配布のため共有フォルダ保存は不可と確定し変更：
  - **ライブろうそく足＝プロジェクト内 `N225LocalEngine/data/ohlc_live.parquet`**（旧 外部 `n225tradingAI2\data\ohlc_data.parquet` から撤去・移行済。内蔵BT/warmupと**同一ファイルに統一**＝旧不整合解消）。[ohlc_storage.py](app/feed/ohlc_storage.py)。
  - **市場カレンダー＝`data/market_Calendar.csv`**（旧 共有AppData撤去。[_market_hours.py](app/feed/_market_hours.py)）。生成UIは将来ダッシュボードに追加（**ボタン前に画面構成をユーザー確認**）。
  - **シークレット(passphrase)＝（この後 夕方に方針変更）ブリッジから取得・ローカルはファイル保存しない**（旧 AppData secret.json 案は廃止。下の「夕II」参照）。
  - 全テストGREEN（candle 6/6・golden・eq_realtime・data_provider）。memory [[reference_localengine_candle_store]]。**配布の正本地図＝ルート [`DISTRIBUTION_MAP.md`](../DISTRIBUTION_MAP.md)**（3製品＝シミュレーション/TV版/ローカル版・1台2台インストール・配布要領）。
- ★**2026-06-17（夕）：ダッシュボードUI機能群 完了**（詳細＝devlog 11:30〜）：
  - **市場カレンダー生成UI**（設定→[カレンダーを更新]・`calendar_fetch.py`＝JPXスクレイプをベンダリング／`calendar_dialog.py`）。
  - **CSV/データ管理**（下段[📁データ管理]→`data_dialog.py`／`backtest/data_import.py`）：**固定2形式＝①実時刻CSV(kabu) ②225Labo xlsx(取引日→実時刻・`settlement_to_actual`ベンダリング)＋.zip自動解凍**。マージ→dedup→**6ヶ月ローリング自動**（保存時・起動時・取込時）。ろうそく足表示＋CSV書出。BT6ヶ月忠告。
  - **長期履歴入手元＝225Labo(=Gatorobo・1箇所)確定**（短期=kabu）。JPXは有料で非同梱（外部配布¥13,200/月分）。
  - **テーマ(ダーク/ライト)＋文字サイズ(標準/大きめ・特大廃止)を設定に追加**（`theme.py`2パレット＋tk scaling＋起動時settings.json読込・再起動反映・ラジオボタン）。**`fit()`＝収まれば固定・あふれる窓だけ縦自動**（保存ボタン隠れ防止）。**全サブ窓を親付近に表示**(`place_near`)。取込に**完了ダイアログ(✅)**。
  - USER_MANUAL §5.5（CSV管理・225Labo・保存先data/csv_import・ZIP可）／DISTRIBUTION_MAP §4.1/§6.4 更新。
- ★**2026-06-17（夕II）：シークレット方式変更＋パラメータ/BT/取引記録（詳細＝devlog 14:00〜）**：
  - **シークレット(passphrase)＝ブリッジから取得・ローカルはファイル保存しない**（旧 AppData secret.json 廃止）。webhook 両端で一致必須の共有値なので**ブリッジ(`%LOCALAPPDATA%\N225BrokerBridge\appsettings.Local.json`・DPAPI/CurrentUser・`enc:`)を正として起動時に復号取得しメモリ保持**（[bridge_secret.py](app/engine/bridge_secret.py)・[controller.py](app/engine/controller.py)）。**生成はブリッジ側(C#)のみ・public リポへ push 済**。設定画面のシークレット欄は読み取り専用＋[ブリッジから取得]。
  - **パラメータフォーム全項目化**（仕様§D.2・phase 6×4・enum Combobox）＋**[保存してBT]で窓を開いたまま調整→BT 反復**（[param_form.py](app/dashboard/param_form.py)）。
  - **内蔵BTに 取引一覧（TV風・最新上・縦スク・CSV）＋Performance Summary（全体/Long/Short）**、**再実行はその場更新**（[bt_view.py](app/dashboard/bt_view.py)/[report.py](app/backtest/report.py)）。6ヶ月未満でも実行（忠告のみ）。
  - **シングルトン**（名前付き mutex で二重起動禁止・`dashboard.py main()`）。
  - ★**取引記録機能**（下段[📒取引記録]・[trade_record_view.py](app/dashboard/trade_record_view.py)）：新規/決済を**発生順に `app/state/trade_log.jsonl` へ累積**（仮想/本番同記録・[realtime_broker.py](app/engine/realtime_broker.py) `on_event`）。**2表示（記録通り/取引一覧）＋戦略別（登録戦略ごと）＋期間（全期間/当日/今週/今月）＋CSV**。**[この戦略の記録を削除]（記録だけ・戦略は残る）/[全削除]/登録解除時に記録も消すか確認**。**6ヶ月超は起動時 `data/history/trade_archive_YYYY-Qn.csv` へ自動退避＋[アーカイブを開く]で読み取り閲覧**。USER_MANUAL §8.5 新設。
- ★**2026-06-17（夜・本番稼働中の指摘）：オートトレードLEDの点灯条件を修正**。旧＝`engine.running`（仮想でも起動中なら点灯＝紛らわしい）→ **新＝`running かつ dry-run OFF（本番）`**＝**仮想中は消灯・本番（赤）起動で点灯＝緑は実弾が出ている合図**。[dashboard.py](app/dashboard/dashboard.py) `_refresh` の LED 1箇所のみ（`status().running` は据置＝停止ボタン制御に使用）。運用モデルを **USER_MANUAL §3.1（LEDの意味・2運用パターン表）** に明文化、外部仕様書 F7 更新。※稼働中プロセスは無影響・再起動で反映（ユーザーが15分足の合間に LocalEngine のみ再起動予定）。
- ★**2026-06-18①：取込タイムスタンプを標準化**。kabu CSV も 225Labo と同じ取引日(settlement)規約と判明（夜間=翌営業日日付）。内部標準＝実時刻に統一し、**取込は「セッションまたぎ＝土曜足の有無」で規約を自動判定→実時刻へ変換**（`data_import.is_settlement_indexed`/`settlement_index_to_actual`）。汚れていた `ohlc_live.parquet` を実時刻でクリーン再構築（旧は`.corrupt_bak`）。4年15分足データの所在＝`N225StrategyBuilder/strategies/MESA_Stochastic/python/n225_15m_4y.{pkl,csv}`。詳細＝devlog/2026-06-18・設計 03 §F.0。
- ★**2026-06-18②：ダッシュボード仕様変更（起動/仮想/停止ボタン全廃）完了**。dry_run撤去・**記録は全戦略常時（実弾との比較監査）・注文(送出)は戦略「有効」のみ**・起動と同時に自動運用・オートトレードLED=有効戦略≥1。ブリッジ起動/停止は残す。全テスト16/16 GREEN。正本＝[[project_localengine_dashboard_button_simplification]]・devlog/2026-06-18。
- ★**2026-06-18③：UI調整＋起動高速化＋用語統一＋ドキュメント全更新 完了**。③オートカード削除＝①戦略②ブリッジの2枚・ボタン2列幅統一・設定/LED右寄せ・窓880×520・一覧6行。起動の遅さ（warmup28秒）を**ウィンドウ先表示＋warmup背景スレッド＋300本短縮で28→11秒**（K.9）。ログ/UI/コメントの「送出」→「注文」統一（pine_brokerの再送出のみ残置）。設計01/02/03/master・USER_MANUAL・DISTRIBUTION_MAP・memory を新モデルへ整合（02のdry-run/2段階記述も解消）。
- ★**2026-06-18④：M6 配布パッケージ化に着手（uv化＋ローカル版配布ツリー）**。正本＝ルート [`DISTRIBUTION_MAP.md`](../DISTRIBUTION_MAP.md)、履歴＝devlog/2026-06-18「午後II〜」。
  - **方針確定**：エンジン基本ルート＝**A案（`uv sync`）**（埋め込みPython installer は M7）。**2ルート**＝基本(通常インストール・Claude Code 不要)／保険(入らない時に Claude Code が `/install`等で救済)。**ブリッジ同梱＝案A**（ローカル版に**ブリッジ source＋（release で）compiled installer を一緒に同梱**・二重インストールは Inno AppId 固定で「あれば入れない」）。**アップデート＝コード入替・ユーザーデータ絶対保持**（`data/`/`app/state/`/`%LOCALAPPDATA%`）・6ヶ月シードは `data/seed/` 初回のみ展開。
  - **実装・検証済**：①`pyproject.toml`+`uv.lock`+`.python-version`(3.10)（依存実測確定・**golden再現で numpy2.2.6/pandas2.3.3 固定**・uv 0.11.21 スタンドアロン導入・golden数値系テスト uv 環境で全PASS）。②`distribution/sync_local.ps1`（excludelist＝コード↔ユーザーデータ↔dev物分離）→ `distribution/runtime-local/`（engine＋bridge source＋data/seed＋起動bat/icon＋VERSION.json＋README＋CLAUDE.md/.claude/commands＋.gitignore）。③`ohlc_storage._restore_seed_if_needed`（初回シード展開・既存非上書き・隔離テスト4/4）。基本ルートは配布copyで `uv sync`→import 検証済。
  - **ブリッジ installer 実ビルド＝完了（2026-06-18 夕）**：Inno Setup 6.7.3＋.NET 8 SDK 8.0.422 を winget 導入→`sync_local.ps1 -BuildBridge` で **`N225BrokerBridge-Setup-0.1.0.exe`（50.7MB・self-contained）** を `runtime-local/bridge/installer/output/` へ同梱。**案A 完成（source＋compiled 同梱）・パッケージ総52.5MB**。※iscc はユーザースコープ導入＝ビルド時 PATH 追加で解決。
  - **残**：基本ルートの**フル起動**確認（dashboard停止時＝singleton/port5000）／**225Labo再配布規約**→シード同梱可否／GitHubリポ分割(public/runtime-local)＆push／任意：`.iss` を x64→x64compatible（Inno 非推奨警告）。
- **現在地＝6/18 の全作業＋M6①②着手 完了・引き継ぎ済（devlog/2026-06-18）。次：①installer 実ビルド(15:45後) ②基本ルートのフル起動確認 ③ユーザー実起動で最終確認/微調整 ④M5 実機ペーパー。**
- **次の一手**：①**UIは継続調整中**（随時対応）②仮想トレード通し稼働の結果反映 ③M6 uv配布（runtime-local＋6ヶ月シード・**225Labo再配布規約の確認**・起動bat/アイコン同梱・インストーラで Desktop/StartMenu ショートカット）④M5複数戦略並行・実機ペーパー ⑤feedランプ改善（任意）。tick分配（local+TV同時）はB案保留・当面A排他。
- **確定（蒸し返さない）**：ブリッジ⇄ダッシュボードは分離・結合は webhook のみ（**A案**）／約定正本＝PineBroker／ろうそく足（セッション末足）無傷（D13）／**シークレットはブリッジ取得・ローカル非保存**／**取引記録は trade_log.jsonl 累積＋6ヶ月アーカイブ・記録削除≠戦略削除**。

> N225TradingSystem を「**TradingView版**（外部・TV+トンネル・既存完成）」と「**ローカル版**（全ローカル・新規）」の2系統に分ける。
> 本フォルダ＝**ローカル版**（kabu ⇄ ブリッジ ⇄ Python戦略エンジン ⇄ ベーシック・ダッシュボード）。
> AIは別製品でなく**着脱できる戦略アドオン**（共通エンジンに載る1戦略）。

## 確定した設計（正本）
- ★**正本＝[design/N225LocalEngine_詳細設計書.md](design/N225LocalEngine_詳細設計書.md)（v1.0・2026-06-14）**。3ドラフトを統合した唯一の基準。設計判断 D1-D10（別製品/コード共有禁止・Webhook送出・**BatchStrategyAdapter**・PositionState・15分固定・順次既定/並列opt-in・外回りコピー流用・別ダッシュボード・golden一致）を確定。
  - 正本の鎖：**Pine(一次正本) ≡ Python(較正済み golden) ≡ ローカルon_bar(ビット一致検証)**。
  - 実装方式＝**BatchStrategyAdapter**（検証済み `simulate_v3` 等をコピー同梱・無改造で毎足回す。on_bar 新規再移植は不採用）。
  - 送出＝確定 Webhook フォーマット（`N225BrokerBridge/docs/webhook-api-spec.md`）。枚数＋売買シグナル、価格と執行はブリッジ。
- 旧3ドラフト（[_archive/strategy_lifecycle_standard.md](design/_archive/strategy_lifecycle_standard.md) / [_archive/local_engine_design.md](design/_archive/local_engine_design.md) / 旧 mesa_local/PORT_SPEC.md）は**正本へ統合済・履歴**（2026-06-23 に `design/_archive/` へ集約）。現役の正本は **詳細設計書（master）＋ 01/02/03 の4点のみ**。

## 現在地（2026-06-14）
- **詳細設計＝正本 v1.1 確定**（3ドラフト統合・D1-D10・§12 配布）。
- **★M1 中核 完成・全テスト PASS**：`engine/`（contract / webhook / executor / adapter / core ＋ tests/test_engine.py）。戦略↔エンジン結合ロジック（PositionState差分→spec§9 webhook・warmup ゲート・順次≡並列・3Split/ドテン）。
- **★M2 完成・golden ビット一致 PASS**：`strategies/mesa_local/`（mesa_local.py＝BatchStrategyAdapter で config_v7_8 を包む／validate_mesa_local.py）。窓つき adapter が golden（588/PF2.40）の建玉推移に**全1717トランジション足＋連続6000足でビット一致**。**必要バッファ長 W=500**（warmup 300＋最大保有138＋余裕＝既存 OHLCStorage の 500 と一致）を実測確定。
  - 実装方式＝**BatchStrategyAdapter**（検証済み `simulate_v3` をコピー同梱・無改造。旧 StreamingMesaV783 不採用・正本 §3.2,§10）。
  - MESA エンジン＝正本 `simulate_v7_8_fib_v3_split.py`・`config_v7_8()`。golden＝[strategies/mesa_local/golden/v783_golden_fills.csv](strategies/mesa_local/golden/v783_golden_fills.csv)。
- **★M3 機能部分 完成・全検証 PASS**：
  - `engine/sender.py`（`BridgeSender`＝webhook 搬送・dry_run）／`engine/backtest.py`（`BacktestRunner`＝BT≡実機）／`run_live.py`（`LiveRunner`＝実機 glue）。
  - **M3-e2e**：Engine 全経路（adapter＋差分→webhook＋sender）が golden 完全一致（5000足/118 webhook）。
  - **Stage2**：生 OHLC→prep→`build_mesa_columns`→simulate_v3 が golden 忠実（指標パリティ25/25・全経路123/123）。
  - **LiveRunner glue**：storage→engine→sender が生OHLC・Stage2 で golden 一致（400足/9 webhook）。
- **残（実機環境が要る・未）**：①**ライブ約定タイミング**（次バー始値約定に対し、エンジンは fill 足で webhook を出す＝市場成行だと1バー遅延。シグナル足で予約発注する設計を要検討＝P&L 直結・正本 §14）②実ブリッジ/kabu 接続でのペーパー実走 ③外回り物理コピー同梱（M6）。

## ★2026-06-14 後半：戦略オーサリング標準へ方針転換（次セッションはここから）
- **登録の仕組みを作る前に、Python 戦略の「書き方・置き方」を標準化する**必要が判明（N225StrategyBuilder の根本改善）。詳細は **devlog `docs/devlog/2026-06-14.md` ⑩** と **`N225StrategyBuilder/strategies/_STRUCTURE.md`**（構造正本）。
- 確定：①戦略＝ロジックだけ（BT/データ/レポートは持たない）②broker（Pine strategy.* と1対1）③共有BTエンジン本拠＝`N225StrategyBuilder/strategies/_engine`（live はコピー・backtest 無し）④フォルダ＝`work/`＋`release/<strategy_name>/`（配布・登録単位）⑤一貫性の軸＝戦略名・版は MANIFEST.version。
- **Sample1/Sample2 を実作成済**（標準フォルダ雛形）。
- **次セッションの手順**：(a) `_engine` 本拠化の移設＋broker 実装 → (b) `_TEMPLATE` 更新 → (c) **Pine→Python 変換テスト1本** → (d) registry/dashboard を「フォルダ指定登録＋ブリッジ strategies.json モニター」に作り直す。
- ★既存 M1-M5・dashboard第一版・registry/controller は**ハードコード版**＝標準で作り直す前段。engine 中核（contract/adapter/executor/webhook/core）と golden 検証は流用可。

## （旧）M1・M2・M3機能部 完了 → ライブ約定タイミング / M4（標準化前の到達点）
1. ~~**M1 中核**~~ ✅完了（`engine/` ＋ tests 全PASS）。
2. ~~**M2 golden ビット一致**~~ ✅完了（`strategies/mesa_local/`・W=500 で全数一致）。
3. ~~**M3 機能部**~~ ✅完了（BridgeSender／BacktestRunner／LiveRunner・M3-e2e／Stage2／glue 全PASS）。
4. ~~ライブ約定タイミング~~ ✅**確定（D11・§7.1）**：**確定足（終値確定）で webhook を出す＝現挙動のまま**。golden（次バー始値約定）と約1バーずれ得るが、足は終値で確定するので確定足で出すのが自然＝ユーザー承知の上で採用。**コード変更なし**。
5. ~~**M5 多戦略＋汎用性**~~ ✅完了：`strategies/dt_local/`（DT＝RSI 差替・cfg は config_v7_8 流用）が DT golden 一致（153/153）＋ mesa_local と**多戦略並列**で各々正しい（sequential/threadpool 両方）。＝「build_input を足すだけ」「多戦略並列」を実証。
6. ~~**M4 ダッシュボード**~~ ✅第一版完成：`strategies/registry.py`（戦略カタログ・manifest）／`controller.py`（頭脳・ON/OFF・warmup・start/stop・状態＝ヘッドレス検証PASS）／`dashboard.py`（tkinter GUI 第一版・独立1枚・構文/import 検証済）。**GUI の見た目はユーザーが実起動して指示・調整する段階**。
7. **次**：①ダッシュボードをユーザーが実起動して配色/レイアウト調整 → ②実機ペーパー実走（ブリッジ/kabu 接続）③**M6** 配布パッケージ化（uv・外回り＋戦略エンジンの物理ベンダリング・§12）。
※本番戦略（DT は HP→RSI L54／TSI／CMF／Momentum／HighVol／OB5m／Scalp）も同じパターンで build_input+cfg を足すだけ。dt_local は plain RSI13 のデモ。
※ローカルエンジン全体の起動：`python dashboard.py`（GUI）／`python run_live.py [warmup_csv]`（ヘッドレス）。dev は共有 venv（`N225SignalTrader/.venv`）。

## やってはいけない（正本 §12 不変条件）
- 検証済みバッチ・golden を**改変しない**（コピーして使う）。close モデル(False)に戻さない。
- **TV版コードを import・共有しない**（別製品・コピー同梱）。
- warmup 300本未充足で発注しない／先読み禁止（確定足まで）。
- 指標ヘルパーは import して使う（再実装禁止）。

## 関連
- 正本＝`design/N225LocalEngine_詳細設計書.md`。golden＝`strategies/mesa_local/golden/`。外回り＝`N225StrategyAI/clone/feed,live`（コピー流用元）＋`N225StrategyAI/design/mesa_clone/data_management_design.md`。
- 横断ロードマップ＝memory [[project_three_strategy_roadmap]]。別製品制約＝[[project_localengine_separate_product]]。送出＝`N225BrokerBridge/docs/webhook-api-spec.md`。
- 既存戦略開発ガイド（昇格基準§7）＝`N225StrategyBuilder/docs/strategy_development_guide.md`。
