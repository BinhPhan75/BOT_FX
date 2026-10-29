# diagnose_v6_dataset.py
"""
Dat o thu muc GOC bot_xutho4/.

Phan tich CHI TIET dataset M5 XAUUSD cua ai_v6 theo TUNG NHOM pattern
(source_type) va TUNG PATTERN CU THE - de tim xem co 1 nhom nao dang AP DAO
so luong mau VA co win rate thuc te KEM hay khong (giong dung hien tuong da
gap voi DIVERGENCE_PATTERN cua ai_v5: chiem 90% khoi luong nhung chi thang
that ~29% - lam keo meo Precision tong the va khien "Precision giam dan khi
nguong tang" - dau hieu bat thuong da thay trong ket qua tune_threshold_v6.py).

Cach dung:
    py -3.11 diagnose_v6_dataset.py
"""
import glob
import logging
import os

import pandas as pd

from ai_v6.config_ai import DATASETS_DIR as V6_DATASETS_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("diagnose_v6_dataset")


def _get_dataset_path() -> str:
    candidates = glob.glob(os.path.join(V6_DATASETS_DIR, "dataset_patterns_*.csv"))
    if not candidates:
        raise FileNotFoundError(f"Không tìm thấy dataset trong {V6_DATASETS_DIR}")
    return max(candidates, key=os.path.getctime)


def main():
    dataset_path = _get_dataset_path()
    df = pd.read_csv(dataset_path)
    print(f"\n📂 Dataset: {dataset_path}")
    print(f"📊 Tổng số mẫu: {len(df)}")

    if "entry_time" in df.columns:
        times = pd.to_datetime(df["entry_time"], errors="coerce", utc=True)
        print(f"📅 Khoảng thời gian: {times.min()} → {times.max()} "
              f"(~{(times.max() - times.min()).days} ngày dữ liệu thực tế)")

    overall_win_rate = df["is_win"].mean()
    print(f"🎯 Win rate TỔNG THỂ (chưa lọc theo ML): {overall_win_rate:.2%}\n")

    print("=" * 90)
    print("PHÂN TÍCH THEO NHÓM NGUỒN (source_type)")
    print("=" * 90)
    by_source = df.groupby("source_type_name").agg(
        n_samples=("is_win", "count"),
        win_rate=("is_win", "mean"),
    ).sort_values("n_samples", ascending=False)
    by_source["pct_of_total"] = by_source["n_samples"] / len(df)
    for name, row in by_source.iterrows():
        flag = " ⚠️ ÁP ĐẢO + WIN RATE KÉM" if row["pct_of_total"] > 0.5 and row["win_rate"] < overall_win_rate - 0.05 else ""
        print(f"{name:25s} | {int(row['n_samples']):5d} mẫu ({row['pct_of_total']:5.1%}) | "
              f"Win rate: {row['win_rate']:.2%}{flag}")

    print("\n" + "=" * 90)
    print("PHÂN TÍCH THEO PATTERN CỤ THỂ (chỉ hiện pattern có ≥ 15 mẫu)")
    print("=" * 90)
    by_pattern = df.groupby("pattern_name").agg(
        n_samples=("is_win", "count"),
        win_rate=("is_win", "mean"),
    ).sort_values("n_samples", ascending=False)
    by_pattern = by_pattern[by_pattern["n_samples"] >= 15]
    for name, row in by_pattern.iterrows():
        flag = " ⚠️" if row["win_rate"] < 0.35 else (" ✅" if row["win_rate"] > 0.55 else "")
        print(f"{name:35s} | {int(row['n_samples']):5d} mẫu | Win rate: {row['win_rate']:.2%}{flag}")

    print("\n" + "=" * 90)
    print("KẾT LUẬN GỢI Ý")
    print("=" * 90)
    dominant = by_source.iloc[0]
    if dominant["pct_of_total"] > 0.5:
        print(f"⚠️ Nhóm '{by_source.index[0]}' chiếm {dominant['pct_of_total']:.1%} tổng số mẫu — "
              f"nếu win rate nhóm này ({dominant['win_rate']:.2%}) thấp hơn đáng kể so với các nhóm "
              f"khác, model có thể đang bị nhóm này CHI PHỐI (giống hệt sự cố DIVERGENCE_PATTERN cũ "
              f"của ai_v5) — cân nhắc loại bớt/hạ trọng số nhóm này hoặc thu thập thêm dữ liệu cho "
              f"các nhóm còn lại trước khi tin dùng model.")
    if len(df) < 3000:
        print(f"⚠️ Tổng số mẫu ({len(df)}) khá nhỏ cho 5-fold Walk-Forward (mỗi fold test chỉ "
              f"~{len(df)//10} mẫu) — kết quả Precision có thể chưa ổn định thống kê. Cân nhắc chạy lại "
              f"run_init_train_v6.py với --days lớn hơn (400-600) để có nhiều dữ liệu hơn.")


if __name__ == "__main__":
    main()
