# bot_xutho4/ai_v5/data/feature_engine.py
import numpy as np
import pandas as pd
from ai_v5.data.feature_schema import FEATURE_COLUMNS, encode_pattern, encode_regime, encode_source_type

def calculate_rsi(prices, period=14):
    """Tính toán chỉ báo RSI cơ bản từ danh sách giá"""
    if len(prices) < period + 1:
        return 50.0
    deltas = np.diff(prices)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    if down == 0:
        return 100.0
    rs = up / down
    rsi = np.zeros_like(prices)
    rsi[:period] = 100. - 100. / (1. + rs)

    for i in range(period, len(prices)):
        delta = deltas[i - 1]
        if delta > 0:
            upval = delta
            downval = 0.
        else:
            upval = 0.
            downval = -delta
        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        if down == 0:
            rsi[i] = 100.
        else:
            rs = up / down
            rsi[i] = 100. - 100. / (1. + rs)
    return float(rsi[-1])

def calculate_atr(candles, period=14):
    """Tính toán chỉ báo ATR để đo lường biến động (Volatility)"""
    if len(candles) < period + 1:
        return 0.0
    tr_list = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i-1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)
    return float(pd.Series(tr_list).rolling(period).mean().iloc[-1])

def extract_features_from_signal(signal_obj) -> dict:
    """
    Trich xuat cac dac trung ky thuat (Features) tu doi tuong tin hieu cua bot v4.
    Tra ve dung schema HOP NHAT (feature_schema.py) de tuong thich voi cac mau
    du lieu GEOMETRIC_PATTERN sinh boi pipeline/build_dataset.py.
    """
    features = {}
    candles = signal_obj.candles_context
    close_prices = [c["close"] for c in candles]

    # Nguon du lieu: day la tin hieu song cua bot v4
    features["source_type_encoded"] = encode_source_type("V4_SIGNAL")

    # 1. Dac trung xu huong & dong luong (Trend & Momentum)
    features["rsi_14"] = calculate_rsi(close_prices, 14)
    features["volume_ratio"] = float(signal_obj.volume_ratio)

    # 2. Dac trung bien dong gia (Volatility)
    atr = calculate_atr(candles, 14)
    features["atr_value"] = atr

    # 3. Che do thi truong (regime) va ADX - lay tu signal_obj.extra neu co (do watcher/analysis gan vao),
    #    neu khong co thi mac dinh UNKNOWN/25.0 de khong lam gay pipeline.
    extra = getattr(signal_obj, "extra", {}) or {}
    features["regime_type_encoded"] = encode_regime(extra.get("regime_type", "UNKNOWN"))
    features["adx_value"] = float(extra.get("adx_value", 25.0))

    # 4. Dac trung cau truc SMC (Smart Money Concepts)
    # Khoang cach tu diem vao lenh toi vung Zone (tinh bang % gia)
    if signal_obj.zone_price and signal_obj.price:
        features["distance_to_zone_pct"] = float(abs(signal_obj.price - signal_obj.zone_price) / signal_obj.price * 100)
    else:
        features["distance_to_zone_pct"] = 0.0

    # Ma hoa Pattern (dung chung bang ma voi GEOMETRIC_PATTERN) thanh so nguyen
    features["pattern_encoded"] = encode_pattern(signal_obj.pattern)

    # 5. Trich xuat dac trung thoi gian (Temporal)
    # Chuyen doi timestamp sang gio Viet Nam de mo hinh hoc thoi quen thi truong theo phien
    try:
        from datetime import datetime, timezone, timedelta
        utc_time = datetime.fromtimestamp(signal_obj.time, tz=timezone.utc)
        vn_time = utc_time + timedelta(hours=7)
        features["hour_of_day"] = vn_time.hour
        features["day_of_week"] = vn_time.weekday()  # 0: Thu 2, 6: Chu nhat
    except Exception:
        features["hour_of_day"] = 0
        features["day_of_week"] = 0

    # Dam bao dien day du gia tri mac dinh cho cac cot con thieu
    for col in FEATURE_COLUMNS:
        if col not in features:
            features[col] = 0.0

    return features