"""
ohlc_processor.py  (n225tradingAI2 の OHLCManager を流用・検査して移植)
tick → 15分足 (セッション対応: タイマー確定 / ダミー足 / 板寄せ特別足)。
適合点: import を自己完結に、on_bar_close コールバック追加 (クローン連携)。
検査修正:
  ① get_bar_times: 原版は session_night_end(翌日6:00) と比較し elif/内 if が常に True・else が
     デッドコード・session_start/end が夜間で誤値 (出力には偶然影響せず)。→ 当日境界で正しく書き直し。
  ② 板寄せ: latest_price が無いと executed_time が True のまま固着し翌日発火しない → 必ず False に戻す。

★N225LocalEngine v2.0（2026-06-16）での唯一の追加 = on_tick seam（詳細仕様 §C.2・内部仕様 §3.3）:
  リアルタイム・ブローカー（指値イントラバー判定）へ「形成中足の現在 tick」を渡す口を1つ足すのみ。
  ろうそく足生成ロジック（確定足/ダミー足/★板寄せ特別足/境界クランプ）は一字一句 無傷（D13）。
"""
import threading
import time
from datetime import datetime, timedelta

from .ohlc_storage import OHLCStorage
from .market_session_manager import MarketSessionManager
from .logger import log_message, persist

INTERVAL = 15

# ★セッション境界は決め打ちしない（[[feedback_no_hardcoding]]）。市場時間の【唯一の正本】＝
#   _market_hours（is_market_open と同一定義・元 config.py）からのみ取得し、本モジュールでは
#   セッション時刻リテラルを一切持たない。フォールバックで値を再宣言すると、制度変更
#   （例: 夜間 16:30→17:00・日中引け 15:15→15:45）の際に正本と静かにズレる（損益直結）。
#   正本が読めない場合は確定足・板寄せ判定の根拠が無いため、握りつぶさず ImportError を伝播させる。
from . import _market_hours as _mh
SESS_DAY_START, SESS_DAY_END = _mh.DAY_START, _mh.DAY_END
SESS_NIGHT_START, SESS_NIGHT_END = _mh.NIGHT_START, _mh.NIGHT_END

# ★出来高過少バグ対策（2026-06-23）: バー確定を「壁時計」でなく「出来高時間(データ時刻)」基準にする。
#   静かな窓・引けで次バーの tick が来ない時のフォールバック確定までの猶予秒。
#   この猶予内に届いた「直前バー終盤の late tick」を取りこぼさずに締める。
FINALIZE_GRACE_SEC = 3

# ★板寄せ猶予秒（2026-06-26）: セッション末（引け15:45 / 夜間引け6:00）の後、kabu が送る
#   「実際の引け板寄せ約定値」tick の到着を待つ秒数。原典の「約10秒待ち」設計に相当。
#   猶予内に板寄せ tick が届けば update_ohlc 経路が実引け値で特別足を立てる。
#   猶予を過ぎても届かなければ、壁時計フォールバックが latest_price（引け直前値）で特別足を立てる。
AUCTION_WAIT_SEC = 12


class OHLCManager:
    _instance = None

    def __new__(cls, *a, **k):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, interval_minutes=INTERVAL, on_bar_close=None, on_tick=None):
        if self._initialized:
            if on_bar_close is not None:
                self.on_bar_close = on_bar_close
            if on_tick is not None:                # ★追加: 既存 singleton にも seam を差せる
                self.on_tick = on_tick
            return
        self.interval_minutes = interval_minutes
        self.on_bar_close = on_bar_close          # callable(candle dict)
        self.on_tick = on_tick                    # ★追加: callable(price, tick_time)（形成中足の各 tick）
        self.ohlc_storage = OHLCStorage()
        self.market_session = MarketSessionManager()
        self.current_candle = None
        self.latest_price = None
        self.last_tick_time = None
        self.executed_time = False
        self._last_auction_dt = None              # ★板寄せ特別足の二重発火防止（壁時計/データ時刻ロール競合）
        self.bar_start_time, self.bar_end_time = self.get_bar_times(datetime.now())
        self.lock = threading.Lock()
        self._initialized = True

    def start_ohlc_timer(self):
        threading.Thread(target=self.bar_timer_loop, daemon=True).start()
        log_message(f"OHLCManager タイマー起動 bar=[{self.bar_start_time:%H:%M}-{self.bar_end_time:%H:%M}]")

    # ── 検査修正版 get_bar_times (当日セッション境界で正しく判定) ──
    #   ★境界時刻は決め打ちせず市場時間の単一ソース(SESS_*)から取る（[[feedback_no_hardcoding]]）。
    def get_bar_times(self, base_time):
        d0 = base_time.replace(hour=0, minute=0, second=0, microsecond=0)
        t = base_time.time()
        day_start = d0.replace(hour=SESS_DAY_START.hour, minute=SESS_DAY_START.minute)
        day_end = d0.replace(hour=SESS_DAY_END.hour, minute=SESS_DAY_END.minute)
        night_start = d0.replace(hour=SESS_NIGHT_START.hour, minute=SESS_NIGHT_START.minute)
        step = timedelta(minutes=self.interval_minutes)

        if SESS_DAY_START <= t < SESS_DAY_END:                 # 日中
            s_start, s_end = day_start, day_end
        elif t >= SESS_NIGHT_START:                            # 当日夜間 (夜間開始-24:00)
            s_start = night_start
            s_end = (d0 + timedelta(days=1)).replace(
                hour=SESS_NIGHT_END.hour, minute=SESS_NIGHT_END.minute)
        elif t < SESS_NIGHT_END:                               # 早朝 = 前日夜間の続き
            s_start = (d0 - timedelta(days=1)).replace(
                hour=SESS_NIGHT_START.hour, minute=SESS_NIGHT_START.minute)
            s_end = d0.replace(hour=SESS_NIGHT_END.hour, minute=SESS_NIGHT_END.minute)
        elif SESS_DAY_END <= t < SESS_NIGHT_START:             # 日中後の隙間 → 夜間開始へ
            return night_start, night_start + step
        else:                                                  # 夜間明け-日中前の隙間 → 日中開始へ
            return day_start, day_start + step

        minute = (base_time.minute // self.interval_minutes) * self.interval_minutes
        start = base_time.replace(minute=minute, second=0, microsecond=0)
        if start < s_start:
            start = s_start
        end = start + step
        if end > s_end:
            end = s_end
        return start, end

    def bar_timer_loop(self):
        # ★フォールバック確定のみ（通常はデータ時刻ロール＝update_ohlc が確定する）。
        #   tick が来ない静かな窓・引けでは、出来高時間が進まずロールが起きないため、
        #   壁時計で「バー終端＋猶予」を過ぎたら確定する。窓前進は確定時にだけ行う
        #   （毎秒 get_bar_times(now) で上書きしない＝データ時刻ロールと衝突させない）。
        while True:
            time.sleep(1)
            with self.lock:
                self._timer_check(datetime.now())

    def _timer_check(self, now):
        """壁時計フォールバック1回分（テスト可能に分離・呼び出し側で lock 済み）。"""
        if self.bar_end_time is None:
            return
        if now < self.bar_end_time + timedelta(seconds=FINALIZE_GRACE_SEC):
            return
        # ★セッション末足（引け/夜間引け）は、その瞬間に市場クローズ扱いへ遷移しても必ず確定し
        #   板寄せ特別足まで出す（is_market_open ゲートで取りこぼしていた＝15:45/6:00 足欠落の主因）。
        #   ただし実際の引け板寄せ約定値 tick の到着を AUCTION_WAIT_SEC まで待つ：猶予内に届けば
        #   update_ohlc 経路が実引け値で特別足を立てる（このフォールバックは走らない）。猶予を過ぎても
        #   届かなければ（静かな引け）、ここが latest_price（引け直前値）で特別足を立てて確定する。
        if self._is_session_close(self.bar_end_time):
            already = (self._last_auction_dt == self.bar_end_time)
            if not already and now < self.bar_end_time + timedelta(seconds=AUCTION_WAIT_SEC):
                return                                    # 実引け値 tick を待つ（猶予内）
            self.finalize_candle()
            self.bar_start_time, self.bar_end_time = self.get_bar_times(datetime.now())
        elif self.market_session.is_market_open():
            self.finalize_candle()
            self.bar_start_time, self.bar_end_time = self.get_bar_times(datetime.now())

    def update_ohlc(self, price: float, volume: float, tick_time: datetime, volume_time=None,
                    op=None, op_t=None, hi=None, hi_t=None, lo=None, lo_t=None):
        now_open = self.market_session.is_market_open()
        # ★引け板寄せ tick（2026-06-26）: セッション末足の終端(15:45/6:00)を越えて最初に届く約定＝
        #   実際の引け板寄せ約定値。市場クローズ扱い(now_open=False)でも、この1本だけは受け入れて
        #   板寄せ特別足を「実引け値」で立てる（戦略が見る引け値を本物にする）。窓が次セッションへ
        #   進めば _is_session_close は偽になり、以降のクローズ中 tick は通常どおり弾かれる。
        #   ※ bar_end_time は別スレッド(_timer_check)が前進させ得るため、引け板寄せ判定は必ず lock 内で
        #     行う（lock 外で読むと、間に窓が進んで誤った ts に幽霊板寄せ足を立てる競合がある）。
        with self.lock:
            is_closing_auction = (not now_open
                                  and self.bar_end_time is not None
                                  and self._is_session_close(self.bar_end_time)
                                  and tick_time >= self.bar_end_time)
            if not now_open and not is_closing_auction:
                return
            self.latest_price = price
            self.last_tick_time = tick_time
            if is_closing_auction:
                # まず未確定の通常足（〜引け）を締め、実引け値で板寄せ特別足を立てて窓を次セッションへ。
                closing_ts = self.bar_end_time
                self._emit_current_or_dummy()                     # [.., 引け] 通常足（close=引け直前値）
                self._emit_closing_auction(closing_ts, price, volume)  # ★板寄せ特別足＝実際の引け値＋引け出来高
                self.bar_start_time, self.bar_end_time = self.get_bar_times(tick_time)
                if self.on_tick:
                    try:
                        self.on_tick(price, tick_time)
                    except Exception as e:
                        log_message(f"on_tick エラー: {e}")
                return
            # ★価格(OHLC)＝価格時刻(tick_time=CurrentPriceTime)、出来高＝売買高時刻(volume_time=TradingVolumeTime)
            #   で別々のバーへ割り当てる（2026-06-24 設計：正時境界の始値/終値が kabu とズレる根本対策）。
            #   volume_time が無い（旧ブリッジ）なら tick_time を流用＝従来動作（後方互換）。
            vt = volume_time if volume_time is not None else tick_time
            # ① 出来高を「売買高時刻」のバーへ：価格バーをロールする前に、vt が現バー窓内なら現バーへ
            #    先行加算する（価格時刻が次バーへロールしても、約定時刻側のバーに出来高が残る）。
            vol_added = False
            if volume and self.current_candle is not None and \
                    self.bar_start_time <= vt < self.bar_end_time:
                self.current_candle["volume"] += volume
                vol_added = True
            # ② 価格バーのロール（価格時刻基準・2026-06-23 のデータ時刻ロール＝D13 無傷）:
            #   この tick の価格時刻が現バー終端を越えていれば、壁時計を待たずに現在足を確定して
            #   窓を前進させる（旧足 close → 新足 open）。
            guard = 0
            while self.bar_end_time is not None and tick_time >= self.bar_end_time and guard < 250:
                self._emit_current_or_dummy()
                self.bar_start_time, self.bar_end_time = self.get_bar_times(self.bar_end_time)
                guard += 1
            # ── 真OHLC化(2026-06-29): kabu の始値/高値/安値を「その *_time が現バー窓内のときだけ」採用。──
            #   始値=寄付(セッション初足のみ命中)、高安=当日累積値が当バーで更新された実値。標本(close)が
            #   逃す「寄付」「push間の山谷」を補正。未提供(旧ブリッジ)は None＝従来の close 標本動作（後方互換）。
            bs, be = self.bar_start_time, self.bar_end_time
            bar_open = op if (op is not None and op_t is not None and bs <= op_t < be) else None
            hi_in = hi if (hi is not None and hi_t is not None and bs <= hi_t < be) else None
            lo_in = lo if (lo is not None and lo_t is not None and bs <= lo_t < be) else None
            eff_high = price if hi_in is None else max(price, hi_in)
            eff_low = price if lo_in is None else min(price, lo_in)

            # ★リアルタイム・ブローカーへの seam（確定足/ダミー足/板寄せ は無傷）。
            #   形成中足の各 tick ＋ 真の寄付/高安を渡す＝差し値約定が標本取りこぼしの touch も拾える。例外は隔離。
            if self.on_tick:
                try:
                    self.on_tick(price, tick_time, bar_open=bar_open, bar_high=hi_in, bar_low=lo_in)
                except Exception as e:
                    log_message(f"on_tick エラー: {e}")
            if not (self.bar_start_time <= tick_time < self.bar_end_time):
                return
            # ③ OHLC を価格時刻バーへ。出来高は①で売買高時刻バーへ計上済みなら二重計上しない。
            if self.current_candle is None:
                o0 = bar_open if bar_open is not None else price            # 始足=寄付・他足=初回現値
                self.current_candle = {"datetime": self.bar_start_time, "open": o0,
                                       "high": max(o0, eff_high), "low": min(o0, eff_low),
                                       "close": price,
                                       "volume": (0 if vol_added else volume)}
            else:
                c = self.current_candle
                c["high"] = max(c["high"], eff_high)
                c["low"] = min(c["low"], eff_low)
                c["close"] = price
                if not vol_added:
                    c["volume"] += volume

    def _emit_current_or_dummy(self):
        """現在の形成中足を確定（あれば実足・無ければ静かな窓のダミー足）して発火する。
        板寄せ特別足は含まない（壁時計 15:45/6:00 専用なので finalize_candle 側に置く）。
        データ時刻ロール（update_ohlc）と壁時計フォールバック（finalize_candle）の共通処理。"""
        if self.current_candle is not None:
            bar = self.current_candle
            self.ohlc_storage.add_to_candle(bar)
            self.ohlc_storage.mark_bar_completed()
            self.current_candle = None
            persist(f"確定足: {bar['datetime']:%m/%d %H:%M} C{bar['close']:.0f}")   # ★ファイルのみ（表示しない・記録は残す）
            self._fire(bar)
        else:
            if not self.market_session.is_market_open():
                return
            last = self.ohlc_storage.get_last_bar()
            if last is not None:                              # ダミー足 (tick 無い静かな窓)
                dummy = {"datetime": self.bar_start_time, "open": float(last["close"]),
                         "high": float(last["close"]), "low": float(last["close"]),
                         "close": float(last["close"]), "volume": 0}
                self.ohlc_storage.add_to_candle(dummy)
                self.ohlc_storage.mark_bar_completed()
                persist(f"ダミー足: {dummy['datetime']:%m/%d %H:%M} C{dummy['close']:.0f}")   # ★ファイルのみ
                self._fire(dummy)

    def _is_session_close(self, bar_end):
        """この足の終端がセッション末（日中引け / 夜間引け）か。
        境界時刻は決め打ちせず市場時間の単一ソース(SESS_*)に従う（[[feedback_no_hardcoding]]）。"""
        if bar_end is None:
            return False
        return bar_end.time() in (SESS_DAY_END, SESS_NIGHT_END)

    def _emit_closing_auction(self, ts, price, volume=0):
        """セッション末の板寄せ特別足を ts(=bar_end) で発火。price＝引け値（latest_price）。
        ★volume＝引け板寄せの出来高（引け板寄せ tick の volume）。TradeStation/TV と同じく板寄せ足にも
        実出来高があるので 0 固定にしない（2026-06-26 修正）。引け tick が来ない静かな引けのみ 0。
        同一引けの二重発火は防ぐ（壁時計経路とデータ時刻ロール経路の競合対策）。"""
        if not price or ts is None:
            return
        if self._last_auction_dt == ts:                       # 同一引けは一度だけ
            return
        sp = {"datetime": ts, "open": price, "high": price,
              "low": price, "close": price, "volume": float(volume or 0)}
        self.ohlc_storage.add_to_candle(sp)
        self.ohlc_storage.mark_bar_completed()
        self._last_auction_dt = ts
        persist(f"板寄せ特別足: {sp['datetime']:%m/%d %H:%M} C{sp['close']:.0f}")   # ★ファイルのみ（表示はcontroller側のセッション境界OHLCV）
        self._fire(sp)

    def finalize_candle(self):
        """壁時計フォールバック確定（lock 内・非ブロッキング）。
        セッション末は通常 update_ohlc の引け板寄せ tick 経路が実引け値で特別足を立てる。
        引け板寄せ tick が AUCTION_WAIT_SEC 内に届かなかった静かな引けのみ、ここが
        latest_price（引け直前値）で特別足を立てるフォールバック（_last_auction_dt で二重発火防止）。"""
        self._emit_current_or_dummy()
        if not self.executed_time and self._is_session_close(self.bar_end_time):
            self.executed_time = True
            try:
                self._emit_closing_auction(self.bar_end_time, self.latest_price)
            finally:
                self.executed_time = False                    # 検査修正②: 必ず戻す(固着防止)

    def _fire(self, candle):
        if self.on_bar_close:
            try:
                self.on_bar_close(candle)
            except Exception as e:
                log_message(f"on_bar_close エラー: {e}")

    def get_latest_price(self):
        return self.latest_price
