# review_v6_trades.py
"""
Dat o thu muc GOC bot_xutho4/.

Doc TOAN BO lenh (dang mo + da dong) tu ai_v6_trades.db, in chi tiet theo
TUNG NHOM DCA (dua vao group_avg_entry de gom cac lenh cung 1 nhom) - de
xem lai PATTERN nao + WinProb bao nhieu da kich hoat tung nhom, so sanh
voi ket qua thuc te (thang/thua), giup danh gia model dang du doan dung/sai
co he thong hay chi la bien dong ngau nhien binh thuong voi mau nho.

Cach dung:
    py -3.11 review_v6_trades.py
"""
import os
import sqlite3

import pandas as pd

from ai_v6.config_ai import AI_BASE_DIR

DB_PATH = os.path.abspath(os.path.join(AI_BASE_DIR, "..", "ai_v6_trades.db"))


def main():
    if not os.path.exists(DB_PATH):
        print(f"❌ Không tìm thấy {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM ai_v6_trades ORDER BY open_time", conn)
    conn.close()

    if df.empty:
        print("Chưa có lệnh nào được ghi nhận.")
        return

    print(f"\n📊 Tổng số lệnh đã ghi: {len(df)}\n")

    # Gom nhom theo group_avg_entry + symbol + direction (lam tron de tranh sai so float)
    df["group_key"] = df["symbol"] + "_" + df["direction"] + "_" + df["group_avg_entry"].round(2).astype(str)

    for group_key, group_df in df.groupby("group_key", sort=False):
        group_df = group_df.sort_values("open_time")
        first = group_df.iloc[0]
        print("=" * 90)
        print(f"NHÓM: {first['symbol']} {first['direction']} | Entry TB nhóm: {first['group_avg_entry']} | "
              f"SL nhóm: {first['group_sl']} | TP nhóm: {first['group_tp']}")
        print("=" * 90)
        for _, row in group_df.iterrows():
            label = "GỐC" if not row["is_dca"] else f"DCA #{row['dca_sequence']}"
            result_str = row["result"] if pd.notna(row["result"]) else "ĐANG MỞ"
            profit_str = f"{row['profit']:+.2f}" if pd.notna(row["profit"]) else "N/A"
            print(f"  [{label}] #{row['ticket']} | {row['open_time']} | Pattern: {row['pattern']} "
                  f"({row['source_type']}) | WinProb: {row['win_probability']:.1%} | Entry: {row['entry']} | "
                  f"Kết quả: {result_str} | P&L: {profit_str}")
        print()

    # Thong ke nhanh theo pattern - xem pattern nao dang thua nhieu
    closed = df[df["result"].notna()]
    if not closed.empty:
        print("=" * 90)
        print("THỐNG KÊ THEO PATTERN (chỉ lệnh đã đóng)")
        print("=" * 90)
        closed = closed.copy()
        closed["is_win_num"] = (closed["result"] == "WIN").astype(int)
        by_pattern = closed.groupby("pattern").agg(
            n=("is_win_num", "count"),
            win_rate=("is_win_num", "mean"),
            avg_win_prob=("win_probability", "mean"),
            total_profit=("profit", "sum"),
        ).sort_values("n", ascending=False)
        for name, row in by_pattern.iterrows():
            print(f"{name:30s} | {int(row['n']):3d} lệnh | Win rate thật: {row['win_rate']:.0%} | "
                  f"WinProb TB lúc vào: {row['avg_win_prob']:.1%} | Tổng P&L: {row['total_profit']:+.2f}")


if __name__ == "__main__":
    main()
