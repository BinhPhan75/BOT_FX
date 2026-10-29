# bot_xutho4/ai_v5/ml/predictor.py
import os
import sqlite3
import json
import logging
from datetime import datetime
import pandas as pd
from ai_v5.config_ai import AI_WINRATE_THRESHOLD, AI_BASE_DIR
from ai_v5.data.feature_schema import validate_features
from ai_v5.ml.model_manager import ModelManager

logger = logging.getLogger("ai_predictor")

SHADOW_LOG_DB_PATH = os.path.join(AI_BASE_DIR, "cache", "shadow_log.db")


def _ensure_shadow_log_table(db_path: str = SHADOW_LOG_DB_PATH):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS shadow_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            pattern TEXT,
            win_probability REAL,
            decision TEXT,
            features_json TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


class AIPredictor:
    """
    AIPredictor chịu trách nhiệm nạp mô hình AI đang vận hành
    và thực hiện dự đoán xác suất thắng cho các tín hiệu giao dịch real-time.
    """
    def __init__(self):
        self.model_manager = ModelManager()
        self.model = None
        self.metadata = None
        self._load_active_model()
        _ensure_shadow_log_table()

    def _load_active_model(self):
        """Nạp bộ não AI mới nhất từ hệ thống quản lý mô hình"""
        self.model, self.metadata = self.model_manager.load_latest_model()
        if self.model is None:
            logger.error("Không thể khởi tạo AIPredictor do chưa có mô hình 'latest_model.pkl' hợp lệ.")

    def predict_signal(self, feature_dict: dict) -> tuple:
        """
        Thực hiện chấm điểm tín hiệu dựa trên đặc trưng truyền vào.
        Trả về: (decision: bool, win_rate: float)
        """
        # Kiểm tra nếu mô hình chưa được nạp, thử nạp lại
        if self.model is None:
            self._load_active_model()
            if self.model is None:
                logger.warning("Mô hình chưa sẵn sàng. Tự động DUYỆT mặc định theo cấu trúc an toàn của v4.")
                return True, 0.50

        try:
            # 1. Chuyển đổi dữ liệu dictionary thành DataFrame đơn dòng để chuẩn hóa đầu vào
            df_input = pd.DataFrame([feature_dict])

            # 2. Xác thực và ép kiểu đúng Schema quy định để tránh lệch cột khi đưa vào LightGBM
            X_scored = validate_features(df_input)

            # 3. Dự đoán xác suất của các lớp [Xác suất Thua, Xác suất Thắng]
            # LightGBM trả về mảng 2 chiều, lấy dòng đầu tiên [0] và cột của lớp 1 (Thắng) [1]
            probabilities = self.model.predict_proba(X_scored)
            win_rate = float(probabilities[0][1])

            # 4. Đưa ra quyết định dựa trên ngưỡng cấu hình hệ thống
            decision = win_rate >= AI_WINRATE_THRESHOLD

            logger.info(f"AI Chấm điểm hoàn tất: WinRate = {win_rate:.2%}, Khấu vị hệ thống định biên: {AI_WINRATE_THRESHOLD:.2%}")
            return decision, win_rate

        except Exception as e:
            logger.error(f"Lỗi hệ thống xảy ra trong quá trình suy luận AI: {str(e)}", exc_info=True)
            # Cơ chế Fallback an toàn: Nếu AI lỗi, không chặn luồng lệnh của bot v4
            return True, 0.50

    def predict_probability(self, feature_dict: dict) -> float:
        """
        Alias dùng bởi shadow_runner.py: chỉ trả về xác suất thắng (float),
        không kèm quyết định duyệt/chặn (quyết định do shadow_runner tự so với ngưỡng).
        """
        _, win_rate = self.predict_signal(feature_dict)
        return win_rate

    def save_shadow_log_to_db(self, signal_obj, win_prob: float, decision: str) -> bool:
        """
        Ghi lại quyết định Shadow Mode của AI v5 vào SQLite riêng (ai_v5/cache/shadow_log.db),
        để sau này đối chiếu với kết quả thật của lệnh (khi lệnh đóng trong trades.db của bot v4).
        """
        try:
            conn = sqlite3.connect(SHADOW_LOG_DB_PATH)
            extra = getattr(signal_obj, "extra", {}) or {}
            conn.execute(
                "INSERT INTO shadow_log (symbol, pattern, win_probability, decision, features_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    getattr(signal_obj, "symbol", ""),
                    getattr(signal_obj, "pattern", ""),
                    float(win_prob),
                    decision,
                    json.dumps(extra, ensure_ascii=False, default=str),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Lỗi khi ghi shadow log vào DB: {str(e)}", exc_info=True)
            return False


if __name__ == "__main__":
    # Test nhanh tính năng suy luận của Predictor
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("\n🔍 Đang kiểm thử bộ suy luận Predictor...")

    predictor = AIPredictor()

    # Mẫu thử đặc trưng giả định (đúng schema hợp nhất)
    mock_features = {
        "source_type_encoded": 0,
        "pattern_encoded": 1,
        "regime_type_encoded": 1,
        "adx_value": 28.0,
        "rsi_14": 62.5,
        "volume_ratio": 1.8,
        "atr_value": 2.1,
        "distance_to_zone_pct": 0.05,
        "hour_of_day": 19,
        "day_of_week": 2,
    }

    decision, win_rate = predictor.predict_signal(mock_features)
    print(f"📊 Kết quả test: Quyết định = {decision} | Xác suất thắng = {win_rate:.2%}")