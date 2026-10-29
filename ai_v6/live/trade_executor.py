# ai_v6/live/trade_executor.py
"""
Dat lenh THAT cho ai_v6 (chien luoc DCA 1 chieu, XAUUSD).

KHAC ai_v5: khong dat SL/TP rieng cho tung lenh tai thoi diem mo (moi lenh
trong nhom DCA se dung CHUNG 1 cap SL/TP tinh theo gia vao trung binh, xem
position_group_manager.py) - lenh duoc mo TRUOC voi sl=0/tp=0, ngay sau do
goi recalc_and_apply_group_sl_tp() de tinh + gan SL/TP DUNG NHAT cho CA
NHOM (bao gom ca lenh vua mo). Khoang trong (lenh chua co SL) chi ton tai
trong khoang thoi gian giua 2 lenh gui API lien tiep (thuong duoi 1 giay).
"""
import logging

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

from ai_v6.config_live import (
    MAGIC_NUMBER, MAX_DCA_POSITIONS, FIXED_LOT, FIXED_LOT_DEFAULT,
    MAX_SPREAD_POINTS, MAX_SPREAD_POINTS_DEFAULT, ORDER_DEVIATION,
)
from ai_v6.live import position_group_manager as group_mgr

logger = logging.getLogger("ai_v6_trade_executor")


def _get_filling_type(sym_info) -> int:
    fm = sym_info.filling_mode
    if fm & 2:
        return mt5.ORDER_FILLING_IOC
    if fm & 1:
        return mt5.ORDER_FILLING_FOK
    return mt5.ORDER_FILLING_RETURN


def _calc_lot(symbol: str) -> float:
    lot = FIXED_LOT.get(symbol, FIXED_LOT_DEFAULT)
    sym_info = mt5.symbol_info(symbol)
    if sym_info:
        step = sym_info.volume_step or 0.01
        lot = round(round(lot / step) * step, 8)
        lot = max(sym_info.volume_min, min(lot, sym_info.volume_max))
        lot = round(lot, 2)
    return lot


def place_v6_trade(symbol: str, direction: str, pattern_name: str, win_prob: float, atr: float,
                    is_dca: bool = False) -> dict:
    """
    Mo 1 lenh market (lenh GOC hoac lenh DCA thu 2/3 - is_dca chi anh huong
    log/comment/Telegram, phan an toan giong het nhau). Sau khi mo thanh
    cong, TU DONG tinh lai va ap dung SL/TP MOI cho CA NHOM.

    Tra ve dict: {"success": bool, "ticket": int, "entry": float, "lot": float, "is_dca": bool,
                  "n_positions_in_group": int, "group_avg_entry": float,
                  "group_sl": float, "group_tp": float, "error": str}
    """
    if mt5 is None:
        return {"success": False, "error": "MetaTrader5 module không khả dụng trên môi trường này"}

    existing = group_mgr.get_group_positions(symbol)
    if len(existing) >= MAX_DCA_POSITIONS:
        return {"success": False, "error": f"Nhóm DCA {symbol} đã đủ {MAX_DCA_POSITIONS} lệnh (tối đa)"}

    if existing:
        group_direction = group_mgr.get_group_direction(existing)
        if group_direction != direction:
            return {"success": False, "error": f"Nhóm DCA {symbol} đang {group_direction}, không thể "
                                                f"thêm lệnh {direction} ngược chiều (chiến lược 1 chiều tuyệt đối)"}

    sym_info = mt5.symbol_info(symbol)
    if not sym_info:
        return {"success": False, "error": f"Không lấy được symbol_info cho {symbol}"}
    if not sym_info.visible:
        mt5.symbol_select(symbol, True)

    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return {"success": False, "error": f"Không lấy được tick cho {symbol}"}

    spread_points = sym_info.spread
    max_spread = MAX_SPREAD_POINTS.get(symbol, MAX_SPREAD_POINTS_DEFAULT)
    if spread_points > max_spread:
        return {"success": False, "error": f"Spread {spread_points} pts > {max_spread} pts — thị trường đang rộng"}

    entry = tick.ask if direction == "BUY" else tick.bid
    lot = _calc_lot(symbol)
    if lot <= 0:
        return {"success": False, "error": "Không tính được lot hợp lệ"}

    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
    filling = _get_filling_type(sym_info)

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": order_type,
        "price": entry,
        "sl": 0.0,   # SL/TP thuc te se duoc gan NGAY sau do o cap NHOM (xem recalc_and_apply_group_sl_tp)
        "tp": 0.0,
        "deviation": ORDER_DEVIATION,
        "magic": MAGIC_NUMBER,
        "comment": f"AIv6_{'DCA' if is_dca else 'INIT'}_{pattern_name[:8]}_{int(win_prob * 100)}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling,
    }

    logger.info(f"[AI v6 LIVE] Chuẩn bị mở lệnh {'DCA' if is_dca else 'GỐC'}: {direction} {symbol} "
                f"lot={lot} entry={entry} pattern={pattern_name} WinProb={win_prob:.1%}")

    result = mt5.order_send(request)
    if result is None:
        return {"success": False, "error": "order_send trả về None"}
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        desc = {
            10004: "Requote", 10006: "Rejected", 10013: "Invalid request",
            10014: "Invalid volume", 10015: "Invalid price", 10018: "Market closed",
            10019: "Not enough money", 10025: "Too many requests",
        }.get(result.retcode, "Xem MQL5 TRADE_RETCODE")
        return {"success": False, "error": f"retcode={result.retcode} ({desc}) | {result.comment}"}

    logger.info(f"[AI v6 LIVE] ✅ Mở lệnh {'DCA' if is_dca else 'GỐC'} thành công #{result.order} "
                f"{symbol} {direction} {lot} lot Entry={result.price}")

    # Tinh lai NGAY breakeven + SL/TP cho CA NHOM (bao gom lenh vua mo)
    group_result = group_mgr.recalc_and_apply_group_sl_tp(symbol, atr)

    return {
        "success": True, "ticket": result.order, "symbol": symbol, "direction": direction,
        "lot": lot, "entry": result.price, "is_dca": is_dca,
        "n_positions_in_group": group_result.get("n_positions", 1),
        "group_avg_entry": group_result.get("avg_entry"),
        "group_sl": group_result.get("sl"), "group_tp": group_result.get("tp"),
    }


def close_group_positions(symbol: str, reason: str = "") -> dict:
    """
    BẢN VÁ (thiết kế lại thành SCALPING): đóng TOÀN BỘ vị thế đang mở trong nhóm DCA của
    symbol này bằng lệnh thị trường ngược chiều - dùng cho cơ chế CHỐT LỆNH THEO THỜI GIAN
    (MAX_HOLD_MINUTES trong config_live.py): không giữ lệnh vô thời hạn chờ TP xa, đặc trưng
    bắt buộc của scalping. Logic đóng lệnh tương tự _close_position() của ai_v5/trade_executor.py
    nhưng lặp qua TOÀN BỘ lệnh trong nhóm thay vì 1 lệnh đơn (do đảo lệnh).

    Tra ve dict: {"closed": int, "total": int, "failed_tickets": [ticket,...]}
    """
    positions = group_mgr.get_group_positions(symbol)
    if not positions:
        return {"closed": 0, "total": 0, "failed_tickets": []}

    closed = 0
    failed = []
    for p in positions:
        sym_info = mt5.symbol_info(p.symbol)
        tick = mt5.symbol_info_tick(p.symbol)
        if not sym_info or not tick:
            failed.append(p.ticket)
            continue

        is_buy = p.type == mt5.POSITION_TYPE_BUY
        close_price = tick.bid if is_buy else tick.ask
        close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": p.symbol,
            "volume": p.volume,
            "type": close_type,
            "position": p.ticket,
            "price": close_price,
            "deviation": ORDER_DEVIATION,
            "magic": MAGIC_NUMBER,
            "comment": f"AIv6_timeout_{reason[:15]}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": _get_filling_type(sym_info),
        }
        result = mt5.order_send(request)
        if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
            closed += 1
            logger.info(f"[AI v6 LIVE] ⏱ Đã đóng #{p.ticket} theo giới hạn thời gian ({reason}).")
        else:
            retcode = result.retcode if result else "None"
            failed.append(p.ticket)
            logger.warning(f"[AI v6 LIVE] Đóng #{p.ticket} theo thời gian thất bại (retcode={retcode}).")

    logger.info(f"[AI v6] Đóng nhóm {symbol} theo thời gian ({reason}): {closed}/{len(positions)} lệnh thành công.")
    return {"closed": closed, "total": len(positions), "failed_tickets": failed}
