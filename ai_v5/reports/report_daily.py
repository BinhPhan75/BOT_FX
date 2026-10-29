# bot_xutho4/ai_v5/reports/report_daily.py
import logging
import requests
from ai_v5.config_ai import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from ai_v5.reports.dashboard import AIDashboardMetrics

logger = logging.getLogger("ai_report_daily")

def send_daily_ai_report():
    """
    Tự động tổng hợp dữ liệu giao dịch trong ngày và gửi báo cáo tổng kết bộ lọc AI về Telegram.
    """
    dash = AIDashboardMetrics()
    metrics = dash.generate_performance_summary()

    if metrics["status"] == "No Data":
        logger.info("Không có dữ liệu giao dịch mới để xuất báo cáo ngày.")
        return False

    report_msg = (
        f"📋 *[BÁO CÁO NGÀY - HỆ THỐNG AI V5]*\n"
        f"-------------------------------------\n"
        f"📈 *Hiệu suất Bot v4 gốc:*\n"
        f"   ▪ Tổng số lệnh đã vào: {metrics['v4_total_trades']}\n"
        f"   ▪ Tỷ lệ thắng (WinRate): {metrics['v4_win_rate']:.1%}\n"
        f"   ▪ Tổng Lợi nhuận/Thua lỗ: {metrics['v4_profit']:.2f} USD\n"
        f"-------------------------------------\n"
        f"🛡️ *Đóng góp bộ lọc AI v5 (Shadow):*\n"
        f"   ▪ Số pha cứu thua (Lọc lệnh âm): {metrics['ai_saved_losses']} lệnh\n"
        f"   ▪ Lợi nhuận giả định nếu theo AI: {metrics['ai_filtered_profit']:.2f} USD\n"
        f"-------------------------------------\n"
        f"🤖 _Mô hình hoạt động ổn định. Dữ liệu được cập nhật liên tục vào Feature Store._"
    )

    if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN" or not TELEGRAM_BOT_TOKEN:
        print("\n=== DAILY REPORT PREVIEW ===")
        print(report_msg)
        return True

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": report_msg, "parse_mode": "Markdown"}, timeout=10)
        logger.info("Đã gửi báo cáo ngày AI v5 lên Telegram.")
        return True
    except Exception as e:
        logger.error(f"Lỗi gửi báo cáo ngày: {str(e)}")
        return False

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    send_daily_ai_report()