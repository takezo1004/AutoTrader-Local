# -*- coding: utf-8 -*-
"""webhook 変換 — ポジション遷移 → ブリッジ webhook（spec §9・単一実装）。

詳細仕様 §G・webhook-api-spec.md v1.0.0。ポジション差分（prev→cur）を
新規/全量返済/部分返済(3Split)/ドテン に分類し webhook ペイロードを作る。

★フォーマットは **TradingView のアラート本文と同一**（2026-08-18 統一）。
  キー・並び・型をそろえる。TradingView 側の本文は下記のとおり：

      {"passphrase":…, "alert_name":…, "time":"{{time}}", "exchange":"{{exchange}}",
       "ticker":"{{ticker}}", "interval":"{{interval}}",
       "bar":{"time":…, "open":…, "high":…, "low":…, "close":…, "volume":…},
       "strategy":{"position_size":…, "order_action":…, "order_contracts":…,
                   "order_price":…, "order_id":…, "market_position":…,
                   "market_position_size":…, "prev_market_position":…,
                   "prev_market_position_size":…}}

  ※ ブリッジが読むのは passphrase / alert_name / interval / ticker と strategy 配下の
     7 項目のみ（RawWebhookPayload.cs）。他は読まれないが、**仕様が「TradingView と同一」**
     のためそろえる。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

_POS = {0: "flat", 1: "long", -1: "short"}
_JST = timezone(timedelta(hours=9))


def to_tv_time(ts) -> str:
    """足の時刻を TradingView の {{time}} と同じ形（UTC・ISO8601・末尾 Z）にする。

    ローカルの足時刻は日本時間（tz なし）。tz 付きならそのまま UTC へ変換する。
    変換できない値はそのまま文字列にして返す（送信を止めない）。
    """
    if ts is None:
        return ""
    try:
        dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        if not isinstance(dt, datetime):
            dt = datetime.fromisoformat(str(dt))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_JST)          # ローカルの足時刻＝日本時間
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return str(ts)


def position_diff_to_webhook(prev_dir: int, prev_qty: int, cur_dir: int, cur_qty: int,
                             name: str, interval: int = 15,
                             passphrase: str = "", ticker: str = "OSE:NK225M1!",
                             order_price: float = 0,
                             bar: dict | None = None, order_id: str = "",
                             exchange: str = "OSE") -> dict | None:
    """ポジション (dir, qty) の prev→cur 遷移を webhook 化。変化なし/非対応は None。

    bar      … 直近の確定足 {"time","open","high","low","close","volume"}（TradingView の bar 相当）
    order_id … TradingView の {{strategy.order.id}} 相当（決済は理由・新規は空）
    """
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

    b = bar or {}
    tv_time = to_tv_time(b.get("time"))

    return {
        "passphrase": passphrase,
        "alert_name": name,
        "time": tv_time,
        "exchange": exchange,
        "ticker": ticker,
        # ★interval は **文字列** で送る（TradingView と同じ形）。
        #   ブリッジの受信 DTO は string? Interval で受けてから数値へ変換する作りのため、
        #   数値で送ると受信時に HTTP 400（The JSON value could not be converted to System.String）。
        #   2026-08-17 の本番初送出で実際に発生（srpf1_local・注文エラー400）。
        "interval": str(int(interval)),
        "bar": {
            "time": tv_time,
            "open": float(b.get("open", 0) or 0),
            "high": float(b.get("high", 0) or 0),
            "low": float(b.get("low", 0) or 0),
            "close": float(b.get("close", 0) or 0),
            "volume": float(b.get("volume", 0) or 0),
        },
        "strategy": {
            "position_size": int(cur_dir * cur_qty),        # 符号付き（TradingView と同じ）
            "order_action": action,
            "order_contracts": int(contracts),
            # ★order_price は必ず実値を入れる。0 を送るとブリッジが「指値 0 円」として
            #   kabu へ送り、「パラメータ不正：値段指定エラー」(4002017) で必ず拒否される
            #   （2026-08-18 13:30 に発生）。TradingView は {{strategy.order.price}} で実値が入る。
            "order_price": order_price,
            "order_id": order_id or "",
            "market_position": _POS[cur_dir],
            "market_position_size": int(cur_qty),
            "prev_market_position": _POS[prev_dir],
            "prev_market_position_size": int(prev_qty),
        },
    }
