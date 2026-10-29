"""
trailing_stop.py
Quản lý trailing stop cho các lệnh đang mở của bot.

v9.8 — Đổi sang chế độ BREAKEVEN-LOCK (mặc định):
  1. Chờ activation: chỉ kích hoạt khi profit >= activation_atr × ATR
  2. Khi đủ điều kiện: dời SL thẳng về ENTRY (+ buffer nhỏ nếu cấu hình)
     MỘT LẦN DUY NHẤT, rồi DỪNG — không trail tiếp theo giá nữa.
     Kết quả cuối chỉ có thể là hoà vốn (nếu giá hồi chạm lại entry) hoặc
     chạm TP — tránh bị quét bởi 1 nhịp hồi nhỏ khi trail bám sát giá quá.

  Chế độ TRAIL LIÊN TỤC cũ vẫn giữ lại, bật qua "mode": "continuous" trong
  config.TRAILING_STOP[symbol] nếu muốn dùng lại (SL tiếp tục bám theo
  peak_price với khoảng cách trail_atr × ATR sau khi activate).

Gọi trong watcher.py mỗi vòng poll:
    import trailing_stop
    trailing_stop.update(mt5_client.get_candles)
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

import config

logger = logging.getLogger("trailing_stop")

# v9.5: LAY TRUC TIEP tu trader.py thay vi hardcode — truoc day hardcode
# 20260622 (magic cua bot CU pattern-nen tren VPS), trong khi trader.py
# cua bot nay (bot_xutho4) da doi thanh 20260702 tu nhieu ban cap nhat
# truoc. Vi lech nhau, bot_positions loc theo BOT_MAGIC luon RONG —
# trailing stop khong bao gio duoc ap dung cho bat ky lenh nao. Import
# truc tiep de tu dong dong bo, khong con the lech lan nua.
try:
    from trader import MAGIC_NUMBER as BOT_MAGIC
except ImportError:
    BOT_MAGIC = 20260702  # fallback neu khong import duoc trader.py

# State lưu trạng thái trailing của từng ticket
# { ticket: TrailState }
_trail_states: Dict[int, "TrailState"] = {}


@dataclass
class TrailState:
    ticket:       int
    symbol:       str
    direction:    str         # BUY | SELL
    entry:        float
    original_sl:  float
    current_sl:   float
    activated:    bool = False  # da doi ve breakeven (hoac dang trail) chua
    peak_price:   float = 0.0  # chi dung cho mode "continuous"


# ─── Config helpers ───────────────────────────────────────────────────────────

def _get_trail_cfg(symbol: str) -> dict:
    """Lấy config trailing stop cho symbol, fallback về default."""
    cfg = getattr(config, "TRAILING_STOP", {})
    default = {
        "enabled":             getattr(config, "TRAILING_STOP_ENABLED", True),
        "mode":                "breakeven",  # "breakeven" (moi, mac dinh) | "continuous" (cu)
        "activation_atr":      2.0,
        "trail_atr":           1.5,          # chi dung cho mode "continuous"
        "breakeven_buffer_atr": 0.0,          # cong them mot chut ATR qua entry (bu spread), 0 = dung entry
    }
    if isinstance(cfg, dict) and symbol in cfg:
        merged = {**default, **cfg[symbol]}
        return merged
    return default


def _calc_atr(candles: list, period: int = 14) -> float:
    """ATR từ list nến (same logic như trader.py)."""
    if len(candles) < period + 1:
        ranges = [c["high"] - c["low"] for c in candles]
        return sum(ranges) / len(ranges) if ranges else 0.0
    true_ranges = []
    for i in range(1, len(candles)):
        high       = candles[i]["high"]
        low        = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
    recent = true_ranges[-period:]
    return sum(recent) / len(recent)


# ─── Gửi lệnh modify SL lên MT5 ──────────────────────────────────────────────

def _modify_sl(position, new_sl: float) -> bool:
    """Gửi TRADE_ACTION_SLTP để cập nhật SL cho position."""
    sym_info = mt5.symbol_info(position.symbol)
    if not sym_info:
        return False

    digits = sym_info.digits
    new_sl = round(new_sl, digits)

    request = {
        "action":   mt5.TRADE_ACTION_SLTP,
        "position": position.ticket,
        "symbol":   position.symbol,
        "sl":       new_sl,
        "tp":       position.tp,
    }
    result = mt5.order_send(request)

    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        retcode = result.retcode if result else "None"
        logger.warning(
            "Không thể sửa SL ticket #%d: retcode=%s", position.ticket, retcode
        )
        return False

    return True


# ─── Core update logic ────────────────────────────────────────────────────────

def _update_position(position, candles: list):
    """Xử lý trailing stop cho 1 position."""
    ticket = position.ticket
    symbol = position.symbol

    trail_cfg = _get_trail_cfg(symbol)
    if not trail_cfg.get("enabled", True):
        return

    # Lấy hoặc tạo state
    if ticket not in _trail_states:
        direction = "BUY" if position.type == mt5.ORDER_TYPE_BUY else "SELL"
        _trail_states[ticket] = TrailState(
            ticket      = ticket,
            symbol      = symbol,
            direction   = direction,
            entry       = position.price_open,
            original_sl = position.sl,
            current_sl  = position.sl,
            peak_price  = position.price_current,
        )
        logger.debug("Đã đăng ký trailing stop cho ticket #%d %s %s", ticket, symbol, direction)

    state = _trail_states[ticket]

    # Mode "breakeven": sau khi da doi ve breakeven 1 lan, KHONG lam gi them.
    if state.activated and trail_cfg.get("mode", "breakeven") == "breakeven":
        return

    if not candles or len(candles) < 15:
        return

    atr = _calc_atr(candles, period=getattr(config, "ATR_PERIOD", 14))
    if atr <= 0:
        return

    activation_dist = atr * trail_cfg["activation_atr"]
    current_price   = position.price_current
    mode            = trail_cfg.get("mode", "breakeven")

    if state.direction == "BUY":
        profit_dist = current_price - state.entry
        if current_price > state.peak_price:
            state.peak_price = current_price

        if not state.activated:
            if profit_dist < activation_dist:
                return  # Chưa đủ profit để bật

            if mode == "breakeven":
                breakeven_sl = state.entry + atr * trail_cfg.get("breakeven_buffer_atr", 0.0)
                if breakeven_sl <= state.current_sl:
                    return  # SL hien tai da tot hon breakeven (hiem, nhung phong thu)
                if _modify_sl(position, breakeven_sl):
                    logger.info(
                        "🔒 Breakeven-lock BUY #%d %s: SL %.5f → %.5f (entry=%.5f) "
                        "— DUNG trail, cho hoa von hoac cham TP.",
                        ticket, symbol, state.current_sl, breakeven_sl, state.entry
                    )
                    state.current_sl = breakeven_sl
                    state.activated = True
                return

            # mode == "continuous": kich hoat, roi rot xuong logic trail ben duoi
            state.activated = True
            logger.info(
                "🟢 Trailing bật (continuous): #%d %s BUY | profit=%.5f >= activation=%.5f (%.1f×ATR)",
                ticket, symbol, profit_dist, activation_dist, trail_cfg["activation_atr"]
            )

        # Chi toi day khi mode == "continuous" va da activated
        trail_dist = atr * trail_cfg["trail_atr"]
        new_sl = state.peak_price - trail_dist
        if new_sl <= state.current_sl:
            return
        if _modify_sl(position, new_sl):
            logger.info(
                "📈 Trail BUY #%d %s: SL %.5f → %.5f (peak=%.5f trail_dist=%.5f)",
                ticket, symbol, state.current_sl, new_sl, state.peak_price, trail_dist
            )
            state.current_sl = new_sl

    else:  # SELL
        profit_dist = state.entry - current_price
        if current_price < state.peak_price or state.peak_price == 0:
            state.peak_price = current_price

        if not state.activated:
            if profit_dist < activation_dist:
                return

            if mode == "breakeven":
                breakeven_sl = state.entry - atr * trail_cfg.get("breakeven_buffer_atr", 0.0)
                if breakeven_sl >= state.current_sl:
                    return
                if _modify_sl(position, breakeven_sl):
                    logger.info(
                        "🔒 Breakeven-lock SELL #%d %s: SL %.5f → %.5f (entry=%.5f) "
                        "— DUNG trail, cho hoa von hoac cham TP.",
                        ticket, symbol, state.current_sl, breakeven_sl, state.entry
                    )
                    state.current_sl = breakeven_sl
                    state.activated = True
                return

            state.activated = True
            logger.info(
                "🔴 Trailing bật (continuous): #%d %s SELL | profit=%.5f >= activation=%.5f (%.1f×ATR)",
                ticket, symbol, profit_dist, activation_dist, trail_cfg["activation_atr"]
            )

        trail_dist = atr * trail_cfg["trail_atr"]
        new_sl = state.peak_price + trail_dist
        if new_sl >= state.current_sl:
            return
        if _modify_sl(position, new_sl):
            logger.info(
                "📉 Trail SELL #%d %s: SL %.5f → %.5f (peak=%.5f trail_dist=%.5f)",
                ticket, symbol, state.current_sl, new_sl, state.peak_price, trail_dist
            )
            state.current_sl = new_sl


def _cleanup_closed(open_tickets: set):
    """Xoá state của các ticket đã đóng."""
    closed = [t for t in _trail_states if t not in open_tickets]
    for t in closed:
        logger.debug("Xoá trail state ticket #%d (đã đóng)", t)
        del _trail_states[t]


# ─── Public API ───────────────────────────────────────────────────────────────

def update(get_candles_fn):
    """
    Gọi mỗi vòng poll trong watcher.py.

    get_candles_fn: hàm lấy nến, signature:
        get_candles_fn(symbol, timeframe, count) → list[dict]
    Truyền vào mt5_client.get_candles là được.
    """
    if mt5 is None:
        return

    # Lấy tất cả positions của bot
    all_positions = mt5.positions_get() or []
    bot_positions = [p for p in all_positions if p.magic == BOT_MAGIC]

    if not bot_positions:
        _cleanup_closed(set())
        return

    open_tickets = {p.ticket for p in bot_positions}
    _cleanup_closed(open_tickets)

    for position in bot_positions:
        candles = get_candles_fn(position.symbol, config.TIMEFRAME, 50)
        if candles:
            _update_position(position, candles)