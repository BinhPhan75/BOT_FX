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
}

# ---------------------------------------------------------------------------
# Bang ma hoa nguon du lieu (source_type)
# ---------------------------------------------------------------------------
SOURCE_TYPE_ENCODING = {
    "V4_SIGNAL": 0,
    "GEOMETRIC_PATTERN": 1,
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
}
UNKNOWN_PATTERN_CODE = 0


def encode_pattern(pattern_name: str) -> int:
    return PATTERN_ENCODING.get(pattern_name, UNKNOWN_PATTERN_CODE)


def encode_regime(regime_name: str) -> int:
    return REGIME_TYPE_ENCODING.get((regime_name or "UNKNOWN").upper(), REGIME_TYPE_ENCODING["UNKNOWN"])


def encode_source_type(source_type: str) -> int:
    return SOURCE_TYPE_ENCODING.get(source_type, 0)


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
