# tune_threshold_v6.py
"""
Dat o thu muc GOC bot_xutho4/ (cung cap voi run_init_train_v6.py).

Do NHIEU muc nguong quyet dinh (PROBABILITY_THRESHOLD) tren dataset M5
XAUUSD cua ai_v6, dung LAI NGUYEN VEN Walk-Forward Validation that cua
ai_v5 (ai_v5.pipeline.walk_forward.run_walk_forward_validation - khong sua
1 dong logic nao) - de tim nguong PHU HOP RIENG cho model ai_v6 thay vi
dung tam 55% cua ai_v5 (nguong do duoc tinh chinh cho phan phoi du lieu
M15, khong dai dien cho M5).

CACH DOC KET QUA:
    - Precision TB: trong so lenh duoc DUYET o nguong do, bao nhieu % thang that
      (qua 5 fold Walk-Forward - Train truoc/Test sau THEO DUNG THU TU THOI GIAN,
      khong xao tron du lieu).
    - Ty le duyet lenh: trong tong so tin hieu quet duoc, bao nhieu % vuot qua
      nguong va duoc coi la "duyet". Nguong cang cao -> duyet cang it lenh (nhung
      chat luong tung lenh cao hon, neu model dang hoc dung).
    - On dinh: do lech chuan Precision giua cac fold co duoi 10 diem % khong -
      neu KHONG on dinh, model co the dang hoc dac diem rieng cua 1 giai doan
      thi truong cu the thay vi quy luat tong quat (giong nguyen tac da ap dung
      khi kiem chung model ai_v5).

Cach dung:
    py -3.11 tune_threshold_v6.py
    py -3.11 tune_threshold_v6.py --thresholds 0.50 0.55 0.60 0.65 0.70
"""
import argparse
import glob
import logging
import os

import pandas as pd

from ai_v5.pipeline.walk_forward import run_walk_forward_validation
from ai_v6.config_ai import DATASETS_DIR as V6_DATASETS_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tune_threshold_v6")

# Nguong duyet qua it lenh (< MIN_APPROVAL_RATE_TO_TRUST) bi LOAI khoi de xuat cuoi
# cung du Precision co the cao - vi mau qua nho (vd chi 2-3 lenh trong ca 5 fold) khong
# du tin cay thong ke, de "may man" chi phoi ket qua.
MIN_APPROVAL_RATE_TO_TRUST = 0.02


def _get_dataset_path() -> str:
    candidates = glob.glob(os.path.join(V6_DATASETS_DIR, "dataset_patterns_*.csv"))
    if not candidates:
        raise FileNotFoundError(
            f"Không tìm thấy dataset trong {V6_DATASETS_DIR} — chạy run_init_train_v6.py trước."
        )
    return max(candidates, key=os.path.getctime)


def main():
    parser = argparse.ArgumentParser(description="Dò ngưỡng quyết định (PROBABILITY_THRESHOLD) cho model AI v6")
    parser.add_argument("--thresholds", type=float, nargs="+",
                        default=[0.50, 0.52, 0.55, 0.58, 0.60, 0.63, 0.65, 0.70])
    parser.add_argument("--dataset", type=str, default=None, help="Đường dẫn dataset CSV cụ thể (mặc định: file mới nhất trong ai_v6/datasets/)")
    args = parser.parse_args()

    dataset_path = args.dataset or _get_dataset_path()
    logger.info(f"📂 Dùng dataset: {dataset_path}")
    df = pd.read_csv(dataset_path)
    logger.info(f"📊 Tổng số mẫu: {len(df)}")

    rows = []
    for threshold in args.thresholds:
        logger.info(f"\n{'=' * 60}\n🔍 Đang đánh giá ngưỡng {threshold:.0%}...\n{'=' * 60}")
        result = run_walk_forward_validation(df, decision_threshold=threshold)
        summary = result.get("summary", {})
        rows.append({
            "threshold": threshold,
            "precision_at_threshold_mean": summary.get("precision_at_threshold_mean"),
            "precision_at_threshold_std": summary.get("precision_at_threshold_std"),
            "avg_approval_rate": summary.get("avg_approval_rate_at_threshold"),
            "n_folds_with_approvals": summary.get("n_folds_with_approvals"),
            "is_stable": result.get("is_stable"),
        })

    report_df = pd.DataFrame(rows)
    print("\n" + "=" * 95)
    print("BẢNG SO SÁNH NGƯỠNG QUYẾT ĐỊNH — AI v6 (XAUUSD, khung M5)")
    print("=" * 95)
    for _, r in report_df.iterrows():
        prec = r["precision_at_threshold_mean"]
        prec_str = f"{prec:.2%}" if prec is not None else "N/A (0 lệnh duyệt)"
        appr = r["avg_approval_rate"]
        appr_str = f"{appr:.1%}" if appr is not None else "N/A"
        print(f"Ngưỡng {r['threshold']:.0%} | Precision TB: {prec_str:>20} | "
              f"Tỷ lệ duyệt lệnh: {appr_str:>8} | Ổn định: {'CÓ' if r['is_stable'] else 'KHÔNG':>4} | "
              f"Fold có lệnh: {r['n_folds_with_approvals']}/5")

    valid = report_df.dropna(subset=["precision_at_threshold_mean"])
    if valid.empty:
        print("\n⚠️ Không có ngưỡng nào duyệt được lệnh nào trong toàn bộ walk-forward — "
              "dataset có thể quá nhỏ hoặc model chưa đủ tốt. Cân nhắc thu thập thêm dữ liệu "
              "(tăng --days khi chạy lại run_init_train_v6.py) trước khi live trading thật.")
        return

    trusted = valid[valid["avg_approval_rate"] >= MIN_APPROVAL_RATE_TO_TRUST]
    if trusted.empty:
        print(f"\n⚠️ Mọi ngưỡng đều duyệt quá ít lệnh (<{MIN_APPROVAL_RATE_TO_TRUST:.0%}) — "
              f"kết quả không đủ tin cậy thống kê để chọn. In toàn bộ bảng ở trên để bạn tự cân nhắc.")
        return

    best = trusted.loc[trusted["precision_at_threshold_mean"].idxmax()]
    print(f"\n👉 Gợi ý (Precision cao nhất trong số ngưỡng còn duyệt đủ lệnh để đáng tin, "
          f"tỷ lệ duyệt ≥ {MIN_APPROVAL_RATE_TO_TRUST:.0%}):")
    print(f"   Ngưỡng {best['threshold']:.0%} — Precision {best['precision_at_threshold_mean']:.2%} "
          f"(±{best['precision_at_threshold_std']:.2%}), tỷ lệ duyệt {best['avg_approval_rate']:.1%}, "
          f"ổn định: {'CÓ' if best['is_stable'] else 'KHÔNG'}")
    if not best["is_stable"]:
        print("   ⚠️ LƯU Ý: ngưỡng này KHÔNG ổn định qua các giai đoạn thời gian (độ lệch chuẩn Precision "
              "≥ 10 điểm %) — cân nhắc chọn ngưỡng khác ổn định hơn dù Precision trung bình thấp hơn 1 chút.")
    print("\nCập nhật trong ai_v6/config_ai.py:")
    print(f'    AI_WINRATE_THRESHOLD = float(os.environ.get("AI_V6_WINRATE_THRESHOLD", "{best["threshold"]:.2f}"))')


if __name__ == "__main__":
    main()
