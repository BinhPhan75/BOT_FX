# test_ai.py
import logging
from analysis import Signal
from ai_v5.shadow_runner import inspect_signal_shadow

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# 1. Giả lập một tín hiệu SMC Bullish BOS từ bot v4 sang
mock_candles = [
    {"time": 1710000000, "open": 2350.0, "high": 2355.0, "low": 2348.0, "close": 2353.0, "volume": 150}
] * 120  # Tạo đủ 120 nến bối cảnh để bộ trích xuất không bị thiếu dữ liệu

mock_signal = Signal(
    symbol="XAUUSD",
    pattern="smc_bullish_bos",
    price=2353.0,
    timeframe="H1",
    zone_price=2345.0,
    candles_context=mock_candles,
    time=1710000000,
    volume_ratio=1.5,
    extra={"signal_group": "smc"}
)

print("\n🚀 Đang kích hoạt thử nghiệm gửi tín hiệu giả lập sang AI v5 Shadow Runner...\n")
inspect_signal_shadow(mock_signal)
print("\n✅ Hoàn tất kiểm tra! Hãy xem log ở trên và kiểm tra điện thoại xem Telegram đã nổ tin nhắn phân tích chưa.")