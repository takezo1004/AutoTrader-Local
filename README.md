# AutoTrader Bridge — ローカル版（kabu ステーション版）

TradingView もインターネット公開も使わず、パソコンの中だけで戦略を動かし、**AutoTrader Bridge** が kabu ステーション（auカブコム証券）へ日経225先物を発注します。

```
[ローカルエンジン（Python）] ──Webhook──> [AutoTrader Bridge] ──> [kabu ステーション] ──> 大阪取引所
```

## ダウンロード（Releases）

| ファイル | 中身 |
|---|---|
| `N225AutoTrader-Local-x.y.z.zip` | ローカルエンジン一式＋ブリッジのインストーラー（`N225BrokerBridge-Setup-x.y.z.exe`）＋起動バッチ＋ユーザーマニュアル |

`.sha256`（改ざん確認用）を添えています。

## 必要なもの（ご自身でご用意ください）

- Windows 10（1809 以降）／ 11（x64）
- kabu ステーション（auカブコム証券・API 利用設定）
- uv（Python 環境を自動で作るツール。PowerShell で 1 行）

## 手順（概略。詳しくは ZIP 内の README と `engine/docs/USER_MANUAL.md`）

1. ZIP を展開し、`N225BrokerBridge-Setup-x.y.z.exe` を実行してブリッジを入れる。
2. PowerShell で `irm https://astral.sh/uv/install.ps1 | iex`（uv の導入・初回のみ）。
3. `起動_N225LocalEngine.bat` をダブルクリック（初回は環境構築のあとダッシュボードが開きます）。

## ご注意

- インストール時に Windows の SmartScreen が出ることがあります（署名なしのため）。「詳細情報」→「実行」で進めます。
- 本ソフトは個人利用のみ・再配布禁止です。投資判断と結果はご自身の責任でお願いします。
