# bot_xutho4/ai_v5/reports/dashboard.py
import os
import sqlite3
import pandas as pd
import logging
from ai_v5.config_ai import AI_BASE_DIR

logger = logging.getLogger("ai_dashboard")

class AIDashboardMetrics:
    """
    Tính toán và đối chiếu hiệu suất tài chính thực tế giữa Bot v4 (Live) 
    và các bộ lọc của AI v5 (Shadow Mode).
    """
    def __init__(self, db_path: str = None):
        # Định vị file database giao dịch nằm ở thư mục gốc bot_xutho4
        if db_path:
            self.db_path = db_path
        else:
            self.db_path = os.path.abspath(os.path.join(AI_BASE_DIR, "..", "trades.db"))

    def generate_performance_summary(self) -> dict:
        """
        Quét database lệnh và tính toán so sánh chi tiết hiệu suất.
        """
        summary = {
            "v4_total_trades": 0, "v4_win_rate": 0.0, "v4_profit": 0.0,
            "ai_saved_losses": 0, "ai_filtered_profit": 0.0, "status": "No Data"
        }
        
        if not os.path.exists(self.db_path):
            logger.warning(f"Không tìm thấy database trades.db tại: {self.db_path}")
            return summary

        try:
            conn = sqlite3.connect(self.db_path)
            # Giả định bảng trades lưu trữ kết quả thực tế (profit, status) 
            # và nhật ký bộ lọc AI (ai_decision, ai_winrate)
            df = pd.read_sql_query("SELECT * FROM trades", conn)
            conn.close()

            if df.empty:
                return summary

            summary["status"] = "Active"
            summary["v4_total_trades"] = len(df)
            
            # Tính toán cho Bot v4 gốc
            v4_wins = df[df['profit'] > 0]
            summary["v4_win_rate"] = len(v4_wins) / len(df) if len(df) > 0 else 0.0
            summary["v4_profit"] = df['profit'].sum()

            # Tính toán hiệu quả của bộ lọc AI v5 (Nếu chạy theo AI)
            # AI cứu thua: Những lệnh thực tế bị âm (profit < 0) nhưng AI đưa ra quyết định REJECT (0)
            if 'ai_decision' in df.columns:
                ai_saved = df[(df['profit'] < 0) & (df['ai_decision'] == 0)]
                summary["ai_saved_losses"] = len(ai_saved)
                
                # Tính toán tổng profit giả định nếu lọc theo quyết định AI (Chỉ giữ lại lệnh AI APPROVE)
                ai_approved_trades = df[df['ai_decision'] == 1]
                summary["ai_filtered_profit"] = ai_approved_trades['profit'].sum()

            return summary
        except Exception as e:
            logger.error(f"Lỗi khi truy vấn số liệu Dashboard từ database: {str(e)}")
            summary["status"] = f"Error: {str(e)}"
            return summary

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    dash = AIDashboardMetrics()
    res = dash.generate_performance_summary()
    print("\n📊 Chỉ số phân tích Dashboard sơ bộ:", res)