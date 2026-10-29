# bot_xutho4/ai_v5/ml/auto_tuner_ml.py
import os
import glob
import logging
from sklearn.model_selection import RandomizedSearchCV
import lightgbm as lgb

from ai_v5.config_ai import DATASETS_DIR
from ai_v5.data.data_loader import DataLoader

logger = logging.getLogger("ai_tuner_ml")

class MLAutoTuner:
    """
    Chuyên biệt dò tìm tham số cây quyết định (Hyperparameters) cho LightGBM 
    phục vụ phân hệ chấm điểm AI v5, độc lập hoàn toàn với WFO kỹ thuật của Bot v4.
    """
    def __init__(self, dataset_path: str = None):
        self.dataset_path = dataset_path if dataset_path else self._get_latest_dataset()

    def _get_latest_dataset(self) -> str:
        list_files = glob.glob(os.path.join(DATASETS_DIR, "dataset_*.csv"))
        if not list_files:
            raise FileNotFoundError("Chưa có file dataset CSV nào trong Feature Store để tune AI.")
        return max(list_files, key=os.path.getctime)

    def tune_lgb_parameters(self, n_iter: int = 8, cv: int = 3) -> dict:
        logger.info(f"🤖 [AI v5 Tuner] Đang quét đặc trưng tại: {self.dataset_path}")
        
        loader = DataLoader(self.dataset_path)
        X, y = loader.get_train_test_split_data()

        if len(X) < 30:
            logger.warning("Mẫu dữ liệu quá ít dưới 30 dòng. Sử dụng bộ tham số AI mặc định.")
            return {"learning_rate": 0.05, "max_depth": 5, "num_leaves": 31}

        # Không gian tham số của mô hình phân loại cây LightGBM
        param_dist = {
            'learning_rate': [0.01, 0.05, 0.1],
            'max_depth': [3, 5, 7, -1],
            'num_leaves': [15, 31, 63],
            'n_estimators': [50, 100, 150],
            'min_child_samples': [5, 10, 20]
        }

        estimator = lgb.LGBMClassifier(verbose=-1, random_state=42)
        
        # Sử dụng scoring='precision' để tối ưu bộ lọc chặn lệnh âm tốt nhất
        search = RandomizedSearchCV(
            estimator=estimator,
            param_distributions=param_dist,
            n_iter=n_iter,
            cv=cv,
            scoring='precision',
            random_state=42,
            n_jobs=-1
        )

        search.fit(X, y)
        logger.info(f"🎯 Đã tìm ra cấu hình AI tối ưu: {search.best_params_} (Precision: {search.best_score_:.2%})")
        return search.best_params_

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        tuner = MLAutoTuner()
        tuner.tune_lgb_parameters(n_iter=3, cv=2)
    except Exception as e:
        logger.error(f"Lỗi kiểm thử: {e}")