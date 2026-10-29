# ai_v5/telegram/bot_listener.py
import logging
import threading
import time
import requests
from ai_v5.config_ai import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from ai_v5.telegram.commands import TelegramCommandHandler

logger = logging.getLogger("ai_telegram_listener")

# Tập hợp chứa các symbol đang bị tạm dừng (Dùng chung cho toàn V5)
disabled_symbols = set()

class TelegramListener:
    def __init__(self):
        self.handler = TelegramCommandHandler()
        self.last_update_id = 0
        self.is_running = False

    def send_message(self, text: str):
        if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Lỗi gửi phản hồi Telegram: {e}")

    def poll_updates(self):
        if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
            logger.warning("Chưa cấu hình TELEGRAM_BOT_TOKEN.")
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
                        parts = text.split()
                        cmd = parts[0].lower() if parts else ""

                        # 🛑 Lệnh /disable SYMBOL (VD: /disable XAUUSD)
                        if cmd in ["/disable", "/disable@bot"]:
                            if len(parts) > 1:
                                sym = parts[1].upper()
                                disabled_symbols.add(sym)
                                reply = f"⛔ *[AI V5]* Đã **TẠM DỪNG** quét & giao dịch cặp `{sym}`."
                            else:
                                reply = "⚠️ Vui lòng nhập kèm tên cặp tiền. Ví dụ: `/disable XAUUSD`"
                            self.send_message(reply)

                        # 🟢 Lệnh /enable SYMBOL (VD: /enable XAUUSD)
                        elif cmd in ["/enable", "/enable@bot"]:
                            if len(parts) > 1:
                                sym = parts[1].upper()
                                disabled_symbols.discard(sym)
                                reply = f"✅ *[AI V5]* Đã **KÍCH HOẠT LẠI** quét & giao dịch cặp `{sym}`."
                            else:
                                reply = "⚠️ Vui lòng nhập kèm tên cặp tiền. Ví dụ: `/enable XAUUSD`"
                            self.send_message(reply)

                        # 📊 Lệnh /status
                        elif cmd in ["/status", "/status@bot"]:
                            reply = self.handler.handle_status_command()
                            disabled_list = ", ".join(disabled_symbols) if disabled_symbols else "Không có (Đang chạy tất cả)"
                            reply += f"\n-------------------------------------\n🛑 *Cặp tiền đang tạm dừng:* `{disabled_list}`"
                            self.send_message(reply)

                        # ⚙️ Lệnh /params
                        elif cmd in ["/params", "/params@bot"]:
                            reply = (
                                "⚙️ *[THAM SỐ CẤU HÌNH AI V5]*\n"
                                f"-------------------------------------\n"
                                f"▪ Ngưỡng lọc (Threshold): `60.0%`\n"
                                f"▪ Thuật toán: `LightGBM Classifier`\n"
                                f"▪ Số Features: `11 đặc trưng`\n"
                                f"▪ Khung thời gian: `M15`"
                            )
                            self.send_message(reply)

                        # ❓ Lệnh /help /start
                        elif cmd in ["/help", "/start", "/help@bot"]:
                            reply = (
                                "🤖 *[DANH SÁCH LỆNH AI V5]*\n"
                                f"-------------------------------------\n"
                                f"▪ `/disable SYMBOL` - Tạm dừng 1 cặp (vd: `/disable XAUUSD`)\n"
                                f"▪ `/enable SYMBOL` - Bật lại 1 cặp (vd: `/enable XAUUSD`)\n"
                                f"▪ `/status` - Xem trạng thái & cặp tiền đang dừng\n"
                                f"▪ `/params` - Xem cấu hình bộ lọc AI v5\n"
                                f"▪ `/help` - Danh sách câu lệnh này"
                            )
                            self.send_message(reply)

            except Exception:
                time.sleep(3)
            time.sleep(1)

    def start_in_background(self):
        self.is_running = True
        thread = threading.Thread(target=self.poll_updates, daemon=True)
        thread.start()
        logger.info("✅ Telegram Bot Listener V5 đã chạy ngầm (Hỗ trợ /disable, /enable).")