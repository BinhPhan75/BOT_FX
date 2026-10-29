# ai_v5/config_live.py
"""
Cau hinh rieng cho ai_v5 khi chay THAT (dat lenh that) tren tai khoan rieng
(demo hoac that tuy giai doan), hoan toan doc lap voi bot v4.
"""
import os

# --- Ket noi MT5 cho ai_v5 ---
# MAC DINH (khong khai bao gi ca): bot se tu ket noi vao terminal MT5 dang
# MO SAN tren may - ban chi can tu mo MT5, dang nhap tai khoan bang tay,
# roi chay live_trader.py la duoc, KHONG can khai bao gi them.
#
# 4 bien duoi day la TUY CHON - chi can khai bao neu muon ep bot ket noi
# DUNG 1 terminal/tai khoan cu the (vi du chay nhieu terminal MT5 cung luc
# tren cung 1 may, can phan biet ro terminal nao la cua ai_v5).
AI_V5_MT5_TERMINAL_PATH = os.environ.get("AI_V5_MT5_TERMINAL_PATH")
AI_V5_MT5_LOGIN = os.environ.get("AI_V5_MT5_LOGIN")
AI_V5_MT5_PASSWORD = os.environ.get("AI_V5_MT5_PASSWORD")
AI_V5_MT5_SERVER = os.environ.get("AI_V5_MT5_SERVER")

# --- Danh sach symbol / khung thoi gian quet song ---
# LUU Y: neu chay tren tai khoan cent, doi thanh dung ten broker (vd
# "XAUUSDc", "EURUSDc", "GBPUSDc" - CHU HOA/THUONG phai khop chinh xac).
SYMBOLS = ["XAUUSD", "EURUSD", "GBPUSD"]
TIMEFRAME = "M15"
SCAN_INTERVAL_SECONDS = 30          # Tan suat kiem tra nen moi (giay)
CANDLES_LOOKBACK = 300              # So nen tai ve moi lan quet (du cho swing/regime/ATR/RSI/MACD)

# --- Quan ly lenh / rui ro ---
MAGIC_NUMBER = 20260720             # Rieng biet voi magic number cua v4 (20260702)

MAX_OPEN_TRADES_PER_SYMBOL = 1      # So luong lenh toi da MAC DINH tren 1 symbol
# Cho phep mo THEM 1 lenh (vuot tran mac dinh) tren cung 1 symbol NEU tin hieu moi
# co WinProb dat toi thieu nguong duoi - van bi chan cung o tran cao hon nay du
# WinProb co cao den dau (khong "vo han lenh" chi vi tu tin cao).
MAX_OPEN_TRADES_PER_SYMBOL_HIGH_CONFIDENCE = 2
HIGH_CONFIDENCE_EXTRA_SLOT_THRESHOLD = 0.65

MAX_TOTAL_OPEN_TRADES = 6

# Gioi han GIO GIAO DICH — chi MO LENH MOI trong khung [START, END) theo gio
# Viet Nam (GMT+7). Ngoai khung nay, bot van quet/phan tich/gui Telegram binh
# thuong (va /analyze van hoat dong moi luc) — CHI RIENG viec mo lenh MOI bi
# tam dung. Lenh dang mo van duoc quan ly binh thuong (khong bi dong cuong buc
# khi het gio). Giong logic TRADING_HOURS_* cua bot v4 (config.py).
TRADING_HOURS_ENABLED = True
TRADING_HOURS_START_VN = 7    # 7h sang
TRADING_HOURS_END_VN = 23     # 23h dem

# Cho phep DAO LENH: neu da dat tran so luong lenh/symbol va tin hieu moi
# NGUOC HUONG voi 1 lenh dang mo tren cung symbol do, VA lenh dang mo do
# dang LO (P&L < 0) -> tu dong dong lenh cu, mo lenh moi theo huong tin
# hieu vua phat hien. Neu lenh cu dang LAI thi KHONG cat (chi bao da du
# tran, giu nguyen lenh dang tot). Giong logic ALLOW_REVERSE_ON_LOSS cua
# bot v4 (config.py).
ALLOW_REVERSE_ON_LOSS = True

ORDER_DEVIATION = 20
MIN_SL_POINTS_DEFAULT = 30

# Nguong spread toi da theo TUNG SYMBOL (dam bao "points" o day la don vi
# point cua chinh symbol do - XAUUSD point=0.01 nen 200 pts ~ $2.00, khac
# han EURUSD point=0.00001 nen 20 pts chi ~2 pips). Dung chung 1 nguong cho
# moi symbol la SAI vi don vi point khac nhau qua lon giua vang va forex.
MAX_SPREAD_POINTS_DEFAULT = 40
MAX_SPREAD_POINTS = {
    "XAUUSD": 200,
    "EURUSD": 20,
    "GBPUSD": 30,
    "USDJPY": 25,
}

# Tran an toan: khoang cach SL toi da (tinh theo GIA, khong phai points) cho
# tung symbol. Chan moi truong hop SL bi tinh qua xa gia hien tai (vd mau
# hinh Rounding/Cup&Handle dua tren dinh/day lich su xa) truoc khi dat lenh
# that - bat ke pattern nao sinh ra no. None = khong gioi han.
MAX_SL_DISTANCE = {
    "XAUUSD": 15.0,   # USD - giong nguong MAX_SL_USD cua bot v4
    "EURUSD": 0.010,  # ~100 pips
    "GBPUSD": 0.010,
}

# Khoi luong lenh CO DINH theo tung symbol (khong tinh theo % rui ro nua).
FIXED_LOT = {
    "XAUUSD": 0.01,
    "EURUSD": 0.03,
    "GBPUSD": 0.03,
}
FIXED_LOT_DEFAULT = 0.01

# --- Vong phan hoi tu hoc (live feedback + auto retrain) ---
AUTO_RETRAIN_ENABLED = True
RETRAIN_CHECK_INTERVAL_SECONDS = 3600   # Kiem tra moi 1 gio co den luc train lai chua
RETRAIN_INTERVAL_DAYS = 7               # Chu ky train lai thong thuong (7 ngay/lan)
MIN_NEW_TRADES_TO_RETRAIN = 10          # Can it nhat bay nhieu lenh MOI dong ke tu lan train truoc
PRECISION_DROP_TOLERANCE = 0.05         # Chi thay model moi neu Precision khong giam qua 5 diem % so voi model cu

