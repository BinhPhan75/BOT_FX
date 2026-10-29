# ai_v6/config_ai.py
"""
Cau hinh co ban cho ai_v6 - GIONG CAU TRUC ai_v5/config_ai.py nhung tro toi
thu muc/token/nguong RIENG cua ai_v6. Khong dung chung MODELS_DIR/DATASETS_DIR
voi ai_v5 vi model v6 duoc train tren du lieu KHUNG M5 (khac M15 cua ai_v5) -
xem README_V6.md muc "Vi sao can train model rieng".
"""
import os

AI_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = AI_BASE_DIR

MODELS_DIR = os.path.join(AI_BASE_DIR, "models")
DATASETS_DIR = os.path.join(AI_BASE_DIR, "datasets")
LOGS_DIR = os.path.join(AI_BASE_DIR, "logs")
CACHE_DIR = os.path.join(AI_BASE_DIR, "cache")
REPORTS_DIR = os.path.join(AI_BASE_DIR, "reports")

for directory in [MODELS_DIR, DATASETS_DIR, LOGS_DIR, CACHE_DIR, REPORTS_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory)

LOGS_FILE = os.path.join(LOGS_DIR, "ai_v6.log")

# Telegram RIENG cho ai_v6 - BAT BUOC khac token/chat_id cua v4 va ai_v5
# (dung 1 bot Telegram cho nhieu bot se gay lan lon lenh /start /stop giua cac he thong).
TELEGRAM_AI_TOKEN = os.environ.get("AI_V6_TELEGRAM_BOT_TOKEN", "") or "8911193169:AAEzfLN-iBEhOAN0WmbJRx3AetarbOBckBc"
TELEGRAM_AI_CHAT_ID = os.environ.get("AI_V6_TELEGRAM_CHAT_ID", "") or "1417402698"

# Nguong quyet dinh cua model ML - dung LAI CO CHE cua ai_v5 (LightGBM tra ve
# xac suat thang, duyet lenh neu >= nguong nay). Gia tri co the khac ai_v5 vi
# model v6 duoc train rieng tren phan phoi du lieu M5.
#
# BẢN VÁ (28/08): hạ từ 0.55 xuống 0.50 — dùng ĐÚNG giá trị đã kiểm chứng bằng Walk-Forward
# thật qua tune_threshold_v6.py (Precision ~50.48%, tỷ lệ duyệt 25.2%, ổn định qua 5 fold).
# LƯU Ý QUAN TRỌNG: model hiện tại được train TRƯỚC KHI chuyển sang cơ chế scalping (SL/TP
# theo ATR M1) — nhãn thắng/thua lúc train vẫn dựa trên SL/TP kiểu pattern gốc (R:R~1.5, biên
# độ M5), lệch với cách quản lý lệnh scalping đang chạy live. Đây có thể là nguyên nhân khiến
# WinProb ra thấp một cách hệ thống (~37-39%) kể cả với tín hiệu hợp lệ trên M15/M5 — CẦN train
# lại model với nhãn phản ánh đúng cơ chế scalping để giải quyết tận gốc (CHƯA làm).
AI_WINRATE_THRESHOLD = float(os.environ.get("AI_V6_WINRATE_THRESHOLD", "0.52"))
PROBABILITY_THRESHOLD = AI_WINRATE_THRESHOLD

# Nguon du lieu lich su khi build dataset train (dung lai ai_v5.pipeline.build_dataset,
# xem run_init_train_v6.py). "csv" doc tu bt_cache/*.csv, "mt5" ket noi song.
HISTORICAL_DATA_SOURCE = os.environ.get("AI_V6_DATA_SOURCE", "csv")
BT_CACHE_DIR = os.path.abspath(os.path.join(AI_BASE_DIR, "..", "bt_cache"))
