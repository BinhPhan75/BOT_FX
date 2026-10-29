# ai_v5/evaluation/confusion_matrix.py
def generate_matrix_report(y_true, y_pred) -> dict:
    tp = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 1) # AI cho vào - Lệnh Thắng thật
    fp = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 1) # AI cho vào - Lệnh Bị Thua (Lỗi nghiêm trọng)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 0) # AI đòi chặn - Thực tế lệnh lại Thắng (Uổng phí)
    tn = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 0) # AI đòi chặn - Thực tế lệnh Thua thật (AI cứu thua xuất sắc)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

    return {
        "true_positive_approved": tp,
        "false_positive_leak": fp,
        "false_negative_missed": fn,
        "true_negative_saved": tn,
        "ai_precision": round(precision * 100, 2)
    }