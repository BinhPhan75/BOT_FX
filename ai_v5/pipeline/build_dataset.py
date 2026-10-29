# ============================================================
# BẢN VÁ #2 cho ai_v5/pipeline/build_dataset.py
# ============================================================
# THAY THẾ TOÀN BỘ hàm _load_candles_mt5() (đã được vá 1 lần trước đó để
# sửa bug "candles_to_copy = days_back * 96") bằng bản DƯỚI ĐÂY - gộp cả 2
# bản vá vào cùng 1 hàm. Mọi phần khác của file GIỮ NGUYÊN.
#
# LỖI MỚI ĐÃ SỬA: mt5.copy_rates_from_pos() trả về mảng có cột khối lượng
# tên là "tick_volume" (và "real_volume"), KHÔNG PHẢI "volume". Toàn bộ
# code còn lại của dự án (live_pattern_scanner.py, feature_builder.py,
# vsa_patterns.py...) đều tham chiếu candle["volume"] - ham
# mt5_client.get_candles() (dùng khi CHẠY LIVE) đã tự đổi tên cột này từ
# lâu nên live không bị ảnh hưởng, nhưng _load_candles_mt5() ở ĐÂY (chỉ
# dùng khi BUILD DATASET qua --source mt5) lại KHÔNG đổi tên -> cột
# "volume" không tồn tại trong DataFrame -> avg_volume_series = None trong
# generate_historical_dataset() -> avg_vol_i luôn = 0.0 -> detect_vsa_patterns()
# (yêu cầu avg_volume > 0) KHÔNG BAO GIỜ được kích hoạt trong suốt quá
# trình quét lịch sử -> dataset train THIẾU HẲN toàn bộ nhóm VSA_PATTERN,
# dù bot live vẫn quét và chấm điểm tín hiệu VSA bình thường (dùng
# mt5_client.get_candles() có cột "volume" đúng) -> LỆCH PHA TRAIN/LIVE
# nghiêm trọng cho riêng nhóm này.
# ============================================================

_BARS_PER_DAY = {
    "M1": 1440, "M5": 288, "M15": 96, "M30": 48,
    "H1": 24, "H4": 6, "D1": 1,
}


def _load_candles_mt5(symbol: str, timeframe: str, days_back: int) -> pd.DataFrame:
    """Ket noi truc tiep MT5 (chi chay duoc tren may Windows co terminal MT5 dang mo)."""
    import MetaTrader5 as mt5  # import cuc bo, tranh loi ImportError khi khong co MT5 (vd moi truong Linux/test)

    if not mt5.initialize():
        logger.error("❌ Không thể kết nối trực tiếp tới Terminal MT5 bằng thư viện gốc.")
        return pd.DataFrame()

    tf_mapping = {
        "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1,
    }
    mt5_tf = tf_mapping.get(timeframe.upper(), mt5.TIMEFRAME_M15)

    # BẢN VÁ #1: tính đúng số nến/ngày THEO TỪNG TIMEFRAME thay vì hard-code 96 (chỉ đúng cho M15).
    bars_per_day = _BARS_PER_DAY.get(timeframe.upper(), 96)
    candles_to_copy = int(days_back * bars_per_day)

    mt5.symbol_select(symbol, True)
    rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, candles_to_copy)
    if rates is None or len(rates) < 500:
        logger.warning(f"⚠️ Dữ liệu nến quá ngắn cho {symbol}.")
        return pd.DataFrame()

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")

    # BẢN VÁ #2: MT5 trả về cột "tick_volume" (không phải "volume") - đổi tên để
    # KHỚP ĐÚNG với dữ liệu mà mt5_client.get_candles() cung cấp khi chạy live,
    # tránh dataset train thiếu hẳn nhóm VSA_PATTERN (module này cần cột "volume"
    # để hoạt động, xem ai_v5/pipeline/vsa_patterns.py).
    if "tick_volume" in df.columns and "volume" not in df.columns:
        df["volume"] = df["tick_volume"]

    actual_days = (df["time"].max() - df["time"].min()).days if len(df) else 0
    logger.info(f"📂 Đã tải {len(df)} nến {timeframe} từ MT5 cho {symbol} "
                f"(yêu cầu ~{candles_to_copy} nến ~ {days_back} ngày, thực tế nhận được ~{actual_days} ngày "
                f"- nếu THẤP HƠN NHIỀU so với days_back yêu cầu, có thể do broker giới hạn lịch sử lưu trữ "
                f"cho khung {timeframe} trên tài khoản này, KHÔNG PHẢI lỗi code).")
    return df