# ai_v5/live/trade_executor.py
"""
Dat lenh THAT (market order) tren tai khoan rieng cua ai_v5.

Dung THANG SL/TP da duoc tinh san boi module detector tuong ung (moi mau
hinh trong 7 nhom co cach tinh SL/TP rieng phu hop voi ban chat cua no -
xem pipeline/*.py) - khong tinh lai, nhung co THEM cac lop kiem tra an toan
truoc khi dat lenh that (spread, khoang cach SL/TP toi thieu theo yeu cau
sang, tran SL toi da, ty le R:R toi thieu, tran so luong lenh/symbol, dao
lenh khi lo).
"""
import logging

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

from ai_v5.config_live import (
    MAGIC_NUMBER, MAX_OPEN_TRADES_PER_SYMBOL,
    MAX_OPEN_TRADES_PER_SYMBOL_HIGH_CONFIDENCE, HIGH_CONFIDENCE_EXTRA_SLOT_THRESHOLD,
    MAX_TOTAL_OPEN_TRADES, MAX_SPREAD_POINTS_DEFAULT, MAX_SPREAD_POINTS,
    ORDER_DEVIATION, MIN_SL_POINTS_DEFAULT, MAX_SL_DISTANCE,
    FIXED_LOT, FIXED_LOT_DEFAULT, ALLOW_REVERSE_ON_LOSS,
)

logger = logging.getLogger("ai_v5_trade_executor")

# Ty le R:R toi thieu duoc chap nhan cho MOI nguon pattern (khong chi 16 mau
# hinh co dien) - lop phong ve thu 2 (defense-in-depth), phong truong hop
# module detector nao do (VSA/ICT/Candlestick/...) cung tinh TP doc lap voi
# SL va vo tinh cho ra ty le R:R phi thuc te.
MIN_ACCEPTABLE_REWARD_RISK_RATIO = 0.8
DEFAULT_REWARD_RISK_RATIO = 1.5


def _get_filling_type(sym_info) -> int:
    fm = sym_info.filling_mode
    if fm & 2:
        return mt5.ORDER_FILLING_IOC
    if fm & 1:
        return mt5.ORDER_FILLING_FOK
    return mt5.ORDER_FILLING_RETURN


def _calc_lot(symbol: str, sl_distance: float):
    """
    Khoi luong lenh CO DINH theo tung symbol (khong tinh theo % rui ro tai
    khoan). Van lay symbol_info de kiem tra/lam tron dung volume_step,
    volume_min, volume_max cua broker. Tra ve (lot, risk_amount_uoc_tinh).
    """
    lot = FIXED_LOT.get(symbol, FIXED_LOT_DEFAULT)

    sym_info = mt5.symbol_info(symbol)
    if sym_info:
        step = sym_info.volume_step or 0.01
        lot = round(round(lot / step) * step, 8)
        lot = max(sym_info.volume_min, min(lot, sym_info.volume_max))
        lot = round(lot, 2)

        # Uoc tinh so tien rui ro (chi de hien thi log/Telegram, khong dung de tinh lot)
        tick_size = sym_info.trade_tick_size
        tick_value = sym_info.trade_tick_value
        if tick_size and tick_value and sl_distance:
            risk_amount = (sl_distance / tick_size) * tick_value * lot
        else:
            risk_amount = 0.0
    else:
        risk_amount = 0.0

    return lot, risk_amount


def _close_position(position) -> dict:
    """Dong 1 vi the dang mo bang lenh nguoc chieu (BUY dong SELL va nguoc lai)."""
    sym_info = mt5.symbol_info(position.symbol)
    tick = mt5.symbol_info_tick(position.symbol)
    if not sym_info or not tick:
        return {"success": False, "error": "Không lấy được thông tin symbol/tick để đóng lệnh"}

    is_buy = position.type == mt5.POSITION_TYPE_BUY
    close_price = tick.bid if is_buy else tick.ask
    close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": position.symbol,
        "volume": position.volume,
        "type": close_type,
        "position": position.ticket,
        "price": close_price,
        "deviation": ORDER_DEVIATION,
        "magic": MAGIC_NUMBER,
        "comment": "AIv5_reverse_close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": _get_filling_type(sym_info),
    }
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        retcode = result.retcode if result else "None"
        return {"success": False, "error": f"Đóng lệnh #{position.ticket} thất bại (retcode={retcode})"}

    return {"success": True, "ticket": position.ticket, "profit": position.profit}


def place_ai_v5_trade(symbol: str, direction: str, sl: float, tp: float,
                       pattern_name: str, win_prob: float) -> dict:
    """
    Dat lenh market that tren tai khoan cua AI v5.
    Tra ve dict: {"success": bool, "ticket": int, "entry": float, "sl": float,
                  "tp": float, "lot": float, "risk_amount": float, "error": str,
                  "reversed_ticket": int|None, "reversed_pnl": float|None}
    """
    if mt5 is None:
        return {"success": False, "error": "MetaTrader5 module không khả dụng trên môi trường này"}

    sym_info = mt5.symbol_info(symbol)
    if not sym_info:
        return {"success": False, "error": f"Không lấy được symbol_info cho {symbol}"}
    if not sym_info.visible:
        mt5.symbol_select(symbol, True)

    all_pos = mt5.positions_get() or []
    bot_pos = [p for p in all_pos if p.magic == MAGIC_NUMBER]
    sym_pos = [p for p in bot_pos if p.symbol == symbol]
    reversed_info = None  # Khoi tao o pham vi ham, de dung duoc ca khi khong can dao lenh

    # Tran so luong lenh/symbol: mac dinh MAX_OPEN_TRADES_PER_SYMBOL, nhung cho
    # phep them 1 lenh (toi da MAX_OPEN_TRADES_PER_SYMBOL_HIGH_CONFIDENCE) NEU
    # tin hieu nay co WinProb du cao - van bi chan cung o tran cao hon nay du
    # WinProb co cao den dau.
    max_allowed_this_symbol = (MAX_OPEN_TRADES_PER_SYMBOL_HIGH_CONFIDENCE
                                if win_prob >= HIGH_CONFIDENCE_EXTRA_SLOT_THRESHOLD
                                else MAX_OPEN_TRADES_PER_SYMBOL)
    if len(sym_pos) >= max_allowed_this_symbol:
        # Truoc khi tu choi vi da du tran, kiem tra co the DAO LENH khong:
        # tim 1 vi the NGUOC HUONG voi tin hieu moi VA dang LO tren cung symbol.
        if ALLOW_REVERSE_ON_LOSS:
            opposite_type = mt5.POSITION_TYPE_SELL if direction == "BUY" else mt5.POSITION_TYPE_BUY
            losing_opposite = [p for p in sym_pos if p.type == opposite_type and p.profit < 0]
            if losing_opposite:
                # Chon vi the lo NHIEU NHAT de dao (uu tien cat lenh te nhat truoc)
                target_pos = min(losing_opposite, key=lambda p: p.profit)
                close_result = _close_position(target_pos)
                if close_result["success"]:
                    logger.info(f"[AI v5 LIVE] 🔄 Đã ĐẢO LỆNH: đóng #{close_result['ticket']} "
                               f"(P&L={close_result['profit']:.2f}) trên {symbol} để mở lệnh {direction} mới.")
                    reversed_info = close_result
                    # Cap nhat lai danh sach vi the sau khi da dong, cho phep tiep tuc dat lenh moi
                    sym_pos = [p for p in sym_pos if p.ticket != target_pos.ticket]
                else:
                    logger.warning(f"[AI v5 LIVE] Đảo lệnh thất bại: {close_result['error']}")

        if len(sym_pos) >= max_allowed_this_symbol and reversed_info is None:
            extra_note = ("" if max_allowed_this_symbol > MAX_OPEN_TRADES_PER_SYMBOL
                          else f" - cần WinProb ≥ {HIGH_CONFIDENCE_EXTRA_SLOT_THRESHOLD:.0%} để mở thêm 1 lệnh")
            return {"success": False, "error": f"Đã có {len(sym_pos)} lệnh AI v5 trên {symbol} "
                                                f"(tối đa {max_allowed_this_symbol}{extra_note})"}

    if len(bot_pos) >= MAX_TOTAL_OPEN_TRADES:
        return {"success": False, "error": f"Đã đạt tối đa {MAX_TOTAL_OPEN_TRADES} lệnh AI v5 tổng"}

    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return {"success": False, "error": f"Không lấy được tick cho {symbol}"}

    spread_points = sym_info.spread
    max_spread = MAX_SPREAD_POINTS.get(symbol, MAX_SPREAD_POINTS_DEFAULT)
    if spread_points > max_spread:
        return {"success": False, "error": f"Spread {spread_points} pts > {max_spread} pts — thị trường đang rộng"}

    entry = tick.ask if direction == "BUY" else tick.bid
    digits = sym_info.digits
    sl = round(sl, digits)
    tp = round(tp, digits)

    point = sym_info.point

    # Muc khoang cach toi thieu THAT do chinh SAN/BROKER quy dinh cho symbol nay
    # (trade_stops_level, tinh theo points) - khac nhau giua cac loai tai khoan
    # (standard/cent/ECN...). Truoc day chi dung nguong cung MIN_SL_POINTS_DEFAULT=30,
    # khong doc gia tri that tu broker -> gay retcode=10016 (Invalid SL/TP) tren
    # tai khoan co stops_level cao hon 30 (vd tai khoan cent).
    broker_min_points = getattr(sym_info, "trade_stops_level", 0) or 0
    min_distance_points = max(MIN_SL_POINTS_DEFAULT, broker_min_points + 2)  # +2 points de an toan du deviation
    min_distance = min_distance_points * point if point else 0

    sl_points = abs(entry - sl) / point if point else 0
    if sl_points < min_distance_points:
        return {"success": False, "error": f"SL quá gần entry ({sl_points:.1f} pts < tối thiểu {min_distance_points:.0f} pts, "
                                            f"trong đó sàn yêu cầu tối thiểu {broker_min_points:.0f} pts)"}

    tp_points = abs(tp - entry) / point if point else 0
    if tp_points < min_distance_points:
        return {"success": False, "error": f"TP quá gần entry ({tp_points:.1f} pts < tối thiểu {min_distance_points:.0f} pts, "
                                            f"trong đó sàn yêu cầu tối thiểu {broker_min_points:.0f} pts)"}

    sl_distance = abs(entry - sl)

    max_sl = MAX_SL_DISTANCE.get(symbol)
    if max_sl is not None and sl_distance > max_sl:
        logger.warning(f"[AI v5 LIVE] SL quá xa ({sl_distance:.4f} > trần {max_sl}) cho {symbol} — "
                       f"thu hẹp SL về mức an toàn thay vì huỷ lệnh.")
        if direction == "BUY":
            sl = round(entry - max_sl, digits)
        else:
            sl = round(entry + max_sl, digits)
        sl_distance = abs(entry - sl)
        # Giu nguyen ty le R:R mac dinh cho an toan (thay vi suy ra tu TP cu co the cung qua xa)
        tp = round(entry + DEFAULT_REWARD_RISK_RATIO * sl_distance, digits) if direction == "BUY" else round(entry - DEFAULT_REWARD_RISK_RATIO * sl_distance, digits)

    # Lop phong ve THU 2 (defense-in-depth), ap dung cho MOI nguon pattern (khong
    # chi 16 mau hinh co dien da duoc tu sua trong pattern_rules.py) - phong truong
    # hop module detector nao do (VSA/ICT/Candlestick/...) cung tinh TP doc lap voi
    # SL va vo tinh cho ra ty le R:R phi thuc te (da xac nhan xay ra that voi
    # BEARISH_RISING_WEDGE truoc khi sua o pattern_rules.py).
    reward_distance = abs(tp - entry)
    if sl_distance > 0 and reward_distance / sl_distance < MIN_ACCEPTABLE_REWARD_RISK_RATIO:
        logger.warning(f"[AI v5 LIVE] R:R quá thấp (1:{reward_distance/sl_distance:.2f}) cho {symbol} "
                       f"({pattern_name}) — tự động tính lại TP theo tỷ lệ 1:{DEFAULT_REWARD_RISK_RATIO} an toàn.")
        tp = round(entry + DEFAULT_REWARD_RISK_RATIO * sl_distance, digits) if direction == "BUY" else round(entry - DEFAULT_REWARD_RISK_RATIO * sl_distance, digits)

    lot, risk_amount = _calc_lot(symbol, sl_distance)
    if lot <= 0:
        return {"success": False, "error": "Không tính được lot hợp lệ"}

    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
    filling = _get_filling_type(sym_info)
    rr = round(abs(tp - entry) / sl_distance, 2) if sl_distance else 0

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": order_type,
        "price": entry,
        "sl": sl,
        "tp": tp,
        "deviation": ORDER_DEVIATION,
        "magic": MAGIC_NUMBER,
        "comment": f"AIv5_{pattern_name[:10]}_{int(win_prob * 100)}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling,
    }

    logger.info(f"[AI v5 LIVE] Chuẩn bị đặt lệnh: {direction} {symbol} | lot={lot} | entry={entry} | "
                f"SL={sl} | TP={tp} | R:R=1:{rr} | pattern={pattern_name} | WinProb={win_prob:.1%}")

    result = mt5.order_send(request)
    if result is None:
        return {"success": False, "error": "order_send trả về None"}

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        desc = {
            10004: "Requote", 10006: "Rejected", 10013: "Invalid request",
            10014: "Invalid volume", 10015: "Invalid price", 10016: "Invalid SL/TP",
            10018: "Market closed", 10019: "Not enough money",
            10025: "Too many requests", 10030: "Invalid fill",
        }.get(result.retcode, "Xem MQL5 TRADE_RETCODE")
        return {"success": False, "error": f"retcode={result.retcode} ({desc}) | {result.comment}"}

    logger.info(f"[AI v5 LIVE] ✅ Đặt lệnh thành công #{result.order} {symbol} {direction} {lot} lots "
                f"Entry={result.price} SL={sl} TP={tp} R:R=1:{rr}")
    if reversed_info:
        logger.info(f"[AI v5 LIVE] (Lệnh này thay thế cho lệnh #{reversed_info['ticket']} vừa bị đảo)")

    return {
        "success": True, "ticket": result.order, "symbol": symbol, "direction": direction,
        "lot": lot, "entry": result.price, "sl": sl, "tp": tp, "rr": rr, "risk_amount": risk_amount,
        "reversed_ticket": reversed_info["ticket"] if reversed_info else None,
        "reversed_pnl": reversed_info["profit"] if reversed_info else None,
    }
