# ai_v5/pipeline/swing_detector.py
"""
Bo phat hien diem Dinh/Day cau truc (Swing High/Low) tu du lieu nen OHLC.
Dung fractal co dien: 1 nen la Dinh (HIGH) neu 'high' cua no lon hon
'left_bars' nen truoc va 'right_bars' nen sau; tuong tu cho Day (LOW).

Duoc dung boi build_dataset.py de dung cau truc gia lich su, lam dau vao
cho pattern_rules.detect_16_patterns().
"""
import pandas as pd


def find_swing_points(df_rates: pd.DataFrame, left_bars: int = 5, right_bars: int = 5) -> list:
    """
    Input:
        df_rates: DataFrame co cot 'high', 'low' (va 'time' neu co, se duoc giu lai).
        left_bars / right_bars: so nen ben trai/phai can thap/cao hon de xac nhan fractal.
    Output:
        List cac dict {'index': int, 'price': float, 'type': 'HIGH'|'LOW', 'time': ...}
        duoc sap xep theo thu tu thoi gian tang dan (index tang dan).
    """
    swings = []
    n = len(df_rates)
    if n < left_bars + right_bars + 1:
        return swings

    highs = df_rates["high"].values
    lows = df_rates["low"].values
    has_time = "time" in df_rates.columns

    for i in range(left_bars, n - right_bars):
        window_high = highs[i - left_bars : i + right_bars + 1]
        window_low = lows[i - left_bars : i + right_bars + 1]

        # Dinh: gia cao nhat trong ca so nam dung tai vi tri i (va la duy nhat / dau tien dat max)
        if highs[i] == window_high.max():
            swings.append({
                "index": i,
                "price": float(highs[i]),
                "type": "HIGH",
                "time": df_rates["time"].iloc[i] if has_time else None,
            })
        # Day: gia thap nhat trong ca so nam dung tai vi tri i
        elif lows[i] == window_low.min():
            swings.append({
                "index": i,
                "price": float(lows[i]),
                "type": "LOW",
                "time": df_rates["time"].iloc[i] if has_time else None,
            })

    return swings
