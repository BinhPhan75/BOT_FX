# bot_xutho4/ai_v5/ml/ml_trainer.py
import os
import glob
import logging
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, classification_report
import lightgbm as lgb

from ai_v5.config_ai import DATASETS_DIR
from ai_v5.data.feature_schema import FEATURE_COLUMNS
from ai_v5.data.data_loader import DataLoader
from ai_v5.ml.model_manager import ModelManager
logger = logging.getLogger("ai_ml_trainer")

class MLTrainer:
    """
    MLTrainer chịu trách nhiệm cấu hình tham số, huấn luyện mô hình LightGBM
    và đánh giá chi tiết các chỉ số hiệu suất trước khi đóng gói mô hình.
    """
    def __init__(self, dataset_path: str = None, use_combined: bool = True):
        self.model_manager = ModelManager()
        if dataset_path:
            self.dataset_path = dataset_path
        elif use_combined:
            self.dataset_path = self._get_combined_dataset()
        else:
            self.dataset_path = self._get_latest_dataset()

    def _get_combined_dataset(self) -> str:
        """Gộp mọi dataset_*.csv hiện có (cả V4_SIGNAL và GEOMETRIC_PATTERN) thành 1 tập train duy nhất."""
        combined_path = DataLoader.combine_all_datasets(DATASETS_DIR)
        if not combined_path:
            return self._get_latest_dataset()
        return combined_path

    def _get_latest_dataset(self) -> str:
        """Tự động quét và lấy file dataset CSV mới nhất trong thư mục lưu trữ"""
        list_files = glob.glob(os.path.join(DATASETS_DIR, "dataset_*.csv"))
        if not list_files:
            raise FileNotFoundError("Không tìm thấy bất kỳ file dataset CSV nào trong thư mục quy định.")
        return max(list_files, key=os.path.getctime)

    def train(self, test_size: float = 0.2, random_state: int = 42):
        """
        Kích hoạt luồng huấn luyện mô hình học máy chuẩn chỉnh.
        """
        if not self.dataset_path:
            logger.error("Không xác định được đường dẫn tập dữ liệu để huấn luyện.")
            return

        logger.info(f"Bắt đầu quy trình huấn luyện AI bằng dataset: {self.dataset_path}")
        
        # 1. Sử dụng DataLoader để nạp và làm sạch dữ liệu theo chuẩn Schema
        loader = DataLoader(self.dataset_path)
        X, y = loader.get_train_test_split_data()
        
        if len(X) < 10:
            logger.error("Số lượng mẫu quá ít (dưới 10 mẫu), không đủ điều kiện để phân tách tập train/test.")
            return

        # 2. Phân tách tập dữ liệu Huấn luyện (Train) và Kiểm thử (Test)
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=random_state, stratify=y
        )
        logger.info(f"Kích thước tập huấn luyện: {len(X_train)} mẫu. Tập kiểm thử: {len(X_test)} mẫu.")

        # 3. Khởi tạo và cấu hình siêu tham số cho thuật toán LightGBM
        # Cấu hình tối ưu cho tập dữ liệu dạng bảng có kích thước vừa và nhỏ
        model = lgb.LGBMClassifier(
            n_estimators=100,
            learning_rate=0.05,
            max_depth=5,
            num_leaves=31,
            random_state=random_state,
            verbose=-1
        )

        # 4. Huấn luyện mô hình
        model.fit(X_train, y_train)
        logger.info("Mô hình LightGBM đã được huấn luyện xong.")

        # 5. Dự đoán và đánh giá hiệu năng trên tập Test kiểm thử
        y_pred = model.predict(X_test)
        
        # Tính toán các chỉ số đo lường cốt lõi
        acc = accuracy_score(y_test, y_pred)
        prec = precision_score(y_test, y_pred, zero_division=0)
        rec = recall_score(y_test, y_pred, zero_division=0)
        f1 = f1_score(y_test, y_pred, zero_division=0)
        
        logger.info("=" * 15 + " KẾT QUẢ ĐÁNH GIÁ MÔ HÌNH " + "=" * 15)
        logger.info(f"▪ Độ chính xác tổng quan (Accuracy): {acc:.2%}")
        logger.info(f"▪ Độ chính xác khi duyệt lệnh (Precision): {prec:.2%}")
        logger.info(f"▪ Tỷ lệ bỏ sót lệnh thắng (Recall): {rec:.2%}")
        logger.info(f"▪ Chỉ số F1-Score: {f1:.2%}")
        
        # Log chi tiết ma trận phân loại (Classification Report)
        report = classification_report(y_test, y_pred, zero_division=0)
        print(report)

        # 6. Đóng gói các chỉ số hiệu suất kèm danh sách đặc trưng để đẩy vào ModelManager
        metrics = {
            "accuracy": float(acc),
            "precision": float(prec),
            "recall": float(rec),
            "f1_score": float(f1),
            "dataset_source": os.path.basename(self.dataset_path),
            "features_used": FEATURE_COLUMNS
        }

        # Tiến hành lưu trữ phiên bản mô hình thông qua ModelManager
        model_path, _ = self.model_manager.save_model(model, metrics)
        return model_path

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    try:
        trainer = MLTrainer()
        trainer.train()
    except Exception as e:
        logger.critical(f"Quá trình huấn luyện thất bại do lỗi hệ thống: {str(e)}", exc_info=True)