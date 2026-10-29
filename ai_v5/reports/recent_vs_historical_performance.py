# ai_v5/reports/recent_vs_historical_performance.py
"""
Cong cu chan doan: so sanh Ty le thang cua tung Pattern/Nhom nguon giua
GIAI DOAN GAN DAY (vd 90 ngay cuoi, tuong duong Fold 5 trong Walk-Forward)
voi GIAI DOAN LICH SU con lai. Muc dich: xac dinh CHINH XAC pattern/nhom
nao dang "hong" (Concept Drift) khien Precision Walk-Forward Fold gan nhat
sut giam, thay vi chi biet chung chung "model dang kem di".

Cach dung:
    python -m ai_v5.reports.recent_vs_historical_performance
    python -m ai_v5.reports.recent_vs_historical_performance --recent-days 90

Yeu cau: dataset phai co cot 'entry_time' (tu ban v6 tro di).
"""
import argparse
import glob
import os

import pandas as pd

from ai_v5.config_ai import DATASETS_DIR
from ai_v5.data.data_loader import DataLoader


def analyze(recent_days: int = 90, min_samples: int = 30):
    combined_path = DataLoader.combine_all_datasets(DATASETS_DIR)
    if not combined_path:
        list_files = glob.glob(os.path.join(DATASETS_DIR, "dataset_*.csv"))
        if not list_files:
            print("❌ Không tìm thấy dataset nào. Hãy chạy build_dataset.py trước.")
            return
        combined_path = max(list_files, key=os.path.getctime)

    df = pd.read_csv(combined_path, low_memory=False)
    if "entry_time" not in df.columns or "is_win" not in df.columns:
        print("❌ Dataset thiếu cột 'entry_time' hoặc 'is_win' — không thể phân tích theo thời gian.")
        return

    df["entry_time"] = pd.to_datetime(df["entry_time"], errors="coerce", utc=True)
    df = df.dropna(subset=["entry_time"])
    if df.empty:
        print("❌ Không có dòng nào có entry_time hợp lệ.")
        return

    cutoff = df["entry_time"].max() - pd.Timedelta(days=recent_days)
    recent = df[df["entry_time"] >= cutoff]
    historical = df[df["entry_time"] < cutoff]

    print("=" * 90)
    print(f"SO SÁNH HIỆU SUẤT: {recent_days} NGÀY GẦN NHẤT (từ {cutoff.date()}) so với LỊCH SỬ TRƯỚC ĐÓ")
    print(f"Gần đây: {len(recent)} mẫu | Lịch sử: {len(historical)} mẫu")
    print("=" * 90)

    key_col = "pattern_name" if "pattern_name" in df.columns else "source_type_name"

    hist_stats = historical.groupby(key_col)["is_win"].agg(["mean", "count"]).rename(
        columns={"mean": "winrate_hist", "count": "n_hist"})
    recent_stats = recent.groupby(key_col)["is_win"].agg(["mean", "count"]).rename(
        columns={"mean": "winrate_recent", "count": "n_recent"})

    combined = hist_stats.join(recent_stats, how="outer").fillna({"n_hist": 0, "n_recent": 0})
    combined = combined[(combined["n_hist"] >= min_samples) & (combined["n_recent"] >= min_samples)]
    combined["delta"] = combined["winrate_recent"] - combined["winrate_hist"]
    combined = combined.sort_values("delta")

    if combined.empty:
        print(f"⚠️ Không có pattern nào đủ tối thiểu {min_samples} mẫu ở cả 2 giai đoạn để so sánh công bằng.")
        print("   Hãy giảm --min-samples hoặc tăng --recent-days nếu dữ liệu Shadow còn ít.")
        return

    print(f"\n{'Pattern':35s} {'WinRate cũ':>12s} {'WinRate mới':>12s} {'Chênh lệch':>12s} {'n_cũ':>8s} {'n_mới':>8s}")
    print("-" * 90)
    for name, row in combined.iterrows():
        flag = " ⚠️ SỤT GIẢM MẠNH" if row["delta"] < -0.10 else (" ✅ CẢI THIỆN" if row["delta"] > 0.10 else "")
        print(f"{name:35s} {row['winrate_hist']:>11.1%} {row['winrate_recent']:>11.1%} "
              f"{row['delta']:>+11.1%} {int(row['n_hist']):>8d} {int(row['n_recent']):>8d}{flag}")

    print("\n" + "=" * 90)
    worst = combined.head(5)
    print("🔴 5 PATTERN SỤT GIẢM MẠNH NHẤT (ưu tiên xem xét loại bỏ hoặc siết điều kiện):")
    for name, row in worst.iterrows():
        if row["delta"] < 0:
            print(f"   - {name}: {row['winrate_hist']:.1%} → {row['winrate_recent']:.1%} ({row['delta']:+.1%})")

    best = combined.tail(5)
    print("\n✅ 5 PATTERN ỔN ĐỊNH/CẢI THIỆN NHẤT (đáng tin cậy hơn trong giai đoạn hiện tại):")
    for name, row in best.iloc[::-1].iterrows():
        if row["delta"] >= 0:
            print(f"   - {name}: {row['winrate_hist']:.1%} → {row['winrate_recent']:.1%} ({row['delta']:+.1%})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="So sánh hiệu suất pattern gần đây vs lịch sử")
    parser.add_argument("--recent-days", type=int, default=90, help="Số ngày gần nhất coi là 'giai đoạn hiện tại'")
    parser.add_argument("--min-samples", type=int, default=30, help="Số mẫu tối thiểu mỗi giai đoạn để so sánh")
    args = parser.parse_args()
    analyze(recent_days=args.recent_days, min_samples=args.min_samples)
