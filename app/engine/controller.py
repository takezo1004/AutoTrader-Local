# -*- coding: utf-8 -*-
"""LocalEngineController — ダッシュボードの頭脳（ヘッドレス・内部仕様 §9）。

責務:
  - 戦略の登録/解除（registered.json）。登録＝Explorer で選んだフォルダを strategies/ に取り込み。
  - 戦略ごと実行可否（段階1・F3）／全体 実行・停止（段階2・F5）／dry-run 切替（F4）。
  - start 時に各戦略へ sender を割当（dry-run=VirtualSink / live=BridgeSender）し warmup prime。
  - feed（OHLCManager）の on_bar_close / on_tick を LiveEngine に配線。
  - 内蔵バックテスト（F2・full_report）。
  - 状態を engine_state.json に書く（ダッシュボードが読む）。
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from .engine import LiveEngine
from .realtime_broker import RealtimeBroker
from .bridge_sender import BridgeSender, VirtualSink
from .bridge_process import BridgeProcess, DEFAULT_BRIDGE_EXE
from .strategy_loader import load_strategy, validate_folder
from .bridge_secret import read_bridge_passphrase

# ★パスフレーズ(passphrase)は「ブリッジ(appsettings.Local.json・DPAPI)から起動時に取得」し、
#   メモリ上だけで保持する。ローカル版は**外部ファイルに保存しない**（旧 secret.json は廃止）。
#   webhook の両端で一致必須の共有値なので、ブリッジを正として取得する。


def _norm_ts(s) -> str:
    """突合・並べ替え用に時刻文字列を正規化（'YYYY-MM-DD HH:MM:SS'・T/末尾切り捨て）。"""
    return str(s).strip().replace("T", " ")[:19]


def pair_trades(records: list) -> dict:
    """発火記録（新規/決済）を戦略×建値時刻でペアリングし取引一覧を組む（純関数）。

    取引記録の「取引一覧」表示と、BT 取引一覧との突合に共通で使う唯一のロジック。
    戻り: {"closed": [...], "open": [...], "orphan": [...]}
      closed: 損益(pnl_jpy/pnl_pt)が記録された決済レグ（発生順）。
      open  : 決済し切っていない新規＝未決済（残数量 open_qty を付与）。
      orphan: 損益が記録されていない決済＝計算不可（損益記録なし）。
    ＝建玉管理はしない。記録（発火）の組み合わせだけで一覧を作る。

    ★損益・累計は決済レコード自身の記録値で完結させ、新規との対応付けに依存させない。
      （決済レコードは entry_ts/建値/損益をすべて自分で持つ。新規↔決済の照合は
      「未決済（保有中）の残数量算出」だけに使う。以前は照合できない決済を累計から
      除外しており、entry_ts の秒ズレ＝ライブ受信時刻 vs 再起動 warmup のバー時刻＝で
      +125,500 円が漏れた実害あり・2026-07-08 修正）
    未決済算出の照合は2段：①完全一致 → ②同戦略で建値時刻が最も近い新規（許容差 90 秒。
    同一戦略の再エントリーは最短でも 1 バー＝300 秒離れるため誤対応しない）。
    """
    from collections import defaultdict
    from datetime import datetime as _dtm

    def _parse(s):
        s = _norm_ts(s)
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return _dtm.strptime(s, fmt)
            except Exception:
                continue
        return None

    entries = {}                                   # (戦略, 建値時刻) -> 新規レコード
    entry_ts_by_stg = defaultdict(list)            # 戦略 -> [(datetime, key)]（近傍照合用）
    for r in records:
        if r.get("kind") == "新規":
            key = (r.get("strategy"), _norm_ts(r.get("entry_ts")))
            entries[key] = r
            d = _parse(r.get("entry_ts"))
            if d is not None:
                entry_ts_by_stg[r.get("strategy")].append((d, key))
    closed_qty: dict = defaultdict(int)
    closed, orphan = [], []
    for r in records:
        if r.get("kind") != "決済":
            continue
        if r.get("pnl_jpy") is None and r.get("pnl_pt") is None:
            orphan.append(r)                       # 損益未記録 → 計算不可
            continue
        closed.append(r)                           # 損益が記録されていれば無条件で累計対象
        # 以下は未決済算出のための数量消し込みのみ（照合失敗しても損益計算には影響しない）
        key = (r.get("strategy"), _norm_ts(r.get("entry_ts")))
        if entries.get(key) is None:               # ①完全一致なし → ②近傍照合（≤90秒）
            d = _parse(r.get("entry_ts"))
            best = None
            if d is not None:
                for ed, ekey in entry_ts_by_stg.get(r.get("strategy"), []):
                    diff = abs((ed - d).total_seconds())
                    if diff <= 90 and (best is None or diff < best[0]):
                        best = (diff, ekey)
            key = best[1] if best is not None else None
        if key is not None:
            closed_qty[key] += int(r.get("qty") or 0)
    opens = []
    for (stg, ets), ent in entries.items():
        rem = int(ent.get("qty") or 0) - closed_qty.get((stg, ets), 0)
        if rem > 0:                                # 決済し切っていない＝未決済
            o = dict(ent); o["open_qty"] = rem; opens.append(o)
    return {"closed": closed, "open": opens, "orphan": orphan}


class LocalEngineController:
    def __init__(self, strategies_dir, state_dir,
                 bridge_url: str = "http://localhost:8001/webhook",
                 bridge_exe=None, on_log=None, sender_factory=None):
        self.strategies_dir = Path(strategies_dir)
        self.state_dir = Path(state_dir)
        self.strategies_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.registered_path = self.state_dir / "registered.json"
        self.engine_state_path = self.state_dir / "engine_state.json"
        self.settings_path = self.state_dir / "settings.json"
        self.trade_log_path = self.state_dir / "trade_log.jsonl"   # 取引イベント記録（全戦略・累積）
        # ★仮想/本番のグローバルモード(dry_run)は廃止。記録は常時・全戦略。注文は戦略ごとの enabled のみ。
        # on_log は「GUI ログ欄へ転送 ＋ 永続ファイルへ必ず残す」。ダッシュボードが後から
        # self.on_log = ... と差し替えても、永続化は property 経由で常に効く（2026-06-23）。
        self._user_on_log = on_log or (lambda m: None)
        self.start_error: str | None = None     # 直近の起動失敗理由（None=正常）。engine_state に出して可視化。
        self._settings = self._read_settings()
        # ★詳細デバッグログの ON/OFF を settings.json から反映（既定 True・決め打ちしない）。
        try:
            from app.feed import logger as _flog
            _flog.set_debug(bool(self._settings.get("debug_log", True)))
        except Exception:
            pass
        # ★パスフレーズは「ブリッジから取得」してメモリ保持（外部ファイルに保存しない）。
        self.passphrase = read_bridge_passphrase()                   # 起動時に自動取得（無ければ ""）
        if self._settings.pop("passphrase", None) is not None:       # 旧 settings.json 内の平文があれば除去のみ
            self._write_settings()
        self.bridge_url = self._settings.get("bridge_url", bridge_url)
        # 注文チャネル（webhook 送出）の生成を seam 化＝唯一の出口。既定は実 BridgeSender（本番）。
        #   テストは sender_factory に捕捉シンクを注入して実ブリッジ/実ネットワークへ出さない。
        #   closure で self.bridge_url を都度参照＝set_bridge_url の変更も反映。
        self._sender_factory = sender_factory or (
            lambda: BridgeSender(self.bridge_url, on_log=self.on_log))
        # データパス（内蔵BT・warmup 用・設定で変更可）。既定＝製品ツリーの data/。
        _data = self.state_dir.parent.parent / "data"
        self.parquet_path = self._settings.get("parquet_path") or str(_data / "ohlc_live.parquet")
        self.csv_dir = self._settings.get("csv_dir") or str(_data / "csv_import")
        self.engine = LiveEngine(on_log=self.on_log)
        _port = urlparse(self.bridge_url).port or 8001
        self.bridge = BridgeProcess(exe_path=(bridge_exe or self._settings.get("bridge_exe")),
                                    webhook_port=_port, on_log=self.on_log)   # 外部ブリッジ制御
        self._kabu_ok = False                # 外部状態キャッシュ（poll_external で更新）
        self._bridge_up = False              # ブリッジ起動中（手動起動含む・port判定）
        self._bridge_self = False            # ダッシュボードが起動した分か（停止可否）
        self._feed_connected = False         # tick が来ているか（ai_feed_status.json）
        self._loaded: dict = {}              # name(フォルダ名=エンジンID) -> LoadedStrategy
        self._registered = self._read_registered()
        self.feed = None
        # ★稼働中の登録/設定変更に伴う「再warmup→再有効化」の直列化用（2026-07-02 非同期化）。
        #   GUI スレッドで同期実行すると全戦略再warmup（実測42秒）で画面が固まる＝ハングに見える事故の修正。
        self._rewarm_lock = threading.Lock()
        self._rewarm_active = False   # 再warmup 進行中フラグ（進行中の連続保存でも「稼働中」と扱うため）
        self.load_all()

    # ───────────── ログ（GUI 転送 ＋ 永続ファイル）─────────────
    @property
    def on_log(self):
        """呼び出し用ログ関数。永続ファイルへ必ず残してから利用側（GUI 等）へ転送する。"""
        return self._emit_log

    @on_log.setter
    def on_log(self, fn):
        self._user_on_log = fn or (lambda m: None)

    def _emit_log(self, msg) -> None:
        try:
            from app.feed import logger as _flog
            _flog.persist(msg)                 # ★まず永続ファイルへ（pythonw でも消えない）
        except Exception:
            pass
        try:
            self._user_on_log(msg)             # GUI ログ欄など
        except Exception:
            pass

    # ───────────── settings.json（グローバル：passphrase 等）─────────────
    def _read_settings(self) -> dict:
        if self.settings_path.exists():
            try:
                return json.loads(self.settings_path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _write_settings(self) -> None:
        self.settings_path.write_text(
            json.dumps(self._settings, ensure_ascii=False, indent=2), encoding="utf-8")

    # ───────────── パスフレーズ（ブリッジから取得・メモリのみ・ファイル保存なし）─────────────
    def set_passphrase(self, secret: str) -> None:
        """パスフレーズをメモリに設定し全 broker へ反映（外部ファイルには保存しない）。"""
        self.passphrase = secret or ""
        for rb in self.engine._brokers.values():
            rb.passphrase = self.passphrase

    def refresh_passphrase_from_bridge(self) -> str:
        """ブリッジ(appsettings.Local.json・DPAPI)から passphrase を取得しメモリに設定。戻り＝取得値。"""
        v = read_bridge_passphrase()
        self.set_passphrase(v)
        self.on_log("パスフレーズをブリッジから取得" + ("" if v else "（取得できませんでした）"))
        return v

    # ───────────── 取引記録（仮想/本番・新規/決済を発生順に累積・trade_log.jsonl）─────────────
    def _is_enabled_alert(self, alert) -> bool:
        """alert_name の戦略が有効（注文ON）か。"""
        return any(r.get("enabled") and r.get("alert_name", r["name"]) == alert
                   for r in self._registered)

    def _on_trade_event(self, ev: dict) -> None:
        """RealtimeBroker からの取引イベント（新規/決済）に mode を付けて JSONL 追記。

        記録は全戦略・常時。mode は従来フォーマットのまま「本番/仮想」：有効(注文した)＝本番／
        無効(記録のみ・注文なし)＝仮想。後で実際の約定と突き合わせる際にどれを送ったか分かる。
        """
        rec = dict(ev)
        # ★時刻は記録層で正規化：warmup(履歴リプレイ)由来の建玉は entry_ts が numpy datetime64＝
        #   'YYYY-MM-DDTHH:MM:SS.000000000' になり、ライブ発火('YYYY-MM-DD HH:MM:SS')と構造が食い違う。
        #   ここで唯一の書込地点として ts/entry_ts をライブ形式へ統一し、混入を恒久遮断する。
        #   ※戦略に渡す bar.ts(numpy)は不変＝offline≡warmup≡live の型一致・BT/golden/戦略ロジックに無影響。
        for _k in ("ts", "entry_ts"):
            if rec.get(_k) is not None:
                rec[_k] = _norm_ts(rec[_k])
        rec["mode"] = "本番" if self._is_enabled_alert(ev.get("strategy")) else "仮想"
        try:
            with open(self.trade_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception as e:
            self.on_log(f"取引記録の書込エラー: {e}")
        kind = rec.get("kind", "")
        strat = rec.get("strategy", "")
        d = rec.get("dir", "")
        q = rec.get("qty", "")
        mode = rec.get("mode", "")
        extra = f" {rec['pnl_jpy']:+,}円" if rec.get("pnl_jpy") is not None else ""
        rtxt = f" {rec.get('reason')}" if rec.get("reason") and kind == "決済" else ""
        # ★一行に詳細表示: どの戦略か・種別・方向×数量・価格・損益・決済理由・モード(本番/仮想)
        self.on_log(f"[記録] {strat} {kind} {d}×{q} @{rec.get('price')}{extra}{rtxt} [{mode}]")

    # ───────────── 建玉スナップショット（受動記録のみ・2026-06-29）─────────────
    #   ★再起動時の建玉復元は warmup_replay（履歴リプレイ＝TV 同一シーケンス）に置換済。
    #   下記は最終既知建玉の受動的な記録（診断用）であり、startup では restore に使わない。
    def positions_dir(self) -> Path:
        """建玉スナップショットの保存フォルダ（app/state/positions・無ければ作る）。"""
        d = self.state_dir / "positions"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _save_position(self, name: str) -> None:
        """戦略 name の現在建玉を positions/<name>.json へ保存（flat は削除）。enabled/disabled 両方。"""
        rb = self.engine._brokers.get(name)
        if rb is None:
            return
        p = self.positions_dir() / f"{name}.json"
        try:
            snap = rb.snapshot()
            if snap is None:
                if p.exists():
                    p.unlink()                       # flat → 削除
            else:
                p.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            self.on_log(f"建玉スナップショット保存エラー({name}): {e}")

    def _load_position(self, name: str) -> dict | None:
        p = self.positions_dir() / f"{name}.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _save_all_positions(self) -> None:
        """全 broker の建玉を保存（確定足ごと＝tp1/tp2 確定後に呼ぶ）。"""
        for name in list(self.engine._brokers.keys()):
            self._save_position(name)

    def _make_on_event(self, name: str):
        """取引イベントハンドラ（記録＋建玉スナップショット保存）を登録名つきで作る。"""
        def handler(ev):
            self._on_trade_event(ev)
            self._save_position(name)                # fill 時に即保存（建玉/filled_ids を反映）
        return handler

    def read_trade_log(self) -> list:
        """取引記録を全件読み込む（list[dict]・発生順）。"""
        p = self.trade_log_path
        if not p.exists():
            return []
        out = []
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                pass
        return out

    def clear_trade_log(self) -> None:
        """取引記録を全件クリア（ファイル削除）。"""
        try:
            if self.trade_log_path.exists():
                self.trade_log_path.unlink()
        except Exception as e:
            self.on_log(f"取引記録クリア失敗: {e}")

    def _rewrite_trade_log(self, recs: list) -> None:
        """取引記録を recs で上書き保存（空なら削除）。"""
        if not recs:
            self.clear_trade_log()
            return
        try:
            with open(self.trade_log_path, "w", encoding="utf-8") as f:
                for r in recs:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        except Exception as e:
            self.on_log(f"取引記録の書込エラー: {e}")

    def delete_strategy_records(self, strategy: str) -> int:
        """指定戦略（alert_name）の取引記録だけを削除。戻り＝削除件数。

        戦略を使わなくなって登録解除する時などに、その戦略の過去記録を消す（①B案・手動）。
        """
        recs = self.read_trade_log()
        keep = [r for r in recs if r.get("strategy") != strategy]
        removed = len(recs) - len(keep)
        if removed:
            self._rewrite_trade_log(keep)
            self.on_log(f"取引記録から「{strategy}」を {removed} 件削除")
        return removed

    @staticmethod
    def _rec_date(rec: dict):
        """記録の ts を date へ。失敗時 None。"""
        s = str(rec.get("ts", "")).strip().replace("T", " ")[:19]
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
            try:
                return datetime.strptime(s, fmt).date()
            except Exception:
                continue
        return None

    def history_dir(self) -> Path:
        """アーカイブCSVの保存フォルダ（data/history・無ければ作る）。"""
        d = self.state_dir.parent.parent / "data" / "history"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def list_archives(self) -> list:
        """退避済みの四半期アーカイブCSV一覧（新しい順）。"""
        d = self.state_dir.parent.parent / "data" / "history"
        if not d.exists():
            return []
        return sorted(d.glob("trade_archive_*.csv"), reverse=True)

    def archive_old_records(self, months: int = 6) -> tuple:
        """months ヶ月より古い取引記録を data/history の四半期CSV（trade_archive_YYYY-Qn.csv）へ
        退避し、ライブログから取り除く（②C案・ローリング・アーカイブ）。戻り＝(件数, 退避先list)。

        現在の直近 months ヶ月は消えない（古い分だけCSVへ退避）。ろうそく足の6ヶ月ローリングと同じ思想。
        """
        import csv
        from collections import defaultdict
        from datetime import timedelta
        recs = self.read_trade_log()
        if not recs:
            return 0, []
        cutoff = (datetime.now() - timedelta(days=int(months * 30))).date()
        old, keep = [], []
        for r in recs:
            d = self._rec_date(r)
            (old if (d is not None and d < cutoff) else keep).append(r)
        if not old:
            return 0, []
        cols = ["ts", "mode", "strategy", "kind", "dir", "qty", "price",
                "entry_ts", "entry_price", "pnl_pt", "pnl_jpy", "reason", "trade_id"]
        groups = defaultdict(list)
        for r in old:
            d = self._rec_date(r)
            q = (d.month - 1) // 3 + 1
            groups[f"{d.year}-Q{q}"].append(r)
        written = []
        hd = self.history_dir()
        for key, rows in sorted(groups.items()):
            p = hd / f"trade_archive_{key}.csv"
            new = not p.exists()
            try:
                with open(p, "a", newline="", encoding="utf-8-sig") as f:
                    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
                    if new:
                        w.writeheader()
                    w.writerows(rows)
                written.append(p)
            except Exception as e:
                self.on_log(f"アーカイブ書込エラー({key}): {e}")
        self._rewrite_trade_log(keep)
        self.on_log(f"取引記録 {len(old)} 件を history へアーカイブ（{months}ヶ月より前・{len(written)}ファイル）")
        return len(old), written

    def prune_old_archives(self, keep_quarters: int = 8) -> list:
        """四半期アーカイブCSV（trade_archive_YYYY-Qn.csv）を新しい順に keep_quarters 個残し、
        それ以前を完全削除する（②C案アーカイブの最終ローリング）。

        archive_old_records がライブ記録を四半期CSVへ退避し続けるため、退避先の data/history が
        無限に増える。直近 keep_quarters（既定8＝約2年分）だけ残して古い四半期は削除する。
        戻り＝削除した Path のリスト。
        """
        files = self.list_archives()              # 新しい順（reverse=True）
        to_delete = files[keep_quarters:]         # 保持数を超えた古い四半期
        deleted = []
        for p in to_delete:
            try:
                p.unlink()
                deleted.append(p)
            except Exception as e:
                self.on_log(f"アーカイブ削除エラー({p.name}): {e}")
        if deleted:
            self.on_log(f"古い取引アーカイブ {len(deleted)} 四半期分を削除（直近{keep_quarters}四半期を保持）")
        return deleted

    def set_bridge_url(self, url: str) -> None:
        self.bridge_url = url or "http://localhost:8001/webhook"
        self._settings["bridge_url"] = self.bridge_url
        self._write_settings()

    def set_calendar_url(self, url: str | None) -> None:
        """市場カレンダーの取得元URL（JPX）を settings.json に保存（空なら既定にフォールバック）。
        ★将来 JPX がURLを変えても、コード変更なしでここを差し替えれば取得が復帰する。"""
        u = (url or "").strip()
        if u:
            self._settings["jpx_calendar_url"] = u
        else:
            self._settings.pop("jpx_calendar_url", None)
        self._write_settings()

    def set_bridge_exe(self, path: str | None) -> None:
        self._settings["bridge_exe"] = path or None
        self._write_settings()
        self.bridge.exe_path = Path(path) if path else DEFAULT_BRIDGE_EXE

    def set_data_paths(self, parquet_path: str | None = None, csv_dir: str | None = None) -> None:
        if parquet_path is not None:
            self.parquet_path = parquet_path; self._settings["parquet_path"] = parquet_path
        if csv_dir is not None:
            self.csv_dir = csv_dir; self._settings["csv_dir"] = csv_dir
        self._write_settings()

    def set_ui_prefs(self, theme: str | None = None, font_scale=None) -> None:
        """テーマ（dark/light）・文字サイズ（font_scale）を保存（再起動で反映）。"""
        if theme is not None:
            self._settings["theme"] = "light" if str(theme).lower() == "light" else "dark"
        if font_scale is not None:
            self._settings["font_scale"] = float(font_scale)
        self._write_settings()

    def settings(self) -> dict:
        """設定画面が表示する現在値。"""
        return {"passphrase": self.passphrase, "bridge_url": self.bridge_url,
                "bridge_exe": self._settings.get("bridge_exe") or str(DEFAULT_BRIDGE_EXE),
                "parquet_path": self.parquet_path, "csv_dir": self.csv_dir,
                "theme": self._settings.get("theme", "dark"),
                "font_scale": float(self._settings.get("font_scale", 1.0)),
                "jpx_calendar_url": self._settings.get("jpx_calendar_url", "")}

    # ───────────── registered.json ─────────────
    def _read_registered(self) -> list:
        if self.registered_path.exists():
            try:
                return json.loads(self.registered_path.read_text(encoding="utf-8")).get("strategies", [])
            except Exception:
                return []
        return []

    def _write_registered(self) -> None:
        self.registered_path.write_text(
            json.dumps({"strategies": self._registered}, ensure_ascii=False, indent=2),
            encoding="utf-8")

    # ───────────── 登録・解除（F1・2段階）─────────────
    def register(self, folder, alert_name: str | None = None, interval: int | None = None,
                 description: str = "", enabled: bool = False) -> str:
        """① 配布フォルダ取り込み ＋ ② ブリッジ登録情報（ショートネーム/足/説明/有効）。

        alert_name/interval 省略時は manifest の name/interval を既定にする。
        """
        src = Path(folder).resolve()
        ok, why = validate_folder(src)
        if not ok:
            raise ValueError(f"登録できません: {why}")
        name = src.name                      # フォルダ名＝エンジン内 戦略ID（内部一意）
        dst = (self.strategies_dir / name).resolve()
        if src != dst:                       # strategies/ 外 → コピー取り込み（自己完結・ZIP 解凍を想定）
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        mf = load_strategy(dst).manifest
        # 登録物を自己記述に統一：manifest.json が無ければ MANIFEST から生成（ZIP配布物は同梱済）。
        mfp = dst / "manifest.json"
        if not mfp.exists():
            mfp.write_text(json.dumps(mf, ensure_ascii=False, indent=2), encoding="utf-8")
        entry = {
            "name": name, "folder": str(dst),
            "alert_name": (alert_name or mf.get("name", name)),      # ブリッジ短名（webhook alert_name）
            "interval": int(interval or mf.get("interval", 15)),
            "enabled": bool(enabled),
            "description": description or "",
            "version": int(mf.get("version", 1)),
        }
        self._registered = [r for r in self._registered if r["name"] != name] + [entry]
        self._write_registered()
        self.reload_one(name)     # ★差分（稼働中＝当該のみ裏で warmup・他戦略は無停止。未稼働＝load_all に委譲）
        self.on_log(f"登録: {name}（alert={entry['alert_name']} / {entry['interval']}分）")
        return name

    def reload_one(self, name: str) -> None:
        """★差分リロード（2026-07-02）：登録済みの1戦略だけフレッシュ再読込→裏で warmup→原子的差替。
        全戦略再構築（load_all＝実測42秒・その間 全戦略判定停止）と違い、**他戦略は無停止・
        engine.running も維持**（差替までは旧実体が処理を続ける＝ダウンタイム実質ゼロ）。
        engine 未稼働（起動前/停止中）は従来どおり load_all に委譲。
        """
        entry = self.get_entry(name)
        if entry is None:
            raise KeyError(f"未登録: {name}")
        if not (getattr(self.engine, "running", False) or getattr(self, "_rewarm_active", False)):
            self.load_all()               # 未稼働＝全読込（起動時と同じ・軽い）
            return
        self.on_log(f"[{name}] 差分リロード：バックグラウンドで warmup 中…（他戦略は無停止・完了時に差替）")

        def _work():
            try:
                ls = load_strategy(entry["folder"])       # config.json を読み直したフレッシュ実体
                rb = RealtimeBroker(ls.instance,
                                    name=entry.get("alert_name", ls.name),
                                    interval=int(entry.get("interval", ls.manifest.get("interval", 15))),
                                    passphrase=self.passphrase)
                rb.on_event = self._make_on_event(name)
                df = self._build_warmup_df()              # 重い読込も warmup も旧実体が生きたまま裏で
                with self._rewarm_lock:                   # 全体再warmup・他の差分と直列化
                    self._loaded[name] = ls
                    self._warm_one(name, rb, df, entry.get("enabled", False))
                    self.engine.upsert(name, rb,
                                       enabled=entry.get("enabled", False), ready=rb._warm_ready)
                self._write_state()
                self.on_log(f"[{name}] 差分リロード完了（他戦略は無停止）")
            except Exception as e:
                self.on_log(f"⚠ [{name}] 差分リロード失敗（旧実体のまま継続。直らなければ再起動）: {e}")

        threading.Thread(target=_work, daemon=True, name=f"le-reload-{name}").start()

    def update_registration(self, name: str, alert_name=None, interval=None,
                            description=None, enabled=None) -> None:
        """②ブリッジ登録情報の編集（再設定）。"""
        for r in self._registered:
            if r["name"] == name:
                if alert_name is not None: r["alert_name"] = alert_name
                if interval is not None: r["interval"] = int(interval)
                if description is not None: r["description"] = description
                if enabled is not None: r["enabled"] = bool(enabled)
        self._write_registered()
        self.reload_one(name)     # ★差分（稼働中＝当該のみ・他戦略は無停止。未稼働＝load_all に委譲）
        self.on_log(f"登録更新: {name}")

    def unregister(self, name: str, drop_records: bool = False) -> int:
        """登録解除。drop_records=True ならその戦略（alert_name）の取引記録も削除（①A案・連動）。
        戻り＝削除した取引記録の件数。"""
        entry = self.get_entry(name)
        removed = 0
        if drop_records and entry:
            removed = self.delete_strategy_records(entry.get("alert_name", name))
        self._registered = [r for r in self._registered if r["name"] != name]
        self._write_registered()
        self.engine.remove(name)
        self._loaded.pop(name, None)
        self.on_log(f"登録解除: {name}" + (f"（取引記録 {removed} 件も削除）" if removed else ""))
        return removed

    def get_entry(self, name: str) -> dict | None:
        return next((r for r in self._registered if r["name"] == name), None)

    # ───────────── 配布パッケージの取り込み（ZIP / フォルダ）─────────────
    @staticmethod
    def _find_strategy_dir(root: Path) -> Path | None:
        """root 自身か直下サブフォルダから strategy.py を持つ戦略フォルダを探す。"""
        root = Path(root)
        if (root / "strategy.py").exists():
            return root
        for sub in sorted(root.iterdir()):
            if sub.is_dir() and (sub / "strategy.py").exists():
                return sub
        return None

    def resolve_package(self, path) -> Path:
        """配布パッケージ（.zip）なら一時展開し戦略フォルダを返す。フォルダならそのまま。"""
        p = Path(path)
        if p.is_file() and p.suffix.lower() == ".zip":
            tmp = Path(tempfile.mkdtemp(prefix="n225strat_"))
            with zipfile.ZipFile(p) as z:
                z.extractall(tmp)
            folder = self._find_strategy_dir(tmp)
            if folder is None:
                raise ValueError("ZIP 内に strategy.py を含む戦略フォルダが見つかりません")
            self.on_log(f"ZIP 展開: {p.name} → {folder.name}")
            return folder
        return p

    # ───────────── ロード ─────────────
    def load_all(self) -> None:
        # ★稼働中に登録/更新/パラメータ保存された場合は、engine を作り直しても再起動なしで復帰させる。
        #   （旧挙動＝load_all が engine を作り直し全戦略 ready=false 化し、start() を再実行しないため、
        #    稼働中の登録1つで全戦略が無効化され「再起動するまでゼロ」になっていた。2026-06-29 修正）
        # ★「稼働中」判定は engine.running に加えて『再warmup 進行中』も含める（2026-07-02）。
        #   進行中に再度保存されると新 engine はまだ running=False のため、従来判定では再有効化が
        #   スキップされ、先行 warmup も世代落ちで破棄＝誰も再開しない事故になる（テストで検出）。
        was_running = (getattr(self, "engine", None) is not None and getattr(self.engine, "running", False)) \
            or getattr(self, "_rewarm_active", False)
        self.engine = LiveEngine(on_log=self.on_log)
        self._loaded = {}
        for r in self._registered:
            try:
                ls = load_strategy(r["folder"])
            except Exception as e:
                self.on_log(f"読込失敗 {r['name']}: {e}")
                continue
            # webhook はブリッジ短名(alert_name)＋足(interval)＋共通 passphrase で送る（F1②）。
            rb = RealtimeBroker(ls.instance,
                                name=r.get("alert_name", ls.name),
                                interval=int(r.get("interval", ls.manifest.get("interval", 15))),
                                passphrase=self.passphrase)
            rb.on_event = self._make_on_event(r["name"])   # 取引イベント記録＋建玉スナップショット保存
            self.engine.add(r["name"], rb, enabled=r.get("enabled", False))   # キー=フォルダ名(ID)
            self._loaded[r["name"]] = ls
        if was_running:
            # ★再有効化：feed コールバックは self.engine を動的参照（_engine_on_tick / _on_confirmed_bar）
            #   なので貼り直し不要。各戦略を warmup→ready→sender 割当し直して処理再開。
            # ★2026-07-02 非同期化：この再warmup（全戦略・実測42秒）を GUI スレッドで同期実行すると
            #   画面が「応答なし」になる（起動時 warmup は元々スレッド化済＝同じパターンに揃える）。
            #   warmup 完了まで engine.running=False＝tick/確定足はスキップ・発注しない（従来と同じ安全動作）。
            #   連続保存対策＝_rewarm_lock で直列化＋「最後の load_all が勝つ」（古い warmup は破棄）。
            eng = self.engine                      # この load_all が作った engine（世代チェック用）
            self._rewarm_active = True             # 進行中フラグ（次の load_all も「稼働中」と判定させる）
            self.on_log("登録/設定変更を受付：バックグラウンドで再warmup中…（完了まで新規判定を停止・完了時にログが出ます）")

            def _rewarm():
                try:
                    df = self._build_warmup_df()   # 重い読込も GUI の外で
                    with self._rewarm_lock:        # 再warmupは常に1本ずつ（連打・多重保存でも直列）
                        if self.engine is not eng:
                            return                 # 世代落ち＝後続 load_all のワーカーが管理（フラグも後続が持つ）
                        self._activate_brokers(df)
                        self.engine.running = True
                    self._write_state()
                    self.on_log("登録/設定変更を反映：稼働中の戦略を再 warmup→有効化（再起動不要）")
                except Exception as e:
                    if self.engine is eng:
                        self.engine.running = False
                        self.on_log(f"⚠ 登録変更後の再有効化に失敗（再起動してください）: {e}")
                        self._write_state()
                finally:
                    if self.engine is eng:         # 自分が最終世代のときだけ進行中フラグを下ろす
                        self._rewarm_active = False

            threading.Thread(target=_rewarm, daemon=True, name="le-rewarm").start()

    # ───────────── 制御（F3：戦略ごと注文ON/OFF）─────────────
    def set_enabled(self, name: str, val: bool) -> None:
        """戦略ごとの注文可否。記録は常時なので、ここでは注文経路(sender)だけを切り替える。"""
        self.engine.set_enabled(name, val)
        for r in self._registered:
            if r["name"] == name:
                r["enabled"] = bool(val)
        self._write_registered()
        rb = self.engine._brokers.get(name)                    # 注文経路を即時反映
        if rb is not None:
            rb.sender = self._sender_factory() if val else None

    # ───────────── 外部ブリッジ制御（kabu 確認 → ブリッジ → オートトレード）─────────────
    def start_bridge(self) -> bool:
        return self.bridge.start()

    def stop_bridge(self) -> None:
        # ★2026-07-02: terminate→wait(5)→kill→wait(3) が最悪約8秒 GUI を止めるためスレッド化。
        #   呼び出しはダッシュボードの［■停止］ボタンのみ＝非同期化で挙動影響なし（状態はポーリング反映）。
        threading.Thread(target=self.bridge.stop, daemon=True, name="bridge-stop").start()

    def poll_external(self) -> dict:
        """kabu/ブリッジ/フィードの稼働状態を実測してキャッシュ更新（背景スレッドから3秒毎）。"""
        self._kabu_ok = self.bridge.kabu_ok()
        self._bridge_up = self.bridge.is_up()                # 手動起動含む
        self._bridge_self = self.bridge.started_by_dashboard()
        self._feed_connected = self._read_feed_connected()
        return {"kabu": self._kabu_ok, "bridge": self._bridge_up,
                "bridge_self": self._bridge_self, "feed": self._feed_connected}

    def _read_feed_connected(self) -> bool:
        """tick が実際に来ているか（live_feed が書く ai_feed_status.json の bridge_connected＋15秒以内更新）。"""
        p = self.state_dir / "ai_feed_status.json"
        if not p.exists():
            return False
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
            if not st.get("bridge_connected"):
                return False
            upd = datetime.strptime(st.get("updated", ""), "%Y-%m-%d %H:%M:%S")
            return (datetime.now() - upd).total_seconds() < 15
        except Exception:
            return False

    def _engine_on_tick(self, price, ts, bar_open=None, bar_high=None, bar_low=None):
        """feed→engine の tick 中継（self.engine を動的参照＝load_all で作り直しても追従）。"""
        self.engine.on_tick(price, ts, bar_open=bar_open, bar_high=bar_high, bar_low=bar_low)

    def _needed_warmup(self, name: str | None = None) -> int:
        """warmup に必要な本数（manifest の warmup_bars 宣言・2026-08-10 決め打ち500を廃止）。

        name 指定＝その戦略の宣言本数（無ければ従来既定の300）。
        name なし＝登録戦略全体の最大（ストアから読む本数。下限500＝従来の読み量を保証）。
        """
        if name is not None:
            ls = self._loaded.get(name)
            return int(ls.manifest.get("warmup_bars", 300)) if ls else 300
        return max([500] + [int(ls.manifest.get("warmup_bars", 300))
                            for ls in self._loaded.values()])

    @staticmethod
    def _wu_last_ts(df):
        """warmup df の最終足時刻。datetime 列（OHLCStorage.get_latest）と
        datetime index（data_provider.merge）の両形式に対応。不明は None。"""
        try:
            import pandas as pd
            if df is None or not len(df):
                return None
            if "datetime" in getattr(df, "columns", []):
                return pd.to_datetime(df["datetime"].iloc[-1])
            return pd.to_datetime(df.index[-1])
        except Exception:
            return None

    def _topup_warmup_df(self, warmup_df):
        """呼び出し側（run_live/dashboard）から渡された warmup が必要最大本数に満たなければ
        ストアから読み直して補充する（2026-08-10）。最新足を失わないよう、読み直した方が
        「長く」かつ「末尾時刻が同等以上」のときだけ差し替える（判定不能なら渡された方を維持）。"""
        need = self._needed_warmup()
        if warmup_df is not None and len(warmup_df) >= need:
            return warmup_df
        rebuilt = self._build_warmup_df()
        if rebuilt is None or not len(rebuilt):
            return warmup_df
        if warmup_df is None or not len(warmup_df):
            return rebuilt
        if len(rebuilt) > len(warmup_df):
            t_new, t_old = self._wu_last_ts(rebuilt), self._wu_last_ts(warmup_df)
            if t_new is not None and t_old is not None and t_new >= t_old:
                return rebuilt
        return warmup_df

    def _build_warmup_df(self):
        """蓄積 parquet ＋ CSV から直近 warmup 本を読む（登録後の再有効化用・dashboard と同方式）。
        読む本数＝登録戦略の宣言の最大（_needed_warmup。旧：決め打ち500本・2026-08-10 修正）。"""
        try:
            import glob
            from app.backtest import data_provider
            pq = data_provider.load_parquet(self.parquet_path)
            csvs = [data_provider.load_csv(p) for p in glob.glob(str(Path(self.csv_dir) / "*.csv"))] \
                if getattr(self, "csv_dir", None) else []
            df = data_provider.merge(pq, csvs)
            return df.tail(self._needed_warmup()) if df is not None and len(df) else None
        except Exception as e:
            self.on_log(f"warmup 読込エラー(再有効化): {e}")
            return None

    def _activate_brokers(self, warmup_df) -> None:
        """各ブローカーを warmup・リプレイ→ready 判定→sender 割当（start と「登録後の再有効化」で共用）。

        ★ウォームアップ・リプレイ（TV 同一シーケンス）：履歴足を live と同一 on_bar でブローカー駆動し、
        現在建玉・出口・指標バッファを履歴から再構築（snapshot/restore 不要）。再構築中は sender=None で
        過去トレードの webhook を送らず、最後に enabled の戦略だけ sender を割り当てる。
        ★2026-08-10：渡された warmup が宣言最大に足りなければストアから補充（決め打ち500の廃止）。
        """
        warmup_df = self._topup_warmup_df(warmup_df)
        for name, rb in self.engine._brokers.items():
            self._warm_one(name, rb, warmup_df, self.engine._enabled.get(name, False))
            self.engine.set_ready(name, rb._warm_ready)

    def _warm_one(self, name, rb, warmup_df, enabled) -> None:
        """1ブローカーの warmup・リプレイ→ready 判定→sender 割当（結果は rb._warm_ready に置く）。
        ★engine への ready 反映は呼び出し側の責務（差分リロードでは upsert 後に反映するため分離）。
        ★2026-08-10：リプレイは全戦略同一本数ではなく「その戦略の manifest 宣言本数」だけ行う
        （宣言300の戦略は300本＝速く、宣言700の戦略は700本＝ready 不能だった事故の解消。
        当日決済型のため建玉再構築に必要なのは当日セッション内＝宣言本数で常に足りる）。"""
        rb.reset()
        rb.sender = None
        ready = True
        need = self._needed_warmup(name)
        wdf = warmup_df.tail(need) if warmup_df is not None and len(warmup_df) > 0 else None
        if wdf is not None and len(wdf) > 0:
            rb.warmup_replay(wdf)
            ready = len(wdf) >= need
            # 再構築で建玉が残ったら warmup 充足に関わらず必ず ready（保有玉の出口を発火させ管理）。
            if rb.bk.pos_dir != 0:
                ready = True
        rb.sender = self._sender_factory() if enabled else None
        rb._warm_ready = ready
        n_wu = len(wdf) if wdf is not None else 0
        if not ready:
            self.on_log(f"warmup 不足のため {name} は待機（{n_wu}<{need}）")
        else:
            pos = "flat" if rb.bk.pos_dir == 0 else (f"long x{rb.bk.pos_qty}" if rb.bk.pos_dir > 0
                                                     else f"short x{rb.bk.pos_qty}")
            self.on_log(f"[warmup] {name} ready=True 注文={'有効' if enabled else '無効(記録のみ)'} "
                        f"復元建玉={pos}（warmup {n_wu}本）")

    def start(self, warmup_df=None, feed=None) -> bool:         # 自動運用 開始（起動時に自動呼出）
        # ★起動時にブリッジから passphrase を再取得（稼働中に変更されても起動時に最新一致）。
        self.refresh_passphrase_from_bridge()
        # ① フィード接続（tick入口）— ★ポート使用中なら接続せず中止（安全・本番の tick を壊さない）
        if feed is not None:
            def _on_confirmed_bar(bar):                            # ★確定足 OHLCV。「ダッシュボード表示」はセッション開始/終了の足だけ。
                #   通常足はファイル(data/logs)にのみ残す＝表示は混まないが記録は全部残る（2026-06-23）。
                #   セッション時刻は決め打ちせず _market_hours の定義を参照（日中/夜間の start/end）。
                try:
                    from app.feed import _market_hours as _mh, logger as _flog
                    line = (f"確定足 {bar['datetime']:%m/%d %H:%M} "
                            f"始値{bar['open']:.0f} 高値{bar['high']:.0f} 安値{bar['low']:.0f} "
                            f"終値{bar['close']:.0f} 出来高{bar['volume']:.0f}")
                    t = bar["datetime"].time()
                    if t in (_mh._DAY_START, _mh._DAY_END, _mh._NIGHT_START, _mh._NIGHT_END):
                        self.on_log(line)        # セッション開始/終了: ダッシュボード表示＋ファイル
                    else:
                        _flog.persist(line)      # 通常足: ファイルにのみ記録（表示しない）
                except Exception:
                    pass
                # ★2026-07-02 ②：確定足はエンジンのディスパッチキューへ積むだけ（バータイマースレッドを
                #   fan-out でブロックしない）。建玉スナップショット保存は fan-out 完了後にワーカー上で実行
                #   （＝tp1/tp2 確定後の状態を保存する従来の順序を維持）。
                def _after_fanout():
                    if self.engine.running:      # ★起動完了後のみ保存（warmup/建玉復元中の半状態を保存しない）
                        self._save_all_positions()
                self.engine.on_confirmed_bar(bar, after=_after_fanout)
            feed.mgr.on_bar_close = _on_confirmed_bar
            feed.mgr.on_tick = self._engine_on_tick   # ★動的バインド：load_all で engine を作り直しても追従
            if not feed.start():                               # 使用中なら False
                self.feed = None
                # ★黙って記録ゼロにしない：原因を engine_state とログに永続化して必ず可視化する。
                #   2026-06-23 夜、ここが静かに return False し、別インスタンス/ゾンビが tick ポートを
                #   握っていたため終夜「記録ゼロ」に気づけなかった。再発防止として状態に残す。
                self.start_error = (
                    "tick入口(ポート5000)が使用中のため接続できず、記録・注文ともに停止しています。"
                    "別のローカルエンジン（ダッシュボード or run_live）が起動していないか確認し、"
                    "そちらを終了してから再起動してください。")
                self.engine.running = False
                self.on_log("⚠ " + self.start_error)
                self._write_state()                            # ← recording:false / start_error を即座に永続化
                return False
            self.feed = feed
        self.start_error = None                                # 接続できた＝起動失敗状態を解除
        # ★②以降を try で包む：warmup/prime 等が失敗しても「feed だけ生きて記録ゼロ」を残さない。
        #   2026-06-23 の本質的異常＝「ロウソク足は作られるのに取引履歴がログに出ない」を再発させないため、
        #   どんな失敗でも feed を止め、原因を start_error＋永続ログ＋engine_state に必ず出す。
        try:
            # ② 各戦略を warmup・リプレイ（履歴から建玉再構築）＋ ready 判定（共通メソッド・登録後再有効化と共用）。
            self._activate_brokers(warmup_df)
            self.engine.running = True
            self._write_state()
            self.on_log("自動運用 開始（記録＝全戦略・常時／注文＝有効戦略のみ）")
            return True
        except Exception as e:
            # 起動途中の失敗＝記録できない状態。feed を生かしたまま放置しない（足だけ流れて記録ゼロを防ぐ）。
            self.engine.running = False
            try:
                if self.feed is not None:
                    self.feed.stop()
            except Exception:
                pass
            self.feed = None
            self.start_error = (
                f"自動運用の起動に失敗したため記録・注文を停止しました（{type(e).__name__}: {e}）。"
                "ロウソク足は流れていても記録されません。ログ(data/logs)を確認し、再起動してください。")
            self.on_log("⚠ " + self.start_error)
            self._write_state()
            return False

    def stop(self) -> None:                                    # 停止（窓を閉じる等）
        self.engine.running = False
        if self.feed is not None:
            try:
                self.feed.stop()
            except Exception:
                pass
        try:
            BridgeSender.flush(6.0)      # ★2026-07-02 ①：送信キューの未送出分を掃き出してから終了（ベストエフォート）
        except Exception:
            pass
        self._write_state()
        self.on_log("停止")

    # ───────────── 内蔵バックテスト（F2）─────────────
    def backtest(self, name: str, df, cost_pts=(0, 5, 10)) -> dict:
        """フレッシュなインスタンス（編集後 config を反映）で半年BT → full_report。"""
        from app.backtest import full_report
        folder = next((r["folder"] for r in self._registered if r["name"] == name), None)
        if folder is None:
            raise KeyError(f"未登録: {name}")
        inst = load_strategy(folder).instance       # config.json を読み直したフレッシュ実体
        return full_report(inst, df, cost_pts=cost_pts)

    # ───────────── 状態 ─────────────
    def status(self) -> dict:
        st = {
            "running": self.engine.running,        # 自動運用（feed受信・記録）稼働中
            "recording": self.engine.running,      # 記録が動いているか（=running）。明示フィールド。
            "start_error": self.start_error,       # 起動失敗理由（None=正常）。ダッシュボードが赤バナー表示。
            "kabu": self._kabu_ok,                 # カブステーション実行中
            "bridge": self._bridge_up,             # ブリッジ実行中（手動起動含む）
            "bridge_self": self._bridge_self,      # ダッシュボード起動分か（停止可否）
            "feed": self._feed_connected,          # tick 受信中か
            "strategies": self.engine.status(),
        }
        return st

    def _write_state(self) -> None:
        try:
            self.engine_state_path.write_text(
                json.dumps(self.status(), ensure_ascii=False, indent=2, default=str),
                encoding="utf-8")
        except Exception as e:
            self.on_log(f"状態書込エラー: {e}")
