# ai_v5/live/live_pattern_scanner.py
"""
Quet SONG (real-time) toan bo 7 nhom mau hinh (tru V4_SIGNAL - da co hook
rieng qua analysis.py cua bot v4) tren cay nen MOI DONG GAN NHAT.

QUAN TRONG: dung LAI CHINH XAC cac ham detector da dung trong
pipeline/build_dataset.py (offline, dung de tao dataset train) - dam bao
logic phat hien SONG va OFFLINE giong het nhau 100%, tranh truong hop model
duoc train tren 1 dinh nghia pattern nhung luc chay that lai dung dinh
nghia khac (se lam vo hieu toan bo qua trinh train).

---------------------------------------------------------------------------
BẢN VÁ (FIX #1): 2 dòng detect_divergence() trước đây dùng `swings_before`
(swing THÔ, chưa lọc) trong khi MỌI nhóm pattern khác trong file này (Harmonic,
Continuation) đều dùng `major_swings_before` (đã lọc qua filter_major_swings,
loại bỏ dao động nhỏ/nhiễu). Đây là nguyên nhân chính khiến DIVERGENCE_PATTERN
chiếm 90% tổng số lệnh nhưng chỉ thắng thật ~29% (dữ liệu từ ai_v5_trades.db) —
vì nó bắt tín hiệu trên MỌI đỉnh/đáy vụn vặt thay vì chỉ các swing có ý nghĩa
cấu trúc. Sửa bằng cách đổi sang dùng major_swings_before, nhất quán với các
nhóm pattern khác.

BẢN VÁ (FIX #2): thêm "_entry_price" vào match dict (dùng current_price tại
thời điểm quét) để feature_builder.py tính được distance_to_zone_pct thật
thay vì hardcode 0.0.
---------------------------------------------------------------------------
"""
import logging
import pandas as pd

from ai_v5.pipeline.swing_detector import find_swing_points, filter_major_swings
from ai_v5.pipeline.pattern_rules import detect_16_patterns
from ai_v5.pipeline.candlestick_patterns import detect_candlestick_patterns
from ai_v5.pipeline.harmonic_patterns import detect_harmonic_patterns
from ai_v5.pipeline.divergence_patterns import detect_divergence, compute_rsi_series, compute_macd_series
from ai_v5.pipeline.vsa_patterns import detect_vsa_patterns
from ai_v5.pipeline.ict_patterns import detect_order_block, detect_fair_value_gap, detect_liquidity_sweep
from ai_v5.pipeline.continuation_patterns import (
    detect_rounding_bottom, detect_rounding_top,
    detect_cup_and_handle, detect_inverted_cup_and_handle,
)

logger = logging.getLogger("ai_v5_live_scanner")

MIN_CANDLES_REQUIRED = 220


def scan_all_patterns_live(candles: list, symbol: str) -> list:
    """
    candles: list dict OHLCV, sap xep TANG DAN theo thoi gian, candles[-1] la
             nen DA DONG gan nhat (dung mt5_client.get_candles(position=1) de
             dam bao dieu nay - KHONG duoc truyen nen dang chay do).

    Tra ve: list [(source_type: str, match: dict), ...] cho MOI pattern khop
            tai nen cuoi cung. match co them cac khoa phu tro "_atr",
            "_momentum_ratio", "_candle_time", "_rsi_14", "_entry_price" de
            live_trader.py dung xay feature vector ma khong phai tinh lai.
    """
    if len(candles) < MIN_CANDLES_REQUIRED:
        logger.debug(f"{symbol}: chỉ có {len(candles)} nến, cần tối thiểu {MIN_CANDLES_REQUIRED} để quét đủ 7 nhóm.")
        return []

    df_rates = pd.DataFrame(candles)
    if "time" not in df_rates.columns:
        df_rates["time"] = range(len(df_rates))

    # 1. Cau truc Dinh/Day (dung chung cho Hinh hoc + Harmonic + Divergence)
    swings = find_swing_points(df_rates, left_bars=5, right_bars=5)
    avg_atr_symbol = (df_rates["high"] - df_rates["low"]).rolling(14).mean().median()
    if pd.isna(avg_atr_symbol) or avg_atr_symbol == 0:
        avg_atr_symbol = df_rates["close"].iloc[-1] * 0.001
    major_swings = filter_major_swings(swings, min_move=float(avg_atr_symbol) * 4)

    # 2. Chi so vector hoa cho Phan ky VA cho RSI thuc (tinh 1 lan cho toan bo
    #    chuoi, tra cuu O CHI SO CUOI) - dung chung cho MOI nhom pattern, khong
    #    con hardcode RSI=50.0 nhu truoc.
    rsi_series = compute_rsi_series(df_rates["close"], period=14)
    macd_series = compute_macd_series(df_rates["close"], fast=12, slow=26)
    avg_volume_series = df_rates["volume"].rolling(20).mean() if "volume" in df_rates.columns else None

    i = len(df_rates) - 1  # CHI quet nen cuoi cung (nen moi dong gan nhat)
    current_price = float(df_rates.iloc[i]["close"])

    swings_before = [s for s in swings if s["index"] < i]
    major_swings_before = [s for s in major_swings if s["index"] < i]
    if len(swings_before) < 5:
        return []

    sub_rates = candles[max(0, i - 100):i + 1]
    sub_df = pd.DataFrame(sub_rates)
    atr = (sub_df["high"] - sub_df["low"]).rolling(14).mean().iloc[-1]
    if pd.isna(atr) or atr == 0:
        atr = current_price * 0.001
    atr = float(atr)

    avg_vol_i = (float(avg_volume_series.iloc[i])
                 if avg_volume_series is not None and not pd.isna(avg_volume_series.iloc[i]) else 0.0)
    recent_candles_6 = candles[max(0, i - 6):i + 1]

    # 3. Kiem tra doc lap CA 7 NHOM (giong het build_dataset.py, tru phan ghi nhan/gan nhan)
    #    FIX #1: Divergence gio dung major_swings_before (da loc) thay vi swings_before (tho),
    #    nhat quan voi Harmonic/Continuation - tranh bat tin hieu tren dao dong vun vat.
    candidates = [
        ("GEOMETRIC_PATTERN", detect_16_patterns(swings_before, current_price, atr)),
        ("HARMONIC_PATTERN", detect_harmonic_patterns(major_swings_before, current_price, atr)),
        ("CANDLESTICK_PATTERN", detect_candlestick_patterns(recent_candles_6, atr)),
        ("DIVERGENCE_PATTERN", detect_divergence(major_swings_before, current_price, rsi_series.iloc[i], rsi_series, atr, "RSI")),
        ("DIVERGENCE_PATTERN", detect_divergence(major_swings_before, current_price, macd_series.iloc[i], macd_series, atr, "MACD")),
        ("VSA_PATTERN", detect_vsa_patterns(candles[max(0, i - 2):i + 1], avg_vol_i, atr)),
        ("ICT_PATTERN", detect_order_block(recent_candles_6, swings_before, current_price, atr)),
        ("ICT_PATTERN", detect_fair_value_gap(recent_candles_6, atr)),
        ("ICT_PATTERN", detect_liquidity_sweep(recent_candles_6, swings_before, atr)),
        ("CONTINUATION_PATTERN", detect_rounding_bottom(major_swings_before, current_price, atr)),
        ("CONTINUATION_PATTERN", detect_rounding_top(major_swings_before, current_price, atr)),
        ("CONTINUATION_PATTERN", detect_cup_and_handle(major_swings_before, current_price, atr)),
        ("CONTINUATION_PATTERN", detect_inverted_cup_and_handle(major_swings_before, current_price, atr)),
    ]
    matches = [(stype, m) for stype, m in candidates if m is not None]

    prev_close = float(candles[i - 1]["close"]) if i > 0 else current_price
    momentum_ratio = (current_price - prev_close) / atr if atr else 0.0
    candle_time = candles[i].get("time", 0)
    current_rsi = float(rsi_series.iloc[i]) if not pd.isna(rsi_series.iloc[i]) else 50.0

    for _stype, m in matches:
        m["_atr"] = atr
        m["_momentum_ratio"] = momentum_ratio
        m["_candle_time"] = candle_time
        m["_rsi_14"] = current_rsi
        m["_entry_price"] = current_price  # FIX #2: dùng cho distance_to_zone_pct trong feature_builder.py

    return matches
