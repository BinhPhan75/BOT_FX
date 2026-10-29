# ai_v5/evaluation/metrics.py
import numpy as np
import pandas as pd

def calculate_trading_metrics(y_true, y_pred, pnl_values) -> dict:
    """
    Tính toán các chỉ số chất lượng giao dịch thực tế của AI.
    y_true: Kết quả thực (1: Thắng, 0: Thua)
    y_pred: Quyết định của AI (1: Duyệt lệnh, 0: Chặn lệnh)
    pnl_values: Giá trị tiền lời/lỗ thực tế của lệnh đó.
    """
    # Lọc ra những lệnh mà AI cho phép vào giao dịch (y_pred == 1)
    executed_pnl = [pnl for pnl, action in zip(pnl_values, y_pred) if action == 1]
    
    if not executed_pnl:
        return {"profit_factor": 0.0, "total_net_profit": 0.0, "win_rate": 0.0}

    gross_profit = sum([p for p in executed_pnl if p > 0])
    gross_loss = abs(sum([p for p in executed_pnl if p < 0]))
    
    # Chỉ số cốt lõi gác cổng AI tài chính
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else gross_profit
    net_profit = sum(executed_pnl)
    win_rate = len([p for p in executed_pnl if p > 0]) / len(executed_pnl)

    return {
        "profit_factor": round(float(profit_factor), 2),
        "total_net_profit": round(float(net_profit), 2),
        "win_rate": round(float(win_rate * 100), 1)
    }