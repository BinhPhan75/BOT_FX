# ai_v5/evaluation/backtest_compare.py
import logging
from ai_v5.evaluation.metrics import calculate_trading_metrics

logger = logging.getLogger("watcher.ai_learner")

def compare_models(old_model, new_model, test_features, test_labels, test_pnls) -> bool:
    """True nếu mô hình mới vượt trội hơn mô hình cũ về mặt Profit Factor."""
    
    # Dự đoán từ mô hình cũ và mô hình mới
    old_preds = old_model.predict(test_features)
    new_preds = new_model.predict(test_features)
    
    # Quy đổi xác suất về dạng nhị phân 0 hoặc 1 (ngưỡng an toàn 0.5)
    old_actions = [1 if p >= 0.5 else 0 for p in old_preds]
    new_actions = [1 if p >= 0.5 else 0 for p in new_preds]

    old_metrics = calculate_trading_metrics(test_labels, old_actions, test_pnls)
    new_metrics = calculate_trading_metrics(test_labels, new_actions, test_pnls)

    logger.info(f"📊 Đối chiếu Backtest: Model Cũ PF = {old_metrics['profit_factor']} | Model Mới PF = {new_metrics['profit_factor']}")

    # Gác cổng điều kiện: Mô hình mới phải cải thiện Profit Factor hoặc duy trì hiệu năng tốt hơn
    if new_metrics["profit_factor"] >= old_metrics["profit_factor"] and new_metrics["profit_factor"] >= 1.2:
        logger.info("🚀 Mô hình mới đạt tiêu chuẩn tài chính vượt trội. Chấp thuận nâng cấp.")
        return True
    
    logger.warning("⚠️ Mô hình mới tuy có Accuracy/AUC toán học cao nhưng Profit Factor kém. HỦY BỎ nâng cấp.")
    return False