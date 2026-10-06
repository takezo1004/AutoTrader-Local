# _START_HERE.md から移した旧い節（2026-10-06）

> 現在形だけを残すため移した。

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
