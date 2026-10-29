# bot_xutho4/ai_v5/ml/ai_learner.py
import os
import time
import logging
import sqlite3
import pandas as pd

from ai_v5.config_ai import AI_BASE_DIR
from ai_v5.ml.ml_trainer import MLTrainer
from ai_v5.ml.drift_detector import DataDriftDetector
from ai_v5.ml.model_manager import ModelManager

logger = logging.getLogger("watcher.ai_learner")

class AILearner:
    """
    Quản lý chu kỳ quét phát hiện Drift và tự động tái huấn luyện (Re-training)
    riêng cho phân hệ học máy AI v5, tách biệt hoàn toàn với learner v3 của Bot v4.
    """
    def __init__(self, check_interval_seconds: int = 86400):
        self.check_interval = check_interval_seconds
        # Trỏ chuẩn xác về db trades ở thư mục gốc
        self.db_path = os.path.abspath(os.path.join(AI_BASE_DIR, "..", "trades.db"))
        self.model_manager = ModelManager()

    def _fetch_historical_reference_data(self) -> pd.DataFrame:
        if not os.path.exists(self.db_path):
            return pd.DataFrame()
        try:
            # Sử dụng kết nối an toàn để đọc dữ liệu
            conn = sqlite3.connect(self.db_path)
            df = pd.read_sql_query("SELECT * FROM trades", conn)
            conn.close()
            return df
        except Exception as e:
            logger.error(f"Lỗi đọc DB tham chiếu: {str(e)}")
            return pd.DataFrame()

    def check_and_retrain(self) -> bool:
        logger.info("🔄 [AI v5] Đang kiểm tra định kỳ phân phối thị trường (Data Drift)...")
        
        ref_df = self._fetch_historical_reference_data()
        if ref_df.empty or len(ref_df) < 20:
            logger.info("⚠️ Số lượng lệnh thực tế chưa đủ để đánh giá Drift cho mô hình AI. Bỏ qua.")
            return False

        # Lấy mẫu lệnh gần nhất để gác cổng
        recent_trades = ref_df.tail(10).to_dict(orient="records")
        detector = DataDriftDetector(ref_df)
        drift_report = detector.calculate_drift_simple(recent_trades)
        
        if drift_report.get("has_drift", False):
            logger.critical("🚨 PHÁT HIỆN MARKET DRIFT! Kích hoạt luồng huấn luyện lại mô hình LightGBM...")
            try:
                # Gọi trainer của tầng ML huấn luyện lại cây quyết định
                trainer = MLTrainer()
                new_model_path = trainer.train()
                if new_model_path:
                    logger.info(f"🎉 Mô hình AI mới đã được cập nhật thành công: {new_model_path}")
                    return True
            except Exception as e:
                logger.error(f"Quá trình Auto Re-train của AI gặp lỗi: {str(e)}")
                return False
        else:
            logger.info("✅ Phân phối thị trường ổn định. Mô hình AI hiện tại vẫn đảm bảo độ chính xác.")
            return False

    def run_forever(self):
        logger.info(f"🚀 AI Learner Daemon đã khởi chạy ngầm (Chu kỳ: {self.check_interval} giây).")
        while True:
            try:
                self.check_and_retrain()
            except Exception as e:
                logger.error(f"Lỗi vòng lặp AI Learner: {str(e)}")
            time.sleep(self.check_interval)

if __name__ == "__main__":
    learner = AILearner()
    learner.check_and_retrain()