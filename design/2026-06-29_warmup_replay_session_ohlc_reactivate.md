# LocalEngine 設計変更（2026-06-29）— 復元の warmup-replay 化／session_lib／OHLC 実値化／登録後の自動再有効化

本日の4つの設計変更をまとめる。正本（master 詳細設計書・01/02/03）は本書に合わせて該当箇所を更新済み。
背景＝実トレード運用で「日中 TV は何度もエントリー、LocalEngine はゼロ」「再起動でしか反映されない」事故が
顕在化し、(A) 復元・(B) セッション制御・(C) ろうそく足・(D) 登録反映 の4系統を是正した。

---

## ① 建玉復元 ＝ warmup-replay（D15 snapshot/restore を置換）

### 変更
- 旧：起動時に flat `prime`（指標だけ温める）＋ `positions/<name>.json` から `restore()`（建玉/TP 復元・D15 改訂 2026-06-24）。
- 新：**起動時に履歴足を live と同一 `on_bar` でブローカー駆動する `RealtimeBroker.warmup_replay(df)`**。
  現在建玉・出口（部分約定含む）・指標バッファ（ポートフォリオはサブ含む）を**履歴から再構築**する。
  ＝**TradingView がロードのたびに履歴から戦略を再計算するのと同一シーケンス**。

### 効果・根拠
- **BT(run_pine)≡live≡warmup が同一コードパスで一致**（同じ on_bar→PineBroker を流すだけ）。
  → 「BT と取引履歴と復元が噛み合わない」三者不一致を構造的に解消。
- snapshot/restore（D15）は**起動経路から不要**。`snapshot()/restore()` メソッドは残置するが
  startup の復元には使わない（建玉 JSON は最終既知建玉の**受動記録**＝診断用のみ）。
- 過去分は**発注も記録もしない**（`warmup_replay` は `_emit`/`_record` を呼ばない＝webhook・取引イベント送出ゼロ）。
  再生後 `_bar_index=n-1` / `_new_bar=True` で、最終 warmup 足の submit を最初の live 始値で約定。

### 検証
- 実データ：warmup_replay の決済済みトレード ＝ `run_pine`／`run_pine_fast`（正本BT）と完全一致。
  建玉中で終わるスライスでも残建玉（TP1/TP2 約定後の残数量）＝ run_pine の EOD クローズと一致＝部分建玉も正確に再構築。
- 回帰テスト＝`tests/test_warmup_replay.py`（W1 決済一致・W2 建玉保持・W3 live継続・空df）。

### 反映
`app/engine/realtime_broker.py`（`warmup_replay` 追加）／`app/engine/controller.py`（`start` が `prime+restore`→`warmup_replay`）。

---

## ② セッション制御 ＝ 共通ライブラリ `session_lib`（プラットフォーム提供）

### 変更
- 「いつ約定してよいか」だけを per-bar・先読みなしで判定する単一ソースを **`app/feed/session_lib.py`** に新設。
  - `flags(ts, interval_min, offset_min=None)` → `{cutoff, block_new, pre_no_hold, force_close, mins_to_end}`
  - `gate(orders, fl, position_size, exit_ids)` → 締切窓の新規/決済間引き＋週末/SQ 強制 flat
- 戦略は `import session_lib` で使う。**戦略 ZIP には同梱しない**（プラットフォーム提供＝一元管理・跨ぎ無し）。
  runtime は `strategy_loader` が `sys.modules` に注入、dev(Builder) は BT ランナーが `app/feed` を載せて解決。
- カレンダーは全外部化（決め打ちなし）：`data/session_hours.json`（era 対応＝日中引け 15:15→15:45・
  夜間 16:30→17:00 の制度変更込み）／`data/sq_calendar.json`（`app/feed/sq_fetch.py` が JPX から生成）／
  祝日・大納会＝`_market_hours`。Pine 側は同一カレンダーの `KengetsuLib/2`。

### ts 頑健化（重要バグ修正）
- `flags()` は `ts` が datetime でないとき変換するが、**numpy.datetime64 の str はナノ秒9桁**で
  Python 3.10 の `fromisoformat` が解析失敗→`ts=None`→**gating 無効**になる静かな抜けがあった。
  offline の step は `pd.Timestamp`（datetime 派生）を渡すので効くが、**on_bar 経路（run_pine／
  realtime on_bar_close／warmup_replay）は numpy.datetime64 を渡すため gating が抜けていた**。
  → `_to_dt()` で datetime/Timestamp/numpy.datetime64/str を統一変換。offline=on_bar=step が同一 gating に。
- ※実 live はフィードの確定足が python datetime なので元々 gating は有効だった。影響したのは
  numpy.datetime64 を渡すテスト/検証経路と warmup_replay（修正で実 live と一致）。

### 反映
`app/feed/session_lib.py`（新規）／`app/feed/sq_fetch.py`（新規・JPX SQ 取得）／`data/session_hours.json`（新規）／
`app/engine/strategy_loader.py`（session_lib 注入）。回帰＝`tests/test_offline_eq_realtime.py`・`test_trade_list_eq_bt.py`。

---

## ③ ろうそく足 OHLC 実値化（2026-06-24 価格/出来高時刻分離の拡張）

### 変更
- ブリッジ（kabu board push）が **始値(寄付)/高値/安値＋各時刻**・最良気配数量・VWAP・現値前値比較を
  拡張 JSON で転送（`open/open_time, high/high_time, low/low_time, bid/bid_qty, ask/ask_qty, tick_dir,
  price_status, vwap, cum_volume`）。kabu の Bid/Ask 命名逆転は転送時に慣習へ正規化。
- `live_feed` がこれらを解析し `update_ohlc(price, vol, tick_time, volume_time=, op=, op_t=, hi=, hi_t=, lo=, lo_t=)`。
- `ohlc_processor`：各時刻が当バー内なら**真の寄付/高値/安値**を採用（標本 close が逃す「寄付」「push 間の山谷」を補正）。
  始足は寄付を始値に。`on_tick(price, ts, bar_open=, bar_high=, bar_low=)`（seam 拡張）。未提供（旧ブリッジ）は None＝従来動作（後方互換）。
- `realtime_broker.on_tick`：**寄付で初足の成行を約定**・**真の高安で建ち注文（指値/逆指値）をイントラバー判定**。

### 反映
ブリッジ `PriceTick.cs`／`KabuBoardWebSocketService.cs`／`AiTickForwarderService.cs`。
LocalEngine `live_feed.py`／`ohlc_processor.py`／`engine.py`／`realtime_broker.py`。
※ D13（セッション末足・板寄せ・境界クランプ・executed_time）は無傷。回帰＝`tests/test_candle.py`（on_tick seam は kwargs 対応）。

---

## ④ 登録/設定変更の自動再有効化（稼働中に全戦略が止まるバグの修正）★運用直結

### 問題（今日のゼロの主因）
- `register` / `update_registration` / パラメータ保存（ParamForm `on_saved=load_all`）はいずれも
  `load_all()` を呼び、`load_all()` は **`self.engine = LiveEngine()` で全ブローカーを作り直す＝全戦略 ready=false**。
  ready=true にするのは `start()` だけで、**登録後に start を再実行しないため、稼働中に1戦略でも登録すると
  全戦略が停止し、再起動するまでシグナル・記録ゼロ**になっていた（実際に終日ゼロが発生）。

### 修正
- `load_all()` は「直前まで稼働中(was_running)」なら、engine を作り直したあと **自動で
  `_activate_brokers()`（warmup→ready→sender 割当）を再実行し `running` を復帰**させる（＝再起動不要）。
- feed コールバックは **self.engine を動的参照**（`_engine_on_tick` メソッド／`_on_confirmed_bar` クロージャ）に
  統一したので、engine を作り直しても貼り直し不要で追従する（旧 `feed.mgr.on_tick = self.engine.on_tick` は
  旧 engine インスタンスに束縛され、load_all 後に tick が旧 engine（空）へ流れる不具合があった＝是正）。
- `start()` と再有効化は `_activate_brokers(warmup_df)` を共用。再有効化用の warmup は
  `_build_warmup_df()`（parquet+CSV→直近500本・dashboard と同方式）。
- ＝**「即時反映（再登録不要）」が初めて実体として成立**（旧 01/02 の記述は意図のみで未達だった）。

### 運用上の注意（移行期）
- 本修正は次回の**エンジン再起動後**に有効（稼働中プロセスは旧コードのまま）。**稼働中プロセスが旧コードの間は、
  ライブ中の「登録/更新/パラメータ保存」を避ける**（全戦略停止→再起動まで復帰しないため）。**有効化(enabled)トグルは
  `set_enabled`＝sender 切替のみで `load_all` を呼ばず安全**。

### 検証
回帰テスト＝`tests/test_register_while_running.py`（稼働中に2本目を登録→既存・新規とも ready 維持・running 継続）。

### 反映
`app/engine/controller.py`（`load_all` 再有効化／`_engine_on_tick`／`_activate_brokers`／`_build_warmup_df`）。

---

## 関連・上書き関係
- 本書①は [`position_restore_redesign_2026-06-24.md`](position_restore_redesign_2026-06-24.md)（D15 snapshot/restore）を**置換**（同書冒頭に supersede 注記）。
- 本書③は [`candle_price_volume_decouple_2026-06-24.md`](candle_price_volume_decouple_2026-06-24.md) を**拡張**（価格/出来高時刻分離＋OHLC 実値）。
- 正本反映：`N225LocalEngine_詳細設計書.md`（D15/D13 更新・変更履歴 v2.2）／`02_内部仕様書.md`（§復元・§Feed）／`03_詳細仕様書.md`（§C・§E）。
