# bot_xutho4/ai_v5/telegram/telegram_ai.py
import logging
import requests
from ai_v5.config_ai import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger("ai_telegram")

def send_ai_signal_notification(signal_data: dict, win_rate: float, decision: bool, explanation: str) -> bool:
    """
    Định dạng cấu trúc tin nhắn trực quan và gửi kết quả phân tích AI v5 về kênh Telegram.
    """
    if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN" or not TELEGRAM_BOT_TOKEN:
        logger.warning("Chưa cấu hình Telegram Bot Token trong config_ai.py. Bỏ qua gửi tin nhắn.")
        return False

    status_emoji = "🟢 APPROVE (DUYỆT LỆNH)" if decision else "🔴 REJECT (BỎ QUA)"
    action_text = "BUY" if "bullish" in signal_data.get("pattern", "").lower() else "SELL"
    
    # Thiết lập nội dung tin nhắn Markdown gọn gàng, scannable
    message = (
        f"🤖 *[AI v5 - SHADOW ANALYSIS]*\n"
        f"-------------------------------------\n"
        f"▪ *Cặp tiền:* {signal_data.get('symbol', 'N/A')}\n"
        f"▪ *Hành động:* {action_text}\n"
        f"▪ *Mẫu tín hiệu:* {signal_data.get('pattern', 'N/A')}\n"
        f"▪ *Khung thời gian:* {signal_data.get('timeframe', 'N/A')}\n"
        f"▪ *Giá Entry v4:* {signal_data.get('price', 0.0):.5f}\n"
        f"▪ *Vùng bảo vệ (Zone):* {signal_data.get('zone_price', 0.0):.5f}\n"
        f"-------------------------------------\n"
        f"📊 *ĐÁNH GIÁ CỦA AI:*\n"
        f"▪ *Xác suất thắng (Win Rate):* {win_rate:.1%}\n"
        f"▪ *Quyết định AI v5:*  *{status_emoji}*\n"
        f"-------------------------------------\n"
        f"💡 *Phân tích tư duy:* {explanation}\n\n"
        f"_*Lưu ý:* Hệ thống đang chạy Shadow Mode. Lệnh live của v4 không bị ảnh hưởng._"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info(f"Đã bắn tin nhắn phân tích AI về Telegram thành công.")
            return True
        else:
            logger.error(f"Lỗi từ Telegram API: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Không thể kết nối đến Telegram API: {str(e)}")
        return False

if __name__ == "__main__":
    # Test độc lập module Telegram
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("\n🔍 Đang chạy kiểm thử module thông báo Telegram...")
    
    mock_sig = {"symbol": "XAUUSD", "pattern": "smc_bullish_bos", "price": 2353.0, "zone_price": 2345.0, "timeframe": "H1"}
    mock_explain = "Tư duy chính dựa trên RSI ổn định ở mức 55.4."
    
    send_ai_signal_notification(mock_sig, 0.655, True, mock_explain)