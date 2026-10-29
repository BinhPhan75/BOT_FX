# ai_v5/pipeline/divergence_patterns.py
"""
Bo phat hien Phan ky (Divergence) giua Gia va chi bao dao dong (RSI hoac MACD).
4 loai: Regular Bullish/Bearish (bao hieu DAO CHIEU) va Hidden Bullish/Bearish
(bao hieu TIEP DIEN xu huong hien tai).

Quy uoc dau ra GIONG HET cac module pattern khac de build_dataset.py goi
thong nhat: {"pattern": str, "direction": "BUY"|"SELL", "sl": float, "tp": float}
hoac None neu khong khop.

Cach dung: tinh truoc 1 chuoi chi bao (RSI hoac MACD line) cho toan bo lich
su bang compute_rsi_series()/compute_macd_series(), roi goi detect_divergence()
tai tung buoc quet, truyen vao gia tri chi bao hien tai + toan bo chuoi de
tra cuu gia tri tai diem Swing gan nhat.
"""
import pandas as pd

SL_BUFFER_ATR = 0.3
REWARD_RISK_RATIO = 1.5


def compute_rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI kieu Wilder, vector hoa cho toan bo chuoi gia (dung Exponential Weighted thay vi vong lap)."""
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.ewm(alpha=1 / period, adjust=False).mean()
    roll_down = down.ewm(alpha=1 / period, adjust=False).mean().replace(0, 1e-9)
    rs = roll_up / roll_down
    return 100 - (100 / (1 + rs))


def compute_macd_series(close: pd.Series, fast: int = 12, slow: int = 26) -> pd.Series:
    """Duong MACD (EMA nhanh - EMA cham), dung truc tiep de so sanh Phan ky (khong can Signal line)."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    return ema_fast - ema_slow


def detect_divergence(swings_before: list, current_price: float, current_indicator_value: float,
                       indicator_series: pd.Series, atr: float, indicator_name: str) -> dict:
    """
    swings_before: danh sach Dinh/Day da xac nhan (dung swings tho tu find_swing_points, chua can loc lon).
    current_indicator_value: gia tri RSI hoac MACD tai buoc quet hien tai.
    indicator_series: toan bo chuoi RSI/MACD (dung de tra cuu gia tri tai diem Swing gan nhat).
    indicator_name: "RSI" hoac "MACD" - dung de dat ten pattern dung theo PATTERN_ENCODING.
    """
    if not swings_before or atr <= 0 or pd.isna(current_indicator_value):
        return None

    last_swing = swings_before[-1]
    idx = last_swing["index"]
    if idx < 0 or idx >= len(indicator_series):
        return None
    ind_at_swing = indicator_series.iloc[idx]
    if pd.isna(ind_at_swing):
        return None

    entry = current_price
    pattern = None
    direction = None
    sl = None

    if last_swing["type"] == "LOW":
        if current_price < last_swing["price"] and current_indicator_value > ind_at_swing:
            # Gia tao Day thap hon, nhung chi bao lai cao hon -> Phan ky Thuong (dao chieu tang)
            pattern = f"{indicator_name}_BULLISH_DIVERGENCE_REGULAR"
            direction = "BUY"
        elif current_price > last_swing["price"] and current_indicator_value < ind_at_swing:
            # Gia tao Day cao hon (chua pha day cu), chi bao lai thap hon -> Phan ky An (tiep dien tang)
            pattern = f"{indicator_name}_BULLISH_DIVERGENCE_HIDDEN"
            direction = "BUY"
        if direction == "BUY":
            extreme = min(current_price, last_swing["price"])
            sl = extreme - SL_BUFFER_ATR * atr
    else:  # HIGH
        if current_price > last_swing["price"] and current_indicator_value < ind_at_swing:
            # Gia tao Dinh cao hon, nhung chi bao lai thap hon -> Phan ky Thuong (dao chieu giam)
            pattern = f"{indicator_name}_BEARISH_DIVERGENCE_REGULAR"
            direction = "SELL"
        elif current_price < last_swing["price"] and current_indicator_value > ind_at_swing:
            # Gia tao Dinh thap hon (chua pha dinh cu), chi bao lai cao hon -> Phan ky An (tiep dien giam)
            pattern = f"{indicator_name}_BEARISH_DIVERGENCE_HIDDEN"
            direction = "SELL"
        if direction == "SELL":
            extreme = max(current_price, last_swing["price"])
            sl = extreme + SL_BUFFER_ATR * atr

    if direction is None:
        return None

    risk = abs(entry - sl)
    if risk <= 0:
        return None
    tp = entry + REWARD_RISK_RATIO * risk if direction == "BUY" else entry - REWARD_RISK_RATIO * risk

    return {"pattern": pattern, "direction": direction, "sl": float(sl), "tp": float(tp)}
