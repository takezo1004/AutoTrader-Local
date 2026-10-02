# AutoTrader Local（ローカル版・kabu ステーション版）

TradingView もインターネット公開も使わず、パソコンの中だけで 15 分足を作って戦略を動かし、**AutoTrader Bridge** が kabu ステーション（auカブコム証券）へ日経225先物を発注します。

```
[AutoTrader Local（Python）] ──Webhook──> [AutoTrader Bridge] ──> [kabu ステーション] ──> 大阪取引所
```

## ダウンロード（Releases）

[Release ページ](../../releases/latest)の「**Assets**」から、**`AutoTrader-Local-Setup-x.y.z.exe`（約 37 MB）1 つ**をダウンロードしてください。`.sha256` は改ざん確認用のテキストです。

**Python も .NET も要りません**（実行に必要なものは Setup に入っています）。

## 必要なもの（ご自身でご用意ください）

- Windows 10（1809 以降）／ 11（x64）
- kabu ステーション（auカブコム証券・API 利用設定）
- **AutoTrader Bridge**（発注を行う本体）。**AutoTrader Bridge 開発キットで作成し、インストールしておく必要があります。**ローカル版だけでは注文は出ません（記録だけが残ります）

## インストールと起動

1. `AutoTrader-Local-Setup-x.y.z.exe` をダブルクリックします。「**WindowsによってPCが保護されました**」と出たら ［詳細情報］→［実行］。
2. 画面の指示に従って ［インストール］。インストール先は **`C:\Users\<お客様の名前>\AutoTraderLocal\`** です（**管理者権限は要りません**）。
3. デスクトップの **「AutoTrader Local」** のアイコンから起動します。

**マニュアルは同梱**です（スタートメニュー →「AutoTrader Local」→「マニュアル」、または `C:\Users\<お客様の名前>\AutoTraderLocal\manual\manual.html`）。導入の流れ・戦略の登録・履歴データの取り込み・運用・困ったときは、すべてマニュアルにあります。

## 新しい版に入れ替えるとき

先にローカル版を終了し、新しい Setup を同じ手順で実行してください。**アンインストールは要りません**（上書きされます）。設定・取引記録・蓄積ストア・登録した戦略（`app\state`・`data`・`strategies`）は引き継がれます。

## ご注意

- 署名のない実行ファイルのため、Windows の SmartScreen が出ることがあります。
- **投資判断と結果はご自身の責任でお願いします。**
- 本ソフトは個人利用のみ・再配布はご遠慮ください。
