# 再起動時の建玉復元 再設計（2026-06-24・D15 改訂）

> ⚠️ **【SUPERSEDED 2026-06-29】本書の snapshot/restore 方式は廃止されました。**
> 起動時の建玉復元は **`warmup_replay`（履歴を live と同一 on_bar で再生して建玉・出口・指標を再構築＝
> TradingView 同一シーケンス）** に置換され、snapshot/restore は起動経路から不要になりました（メソッドは
> 残置・建玉 JSON は受動記録＝診断用のみ）。最新設計＝[`2026-06-29_warmup_replay_session_ohlc_reactivate.md`](2026-06-29_warmup_replay_session_ohlc_reactivate.md) ①。
> 以下は経緯の記録として残します。

## 0. 背景・なぜ変えるか
2026-06-23 に「**再起動はリセット＝建玉/TP を復元しない**」と決めた（D15）。だが致命的欠陥が判明：
- 例：**夜間に新規建玉 → 翌朝エンジン停止・再起動**。復元しないと、その玉の**決済（TP1/TP2・反対サイン）が二度と発火せず**、kabu に実弾が残ったまま**管理不能**になる。
- ＝**復元する方向へ再設計**（D15 撤回）。

## 1. 方針（確定・ユーザー回答反映）
- **永続スナップショットから建玉＋出口状態を直接復元**する（旧A案の「履歴を売買しながら再生」＝幽霊トレードは使わない）。
- **ブリッジ突合はしない**（LocalEngine からブリッジの実建玉を読む手段がないため）。LocalEngine は**自分の永続モデルを信頼**する。
- **enabled / disabled の両方を復元**（実弾＋仮想記録の継続）。
- 停止中に外部決済された建玉を復元しても、TP 発火時の close webhook は**ブリッジ側の建玉管理が安全に処理**（ブリッジは webhook データ有無を確認し自分で建玉管理＝存在しない建玉に逆玉を建てない）。

## 2. 設計

### 2.1 柱1：永続化（建玉が変わるたび保存）
- `RealtimeBroker` の建玉が変化したとき（`on_event`＝新規/部分決済/全決済）、戦略ごとに
  `app/state/positions/<登録名>.json` へ**現在の建玉スナップショット**を保存。
- スナップショット内容：
  - broker：`pos_dir / pos_qty / avg_price / entry_ts / trade_id / filled_ids(list) / book(建ち注文) / bars_held`
  - 戦略：`signup / tp1 / tp2 / zz_p1 / prev_size`
- **flat（pos_dir==0）になったらファイルを削除**。
- 取引記録 `trade_log.jsonl`（発生順の履歴）とは**別物**＝「現在の建玉状態」。

### 2.2 柱2：復元（warmup 後・直接注入・履歴再生しない）
- `controller.start` の **warmup（flat prime）の後**に、各 broker のスナップショットを読み込み `rb.restore(snap)`。
- broker へ：`pos_dir / pos_qty / avg_price / entry_ts / trade_id / filled_ids / book` を注入。
  - **`entry_bar` を warmup 後の現在 `_bar_index` に再アンカー**（＝次の確定足から `i > entry_bar` が成立し TP 発火可）。`bars_since_entry` は `bars_held` を反映（近似可）。
  - **`filled_ids` を復元＝既に約定した TP（例 TP1）を再約定させない（TP 二重決済の防止・最重要）**。
- 戦略へ：`signup / tp1 / tp2 / zz_p1` を注入し、**`prev_size = pos_dir*pos_qty`（=size）に設定**
  （`just_entered`（size>0 & prev<=0）を再発火させない＝TP 再計算しない＝復元した tp1/tp2 を使う）。
- 戦略は `size≠0` を見て**出口（TP1/TP2 指値・反対サイン成行）だけ生成＝新規エントリーは再発火しない**。
- enabled/disabled とも同じ仕組みで復元。

### 2.3 柱3：ブリッジ突合 → **廃止**
- LocalEngine は自分の永続モデルのみで復元。停止中の外部決済はブリッジ側建玉管理に委ねる。

## 3. 誤発火・「見ていない期間」
- TP1/TP2 は**エントリー時に確定した固定値**＝復元しても正しい（価格到達で約定／停止中に通過済みなら再開後最初の足でギャップ＝現値で決済＝合理的）。
- エントリーは `size≠0` で再発火しない＝幽霊建てなし。
- 取り戻せないのは「停止中の見ていない値動き」だけ＝**再起動は15分足の合間に短時間**で行い欠落窓を最小化（運用則）。

## 4. 実装
- `RealtimeBroker.snapshot() -> dict|None`（flat は None）／`RealtimeBroker.restore(snap)`。
- `controller`：`load_all` で `rb.on_event` を**登録名つきクロージャ**にし、`_on_trade_event(ev, name)` が記録＋スナップショット保存（flat は削除）。`start` の prime 後に各 broker を restore。
- `app/state/positions/` ディレクトリ（無ければ作る）。
- **D13（ろうそく足）・記録の発火ベース原則は無傷**。warmup の flat prime はそのまま（指標暖機）、その後に復元を載せるだけ。

## 5. 検証（ユニットテスト）
- **round-trip**：建玉→snapshot→restore で broker/戦略の状態が一致。
- **TP 二重決済防止**：TP1 約定済（qty3→2・filled_ids={TP1}）を restore → 次足で TP1 が再約定しない・TP2 のみ生かす。
- **flat 削除**：全決済で positions/<name>.json が消える。
- **復元後にエントリー再発火しない**：size≠0 で entry を出さず exit のみ。
- `tests/test_reconstruction.py`（旧A案の名残）は本設計に作り替え。

## 6. D15 改訂文
- 旧：「再起動はリセット・建玉/TP 復元しない」。
- 新：「**再起動時は永続スナップショット（`app/state/positions/`）から建玉＋出口状態を復元（enabled/disabled 両方・ブリッジ突合なし・履歴再生なし）**。`filled_ids` 復元で TP 二重決済を防止。D13・発火ベース記録は無傷」。
