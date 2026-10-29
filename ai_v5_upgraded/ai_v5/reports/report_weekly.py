# bot_xutho4/ai_v5/reports/report_weekly.py
import logging
import requests
from ai_v5.config_ai import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from ai_v5.reports.dashboard import AIDashboardMetrics

logger = logging.getLogger("ai_report_weekly")

def send_weekly_ai_report():
    """
    Tổng hợp dữ liệu hiệu suất theo tuần và đẩy thông báo cảnh báo/re-train nếu cần.
    """
    dash = AIDashboardMetrics()
    metrics = dash.generate_performance_summary()

    if metrics["status"] != "Active":
        return False

    # Tính toán độ chênh lệch hiệu quả giữa chạy AI và chạy gốc
    edge = metrics['ai_filtered_profit'] - metrics['v4_profit']
    edge_status = f"🚀 Tối ưu hơn gốc: +{edge:.2f} USD" if edge >= 0 else f"⚠️ Kém hiệu quả hơn gốc: {edge:.2f} USD"

    report_msg = (
        f"🦅 *[BÁO CÁO TUẦN - CHIẾN LƯỢC AI MLOPS]*\n"
        f"-------------------------------------\n"
        f"📊 *Tổng kết 5 ngày giao dịch:*\n"
        f"   ▪ PnL Thực tế (Bot v4): {metrics['v4_profit']:.2f} USD\n"
        f"   ▪ PnL Giả định (AI v5): {metrics['ai_filtered_profit']:.2f} USD\n"
        f"   ▪ Đánh giá chênh lệch: {edge_status}\n"
        f"-------------------------------------\n"
        f"💡 *Khuyến nghị MLOps:* "
        f"{'Hệ thống tối ưu tốt, tiếp tục duy trì!' if edge >= 0 else 'Thị trường thay đổi cấu trúc, khuyến nghị kích hoạt auto_tuner hoặc re-train mô hình.'}"
    )

    if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN" or not TELEGRAM_BOT_TOKEN:
        print("\n=== WEEKLY REPORT PREVIEW ===")
        print(report_msg)
        return True

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": report_msg, "parse_mode": "Markdown"}, timeout=10)
        logger.info("Đã gửi báo cáo tuần AI v5 lên Telegram.")
        return True
    except Exception as e:
        logger.error(f"Lỗi gửi báo cáo tuần: {str(e)}")
        return False

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    send_weekly_ai_report()