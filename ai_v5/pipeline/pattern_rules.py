# ai_v5/pipeline/pattern_rules.py
"""
---------------------------------------------------------------------------
BẢN VÁ (FIX #3, mới): 2 mẫu hình BEARISH_RISING_WEDGE và BEARISH_FLAG tính
TP theo công thức "current_price - (p2 - p1)". Vì p2 (đáy, xuất hiện SAU
p1-đỉnh) gần như luôn NHỎ HƠN p1, nên (p2 - p1) mang dấu ÂM, khiến công thức
thực chất trở thành "current_price + |p1-p2|" — TP bị đặt CAO HƠN entry, sai
phía cho 1 lệnh SELL (TP đúng phải THẤP hơn entry). Đây là lỗi đảo dấu khi
copy công thức từ mẫu BUY tương ứng (BULLISH_FALLING_WEDGE/BULLISH_FLAG)
sang mà quên đổi lại thứ tự phép trừ.

Vì lớp phòng vệ R:R (dùng abs() cả 2 vế) KHÔNG phát hiện được lỗi sai PHÍA
(chỉ phát hiện sai TỶ LỆ), đã thêm thêm 1 lớp kiểm tra mới trong
detect_16_patterns(): xác nhận TP nằm ĐÚNG PHÍA so với entry theo direction,
độc lập với việc kiểm tra tỷ lệ R:R.
---------------------------------------------------------------------------
"""
import numpy as np

def _detect_16_patterns_raw(swings: list, current_price: float, atr: float) -> dict:
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
                        "tp": current_price - (p1['price'] - neckline)  # Neo tu gia vao lenh thuc te
                    }
            # Nếu chỉ có 2 đỉnh -> DOUBLE TOP
            elif p5['type'] == 'LOW': 
                neckline = p2['price']
                if current_price < neckline:
                    return {
                        "pattern": "DOUBLE_TOP",
                        "direction": "SELL",
                        "sl": max(p1['price'], p3['price']) + threshold,
                        "tp": current_price - (p1['price'] - neckline)  # Neo tu gia vao lenh thuc te
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
                        "tp": current_price + (neckline - p1['price'])  # Neo tu gia vao lenh thuc te
                    }
            # Hai đáy -> DOUBLE BOTTOM
            elif p5['type'] == 'HIGH':
                neckline = p2['price']
                if current_price > neckline:
                    return {
                        "pattern": "DOUBLE_BOTTOM",
                        "direction": "BUY",
                        "sl": min(p1['price'], p3['price']) - threshold,
                        "tp": current_price + (neckline - p1['price'])  # Neo tu gia vao lenh thuc te
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
                        "tp": current_price - (p3['price'] - neckline)  # Neo tu gia vao lenh thuc te
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
                        "tp": current_price + (neckline - p3['price'])  # Neo tu gia vao lenh thuc te
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
                        # FIX #3: công thức gốc "current_price - (p2 - p1)" bị đảo dấu (p2<p1 => TP
                        # nằm CAO hơn entry, sai phía cho lệnh SELL). Sửa thành "- (p1 - p2)" để TP
                        # nằm đúng phía DƯỚI entry, nhất quán với BULLISH_FALLING_WEDGE.
                        "tp": current_price - (p1['price'] - p2['price'])
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
                        # FIX #3: cùng lỗi đảo dấu như BEARISH_RISING_WEDGE ở trên, sửa tương tự.
                        "tp": current_price - (p1['price'] - p2['price']) * 1.5
                    }

    return None


# ============================================================
# BAN VA (sau su co lenh that GBPUSDc R:R chi 1:0.2): mot so mau
# hinh (dac biet la Wedge) tinh do lon TP tu 1 "chan song" doc lap
# voi khoang cach SL (dua tren dinh/day khac) - neu chan song do
# tinh ra qua nho/nhieu, TP bi co lai gan bang 0 trong khi SL van
# giu nguyen khoang cach lon, gay ra ty le R:R meo mo nghiem trong.
# Bo boc ben duoi kiem tra LAI tat ca 16 mau hinh sau khi tinh
# xong, tu dong sua TP neu ty le qua thap.
#
# FIX #3 (moi): them kiem tra TP dung PHIA so voi entry theo direction -
# lop kiem tra R:R cu chi dung abs() nen KHONG phat hien duoc truong hop
# TP nam sai phia hoan toan (da xac nhan xay ra that voi BEARISH_RISING_WEDGE/
# BEARISH_FLAG do loi dao dau trong _detect_16_patterns_raw). Da sua tan goc
# 2 cong thuc do, nhung van giu them lop kiem tra nay o day nhu 1 tang phong
# ve doc lap, phong truong hop phat sinh loi tuong tu o mau hinh khac trong
# tuong lai (vi du khi them mau hinh moi sau nay).
# ============================================================

MIN_ACCEPTABLE_REWARD_RISK_RATIO = 0.8
REWARD_RISK_RATIO_FLOOR = 1.5


def detect_16_patterns(swings: list, current_price: float, atr: float) -> dict:
    """
    Bo boc ngoai _detect_16_patterns_raw(): dam bao khong bao gio tra ve 1
    tin hieu co ty le R:R phi thuc te (da xac nhan xay ra that voi
    BEARISH_RISING_WEDGE tren GBPUSDc - R:R chi 1:0.2 thay vi 1:1.5 thiet ke),
    VA khong bao gio tra ve TP nam SAI PHIA so voi entry (FIX #3).
    """
    match = _detect_16_patterns_raw(swings, current_price, atr)
    if match is None:
        return None

    entry = current_price
    sl = match["sl"]
    tp = match["tp"]
    direction = match["direction"]

    risk = abs(entry - sl)
    reward = abs(tp - entry)
    if risk <= 0:
        return match  # Khong the danh gia, giu nguyen (truong hop hiem, sl=entry)

    ratio = reward / risk
    if ratio < MIN_ACCEPTABLE_REWARD_RISK_RATIO:
        new_tp = (entry + REWARD_RISK_RATIO_FLOOR * risk) if direction == "BUY" else (entry - REWARD_RISK_RATIO_FLOOR * risk)
        match = dict(match)  # Tranh sua truc tiep dict tra ve tu ham raw
        match["tp"] = new_tp
        tp = new_tp

    # FIX #3: lop kiem tra doc lap - TP phai nam DUNG PHIA so voi entry theo direction.
    # BUY -> tp phai > entry. SELL -> tp phai < entry. Neu sai phia (bat ke ty le R:R
    # tinh ra co "hop ly" hay khong), TU DONG TINH LAI theo ty le floor an toan thay vi
    # dat lenh voi TP vo nghia.
    if (direction == "BUY" and tp <= entry) or (direction == "SELL" and tp >= entry):
        match = dict(match)
        match["tp"] = (entry + REWARD_RISK_RATIO_FLOOR * risk) if direction == "BUY" else (entry - REWARD_RISK_RATIO_FLOOR * risk)

    return match
