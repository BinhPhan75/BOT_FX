# ai_v5/pipeline/build_dataset.py
import os
import pandas as pd
import logging
import MetaTrader5 as mt5
from datetime import datetime

import config
import mt5_client
import market_regime

# 🚨 IMPORT BỘ PHÁT HIỆN 16 MÔ HÌNH CHUYÊN NGHIỆP 🚨
from ai_v5.pipeline.swing_detector import find_swing_points
from ai_v5.pipeline.pattern_rules import detect_16_patterns

logger = logging.getLogger("watcher.ai_learner")

def assemble_training_set(db_df: pd.DataFrame) -> pd.DataFrame:
    if db_df.empty:
        return pd.DataFrame()
    if "pnl" in db_df.columns:
        db_df["target"] = db_df["pnl"].apply(lambda x: 1 if x > 0 else 0)
    else:
        db_df["target"] = 0
    return db_df

def generate_historical_dataset(symbols: list, timeframe: str, days_back: int = 365) -> pd.DataFrame:
    """
    Quét lịch sử nến, tự động vẽ Đỉnh/Đáy và nhận diện 16 Mô hình giá kinh điển.
    Ghi nhận bối cảnh và kết quả thực tế để AI V5 học quy luật.
    """
    logger.info(f"📁 BẮT ĐẦU QUÉT LỊCH SỬ KHAI THÁC 16 MÔ HÌNH GIÁ TRONG {days_back} NGÀY...")
    
    if not mt5.initialize():
        logger.error("Không thể kết nối MT5.")
        return pd.DataFrame()
        
    tf_mapping = {
        'M1': mt5.TIMEFRAME_M1, 'M5': mt5.TIMEFRAME_M5, 'M15': mt5.TIMEFRAME_M15,
        'M30': mt5.TIMEFRAME_M30, 'H1': mt5.TIMEFRAME_H1, 'H4': mt5.TIMEFRAME_H4, 'D1': mt5.TIMEFRAME_D1
    }
    
    mt5_tf = tf_mapping.get(timeframe.upper(), mt5.TIMEFRAME_M15)
    candles_to_copy = int(days_back * 96) # Ước lượng số nến M15 trong 1 năm
    all_samples = []
    
    # Theo dõi thống kê các mô hình nhặt được
    pattern_stats = {}
    
    for symbol in symbols:
        logger.info(f"⏳ Đang dựng cấu trúc đỉnh/đáy lịch sử cho {symbol}...")
        mt5.symbol_select(symbol, True)
        rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, candles_to_copy)
        
        if rates is None or len(rates) < 500:
            logger.warning(f"⚠️ Dữ liệu nến quá ngắn cho {symbol}.")
            continue
            
        df_rates = pd.DataFrame(rates)
        df_rates['time'] = pd.to_datetime(df_rates['time'], unit='s')
        
        # 1. Tìm toàn bộ Đỉnh/Đáy cấu trúc trong suốt 1 năm qua
        swings = find_swing_points(df_rates, left_bars=5, right_bars=5)
        logger.info(f"📐 Đã vẽ xong {len(swings)} đỉnh/đáy cho {symbol}. Bắt đầu khớp mô hình...")
        
        # Duyệt nến để khớp mô hình
        for i in range(200, len(df_rates) - 100):
            current_time = df_rates.iloc[i]['time']
            current_price = df_rates.iloc[i]['close']
            
            # Lọc các đỉnh/đáy đã xuất hiện TRƯỚC thời điểm nến hiện tại (để tránh lấy dữ liệu tương lai)
            swings_before = [s for s in swings if s['index'] < i]
            if len(swings_before) < 5:
                continue
                
            # Lấy mảng nến con phục vụ tính ATR và Market Regime
            sub_rates_raw = rates[i-100:i+1]
            sub_rates_df = pd.DataFrame(sub_rates_raw)
            sub_rates_df['time'] = pd.to_datetime(sub_rates_df['time'], unit='s')
            
            # Tính chỉ báo ATR động làm sai số chuẩn
            atr = (sub_rates_df['high'] - sub_rates_df['low']).rolling(14).mean().iloc[-1]
            if pd.isna(atr) or atr == 0:
                atr = current_price * 0.001
                
            # 2. Khớp 16 mô hình toán học
            match = detect_16_patterns(swings_before, current_price, atr)
            if not match:
                continue
                
            # 3. Đã khớp mô hình -> Lấy bối cảnh thị trường lúc đó làm Features
            sub_rates_list = sub_rates_df.to_dict(orient='records')
            regime_res = market_regime.get_regime(sub_rates_list, symbol)
            
            # 4. Gán nhãn bằng cách chạy nến tương lai xem chạm SL hay TP trước (Theo đúng SL/TP của mô hình)
            sl_price = match['sl']
            tp_price = match['tp']
            direction = match['direction']
            
            label = None
            pnl = 0.0
            
            for idx, f_candle in df_rates.iloc[i+1:].iterrows():
                high = f_candle['high']
                low = f_candle['low']
                
                if direction == "BUY":
                    if low <= sl_price:
                        label = 0  # Thua
                        pnl = sl_price - current_price
                        break
                    if high >= tp_price:
                        label = 1  # Thắng
                        pnl = tp_price - current_price
                        break
                else: # SELL
                    if high >= sl_price:
                        label = 0  # Thua
                        pnl = current_price - sl_price
                        break
                    if low <= tp_price:
                        label = 1  # Thắng
                        pnl = current_price - tp_price
                        break
                        
            if label is None:
                continue # Lệnh lơ lửng không chạm SL/TP thì bỏ qua
                
            # Cập nhật thống kê
            pattern_name = match['pattern']
            pattern_stats[pattern_name] = pattern_stats.get(pattern_name, 0) + 1
            
            # Đóng gói mẫu dữ liệu đặc trưng chuẩn
            sample = {
                "symbol": symbol,
                "source_type": "GEOMETRIC_PATTERN",
                "pattern": pattern_name,
                "regime_type": regime_res.regime,
                "adx_value": regime_res.adx,
                "volume_ratio": (current_price - df_rates.iloc[i-1]['close']) / atr, # Momentum tương đối thay cho volume_ratio cũ
                "close_price": current_price,
                "target": label,
                "pnl": pnl
            }
            all_samples.append(sample)
            
    if not all_samples:
        logger.warning("Không tìm thấy bất kỳ mẫu hình nào thỏa mãn trong lịch sử.")
        return pd.DataFrame()
        
    dataset_df = pd.DataFrame(all_samples)
    logger.info("📈 THỐNG KÊ CHI TIẾT MẪU HÌNH ĐÃ THU THẬP ĐƯỢC:")
    for pat, count in pattern_stats.items():
        logger.info(f" - {pat}: {count} mẫu")
        
    logger.info(f"✅ Đã tạo xong tập dữ liệu KHỔNG LỒ chứa {len(dataset_df)} mẫu hình học xịn sò!")
    return dataset_df