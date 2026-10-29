# ai_v6/live/vsa_v6.py
"""
VSA - SUA LOI DINH NGHIA cua ai_v5/pipeline/vsa_patterns.py (giu nguyen TEN pattern, dau ra, nguong spread/volume goc).

LOI GOC (da chay thu):
  - SELLING_CLIMAX / BUYING_CLIMAX khong yeu cau gia DONG CUA XA CUC TRI. Nen giam rong + volume lon nhung DONG SAT DAY la ap luc ban that
    (tiep dien giam), khong phai kiet suc; code van vao BUY nguoc chieu ngay tren nen do.
  - NO_DEMAND / NO_SUPPLY va cac Climax khong kiem tra BOI CANH: No Demand (nen tang yeu) chi co nghia sau mot dot TANG, No Supply sau mot dot GIAM,
    Selling Climax o day xu huong giam, Buying Climax o dinh xu huong tang. Code bao ca khi gia dang di nguoc boi canh.
  - No Demand/No Supply theo VSA con yeu cau volume THAP HON 2 nen truoc (khong chi thap hon trung binh 20 nen).

SUA: them boi canh (dot di truoc >= MIN_PRIOR_MOVE_ATR x ATR trong PRIOR_LOOKBACK nen), vi tri dong cua, va volume < 2 nen truoc cho No Demand/Supply.
Cac nguong (0.5 ATR, close 0.4/0.6) la GIA TRI TAM can hieu chuan bang pattern_lab_v6.py.
"""
SL_BUFFER_ATR = 0.3
REWARD_RISK_RATIO = 1.5
NARROW_SPREAD_RATIO = 0.7
WIDE_SPREAD_RATIO = 1.5
LOW_VOLUME_RATIO = 0.7
HIGH_VOLUME_RATIO = 2.0
STOPPING_VOLUME_RATIO = 2.5
CLOSE_POSITION_THRESHOLD = 0.3
PRIOR_LOOKBACK = 5
MIN_PRIOR_MOVE_ATR = 0.5
CLIMAX_CLOSE_MIN = 0.4      # Selling Climax: dong cua >= 40% bien do tu day (khong sat day)
CLIMAX_CLOSE_MAX = 0.6      # Buying Climax: dong cua <= 60% bien do tu day (khong sat dinh)


def _spread(c):
    return max(c["high"] - c["low"], 1e-9)


def _result(pattern, direction, entry, extreme, atr):
    buffer = SL_BUFFER_ATR * atr
    if direction == "BUY":
        sl = extreme - buffer
        tp = entry + REWARD_RISK_RATIO * (entry - sl)
    else:
        sl = extreme + buffer
        tp = entry - REWARD_RISK_RATIO * (sl - entry)
    return {"pattern": pattern, "direction": direction, "sl": float(sl), "tp": float(tp)}


def detect_vsa_patterns_v6(candles: list, avg_volume: float, atr: float):
    """candles: >= PRIOR_LOOKBACK+3 nen gan nhat (tang dan), nen cuoi la nen DA DONG gan nhat."""
    if len(candles) < PRIOR_LOOKBACK + 3 or atr <= 0 or avg_volume <= 0:
        return None
    c, p1, p2 = candles[-1], candles[-2], candles[-3]
    spread = _spread(c)
    volume = c.get("volume", 0) or 0
    entry = c["close"]
    bull, bear = c["close"] > c["open"], c["close"] < c["open"]
    close_pos = (c["close"] - c["low"]) / spread
    spread_ratio, volume_ratio = spread / atr, volume / avg_volume
    prior = candles[-2]["close"] - candles[-2 - PRIOR_LOOKBACK]["close"]
    up_ctx, down_ctx = prior >= MIN_PRIOR_MOVE_ATR * atr, prior <= -MIN_PRIOR_MOVE_ATR * atr
    quieter = volume < min(p1.get("volume", 0) or 0, p2.get("volume", 0) or 0)

    if bear and down_ctx and spread_ratio >= WIDE_SPREAD_RATIO and volume_ratio >= STOPPING_VOLUME_RATIO \
            and close_pos >= 1 - CLOSE_POSITION_THRESHOLD:
        return _result("VSA_STOPPING_VOLUME_BUY", "BUY", entry, c["low"], atr)
    if bull and up_ctx and spread_ratio >= WIDE_SPREAD_RATIO and volume_ratio >= STOPPING_VOLUME_RATIO \
            and close_pos <= CLOSE_POSITION_THRESHOLD:
        return _result("VSA_STOPPING_VOLUME_SELL", "SELL", entry, c["high"], atr)
    if bear and down_ctx and spread_ratio >= WIDE_SPREAD_RATIO and volume_ratio >= HIGH_VOLUME_RATIO and close_pos >= CLIMAX_CLOSE_MIN:
        return _result("VSA_SELLING_CLIMAX", "BUY", entry, c["low"], atr)
    if bull and up_ctx and spread_ratio >= WIDE_SPREAD_RATIO and volume_ratio >= HIGH_VOLUME_RATIO and close_pos <= CLIMAX_CLOSE_MAX:
        return _result("VSA_BUYING_CLIMAX", "SELL", entry, c["high"], atr)
    if bull and up_ctx and spread_ratio <= NARROW_SPREAD_RATIO and volume_ratio <= LOW_VOLUME_RATIO and quieter:
        return _result("VSA_NO_DEMAND", "SELL", entry, c["high"], atr)
    if bear and down_ctx and spread_ratio <= NARROW_SPREAD_RATIO and volume_ratio <= LOW_VOLUME_RATIO and quieter:
        return _result("VSA_NO_SUPPLY", "BUY", entry, c["low"], atr)
    return None
