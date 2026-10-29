# ai_v5/live/feature_builder.py
"""
Dong goi vector dac trung (dung schema hop nhat feature_schema.py) tu 1 match
cua live_pattern_scanner.py. Tach rieng module nay (thay vi de trong
live_trader.py) de ca live_trader.py lan telegram_commander.py deu dung duoc
ma khong gay vong lap import (live_trader.py da import telegram_commander.py
de khoi dong no, nen telegram_commander.py khong the import nguoc lai
live_trader.py).

---------------------------------------------------------------------------
BẢN VÁ: "distance_to_zone_pct" truoc day LUON = 0.0 cho MOI lenh, du co mat
trong FEATURE_COLUMNS ma model dung de hoc -> model chua bao gio co thong
tin "gia hien tai con cach vung muc tieu (TP) bao xa". Gio tinh gia tri that
= khoang cach tu entry -> TP theo % gia entry, dua tren "_entry_price" (moi
them o live_pattern_scanner.py) va "tp" co san trong match.

LUU Y QUAN TRONG: sau khi deploy bản vá này, GIA TRI CUA COT NAY SE THAY DOI
Y NGHIA so voi du lieu train cu (truoc day toan bo la 0.0). Can TRAIN LAI
MODEL (chay run_init_train.py hoac trigger 1 chu ky auto_retrain) sau khi
deploy, neu khong model dang chay se nhan input voi 1 cot co phan phoi khac
hoan toan so luc train - co the lam giam do chinh xac tam thoi cho toi khi
train lai.
---------------------------------------------------------------------------
"""
from datetime import datetime, timezone, timedelta

from ai_v5.data.feature_schema import encode_pattern, encode_regime, encode_source_type, encode_trend_alignment


def build_feature_dict(match: dict, source_type: str, regime_res) -> dict:
    """Dong goi dung SCHEMA HOP NHAT (feature_schema.py) tu 1 match cua live_pattern_scanner."""
    direction = match["direction"]
    atr = match.get("_atr", 0.0)
    momentum_ratio = match.get("_momentum_ratio", 0.0)
    candle_time = match.get("_candle_time", 0)
    try:
        vn_time = datetime.fromtimestamp(candle_time, tz=timezone.utc) + timedelta(hours=7)
    except Exception:
        vn_time = datetime.now()

    # BẢN VÁ: distance_to_zone_pct thật, thay vì hardcode 0.0
    entry_price = match.get("_entry_price", 0.0)
    tp = match.get("tp")
    if entry_price and tp is not None:
        distance_to_zone_pct = abs(float(tp) - float(entry_price)) / float(entry_price) * 100.0
    else:
        distance_to_zone_pct = 0.0

    return {
        "source_type_encoded": encode_source_type(source_type),
        "pattern_encoded": encode_pattern(match["pattern"]),
        "regime_type_encoded": encode_regime(regime_res.regime if regime_res else "UNKNOWN"),
        "adx_value": float(regime_res.adx) if regime_res else 25.0,
        "rsi_14": match.get("_rsi_14", 50.0),
        "volume_ratio": float(momentum_ratio),
        "atr_value": float(atr),
        "distance_to_zone_pct": distance_to_zone_pct,
        "hour_of_day": vn_time.hour,
        "day_of_week": vn_time.weekday(),
        "trend_alignment_encoded": encode_trend_alignment(direction, regime_res.trend_dir if regime_res else "neutral"),
    }
