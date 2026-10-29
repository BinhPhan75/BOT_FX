import logging
import threading
import time
import requests
from ai_v5.config_ai import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, PROBABILITY_THRESHOLD
from ai_v5.telegram.telegram_ai import send_telegram_msg

logger = logging.getLogger("telegram_listener")

class TelegramListener(threading.Thread):
    def __init__(self, symbols=None):
        super().__init__()
        self.daemon = True  # Tự đóng thread khi chương trình chính dừng
        self.symbols = symbols if symbols else ["XAUUSD", "EURUSD", "GBPUSD"]
        self.active_symbols = set(self.symbols)
        self.offset = 0
        self.running = True

    def run(self):
        if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
            logger.warning("Chưa cấu hình TELEGRAM_BOT_TOKEN. Bỏ qua TelegramListener.")
            return

        logger.info("🟢 Telegram Bot Listener V5 đã chạy ngầm (Hỗ trợ /status, /disable, /enable, /help).")

        while self.running:
            try:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
                params = {"offset": self.offset, "timeout": 10}
                res = requests.get(url, params=params, timeout=12)

                if res.status_code == 200:
                    data = res.json()
                    for result in data.get("result", []):
                        self.offset = result["update_id"] + 1
                        message = result.get("message", {})
                        chat_id = str(message.get("chat", {}).get("id", ""))
                        text = message.get("text", "").strip()

                        # Chỉ xử lý tin nhắn từ đúng CHAT_ID được cấp quyền
                        if chat_id == str(TELEGRAM_CHAT_ID) and text.startswith("/"):
                            self.handle_command(text)
            except Exception as e:
                logger.debug(f"Lỗi kết nối Telegram API: {e}")

            time.sleep(2)

    def handle_command(self, cmd_text: str):
        parts = cmd_text.split()
        cmd = parts[0].lower()
        param = parts[1].upper() if len(parts) > 1 else ""

        if cmd == "/status":
            active_list = ", ".join(self.active_symbols) if self.active_symbols else "Không có (Đang dừng tất cả)"
            msg = (
                f"📊 *[AI V5 STATUS REPORT - LIVE]*\n"
                f"-------------------------------------\n"
                f"🟢 *Các cặp đang quét:* `{active_list}`\n"
                f"🎯 *Ngưỡng duyệt (Threshold):* `{PROBABILITY_THRESHOLD:.0%}`\n"
                f"⚡ *Trạng thái Bot:* Đang hoạt động bình thường!"
            )
            send_telegram_msg(msg)

        elif cmd == "/disable":
            if param:
                if param in self.active_symbols:
                    self.active_symbols.remove(param)
                    send_telegram_msg(f"🔴 *[AI V5]* Đã tạm dừng quét & giao dịch cặp `{param}`.")
                else:
                    send_telegram_msg(f"⚠️ Cặp `{param}` hiện không có trong danh sách chạy.")
            else:
                self.active_symbols.clear()
                send_telegram_msg("🔴 *[AI V5]* Đã TẠM DỪNG quét tất cả các cặp tiền!")

        elif cmd == "/enable":
            if param:
                if param in self.symbols:
                    self.active_symbols.add(param)
                    send_telegram_msg(f"🟢 *[AI V5]* Đã KÍCH HOẠT LAI quét & giao dịch cặp `{param}`.")
                else:
                    send_telegram_msg(f"⚠️ Cặp `{param}` không nằm trong cấu hình danh sách mặc định.")
            else:
                self.active_symbols = set(self.symbols)
                send_telegram_msg("🟢 *[AI V5]* Đã KÍCH HOẠT LẠI quét tất cả các cặp tiền!")

        elif cmd == "/help":
            msg = (
                f"🤖 *[AI V5 - TELEGRAM COMMANDS]*\n"
                f"-------------------------------------\n"
                f"🔹 `/status` - Xem trạng thái hiện tại của Bot\n"
                f"🔹 `/disable` - Tạm dừng tất cả các cặp\n"
                f"🔹 `/disable XAUUSD` - Tạm dừng quét Vàng\n"
                f"🔹 `/enable` - Bật lại tất cả các cặp\n"
                f"🔹 `/enable XAUUSD` - Bật lại quét Vàng\n"
                f"🔹 `/help` - Xem danh sách lệnh hỗ trợ"
            )
            send_telegram_msg(msg)

    def get_active_symbols(self):
        return list(self.active_symbols)

    def stop(self):
        self.running = False