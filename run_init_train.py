# run_init_train.py
import logging
import sys
import os

# Đảm bảo hệ thống nhận diện đúng thư mục root
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ai_v5.pipeline.build_dataset import generate_historical_dataset
from ai_v5.pipeline.train_pipeline import execute_train_pipeline

# Cấu hình log hiển thị ra màn hình cho anh dễ theo dõi
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ai_init")

def main():
    logger.info("🚀 BẮT ĐẦU KÍCH HOẠT TIẾN TRÌNH AI V5 TỰ HỌC CHỦ ĐỘNG...")
    
    # Cấu hình tham số quét lịch sử: 3 cặp tiền, khung M15, quét ngược 365 ngày
    symbols = ['XAUUSD', 'EURUSD', 'GBPUSD']
    timeframe = 'M15'
    days_back = 1095 
    
    # 1. Tự động cào dữ liệu lịch sử lớn từ MT5 và giả lập tìm mọi Pattern quá khứ
    raw_dataset = generate_historical_dataset(symbols=symbols, timeframe=timeframe, days_back=days_back)
    
    if raw_dataset.empty:
        logger.error("❌ Không thể tạo tập dữ liệu lịch sử. Vui lòng kiểm tra kết nối MT5.")
        return
        
    # 2. Đẩy tập dữ liệu hàng ngàn mẫu này vào Pipeline để huấn luyện LightGBM
    model_path = execute_train_pipeline(raw_dataset)
    
    if model_path:
        logger.info(f"🎉 XUẤT SẮC! Mô hình AI v5 đầu tiên đã học xong dữ liệu 1 năm và lưu tại: {model_path}")
    else:
        logger.error("❌ Quá trình huấn luyện Pipeline thất bại.")

if __name__ == "__main__":
    main()