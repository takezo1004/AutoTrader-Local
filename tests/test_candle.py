# -*- coding: utf-8 -*-
"""J-1 ろうそく足生成テスト（詳細仕様 §J-1・最重要＝★セッション末足）。

検証済み OHLCManager の挙動を**決定的に**確認する。ろうそく足生成ロジックは無傷（D13）なので、
本テストはそれを「変えていない」ことの回帰固定＋唯一の追加 on_tick seam の確認。

隔離手法（実ロジックは触らず外部依存だけ差し替える）:
  - datetime.now() → FakeDT で凍結（タイマースレッドは使わず finalize_candle を直接呼ぶ）。
  - time.sleep(10) → no-op（板寄せの10秒待ちを瞬時化。挙動は同一）。
  - OHLCStorage / MarketSessionManager → Fake（parquet I/O・カレンダー読込を回避）。
  - 確定足は on_bar_close で捕捉、tick は on_tick で捕捉。

カバー:
  T1 on_tick seam が全 tick で発火（窓外 tick でも・確定足は無傷）
  T2 通常確定足（OHLC 累積→確定・datetime=bar_start）
  T3 ダミー足（tick 無し・前足 close でフラット）
  T4 ★板寄せ特別足（15:45・10秒後の latest_price・datetime=bar_end・executed_time 戻し）
  T5 ★executed_time 固着バグ②回帰（latest_price 無し → 特別足出ず・executed_time は False）
  T6 get_bar_times 境界（日中/夜間/早朝=前日夜間続き=バグ①回帰/隙間）
"""
import sys
from datetime import datetime as _RealDT
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # N225LocalEngine/ を path に
import app.feed.ohlc_processor as op  # noqa: E402


class FakeDT(_RealDT):
    """datetime.now() を凍結値で返す（他は本物の datetime）。"""
    _frozen = None

    @classmethod
    def now(cls, tz=None):
        return cls._frozen


class FakeStorage:
    def __init__(self):
        self.added = []
        self._seed = None

    def add_to_candle(self, c):
        self.added.append(dict(c))

    def mark_bar_completed(self):
        pass

    def get_last_bar(self):
        if self._seed is not None:
            return self._seed
        return self.added[-1] if self.added else None


class OpenSession:
    def is_market_open(self):
        return True


def _dt(y=2026, mo=6, d=16, h=0, mi=0, s=0):
    return _RealDT(y, mo, d, h, mi, s)


def _new_mgr(frozen):
    """凍結時刻 frozen でフレッシュな OHLCManager を作る（外部依存は Fake）。"""
    FakeDT._frozen = frozen
    op.datetime = FakeDT
    op.time = SimpleNamespace(sleep=lambda *a, **k: None)   # sleep(10) を瞬時化
    op.OHLCStorage = FakeStorage
    op.MarketSessionManager = OpenSession
    op.OHLCManager._instance = None                         # singleton リセット
    captured = []
    ticks = []
    # on_tick は (price, ts, bar_open=, bar_high=, bar_low=) で呼ばれ得る（OHLC 実値化・2026-06-29）。
    mgr = op.OHLCManager(on_bar_close=lambda c: captured.append(dict(c)),
                         on_tick=lambda p, t, **kw: ticks.append((p, t)))
    return mgr, captured, ticks


# ───────────────────────────── T1 ─────────────────────────────
def test_on_tick_seam_fires_for_all_ticks():
    mgr, captured, ticks = _new_mgr(_dt(h=9, mi=5))
    assert (mgr.bar_start_time, mgr.bar_end_time) == (_dt(h=9, mi=0), _dt(h=9, mi=15))
    # 窓内 tick
    mgr.update_ohlc(39000.0, 1.0, _dt(h=9, mi=6))
    mgr.update_ohlc(39020.0, 2.0, _dt(h=9, mi=10))
    # 窓外 tick（確定足には入らないが on_tick は発火する＝設計 §C.2）
    mgr.update_ohlc(38900.0, 1.0, _dt(h=8, mi=59))
    assert ticks == [(39000.0, _dt(h=9, mi=6)), (39020.0, _dt(h=9, mi=10)), (38900.0, _dt(h=8, mi=59))]
    # 確定足側は窓内2本だけ反映
    c = mgr.current_candle
    assert c["open"] == 39000.0 and c["high"] == 39020.0 and c["low"] == 39000.0
    assert c["close"] == 39020.0 and c["volume"] == 3.0 and c["datetime"] == _dt(h=9, mi=0)


# ───────────────────────────── T2 ─────────────────────────────
def test_normal_confirmed_candle():
    mgr, captured, _ = _new_mgr(_dt(h=9, mi=5))
    mgr.update_ohlc(39000.0, 1.0, _dt(h=9, mi=2))
    mgr.update_ohlc(39050.0, 1.0, _dt(h=9, mi=7))
    mgr.update_ohlc(38990.0, 1.0, _dt(h=9, mi=12))
    FakeDT._frozen = _dt(h=9, mi=15)          # バー境界に到達
    mgr.finalize_candle()
    assert len(captured) == 1
    bar = captured[0]
    assert bar["datetime"] == _dt(h=9, mi=0)
    assert (bar["open"], bar["high"], bar["low"], bar["close"]) == (39000.0, 39050.0, 38990.0, 38990.0)
    assert mgr.current_candle is None         # 確定後はクリア


# ───────────────────────────── T3 ─────────────────────────────
def test_dummy_candle_when_quiet():
    mgr, captured, _ = _new_mgr(_dt(h=9, mi=5))
    mgr.ohlc_storage._seed = {"close": 39000.0}   # 前足が存在（tick 無い静かな窓）
    FakeDT._frozen = _dt(h=9, mi=15)
    mgr.finalize_candle()
    assert len(captured) == 1
    d = captured[0]
    assert d["datetime"] == _dt(h=9, mi=0)
    assert d["open"] == d["high"] == d["low"] == d["close"] == 39000.0
    assert d["volume"] == 0


# ───────────────────────────── T4 ★最重要（フォールバック板寄せ） ─────────────────────────────
def test_closing_auction_special_candle():
    """静かな引け（板寄せ tick が来ない）のフォールバック: latest_price を datetime=bar_end の特別足に。"""
    mgr, captured, _ = _new_mgr(_dt(h=15, mi=44))
    assert (mgr.bar_start_time, mgr.bar_end_time) == (_dt(h=15, mi=30), _dt(h=15, mi=45))
    mgr.update_ohlc(39000.0, 1.0, _dt(h=15, mi=40))
    mgr.update_ohlc(39010.0, 1.0, _dt(h=15, mi=44, s=30))   # latest_price=39010
    FakeDT._frozen = _dt(h=15, mi=45, s=5)                   # 引け直後（板寄せ確定）
    mgr.finalize_candle()
    # ① 通常確定足（15:30）→ ② 板寄せ特別足（15:45・latest_price）
    assert len(captured) == 2, captured
    conf, special = captured
    assert conf["datetime"] == _dt(h=15, mi=30) and conf["close"] == 39010.0
    assert special["datetime"] == _dt(h=15, mi=45)          # ★datetime=bar_end
    assert special["open"] == special["high"] == special["low"] == special["close"] == 39010.0
    assert special["volume"] == 0
    assert mgr.executed_time is False                        # ★finally で戻る


# ───────────────────────────── T5 ★バグ②回帰 ─────────────────────────────
def test_executed_time_resets_when_no_price():
    """latest_price 無しでも executed_time は False に戻る（戻らないと翌日板寄せが出ない＝固着バグ）。"""
    mgr, captured, _ = _new_mgr(_dt(h=15, mi=44))
    # tick を一切流さない → latest_price は None。前足も無い → ダミー足も出ない。
    FakeDT._frozen = _dt(h=15, mi=45, s=3)
    mgr.finalize_candle()
    assert captured == []                                   # 特別足もダミー足も出ない
    assert mgr.executed_time is False                       # ★固着しない（バグ②修正の回帰）


# ───────────────────────────── T6 境界（バグ①回帰含む） ─────────────────────────────
def test_get_bar_times_boundaries():
    mgr, _, _ = _new_mgr(_dt(h=9, mi=5))
    f = mgr.get_bar_times
    # 日中
    assert f(_dt(h=9, mi=5)) == (_dt(h=9, mi=0), _dt(h=9, mi=15))
    assert f(_dt(h=15, mi=44)) == (_dt(h=15, mi=30), _dt(h=15, mi=45))   # 日中最後の足
    # 日中後の隙間（15:45-17:00）→ 夜間開始へ
    assert f(_dt(h=15, mi=50)) == (_dt(h=17, mi=0), _dt(h=17, mi=15))
    # 夜間
    assert f(_dt(h=18, mi=7)) == (_dt(h=18, mi=0), _dt(h=18, mi=15))
    assert f(_dt(h=23, mi=59)) == (_dt(h=23, mi=45), _dt(d=17, h=0, mi=0))  # 日跨ぎ（翌0:00）
    # 早朝 0:00-6:00 = 前日夜間の続き（★バグ①回帰: session を当日境界で正しく）
    assert f(_dt(h=2, mi=30)) == (_dt(h=2, mi=30), _dt(h=2, mi=45))
    assert f(_dt(h=5, mi=50)) == (_dt(h=5, mi=45), _dt(h=6, mi=0))          # 夜間最後の足（6:00 クランプ）
    # 6:00-8:45 の隙間 → 日中開始へ
    assert f(_dt(h=6, mi=30)) == (_dt(h=8, mi=45), _dt(h=9, mi=0))


# ───────────────────────────── T7 ★出来高時間ロール（出来高過少バグ修正） ─────────────────────────────
def test_data_time_roll_keeps_trailing_volume():
    """出来高時間が次バーに入った tick で旧足を確定。直前バー終盤の出来高を取りこぼさない。
    （壁時計で窓が先に進み late tick を捨てて出来高過少／0 になっていたのを修正）。"""
    mgr, captured, _ = _new_mgr(_dt(h=9, mi=5))            # 窓 [09:00,09:15)
    mgr.update_ohlc(39000.0, 5.0, _dt(h=9, mi=10))
    mgr.update_ohlc(39010.0, 7.0, _dt(h=9, mi=14, s=59))  # バー終盤の出来高（従来は取りこぼし対象）
    # 次バーの出来高時間の tick → 旧足[09:00,09:15)を確定し、新足[09:15,09:30)を開始
    mgr.update_ohlc(39020.0, 3.0, _dt(h=9, mi=15, s=1))

    assert len(captured) == 1, captured
    bar1 = captured[0]
    assert bar1["datetime"] == _dt(h=9, mi=0)
    assert bar1["close"] == 39010.0
    assert bar1["volume"] == 12.0                          # 5+7 を取りこぼさない（←修正点）
    # 新足が始まり、次バーの tick がそこに入る
    assert mgr.bar_start_time == _dt(h=9, mi=15)
    assert mgr.current_candle is not None
    assert mgr.current_candle["datetime"] == _dt(h=9, mi=15)
    assert mgr.current_candle["volume"] == 3.0


# ───────────── T8 ★価格時刻／売買高時刻 分離（2026-06-24・kabu 一致） ─────────────
def test_price_volume_decouple_at_boundary():
    """価格(OHLC)は価格時刻バー・出来高は売買高時刻バーへ分離（正時境界の始値/終値ズレ対策）。"""
    mgr, captured, _ = _new_mgr(_dt(h=9, mi=5))                       # 窓 [09:00,09:15)
    mgr.update_ohlc(39000.0, 5.0, _dt(h=9, mi=10), volume_time=_dt(h=9, mi=10))
    # 跨ぎ tick: 価格時刻 09:15:01（→09:15バー）・売買高時刻 09:14:59（→09:00バー）
    mgr.update_ohlc(39020.0, 7.0, _dt(h=9, mi=15, s=1), volume_time=_dt(h=9, mi=14, s=59))
    assert len(captured) == 1, captured
    bar1 = captured[0]
    assert bar1["datetime"] == _dt(h=9, mi=0)
    assert bar1["close"] == 39000.0           # ★始値/終値は価格時刻＝跨ぎ tick の価格は 09:00 に入らない
    assert bar1["volume"] == 12.0             # ★出来高は売買高時刻で 09:00 バーへ（5+7）
    # 新足 09:15: 跨ぎ tick の価格が始値・出来高は二重計上しない
    assert mgr.current_candle["datetime"] == _dt(h=9, mi=15)
    assert mgr.current_candle["open"] == 39020.0
    assert mgr.current_candle["volume"] == 0.0


# ───────────── T9 後方互換（volume_time 無し＝旧ブリッジ＝従来動作） ─────────────
def test_backward_compat_no_volume_time():
    """volume_time を渡さない場合は従来どおり：出来高も価格時刻バーへ入る。"""
    mgr, captured, _ = _new_mgr(_dt(h=9, mi=5))
    mgr.update_ohlc(39000.0, 5.0, _dt(h=9, mi=10))                    # volume_time 無し
    mgr.update_ohlc(39020.0, 7.0, _dt(h=9, mi=15, s=1))              # 価格時刻で 09:15 へ→出来高も 09:15
    assert len(captured) == 1
    assert captured[0]["volume"] == 5.0                              # 09:00 バーは 5 のみ（従来動作）
    assert mgr.current_candle["volume"] == 7.0                       # 跨ぎ tick の出来高は 09:15 バーへ（従来）


class ClosedSession:
    def is_market_open(self):
        return False


# ───────────── T10 ★回帰: セッション末は market closed 扱いでも板寄せを出す（フォールバック） ─────────────
def test_timer_fires_closing_auction_when_market_closed():
    """15:45/6:00 足欠落バグの回帰固定。板寄せ tick が来ない静かな引けでも、壁時計フォールバック
    (_timer_check) が AUCTION_WAIT_SEC 経過後にセッション末足を確定し板寄せ特別足まで出す＋窓前進。"""
    mgr, captured, _ = _new_mgr(_dt(h=15, mi=44))            # OpenSession で日中足を作る
    mgr.update_ohlc(39000.0, 1.0, _dt(h=15, mi=40))
    mgr.update_ohlc(39010.0, 1.0, _dt(h=15, mi=44, s=30))   # latest_price=39010（引け直前値）
    mgr.market_session = ClosedSession()                    # 引け→市場クローズ扱いへ遷移
    # 板寄せ猶予内（15:45:05）はまだ待つ＝確定しない
    mgr._timer_check(_dt(h=15, mi=45, s=5))
    assert captured == []
    # 猶予超過（15:45 + AUCTION_WAIT_SEC 超）でフォールバック確定
    FakeDT._frozen = _dt(h=15, mi=45, s=20)
    mgr._timer_check(_dt(h=15, mi=45, s=20))
    # ① 15:30 通常足 → ② 15:45 板寄せ特別足（クローズ中でも出る・latest_price フォールバック）
    assert len(captured) == 2, captured
    conf, special = captured
    assert conf["datetime"] == _dt(h=15, mi=30) and conf["close"] == 39010.0
    assert special["datetime"] == _dt(h=15, mi=45)
    assert special["close"] == 39010.0 and special["volume"] == 0
    # 窓は夜間開始へ前進（15:45-17:00 の隙間 → 17:00）
    assert (mgr.bar_start_time, mgr.bar_end_time) == (_dt(h=17, mi=0), _dt(h=17, mi=15))


# ───────────── T13 ★最重要: 実際の引け板寄せ約定値で特別足を立てる ─────────────
def test_real_closing_auction_tick_used():
    """引け後に届く実際の引け板寄せ tick を捕捉し、その約定値で板寄せ特別足を立てる
    （市場クローズ扱いでも1本だけ受け入れ）。通常足の close は引け直前値のまま＝別の1本。"""
    mgr, captured, ticks = _new_mgr(_dt(h=15, mi=44))       # OpenSession で日中足
    mgr.update_ohlc(39000.0, 1.0, _dt(h=15, mi=40))
    mgr.update_ohlc(39010.0, 1.0, _dt(h=15, mi=44, s=30))   # 引け直前の最終連続値=39010
    mgr.market_session = ClosedSession()                    # 引け→クローズ
    # ★実際の引け板寄せ約定値（連続値と飛ぶ）＋引け出来高が 15:45:02 に届く
    mgr.update_ohlc(39555.0, 2354.0, _dt(h=15, mi=45, s=2))
    # ① 15:30 通常足（close=引け直前 39010）→ ② 15:45 板寄せ特別足（=実引け値 39555・出来高2354）
    assert len(captured) == 2, captured
    conf, special = captured
    assert conf["datetime"] == _dt(h=15, mi=30) and conf["close"] == 39010.0
    assert special["datetime"] == _dt(h=15, mi=45)
    assert special["open"] == special["high"] == special["low"] == special["close"] == 39555.0
    assert special["volume"] == 2354.0                      # ★板寄せ出来高を載せる（V=0 固定にしない）
    assert ticks[-1] == (39555.0, _dt(h=15, mi=45, s=2))    # on_tick も発火
    # 窓は夜間開始へ前進＝以降のクローズ中 tick は弾く
    assert (mgr.bar_start_time, mgr.bar_end_time) == (_dt(h=17, mi=0), _dt(h=17, mi=15))
    # 引け後の別 tick（板寄せ後の場外）は無視（特別足は増えない）
    mgr.update_ohlc(39560.0, 0.0, _dt(h=15, mi=50))
    assert len(captured) == 2


# ───────────── T14 ★実引け値 tick が来たら壁時計フォールバックは二重に出さない ─────────────
def test_real_auction_then_timer_no_double():
    mgr, captured, _ = _new_mgr(_dt(h=15, mi=44))
    mgr.update_ohlc(39010.0, 1.0, _dt(h=15, mi=44, s=30))
    mgr.market_session = ClosedSession()
    mgr.update_ohlc(39555.0, 0.0, _dt(h=15, mi=45, s=2))    # 実引け値で特別足＋窓前進
    n = len(captured)
    # その後タイマーが回っても、窓は17:15・板寄せは発火済＝二重発火しない
    FakeDT._frozen = _dt(h=15, mi=45, s=30)
    mgr._timer_check(_dt(h=15, mi=45, s=30))
    assert len(captured) == n


# ───────────── T11 ★通常足は market closed 中にフォールバック確定しない（ゲート過拡張防止） ─────────────
def test_timer_skips_normal_bar_when_market_closed():
    mgr, captured, _ = _new_mgr(_dt(h=9, mi=5))
    mgr.update_ohlc(39000.0, 1.0, _dt(h=9, mi=6))
    mgr.market_session = ClosedSession()
    FakeDT._frozen = _dt(h=9, mi=15, s=5)
    mgr._timer_check(_dt(h=9, mi=15, s=5))
    assert captured == []                                   # セッション末でない通常足は確定しない
    assert (mgr.bar_start_time, mgr.bar_end_time) == (_dt(h=9, mi=0), _dt(h=9, mi=15))  # 窓も前進しない


# ───────────── T12 ★板寄せの二重発火防止（同一引けは一度だけ） ─────────────
def test_closing_auction_not_emitted_twice():
    mgr, captured, _ = _new_mgr(_dt(h=15, mi=44))
    mgr.update_ohlc(39010.0, 1.0, _dt(h=15, mi=44, s=30))
    FakeDT._frozen = _dt(h=15, mi=45, s=5)
    mgr.finalize_candle()                                   # 1回目: 15:30 足 + 15:45 板寄せ
    n_after_first = len(captured)
    mgr._emit_closing_auction(mgr.bar_end_time, mgr.latest_price)  # 同一 ts を再要求
    assert len(captured) == n_after_first                   # 増えない（_last_auction_dt で抑止）


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    ok = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            ok += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{ok}/{len(tests)} passed")
    return ok == len(tests)


if __name__ == "__main__":
    print("J-1 ろうそく足生成テスト（★セッション末足含む）")
    sys.exit(0 if _run_all() else 1)
