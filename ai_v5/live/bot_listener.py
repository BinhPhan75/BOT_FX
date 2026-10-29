import logging
import threading
import time
import requests
from ai_v5.config_ai import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from ai_v5.telegram.commands import TelegramCommandHandler

logger = logging.getLogger("ai_telegram_listener")

class TelegramListener:
    """
    Luồng chạy ngầm (Background Thread) lắng nghe và xử lý câu lệnh từ Telegram gửi tới V5.
    """
    def __init__(self):
        self.handler = TelegramCommandHandler()
        self.last_update_id = 0
        self.is_running = False

    def send_message(self, text: str):
        """Gửi tin nhắn phản hồi về Telegram."""
        if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Lỗi gửi phản hồi Telegram: {e}")

    def poll_updates(self):
        """Vòng lặp lấy tin nhắn mới từ Telegram API (Polling)."""
        if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
            logger.warning("Chưa cấu hình TELEGRAM_BOT_TOKEN. Tắt Telegram Listener.")
            return

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        
        while self.is_running:
            try:
                params = {"offset": self.last_update_id + 1, "timeout": 5}
                res = requests.get(url, params=params, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    for update in data.get("result", []):
                        self.last_update_id = update["update_id"]
                        message = update.get("message", {})
                        text = message.get("text", "").strip()

                        # Xử lý các câu lệnh
                        if text in ["/status", "/status@bot"]:
                            reply = self.handler.handle_status_command()
                            self.send_message(reply)
                        elif text in ["/help", "/start", "/help@bot"]:
                            reply = (
                                "🤖 *[AI V5 LIVE COMMANDS]*\n"
                                f"-------------------------------------\n"
                                f"▪ `/status` - Kiểm tra thông số & Precision mô hình V5\n"
                                f"▪ `/params` - Xem cấu hình ngưỡng lọc probability (60%)\n"
                                f"▪ `/help` - Danh sách lệnh hệ thống V5\n"
                            )
                            self.send_message(reply)
                        elif text in ["/params", "/params@bot"]:
                            reply = (
                                "⚙️ *[AI V5 CONFIGURATION]*\n"
                                f"-------------------------------------\n"
                                f"▪ Threshold: `60.0%`\n"
                                f"▪ Model: `LightGBM (11 Features)`\n"
                                f"▪ Timeframe: `M15`\n"
                                f"▪ Mode: `Live Trading (Demo)`"
                            )
                            self.send_message(reply)
            except Exception as e:
                time.sleep(3)
            time.sleep(1)

    def start_in_background(self):
        """Khởi chạy Bot Listener dưới dạng Thread chạy song song với Live Trader."""
        self.is_running = True
        thread = threading.Thread(target=self.poll_updates, daemon=True)
        thread.start()
        logger.info("✅ Telegram Bot Listener V5 đã khởi chạy ngầm.")