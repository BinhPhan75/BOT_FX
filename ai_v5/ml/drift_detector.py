# bot_xutho4/ai_v5/ml/drift_detector.py
import os
import numpy as np
import pandas as pd
import logging
from ai_v5.data.feature_schema import FEATURE_COLUMNS

logger = logging.getLogger("ai_drift_detector")

class DataDriftDetector:
    """
    Giám sát và phát hiện sự thay đổi phân phối dữ liệu của thị trường (Data Drift).
    Cảnh báo khi các chỉ số kỹ thuật hiện tại lệch quá xa so với tập dữ liệu huấn luyện lịch sử.
    """
    def __init__(self, reference_df: pd.DataFrame = None):
        self.reference_df = reference_df
        # Ngưỡng cảnh báo độ lệch chuẩn hóa (Z-score biên độ)
        self.drift_threshold = 2.0 

    def calculate_drift_simple(self, current_features_list: list) -> dict:
        """
        So sánh dữ liệu các lệnh real-time gần đây với tập dữ liệu gốc.
        current_features_list: Danh sách các dict đặc trưng thu thập được gần đây từ live/shadow.
        """
        drift_report = {"has_drift": False, "details": {}}
        
        if self.reference_df is None or self.reference_df.empty:
            logger.warning("Chưa nạp dữ liệu huấn luyện gốc làm mốc so sánh (Reference Data).")
            return drift_report

        if not current_features_list or len(current_features_list) < 5:
            logger.info("Chưa đủ số lượng mẫu lệnh gần đây để đánh giá độ lệch phân phối (Tối thiểu 5 mẫu).")
            return drift_report

        df_current = pd.DataFrame(current_features_list)
        drift_count = 0

        for col in FEATURE_COLUMNS:
            if col not in df_current.columns or col not in self.reference_df.columns:
                continue
            
            # Tính toán giá trị trung bình lịch sử và hiện tại
            ref_mean = self.reference_df[col].mean()
            ref_std = self.reference_df[col].std() if self.reference_df[col].std() != 0 else 1.0
            curr_mean = df_current[col].mean()

            # Tính toán chỉ số Z-score chênh lệch phân phối
            z_score = abs(curr_mean - ref_mean) / ref_std
            
            is_drifted = z_score > self.drift_threshold
            drift_report["details"][col] = {
                "ref_mean": float(ref_mean),
                "current_mean": float(curr_mean),
                "deviation_score": float(z_score),
                "drift_detected": bool(is_drifted)
            }

            if is_drifted:
                drift_count += 1
                logger.warning(f"🚨 Phát hiện Drift tại đặc trưng '{col}': Độ lệch score = {z_score:.2f}")

        # Nếu có trên 30% số lượng đặc trưng bị lệch, kích hoạt cảnh báo hệ thống
        if drift_count / len(FEATURE_COLUMNS) >= 0.3:
            drift_report["has_drift"] = True
            logger.critical("🚨 CẢNH BÁO: Cấu trúc thị trường đã dịch chuyển lớn so với dữ liệu huấn luyện cũ! Đề xuất re-train lại AI.")

        return drift_report

if __name__ == "__main__":
    # Test nhanh cơ chế phát hiện lệch dữ liệu
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("\n🔍 Đang kiểm thử bộ giám sát Data Drift...")
    
    # Giả lập dữ liệu gốc (Reference Data)
    np.random.seed(42)
    mock_ref = pd.DataFrame({
        "rsi_14": np.random.normal(50, 10, 100),
        "volume_ratio": np.random.normal(1.0, 0.2, 100),
        "atr_value": np.random.normal(1.5, 0.3, 100),
        "distance_to_zone_pct": np.random.normal(0.05, 0.02, 100),
        "pattern_encoded": np.random.choice([1, 2], 100),
        "hour_of_day": np.random.randint(0, 24, 100),
        "day_of_week": np.random.randint(0, 5, 100)
    })

    # Giả lập dữ liệu live hiện tại bị lệch mạnh (ví dụ thị trường bỗng nhiên biến động mạnh, rsi và atr tăng vọt)
    mock_live = [
        {"rsi_14": 75.0, "volume_ratio": 2.5, "atr_value": 3.8, "distance_to_zone_pct": 0.15, "pattern_encoded": 1, "hour_of_day": 10, "day_of_week": 1}
        for _ in range(5)
    ]

    detector = DataDriftDetector(mock_ref)
    report = detector.calculate_drift_simple(mock_live)
    print(f"\n📊 Trạng thái Drift tổng quan: {report['has_drift']}")