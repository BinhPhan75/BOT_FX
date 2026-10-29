# bot_xutho4/ai_v5/ml/explain.py
import numpy as np
import pandas as pd
import logging
from ai_v5.data.feature_schema import FEATURE_COLUMNS
from ai_v5.ml.model_manager import ModelManager

logger = logging.getLogger("ai_explain")

class AIExplainer:
    """
    AIExplainer cung cấp khả năng giải thích các quyết định của mô hình AI,
    bóc tách các yếu tố kỹ thuật chính ảnh hưởng đến xác suất thắng/thua của lệnh.
    """
    def __init__(self):
        self.model_manager = ModelManager()
        
    def get_feature_importance(self) -> dict:
        """
        Trích xuất mức độ quan trọng của các đặc trưng (Feature Importance) từ mô hình đang hoạt động.
        """
        model, metadata = self.model_manager.load_latest_model()
        if model is None:
            logger.warning("Không thể lấy trọng số tính năng do chưa có mô hình active.")
            return {}

        try:
            # Lấy giá trị importance trực tiếp từ LightGBM
            importances = model.feature_importances_
            total = sum(importances) if sum(importances) > 0 else 1
            
            # Khớp nối với danh sách cột đặc trưng
            importance_dict = {
                col: float(imp / total) for col, imp in zip(FEATURE_COLUMNS, importances)
            }
            
            # Sắp xếp giảm dần theo mức độ ảnh hưởng
            sorted_importance = dict(sorted(importance_dict.items(), key=lambda item: item[1], reverse=True))
            return sorted_importance
        except Exception as e:
            logger.error(f"Lỗi khi tính toán tầm quan trọng của tính năng: {str(e)}")
            return {}

    def explain_single_prediction(self, feature_dict: dict) -> str:
        """
        Giải thích nhanh lý do tại sao AI đưa ra quyết định dựa trên các thông số kỹ thuật đầu vào.
        """
        importance = self.get_feature_importance()
        if not importance:
            return "Không có dữ liệu giải thích mô hình."

        # Lấy đặc trưng có tầm ảnh hưởng lớn nhất để phân tích
        top_feature = list(importance.keys())[0]
        top_value = feature_dict.get(top_feature, "N/A")

        explanation = f"Tư duy chính của AI dựa trên biến trọng yếu [{top_feature}] (chiếm {importance[top_feature]:.1%} trọng số quyết định). "
        
        # Đưa ra các gợi ý định tính dựa trên giá trị thực tế
        if top_feature == "rsi_14":
            if float(top_value) > 70:
                explanation += f"Giá trị RSI hiện tại ({top_value:.1f}) đang rơi vào vùng quá mua, tăng rủi ro đảo chiều."
            elif float(top_value) < 30:
                explanation += f"Giá trị RSI hiện tại ({top_value:.1f}) đang rơi vào vùng quá bán, rủi ro bán đuổi cao."
            else:
                explanation += f"Động lượng RSI ổn định ở mức {top_value:.1f}."
        elif top_feature == "atr_value":
            explanation += f"Độ biến động thị trường (ATR) đo được là {top_value:.4f}, ảnh hưởng lớn đến biên độ quét SL."
        elif top_feature == "distance_to_zone_pct":
            explanation += f"Khoảng cách tới vùng Zone an toàn là {top_value:.3f}%, ảnh hưởng đến độ tối ưu của điểm Entry."
        else:
            explanation += f"Giá trị ghi nhận của đặc trưng này là {top_value}."

        return explanation

if __name__ == "__main__":
    # Test thử hoạt động của bộ giải thích AI độc lập
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("\n🔍 Đang chạy kiểm thử bộ giải thích AI (Explainer)...")
    
    explainer = AIExplainer()
    
    # Đọc thử trọng số của mô hình vừa huấn luyện thành công trước đó
    importance = explainer.get_feature_importance()
    print("\n📊 Bảng xếp hạng mức độ ảnh hưởng của các đặc trưng kỹ thuật:")
    for col, score in importance.items():
        print(f"  - {col}: {score:.2%}")
        
    # Giả lập giải thích 1 lệnh
    mock_features = {"rsi_14": 74.5, "volume_ratio": 1.5, "atr_value": 0.0025, "distance_to_zone_pct": 0.08}
    reason = explainer.explain_single_prediction(mock_features)
    print(f"\n💡 AI giải thích phân tích: {reason}")