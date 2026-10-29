# audit_v6_live_performance.py
"""
Dat o thu muc GOC bot_xutho4/ (cung cap voi ai_v6_trades.db).

Doc DU LIEU LENH THAT tu ai_v6_trades.db (da duoc dong bo qua trade_logger.sync_closed_trades()
- chay dinh ky moi 60 chu ky trong live_trader.py), danh gia xem cac tham so hien tai
(AI_WINRATE_THRESHOLD, SCALP_REWARD_RISK_RATIO, MAX_HOLD_MINUTES...) co con phu hop VOI KET
QUA THAT khong - khac voi Walk-Forward TRUOC DAY (dua tren du lieu LICH SU mo phong), day la
LAN DAU danh gia dua tren chinh nhung gi bot da giao dich that.

CHI DOC (read-only) - khong sua/xoa gi trong DB, an toan chay ngay ca khi bot dang live.

Cac phan tich:
    1. Tong quan: so lenh, win rate, P&L, thoi gian giu TB.
    2. Kiem dinh HIEU CHUAN model: win rate THAT co tang dan theo WinProb luc vao lenh khong?
       (day la cau hoi QUAN TRONG NHAT - neu KHONG tang dan, model dang mat hieu luc trong
       thuc te du Walk-Forward tren du lieu lich su cho ket qua tot).
    3. Phan tich theo NHOM DCA (P&L/nhom, so lenh DCA TB/nhom).
    4. Canh bao neu mau con qua nho de ket luan thong ke dang tin - KHONG voi vang doi tham so
       chi vi vai chuc lenh dau tien.

Cach dung:
    py -3.11 audit_v6_live_performance.py
    py -3.11 audit_v6_live_performance.py --min-trades 30
"""
import argparse
import os
import sqlite3

import pandas as pd


def _load_trades(db_path: str) -> pd.DataFrame:
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Không tìm thấy {db_path}")
    # Mo CHI DOC (read-only, qua URI) - an toan tuyet doi voi bot dang ghi song song, khong
    # gay tranh chap khoa file voi live_trader.py.
    conn = sqlite3.connect(f"file:{os.path.abspath(db_path)}?mode=ro", uri=True)
    df = pd.read_sql_query("SELECT * FROM ai_v6_trades ORDER BY open_time", conn)
    conn.close()
    return df


def _print_overall(df_closed: pd.DataFrame) -> None:
    n = len(df_closed)
    wins = int((df_closed["result"] == "WIN").sum())
    losses = int((df_closed["result"] == "LOSS").sum())
    breakeven = int((df_closed["result"] == "BREAKEVEN").sum())
    win_rate = wins / n if n else 0
    total_profit = df_closed["profit"].sum()
    avg_profit = df_closed["profit"].mean() if n else 0

    df = df_closed.copy()
    df["open_dt"] = pd.to_datetime(df["open_time"], errors="coerce")
    df["close_dt"] = pd.to_datetime(df["close_time"], errors="coerce")
    df["hold_minutes"] = (df["close_dt"] - df["open_dt"]).dt.total_seconds() / 60

    print("=" * 90)
    print("TỔNG QUAN LỆNH ĐÃ ĐÓNG (dữ liệu THẬT từ ai_v6_trades.db)")
    print("=" * 90)
    print(f"Tổng số lệnh đã đóng: {n} | WIN: {wins} | LOSS: {losses} | BREAKEVEN: {breakeven}")
    print(f"Win rate: {win_rate:.1%} | Tổng P&L: {total_profit:+.2f} | P&L TB/lệnh: {avg_profit:+.2f}")
    if df["hold_minutes"].notna().any():
        print(f"Thời gian giữ TB: {df['hold_minutes'].mean():.1f} phút "
              f"(min={df['hold_minutes'].min():.1f}, max={df['hold_minutes'].max():.1f})")


def _print_calibration_check(df_closed: pd.DataFrame) -> None:
    """Kiem tra HIEU CHUAN model: win rate THAT co tang dan theo WinProb khong? Day la cau hoi
    quan trong nhat cua toan bo audit - neu KHONG, model dang khong con dang tin trong thuc te."""
    print("\n" + "=" * 90)
    print("KIỂM ĐỊNH HIỆU CHUẨN MODEL (win rate thật theo từng khoảng WinProb lúc vào lệnh)")
    print("=" * 90)
    df = df_closed.copy()
    df["is_win_num"] = (df["result"] == "WIN").astype(int)
    bins = [0, 0.50, 0.55, 0.60, 0.65, 0.70, 1.01]
    labels = ["<50%", "50-55%", "55-60%", "60-65%", "65-70%", "≥70%"]
    df["prob_bucket"] = pd.cut(df["win_probability"], bins=bins, labels=labels, right=False)

    grouped = df.groupby("prob_bucket", observed=True).agg(
        n=("is_win_num", "count"),
        win_rate=("is_win_num", "mean"),
        avg_profit=("profit", "mean"),
    )

    prev_win_rate = None
    monotonic_ok = True
    any_row_printed = False
    for bucket, row in grouped.iterrows():
        if row["n"] == 0:
            continue
        any_row_printed = True
        trend = ""
        if prev_win_rate is not None and row["n"] >= 3:
            if row["win_rate"] < prev_win_rate - 0.05:
                trend = " ⚠️ THẤP HƠN khoảng WinProb thấp hơn liền trước (đáng chú ý)"
                monotonic_ok = False
        print(f"  WinProb {str(bucket):>8} | {int(row['n']):3d} lệnh | Win rate: {row['win_rate']:.1%} | "
              f"P&L TB: {row['avg_profit']:+.2f}{trend}")
        if row["n"] >= 3:
            prev_win_rate = row["win_rate"]

    if not any_row_printed:
        print("Chưa đủ dữ liệu để chia khoảng WinProb.")
        return

    if monotonic_ok:
        print("\n✅ Xu hướng hợp lý: WinProb cao hơn → win rate thật cũng có xu hướng cao hơn "
              "(model vẫn đáng tin trong thực tế live).")
    else:
        print("\n⚠️ CẢNH BÁO: có khoảng WinProb cao nhưng win rate thật lại THẤP hơn khoảng thấp hơn "
              "liền trước — dấu hiệu model có thể đang MẤT HIỆU LỰC trong live (khác kết quả Walk-Forward "
              "trên dữ liệu lịch sử). Cần thêm dữ liệu để xác nhận đây là xu hướng thật hay chỉ do mẫu nhỏ "
              "ở từng khoảng (đặc biệt các khoảng có < 10 lệnh).")


def _print_group_analysis(df_closed: pd.DataFrame) -> None:
    """
    BẢN VÁ: group_avg_entry KHÔNG dùng được để gom nhóm - giá trị này thay đổi ở MỖI lệnh
    trong cùng 1 nhóm (lệnh gốc ghi entry riêng của nó, lệnh DCA #2 ghi giá TRUNG BÌNH MỚI
    sau khi thêm - khác hẳn giá trị lệnh gốc đã ghi). Gom nhóm ĐÚNG bằng cách đi tuần tự theo
    thời gian mở lệnh (đã ORDER BY open_time từ SQL), dùng is_dca/dca_sequence: dca_sequence=1
    (is_dca=0) LUÔN bắt đầu 1 nhóm MỚI; dca_sequence>1 (is_dca=1) THAM GIA nhóm ĐANG MỞ gần
    nhất CÙNG symbol+direction.
    """
    print("\n" + "=" * 90)
    print("PHÂN TÍCH THEO NHÓM DCA")
    print("=" * 90)
    df = df_closed.sort_values("open_time").reset_index(drop=True)

    groups = []              # list cac nhom da hoan tat, moi nhom la list cac dict-row
    open_group_key = {}      # {(symbol,direction): index trong `groups` cua nhom DANG MO}

    for _, row in df.iterrows():
        key = (row["symbol"], row["direction"])
        is_dca = bool(row["is_dca"])
        if not is_dca or key not in open_group_key:
            # Lenh GOC (hoac lenh DCA "mo coi" - vd du lieu cu thieu ngu canh) -> mo NHOM MOI
            groups.append([row])
            open_group_key[key] = len(groups) - 1
        else:
            groups[open_group_key[key]].append(row)
        # Nhom duoc coi la DA DONG ngay khi ghi nhan (vi day la du lieu LICH SU, tat ca deu da
        # dong) - nhung van giu open_group_key de LENH DCA TIEP THEO (neu co) noi dung vao,
        # cho toi khi gap 1 lenh GOC MOI cung symbol+direction (danh dau nhom cu da thuc su xong).

    if not groups:
        print("Chưa đủ dữ liệu để phân tích theo nhóm.")
        return

    group_rows = []
    for g in groups:
        total_profit = sum(r["profit"] for r in g)
        group_rows.append({"n_positions": len(g), "total_profit": total_profit, "is_win": total_profit > 0})
    gdf = pd.DataFrame(group_rows)
    n_groups = len(gdf)

    print(f"Tổng số NHÓM đã đóng: {n_groups} | Win rate theo NHÓM (không phải theo từng lệnh lẻ): "
          f"{gdf['is_win'].mean():.1%}")
    print(f"Số lệnh (gốc+DCA) trung bình/nhóm: {gdf['n_positions'].mean():.2f}")
    dist = gdf["n_positions"].value_counts().sort_index()
    dist_str = ", ".join(f"{k} lệnh: {v} nhóm" for k, v in dist.items())
    print(f"Phân bố: {dist_str}")
    if (gdf["n_positions"] > 1).sum() == 0:
        print("⚠️ Không có nhóm nào có DCA - kiểm tra lại DCA_TRIGGER_ATR_MULTIPLE/DCA_MIN_INTERVAL_MINUTES "
              "có đang quá chặt không, hoặc đơn giản là trong giai đoạn này lệnh đóng (SL/TP/timeout) quá "
              "nhanh trước khi kịp đủ điều kiện DCA.")


def main():
    parser = argparse.ArgumentParser(description="Đánh giá hiệu suất live THẬT của ai_v6 từ ai_v6_trades.db")
    parser.add_argument("--db", type=str, default="ai_v6_trades.db", help="Đường dẫn file DB")
    parser.add_argument("--min-trades", type=int, default=20,
                        help="Số lệnh tối thiểu để coi kết quả đủ tin cậy đưa ra khuyến nghị")
    args = parser.parse_args()

    df = _load_trades(args.db)
    print(f"📂 Tổng số bản ghi (mở + đóng): {len(df)}")

    df_closed = df[df["result"].notna()].copy()
    df_open = df[df["result"].isna()]
    print(f"   Đã đóng: {len(df_closed)} | Đang mở: {len(df_open)}\n")

    if len(df_closed) == 0:
        print("⚠️ Chưa có lệnh nào đóng (hoặc trade_logger.sync_closed_trades() chưa chạy lần nào) "
              "— chưa thể đánh giá. Kiểm tra bot có đang chạy và đã qua ít nhất 1 chu kỳ đồng bộ "
              "(mỗi 60 lần quét, ~10 phút) chưa.")
        return

    _print_overall(df_closed)

    if len(df_closed) < args.min_trades:
        print(f"\n⚠️ Chỉ có {len(df_closed)} lệnh đã đóng (< {args.min_trades}) — CHƯA ĐỦ để kết luận "
              f"thống kê đáng tin cậy. Các phân tích dưới đây CHỈ MANG TÍNH THAM KHẢO SƠ BỘ — "
              f"KHÔNG nên vội đổi tham số chỉ dựa vào lần chạy này, tiếp tục theo dõi thêm.")

    _print_calibration_check(df_closed)
    _print_group_analysis(df_closed)

    print("\n" + "=" * 90)
    print("GỢI Ý ĐỌC KẾT QUẢ")
    print("=" * 90)
    print("- Win rate THẬT gần với Precision đã đo qua Walk-Forward (~55-64% tùy ngưỡng, xem lần chạy")
    print("  tune_threshold_v6.py gần nhất) → tham số đang ổn, không cần đổi gì.")
    print("- Win rate THẬT thấp hơn ĐÁNG KỂ (>10 điểm %) so với Walk-Forward → cân nhắc: (a) nâng")
    print("  AI_WINRATE_THRESHOLD lên 1 bậc, (b) khi đủ ~100+ lệnh, build lại dataset TỪ CHÍNH DỮ LIỆU")
    print("  LIVE này (đáng tin hơn cả lịch sử mô phỏng) rồi train lại model.")
    print("- Bảng hiệu chuẩn KHÔNG đơn điệu tăng → model có thể cần retrain sớm hơn dự kiến, đặc biệt")
    print("  nếu thị trường đã chuyển pha (vd từ trending sang ranging kéo dài) so với giai đoạn train.")


if __name__ == "__main__":
    main()