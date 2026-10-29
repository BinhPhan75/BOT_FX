# bot_xutho4/ai_v5/ml/model_manager.py
import os
import joblib
import json
import logging
import glob
from datetime import datetime
from ai_v5.config_ai import MODELS_DIR

logger = logging.getLogger("ai_model_manager")

class ModelManager:
    """
    ModelManager chịu trách nhiệm quản lý vòng đời của các mô hình học máy (ML Models).
    Hỗ trợ lưu trữ, tải, lập phiên bản và quản lý siêu dữ liệu (metadata) của mô hình.
    """
    def __init__(self, models_dir: str = MODELS_DIR):
        self.models_dir = os.path.abspath(models_dir)
        if not os.path.exists(self.models_dir):
            os.makedirs(self.models_dir)
            logger.info(f"Đã tạo thư mục lưu trữ mô hình: {self.models_dir}")

    def save_model(self, model, metrics: dict, model_name: str = None) -> tuple:
        """
        Lưu mô hình ML kèm theo file metadata ghi nhận các chỉ số hiệu suất (accuracy, precision, f1...).
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if not model_name:
            model_name = f"model_{timestamp}"

        model_filename = f"{model_name}.pkl"
        meta_filename = f"{model_name}_meta.json"
        
        model_path = os.path.join(self.models_dir, model_filename)
        meta_path = os.path.join(self.models_dir, meta_filename)

        try:
            # 1. Lưu file model vật lý
            joblib.dump(model, model_path)
            logger.info(f"Đã lưu file mô hình tại: {model_path}")

            # 2. Lưu thông tin metadata đi kèm
            metadata = {
                "model_name": model_name,
                "timestamp": timestamp,
                "metrics": metrics,
                "features_used": metrics.get("features_used", []),
                "framework": "LightGBM"
            }
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=4, ensure_ascii=False)
            logger.info(f"Đã lưu file metadata đi kèm tại: {meta_path}")

            # 3. Đồng bộ hóa làm mô hình mặc định (latest_model.pkl)
            latest_model_path = os.path.join(self.models_dir, "latest_model.pkl")
            latest_meta_path = os.path.join(self.models_dir, "latest_model_meta.json")
            
            joblib.dump(model, latest_model_path)
            with open(latest_meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=4, ensure_ascii=False)
            logger.info("Đã cập nhật mô hình mới nhất thành 'latest_model.pkl'")

            return model_path, meta_path
        except Exception as e:
            logger.error(f"Gặp lỗi khi lưu mô hình và metadata: {str(e)}", exc_info=True)
            return "", ""

    def load_latest_model(self):
        """
        Nạp mô hình mặc định 'latest_model.pkl' đang hoạt động.
        Trả về (model, metadata). Trả về (None, None) nếu không tìm thấy hoặc lỗi.
        """
        latest_model_path = os.path.join(self.models_dir, "latest_model.pkl")
        latest_meta_path = os.path.join(self.models_dir, "latest_model_meta.json")

        if not os.path.exists(latest_model_path):
            logger.warning("Không tìm thấy file mô hình mặc định 'latest_model.pkl'")
            return None, None

        try:
            model = joblib.load(latest_model_path)
            metadata = {}
            if os.path.exists(latest_meta_path):
                with open(latest_meta_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
            logger.info(f"Đã nạp thành công mô hình 'latest_model.pkl' (Tạo lúc: {metadata.get('timestamp', 'N/A')})")
            return model, metadata
        except Exception as e:
            logger.error(f"Lỗi khi nạp mô hình 'latest_model.pkl': {str(e)}", exc_info=True)
            return None, None

    def get_all_models_report(self) -> list:
        """
        Quét toàn bộ thư mục models và trả về danh sách lịch sử tất cả các phiên bản model kèm chỉ số của chúng.
        """
        meta_files = glob.glob(os.path.join(self.models_dir, "*_meta.json"))
        models_history = []
        for file_path in meta_files:
            if "latest_model" in file_path:
                continue
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    meta_data = json.load(f)
                models_history.append(meta_data)
            except Exception as e:
                logger.error(f"Không thể đọc file metadata {file_path}: {str(e)}")
        
        # Sắp xếp theo thứ tự thời gian mới nhất lên đầu
        models_history.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return models_history


if __name__ == "__main__":
    # Test thử hoạt động của ModelManager độc lập
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("\n🔍 Đang chạy thử nghiệm thực tế ModelManager...")
    
    manager = ModelManager()
    
    # Tạo thử một class giả lập thay cho mô hình thật để test tính năng lưu/đọc
    class DummyModel:
        def predict(self, X):
            return [1] * len(X)
            
    dummy = DummyModel()
    test_metrics = {
        "accuracy": 0.72,
        "precision": 0.68,
        "features_used": ["rsi_14", "volume_ratio"]
    }
    
    # 1. Test save
    m_path, meta_path = manager.save_model(dummy, test_metrics, "model_test_unit")
    if m_path:
        print("✅ Lưu mô hình kiểm thử và đồng bộ hóa 'latest_model.pkl' thành công!")
        
    # 2. Test load
    model, meta = manager.load_latest_model()
    if model and meta:
        print(f"✅ Nạp thành công mô hình. Chỉ số kiểm nghiệm cũ: Accuracy={meta['metrics']['accuracy']}")
        
    # 3. Test quét lịch sử
    history = manager.get_all_models_report()
    print(f"✅ Đang lưu trữ tổng cộng {len(history)} phiên bản mô hình trong lịch sử.")
    
    # Dọn dẹp file test để không làm bẩn thư mục model thật
    for p in [m_path, meta_path]:
        if os.path.exists(p):
            os.remove(p)