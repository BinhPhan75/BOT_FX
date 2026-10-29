# bot_xutho4/ai_v5/data/dataset_builder.py
import os
import sqlite3
import pandas as pd
import logging
from datetime import datetime
from ai_v5.config_ai import DATASETS_DIR
from ai_v5.data.feature_schema import FEATURE_COLUMNS, TARGET_COLUMN
from ai_v5.data.feature_engine import extract_features_from_signal

logger = logging.getLogger("ai_dataset_builder")

# Đường dẫn mặc định tới database của bot v4
DEFAULT_TRADES_DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "trades.db")

class DatasetBuilder:
    def __init__(self, db_path: str = DEFAULT_TRADES_DB):
        self.db_path = os.path.abspath(db_path)
        
    def _connect_db(self):
        return sqlite3.connect(self.db_path)

    def load_closed_trades_from_v4(self) -> pd.DataFrame:
        """
        Đọc các giao dịch đã đóng hoàn toàn từ trades.db của bot v4.
        """
        if not os.path.exists(self.db_path):
            logger.error(f"Không tìm thấy file cơ sở dữ liệu trades.db tại: {self.db_path}")
            return pd.DataFrame()
            
        query = """
        SELECT 
            ticket, symbol, pattern, direction, timeframe, 
            volume_ratio, entry_price, open_time, close_time, 
            close_price, profit
        FROM trades
        WHERE close_time IS NOT NULL AND profit IS NOT NULL
        """
        try:
            with self._connect_db() as conn:
                df = pd.read_sql_query(query, conn)
            logger.info(f"Đã tải {len(df)} giao dịch đã đóng từ trades.db")
            return df
        except Exception as e:
            logger.error(f"Lỗi khi đọc bảng trades từ SQLite: {str(e)}", exc_info=True)
            return pd.DataFrame()

    def build_training_dataset(self, candles_history_provider=None) -> str:
        """
        Xây dựng tập dữ liệu huấn luyện bằng cách gán nhãn và trích xuất đặc trưng.
        """
        trades_df = self.load_closed_trades_from_v4()
        if trades_df.empty:
            logger.warning("Không có dữ liệu giao dịch nào để xây dựng dataset.")
            return ""

        dataset_rows = []
        
        if candles_history_provider is None:
            logger.warning("Chưa cung cấp candles_history_provider. Sử dụng bối cảnh nến tối giản.")

        for _, trade in trades_df.iterrows():
            try:
                # Gán nhãn nhị phân: Có lời -> 1, Lỗ/Hòa -> 0
                is_win = 1 if trade["profit"] > 0 else 0
                
                # Giả lập lại đối tượng Signal tại thời điểm vào lệnh
                candles_context = []
                if candles_history_provider:
                    candles_context = candles_history_provider(
                        symbol=trade["symbol"], 
                        timeframe=trade["timeframe"] if trade["timeframe"] else "H1",  
                        end_time=trade["open_time"], 
                        count=120
                    )
                
                if not candles_context:
                    # Fallback tạo nến giả lập từ thông tin lệnh để tránh crash bộ trích xuất
                    candles_context = [{
                        "time": trade["open_time"],
                        "open": trade["entry_price"],
                        "high": trade["entry_price"],
                        "low": trade["entry_price"],
                        "close": trade["entry_price"],
                        "volume": 100
                    }]

                # Mock một Signal object tương thích với cấu trúc của Feature Engine
                class MockSignal:
                    def __init__(self, t):
                        self.symbol = t["symbol"]
                        self.pattern = t["pattern"]
                        self.price = t["entry_price"]
                        self.timeframe = t["timeframe"] if t["timeframe"] else "H1"
                        self.zone_price = t["entry_price"]  # Database không có zone_price, dùng entry_price làm gốc
                        self.candles_context = candles_context
                        self.volume_ratio = t["volume_ratio"] if t["volume_ratio"] is not None else 1.0
                        self.time = t["open_time"]

                sig_obj = MockSignal(trade)
                
                # Trích xuất các đặc trưng
                features = extract_features_from_signal(sig_obj)
                features[TARGET_COLUMN] = is_win
                features["trade_id"] = trade["ticket"]  
                features["ticket"] = trade["ticket"]
                
                dataset_rows.append(features)
                
            except Exception as e:
                logger.error(f"Lỗi khi xử lý đặc trưng cho trade ticket {trade['ticket']}: {str(e)}")
                continue

        if not dataset_rows:
            logger.error("Không trích xuất được bất kỳ dòng dữ liệu đặc trưng nào.")
            return ""

        # Tạo DataFrame và lưu thành file CSV
        final_df = pd.DataFrame(dataset_rows)
        
        # Đảm bảo thứ tự các cột tuân thủ định dạng của Schema
        ordered_cols = ["trade_id", "ticket"] + FEATURE_COLUMNS + [TARGET_COLUMN]
        final_df = final_df[[c for c in ordered_cols if c in final_df.columns]]

        if not os.path.exists(DATASETS_DIR):
            os.makedirs(DATASETS_DIR)

        filename = f"dataset_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        output_path = os.path.join(DATASETS_DIR, filename)
        final_df.to_csv(output_path, index=False)
        
        logger.info(f"Đã xây dựng thành công tập dữ liệu huấn luyện: {output_path} ({len(final_df)} dòng)")
        return output_path

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    builder = DatasetBuilder()
    builder.build_training_dataset()