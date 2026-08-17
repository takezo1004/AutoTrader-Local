# ローソク足 価格時刻／売買高時刻 分離 設計書（2026-06-24）

> 🔗 **【拡張 2026-06-29】OHLC 実値化**：本書の価格/出来高時刻分離に加え、ブリッジが board の
> **始値(寄付)/高値/安値＋各時刻**・気配数量・VWAP・前値比較を転送し、`update_ohlc(op,op_t,hi,hi_t,lo,lo_t)`＋
> `on_tick(bar_open/high/low)` で**真の寄付/高安**を採用（標本 close が逃す寄付・push 間の山谷を補正）。
> 詳細＝[`2026-06-29_warmup_replay_session_ohlc_reactivate.md`](2026-06-29_warmup_replay_session_ohlc_reactivate.md) ③。

## 0. 目的
LocalEngine が生成する15分足を **kabu Station の足（実約定源・正本）に一致**させる。
現状、**正時境界の始値/終値が15〜155円ズレ**ており（出来高も連動してズレ）、これを解消する。

## 1. 症状（実測・2026-06-24）
kabu Station CSV（`data/csv_import/161090019_15分足_260624-1218.csv`）と LocalEngine 生成足
（`data/ohlc_live.parquet`）を06-24の37本で比較：大半は±5円一致だが、**正時境界の4本だけ**大きくズレる。

| 時刻 | ズレ（Local−kabu） | 出来高差 |
|---|---|---|
| 08:45 | **終値 +25** | V −1,604 |
| 09:00 | **始値 −15** | V +121 |
| 10:00 | 始値 +10 | V +16 |
| **11:00** | **始値 +155** | **V −4,154** |

kabu は「08:45終値＝09:00始値＝69,695」と**連続**。LocalEngine は終値69,720・始値69,680と**境界をまたいでズレ**ている＝**境界 tick の割り当て誤り**。出来高のズレと連動。

## 2. 根本原因
ブリッジ `N225BrokerBridge/src/.../Integration/AiTickForwarderService.cs` L118：
```csharp
var jst = (volInc > 0m ? vAt : tick.At).AddHours(9);   // 出来高があれば「売買高時刻 vAt」で送る
$"{{\"timestamp\":\"{jst}\",\"close\":{tick.LastPrice.Value},\"volume\":{(long)volInc}}}\n"
```
- 1つのタイムスタンプ（`timestamp`）で **価格(OHLC)と出来高の両方**のバー割り当てを兼用している。
- 出来高が増えた tick は `timestamp = 売買高時刻 vAt` になり、**その tick の価格（始値/終値）も vAt のバーへ**入る。
- 正時境界では出来高バーストが起き、価格時刻(`tick.At` = CurrentPriceTime)と売買高時刻(`vAt` = TradingVolumeTime)が境界をまたぐため、**価格が隣のバーへ誤配置**される。
- ＝**2026-06-23 の「出来高を売買高時刻のバーへ」修正が、価格の割り当てを巻き添えにした。**

### kabu の正しい挙動（合わせる相手）
- **価格(OHLC)＝価格観測時刻(CurrentPriceTime)** のバー（始値＝そのバー最初の観測価格＝前バー終値と連続）。
- **出来高＝約定時刻(≈TradingVolumeTime)** のバー（境界の約定は約定時刻側のバーへ）。
- ＝価格と出来高は**別の時刻でバー割り当て**される（境界で1秒またぎ得る）。

## 3. 設計方針（分離＝decouple）
**価格(OHLC)は価格時刻で、出来高は売買高時刻で、別々にバー割り当てする。**
そのために tick プロトコルに**両方の時刻**を載せ、受信側がそれぞれ正しいバーへ反映する。

## 4. 変更仕様

### 4.1 ブリッジ（C#・窓 3:45–5:00 で実装＋再ビルド）
`AiTickForwarderService.OnPriceUpdated`：
- **`timestamp` を常に価格時刻 `tick.At`（CurrentPriceTime）にする**（OHLC を価格時刻バーへ）。
- **新フィールド `volume_time` を追加**＝売買高時刻 `vAt`（TradingVolumeTime・JST）。出来高(`volume`=volInc)はこの時刻のバーへ。
- 送出 JSON（後方互換＝追加のみ）：
  ```json
  {"timestamp":"2026/06/24 09:00:01","close":69680,"volume":120,"volume_time":"2026/06/24 08:59:59"}
  ```
  - `volume`==0 の時は `volume_time` を `timestamp` と同値（または省略）にしてよい（価格のみ更新）。
- 出来高増分(volInc)の計算ロジック（`vAt > _prevVolumeAt` の時だけ `cum-prevCum`）は**現状維持**。変えるのは「価格は price-time、出来高に volume_time を別送」だけ。

### 4.2 LocalEngine（Python・後方互換・稼働中に先行実装可）
**`volume_time` が来た時だけ新動作。来なければ現状動作（＝旧ブリッジでも壊れない）。**

`app/feed/live_feed.py::_on_line`：
- JSON から `volume_time`（任意）を追加パース。無ければ `None`。
- `self.mgr.update_ohlc(price, vol, tick_time, volume_time=vt)` へ渡す。

`app/feed/ohlc_processor.py::OHLCManager.update_ohlc(price, volume, tick_time, volume_time=None)`：
- **価格(OHLC)とバーのロールは `tick_time`（＝価格時刻）基準**（既存ロジックそのまま＝D13 のセッション末足/ダミー足/板寄せは無傷）。
- **出来高は `volume_time` のバーへ計上**：
  - `vt = volume_time or tick_time`。
  - **ロール前**に、`vt` が現在の形成中バー窓 `[bar_start, bar_end)` 内なら、その出来高を**現バーへ先に加算**（価格バーが次へロールしても、約定時刻側のバーに残る）。
  - `vt` が現バーより前（既に確定済み）の稀ケースは現バーへ best-effort 加算（境界1秒ズレの取りこぼし防止が主目的）。
  - 価格時刻バーの OHLC 更新時は、**二重計上を避けるため**「既に出来高を加算済みなら価格バー側では加算しない」フラグで制御。
- ＝**OHLC は価格時刻バー、出来高は売買高時刻バー**に入る。kabu と一致。

#### 擬似コード（update_ohlc）
```
vt = volume_time or tick_time
with lock:
    latest_price=price; last_tick_time=tick_time
    vol_added = False
    # ① 出来高を売買高時刻のバーへ（ロール前＝現バーに先行加算）
    if volume and current_candle is not None and bar_start <= vt < bar_end:
        current_candle["volume"] += volume; vol_added = True
    # ② 価格バーのロール（price-time 基準・既存 while ループ＝D13 無傷）
    while tick_time >= bar_end: _emit_current_or_dummy(); roll
    on_tick seam（既存）
    if not (bar_start <= tick_time < bar_end): 
        # price-time が窓外の稀ケース。未加算の出来高は取りこぼさず現状維持で return
        return
    # ③ OHLC を価格時刻バーへ
    if current_candle is None:
        current_candle = {open:price,...,volume:(0 if vol_added else volume)}
    else:
        high=max; low=min; close=price
        if not vol_added: current_candle["volume"] += volume
```

## 5. 検証（実装後）
- **ユニットテスト**（`tests/test_candle.py` に追加）：価格時刻09:00・売買高時刻08:59:59 の tick を流し、
  **出来高が08:45バー・始値が09:00バー**に入ることを assert。境界跨ぎ・通常時の両方。
- **実データ照合**：次セッション後、`data/ohlc_live.parquet` と kabu CSV を§1のスクリプトで再比較し、
  境界4本のズレが**±5円以内**に収まることを確認。

## 6. 影響範囲・リスク
- **全戦略の足データ**が対象（境界始値が最大155円ズレ＝損益直結）。zigzag/指標の境界挙動が改善。
- **D13（ろうそく足の確定/ダミー/板寄せ/セッション末足）は無傷**＝ロール・確定ロジックは変えず、出来高の計上先だけ分離。
- 後方互換：`volume_time` 未送の旧ブリッジでも現状動作（壊れない）。

## 7. ロールアウト手順
1. **LocalEngine 先行実装**（稼働中OK・`volume_time` 来るまで現状動作）→ ユニットテスト GREEN → 次回起動で待機。
2. **窓 3:45–5:00**：ブリッジ停止 → `AiTickForwarderService` 修正（timestamp=price-time＋volume_time 追加）→ 再ビルド → 起動。
3. 次セッションで kabu CSV と再照合 → 境界ズレ解消を確認。
4. 配布（`sync_*.ps1`→3製品 bridge/＋runtime push）は照合OK後。
