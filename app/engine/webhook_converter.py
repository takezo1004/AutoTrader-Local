# -*- coding: utf-8 -*-
"""webhook 変換 — ポジション遷移 → ブリッジ webhook（spec §9・単一実装）。

詳細仕様 §G・webhook-api-spec.md v1.0.0。ポジション差分（prev→cur）を
新規/全量返済/部分返済(3Split)/ドテン に分類し webhook ペイロードを作る。
order_price=0（成行・ブリッジが対等価格執行・D7）。指値価格を載せる場合は order_price>0。
"""
from __future__ import annotations

_POS = {0: "flat", 1: "long", -1: "short"}


def position_diff_to_webhook(prev_dir: int, prev_qty: int, cur_dir: int, cur_qty: int,
                             name: str, interval: int = 15,
                             passphrase: str = "", ticker: str = "OSE:NK225M1!",
                             order_price: float = 0) -> dict | None:
    """ポジション (dir, qty) の prev→cur 遷移を webhook 化。変化なし/非対応は None。"""
    if prev_dir == cur_dir and prev_qty == cur_qty:
        return None

    if prev_dir == 0 and cur_dir != 0:                      # 新規
        action = "buy" if cur_dir > 0 else "sell"
        contracts = cur_qty
    elif cur_dir == 0 and prev_dir != 0:                    # 全量返済
        action = "sell" if prev_dir > 0 else "buy"
        contracts = prev_qty
    elif prev_dir == cur_dir and cur_qty < prev_qty:        # 部分返済（3Split）
        action = "sell" if prev_dir > 0 else "buy"
        contracts = prev_qty - cur_qty
    elif prev_dir != 0 and cur_dir != 0 and prev_dir != cur_dir:  # ドテン
        action = "buy" if cur_dir > 0 else "sell"
        contracts = cur_qty
    else:
        return None   # 同方向増（pyramiding）等＝pyramiding=1 では発生しない

    return {
        "passphrase": passphrase,
        "alert_name": name,
        # ★interval は **文字列** で送る（TradingView と同じ形）。
        #   ブリッジの受信 DTO は string? Interval で受けてから数値へ変換する作りのため、
        #   数値で送ると受信時に HTTP 400（The JSON value could not be converted to System.String）。
        #   2026-08-17 の本番初送出で実際に発生（srpf1_local・注文エラー400）。
        "interval": str(int(interval)),
        "ticker": ticker,
        "strategy": {
            "order_action": action,
            "market_position": _POS[cur_dir],
            "prev_market_position": _POS[prev_dir],
            "order_contracts": int(contracts),
            "market_position_size": int(cur_qty),
            "prev_market_position_size": int(prev_qty),
            "order_price": order_price,
        },
    }
