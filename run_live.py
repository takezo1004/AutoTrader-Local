# -*- coding: utf-8 -*-
"""起動②: ヘッドレス・ライブ実行（GUI なし・設計 v2.0）。

  python run_live.py [warmup_csv]

ブリッジ(tick転送 TCP5000)からの確定足/tick で登録戦略を実行する。
**記録は全戦略・常時／送出は戦略の「有効」(registered.json の enabled)のみ**（仮想/本番のグローバルモードは廃止）。
warmup_csv を渡すと起動時 warmup（kabu CSV ≈335本）を投入して即発注解禁にする。

※旧 M1–M5（BatchStrategyAdapter 版）の run_live は破棄。本ファイルは v2.0（二刀エンジン）版。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.engine import LocalEngineController          # noqa: E402
from app.feed.live_feed import LiveFeed               # noqa: E402
from app.feed.ohlc_storage import OHLCStorage         # noqa: E402
from app.feed.history_seed import seed_storage_from_kabu  # noqa: E402

ROOT = Path(__file__).resolve().parent


def main():
    # ★単一インスタンスガード：ダッシュボードと同じ Mutex 名で相互排他（tick ポート :5000 競合の根絶）。
    #   既にダッシュボード or run_live が起動中なら、黙って :5000 を奪い合わず明示終了する（2026-06-23）。
    from app.instance_lock import acquire_single_instance
    if acquire_single_instance() is None:
        print("既にローカルエンジン（ダッシュボード or run_live）が起動しています。"
              "二重起動はできません（tick ポート競合防止）。先に起動中のものを終了してください。")
        return

    args = [a for a in sys.argv[1:] if a != "--live"]   # --live は廃止（送出は戦略の有効で決まる）
    warmup_csv = args[0] if args else None

    # ★起動時の自動整形：蓄積ストアが6ヶ月超なら自動で切り詰める。
    try:
        from app.feed.ohlc_storage import DEFAULT_PARQUET
        from app.backtest import data_import as _di
        _r = _di.trim_store(DEFAULT_PARQUET)
        if _r.get("changed"):
            print(f"[起動整形] 蓄積を6ヶ月にトリム: {_r['before']:,}→{_r['after']:,} 本")
    except Exception as _e:
        print(f"[起動整形] スキップ: {_e}")

    storage = OHLCStorage()
    if warmup_csv:
        seed_storage_from_kabu(warmup_csv, storage)
    warm = storage.get_latest(500)

    ctrl = LocalEngineController(strategies_dir=ROOT / "strategies",
                                 state_dir=ROOT / "app" / "state", on_log=print)
    feed = LiveFeed()                                  # OHLCManager は controller.start で配線
    ok = ctrl.start(warmup_df=(warm if warm is not None and len(warm) else None), feed=feed)
    if not ok:
        print("tick ポート(5000)が使用中のため接続できません。安全のため起動を中止しました。")
        return
    print("ライブ開始（記録＝全戦略・常時／送出＝有効戦略のみ）。Ctrl+C で終了。")
    try:
        while True:
            time.sleep(5)
            ctrl._write_state()
    except KeyboardInterrupt:
        ctrl.stop()
        print("終了")


if __name__ == "__main__":
    main()
