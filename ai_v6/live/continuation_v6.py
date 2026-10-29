# ai_v6/live/continuation_v6.py
"""
Rounding Top/Bottom, Cup & Handle - SUA LOI LOGIC cua ai_v5/pipeline/continuation_patterns.py.

LOI GOC (da chay thu): "vanh cuc" (rim) duoc lay bang max/min cua cac DAY (voi Rounding Bottom) thay vi cac DINH tao nen
vanh cuc. Dieu kien "gia pha vanh" (current_price > rim) vi vay chi la "gia cao hon day dau tien cua cuc" - dung ngay khi
gia con cach vanh thuc ~10$. Cup & Handle dung rim sai nay de tinh do sau cuc/handle nen ca hai deu vo nghia. Ngoai ra
khong yeu cau pha MOI (nen truoc dong cua chua vuot vanh) nen bao lap lai o moi nen.

SUA: rim = dinh CAO NHAT (Rounding Bottom) / day THAP NHAT (Rounding Top) cua cac swing doi dien nam GIUA day dau va day cuoi cua cuc;
bat buoc co it nhat 1 swing doi dien do; yeu cau pha moi: nen truoc dong cua <= rim, nen hien tai dong > rim.
"""
SL_BUFFER_ATR = 0.3
REWARD_RISK_RATIO = 1.5
MAX_SL_ATR_MULTIPLE = 10


def _rr_sl_tp(direction, entry, extreme, atr):
    buffer, max_d = SL_BUFFER_ATR * atr, MAX_SL_ATR_MULTIPLE * atr
    if direction == "BUY":
        sl = max(extreme - buffer, entry - max_d)
        return float(sl), float(entry + REWARD_RISK_RATIO * (entry - sl))
    sl = min(extreme + buffer, entry + max_d)
    return float(sl), float(entry - REWARD_RISK_RATIO * (sl - entry))


def _is_u(prices):
    n, k = len(prices), prices.index(min(prices))
    return 1 <= k <= n - 2 and prices[0] > prices[k] and prices[-1] > prices[k]


def _is_inv_u(prices):
    n, k = len(prices), prices.index(max(prices))
    return 1 <= k <= n - 2 and prices[0] < prices[k] and prices[-1] < prices[k]


def _rim(swings, first_idx, last_idx, opposite, pick):
    vals = [s["price"] for s in swings if s["type"] == opposite and first_idx < s["index"] < last_idx]
    return pick(vals) if vals else None


def detect_rounding_bottom_v6(swings, current_price, prev_close, atr):
    lows = [s for s in swings if s["type"] == "LOW"]
    if len(lows) < 5 or atr <= 0:
        return None
    cup = lows[-5:]
    prices = [s["price"] for s in cup]
    if not _is_u(prices):
        return None
    rim = _rim(swings, cup[0]["index"], cup[-1]["index"], "HIGH", max)
    if rim is None or not (current_price > rim >= prev_close):
        return None
    sl, tp = _rr_sl_tp("BUY", current_price, min(prices), atr)
    return {"pattern": "ROUNDING_BOTTOM", "direction": "BUY", "sl": sl, "tp": tp}


def detect_rounding_top_v6(swings, current_price, prev_close, atr):
    highs = [s for s in swings if s["type"] == "HIGH"]
    if len(highs) < 5 or atr <= 0:
        return None
    cap = highs[-5:]
    prices = [s["price"] for s in cap]
    if not _is_inv_u(prices):
        return None
    rim = _rim(swings, cap[0]["index"], cap[-1]["index"], "LOW", min)
    if rim is None or not (current_price < rim <= prev_close):
        return None
    sl, tp = _rr_sl_tp("SELL", current_price, max(prices), atr)
    return {"pattern": "ROUNDING_TOP", "direction": "SELL", "sl": sl, "tp": tp}


def detect_cup_and_handle_v6(swings, current_price, prev_close, atr):
    lows = [s for s in swings if s["type"] == "LOW"]
    if len(lows) < 6 or atr <= 0:
        return None
    cup = lows[-6:-1]
    prices = [s["price"] for s in cup]
    if not _is_u(prices):
        return None
    rim = _rim(swings, cup[0]["index"], cup[-1]["index"], "HIGH", max)
    if rim is None:
        return None
    depth = rim - min(prices)
    handle_low = lows[-1]["price"]
    handle_depth = rim - handle_low
    if depth <= 0 or not (0 < handle_depth < 0.5 * depth):
        return None
    if not (current_price > rim >= prev_close):
        return None
    sl, tp = _rr_sl_tp("BUY", current_price, handle_low, atr)
    return {"pattern": "CUP_AND_HANDLE", "direction": "BUY", "sl": sl, "tp": tp}


def detect_inverted_cup_and_handle_v6(swings, current_price, prev_close, atr):
    highs = [s for s in swings if s["type"] == "HIGH"]
    if len(highs) < 6 or atr <= 0:
        return None
    cap = highs[-6:-1]
    prices = [s["price"] for s in cap]
    if not _is_inv_u(prices):
        return None
    rim = _rim(swings, cap[0]["index"], cap[-1]["index"], "LOW", min)
    if rim is None:
        return None
    depth = max(prices) - rim
    handle_high = highs[-1]["price"]
    handle_depth = handle_high - rim
    if depth <= 0 or not (0 < handle_depth < 0.5 * depth):
        return None
    if not (current_price < rim <= prev_close):
        return None
    sl, tp = _rr_sl_tp("SELL", current_price, handle_high, atr)
    return {"pattern": "INVERTED_CUP_AND_HANDLE", "direction": "SELL", "sl": sl, "tp": tp}
