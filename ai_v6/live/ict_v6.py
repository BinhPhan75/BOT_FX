# ai_v6/live/ict_v6.py
"""
ICT: Order Block (BOS + dich chuyen) va Liquidity Sweep - SUA LOI LOGIC cua ai_v5/pipeline/ict_patterns.py.
(Fair Value Gap cua ai_v5 KHONG co loi dinh nghia nen giu nguyen.)

LOI GOC (da chay thu):
  - Dung `swings[-1]` (swing CUOI CUNG bat ke loai) lam moc: neu swing cuoi la DAY (vua co nhip hoi), cu pha DINH cu
    (BOS tang kinh dien) bi bo sot vi code doi swing cuoi phai la DINH. Tuong tu liquidity sweep dinh khi swing cuoi la day.
  - BOS khong kiem tra "pha MOI": moi nen lon dong tren dinh cu deu bao lai Order Block du dinh da bi pha tu truoc.
  - Khong gioi han tuoi cua swing: swing cach 300 nen van duoc dung.

SUA: dung swing DINH gan nhat va swing DAY gan nhat RIENG BIET (trong MAX_SWING_AGE nen); BOS yeu cau nen truoc DONG CUA CHUA vuot moc.
"""
SL_BUFFER_ATR = 0.3
REWARD_RISK_RATIO = 1.5
DISPLACEMENT_ATR_RATIO = 1.5
MAX_SWING_AGE = 80


def _rr_sl_tp(direction, entry, extreme, atr):
    buffer = SL_BUFFER_ATR * atr
    if direction == "BUY":
        sl = extreme - buffer
        return float(sl), float(entry + REWARD_RISK_RATIO * (entry - sl))
    sl = extreme + buffer
    return float(sl), float(entry - REWARD_RISK_RATIO * (sl - entry))


def _last_swing(swings, stype, cur_index):
    for s in reversed(swings):
        if s["type"] == stype and s["index"] < cur_index:
            return s if cur_index - s["index"] <= MAX_SWING_AGE else None
    return None


def detect_order_block_v6(candles: list, swings: list, cur_index: int, current_price: float, atr: float):
    if len(candles) < 6 or not swings or atr <= 0:
        return None
    cur, prev = candles[-1], candles[-2]
    if abs(cur["close"] - cur["open"]) < DISPLACEMENT_ATR_RATIO * atr:
        return None

    hi, lo = _last_swing(swings, "HIGH", cur_index), _last_swing(swings, "LOW", cur_index)
    if hi and cur["close"] > cur["open"] and cur["close"] > hi["price"] and prev["close"] <= hi["price"]:
        for c in reversed(candles[:-1]):
            if c["close"] < c["open"]:
                sl, tp = _rr_sl_tp("BUY", current_price, c["low"], atr)
                return {"pattern": "BULLISH_ORDER_BLOCK", "direction": "BUY", "sl": sl, "tp": tp}
    if lo and cur["close"] < cur["open"] and cur["close"] < lo["price"] and prev["close"] >= lo["price"]:
        for c in reversed(candles[:-1]):
            if c["close"] > c["open"]:
                sl, tp = _rr_sl_tp("SELL", current_price, c["high"], atr)
                return {"pattern": "BEARISH_ORDER_BLOCK", "direction": "SELL", "sl": sl, "tp": tp}
    return None


def detect_liquidity_sweep_v6(candles: list, swings: list, cur_index: int, atr: float):
    if not candles or not swings or atr <= 0:
        return None
    cur = candles[-1]
    entry = cur["close"]
    hi, lo = _last_swing(swings, "HIGH", cur_index), _last_swing(swings, "LOW", cur_index)
    if hi and cur["high"] > hi["price"] and cur["close"] < hi["price"]:
        sl, tp = _rr_sl_tp("SELL", entry, cur["high"], atr)
        return {"pattern": "BEARISH_LIQUIDITY_SWEEP", "direction": "SELL", "sl": sl, "tp": tp}
    if lo and cur["low"] < lo["price"] and cur["close"] > lo["price"]:
        sl, tp = _rr_sl_tp("BUY", entry, cur["low"], atr)
        return {"pattern": "BULLISH_LIQUIDITY_SWEEP", "direction": "BUY", "sl": sl, "tp": tp}
    return None
