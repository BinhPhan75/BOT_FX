# ai_v6/live/position_group_manager.py
"""
Quan ly NHOM lenh DCA 1 CHIEU tren 1 symbol (XAUUSD) - toi da
config_live.MAX_DCA_POSITIONS lenh cung huong.

MT5 KHONG co khai niem "group SL/TP" native (moi position la 1 entity doc
lap voi SL/TP rieng). Module nay MO PHONG hanh vi "dong ca nhom cung luc"
bang cach: sau MOI LAN mo/them 1 lenh trong nhom, tinh lai GIA VAO TRUNG
BINH co trong so theo khoi luong (dung dinh nghia DCA/breakeven chuan) cua
TOAN BO lenh dang mo (cung magic + symbol), roi GAN CUNG 1 cap gia tri
SL/TP cho TAT CA lenh trong nhom (sua qua TRADE_ACTION_SLTP). Vi tat ca lenh
dung chung 1 muc gia SL/TP, khi gia thi truong cham muc do, tung lenh MT5
van kich hoat DOC LAP nhung THUC TE se xay ra gan nhu dong thoi (cung 1 tick
gia hoac chenh lech vai mili giay do co che khop lenh cua broker).
"""
import logging

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

from ai_v6.config_live import MAGIC_NUMBER, SCALP_SL_ATR_MULTIPLE, SCALP_REWARD_RISK_RATIO

logger = logging.getLogger("ai_v6_position_group")


def get_group_positions(symbol: str) -> list:
    """Danh sach vi the dang mo cua ai_v6 tren symbol nay (loc theo MAGIC_NUMBER RIENG
    cua ai_v6 - khong bao gio lan voi lenh cua v4/ai_v5 du chung 1 terminal)."""
    if mt5 is None:
        return []
    all_pos = mt5.positions_get(symbol=symbol) or []
    return [p for p in all_pos if p.magic == MAGIC_NUMBER]


def get_group_direction(positions: list):
    """BUY hoac SELL - ca nhom LUON cung 1 huong (dam bao boi trade_executor.place_v6_trade(),
    tu choi mo lenh nguoc huong voi nhom dang mo - chien luoc 1 chieu tuyet doi)."""
    if not positions:
        return None
    return "BUY" if positions[0].type == mt5.POSITION_TYPE_BUY else "SELL"


def calc_group_average_entry(positions: list) -> float:
    """Gia vao TRUNG BINH co trong so theo khoi luong - dung cong thuc DCA/breakeven chuan
    (KHONG phai trung binh cong don gian cac gia entry, vi cac lenh co the khac volume)."""
    total_volume = sum(p.volume for p in positions)
    if total_volume <= 0:
        return 0.0
    weighted_sum = sum(p.price_open * p.volume for p in positions)
    return weighted_sum / total_volume


def get_group_open_time(positions: list):
    """BẢN VÁ (chốt lệnh theo thời gian - scalping): thời điểm mở LỆNH GỐC (sớm nhất) trong
    nhóm, dùng để tính đã giữ nhóm bao lâu (so với MAX_HOLD_MINUTES trong config_live.py).
    Trả về Unix timestamp (giây, UTC) - giống định dạng position.time của MT5."""
    if not positions:
        return None
    return min(p.time for p in positions)


def calc_group_sl_tp(avg_entry: float, direction: str, atr: float, digits: int) -> tuple:
    """SL/TP MOI cho ca nhom, neo tu GIA VAO TRUNG BINH (khong phai tu entry cua rieng 1 lenh).
    BẢN VÁ: atr truyen vao gio la ATR KHUNG M1 (scalping), khong con la ATR M5 nhu ban dau -
    xem calc_m1_atr() trong mtf_scanner.py va ghi chu trong config_live.py."""
    sl_distance = SCALP_SL_ATR_MULTIPLE * atr
    if direction == "BUY":
        sl = avg_entry - sl_distance
        tp = avg_entry + SCALP_REWARD_RISK_RATIO * sl_distance
    else:
        sl = avg_entry + sl_distance
        tp = avg_entry - SCALP_REWARD_RISK_RATIO * sl_distance
    return round(sl, digits), round(tp, digits)


def apply_sl_tp_to_group(positions: list, sl: float, tp: float) -> dict:
    """Sua SL/TP cho TUNG lenh trong nhom ve CUNG 1 cap gia tri (TRADE_ACTION_SLTP).
    Tra ve {"success_count": int, "failed_tickets": [(ticket, retcode), ...]}."""
    success_count = 0
    failed = []
    for p in positions:
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": p.symbol,
            "position": p.ticket,
            "sl": sl,
            "tp": tp,
            "magic": MAGIC_NUMBER,
        }
        result = mt5.order_send(request)
        if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
            success_count += 1
        else:
            retcode = result.retcode if result else "None"
            failed.append((p.ticket, retcode))
            logger.warning(f"[AI v6] Không sửa được SL/TP cho lệnh #{p.ticket} (retcode={retcode})")
    return {"success_count": success_count, "failed_tickets": failed}


def recalc_and_apply_group_sl_tp(symbol: str, atr: float) -> dict:
    """Ham tien ich TRUNG TAM - goi NGAY SAU MOI LAN mo/them lenh trong nhom: tinh lai
    breakeven trung binh + SL/TP moi, ap dung cho toan bo nhom (bao gom lenh vua mo).
    Tra ve dict thong tin de log/ghi DB/gui Telegram."""
    positions = get_group_positions(symbol)
    if not positions:
        return {"n_positions": 0}

    direction = get_group_direction(positions)
    avg_entry = calc_group_average_entry(positions)

    sym_info = mt5.symbol_info(symbol)
    digits = sym_info.digits if sym_info else 2

    sl, tp = calc_group_sl_tp(avg_entry, direction, atr, digits)
    apply_result = apply_sl_tp_to_group(positions, sl, tp)

    total_volume = sum(p.volume for p in positions)
    logger.info(f"[AI v6] Nhóm DCA {symbol} ({direction}): {len(positions)} lệnh, "
                f"volume={total_volume:.2f}, Entry TB={avg_entry:.2f}, SL mới={sl}, TP mới={tp} "
                f"(áp dụng thành công {apply_result['success_count']}/{len(positions)} lệnh)")

    return {
        "n_positions": len(positions), "direction": direction, "avg_entry": avg_entry,
        "total_volume": total_volume, "sl": sl, "tp": tp, **apply_result,
    }
