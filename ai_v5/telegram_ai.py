# bot_xutho4/ai_v5/telegram/telegram_ai.py
import logging
import requests
from ai_v5.config_ai import TELEGRAM_AI_TOKEN, TELEGRAM_AI_CHAT_ID

def send_ai_signal_notification(signal_obj, win_prob: float, decision: str):
    """
    Gửi tin nhắn phân tích tín hiệu Shadow Mode của AI v5 qua Telegram.
    """
    if not TELEGRAM_AI_TOKEN or not TELEGRAM_AI_CHAT_ID:
        logging.warning("Chưa cấu hình Telegram Bot Token hoặc Chat ID cho AI v5.")
        return

    symbol = signal_obj.symbol
    direction = "🟢 BUY" if "bullish" in signal_obj.pattern else "🔴 SELL"
    pattern = signal_obj.pattern
    entry = signal_obj.price
    zone = signal_obj.zone_price
    vol_ratio = signal_obj.volume_ratio

    # Định dạng trạng thái icon dựa trên quyết định của AI
    status_icon = "✅" if "APPROVE" in decision else "❌"
    
    # Tạo nội dung tin nhắn Markdown
    message = (
        f"🤖 *[AI v5 - LIVE ANALYSIS]*\n"
        f"-------------------------------------\n"
        f"▪️ *Cặp tiền:* {symbol}\n"
        f"▪️ *Hành động:* {direction}\n"
        f"▪️ *Mẫu tín hiệu:* `{pattern}`\n"
        f"▪️ *Giá Entry v4:* {entry:.5f}\n"
        f"▪️ *Vùng bảo vệ (Zone):* {zone:.5f}\n"
        f"▪️ *Tỷ lệ Volume:* {vol_ratio}x\n"
        f"-------------------------------------\n"
        f"📊 *ĐÁNH GIÁ CỦA AI:*\n"
        f"▪️ **Xác suất thắng (Win Rate):** `{win_prob * 100:.1f}%`\n"
        f"▪️ **Quyết định AI v5:** {status_icon} *{decision}*\n"
        f"-------------------------------------\n"
        
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_AI_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_AI_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            logging.error(f"Lỗi gửi Telegram AI v5: {response.text}")
    except Exception as e:
        logging.error(f"Không thể kết nối tới API Telegram: {str(e)}")