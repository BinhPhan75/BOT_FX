# bot_xutho4/ai_v5/config_ai.py
import os

# 1. Dinh nghia thu muc goc cua phan he AI v5
AI_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Alias tuong thich nguoc: bootstrap.py va mot so module cu import "BASE_DIR"
BASE_DIR = AI_BASE_DIR

# 2. Dinh nghia tuong minh duong dan den cac thu muc chuc nang
MODELS_DIR   = os.path.join(AI_BASE_DIR, "models")
DATASETS_DIR = os.path.join(AI_BASE_DIR, "datasets")
LOGS_DIR     = os.path.join(AI_BASE_DIR, "logs")
CACHE_DIR    = os.path.join(AI_BASE_DIR, "cache")
REPORTS_DIR  = os.path.join(AI_BASE_DIR, "reports")

# 3. Tu dong khoi tao thu muc neu chua ton tai tren he thong/VPS
for directory in [MODELS_DIR, DATASETS_DIR, LOGS_DIR, CACHE_DIR, REPORTS_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory)

# File log rieng cho AI v5 (dung boi bootstrap.py)
LOGS_FILE = os.path.join(LOGS_DIR, "ai_v5.log")

# 4. Cau hinh Telegram rieng cho phan he AI v5 (bot Shadow Analysis).
# UU TIEN doc tu bien moi truong de tranh hardcode token nhay cam trong code.
# Neu chua set env, fallback ve rong (module gui Telegram se tu bo qua va log canh bao).
TELEGRAM_AI_TOKEN = os.environ.get("AI_V5_TELEGRAM_BOT_TOKEN", "") or "8911193169:AAEzfLN-iBEhOAN0WmbJRx3AetarbOBckBc"
TELEGRAM_AI_CHAT_ID = os.environ.get("AI_V5_TELEGRAM_CHAT_ID", "") or "1417402698"

# Alias tuong thich nguoc (mot so module cu dung ten TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID)
TELEGRAM_BOT_TOKEN = "8911193169:AAEzfLN-iBEhOAN0WmbJRx3AetarbOBckBc"
TELEGRAM_CHAT_ID = "1417402698"

# 5. Cau hinh nguong loc lenh (Decision Threshold)
AI_WINRATE_THRESHOLD = 0.55      # Nguong duyet lenh khi dung predictor.predict_signal()
PROBABILITY_THRESHOLD = AI_WINRATE_THRESHOLD  # Alias dung trong shadow_runner.py

# 6. Nguon du lieu lich su cho pipeline/build_dataset.py
#    "csv"  -> doc tu bt_cache/*.csv (dung de dung thu/test cuc bo, khong can MT5)
#    "mt5"  -> ket noi truc tiep MetaTrader5 python lib (chi chay tren may Windows co MT5)
HISTORICAL_DATA_SOURCE = os.environ.get("AI_V5_DATA_SOURCE", "csv")
BT_CACHE_DIR = os.path.abspath(os.path.join(AI_BASE_DIR, "..", "bt_cache"))
