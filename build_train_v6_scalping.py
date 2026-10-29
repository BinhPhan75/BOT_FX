# build_train_v6_scalping.py
"""
Dat o thu muc GOC bot_xutho4/.

XAY DUNG LAI dataset train cho model AI v6 VOI NHAN (WIN/LOSS) TINH DUNG THEO CO CHE
SCALPING THAT dang chay live (SL/TP theo ATR khung M1, R:R theo SCALP_REWARD_RISK_RATIO,
chot theo MAX_HOLD_MINUTES neu chua cham TP/SL) - THAY vi nhan CU (dataset_patterns_*.csv
sinh boi run_init_train_v6.py -> ai_v5.pipeline.build_dataset.py) tinh theo SL/TP CUA RIENG
TUNG PATTERN (R:R~1.5, bien do M5) - co che da KHONG CON DUNG ke tu khi chuyen sang scalping.

Day rat co the la nguyen nhan khien model hien tai (train TRUOC khi co scalping) cham diem
WinProb THAP MOT CACH HE THONG (~37-39%) ke ca voi tin hieu hop le tren M15/M5 khi chay live -
model dang duoc hoi "tin hieu nay co thang theo SL/TP CU khong", trong khi cau hoi THAT SU
can tra loi la "tin hieu nay co thang theo SL/TP SCALPING MOI khong".

NGUYEN TAC: dung lai TOI DA cac ham thuan tuy da co (khong copy/sua):
    - backtest_v6_scalping._load_mt5_candles()      (tai du lieu, da vay bars/day + volume)
    - backtest_v6_scalping._check_tp_sl_hit()        (quy uoc cham SL/TP trong 1 nen OHLC)
    - ai_v5.live.live_pattern_scanner.scan_all_patterns_live()  (7 nhom pattern M5)
    - ai_v6.live.mtf_scanner.get_m15_trend_bias()/calc_m1_atr() (bias M15 + ATR M1)
    - ai_v5.live.feature_builder.build_feature_dict()  (dong goi feature dung schema)
CHI viet MOI phan "quet tien ve tuong lai qua M1 de xac dinh thang/thua dung CO CHE SCALPING".

QUAN TRONG: CHI tao mau training cho cac match ma M15 bias KHOP CHIEU voi match (dung boi loc
GIONG HET get_m5_confirmed_matches() dang dung khi live) - vi model THAT SU chi bao gio duoc
goi cham diem cho nhung tin hieu da qua loc nay. Neu dua ca tin hieu KHONG khop chieu M15 vao
training, phan phoi du lieu train se lech voi phan phoi model thuc su gap khi live.

Cach dung:
    py -3.11 build_train_v6_scalping.py --days 60
        Quet lich su 60 ngay, xay dataset moi, train model moi, luu vao ai_v6/models/.

    py -3.11 build_train_v6_scalping.py --days 60 --dataset-only
        Chi tao dataset CSV, KHONG train ngay (de tu chay diagnose/tune truoc neu muon).
"""
import argparse
import logging
import os
from datetime import datetime, timezone

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("build_train_v6_scalping")

# Tai su dung TRUC TIEP tu backtest_v6_scalping.py (khong copy/sua) - dam bao logic tai du
# lieu + quy uoc cham SL/TP GIONG HET giua "tao dataset train" va "backtest kiem chung".
from backtest_v6_scalping import _load_mt5_candles, MIN_BARS_WARMUP, _check_tp_sl_hit

from ai_v6.live.scanner_v6 import scan_all_patterns_live   # v6: nhận diện nến đã sửa + loại nhóm lỗi
from ai_v5.live.feature_builder import build_feature_dict
from ai_v5.data.feature_schema import FEATURE_COLUMNS, TARGET_COLUMN
from ai_v6.live.mtf_scanner import get_m15_trend_bias, calc_m1_atr

SYMBOL = "XAUUSD"
LOOKBACK_M15, LOOKBACK_M5 = 300, 300


def _resolve_outcome_forward(m1_candles: list, start_idx: int, entry: float, direction: str,
                             sl: float, tp: float, max_hold_minutes: float):
    """
    Quet TIEN VE TUONG LAI qua cac nen M1 (KHONG nhin truoc ngoai pham vi nay - dung nguyen
    tac no-lookahead), xac dinh THANG/THUA dung HET co che THAT dang chay live:
        - Cham TP truoc -> WIN. Cham SL truoc -> LOSS (dung _check_tp_sl_hit - CUNG quy uoc
          voi backtest_v6_scalping.py).
        - Qua max_hold_minutes ma chua cham ca 2 -> dong tai gia hien tai (dung quy uoc
          TIMEOUT cua live), THANG/THUA theo dau P&L tai thoi diem do.

    Tra ve (is_win: bool, resolved: bool). resolved=False neu het du lieu M1 truoc khi giai
    quyet duoc (thuong o CUOI tap du lieu) - mau nay se BI LOAI, vi khong the biet ket qua that.
    """
    start_time = m1_candles[start_idx]["time"]
    for j in range(start_idx, len(m1_candles)):
        c = m1_candles[j]
        elapsed_min = (c["time"] - start_time) / 60
        exit_price, reason = _check_tp_sl_hit(c, direction, sl, tp)
        if exit_price is not None:
            return (reason == "TP"), True
        if elapsed_min >= max_hold_minutes:
            is_win = (c["close"] > entry) if direction == "BUY" else (c["close"] < entry)
            return is_win, True
    return False, False


def build_scalping_dataset(symbol: str, m15_candles: list, m5_candles: list, m1_candles: list,
                           scalp_sl_atr_multiple: float, scalp_rr: float, max_hold_minutes: float) -> pd.DataFrame:
    n15, n5, n1 = len(m15_candles), len(m5_candles), len(m1_candles)
    idx_m15, idx_m1 = 0, 0
    cache_m15_idx, cache_bias, cache_regime = -1, None, None

    samples = []

    for i5 in range(MIN_BARS_WARMUP["M5"], n5):
        t5 = m5_candles[i5]["time"]

        while idx_m15 < n15 and m15_candles[idx_m15]["time"] + 15 * 60 <= t5:
            idx_m15 += 1
        if idx_m15 < MIN_BARS_WARMUP["M15"]:
            continue

        if idx_m15 != cache_m15_idx:
            m15_window = m15_candles[max(0, idx_m15 - LOOKBACK_M15):idx_m15]
            cache_bias, cache_regime = get_m15_trend_bias(symbol, m15_window)
            cache_m15_idx = idx_m15
        bias_direction, regime_res = cache_bias, cache_regime

        # BẢN VÁ QUAN TRỌNG: model THẬT SỰ chỉ được gọi chấm điểm khi M15 bias RÕ RÀNG và tín
        # hiệu M5 KHỚP CHIỀU (get_m5_confirmed_matches trong live_trader.py) - bỏ qua các
        # trường hợp khác để không tạo dữ liệu train "model không bao giờ gặp trong đời thật".
        if bias_direction is None:
            continue

        # BẢN VÁ LOOKAHEAD: nến M5 thứ i5 MỞ lúc t5 và chỉ ĐÓNG lúc t5+5 phút, nhưng điểm vào lệnh
        # (close nến M1 sau t5) nằm TRONG nến đó (~2 phút sau khi mở). Cửa sổ cũ [:i5+1] cho detector
        # thấy trọn OHLC/volume của nến chưa đóng => pattern nến + feature 'biết trước' hướng nến => WR
        # dataset bị thổi phồng so với live/backtest (chỉ dùng nến ĐÃ ĐÓNG). Chỉ dùng nến đã đóng: [:i5].
        m5_window = m5_candles[max(0, i5 - LOOKBACK_M5):i5]
        all_matches = scan_all_patterns_live(m5_window, symbol)
        matches = [(s, m) for s, m in all_matches if m["direction"] == bias_direction]
        if not matches:
            continue

        while idx_m1 < n1 and m1_candles[idx_m1]["time"] <= t5:
            idx_m1 += 1
        if idx_m1 < 14 or idx_m1 >= n1:
            continue

        m1_atr_window = m1_candles[max(0, idx_m1 - 14):idx_m1 + 1]
        atr_m1 = calc_m1_atr(m1_atr_window)
        if atr_m1 <= 0:
            continue

        entry_price = m1_candles[idx_m1]["close"]

        for source_type, match in matches:
            direction = match["direction"]
            sl_dist = scalp_sl_atr_multiple * atr_m1
            sl = entry_price - sl_dist if direction == "BUY" else entry_price + sl_dist
            tp = entry_price + scalp_rr * sl_dist if direction == "BUY" else entry_price - scalp_rr * sl_dist

            is_win, resolved = _resolve_outcome_forward(m1_candles, idx_m1, entry_price, direction, sl, tp, max_hold_minutes)
            if not resolved:
                continue

            # GHI ĐÈ atr/entry_price/sl/tp bằng giá trị SCALPING (không phải giá trị M5 gốc
            # của module detector) - để feature "atr_value"/"distance_to_zone_pct" phản ánh
            # ĐÚNG cơ sở tính SL/TP THẬT đang dùng khi live, đảm bảo train/live nhất quán.
            match = dict(match)
            match["_atr"] = atr_m1
            match["_entry_price"] = entry_price
            match["sl"] = sl
            match["tp"] = tp

            features = build_feature_dict(match, source_type, regime_res)
            features[TARGET_COLUMN] = int(is_win)
            features["symbol"] = symbol
            features["pattern_name"] = match["pattern"]
            features["source_type_name"] = source_type
            features["entry_time"] = datetime.fromtimestamp(m1_candles[idx_m1]["time"], tz=timezone.utc).isoformat()
            samples.append(features)

    return pd.DataFrame(samples)


def main():
    parser = argparse.ArgumentParser(description="Xây dựng lại dataset + train model AI v6 với nhãn ĐÚNG cơ chế scalping")
    parser.add_argument("--days", type=int, default=60, help="Số ngày lịch sử cần dùng")
    parser.add_argument("--dataset-only", action="store_true", help="Chỉ tạo dataset CSV, không train ngay")
    args = parser.parse_args()

    from ai_v6.live import mt5_connector
    if not mt5_connector.init():
        print("❌ Không kết nối được MT5.")
        return

    try:
        from ai_v6.config_live import SCALP_SL_ATR_MULTIPLE, SCALP_REWARD_RISK_RATIO, MAX_HOLD_MINUTES

        m15 = _load_mt5_candles(SYMBOL, "M15", args.days)
        m5 = _load_mt5_candles(SYMBOL, "M5", args.days)
        m1 = _load_mt5_candles(SYMBOL, "M1", args.days)
        if not m15 or not m5 or not m1:
            print("❌ Không tải được đủ dữ liệu (M15/M5/M1).")
            return

        print(f"\n🔨 Đang xây dataset SCALPING (SL={SCALP_SL_ATR_MULTIPLE}×ATR_M1, "
              f"RR={SCALP_REWARD_RISK_RATIO}, MaxHold={MAX_HOLD_MINUTES} phút, "
              f"chỉ lấy tín hiệu KHỚP CHIỀU M15 bias — đúng những gì model thật sự gặp khi live)...\n")
        df = build_scalping_dataset(SYMBOL, m15, m5, m1, SCALP_SL_ATR_MULTIPLE, SCALP_REWARD_RISK_RATIO, MAX_HOLD_MINUTES)

        if df.empty:
            print("❌ Không tạo được mẫu nào — kiểm tra lại dữ liệu/tham số, hoặc tăng --days.")
            return

        print(f"✅ Đã tạo {len(df)} mẫu. Win rate tổng thể (theo nhãn scalping mới): {df[TARGET_COLUMN].mean():.2%}")

        from ai_v6.config_ai import DATASETS_DIR
        os.makedirs(DATASETS_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Đặt tên khớp pattern "dataset_patterns_*.csv" mà diagnose_v6_dataset.py/tune_threshold_v6.py
        # đang tự động dò (lấy file mới nhất) - KHÔNG cần sửa 2 script đó, tự động dùng được ngay.
        out_path = os.path.join(DATASETS_DIR, f"dataset_patterns_scalping_{timestamp}.csv")
        df.to_csv(out_path, index=False)
        print(f"💾 Đã lưu dataset: {out_path}")

        if args.dataset_only:
            print("\n👉 Chạy tiếp để kiểm tra trước khi train:")
            print(f"   py -3.11 diagnose_v6_dataset.py")
            print(f"   py -3.11 tune_threshold_v6.py --dataset \"{out_path}\"")
            return

        from ai_v5.ml.ml_trainer import MLTrainer
        from ai_v5.ml.model_manager import ModelManager
        from ai_v6.config_ai import MODELS_DIR

        print("\n🏋️ Đang train model LightGBM mới (nhãn scalping)...")
        trainer = MLTrainer(dataset_path=out_path, use_combined=False)
        trainer.model_manager = ModelManager(models_dir=MODELS_DIR)
        model_path = trainer.train()
        if model_path:
            print(f"\n✅ Model MỚI (nhãn scalping) đã lưu tại: {model_path}")
            print(f"✅ latest_model.pkl đã cập nhật — bot live sẽ dùng model này ở lần chấm điểm tiếp theo.")
            print(f"\n👉 BẮT BUỘC chạy tiếp để dò lại ngưỡng quyết định cho model MỚI (đừng dùng 0.50 cũ, "
                  f"model mới có phân phối WinProb khác hẳn):")
            print(f"   py -3.11 tune_threshold_v6.py --dataset \"{out_path}\"")
        else:
            print("❌ Train thất bại — kiểm tra log phía trên.")
    finally:
        mt5_connector.shutdown()


if __name__ == "__main__":
    main()