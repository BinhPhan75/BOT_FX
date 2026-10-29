# ai_v5/pipeline/vsa_patterns.py
"""
Bo phat hien mau hinh Volume Spread Analysis (VSA) - phan tich moi quan he
giua Bien do nen (Spread) va Khoi luong (Volume) de tim dau hieu "Tien Thong
Minh" (Smart Money) dang hanh dong nguoc voi dam dong.

6 mau hinh:
    - NO_DEMAND / NO_SUPPLY: nen tang/giam voi Spread hep + Volume thap ->
      dau hieu YEU cua phe dang kiem soat, du bao dao chieu nguoc lai.
    - SELLING_CLIMAX / BUYING_CLIMAX: nen giam/tang voi Spread rong + Volume
      dot bien (kiet suc ban/mua) -> du bao dao chieu.
    - VSA_STOPPING_VOLUME_BUY / SELL: giong Climax nhung co xac nhan them
      bang vi tri dong cua (dong o 1/3 doi dien voi huong nen) -> tin hieu
      manh hon Climax thuong.

Quy uoc dau ra GIONG HET cac module pattern khac de build_dataset.py goi
thong nhat: {"pattern": str, "direction": "BUY"|"SELL", "sl": float, "tp": float}
hoac None neu khong khop.

Input candles: list cac dict {'open','high','low','close','volume'}, sap xep
tang dan theo thoi gian, candles[-1] la nen hien tai.
"""

SL_BUFFER_ATR = 0.3
REWARD_RISK_RATIO = 1.5

NARROW_SPREAD_RATIO = 0.7   # Spread < 0.7 x ATR duoc coi la "hep"
WIDE_SPREAD_RATIO = 1.5     # Spread > 1.5 x ATR duoc coi la "rong"
LOW_VOLUME_RATIO = 0.7      # Volume < 0.7 x Volume trung binh duoc coi la "thap"
HIGH_VOLUME_RATIO = 2.0     # Volume > 2.0 x Volume trung binh duoc coi la "cao dot bien"
STOPPING_VOLUME_RATIO = 2.5  # Nguong volume cao hon cho tin hieu Stopping Volume (manh hon Climax thuong)
CLOSE_POSITION_THRESHOLD = 0.3  # Dong cua nam trong 30% tren/duoi cua bien do nen


def _spread(c):
    return max(c["high"] - c["low"], 1e-9)


def _close_position(c):
    """Vi tri gia dong cua trong bien do nen: 0.0 = day nen (low), 1.0 = dinh nen (high)."""
    return (c["close"] - c["low"]) / _spread(c)


def _make_result(pattern, direction, entry, extreme, atr):
    buffer = SL_BUFFER_ATR * atr
    if direction == "BUY":
        sl = extreme - buffer
        risk = entry - sl
        tp = entry + REWARD_RISK_RATIO * risk
    else:
        sl = extreme + buffer
        risk = sl - entry
        tp = entry - REWARD_RISK_RATIO * risk
    return {"pattern": pattern, "direction": direction, "sl": float(sl), "tp": float(tp)}


def detect_vsa_patterns(candles: list, avg_volume: float, atr: float) -> dict:
    """
    candles: >= 2 nen gan nhat (sap xep tang dan). avg_volume: khoi luong trung binh
    tham chieu (vd trung binh 20 nen). atr: bien do trung binh hien tai.
    """
    if len(candles) < 2 or atr <= 0 or avg_volume <= 0:
        return None

    c = candles[-1]
    spread = _spread(c)
    volume = c.get("volume", 0) or 0
    entry = c["close"]
    is_bullish = c["close"] > c["open"]
    is_bearish = c["close"] < c["open"]
    close_pos = _close_position(c)

    spread_ratio = spread / atr
    volume_ratio = volume / avg_volume

    # ---- Uu tien kiem tra Stopping Volume (tin hieu manh, can xac nhan vi tri dong cua) ----
    if is_bearish and spread_ratio >= WIDE_SPREAD_RATIO and volume_ratio >= STOPPING_VOLUME_RATIO:
        if close_pos >= (1 - CLOSE_POSITION_THRESHOLD):  # Dong cua o 1/3 TREN (nguoc voi phe Ban) -> Nguoi mua hap thu het luc ban
            return _make_result("VSA_STOPPING_VOLUME_BUY", "BUY", entry, c["low"], atr)

    if is_bullish and spread_ratio >= WIDE_SPREAD_RATIO and volume_ratio >= STOPPING_VOLUME_RATIO:
        if close_pos <= CLOSE_POSITION_THRESHOLD:  # Dong cua o 1/3 DUOI (nguoc voi phe Mua) -> Nguoi ban hap thu het luc mua
            return _make_result("VSA_STOPPING_VOLUME_SELL", "SELL", entry, c["high"], atr)

    # ---- Selling Climax / Buying Climax (kiet suc, chua can xac nhan vi tri dong cua chat che) ----
    if is_bearish and spread_ratio >= WIDE_SPREAD_RATIO and volume_ratio >= HIGH_VOLUME_RATIO:
        return _make_result("VSA_SELLING_CLIMAX", "BUY", entry, c["low"], atr)

    if is_bullish and spread_ratio >= WIDE_SPREAD_RATIO and volume_ratio >= HIGH_VOLUME_RATIO:
        return _make_result("VSA_BUYING_CLIMAX", "SELL", entry, c["high"], atr)

    # ---- No Demand / No Supply (Spread hep + Volume thap -> phe kiem soat dang yeu) ----
    if is_bullish and spread_ratio <= NARROW_SPREAD_RATIO and volume_ratio <= LOW_VOLUME_RATIO:
        return _make_result("VSA_NO_DEMAND", "SELL", entry, c["high"], atr)

    if is_bearish and spread_ratio <= NARROW_SPREAD_RATIO and volume_ratio <= LOW_VOLUME_RATIO:
        return _make_result("VSA_NO_SUPPLY", "BUY", entry, c["low"], atr)

    return None
