# ai_v5/pipeline/predict_pipeline.py
import os
import joblib

class PredictPipeline:
    def __init__(self, model_path="ai_v5/models/latest_model.pkl"):
        self.model_path = model_path
        self.model = None
        self.load_model()

    def load_model(self):
        if os.path.exists(self.model_path):
            self.model = joblib.load(self.model_path)

    def predict_live(self, feature_vector: list) -> float:
        """Trả về xác suất thắng của lệnh (từ 0.0 đến 1.0)."""
        if self.model is None:
            return 1.0 # Cơ chế dự phòng: Nếu chưa có AI model, trả về 1.0 để không chặn nhầm lệnh v4 gốc
        
        # Biến đổi mảng thành dạng 2D matrix để nạp vào mô hình học máy
        prob = self.model.predict_proba([feature_vector])[0][1]
        return float(prob)