# ai_v5/ml/live_feedback.py
"""
VONG PHAN HOI TU HOC: chuyen ket qua THAT cua cac lenh ai_v5 da dong
(ai_v5_trades.db, co san features_json luu tu luc quyet dinh) thanh mau
du lieu training moi, dua vao dataset chung de model lan sau duoc HOC TU
CHINH LICH SU GIAO DICH THAT cua no - khong chi hoc tu mo phong lich su
(build_dataset.py quet nen cu, khong phai lenh that).

Truoc ban vá nay, day la mat xich hoan toan thieu: bot da chay live ca
thang, tich luy hang chuc lenh thang/thua that, nhung model KHONG BAO GIO
duoc cap nhat tu chinh nhung lenh do.

Cach dung:
    python -m ai_v5.ml.live_feedback
"""
import os
import json
import sqlite3
import logging
from datetime import datetime

import pandas as pd

from ai_v5.config_ai import AI_BASE_DIR, DATASETS_DIR
from ai_v5.data.feature_schema import FEATURE_COLUMNS, TARGET_COLUMN

logger = logging.getLogger("ai_v5_live_feedback")

DB_PATH = os.path.abspath(os.path.join(AI_BASE_DIR, "..", "ai_v5_trades.db"))
OUTPUT_PATH = os.path.join(DATASETS_DIR, "dataset_live_feedback.csv")

# BREAKEVEN (lenh dong hoa von, khong ro Thang/Thua ro rang) - mac dinh BO QUA,
# khong dua vao training vi nhan khong ro rang, de tranh gay nhieu.
INCLUDE_BREAKEVEN = False


def export_new_closed_trades_to_dataset(min_new_trades: int = 1) -> int:
    """
    Quet ai_v5_trades.db, lay cac lenh DA DONG (result IS NOT NULL) CHUA duoc
    dua vao dataset (used_for_training=0), chuyen thanh mau training (dung
    dung FEATURE_COLUMNS + TARGET_COLUMN), GHEP vao dataset_live_feedback.csv
    hien co (khong ghi de, tich luy dan qua thoi gian), roi danh dau da dung.

    Tra ve: so luong mau moi vua duoc them.
    """
    if not os.path.exists(DB_PATH):
        logger.info("Chưa có ai_v5_trades.db — chưa có lệnh nào để học từ kết quả thật.")
        return 0

    # Dam bao schema DB da duoc nang cap (them cot features_json/used_for_training)
    # TRUOC khi truy van - truoc day chi trade_logger.log_open_trade()/sync_closed_trades()
    # moi tu nang cap, nen neu ham nay chay TRUOC khi co lenh moi nao duoc ghi trong
    # phien hien tai (vd auto_retrain chay ngay luc khoi dong), DB cu (tao tu ban truoc)
    # se thieu cot moi, gay loi "no such column: used_for_training".
    from ai_v5.live import trade_logger
    trade_logger._ensure_table()

    conn = sqlite3.connect(DB_PATH)
    query = "SELECT * FROM ai_v5_trades WHERE close_time IS NOT NULL AND used_for_training = 0"
    if not INCLUDE_BREAKEVEN:
        query += " AND result != 'BREAKEVEN'"
    df = pd.read_sql_query(query, conn)

    if df.empty:
        conn.close()
        logger.info("Không có lệnh đã đóng nào mới để đưa vào training.")
        return 0

    samples = []
    valid_tickets = []
    for _, row in df.iterrows():
        if not row.get("features_json"):
            # Lenh cu (truoc khi co cot features_json) - khong the tai tao
            # chinh xac vector dac trung, bo qua thay vi doan mo.
            continue
        try:
            features = json.loads(row["features_json"])
        except Exception as e:
            logger.warning(f"Bỏ qua lệnh #{row['ticket']}: features_json lỗi ({e})")
            continue

        missing = [c for c in FEATURE_COLUMNS if c not in features]
        if missing:
            logger.warning(f"Bỏ qua lệnh #{row['ticket']}: thiếu cột đặc trưng {missing}")
            continue

        sample = {c: features[c] for c in FEATURE_COLUMNS}
        sample[TARGET_COLUMN] = 1 if row["result"] == "WIN" else 0
        sample["symbol"] = row["symbol"]
        sample["pattern_name"] = row["pattern"]
        sample["source_type_name"] = row["source_type"]
        sample["entry_time"] = row["open_time"]
        samples.append(sample)
        valid_tickets.append(int(row["ticket"]))

    if not samples:
        conn.close()
        logger.info("Có lệnh đóng mới nhưng không có mẫu hợp lệ để đưa vào training (thiếu features_json).")
        return 0

    new_df = pd.DataFrame(samples)

    if os.path.exists(OUTPUT_PATH):
        existing = pd.read_csv(OUTPUT_PATH)
        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        combined = new_df

    os.makedirs(DATASETS_DIR, exist_ok=True)
    combined.to_csv(OUTPUT_PATH, index=False)

    # Danh dau cac lenh vua dua vao la DA DUNG, tranh lap lai lan sau
    cur = conn.cursor()
    cur.executemany("UPDATE ai_v5_trades SET used_for_training = 1 WHERE ticket = ?",
                     [(t,) for t in valid_tickets])
    conn.commit()
    conn.close()

    logger.info(f"✅ Đã thêm {len(samples)} mẫu từ lệnh THẬT vào {OUTPUT_PATH} "
                f"(tổng cộng hiện có {len(combined)} mẫu phản hồi thật tích luỹ).")
    return len(samples)


def get_live_feedback_summary() -> dict:
    """Thong ke nhanh: hien co bao nhieu mau phan hoi that, ty le thang thuc te theo du lieu nay."""
    if not os.path.exists(OUTPUT_PATH):
        return {"n_samples": 0}
    df = pd.read_csv(OUTPUT_PATH)
    return {
        "n_samples": len(df),
        "win_rate": float(df[TARGET_COLUMN].mean()) if len(df) else None,
        "by_source_type": df.groupby("source_type_name")[TARGET_COLUMN].mean().to_dict() if len(df) else {},
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    n = export_new_closed_trades_to_dataset()
    print(f"Đã thêm {n} mẫu mới từ lệnh thật.")
    print(get_live_feedback_summary())
