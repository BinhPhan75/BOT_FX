# run_init_train_v6.py
"""
Dat o thu muc GOC bot_xutho4/ (cung cap voi run_init_train.py cua ai_v5).

Train MODEL RIENG cho ai_v6, dua tren du lieu XAUUSD khung M5 (khac ai_v5
dung M15) - vi toan bo pattern/feature cua ai_v6 duoc quet tren khung M5
(TF_CONFIRM trong ai_v6/config_live.py). Neu dung tam latest_model.pkl cua
ai_v5, model se cham diem sai lech vi duoc train tren PHAN PHOI SWING/ATR
cua M15, khac han M5 - giong dung bai hoc "feature distribution changes
require retraining" da rut ra trong qua trinh sua loi distance_to_zone_pct
cua ai_v5 (xem README_HANDOFF_1.md).

Vi ai_v6 TAI SU DUNG NGUYEN VEN pipeline/ (7 nhom detector) va ml/
(MLTrainer, ModelManager) cua ai_v5, script nay CHI la 1 lop MONG dieu
huong dataset -> model sang thu muc ai_v6/ thay vi ai_v5/, khong sua bat
ky logic train/detect nao.

Cach dung:
    py -3.11 run_init_train_v6.py                     # 260 ngay mac dinh
    py -3.11 run_init_train_v6.py --days 400 --source mt5
"""
import argparse
import glob
import logging
import os
import shutil

from ai_v5.pipeline.build_dataset import generate_historical_dataset
from ai_v5.ml.ml_trainer import MLTrainer
from ai_v5.ml.model_manager import ModelManager
from ai_v5.config_ai import DATASETS_DIR as V5_DATASETS_DIR
from ai_v6.config_ai import DATASETS_DIR as V6_DATASETS_DIR, MODELS_DIR as V6_MODELS_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_init_train_v6")


def main():
    parser = argparse.ArgumentParser(description="Train model riêng cho ai_v6 (XAUUSD, khung M5)")
    parser.add_argument("--days", type=int, default=260, help="Số ngày lịch sử tối đa cần dùng")
    parser.add_argument("--source", choices=["csv", "mt5"], default=None,
                        help="Nguồn dữ liệu nến (mặc định: config_ai.HISTORICAL_DATA_SOURCE)")
    args = parser.parse_args()

    # 1. Quet lich su XAUUSD tren khung M5 (khac ai_v5 dung M15). Ham nay ghi vao
    #    ai_v5.config_ai.DATASETS_DIR theo mac dinh (khong sua duoc tu ben ngoai) -
    #    nen sau khi chay xong, COPY file dataset vua tao sang ai_v6/datasets/.
    logger.info("📁 Bắt đầu quét lịch sử XAUUSD khung M5 (dùng lại 7 nhóm detector của ai_v5)...")
    df = generate_historical_dataset(symbols=["XAUUSD"], timeframe="M5", days_back=args.days, source=args.source)
    if df.empty:
        logger.error("❌ Không tạo được dataset M5 cho XAUUSD — kiểm tra bt_cache/XAUUSD_M5_*d.csv "
                     "(hoặc dùng --source mt5 nếu đang chạy trên máy có MT5 mở sẵn).")
        return

    os.makedirs(V6_DATASETS_DIR, exist_ok=True)
    candidates = glob.glob(os.path.join(V5_DATASETS_DIR, "dataset_patterns_*.csv"))
    if not candidates:
        logger.error("❌ Không tìm thấy file dataset vừa tạo trong ai_v5/datasets/.")
        return
    latest = max(candidates, key=os.path.getctime)
    dest = os.path.join(V6_DATASETS_DIR, os.path.basename(latest))
    shutil.copy2(latest, dest)
    logger.info(f"✅ Đã copy dataset M5 sang: {dest}")

    # 2. Train model bang MLTrainer cua ai_v5 (logic GIU NGUYEN 100%), nhung LUU vao
    #    ai_v6/models/ thay vi ai_v5/models/ (dieu huong qua model_manager rieng).
    logger.info("🏋️ Bắt đầu train model LightGBM cho ai_v6 (dùng lại MLTrainer của ai_v5)...")
    trainer = MLTrainer(dataset_path=dest, use_combined=False)
    trainer.model_manager = ModelManager(models_dir=V6_MODELS_DIR)  # Dieu huong noi luu model
    model_path = trainer.train()

    if model_path:
        logger.info(f"✅ Model AI v6 (XAUUSD, khung M5) đã lưu tại: {model_path}")
        logger.info(f"✅ latest_model.pkl đã cập nhật tại: {os.path.join(V6_MODELS_DIR, 'latest_model.pkl')}")
        logger.info("👉 Có thể chạy: py -3.11 -m ai_v6.live.live_trader")
    else:
        logger.error("❌ Train thất bại — kiểm tra log phía trên (thường do dataset quá nhỏ).")


if __name__ == "__main__":
    main()
