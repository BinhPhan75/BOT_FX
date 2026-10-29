# ai_v6/live/candlestick_v6.py
"""
Bo nhan dien nen Nhat ai_v6 - SUA cac loi DINH NGHIA cua ai_v5/pipeline/candlestick_patterns.py
(giu nguyen TEN pattern + format dau ra de pattern_encoded/feature_builder van dung duoc).

LOI DA XAC NHAN BANG CACH CHAY THAT code goc voi cac truong hop sach giao khoa (xem test_candlestick_v6.py):

 1. PIERCING_LINE / DARK_CLOUD_COVER doi "gap" (open nen 3 < close nen 2 / open > close nen 2) - nhung
    thi truong 24h (XAUUSD M5) gan nhu khong co gap: open ~ close nen truoc. Ket qua: mau hinh dung sach
    giao khoa BI BO SOT khi open == close truoc, va chi khop khi open lech vai cent NGAU NHIEN.
    => thay bang dung sai theo ATR (GAP_TOL_ATR): open <= close_truoc + tol.
 2. Mau hinh DAO CHIEU (Morning/Evening Star, Engulfing, Piercing, Dark Cloud) khong kiem tra con song
    truoc do (bien `trend` chi duoc dung cho nen don) => khop ca khi mau hinh KHONG xuat hien sau xu huong.
    => doi hoi con song truoc mau hinh di NGUOC chieu tin hieu >= MIN_PRIOR_MOVE_ATR x ATR
    (dung ban chat "pullback roi tiep dien theo bias M15" ma bot dang khai thac).
 3. Khong co nguong than nen toi thieu: nen vi mo 0.04$ tren nen ATR 4$ van duoc coi la Engulfing.
    => than nen >= MIN_BODY_ATR x ATR, bien do nen don >= MIN_RANGE_ATR x ATR.
 4. `_local_trend` (nen don) chi so 2 gia dong cua cach nhau 3 nen (15 phut M5) va gan nhu luon ra UP/DOWN
    (FLAT chi khi bang nhau tuyet doi) => thay bang con song PRIOR_LOOKBACK nen co nguong ATR.

LUU Y TRUNG THUC: cac nguong (0.30/0.60/0.10/0.50 ATR, lookback 5) la GIA TRI TAM theo tinh than "mau hinh
phai co y nghia", CHUA toi uu bang du lieu. Can do bang dataset da sua lookahead (xem README). Co the TAT tung bo
loc bang REQUIRE_CONTEXT / dat nguong = 0 de so sanh (ablation).

Input: candles list dict {open,high,low,close}, tang dan theo thoi gian, candles[-1] la nen DA DONG gan nhat.
Output: {"pattern","direction","sl","tp"} hoac None (giong detect_candlestick_patterns cua ai_v5).
"""

REWARD_RISK_RATIO = 1.5

MIN_BODY_ATR = 0.30        # than nen co y nghia toi thieu (ATR = TB (high-low) 14 nen M5, giong ai_v5 scanner)
MIN_RANGE_ATR = 0.60       # bien do toi thieu cua nen don (Hammer/Shooting Star/Doji)
GAP_TOL_ATR = 0.10         # dung sai thay cho "gap" (thi truong 24h gan nhu khong co gap that)
PRIOR_LOOKBACK = 5         # so nen xet con song TRUOC mau hinh
MIN_PRIOR_MOVE_ATR = 0.50  # con song truoc phai di nguoc chieu tin hieu it nhat 0.5 ATR
REQUIRE_CONTEXT = True     # False = bo kiem tra con song truoc (de ablation)


def _body(c):
    return abs(c["close"] - c["open"])


def _range(c):
    return max(c["high"] - c["low"], 1e-9)


def _bull(c):
    return c["close"] > c["open"]


def _bear(c):
    return c["close"] < c["open"]


def _upper_wick(c):
    return c["high"] - max(c["open"], c["close"])


def _lower_wick(c):
    return min(c["open"], c["close"]) - c["low"]


def _mid(c):
    return (c["open"] + c["close"]) / 2


def _result(pattern, direction, entry, extreme, atr):
    buffer = 0.3 * atr
    if direction == "BUY":
        sl = extreme - buffer
        tp = entry + REWARD_RISK_RATIO * (entry - sl)
    else:
        sl = extreme + buffer
        tp = entry - REWARD_RISK_RATIO * (sl - entry)
    return {"pattern": pattern, "direction": direction, "sl": float(sl), "tp": float(tp)}


def _prior_move(candles, n_pattern):
    """Bien dong gia (close) trong PRIOR_LOOKBACK nen NGAY TRUOC nen dau tien cua mau hinh n_pattern nen."""
    end = candles[-(n_pattern + 1)]["close"]
    start = candles[-(n_pattern + 1 + PRIOR_LOOKBACK)]["close"]
    return end - start


def _context_ok(direction, prior, atr):
    if not REQUIRE_CONTEXT:
        return True
    need = MIN_PRIOR_MOVE_ATR * atr
    return prior <= -need if direction == "BUY" else prior >= need


def detect_candlestick_patterns_v6(candles: list, atr: float):
    if len(candles) < PRIOR_LOOKBACK + 4 or atr <= 0:
        return None

    c1, c2, c3 = candles[-3], candles[-2], candles[-1]
    entry = c3["close"]
    min_body = MIN_BODY_ATR * atr
    tol = GAP_TOL_ATR * atr
    pm3, pm2, pm1 = _prior_move(candles, 3), _prior_move(candles, 2), _prior_move(candles, 1)

    # ---------------- 3 NEN ----------------
    # MORNING STAR
    if _bear(c1) and _body(c1) > 0.5 * _range(c1) and _body(c1) >= min_body:
        if _body(c2) < 0.4 * _body(c1) and _bull(c3) and _body(c3) >= min_body and c3["close"] > _mid(c1) \
                and _context_ok("BUY", pm3, atr):
            return _result("MORNING_STAR", "BUY", entry, min(c1["low"], c2["low"], c3["low"]), atr)

    # EVENING STAR
    if _bull(c1) and _body(c1) > 0.5 * _range(c1) and _body(c1) >= min_body:
        if _body(c2) < 0.4 * _body(c1) and _bear(c3) and _body(c3) >= min_body and c3["close"] < _mid(c1) \
                and _context_ok("SELL", pm3, atr):
            return _result("EVENING_STAR", "SELL", entry, max(c1["high"], c2["high"], c3["high"]), atr)

    # THREE WHITE SOLDIERS / THREE BLACK CROWS (tiep dien dong luong - giu logic goc, them than toi thieu)
    if _bull(c1) and _bull(c2) and _bull(c3) and min(_body(c1), _body(c2), _body(c3)) >= min_body:
        if c2["close"] > c1["close"] and c3["close"] > c2["close"] and c2["open"] > c1["open"] and c3["open"] > c2["open"]:
            return _result("THREE_WHITE_SOLDIERS", "BUY", entry, c1["low"], atr)
    if _bear(c1) and _bear(c2) and _bear(c3) and min(_body(c1), _body(c2), _body(c3)) >= min_body:
        if c2["close"] < c1["close"] and c3["close"] < c2["close"] and c2["open"] < c1["open"] and c3["open"] < c2["open"]:
            return _result("THREE_BLACK_CROWS", "SELL", entry, c1["high"], atr)

    # ---------------- 2 NEN ----------------
    # ENGULFING (dung sai thay cho gap)
    if _bear(c2) and _bull(c3) and _body(c3) >= min_body and _context_ok("BUY", pm2, atr):
        if c3["open"] <= c2["close"] + tol and c3["close"] >= c2["open"]:
            return _result("BULLISH_ENGULFING", "BUY", entry, min(c2["low"], c3["low"]), atr)
    if _bull(c2) and _bear(c3) and _body(c3) >= min_body and _context_ok("SELL", pm2, atr):
        if c3["open"] >= c2["close"] - tol and c3["close"] <= c2["open"]:
            return _result("BEARISH_ENGULFING", "SELL", entry, max(c2["high"], c3["high"]), atr)

    # PIERCING LINE: nen 3 dong TREN 50% than nen 2 nhung DUOI open nen 2
    if _bear(c2) and _bull(c3) and _body(c2) >= min_body and _body(c3) >= min_body and _context_ok("BUY", pm2, atr):
        if c3["open"] <= c2["close"] + tol and _mid(c2) < c3["close"] < c2["open"]:
            return _result("PIERCING_LINE", "BUY", entry, min(c2["low"], c3["low"]), atr)

    # DARK CLOUD COVER
    if _bull(c2) and _bear(c3) and _body(c2) >= min_body and _body(c3) >= min_body and _context_ok("SELL", pm2, atr):
        if c3["open"] >= c2["close"] - tol and c2["open"] < c3["close"] < _mid(c2):
            return _result("DARK_CLOUD_COVER", "SELL", entry, max(c2["high"], c3["high"]), atr)

    # ---------------- 1 NEN ----------------
    rng3 = _range(c3)
    if rng3 >= MIN_RANGE_ATR * atr:
        body = _body(c3)
        if body > 0 and _context_ok("BUY", pm1, atr) and _lower_wick(c3) >= 2 * body and _upper_wick(c3) <= 0.3 * body:
            return _result("HAMMER", "BUY", entry, c3["low"], atr)
        if body > 0 and _context_ok("SELL", pm1, atr) and _upper_wick(c3) >= 2 * body and _lower_wick(c3) <= 0.3 * body:
            return _result("SHOOTING_STAR", "SELL", entry, c3["high"], atr)
        if body <= 0.1 * rng3:
            if _context_ok("BUY", pm1, atr):
                return _result("DOJI_BULLISH_REVERSAL", "BUY", entry, c3["low"], atr)
            if _context_ok("SELL", pm1, atr):
                return _result("DOJI_BEARISH_REVERSAL", "SELL", entry, c3["high"], atr)
    return None
