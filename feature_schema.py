# bot_xutho4/ai_v5/data/feature_schema.py

# Danh sách các đặc trưng dạng số mà mô hình ML sẽ sử dụng làm đầu vào
FEATURE_COLUMNS = [
    # 1. Thông tin cơ bản về tín hiệu
    "direction_num",         # BUY = 1, SELL = 0
    "volume_ratio",          # Tỷ lệ volume nến hiện tại so với trung bình 20 nến
    
    # 2. Đặc trưng động lượng & biến động tại thời điểm vào lệnh
    "atr_value",             # Giá trị ATR hiện tại (đo lường độ biến động)
    "atr_percent",           # ATR / Giá đóng cửa (chuẩn hóa biên độ dao động giữa các symbol)
    "candle_body_ratio",     # Tỷ lệ thân nến / toàn bộ chiều dài nến (độ mạnh của lực nến)
    
    # 3. Trạng thái các chỉ báo kỹ thuật của v4
    "ema_diff_percent",      # Khoảng cách % giữa EMA Fast và EMA Slow
    "st_trend_state",        # Xu hướng SuperTrend hiện tại (1: Bullish, -1: Bearish)
    
    # 4. Đặc trưng SMC & Cấu trúc thị trường
    "distance_to_zone_pct",  # Khoảng cách từ giá đóng cửa hiện tại tới zone_price (độ giãn SL)[cite: 1, 2]
    
    # 5. Thời gian (Tránh giao dịch các khung giờ thanh khoản kém hoặc biến động nhiễu)
    "hour_of_day",           # Giờ trong ngày (0 - 23)
    "day_of_week",           # Ngày trong tuần (0 - 4: Thứ 2 - Thứ 6)
]

# Nhãn mục tiêu (Target Label) để AI học
TARGET_COLUMN = "is_win"      # Lệnh thắng = 1, Lệnh thua = 0