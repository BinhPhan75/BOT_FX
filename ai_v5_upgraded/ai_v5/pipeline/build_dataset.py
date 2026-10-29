# ai_v5/pipeline/build_dataset.py
"""
Quet lich su nen (tu bt_cache/*.csv HOAC truc tiep MT5), tu dong ve Dinh/Day
va nhan dien 16 Mau hinh gia kinh dien, gan nhan Thang/Thua bang cach chay
tiep nen tuong lai xem cham SL hay TP truoc. Ket qua duoc ghi ra CSV theo
schema HOP NHAT (ai_v5/data/feature_schema.py, source_type=GEOMETRIC_PATTERN)
de co the gop chung voi dataset tu tin hieu song cua bot v4 (source_type=V4_SIGNAL)
khi huan luyen model.

Cach dung:
    python -m ai_v5.pipeline.build_dataset                     # dung nguon mac dinh trong config_ai (csv)
    python -m ai_v5.pipeline.build_dataset --source mt5        # bat buoc dung MT5 song (chi chay tren Windows co MT5)
    python -m ai_v5.pipeline.build_dataset --source csv --days 260
"""
import os
import glob
import logging
import argparse
from datetime import datetime, timezone

import pandas as pd

from ai_v5.config_ai import DATASETS_DIR, BT_CACHE_DIR, HISTORICAL_DATA_SOURCE
from ai_v5.data.feature_schema import (
    FEATURE_COLUMNS, TARGET_COLUMN,
    encode_pattern, encode_regime, encode_source_type,
)
from ai_v5.pipeline.swing_detector import find_swing_points
from ai_v5.pipeline.pattern_rules import detect_16_patterns

logger = logging.getLogger("ai_v5.build_dataset")


# ---------------------------------------------------------------------------
# Nap du lieu nen: 2 nguon co the hoan doi cho nhau (cung tra ve 1 DataFrame
# co cot time/open/high/low/close/volume)
# ---------------------------------------------------------------------------

def _load_candles_csv(symbol: str, timeframe: str, days_back: int) -> pd.DataFrame:
    """Doc nen tu bt_cache/{symbol}_{timeframe}_{Nd}.csv. Chon file co so ngay
    lon nhat <= days_back yeu cau (hoac file lon nhat co san neu khong co ban khop)."""
    pattern = os.path.join(BT_CACHE_DIR, f"{symbol}_{timeframe}_*d.csv")
    candidates = glob.glob(pattern)
    if not candidates:
        logger.warning(f"Không tìm thấy file CSV cache nào khớp {symbol}_{timeframe}_*d.csv trong {BT_CACHE_DIR}")
        return pd.DataFrame()

    def _extract_days(path):
        base = os.path.basename(path)
        try:
            return int(base.split("_")[-1].replace("d.csv", ""))
        except Exception:
            return 0

    candidates.sort(key=_extract_days, reverse=True)  # File có nhiều ngày nhất lên đầu
    chosen = candidates[0]
    for c in candidates:
        if _extract_days(c) <= days_back:
            chosen = c
            break

    df = pd.read_csv(chosen)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    logger.info(f"📂 Đã nạp {len(df)} nến từ cache CSV: {os.path.basename(chosen)}")
    return df


def _load_candles_mt5(symbol: str, timeframe: str, days_back: int) -> pd.DataFrame:
    """Ket noi truc tiep MT5 (chi chay duoc tren may Windows co terminal MT5 dang mo)."""
    import MetaTrader5 as mt5  # import cuc bo, tranh loi ImportError khi khong co MT5 (vd moi truong Linux/test)

    if not mt5.initialize():
        logger.error("❌ Không thể kết nối trực tiếp tới Terminal MT5 bằng thư viện gốc.")
        return pd.DataFrame()

    tf_mapping = {
        "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1,
    }
    mt5_tf = tf_mapping.get(timeframe.upper(), mt5.TIMEFRAME_M15)
    candles_to_copy = int(days_back * 96)  # uoc luong so nen M15 trong days_back ngay

    mt5.symbol_select(symbol, True)
    rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, candles_to_copy)
    if rates is None or len(rates) < 500:
        logger.warning(f"⚠️ Dữ liệu nến quá ngắn cho {symbol}.")
        return pd.DataFrame()

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def _load_candles(symbol: str, timeframe: str, days_back: int, source: str) -> pd.DataFrame:
    if source == "mt5":
        return _load_candles_mt5(symbol, timeframe, days_back)
    return _load_candles_csv(symbol, timeframe, days_back)


def _get_regime_safe(candles_list: list, symbol: str):
    """Goi market_regime.get_regime() neu module co san (chi co tren may co day du code goc bot_xutho4).
    Neu khong import duoc (vd chay doc lap ai_v5), tra ve regime mac dinh trung tinh."""
    try:
        import market_regime
        return market_regime.get_regime(candles_list, symbol)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Ham chinh: quet lich su, khop 16 mau hinh, gan nhan, xuat dataset hop nhat
# ---------------------------------------------------------------------------

def generate_historical_dataset(symbols: list, timeframe: str, days_back: int = 260,
                                 source: str = None) -> pd.DataFrame:
    """
    Quet lich su nen, tu dong ve Dinh/Day va nhan dien 16 Mo hinh gia kinh dien.
    source: "csv" (bt_cache, mac dinh) hoac "mt5" (song, can Windows + MT5 terminal).
    """
    source = source or HISTORICAL_DATA_SOURCE
    logger.info(f"📁 BẮT ĐẦU QUÉT LỊCH SỬ KHAI THÁC 16 MÔ HÌNH GIÁ (nguồn={source}, {days_back} ngày)...")

    all_samples = []
    pattern_stats = {}

    for symbol in symbols:
        logger.info(f"⏳ Đang dựng cấu trúc đỉnh/đáy lịch sử cho {symbol}...")
        df_rates = _load_candles(symbol, timeframe, days_back, source)
        if df_rates.empty or len(df_rates) < 500:
            logger.warning(f"⚠️ Bỏ qua {symbol}: dữ liệu nến quá ngắn hoặc không tải được.")
            continue

        rates_records = df_rates.to_dict(orient="records")

        # 1. Tim toan bo Dinh/Day cau truc
        swings = find_swing_points(df_rates, left_bars=5, right_bars=5)
        logger.info(f"📐 Đã vẽ xong {len(swings)} đỉnh/đáy cho {symbol}. Bắt đầu khớp mô hình...")

        for i in range(200, len(df_rates) - 100):
            current_price = df_rates.iloc[i]["close"]
            current_time = df_rates.iloc[i]["time"]

            swings_before = [s for s in swings if s["index"] < i]
            if len(swings_before) < 5:
                continue

            sub_rates = rates_records[max(0, i - 100):i + 1]
            sub_df = pd.DataFrame(sub_rates)
            atr = (sub_df["high"] - sub_df["low"]).rolling(14).mean().iloc[-1]
            if pd.isna(atr) or atr == 0:
                atr = current_price * 0.001

            match = detect_16_patterns(swings_before, float(current_price), float(atr))
            if not match:
                continue

            regime_res = _get_regime_safe(sub_rates, symbol)

            sl_price, tp_price, direction = match["sl"], match["tp"], match["direction"]
            label = None
            for f_candle in rates_records[i + 1:]:
                high, low = f_candle["high"], f_candle["low"]
                if direction == "BUY":
                    if low <= sl_price:
                        label = 0
                        break
                    if high >= tp_price:
                        label = 1
                        break
                else:
                    if high >= sl_price:
                        label = 0
                        break
                    if low <= tp_price:
                        label = 1
                        break
            if label is None:
                continue  # Lệnh lơ lửng chưa chạm SL/TP thì bỏ qua

            pattern_name = match["pattern"]
            pattern_stats[pattern_name] = pattern_stats.get(pattern_name, 0) + 1

            # Dong goi mau du lieu theo dung SCHEMA HOP NHAT
            prev_close = rates_records[i - 1]["close"] if i > 0 else current_price
            momentum_ratio = (float(current_price) - float(prev_close)) / atr if atr else 0.0

            vn_time = pd.Timestamp(current_time)
            try:
                vn_time = vn_time.tz_localize("UTC").tz_convert("Asia/Ho_Chi_Minh")
            except Exception:
                pass

            sample = {
                "source_type_encoded": encode_source_type("GEOMETRIC_PATTERN"),
                "pattern_encoded": encode_pattern(pattern_name),
                "regime_type_encoded": encode_regime(regime_res.regime if regime_res else "UNKNOWN"),
                "adx_value": float(regime_res.adx) if regime_res else 25.0,
                "rsi_14": 50.0,  # Khong tinh RSI rieng cho mau hinh hoc (mac dinh trung tinh)
                "volume_ratio": float(momentum_ratio),
                "atr_value": float(atr),
                "distance_to_zone_pct": 0.0,  # Khong co khai niem "zone" trong 16 mau hinh co dien
                "hour_of_day": int(vn_time.hour),
                "day_of_week": int(vn_time.weekday()),
                TARGET_COLUMN: label,
                # Cot phu tro de debug/audit (khong dua vao FEATURE_COLUMNS khi train)
                "symbol": symbol,
                "pattern_name": pattern_name,
            }
            all_samples.append(sample)

    if not all_samples:
        logger.warning("Không tìm thấy bất kỳ mẫu hình nào thỏa mãn trong lịch sử.")
        return pd.DataFrame()

    dataset_df = pd.DataFrame(all_samples)
    logger.info("📈 THỐNG KÊ MẪU HÌNH ĐÃ THU THẬP:")
    for pat, count in pattern_stats.items():
        logger.info(f" - {pat}: {count} mẫu")

    ordered_cols = ["symbol", "pattern_name"] + FEATURE_COLUMNS + [TARGET_COLUMN]
    dataset_df = dataset_df[[c for c in ordered_cols if c in dataset_df.columns]]

    os.makedirs(DATASETS_DIR, exist_ok=True)
    filename = f"dataset_geometric_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    output_path = os.path.join(DATASETS_DIR, filename)
    dataset_df.to_csv(output_path, index=False)
    logger.info(f"✅ Đã tạo xong tập dữ liệu chứa {len(dataset_df)} mẫu hình học: {output_path}")

    return dataset_df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Xây dựng dataset 16 mẫu hình giá cho ai_v5")
    parser.add_argument("--source", choices=["csv", "mt5"], default=None, help="Nguồn dữ liệu nến (mặc định: config_ai.HISTORICAL_DATA_SOURCE)")
    parser.add_argument("--days", type=int, default=260, help="Số ngày lịch sử tối đa cần dùng")
    parser.add_argument("--symbols", nargs="+", default=["XAUUSD", "EURUSD", "GBPUSD"])
    parser.add_argument("--timeframe", default="M15")
    args = parser.parse_args()

    generate_historical_dataset(args.symbols, args.timeframe, days_back=args.days, source=args.source)
