"""
trader.py
Tu dong dat lenh vao MT5 khi phat hien pattern.

CHANGELOG v3 - Dynamic params:
  - _calc_sl_tp: doc atr_period va atr_multiplier tu param_loader (dong)
    thay vi hardcode trong config.py
  - _calc_lot / place_trade: hien thi rui ro theo dung dong tien tai khoan
    (VND -> format so nguyen co dau phan cach, USD -> 2 chu so thap phan)
  - Giu nguyen toan bo logic SMC, filling mode, SL cap, body strength filter
"""

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

import config
import param_loader

logger = logging.getLogger("trader")

# v5 (bot_xutho4 — SMC): magic number RIENG, khac voi bot cu (mt5-watcher
# tren VPS dung 20260622), de 2 bot khong nhan nham lenh cua nhau khi
# (tam thoi) con dung chung 1 tai khoan MT5.
MAGIC_NUMBER = 20260702

# v7: 4 nhom tin hieu doc lap (OR logic) — xem analysis.py
BULLISH_PATTERNS = {
    "smc_bullish_bos", "smc_bullish_choch",
    "st_flip_bullish", "ema_cross_bullish", "price_action_bullish",
}
BEARISH_PATTERNS = {
    "smc_bearish_bos", "smc_bearish_choch",
    "st_flip_bearish", "ema_cross_bearish", "price_action_bearish",
}


# ─── Helpers format rủi ro ────────────────────────────────────────────────────

def _format_risk(amount: float, currency: str) -> str:
    """
    Format so tien rui ro theo dong tien tai khoan.
    VND: so nguyen, co dau phan cach (vi du: 250,000 VND)
    USD va khac: 2 chu so thap phan (vi du: 3.50 USD)
    """
    if currency.upper() == "VND":
        return f"{int(round(amount)):,} VND"
    return f"{amount:.2f} {currency}"


def _get_account_currency() -> str:
    """Lay dong tien tai khoan tu MT5, fallback USD neu khong ket noi."""
    if mt5 is None:
        return "USD"
    try:
        acct = mt5.account_info()
        return acct.currency if acct else "USD"
    except Exception:
        return "USD"


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class TradeResult:
    success:    bool
    ticket:     int   = 0
    symbol:     str   = ""
    direction:  str   = ""
    lot:        float = 0.0
    entry:      float = 0.0
    sl:         float = 0.0
    tp:         float = 0.0
    rr:         float = 0.0
    risk_usd:   float = 0.0
    error:      str   = ""
    reversed_ticket: int   = 0    # ticket lenh CU vua bi dong (dao chieu), 0 neu khong co
    reversed_pnl:    float = 0.0  # P&L cua lenh cu tai thoi diem dong

    def summary(self) -> str:
        currency = _get_account_currency()
        risk_str = _format_risk(self.risk_usd, currency)
        if not self.success:
            return f"Dat lenh that bai: {self.error}"
        reverse_note = ""
        if self.reversed_ticket:
            reverse_note = (f"  (da dong lenh nguoc #{self.reversed_ticket}, "
                             f"P&L={self.reversed_pnl:+.2f})\n")
        return (
            f"#{self.ticket} {self.symbol} {self.direction} {self.lot} lots\n"
            f"{reverse_note}"
            f"  Entry: {self.entry}  SL: {self.sl}  TP: {self.tp}\n"
            f"  R:R = 1:{self.rr}  |  Rui ro: ~{risk_str}"
        )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_direction(pattern: str) -> Optional[str]:
    if pattern in BULLISH_PATTERNS: return "BUY"
    if pattern in BEARISH_PATTERNS: return "SELL"
    return None


def _calc_atr(candles: list, period: int = 14) -> float:
    if len(candles) < period + 1:
        ranges = [c["high"] - c["low"] for c in candles]
        return sum(ranges) / len(ranges) if ranges else 0.0
    true_ranges = []
    for i in range(1, len(candles)):
        h = candles[i]["high"]; l = candles[i]["low"]
        pc = candles[i - 1]["close"]
        true_ranges.append(max(h - l, abs(h - pc), abs(l - pc)))
    recent = true_ranges[-period:]
    return sum(recent) / len(recent)


def _check_body_strength(candles: list, direction: str) -> bool:
    """Loc nen xac nhan than qua yeu (doji / pin bar gia)."""
    if not candles:
        return True
    min_strength = getattr(config, "BODY_STRENGTH_MIN", 0.35)
    last = candles[-1]
    candle_range = last["high"] - last["low"]
    if candle_range <= 0:
        return False
    body = abs(last["close"] - last["open"])
    if body / candle_range < min_strength:
        logger.info("Nen xac nhan than yeu (%.1f%%) — bo qua.", body / candle_range * 100)
        return False
    return True


def _calc_sl_tp(
    direction: str,
    entry: float,
    zone_price: float,
    candles_context: list,
    symbol: str = "",
) -> Tuple[float, float]:
    """
    Tinh SL va TP dua tren ATR dong — v8: TP tinh DOC LAP voi SL (khong con
    la boi so cung cua SL qua rr_ratio). Truoc day dung
    `tp = entry + (entry-sl) * config.DEFAULT_RR_RATIO` — vua HARDCODE
    hang so global (khong doc tu param_loader nen ROI theo tung symbol da
    toi uu KHONG BAO GIO duoc ap dung khi giao dich live, dan toi lech so
    voi ket qua backtest), vua ep TP luon ty le CUNG voi SL (VD: XAUUSD
    ATR rong → SL rong → TP theo do cung rong theo, gay lai/lo bien dong
    manh; EURUSD ATR hep → SL hep → TP theo do cung hep, entry/TP qua gan
    nhau). Nay TP dung `tp_atr_multiplier` RIENG, tu dong theo tung symbol,
    doc dong qua param_loader (giong het atr_multiplier cua SL).

    atr_period, atr_multiplier, tp_atr_multiplier deu doc tu param_loader
    (tu optimized_params.json neu co, nguoc lai fallback ve config.py).

    Cap MAX_SL_USD per symbol de SL khong bi phinh ra qua xa.
    """
    last_candle = candles_context[-1] if candles_context else {}

    # ── Doc tham so DONG tu param_loader ─────────────────────────────────────
    atr_period     = int(param_loader.get_param(symbol, "atr_period",
                         getattr(config, "ATR_PERIOD_DEFAULT", 14)))
    atr_multiplier = float(param_loader.get_param(symbol, "atr_multiplier",
                           getattr(config, "ATR_MULTIPLIER_DEFAULT", 1.8)))
    tp_atr_multiplier = float(param_loader.get_param(symbol, "tp_atr_multiplier", 3.6))

    atr     = _calc_atr(candles_context, period=atr_period)
    atr_buf = atr * atr_multiplier
    tp_buf  = atr * tp_atr_multiplier

    # Buffer co dinh toi thieu (fallback) — CA CHO SL VA TP (v9: truoc day
    # chi SL co san toi thieu, TP thuan ATR nen co qua nho luc thi truong
    # it bien dong — them san rieng cho TP de tranh TP < 10 pip bat thuong).
    buf_cfg = getattr(config, "SL_BUFFER_PERCENT", {})
    buf_pct = (buf_cfg.get(symbol, getattr(config, "SL_BUFFER_PERCENT_DEFAULT", 0.06))
               if isinstance(buf_cfg, dict) else float(buf_cfg))
    fixed_buf = zone_price * buf_pct / 100

    tp_buf_cfg = getattr(config, "TP_BUFFER_PERCENT", {})
    tp_buf_pct = (tp_buf_cfg.get(symbol, getattr(config, "TP_BUFFER_PERCENT_DEFAULT", 0.06))
                  if isinstance(tp_buf_cfg, dict) else float(tp_buf_cfg))
    fixed_tp_buf = entry * tp_buf_pct / 100

    buf = max(atr_buf, fixed_buf)
    tp_buf = max(tp_buf, fixed_tp_buf)

    # Cap MAX_SL_USD
    max_sl_cfg = getattr(config, "MAX_SL_USD", {})
    max_sl_default = getattr(config, "MAX_SL_USD_DEFAULT", None)
    max_sl = (max_sl_cfg.get(symbol, max_sl_default)
              if isinstance(max_sl_cfg, dict) else max_sl_cfg or max_sl_default)
    if max_sl and buf > max_sl:
        logger.info("ATR buf=%.4f vuot MAX_SL=%.1f → thu hep ve cap.", buf, max_sl)
        buf = max_sl

    # Gioi han khoang cach SL-tinh-tu-ENTRY: zone_price/anchor (dinh/day gan
    # nhat) co the nam XA entry hon nhieu so voi buf ATR thuan tuy (vi du gia
    # da chay 1 doan tu luc phat hien tin hieu den luc khop lenh) — neu
    # khong gioi han, SL se bi "keo gian" theo zone trong khi TP (tu v8) chi
    # tinh thuan tuy tu ATR quanh entry, gay lech RR nghiem trong (SL rat xa,
    # TP van gan — dung hien tuong da gap: EURUSD/GBPUSD RR≈0.5 thay vi
    # dung nhu tuong tu tp_atr_multiplier/atr_multiplier toi uu).
    max_sl_atr_mult = float(param_loader.get_param(symbol, "max_sl_atr_mult", 1.5))
    max_sl_from_entry = buf * max_sl_atr_mult

    logger.debug(
        "ATR(%d)=%.5f | SL: x%.2f=%.5f fixed=%.5f cap=%s dung=%.5f | TP: x%.2f=%.5f "
        "| max_sl_from_entry(x%.1f)=%.5f",
        atr_period, atr, atr_multiplier, atr_buf, fixed_buf,
        str(max_sl) if max_sl else "none", buf,
        tp_atr_multiplier, tp_buf, max_sl_atr_mult, max_sl_from_entry,
    )

    # v9.7: TP giờ tính TỪ khoảng cách SL THỰC TẾ (sau khi đã áp zone-anchor
    # + moi gioi han/cap) nhan voi ty le da toi uu (tp_atr_multiplier/
    # atr_multiplier) — thay vi tinh HOAN TOAN doc lap tu ATR nhu ban truoc.
    # Ly do: neu SL bi cap boi max_sl_atr_mult (zone qua xa), TP van giu
    # nguyen theo ATR thuan se tao ra RR CO DINH = 1/max_sl_atr_mult moi
    # khi cap kich hoat (da gap: XAUUSD ra dung 1:0.667 = 1/1.5 nhieu lan
    # lien tiep, khong phai ngau nhien) — hoan toan bo qua ty le auto_tuner
    # da toi uu. Cach moi dam bao RR LUON KHOP voi tp_atr_multiplier/
    # atr_multiplier ma auto_tuner chon, bat ke SL cuoi cung la bao nhieu.
    tp_sl_ratio = tp_atr_multiplier / atr_multiplier if atr_multiplier > 0 else 1.0

    if direction == "BUY":
        anchor = last_candle.get("low", zone_price)
        zone_sl = min(zone_price, anchor) - buf
        sl_dist = entry - zone_sl
        if sl_dist > max_sl_from_entry:
            sl_dist = max_sl_from_entry  # zone qua xa → cap lai
        sl = entry - sl_dist
        tp_dist = max(sl_dist * tp_sl_ratio, tp_buf)  # van giu san TP toi thieu (tp_buf)
        tp = entry + tp_dist
    else:
        anchor = last_candle.get("high", zone_price)
        zone_sl = max(zone_price, anchor) + buf
        sl_dist = zone_sl - entry
        if sl_dist > max_sl_from_entry:
            sl_dist = max_sl_from_entry
        sl = entry + sl_dist
        tp_dist = max(sl_dist * tp_sl_ratio, tp_buf)
        tp = entry - tp_dist

    return sl, tp


def _calc_lot(symbol: str, sl_distance: float) -> Tuple[float, float]:
    """
    Tinh lot theo risk % tai khoan. Tra ve (lot, risk_amount).
    risk_amount la so tien rui ro theo dong tien tai khoan (VND hoac USD).
    """
    sym_info = mt5.symbol_info(symbol)
    account  = mt5.account_info()

    if not sym_info or not account:
        return getattr(config, "FIXED_LOT", {}).get(symbol, 0.01), 0.0

    balance    = account.balance
    currency   = account.currency
    risk_funds = balance * config.RISK_PER_TRADE_PCT / 100

    point      = sym_info.point
    tick_size  = sym_info.trade_tick_size
    tick_value = sym_info.trade_tick_value

    if point <= 0 or tick_size <= 0 or tick_value <= 0:
        logger.warning("Symbol info khong hop le cho %s.", symbol)
        return sym_info.volume_min, risk_funds

    sl_ticks      = sl_distance / tick_size
    value_per_lot = sl_ticks * tick_value  # rui ro neu SL bi hit, 1 lot

    if value_per_lot <= 0:
        return sym_info.volume_min, risk_funds

    raw_lot = risk_funds / value_per_lot
    step    = sym_info.volume_step
    lot     = round(round(raw_lot / step) * step, 8)
    lot     = max(sym_info.volume_min, min(lot, sym_info.volume_max, config.MAX_LOT_SIZE))
    lot     = round(lot, 2)

    actual_risk = lot * value_per_lot
    return lot, actual_risk


def _get_filling_type(sym_info) -> int:
    fm = sym_info.filling_mode
    logger.debug("Filling mode bitmask %s: %d", sym_info.name, fm)
    if fm & 2: return mt5.ORDER_FILLING_IOC
    if fm & 1: return mt5.ORDER_FILLING_FOK
    return mt5.ORDER_FILLING_RETURN


def _check_min_sl(entry: float, sl: float, direction: str, sym_info) -> bool:
    point     = sym_info.point
    sl_points = abs(entry - sl) / point
    min_pts_cfg = getattr(config, "MIN_SL_POINTS", {})
    default     = getattr(config, "MIN_SL_POINTS_DEFAULT", 30)
    min_pts     = (min_pts_cfg.get(sym_info.name, default)
                   if isinstance(min_pts_cfg, dict) else int(min_pts_cfg))
    if sl_points < min_pts:
        logger.warning("SL qua gan entry: %.1f pts < min %d (%s).", sl_points, min_pts, sym_info.name)
        return False
    return True


def _close_position(position) -> bool:
    """
    Dong 1 vi the dang mo bang lenh nguoc chieu, cung volume, gia thi truong.
    Dung khi phat hien tin hieu MOI nguoc chieu VA lenh cu dang LO (xem
    place_trade() — tinh nang "dao lenh khi lo + tin hieu nguoc").
    """
    tick = mt5.symbol_info_tick(position.symbol)
    if not tick:
        logger.error("Khong lay duoc tick de dong vi the #%d.", position.ticket)
        return False

    sym_info = mt5.symbol_info(position.symbol)
    filling = _get_filling_type(sym_info) if sym_info else mt5.ORDER_FILLING_IOC

    is_buy = position.type == mt5.POSITION_TYPE_BUY
    close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
    price = tick.bid if is_buy else tick.ask

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       position.symbol,
        "volume":       position.volume,
        "type":         close_type,
        "position":     position.ticket,
        "price":        price,
        "deviation":    getattr(config, "ORDER_DEVIATION", 20),
        "magic":        MAGIC_NUMBER,
        "comment":      "AI_reverse_close",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": filling,
    }

    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error("Dong vi the #%d (dao chieu) that bai: %s",
                     position.ticket, result.comment if result else "order_send None")
        return False

    logger.info(
        "Da dong vi the #%d (%s %s, P&L=%.2f) de mo lenh nguoc chieu theo tin hieu moi.",
        position.ticket, position.symbol, "BUY" if is_buy else "SELL", position.profit,
    )
    return True


def _get_last_closed_deal(symbol: str, lookback_hours: int = 12) -> Optional[Tuple[str, float, int]]:
    """
    Lay deal DONG LENH gan nhat cua bot nay (cung MAGIC_NUMBER) cho symbol,
    qua mt5.history_deals_get(). Dung de kiem tra FOMO guard (xem
    _check_fomo_guard). Tra ve (direction_cua_lenh_goc, gia_dong, thoi_gian_dong)
    hoac None neu khong tim thay.
    """
    from datetime import datetime, timedelta

    date_from = datetime.now() - timedelta(hours=lookback_hours)
    date_to   = datetime.now() + timedelta(minutes=5)
    deals = mt5.history_deals_get(date_from, date_to)
    if not deals:
        return None

    closing_deals = [
        d for d in deals
        if d.symbol == symbol and d.magic == MAGIC_NUMBER
        and d.entry == mt5.DEAL_ENTRY_OUT
    ]
    if not closing_deals:
        return None

    last = max(closing_deals, key=lambda d: d.time)
    # d.type la loai lenh DUNG DE DONG (nguoc voi huong vi the goc):
    # dong bang SELL nghia la vi the goc la BUY, va nguoc lai.
    original_direction = "BUY" if last.type == mt5.ORDER_TYPE_SELL else "SELL"
    return original_direction, last.price, last.time


def _check_fomo_guard(symbol: str, direction: str, entry: float,
                       candles_context: list) -> Optional[str]:
    """
    Chan tin hieu "duoi gia" (FOMO): neu lenh GAN NHAT vua dong tren symbol
    nay CUNG CHIEU voi tin hieu moi, VA gia hien tai da chay qua xa (tinh
    theo ATR) so voi gia dong lenh do — nghia la dang vao lenh muon, entry
    khong con hop ly, de bi dieu chinh nguoc lai gay lo.

    Tra ve chuoi ly do neu bi chan, None neu OK de tiep tuc dat lenh.
    """
    if not getattr(config, "FOMO_GUARD_ENABLED", True):
        return None

    last_deal = _get_last_closed_deal(symbol)
    if last_deal is None:
        return None
    last_direction, last_close_price, _ = last_deal

    if last_direction != direction:
        return None  # lenh truoc khac chieu — khong phai FOMO, la dao chieu binh thuong

    atr_period = int(param_loader.get_param(symbol, "atr_period",
                     getattr(config, "ATR_PERIOD_DEFAULT", 14)))
    atr_now = _calc_atr(candles_context, period=atr_period)
    if atr_now <= 0:
        return None

    fomo_mult  = float(param_loader.get_param(symbol, "fomo_guard_atr_mult", 0.5))
    extension  = abs(entry - last_close_price)
    ext_in_atr = extension / atr_now

    if ext_in_atr > fomo_mult:
        return (f"FOMO guard: gia da chay {ext_in_atr:.2f}x ATR "
                f"(nguong {fomo_mult:.2f}x) tu lenh {direction} vua dong gan day "
                f"— bo qua de tranh vao lenh duoi gia.")
    return None


# ─── Main entry point ─────────────────────────────────────────────────────────

def place_trade(signal) -> TradeResult:
    """Dat lenh market dua tren Signal. Tra ve TradeResult."""

    if not getattr(config, "AUTO_TRADE_ENABLED", False):
        return TradeResult(success=False, error="AUTO_TRADE_ENABLED=False")
    if mt5 is None:
        return TradeResult(success=False, error="MetaTrader5 module khong kha dung")

    direction = _get_direction(signal.pattern)
    if direction is None:
        return TradeResult(success=False,
            error=f"Pattern '{signal.pattern}' khong co huong ro rang, bo qua.")

    reversed_ticket = 0
    reversed_pnl = 0.0

    symbol   = signal.symbol
    sym_info = mt5.symbol_info(symbol)
    if not sym_info:
        return TradeResult(success=False, error=f"Khong lay duoc symbol_info cho {symbol}")
    if not sym_info.visible:
        mt5.symbol_select(symbol, True)

    # Body strength filter
    if not _check_body_strength(signal.candles_context, direction):
        return TradeResult(success=False, symbol=symbol, direction=direction,
            error=f"Nen xac nhan than qua yeu — bo qua {signal.pattern}")

    # Kiem tra so lenh dang mo
    all_pos = mt5.positions_get() or []
    bot_pos = [p for p in all_pos if p.magic == MAGIC_NUMBER]
    sym_pos = [p for p in bot_pos if p.symbol == symbol]

    if len(sym_pos) >= config.MAX_OPEN_TRADES_PER_SYMBOL:
        # ── Dao lenh: neu tin hieu MOI nguoc chieu voi lenh dang mo VA lenh
        # dang mo dang LO (profit < 0) → dong lenh cu, cho phep mo lenh moi.
        # Tranh truong hop bot "ket cung" 1 lenh lo dai han chi vi da dat
        # toi da 1 lenh/symbol, trong khi thi truong da doi huong ro rang.
        allow_reverse = getattr(config, "ALLOW_REVERSE_ON_LOSS", True)
        closed_any = False
        if allow_reverse:
            for pos in sym_pos:
                pos_direction = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
                is_opposite = pos_direction != direction
                is_losing   = pos.profit < 0
                if is_opposite and is_losing:
                    reversed_ticket = pos.ticket
                    reversed_pnl = pos.profit
                    if _close_position(pos):
                        closed_any = True
                    else:
                        return TradeResult(success=False, symbol=symbol, direction=direction,
                            error=f"Tin hieu nguoc chieu nhung dong lenh cu #{pos.ticket} that bai")

        if closed_any:
            # Lay lai danh sach vi the SAU khi da dong, de cac check ben duoi
            # (MAX_TOTAL_OPEN_TRADES) dung so lieu moi nhat.
            all_pos = mt5.positions_get() or []
            bot_pos = [p for p in all_pos if p.magic == MAGIC_NUMBER]
            sym_pos = [p for p in bot_pos if p.symbol == symbol]
        else:
            return TradeResult(success=False,
                error=f"Da co {len(sym_pos)} lenh tren {symbol} (toi da {config.MAX_OPEN_TRADES_PER_SYMBOL})")

    if len(bot_pos) >= config.MAX_TOTAL_OPEN_TRADES:
        return TradeResult(success=False,
            error=f"Da dat toi da {config.MAX_TOTAL_OPEN_TRADES} lenh tong")

    # Kiem tra spread
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return TradeResult(success=False, error=f"Khong lay duoc tick cho {symbol}")
    spread_points  = sym_info.spread
    max_spread_cfg = getattr(config, "MAX_SPREAD_POINTS", {})
    max_spread     = (max_spread_cfg.get(symbol, getattr(config, "MAX_SPREAD_POINTS_DEFAULT", 40))
                      if isinstance(max_spread_cfg, dict) else int(max_spread_cfg))
    if spread_points > max_spread:
        return TradeResult(success=False,
            error=f"Spread {spread_points} pts > {max_spread} pts — thi truong dang rong")

    entry = tick.ask if direction == "BUY" else tick.bid

    # FOMO guard: chan neu dang "duoi theo" gia sau khi lenh cung chieu
    # vua dong gan day (xem _check_fomo_guard).
    fomo_reason = _check_fomo_guard(symbol, direction, entry, signal.candles_context)
    if fomo_reason:
        return TradeResult(success=False, symbol=symbol, direction=direction, error=fomo_reason)

    # Tinh SL/TP DONG
    sl, tp = _calc_sl_tp(direction, entry, signal.zone_price, signal.candles_context, symbol)
    digits = sym_info.digits
    sl = round(sl, digits)
    tp = round(tp, digits)

    if not _check_min_sl(entry, sl, direction, sym_info):
        return TradeResult(success=False,
            error=f"SL ({sl}) qua gan entry ({entry})")

    # Tinh lot va rui ro
    sl_distance   = abs(entry - sl)
    fixed_lot_cfg = getattr(config, "FIXED_LOT", {})
    currency      = _get_account_currency()

    if isinstance(fixed_lot_cfg, dict) and symbol in fixed_lot_cfg:
        lot      = fixed_lot_cfg[symbol]
        tick_val  = sym_info.trade_tick_value
        tick_size = sym_info.trade_tick_size or 1
        sl_ticks  = sl_distance / tick_size
        risk_raw  = lot * sl_ticks * tick_val
    else:
        lot, risk_raw = _calc_lot(symbol, sl_distance)

    risk_str = _format_risk(risk_raw, currency)

    # Gui lenh
    order_type  = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
    filling     = _get_filling_type(sym_info)
    rr_achieved = round(abs(tp - entry) / abs(entry - sl), 2) if sl != entry else 0

    # Log tham so dang dung
    atr_p = param_loader.get_param(symbol, "atr_period", 14)
    atr_m = param_loader.get_param(symbol, "atr_multiplier", 1.8)
    p_lkb = param_loader.get_param(symbol, "pivot_lookback", config.PIVOT_LOOKBACK)
    logger.info(
        "Dat lenh: %s %s | lot=%.2f | entry=%.5f | SL=%.5f | TP=%.5f "
        "| R:R=1:%.1f | rui ro~%s | ATR(%d)×%.2f | pivot=%d",
        direction, symbol, lot, entry, sl, tp,
        rr_achieved, risk_str, atr_p, atr_m, p_lkb,
    )

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       lot,
        "type":         order_type,
        "price":        entry,
        "sl":           sl,
        "tp":           tp,
        "deviation":    config.ORDER_DEVIATION,
        "magic":        MAGIC_NUMBER,
        "comment":      f"AI_{signal.pattern[:12]}",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": filling,
    }

    result = mt5.order_send(request)
    if result is None:
        return TradeResult(success=False, error="order_send tra ve None")

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        desc = {
            10004:"Requote", 10006:"Rejected", 10013:"Invalid request",
            10014:"Invalid volume", 10015:"Invalid price", 10016:"Invalid SL/TP",
            10018:"Market closed", 10019:"Not enough money",
            10025:"Too many requests", 10030:"Invalid fill",
        }.get(result.retcode, "Xem MQL5 TRADE_RETCODE")
        return TradeResult(success=False,
            error=f"retcode={result.retcode} ({desc}) | {result.comment}")

    trade_result = TradeResult(
        success=True, ticket=result.order, symbol=symbol, direction=direction,
        lot=lot, entry=result.price, sl=sl, tp=tp,
        rr=rr_achieved, risk_usd=risk_raw,
        reversed_ticket=reversed_ticket, reversed_pnl=reversed_pnl,
    )
    logger.info(trade_result.summary())
    return trade_result