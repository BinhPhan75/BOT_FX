# bot_xutho4/ai_v5/bootstrap.py
import os
import logging
from ai_v5.config_ai import BASE_DIR, LOGS_FILE

def setup_ai_environment():
    """Tự động tạo các thư mục trống cho AI v5 nếu chưa tồn tại"""
    required_dirs = [
        "models",
        "datasets",
        "logs",
        "cache",
        "reports"
    ]
    
    for folder in required_dirs:
        path = os.path.join(BASE_DIR, folder)
        if not os.path.exists(path):
            os.makedirs(path)
            
    # Cấu hình logging riêng cho AI v5
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] (AI_v5) %(message)s",
        handlers=[
            logging.FileHandler(LOGS_FILE, encoding="utf-8"),
            logging.StreamHandler()
        ]
    )
    logging.info("Trình khởi động AI v5 hoàn tất. Sẵn sàng chạy song song!")

if __name__ == "__main__":
    setup_ai_environment()