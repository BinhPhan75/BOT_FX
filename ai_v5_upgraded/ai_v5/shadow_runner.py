# bot_xutho4/ai_v5/shadow_runner.py
import logging
from ai_v5.config_ai import PROBABILITY_THRESHOLD
from ai_v5.data.feature_engine import extract_features_from_signal
from ai_v5.ml.predictor import AIPredictor
from ai_v5.ml.explain import AIExplainer
from ai_v5.telegram.telegram_ai import send_ai_signal_notification

# Khởi tạo predictor (Chỉ load model một lần khi khởi động hệ thống)
predictor = AIPredictor()
explainer = AIExplainer()

def inspect_signal_shadow(signal_obj):
    """
    Hứng đối tượng Signal từ luồng phân tích của bot v4 để xử lý song song.
    """
    try:
        symbol = signal_obj.symbol
        direction = "BUY" if "bullish" in signal_obj.pattern else "SELL"
        signal_group = signal_obj.extra.get("signal_group", "unknown")
        
        logging.info(f"AI v5 bắt đầu phân tích tín hiệu: {symbol} | {direction} ({signal_group})")
        
        # 1. Trích xuất vector đặc trưng từ Signal context
        features_dict = extract_features_from_signal(signal_obj)
        
        # 2. Dự đoán xác suất thắng từ mô hình ML
        win_prob = predictor.predict_probability(features_dict)
        
        # 3. Đưa ra quyết định dựa trên Threshold cấu hình
        decision_bool = win_prob >= PROBABILITY_THRESHOLD
        ai_decision = "APPROVE (DUYỆT LỆNH)" if decision_bool else "REJECT (BỎ QUA)"
        
        logging.info(f"Kết quả AI v5: Xác suất {win_prob*100:.1f}% -> Quyết định: {ai_decision}")

        # 4. Giải thích ngắn gọn lý do AI đưa ra quyết định (dựa trên feature importance)
        explanation = explainer.explain_single_prediction(features_dict)

        # 5. Bắn thông báo kết quả phân tích sang Telegram riêng của AI
        signal_data = {
            "symbol": signal_obj.symbol,
            "pattern": signal_obj.pattern,
            "timeframe": signal_obj.timeframe,
            "price": signal_obj.price,
            "zone_price": signal_obj.zone_price,
        }
        send_ai_signal_notification(
            signal_data=signal_data,
            win_rate=win_prob,
            decision=decision_bool,
            explanation=explanation,
        )
        
        # 6. Ghi log dữ liệu này vào database để chuẩn bị đối chiếu khi lệnh kết thúc
        predictor.save_shadow_log_to_db(signal_obj, win_prob, ai_decision)
        
    except Exception as e:
        logging.error(f"Lỗi nghiêm trọng trong Shadow Runner AI v5: {str(e)}", exc_info=True)