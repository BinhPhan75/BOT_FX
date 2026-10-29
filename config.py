"""
config.py
Cau hinh he thong AI Forex Pattern Watcher.
Cac gia tri nay la DEFAULT FALLBACK khi chua co optimized_params.json.
"""

# ====== MT5 ======
# USDJPY tam thoi loai bo (07/2026) — qua it lenh khi backtest o ca 2 bot,
# chua du du lieu de danh gia. Cac dict cau hinh rieng cho USDJPY ben duoi
# (TRAILING_STOP, ATR_SL_FACTOR, MIN_SL_POINTS...) giu nguyen de de bat lai
# sau nay, chi can them "USDJPY" vao SYMBOLS.
SYMBOLS   = ["XAUUSD", "EURUSD", "GBPUSD"]
TIMEFRAME = "M15"

# v9.3: Symbol bi TAM DUNG giao dich qua lenh Telegram /disable <SYMBOL>.
# Bot se BO QUA HOAN TOAN symbol nay (khong phan tich, khong tin hieu,
# khong lenh) cho toi khi /enable <SYMBOL>. Muc dich: tat XAUUSD thu cong
# trong phien My co tin tuc manh (NFP, CPI, FOMC...) de tranh rui ro bien
# dong dot ngot, trong khi EUR/GBP van tiep tuc giao dich binh thuong.
# Runtime-mutable — telegram_commander.py thay doi truc tiep bien nay.
DISABLED_SYMBOLS = set()
HTF_TIMEFRAME  = "H1"
HTF_BARS_COUNT = 100
BARS_COUNT     = 200

# ====== S/R DETECTION ======
# PIVOT_LOOKBACK: fallback khi param_loader chua co du lieu symbol
# Gia tri lon = it dinh day gia = tin hieu it hon nhung chinh xac hon
# XAUUSD nen dung 7-10 (volatility cao, dinh day can phai ro rang hon)
PIVOT_LOOKBACK      = 7      # tang tu 5 → 7 de giam nhieu
ZONE_MERGE_PERCENT  = 0.08   # tang tu 0.05 → 0.08 de gop zone gan nhau hon
MIN_TOUCHES         = 2

# ====== BREAKOUT DETECTION ======
BREAKOUT_THRESHOLD_PERCENT = 0.03
VOLUME_SPIKE_MULTIPLIER    = 1.5
VOLUME_AVG_PERIOD          = 20

# ====== SMC ======
SMC_ORDER_BLOCK_SEARCH_RANGE = 15

# ====== SERVER ======
WEBHOOK_URL    = "https://forexai-five.vercel.app/api/analyze"
WEBHOOK_SECRET = "Xuxu@2712"

# ====== POLLING ======
POLL_INTERVAL_SECONDS = 30

# ====== LOGGING ======
LOG_FILE       = "watcher.log"
DEDUPE_MINUTES = 60

# ====== TRAILING STOP ======
TRAILING_STOP_ENABLED = True
TRAILING_STOP = {
    "XAUUSD": {"enabled": True, "activation_atr": 2.0, "trail_atr": 1.5},
    "EURUSD": {"enabled": True, "activation_atr": 1.5, "trail_atr": 1.0},
    "GBPUSD": {"enabled": True, "activation_atr": 1.5, "trail_atr": 1.0},
    "USDJPY": {"enabled": True, "activation_atr": 2.0, "trail_atr": 1.5},
}

# v9.9: Gioi han GIO GIAO DICH — chi mo LENH MOI trong khung
# [TRADING_HOURS_START_VN, TRADING_HOURS_END_VN) theo gio Viet Nam (GMT+7).
# Ngoai khung nay (mac dinh 0h-7h sang), bot van chay day du: van phan tich,
# van gui thong bao tin hieu, TRAILING STOP va cac lenh dang mo VAN duoc
# quan ly binh thuong — CHI RIENG viec mo lenh MOI bi tam dung.
# Dat TRADING_HOURS_ENABLED = False de tat, giao dich 24/24 nhu truoc.
TRADING_HOURS_ENABLED   = True
TRADING_HOURS_START_VN  = 7    # 7h sang
TRADING_HOURS_END_VN    = 24   # 24h = het ngay (tuc dung mo lenh tu 0h-7h)

# ====== AUTO TRADING ======
AUTO_TRADE_ENABLED = True
RISK_PER_TRADE_PCT = 1.0
DEFAULT_RR_RATIO   = 2.0

# ====== ATR DYNAMIC PARAMS (fallback defaults) ======
# param_loader se dung cac gia tri nay neu chua co optimized_params.json
ATR_PERIOD_DEFAULT     = 14
ATR_MULTIPLIER_DEFAULT = 1.8   # giam tu 2.0 → 1.8 de SL khat hon

# Per-symbol ATR factor (fallback - se bi ghi de boi optimized_params.json)
ATR_SL_FACTOR_DEFAULT = 1.8
ATR_SL_FACTOR = {
    "XAUUSD": 1.5,   # XAUUSD: SL = 1.5 x ATR, co cap MAX_SL_USD
    "EURUSD": 1.8,
    "GBPUSD": 1.8,
    "USDJPY": 2.0,
}

SL_BUFFER_PERCENT_DEFAULT = 0.06
SL_BUFFER_PERCENT = {
    "XAUUSD": 0.05,
    "EURUSD": 0.06,
    "GBPUSD": 0.06,
    "USDJPY": 0.10,
}

# v9: TP gio tinh doc lap theo ATR (tp_atr_multiplier) nen can SAN TOI
# THIEU rieng, giong het SL_BUFFER_PERCENT — neu khong, luc thi truong it
# bien dong (ATR co lai) TP se co qua nho (co the < 10 pip) trong khi SL
# van duoc giu san % toi thieu, gay lech RR nghiem trong.
TP_BUFFER_PERCENT_DEFAULT = 0.06
TP_BUFFER_PERCENT = {
    "XAUUSD": 0.08,   # TP thuong can rong hon SL 1 chut de RR hop ly
    "EURUSD": 0.10,
    "GBPUSD": 0.10,
    "USDJPY": 0.14,
}

# ====== TRADE LIMITS ======
MAX_OPEN_TRADES_PER_SYMBOL = 1
MAX_TOTAL_OPEN_TRADES      = 4

# Neu da co 1 lenh mo (dat toi da MAX_OPEN_TRADES_PER_SYMBOL) VA phat hien
# tin hieu MOI nguoc chieu voi lenh dang mo VA lenh dang mo dang LO (am) —
# tu dong DONG lenh cu de mo lenh moi theo tin hieu. Neu False, giu hanh vi
# cu: bo qua tin hieu moi khi da du so lenh toi da.
ALLOW_REVERSE_ON_LOSS = True

# v9.2: Chan tin hieu "duoi gia" (FOMO) — vi du lenh BUY vua chot TP, gia
# tiep tuc tang, bot phat hien tin hieu BUY moi va vao lenh ngay tai vung
# gia da bi day len xa, de bi dieu chinh nguoc lai gay lo. Neu gia hien tai
# da chay qua "fomo_guard_atr_mult" lan ATR so voi gia dong lenh CUNG CHIEU
# gan nhat, bot se bo qua tin hieu do (xem param_loader "fomo_guard_atr_mult",
# mac dinh 0.5 — co the tuy chinh rieng tung symbol qua optimized_params.json).
FOMO_GUARD_ENABLED = True

MIN_SL_POINTS_DEFAULT = 100
MIN_SL_POINTS = {
    "XAUUSD": 150,
    "EURUSD": 100,
    "GBPUSD": 120,
    "USDJPY": 200,
}

MAX_SPREAD_POINTS_DEFAULT = 40
MAX_SPREAD_POINTS = {
    "XAUUSD": 200,
    "EURUSD": 20,
    "GBPUSD": 30,
    "USDJPY": 25,
}

FIXED_LOT = {
    "XAUUSD": 0.01,
    "EURUSD": 0.05,
    "GBPUSD": 0.05,
    "USDJPY": 0.05,
}

MAX_LOT_SIZE   = 1.0
ORDER_DEVIATION = 20

# ====== SL CAP ======
MAX_SL_USD         = {"XAUUSD": 15.0}
MAX_SL_USD_DEFAULT = None
BODY_STRENGTH_MIN  = 0.35

# ====== MARKET REGIME ======
ADX_PERIOD = 14
ADX_TRENDING_THRESHOLD = {"XAUUSD": 25, "EURUSD": 20, "GBPUSD": 20, "USDJPY": 22}
ADX_VOLATILE_THRESHOLD = {"XAUUSD": 75, "EURUSD": 65, "GBPUSD": 65, "USDJPY": 70}
ADX_SPIKE_MULT = 1.8

# ====== ADAPTIVE FILTER ======
ADAPTIVE_SCORE_THRESHOLD = 55

# ====== ATR GATE ======
ATR_MIN_PCT_OF_PRICE = 0.0001
ATR_MAX_MULT         = 4.0
MAX_ZONE_DISTANCE_PCT = 1.0

# ====== AUTO TUNER ======
# Chay theo LICH CO DINH gio Viet Nam (GMT+7) moi ngay — vi du 2 = 2h sang.
# Dat = None de quay lai hanh vi cu (chay moi AUTO_TUNER_INTERVAL_DAYS ke tu
# lan chay truoc, co the troi gio tuy luc bot duoc khoi dong/restart).
AUTO_TUNER_SCHEDULED_HOUR_VN = 2

# Chay lai backtest + toi uu moi ngay (hay khi co 3 lenh live moi dong)
AUTO_TUNER_INTERVAL_DAYS    = 1
AUTO_TUNER_BACKTEST_DAYS    = 365
AUTO_TUNER_ENABLE_FINE_PHASE = True  # Bat lai: coarse da cho XAUUSD/EURUSD/GBPUSD gan/vuot breakeven, dang tinh chinh them  # Tong so ngay data cho WFO
AUTO_TUNER_MIN_NEW_TRADES   = 3

# ====== TELEGRAM ======
TELEGRAM_BOT_TOKEN = "8888260338:AAG_6jkj0saW9DqD9LDlJCVVMFV_h-jtAXc"
TELEGRAM_CHAT_ID   = "1417402698"