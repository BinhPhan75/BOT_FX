# ai_v5/pipeline/candlestick_patterns.py
"""
Bo phat hien Mau hinh Nen Nhat (Candlestick Patterns) - nhom don nen/da nen,
khac voi 16 mau hinh hinh hoc dua tren cau truc Dinh/Day.

Quy uoc dau ra GIONG HET pattern_rules.detect_16_patterns() de build_dataset.py
co the goi thong nhat ca 3 nhom:
    {"pattern": str, "direction": "BUY"|"SELL", "sl": float, "tp": float}
hoac None neu khong khop mau hinh nao.

Input candles: list cac dict {'open','high','low','close'}, sap xep theo thoi
gian TANG DAN, candles[-1] la nen hien tai/moi dong gan nhat.
"""

REWARD_RISK_RATIO = 1.5  # Ty le R:R mac dinh de tinh TP tu SL (do nen khong co muc tieu do luong san co)


def _body(c):
    return abs(c["close"] - c["open"])


def _range(c):
    return max(c["high"] - c["low"], 1e-9)


def _is_bullish(c):
    return c["close"] > c["open"]


def _is_bearish(c):
    return c["close"] < c["open"]


def _upper_wick(c):
    return c["high"] - max(c["open"], c["close"])


def _lower_wick(c):
    return min(c["open"], c["close"]) - c["low"]


def _make_result(pattern, direction, entry, extreme, atr):
    """Dong goi SL/TP theo ATR + Ty le R:R chuan (vi nen khong co muc tieu do luong hinh hoc)."""
    buffer = 0.3 * atr
    if direction == "BUY":
        sl = extreme - buffer
        risk = entry - sl
        tp = entry + REWARD_RISK_RATIO * risk
    else:
        sl = extreme + buffer
        risk = sl - entry
        tp = entry - REWARD_RISK_RATIO * risk
    return {"pattern": pattern, "direction": direction, "sl": float(sl), "tp": float(tp)}


def _local_trend(candles, lookback=4):
    """Uoc luong xu huong ngan han truoc mau hinh: so sanh close dau va cuoi doan lookback."""
    if len(candles) < lookback + 1:
        return "FLAT"
    start_close = candles[-(lookback + 1)]["close"]
    end_close = candles[-2]["close"]  # nen ngay truoc mau hinh dang xet
    if end_close < start_close:
        return "DOWN"
    if end_close > start_close:
        return "UP"
    return "FLAT"


def detect_candlestick_patterns(candles: list, atr: float) -> dict:
    """
    candles: >= 5 nen gan nhat (sap xep tang dan theo thoi gian).
    Kiem tra theo thu tu: mau hinh 3 nen -> 2 nen -> 1 nen (uu tien mau hinh
    nhieu thong tin hon truoc).
    """
    if len(candles) < 5 or atr <= 0:
        return None

    c1, c2, c3 = candles[-3], candles[-2], candles[-1]
    entry = c3["close"]
    trend = _local_trend(candles, lookback=4)

    # ---------------- NHOM 3 NEN ----------------

    # MORNING STAR (dao chieu tang): nen giam manh -> nen than nho -> nen tang dong tren 50% than nen 1
    if _is_bearish(c1) and _body(c1) > 0.5 * _range(c1):
        if _body(c2) < 0.4 * _body(c1):
            if _is_bullish(c3) and c3["close"] > (c1["open"] + c1["close"]) / 2:
                extreme = min(c1["low"], c2["low"], c3["low"])
                return _make_result("MORNING_STAR", "BUY", entry, extreme, atr)

    # EVENING STAR (dao chieu giam): nen tang manh -> nen than nho -> nen giam dong duoi 50% than nen 1
    if _is_bullish(c1) and _body(c1) > 0.5 * _range(c1):
        if _body(c2) < 0.4 * _body(c1):
            if _is_bearish(c3) and c3["close"] < (c1["open"] + c1["close"]) / 2:
                extreme = max(c1["high"], c2["high"], c3["high"])
                return _make_result("EVENING_STAR", "SELL", entry, extreme, atr)

    # THREE WHITE SOLDIERS: 3 nen tang lien tiep, moi nen dong cao hon nen truoc
    if _is_bullish(c1) and _is_bullish(c2) and _is_bullish(c3):
        if c2["close"] > c1["close"] and c3["close"] > c2["close"]:
            if c2["open"] > c1["open"] and c3["open"] > c2["open"]:
                extreme = c1["low"]
                return _make_result("THREE_WHITE_SOLDIERS", "BUY", entry, extreme, atr)

    # THREE BLACK CROWS: 3 nen giam lien tiep, moi nen dong thap hon nen truoc
    if _is_bearish(c1) and _is_bearish(c2) and _is_bearish(c3):
        if c2["close"] < c1["close"] and c3["close"] < c2["close"]:
            if c2["open"] < c1["open"] and c3["open"] < c2["open"]:
                extreme = c1["high"]
                return _make_result("THREE_BLACK_CROWS", "SELL", entry, extreme, atr)

    # ---------------- NHOM 2 NEN ----------------

    # BULLISH ENGULFING: nen 1 giam, nen 2 tang va "nuot" than nen 1
    if _is_bearish(c2) and _is_bullish(c3):
        if c3["open"] <= c2["close"] and c3["close"] >= c2["open"]:
            extreme = min(c2["low"], c3["low"])
            return _make_result("BULLISH_ENGULFING", "BUY", entry, extreme, atr)

    # BEARISH ENGULFING: nguoc lai
    if _is_bullish(c2) and _is_bearish(c3):
        if c3["open"] >= c2["close"] and c3["close"] <= c2["open"]:
            extreme = max(c2["high"], c3["high"])
            return _make_result("BEARISH_ENGULFING", "SELL", entry, extreme, atr)

    # PIERCING LINE: nen giam -> nen tang dong tren 50% than nen 1 nhung duoi gia mo nen 1
    if _is_bearish(c2) and _is_bullish(c3):
        midpoint = (c2["open"] + c2["close"]) / 2
        if c3["open"] < c2["close"] and c2["close"] < c3["close"] < midpoint + (c2["open"] - midpoint) and c3["close"] > midpoint and c3["close"] < c2["open"]:
            extreme = min(c2["low"], c3["low"])
            return _make_result("PIERCING_LINE", "BUY", entry, extreme, atr)

    # DARK CLOUD COVER: nguoc lai
    if _is_bullish(c2) and _is_bearish(c3):
        midpoint = (c2["open"] + c2["close"]) / 2
        if c3["open"] > c2["close"] and c3["close"] < midpoint and c3["close"] > c2["open"]:
            extreme = max(c2["high"], c3["high"])
            return _make_result("DARK_CLOUD_COVER", "SELL", entry, extreme, atr)

    # ---------------- NHOM 1 NEN ----------------

    # HAMMER: sau xu huong giam, than nho o phan tren, bong duoi dai (>=2x than)
    if trend == "DOWN":
        body = _body(c3)
        if body > 0 and _lower_wick(c3) >= 2 * body and _upper_wick(c3) <= 0.3 * body:
            extreme = c3["low"]
            return _make_result("HAMMER", "BUY", entry, extreme, atr)

    # SHOOTING STAR: sau xu huong tang, than nho o phan duoi, bong tren dai (>=2x than)
    if trend == "UP":
        body = _body(c3)
        if body > 0 and _upper_wick(c3) >= 2 * body and _lower_wick(c3) <= 0.3 * body:
            extreme = c3["high"]
            return _make_result("SHOOTING_STAR", "SELL", entry, extreme, atr)

    # DOJI: than cuc nho so voi bien do nen, chi xet khi co xu huong ro rang truoc do (nen dao chieu)
    if _body(c3) <= 0.1 * _range(c3):
        if trend == "DOWN":
            extreme = c3["low"]
            return _make_result("DOJI_BULLISH_REVERSAL", "BUY", entry, extreme, atr)
        if trend == "UP":
            extreme = c3["high"]
            return _make_result("DOJI_BEARISH_REVERSAL", "SELL", entry, extreme, atr)

    return None
