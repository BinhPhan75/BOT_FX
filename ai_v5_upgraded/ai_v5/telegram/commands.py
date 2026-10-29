# bot_xutho4/ai_v5/telegram/commands.py
import logging
from ai_v5.ml.model_manager import ModelManager

logger = logging.getLogger("ai_telegram_commands")

class TelegramCommandHandler:
    """
    Xử lý các câu lệnh tương tác từ Telegram gửi tới phân hệ AI v5.
    """
    def __init__(self):
        self.model_manager = ModelManager()

    def handle_status_command(self) -> str:
        """Trả về thông tin trạng thái hoạt động hiện tại của mô hình AI"""
        model, metadata = self.model_manager.load_latest_model()
        if model is None:
            return "❌ Phân hệ AI v5 chưa được kích hoạt mô hình active."
            
        metrics = metadata.get("metrics", {})
        status_msg = (
            f"🤖 *[AI v5 Status Report]*\n"
            f"▪ *Mô hình active:* {metadata.get('model_name', 'N/A')}\n"
            f"▪ *Ngày cập nhật:* {metadata.get('timestamp', 'N/A')}\n"
            f"-------------------------------------\n"
            f"📊 *Chỉ số huấn luyện gốc:*\n"
            f"▪ Accuracy: {metrics.get('accuracy', 0.0):.2%}\n"
            f"▪ Precision: {metrics.get('precision', 0.0):.2%}\n"
            f"▪ F1-Score: {metrics.get('f1_score', 0.0):.2%}\n"
            f"-------------------------------------\n"
            f"✅ Hệ thống Shadow Mode đang trực chiến."
        )
        return status_msg