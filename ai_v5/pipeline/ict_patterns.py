# ai_v5/pipeline/ict_patterns.py
"""
Bo phat hien cac khai niem ICT/SMC nang cao (bo sung cho SMC BOS/CHoCH co
ban da co san trong analysis.py cua bot v4):
    - ORDER BLOCK: nen doi mau cuoi cung truoc 1 cu Dich chuyen manh
      (Displacement) pha vo cau truc - vung ma "Tien Thong Minh" duoc cho
      la da dat lenh, gia thuong quay lai test truoc khi tiep tuc.
    - FAIR VALUE GAP (FVG): khoang trong gia (Imbalance) giua 3 nen lien
      tiep - gia co xu huong quay lai lap day truoc khi di tiep.
    - LIQUIDITY SWEEP: gia quet qua 1 Dinh/Day gan nhat (rau nen vuot qua)
      roi dong cua tro lai ben trong - dau hieu "san thanh khoan" (stop
      hunt) truoc khi dao chieu.

Quy uoc dau ra GIONG HET cac module pattern khac de build_dataset.py goi
thong nhat: {"pattern": str, "direction": "BUY"|"SELL", "sl": float, "tp": float}
hoac None neu khong khop.

Input candles: list cac dict {'open','high','low','close'}, sap xep tang
dan theo thoi gian, candles[-1] la nen hien tai.
"""

SL_BUFFER_ATR = 0.3
REWARD_RISK_RATIO = 1.5
DISPLACEMENT_ATR_RATIO = 1.5  # Than nen phai >= 1.5x ATR moi duoc coi la Dich chuyen manh
MIN_FVG_SIZE_ATR = 0.2        # Khoang trong toi thieu (tinh theo ATR) moi duoc coi la FVG dang ke


def _rr_sl_tp(direction, entry, extreme, atr):
    buffer = SL_BUFFER_ATR * atr
    if direction == "BUY":
        sl = extreme - buffer
        risk = entry - sl
        tp = entry + REWARD_RISK_RATIO * risk
    else:
        sl = extreme + buffer
        risk = sl - entry
        tp = entry - REWARD_RISK_RATIO * risk
    return float(sl), float(tp)


def detect_order_block(candles: list, swings: list, current_price: float, atr: float) -> dict:
    """
    candles: >= 6 nen gan nhat. swings: dinh/day da xac nhan gan nhat.
    Kiem tra nen hien tai co phai la nen Dich chuyen manh pha vo cau truc
    (BOS) hay khong; neu co, lui lai tim nen doi mau gan nhat lam Order Block.
    """
    if len(candles) < 6 or not swings or atr <= 0:
        return None

    current = candles[-1]
    body = abs(current["close"] - current["open"])
    if body < DISPLACEMENT_ATR_RATIO * atr:
        return None  # Khong phai nen Dich chuyen du manh

    last_swing = swings[-1]
    is_bullish_break = (current["close"] > current["open"] and
                         last_swing["type"] == "HIGH" and current["close"] > last_swing["price"])
    is_bearish_break = (current["close"] < current["open"] and
                         last_swing["type"] == "LOW" and current["close"] < last_swing["price"])

    if is_bullish_break:
        for c in reversed(candles[:-1]):
            if c["close"] < c["open"]:  # Nen GIAM gan nhat = Bullish Order Block
                sl, tp = _rr_sl_tp("BUY", current_price, c["low"], atr)
                return {"pattern": "BULLISH_ORDER_BLOCK", "direction": "BUY", "sl": sl, "tp": tp}

    if is_bearish_break:
        for c in reversed(candles[:-1]):
            if c["close"] > c["open"]:  # Nen TANG gan nhat = Bearish Order Block
                sl, tp = _rr_sl_tp("SELL", current_price, c["high"], atr)
                return {"pattern": "BEARISH_ORDER_BLOCK", "direction": "SELL", "sl": sl, "tp": tp}

    return None


def detect_fair_value_gap(candles: list, atr: float) -> dict:
    """3 nen lien tiep: kiem tra khoang trong gia (Imbalance) giua nen dau va nen cuoi."""
    if len(candles) < 3 or atr <= 0:
        return None

    c1, c2, c3 = candles[-3], candles[-2], candles[-1]
    entry = c3["close"]

    if c1["high"] < c3["low"]:  # Bullish FVG: khoang trong ben duoi
        gap_size = c3["low"] - c1["high"]
        if gap_size >= MIN_FVG_SIZE_ATR * atr:
            sl, tp = _rr_sl_tp("BUY", entry, c1["high"], atr)
            return {"pattern": "BULLISH_FVG", "direction": "BUY", "sl": sl, "tp": tp}

    if c1["low"] > c3["high"]:  # Bearish FVG: khoang trong ben tren
        gap_size = c1["low"] - c3["high"]
        if gap_size >= MIN_FVG_SIZE_ATR * atr:
            sl, tp = _rr_sl_tp("SELL", entry, c1["low"], atr)
            return {"pattern": "BEARISH_FVG", "direction": "SELL", "sl": sl, "tp": tp}

    return None


def detect_liquidity_sweep(candles: list, swings: list, atr: float) -> dict:
    """Nen hien tai co rau nen vuot qua Dinh/Day gan nhat roi dong cua tro lai ben trong (san thanh khoan)."""
    if len(candles) < 1 or not swings or atr <= 0:
        return None

    current = candles[-1]
    last_swing = swings[-1]
    entry = current["close"]

    if last_swing["type"] == "HIGH" and current["high"] > last_swing["price"] and current["close"] < last_swing["price"]:
        sl, tp = _rr_sl_tp("SELL", entry, current["high"], atr)
        return {"pattern": "BEARISH_LIQUIDITY_SWEEP", "direction": "SELL", "sl": sl, "tp": tp}

    if last_swing["type"] == "LOW" and current["low"] < last_swing["price"] and current["close"] > last_swing["price"]:
        sl, tp = _rr_sl_tp("BUY", entry, current["low"], atr)
        return {"pattern": "BULLISH_LIQUIDITY_SWEEP", "direction": "BUY", "sl": sl, "tp": tp}

    return None
