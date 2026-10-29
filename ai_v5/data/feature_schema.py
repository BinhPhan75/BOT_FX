# bot_xutho4/ai_v5/data/feature_schema.py
"""
Schema dac trung HOP NHAT cho ca 2 nguon du lieu cua ai_v5:
  - "V4_SIGNAL"        : tin hieu song (SMC/SuperTrend/EMA/PriceAction) tu analysis.py cua bot v4,
                          duoc shadow_runner.py cham diem real-time va ghi lai khi lenh dong.
  - "GEOMETRIC_PATTERN" : 16 mau hinh gia co dien (Double Top, H&S, Triangle, Wedge, Flag...)
                          duoc pipeline/build_dataset.py quet truc tiep tu lich su nen MT5/bt_cache.

Ca hai nguon deu ghi du lieu vao CUNG 1 schema nay (cot nao khong ap dung se duoc
dien gia tri mac dinh hop ly) de mot model LightGBM duy nhat co the hoc tu ca 2 nguon,
phan biet boi cot 'source_type'.
"""

# Nhan muc tieu (Target Column) - 1: Thang, 0: Thua/Hoa
TARGET_COLUMN = "is_win"

# Danh sach toan bo dac trung dau vao ma model se dung de hoc va du doan
FEATURE_COLUMNS = [
    "source_type_encoded",   # 0: V4_SIGNAL (tin hieu SMC/ST/EMA/PA cua bot v4) | 1: GEOMETRIC_PATTERN (16 mau hinh co dien)
    "pattern_encoded",       # Ma so mau hinh, dung chung 1 bang ma cho ca 2 nguon (xem PATTERN_ENCODING ben duoi)
    "regime_type_encoded",   # Ma so che do thi truong: 0 SIDEWAYS / 1 TRENDING / 2 VOLATILE / 3 UNKNOWN
    "adx_value",             # Gia tri ADX tai thoi diem tin hieu (do suc manh xu huong)
    "rsi_14",                # RSI 14 tai thoi diem vao lenh (mac dinh 50.0 neu khong tinh duoc - vd mau GEOMETRIC_PATTERN)
    "volume_ratio",          # Ty le volume/dong luong tuong doi tai tin hieu
    "atr_value",             # Do bien dong thi truong (ATR 14)
    "distance_to_zone_pct",  # Khoang cach Entry -> vung an toan (Zone/Neckline) theo % (0.0 neu khong ap dung)
    "hour_of_day",           # Gio vao lenh theo gio VN (0-23)
    "day_of_week",           # Ngay trong tuan (0: Thu 2 - 6: Chu Nhat)
    "trend_alignment_encoded",  # 0: NGUOC xu huong chinh | 1: TRUNG LAP/khong ro | 2: THUAN xu huong chinh (xem TREND_ALIGNMENT_ENCODING)
]

# Kieu du lieu chuan cho tung cot, tranh loi ep kieu khi nap vao LightGBM
FEATURE_TYPES = {
    "source_type_encoded": "int32",
    "pattern_encoded": "int32",
    "regime_type_encoded": "int32",
    "adx_value": "float64",
    "rsi_14": "float64",
    "volume_ratio": "float64",
    "atr_value": "float64",
    "distance_to_zone_pct": "float64",
    "hour_of_day": "int32",
    "day_of_week": "int32",
    "trend_alignment_encoded": "int32",
}

# ---------------------------------------------------------------------------
# Bang ma hoa nguon du lieu (source_type)
# ---------------------------------------------------------------------------
SOURCE_TYPE_ENCODING = {
    "V4_SIGNAL": 0,
    "GEOMETRIC_PATTERN": 1,
    "CANDLESTICK_PATTERN": 2,
    "HARMONIC_PATTERN": 3,
    "DIVERGENCE_PATTERN": 4,
    "VSA_PATTERN": 5,
    "ICT_PATTERN": 6,
    "CONTINUATION_PATTERN": 7,
}

# ---------------------------------------------------------------------------
# Bang ma hoa che do thi truong (khop voi market_regime.py: REGIME_SIDEWAYS/
# REGIME_TRENDING/REGIME_VOLATILE/REGIME_UNKNOWN)
# ---------------------------------------------------------------------------
REGIME_TYPE_ENCODING = {
    "SIDEWAYS": 0,
    "TRENDING": 1,
    "VOLATILE": 2,
    "UNKNOWN": 3,
}

# ---------------------------------------------------------------------------
# Bang ma hoa THUAN/NGUOC XU HUONG (HTF Trend Alignment).
# So sanh huong tin hieu (BUY/SELL) voi trend_dir cua market_regime.RegimeResult
# ("bullish"/"bearish"/"neutral"). Dung de model tu hoc ha diem tin cay cho
# tin hieu di NGUOC xu huong chinh cua thi truong (vd tin hieu BUY nhung
# trend_dir dang la "bearish" -> AGAINST).
# ---------------------------------------------------------------------------
TREND_ALIGNMENT_ENCODING = {
    "AGAINST": 0,   # Tin hieu di NGUOC xu huong chinh (rui ro cao hon)
    "NEUTRAL": 1,   # Khong xac dinh duoc xu huong ro rang (trend_dir="neutral"/"unknown")
    "ALIGNED": 2,   # Tin hieu di THUAN xu huong chinh (uu the hon)
}

# ---------------------------------------------------------------------------
# Bang ma hoa MAU HINH dung chung cho ca 2 nguon.
# Nhom 1-8: tin hieu song cua bot v4 (khop dung ten pattern do analysis.py sinh ra).
# Nhom 9-24: 16 mau hinh hinh hoc co dien (khop dung ten do pattern_rules.detect_16_patterns tra ve).
# ---------------------------------------------------------------------------
PATTERN_ENCODING = {
    # --- V4_SIGNAL (bot_xutho4 goc) ---
    "smc_bullish_bos": 1,
    "smc_bearish_bos": 2,
    "smc_bullish_choch": 3,
    "smc_bearish_choch": 4,
    "st_flip_bullish": 5,
    "st_flip_bearish": 6,
    "ema_cross_bullish": 7,
    "ema_cross_bearish": 8,
    "price_action_bullish": 9,
    "price_action_bearish": 10,
    # --- GEOMETRIC_PATTERN (16 mau hinh co dien, ai_v5) ---
    "DOUBLE_TOP": 20,
    "DOUBLE_BOTTOM": 21,
    "TRIPLE_TOP": 22,
    "TRIPLE_BOTTOM": 23,
    "HEAD_AND_SHOULDERS": 24,
    "INVERTED_HEAD_AND_SHOULDERS": 25,
    "ASCENDING_TRIANGLE": 26,
    "DESCENDING_TRIANGLE": 27,
    "BULLISH_SYMMETRICAL_TRIANGLE": 28,
    "BEARISH_SYMMETRICAL_TRIANGLE": 29,
    "BULLISH_FALLING_WEDGE": 30,
    "BEARISH_RISING_WEDGE": 31,
    "BULLISH_FLAG": 32,
    "BEARISH_FLAG": 33,
    # --- CANDLESTICK_PATTERN (nến Nhật, ai_v5) ---
    "BULLISH_ENGULFING": 40,
    "BEARISH_ENGULFING": 41,
    "HAMMER": 42,
    "SHOOTING_STAR": 43,
    "MORNING_STAR": 44,
    "EVENING_STAR": 45,
    "PIERCING_LINE": 46,
    "DARK_CLOUD_COVER": 47,
    "THREE_WHITE_SOLDIERS": 48,
    "THREE_BLACK_CROWS": 49,
    "DOJI_BULLISH_REVERSAL": 50,
    "DOJI_BEARISH_REVERSAL": 51,
    # --- HARMONIC_PATTERN (Fibonacci XABCD, ai_v5) ---
    "GARTLEY_BULLISH": 60,
    "GARTLEY_BEARISH": 61,
    "BAT_BULLISH": 62,
    "BAT_BEARISH": 63,
    "BUTTERFLY_BULLISH": 64,
    "BUTTERFLY_BEARISH": 65,
    "CRAB_BULLISH": 66,
    "CRAB_BEARISH": 67,
    # --- DIVERGENCE_PATTERN (RSI/MACD, ai_v5) ---
    "RSI_BULLISH_DIVERGENCE_REGULAR": 70,
    "RSI_BEARISH_DIVERGENCE_REGULAR": 71,
    "RSI_BULLISH_DIVERGENCE_HIDDEN": 72,
    "RSI_BEARISH_DIVERGENCE_HIDDEN": 73,
    "MACD_BULLISH_DIVERGENCE_REGULAR": 74,
    "MACD_BEARISH_DIVERGENCE_REGULAR": 75,
    "MACD_BULLISH_DIVERGENCE_HIDDEN": 76,
    "MACD_BEARISH_DIVERGENCE_HIDDEN": 77,
    # --- VSA_PATTERN (Volume Spread Analysis, ai_v5) ---
    "VSA_NO_DEMAND": 80,
    "VSA_NO_SUPPLY": 81,
    "VSA_SELLING_CLIMAX": 82,
    "VSA_BUYING_CLIMAX": 83,
    "VSA_STOPPING_VOLUME_BUY": 84,
    "VSA_STOPPING_VOLUME_SELL": 85,
    # --- ICT_PATTERN (Smart Money Concepts nang cao, ai_v5) ---
    "BULLISH_ORDER_BLOCK": 90,
    "BEARISH_ORDER_BLOCK": 91,
    "BULLISH_FVG": 92,
    "BEARISH_FVG": 93,
    "BULLISH_LIQUIDITY_SWEEP": 94,
    "BEARISH_LIQUIDITY_SWEEP": 95,
    # --- CONTINUATION_PATTERN (mau hinh dai han, ai_v5) ---
    "ROUNDING_BOTTOM": 100,
    "ROUNDING_TOP": 101,
    "CUP_AND_HANDLE": 102,
    "INVERTED_CUP_AND_HANDLE": 103,
}
UNKNOWN_PATTERN_CODE = 0


def encode_pattern(pattern_name: str) -> int:
    return PATTERN_ENCODING.get(pattern_name, UNKNOWN_PATTERN_CODE)


def encode_regime(regime_name: str) -> int:
    return REGIME_TYPE_ENCODING.get((regime_name or "UNKNOWN").upper(), REGIME_TYPE_ENCODING["UNKNOWN"])


def encode_source_type(source_type: str) -> int:
    return SOURCE_TYPE_ENCODING.get(source_type, 0)


def encode_trend_alignment(signal_direction: str, trend_dir: str) -> int:
    """
    signal_direction: "BUY" hoac "SELL" (huong lenh cua tin hieu).
    trend_dir: "bullish" | "bearish" | "neutral" (tu market_regime.RegimeResult.trend_dir).
    """
    trend_dir = (trend_dir or "neutral").lower()
    signal_direction = (signal_direction or "").upper()

    if trend_dir not in ("bullish", "bearish"):
        return TREND_ALIGNMENT_ENCODING["NEUTRAL"]

    is_aligned = (signal_direction == "BUY" and trend_dir == "bullish") or \
                 (signal_direction == "SELL" and trend_dir == "bearish")
    return TREND_ALIGNMENT_ENCODING["ALIGNED"] if is_aligned else TREND_ALIGNMENT_ENCODING["AGAINST"]


def validate_features(df_features):
    """
    Ham kiem tra nhanh tinh toan ven cua du lieu dac trung dau vao.
    Dam bao khong bi thieu cot hoac sai lech kieu du lieu truoc khi Train hoac Predict.
    """
    missing_cols = [col for col in FEATURE_COLUMNS if col not in df_features.columns]
    if missing_cols:
        raise ValueError(f"Du lieu bi thieu cac cot dac trung bat buoc: {missing_cols}")

    validated_df = df_features[FEATURE_COLUMNS].copy()
    for col, dtype in FEATURE_TYPES.items():
        validated_df[col] = validated_df[col].astype(dtype)

    return validated_df
