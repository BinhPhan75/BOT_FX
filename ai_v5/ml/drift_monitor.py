# ai_v5/ml/drift_monitor.py
"""
Kiem tra "lech phan phoi" (Data Drift) giua dac trung cua CAC LENH THAT gan
day (ai_v5_trades.db) so voi dac trung trong DATASET LICH SU dang dung de
train model hien tai. Neu thi truong gan day co dac diem khac han so voi
giai doan model duoc hoc, canh bao de can nhac train lai som hon lich thong
thuong.

[VIET LAI TU DAU, khong vá code cu] Ban ai_learner.py/drift_detector.py
truoc day (thuoc bot v4, da bi go khoi vong lap khi tach bach ai_v5 - ban
12) co loi thiet ke: so sanh COT THO cua trades.db (vd entry_price, ticket)
thay vi COT DAC TRUNG DA TRICH XUAT (rsi_14, atr_value...) - khien co che
phat hien lech KHONG BAO GIO kich hoat duoc vi 2 ben khac dinh dang hoan
toan. Ban nay dung THANG features_json da luu (cung dinh dang FEATURE_COLUMNS
voi dataset training), tranh lap lai loi cu.

Cach dung:
    python -m ai_v5.ml.drift_monitor
"""
import os
import json
import sqlite3
import logging
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

from ai_v5.config_ai import AI_BASE_DIR, DATASETS_DIR
from ai_v5.data.feature_schema import FEATURE_COLUMNS

logger = logging.getLogger("ai_v5_drift_monitor")

DB_PATH = os.path.abspath(os.path.join(AI_BASE_DIR, "..", "ai_v5_trades.db"))

# Chi so sanh cac dac trung SO (bo qua cac cot ma-hoa phan loai nhu
# pattern_encoded/source_type_encoded - so sanh trung binh cua ma phan loai
# khong co y nghia thong ke).
NUMERIC_DRIFT_FEATURES = ["adx_value", "rsi_14", "volume_ratio", "atr_value", "hour_of_day"]

# Lech tuong doi (%) vuot qua muc nay o 1 dac trung duoc coi la dang chu y.
DRIFT_THRESHOLD_PCT = 30.0
# So dac trung bi lech vuot nguong tro len moi coi la "drift dang ke", can canh bao.
MIN_DRIFTED_FEATURES_TO_ALERT = 2

MIN_RECENT_TRADES = 15  # Can it nhat bay nhieu lenh that gan day moi du tin cay de so sanh


def _load_recent_live_features(lookback_days: int = 30) -> pd.DataFrame:
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()

    # Dam bao schema DB da duoc nang cap truoc khi truy van cot features_json
    # (cung ly do nhu live_feedback.py - tranh loi "no such column" neu ham nay
    # chay truoc khi co lenh moi nao duoc ghi trong phien hien tai).
    from ai_v5.live import trade_logger
    trade_logger._ensure_table()

    conn = sqlite3.connect(DB_PATH)
    cutoff = (datetime.now() - timedelta(days=lookback_days)).isoformat()
    df = pd.read_sql_query(
        "SELECT features_json FROM ai_v5_trades WHERE open_time >= ? AND features_json IS NOT NULL",
        conn, params=(cutoff,)
    )
    conn.close()

    if df.empty:
        return pd.DataFrame()

    rows = []
    for raw in df["features_json"]:
        try:
            rows.append(json.loads(raw))
        except Exception:
            continue
    return pd.DataFrame(rows)


def _load_historical_training_features() -> pd.DataFrame:
    """Doc dataset lich su lon nhat hien co (dataset_patterns_*.csv) lam moc so sanh."""
    import glob
    candidates = glob.glob(os.path.join(DATASETS_DIR, "dataset_patterns_*.csv"))
    if not candidates:
        return pd.DataFrame()
    latest = max(candidates, key=os.path.getctime)
    try:
        return pd.read_csv(latest)
    except Exception as e:
        logger.warning(f"Không đọc được dataset lịch sử {latest}: {e}")
        return pd.DataFrame()


def check_drift(lookback_days: int = 30) -> dict:
    """
    Tra ve dict: {"has_drift": bool, "n_recent_trades": int, "drifted_features": [...],
                  "details": {feature: {"historical_mean": .., "recent_mean": .., "pct_change": ..}}}
    """
    recent = _load_recent_live_features(lookback_days)
    historical = _load_historical_training_features()

    result = {"has_drift": False, "n_recent_trades": len(recent), "drifted_features": [], "details": {}}

    if len(recent) < MIN_RECENT_TRADES:
        logger.info(f"Chỉ có {len(recent)} lệnh thật gần đây (cần ≥{MIN_RECENT_TRADES}) — "
                    f"chưa đủ để đánh giá drift đáng tin cậy, bỏ qua.")
        return result

    if historical.empty:
        logger.warning("Không có dataset lịch sử để so sánh — bỏ qua kiểm tra drift.")
        return result

    for feat in NUMERIC_DRIFT_FEATURES:
        if feat not in recent.columns or feat not in historical.columns:
            continue
        hist_mean = float(historical[feat].mean())
        recent_mean = float(recent[feat].mean())
        if abs(hist_mean) < 1e-9:
            continue  # Tranh chia cho 0
        pct_change = abs(recent_mean - hist_mean) / abs(hist_mean) * 100

        result["details"][feat] = {
            "historical_mean": round(hist_mean, 4),
            "recent_mean": round(recent_mean, 4),
            "pct_change": round(pct_change, 1),
        }
        if pct_change >= DRIFT_THRESHOLD_PCT:
            result["drifted_features"].append(feat)

    result["has_drift"] = len(result["drifted_features"]) >= MIN_DRIFTED_FEATURES_TO_ALERT

    if result["has_drift"]:
        logger.warning(f"⚠️ Phát hiện DRIFT trên {len(result['drifted_features'])} đặc trưng: "
                       f"{result['drifted_features']} — nên cân nhắc train lại sớm hơn lịch thường lệ.")
    else:
        logger.info(f"✅ Không phát hiện drift đáng kể (dựa trên {len(recent)} lệnh thật gần đây).")

    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    result = check_drift()
    print(json.dumps(result, indent=2, ensure_ascii=False))
