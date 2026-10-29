# ai_v5/pipeline/walk_forward.py
"""
Walk-Forward Validation THAT (khong con la ban gia lap).

Khac voi train_test_split() ngau nhien (xao tron du lieu roi chia 80/20 -
mau tuong lai co the lot vao tap Train, mau qua khu lot vao tap Test), Walk-
Forward chia du lieu THEO DUNG THU TU THOI GIAN va luon Train truoc - Test
sau, giong het cach 1 model se duoc dung thuc te (chi biet qua khu, khong
bao gio "nhin thay tuong lai" khi train).

Phuong phap: Anchored/Expanding Window.
    Fold 1: Train [0%  -> 50%]  Test [50% -> 60%]
    Fold 2: Train [0%  -> 60%]  Test [60% -> 70%]
    Fold 3: Train [0%  -> 70%]  Test [70% -> 80%]
    Fold 4: Train [0%  -> 80%]  Test [80% -> 90%]
    Fold 5: Train [0%  -> 90%]  Test [90% -> 100%]
Tap Train cua fold sau luon "nuot" them du lieu cua fold truoc (mo rong dan),
Tap Test luon la khoang thoi gian NGAY SAU do, chua tung duoc nhin thay.

Neu Precision/Accuracy on dinh qua cac fold -> model dang hoc quy luat that,
khong phai overfit theo 1 giai doan thi truong cu the. Neu dao dong manh
hoac giam dan theo thoi gian -> model co the dang "hoc thuoc" dac diem rieng
cua 1 giai doan (vd 1 xu huong gia vang manh) chu khong tong quat hoa duoc.
"""
import logging
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

from ai_v5.config_ai import AI_WINRATE_THRESHOLD
from ai_v5.data.feature_schema import FEATURE_COLUMNS, TARGET_COLUMN, validate_features

logger = logging.getLogger("watcher.ai_learner")

DEFAULT_N_FOLDS = 5
DEFAULT_MIN_TRAIN_FRACTION = 0.5  # Fold dau tien can toi thieu 50% du lieu de train truoc khi bat dau danh gia


def run_walk_forward_validation(full_dataset: pd.DataFrame, n_folds: int = DEFAULT_N_FOLDS,
                                 min_train_fraction: float = DEFAULT_MIN_TRAIN_FRACTION,
                                 decision_threshold: float = AI_WINRATE_THRESHOLD) -> dict:
    """
    full_dataset: DataFrame day du (phai co cot 'entry_time' de sap xep theo thoi gian
                  va cac cot FEATURE_COLUMNS + TARGET_COLUMN).
    decision_threshold: nguong xac suat de "duyet lenh" giong het production
                  (mac dinh AI_WINRATE_THRESHOLD=0.60 trong config_ai.py), dung de tinh
                  bo them 1 bo chi so "at_threshold" phan anh dung hanh vi that cua bot
                  (chi duyet lenh khi tu tin >= threshold), thay vi chi dung nguong
                  mac dinh 0.5 cua model.predict().
    Tra ve dict: {"folds": [...chi tiet tung fold...], "summary": {...trung binh/do lech chuan...}, "is_stable": bool}
    """
    if "entry_time" not in full_dataset.columns:
        logger.error("❌ Dataset thiếu cột 'entry_time' — không thể chạy Walk-Forward thật "
                     "(dataset cũ sinh ra trước khi có bản vá này). Hãy chạy lại build_dataset.py để tạo dataset mới.")
        return {"folds": [], "summary": {}, "is_stable": False, "error": "missing_entry_time"}

    df = full_dataset.dropna(subset=["entry_time"] + FEATURE_COLUMNS + [TARGET_COLUMN]).copy()
    df["entry_time"] = pd.to_datetime(df["entry_time"], errors="coerce", utc=True)
    df = df.dropna(subset=["entry_time"]).sort_values("entry_time").reset_index(drop=True)

    n = len(df)
    if n < 500:
        logger.error(f"❌ Dataset quá nhỏ ({n} mẫu) để chạy Walk-Forward đáng tin cậy (cần tối thiểu 500).")
        return {"folds": [], "summary": {}, "is_stable": False, "error": "insufficient_data"}

    logger.info(f"🔄 Bắt đầu Walk-Forward Validation THẬT trên {n} mẫu (khoảng thời gian "
                f"{df['entry_time'].iloc[0]} → {df['entry_time'].iloc[-1]}), {n_folds} fold cuốn chiếu...")

    fold_results = []
    # Chia đường thời gian thành (n_folds + số bước của min_train_fraction) đoạn bằng nhau
    test_fraction_each = (1.0 - min_train_fraction) / n_folds

    for fold_idx in range(1, n_folds + 1):
        train_end_frac = min_train_fraction + test_fraction_each * (fold_idx - 1)
        test_end_frac = min_train_fraction + test_fraction_each * fold_idx

        train_end_idx = int(n * train_end_frac)
        test_start_idx = train_end_idx
        test_end_idx = int(n * test_end_frac)

        train_df = df.iloc[:train_end_idx]
        test_df = df.iloc[test_start_idx:test_end_idx]

        if len(train_df) < 200 or len(test_df) < 50:
            logger.warning(f"⚠️ Fold {fold_idx}: dữ liệu quá ít (Train={len(train_df)}, Test={len(test_df)}), bỏ qua.")
            continue
        if test_df[TARGET_COLUMN].nunique() < 2:
            logger.warning(f"⚠️ Fold {fold_idx}: tập Test chỉ có 1 nhãn duy nhất, không đánh giá được Precision/Recall, bỏ qua.")
            continue

        X_train = validate_features(train_df)
        y_train = train_df[TARGET_COLUMN]
        X_test = validate_features(test_df)
        y_test = test_df[TARGET_COLUMN]

        model = LGBMClassifier(n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42, verbosity=-1)
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)

        acc = accuracy_score(y_test, y_pred)
        prec = precision_score(y_test, y_pred, zero_division=0)
        rec = recall_score(y_test, y_pred, zero_division=0)
        f1 = f1_score(y_test, y_pred, zero_division=0)

        # --- Danh gia THEM tai dung nguong quyet dinh san xuat (vd 0.60) thay vi 0.5 mac dinh ---
        # Day moi la con so phan anh dung hanh vi that: bot chi "duyet lenh" khi tu tin >= threshold,
        # nen so lenh duoc duyet se it hon nhieu nhung ky vong Precision cao hon.
        y_proba = model.predict_proba(X_test)[:, 1]
        y_pred_at_threshold = (y_proba >= decision_threshold).astype(int)
        n_approved = int(y_pred_at_threshold.sum())
        if n_approved > 0:
            prec_at_threshold = precision_score(y_test, y_pred_at_threshold, zero_division=0)
            rec_at_threshold = recall_score(y_test, y_pred_at_threshold, zero_division=0)
        else:
            prec_at_threshold = None
            rec_at_threshold = None

        result = {
            "fold": fold_idx,
            "train_start": str(df["entry_time"].iloc[0]),
            "train_end": str(train_df["entry_time"].iloc[-1]),
            "test_start": str(test_df["entry_time"].iloc[0]),
            "test_end": str(test_df["entry_time"].iloc[-1]),
            "n_train": len(train_df),
            "n_test": len(test_df),
            "accuracy": float(acc),
            "precision": float(prec),
            "recall": float(rec),
            "f1": float(f1),
            "n_approved_at_threshold": n_approved,
            "approval_rate_at_threshold": float(n_approved / len(test_df)) if len(test_df) else 0.0,
            "precision_at_threshold": float(prec_at_threshold) if prec_at_threshold is not None else None,
            "recall_at_threshold": float(rec_at_threshold) if rec_at_threshold is not None else None,
        }
        fold_results.append(result)
        threshold_str = (f"Precision@{decision_threshold:.0%}={result['precision_at_threshold']:.2%} "
                         f"(duyệt {n_approved}/{len(test_df)} lệnh, {result['approval_rate_at_threshold']:.1%})"
                         if result['precision_at_threshold'] is not None
                         else f"Precision@{decision_threshold:.0%}=N/A (0 lệnh được duyệt)")
        logger.info(f"📅 Fold {fold_idx}: Train {len(train_df)} mẫu (đến {result['train_end'][:10]}) "
                    f"→ Test {len(test_df)} mẫu ({result['test_start'][:10]} → {result['test_end'][:10]}) "
                    f"| Acc={acc:.2%} Precision={prec:.2%} Recall={rec:.2%} | {threshold_str}")

    if not fold_results:
        logger.error("❌ Không có fold nào chạy được (dữ liệu không đủ hoặc phân bố nhãn không hợp lệ).")
        return {"folds": [], "summary": {}, "is_stable": False, "error": "no_valid_folds"}

    precisions = [f["precision"] for f in fold_results]
    accuracies = [f["accuracy"] for f in fold_results]
    precisions_at_threshold = [f["precision_at_threshold"] for f in fold_results if f["precision_at_threshold"] is not None]
    approval_rates = [f["approval_rate_at_threshold"] for f in fold_results]

    summary = {
        "n_folds_run": len(fold_results),
        "precision_mean": float(np.mean(precisions)),
        "precision_std": float(np.std(precisions)),
        "accuracy_mean": float(np.mean(accuracies)),
        "accuracy_std": float(np.std(accuracies)),
        "precision_min": float(np.min(precisions)),
        "precision_max": float(np.max(precisions)),
        "decision_threshold": decision_threshold,
        "precision_at_threshold_mean": float(np.mean(precisions_at_threshold)) if precisions_at_threshold else None,
        "precision_at_threshold_std": float(np.std(precisions_at_threshold)) if precisions_at_threshold else None,
        "avg_approval_rate_at_threshold": float(np.mean(approval_rates)),
        "n_folds_with_approvals": len(precisions_at_threshold),
    }

    # Tieu chi on dinh don gian: do lech chuan cua Precision qua cac fold khong duoc vuot qua 10 diem %
    # (dao dong lon giua cac giai doan thoi gian la dau hieu model khong tong quat hoa tot)
    is_stable = summary["precision_std"] < 0.10

    logger.info(f"📊 TỔNG KẾT WALK-FORWARD (ngưỡng mặc định 0.5): Precision trung bình = {summary['precision_mean']:.2%} "
                f"(độ lệch chuẩn ±{summary['precision_std']:.2%}, dao động {summary['precision_min']:.2%}"
                f"–{summary['precision_max']:.2%} qua {summary['n_folds_run']} fold)")
    if summary["precision_at_threshold_mean"] is not None:
        logger.info(f"📊 TỔNG KẾT WALK-FORWARD (ngưỡng sản xuất {decision_threshold:.0%}): Precision trung bình = "
                    f"{summary['precision_at_threshold_mean']:.2%} (±{summary['precision_at_threshold_std']:.2%}), "
                    f"tỷ lệ lệnh được duyệt trung bình = {summary['avg_approval_rate_at_threshold']:.1%} "
                    f"({summary['n_folds_with_approvals']}/{summary['n_folds_run']} fold có ít nhất 1 lệnh được duyệt)")
    else:
        logger.warning(f"⚠️ Không có fold nào duyệt được lệnh nào ở ngưỡng {decision_threshold:.0%} — "
                       "ngưỡng có thể đang quá cao so với chất lượng model hiện tại.")

    if is_stable:
        logger.info("✅ Model ỔN ĐỊNH qua các giai đoạn thời gian khác nhau (độ lệch chuẩn Precision < 10 điểm %).")
    else:
        logger.warning("⚠️ Model KHÔNG ổn định — Precision dao động mạnh giữa các giai đoạn thời gian "
                       "(độ lệch chuẩn ≥ 10 điểm %). Có thể đang học đặc điểm riêng của 1 giai đoạn thị trường "
                       "cụ thể thay vì quy luật tổng quát. CHƯA nên tin dùng cho live.")

    return {"folds": fold_results, "summary": summary, "is_stable": is_stable}


if __name__ == "__main__":
    import glob
    import os
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    from ai_v5.config_ai import DATASETS_DIR
    from ai_v5.data.data_loader import DataLoader

    combined_path = DataLoader.combine_all_datasets(DATASETS_DIR)
    if not combined_path:
        list_files = glob.glob(os.path.join(DATASETS_DIR, "dataset_*.csv"))
        if not list_files:
            print("❌ Không tìm thấy dataset nào trong ai_v5/datasets/. Hãy chạy build_dataset.py trước.")
            raise SystemExit(1)
        combined_path = max(list_files, key=os.path.getctime)

    df = pd.read_csv(combined_path)
    result = run_walk_forward_validation(df)
    print("\n" + "=" * 70)
    print("KẾT QUẢ WALK-FORWARD VALIDATION")
    print("=" * 70)
    for f in result.get("folds", []):
        thr_str = (f"Precision@{result['summary']['decision_threshold']:.0%}={f['precision_at_threshold']:.2%} "
                   f"(duyệt {f['n_approved_at_threshold']}/{f['n_test']})"
                   if f["precision_at_threshold"] is not None else "0 lệnh duyệt")
        print(f"Fold {f['fold']}: Train {f['n_train']} → Test {f['n_test']} | "
              f"Acc={f['accuracy']:.2%} Precision(0.5)={f['precision']:.2%} Recall={f['recall']:.2%} | {thr_str}")
    if result.get("summary"):
        s = result["summary"]
        print(f"\n--- Ngưỡng mặc định 0.5 ---")
        print(f"Precision trung bình: {s['precision_mean']:.2%} ± {s['precision_std']:.2%}")
        print(f"Ổn định qua thời gian: {'CÓ' if result['is_stable'] else 'KHÔNG'}")
        print(f"\n--- Ngưỡng sản xuất {s['decision_threshold']:.0%} (giống hành vi bot thật) ---")
        if s["precision_at_threshold_mean"] is not None:
            print(f"Precision trung bình: {s['precision_at_threshold_mean']:.2%} ± {s['precision_at_threshold_std']:.2%}")
            print(f"Tỷ lệ lệnh được duyệt: {s['avg_approval_rate_at_threshold']:.1%}")
        else:
            print("Không có lệnh nào được duyệt ở ngưỡng này trong toàn bộ các fold.")
