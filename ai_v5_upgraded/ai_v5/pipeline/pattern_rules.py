# ai_v5/pipeline/pattern_rules.py
import numpy as np

def detect_16_patterns(swings: list, current_price: float, atr: float) -> dict:
    """
    Đầu vào: Danh sách đỉnh/đáy cấu trúc 'swings' gần nhất, giá hiện tại và ATR để tính sai số.
    Trả về: Dict thông tin mô hình phát hiện được kèm tọa độ SL/TP chuẩn lý thuyết.
    """
    if len(swings) < 5:
        return None
        
    # Lấy 5 điểm đảo chiều gần nhất (P1 xa nhất -> P5 gần nhất)
    p1, p2, p3, p4, p5 = swings[-5], swings[-4], swings[-3], swings[-2], swings[-1]
    
    # Định nghĩa sai số chấp nhận được dựa trên 10% ATR (ví dụ 1.5$ đối với Vàng)
    threshold = atr * 0.1
    
    # Tính toán các hiệu số để kiểm tra xu hướng của đỉnh/đáy
    # Nếu đỉnh/đáy sau cao hơn -> Up trend. Thấp hơn -> Down trend.
    
    # ----------------- NHÓM 1: REVERSAL (ĐẢO CHIỀU) -----------------
    
    # 1. Double Top (Hai Đỉnh) & Triple Top (Ba Đỉnh)
    if p1['type'] == 'HIGH' and p3['type'] == 'HIGH':
        # Hai đỉnh cao bằng nhau (P1 và P3)
        if abs(p1['price'] - p3['price']) <= threshold:
            # Nếu có thêm đỉnh thứ 3 (P5) bằng 2 đỉnh trước -> TRIPLE TOP
            if p5['type'] == 'HIGH' and abs(p3['price'] - p5['price']) <= threshold:
                neckline = min(p2['price'], p4['price'])
                if current_price < neckline: # Phá vỡ đường cổ
                    return {
                        "pattern": "TRIPLE_TOP",
                        "direction": "SELL",
                        "sl": max(p1['price'], p3['price'], p5['price']) + threshold,
                        "tp": neckline - (p1['price'] - neckline)
                    }
            # Nếu chỉ có 2 đỉnh -> DOUBLE TOP
            elif p5['type'] == 'LOW': 
                neckline = p2['price']
                if current_price < neckline:
                    return {
                        "pattern": "DOUBLE_TOP",
                        "direction": "SELL",
                        "sl": max(p1['price'], p3['price']) + threshold,
                        "tp": neckline - (p1['price'] - neckline)
                    }

    # 2. Double Bottom (Hai Đáy) & Triple Bottom (Ba Đáy)
    if p1['type'] == 'LOW' and p3['type'] == 'LOW':
        # Hai đáy thấp bằng nhau (P1 và P3)
        if abs(p1['price'] - p3['price']) <= threshold:
            # Ba đáy bằng nhau -> TRIPLE BOTTOM
            if p5['type'] == 'LOW' and abs(p3['price'] - p5['price']) <= threshold:
                neckline = max(p2['price'], p4['price'])
                if current_price > neckline:
                    return {
                        "pattern": "TRIPLE_BOTTOM",
                        "direction": "BUY",
                        "sl": min(p1['price'], p3['price'], p5['price']) - threshold,
                        "tp": neckline + (neckline - p1['price'])
                    }
            # Hai đáy -> DOUBLE BOTTOM
            elif p5['type'] == 'HIGH':
                neckline = p2['price']
                if current_price > neckline:
                    return {
                        "pattern": "DOUBLE_BOTTOM",
                        "direction": "BUY",
                        "sl": min(p1['price'], p3['price']) - threshold,
                        "tp": neckline + (neckline - p1['price'])
                    }

    # 3. Head & Shoulders (Vai Đầu Vai)
    # Cấu trúc đỉnh: Thấp (P1) -> Cao hẳn (P3) -> Thấp bằng P1 (P5)
    if p1['type'] == 'HIGH' and p3['type'] == 'HIGH' and p5['type'] == 'HIGH':
        if p3['price'] > p1['price'] and p3['price'] > p5['price']:
            if abs(p1['price'] - p5['price']) <= (threshold * 1.5): # 2 vai tương đương nhau
                neckline = min(p2['price'], p4['price'])
                if current_price < neckline:
                    return {
                        "pattern": "HEAD_AND_SHOULDERS",
                        "direction": "SELL",
                        "sl": p3['price'] + threshold,
                        "tp": neckline - (p3['price'] - neckline)
                    }

    # 4. Inverted Head & Shoulders (Vai Đầu Vai Ngược)
    # Cấu trúc đáy: Cao (P1) -> Thấp hẳn (P3) -> Cao bằng P1 (P5)
    if p1['type'] == 'LOW' and p3['type'] == 'LOW' and p5['type'] == 'LOW':
        if p3['price'] < p1['price'] and p3['price'] < p5['price']:
            if abs(p1['price'] - p5['price']) <= (threshold * 1.5):
                neckline = max(p2['price'], p4['price'])
                if current_price > neckline:
                    return {
                        "pattern": "INVERTED_HEAD_AND_SHOULDERS",
                        "direction": "BUY",
                        "sl": p3['price'] - threshold,
                        "tp": neckline + (neckline - p3['price'])
                    }

    # ----------------- NHÓM 2: CONTINUATION (TIẾP DIỄN) -----------------

    # 5. Ascending Triangle (Tam Giác Tăng)
    # Đỉnh bằng nhau (P1, P3, P5) nhưng Đáy nâng dần (P2 < P4)
    if p1['type'] == 'HIGH' and p3['type'] == 'HIGH':
        if abs(p1['price'] - p3['price']) <= threshold and p4['price'] > p2['price']:
            if current_price > p3['price']: # Breakout hướng lên
                return {
                    "pattern": "ASCENDING_TRIANGLE",
                    "direction": "BUY",
                    "sl": p4['price'] - threshold,
                    "tp": current_price + (p3['price'] - p2['price'])
                }

    # 6. Descending Triangle (Tam Giác Giảm)
    # Đáy bằng nhau (P1, p3, P5) nhưng Đỉnh hạ dần (P2 > P4)
    if p1['type'] == 'LOW' and p3['type'] == 'LOW':
        if abs(p1['price'] - p3['price']) <= threshold and p4['price'] < p2['price']:
            if current_price < p3['price']: # Breakout hướng xuống
                return {
                    "pattern": "DESCENDING_TRIANGLE",
                    "direction": "SELL",
                    "sl": p4['price'] + threshold,
                    "tp": current_price - (p2['price'] - p3['price'])
                }

    # 7. Symmetrical Triangle (Tam Giác Cân - Bullish / Bearish)
    # Đỉnh hạ dần (P1 > P3) và Đáy nâng dần (P2 < p4) -> Nén giá cực chặt
    if p1['type'] == 'HIGH' and p3['type'] == 'HIGH' and p2['type'] == 'LOW' and p4['type'] == 'LOW':
        if p1['price'] > p3['price'] and p2['price'] < p4['price']:
            # Phá đỉnh gần nhất -> Symmetrical Bullish
            if current_price > p3['price']:
                return {
                    "pattern": "BULLISH_SYMMETRICAL_TRIANGLE",
                    "direction": "BUY",
                    "sl": p4['price'] - threshold,
                    "tp": current_price + (p1['price'] - p2['price'])
                }
            # Phá đáy gần nhất -> Symmetrical Bearish
            elif current_price < p4['price']:
                return {
                    "pattern": "BEARISH_SYMMETRICAL_TRIANGLE",
                    "direction": "SELL",
                    "sl": p3['price'] + threshold,
                    "tp": current_price - (p1['price'] - p2['price'])
                }

    # 8. Bullish Wedge & Falling Wedge (Nêm Giảm/Nêm Tăng)
    # Đỉnh sau thấp hơn đỉnh trước, Đáy sau thấp hơn đáy trước nhưng biên độ hẹp dần
    if p1['type'] == 'HIGH' and p3['type'] == 'HIGH' and p2['type'] == 'LOW' and p4['type'] == 'LOW':
        # Độ dốc giảm dần (Nêm hướng xuống)
        if p1['price'] > p3['price'] and p2['price'] > p4['price']:
            # Chiều rộng sóng 1 (P1-P2) lớn hơn sóng 2 (P3-P4) -> Hội tụ nêm
            if (p1['price'] - p2['price']) > (p3['price'] - p4['price']):
                if current_price > p3['price']: # Phá vỡ nêm đi lên
                    return {
                        "pattern": "BULLISH_FALLING_WEDGE",
                        "direction": "BUY",
                        "sl": p4['price'] - threshold,
                        "tp": current_price + (p1['price'] - p2['price'])
                    }

        # Độ dốc tăng dần (Nêm hướng lên)
        if p1['price'] < p3['price'] and p2['price'] < p4['price']:
            if (p2['price'] - p1['price']) > (p4['price'] - p3['price']):
                if current_price < p4['price']: # Phá vỡ nêm đi xuống
                    return {
                        "pattern": "BEARISH_RISING_WEDGE",
                        "direction": "SELL",
                        "sl": p3['price'] + threshold,
                        "tp": current_price - (p2['price'] - p1['price'])
                    }

    # 9. Bullish Flag & Bearish Flag (Mô Hình Cờ)
    # Kênh giá tích lũy song song ngược chiều xu hướng mạnh trước đó
    if p1['type'] == 'HIGH' and p3['type'] == 'HIGH' and p2['type'] == 'LOW' and p4['type'] == 'LOW':
        # Cờ Tăng (Bullish Flag): Xu hướng trước tăng mạnh, kênh tích lũy dốc xuống nhẹ
        if p1['price'] > p3['price'] and p2['price'] > p4['price']:
            # Kênh song song (Độ rộng 2 sóng bằng nhau)
            if abs((p1['price'] - p2['price']) - (p3['price'] - p4['price'])) <= threshold:
                if current_price > p3['price']:
                    return {
                        "pattern": "BULLISH_FLAG",
                        "direction": "BUY",
                        "sl": p4['price'] - threshold,
                        "tp": current_price + (p1['price'] - p2['price']) * 1.5 # Cột cờ
                    }
        # Cờ Giảm (Bearish Flag)
        if p1['price'] < p3['price'] and p2['price'] < p4['price']:
            if abs((p2['price'] - p1['price']) - (p4['price'] - p3['price'])) <= threshold:
                if current_price < p4['price']:
                    return {
                        "pattern": "BEARISH_FLAG",
                        "direction": "SELL",
                        "sl": p3['price'] + threshold,
                        "tp": current_price - (p2['price'] - p1['price']) * 1.5
                    }

    return None