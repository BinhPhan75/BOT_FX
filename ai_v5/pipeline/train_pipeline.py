# ai_v5/pipeline/train_pipeline.py
"""
LƯU Ý (18/07/2026): file này trước đây dùng schema RIÊNG (source_type/pattern/
regime_type dạng text + cột nhãn "target"), không còn khớp với output của
build_dataset.py sau khi hợp nhất schema (ai_v5/data/feature_schema.py) — sẽ
crash KeyError: 'target'. Đã viết lại để dùng chung schema + ModelManager,
tránh tạo ra 1 model_path riêng (lgbm_v5_hybrid.pkl) lệch với latest_model.pkl
mà predictor.py / watcher.py đang dùng.

Khuyến nghị dùng ai_v5.ml.ml_trainer.MLTrainer cho việc train định kỳ (tự gộp
nhiều dataset). Hàm execute_train_pipeline() ở đây được giữ lại để tương thích
ngược với run_init_train.py, nay chỉ là một lớp mỏng gọi sang MLTrainer.
"""
import logging
import pandas as pd

from ai_v5.data.feature_schema import FEATURE_COLUMNS, TARGET_COLUMN, validate_features
from ai_v5.ml.model_manager import ModelManager
from sklearn.model_selection import train_test_split
from lightgbm import LGBMClassifier

logger = logging.getLogger("watcher.ai_learner")


def execute_train_pipeline(raw_dataset: pd.DataFrame):
    """Tiền xử lý tập dữ liệu (schema hợp nhất) và huấn luyện mô hình LightGBM.
    Trả về đường dẫn model đã lưu (ai_v5/models/latest_model.pkl) hoặc None nếu lỗi."""
    if raw_dataset.empty:
        logger.error("❌ Tập dữ liệu rỗng, không thể huấn luyện.")
        return None

    logger.info(f"⚡ Đang tiền xử lý {len(raw_dataset)} mẫu dữ liệu hỗn hợp...")

    df = raw_dataset.copy()
    missing_cols = [c for c in FEATURE_COLUMNS + [TARGET_COLUMN] if c not in df.columns]
    if missing_cols:
        logger.error(f"❌ Dataset thiếu cột bắt buộc theo schema hợp nhất: {missing_cols}")
        return None

    X = validate_features(df)
    y = df[TARGET_COLUMN]

    logger.info(f"📐 Vector đặc trưng bao gồm các cột: {FEATURE_COLUMNS}")

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    logger.info(f"📊 Tập Train: {len(X_train)} mẫu | Tập Test: {len(X_test)} mẫu.")
    logger.info("🏋️ Đang tính toán cấu trúc cây và huấn luyện mô hình LightGBM...")

    model = LGBMClassifier(
        n_estimators=100,
        learning_rate=0.05,
        max_depth=5,
        random_state=42,
        verbosity=-1,
    )
    model.fit(X_train, y_train)

    train_acc = model.score(X_train, y_train)
    test_acc = model.score(X_test, y_test)
    logger.info(f"🎯 Kết quả học tập: Độ chính xác tập Train = {train_acc:.2%}, Tập Test = {test_acc:.2%}")

    # Lưu qua ModelManager để đồng bộ với predictor.py / watcher.py (latest_model.pkl)
    metrics = {"train_accuracy": float(train_acc), "test_accuracy": float(test_acc), "n_samples": int(len(df))}
    model_path, _meta_path = ModelManager().save_model(model, metrics)
    logger.info(f"💾 Đã lưu thành công bộ não AI V5 tại: {model_path}")

    return model_path
