# backtest_v6_scalping.py
"""
Dat o thu muc GOC bot_xutho4/.

Backtest engine RIENG cho chien luoc DCA scalping cua ai_v6 (M15 bias + M5 xac nhan + M1
entry/exit) - vi backtest_engine.py hien co cua du an duoc thiet ke cho lenh don (v4/ai_v5),
CHUA mo phong duoc nhom DCA nhieu lenh + SL/TP tinh lai theo breakeven dong (da ghi nhan la
viec con ton dong trong README_V6.md muc 7).

NGUYEN TAC QUAN TRONG: dung lai NGUYEN VEN cac ham tinh toan THUAN TUY (khong phu thuoc MT5
live/order_send) tu chinh ai_v6/live/*.py va ai_v5/live/*.py - DAM BAO logic backtest va logic
live GIONG HET NHAU (dung nguyen tac da ap dung xuyen suot du an: tranh lap lai loi
walk_forward.py gia cua ai_v5 truoc day). Cac ham dung lai TRUC TIEP (khong copy/sua):
    - ai_v6.live.mtf_scanner.get_m15_trend_bias()       (M15 bias, co adx_threshold_override de do)
    - ai_v5.live.live_pattern_scanner.scan_all_patterns_live()  (7 nhom pattern M5)
    - ai_v6.live.mtf_scanner.m1_entry_confirmed()        (M1 timing, che do "soft")
    - ai_v6.live.mtf_scanner.calc_m1_atr()               (ATR M1 - co so SL/TP/DCA)
    - ai_v6.live.mtf_scanner.score_match_with_ml()       (cham diem ML - dung model da train)
    - ai_v6.live.position_group_manager.calc_group_average_entry()/calc_group_sl_tp()/
      get_group_direction()/get_group_open_time()        (thuan tuy, khong goi MT5 order_send)

CHI KHONG dung lai duoc cac ham goi MT5 order_send() that (place_v6_trade, apply_sl_tp_to_group
that) - backtest tu mo phong viec mo/dong lenh bang doi tuong SimPosition (class nhe, co du
thuoc tinh .volume/.price_open/.time/.type de tuong thich voi cac ham tren) thay vi lenh MT5 that.

GIOI HAN CAN BIET (don gian hoa hop ly cho backtest, khong phai loi):
    - Chi co OHLC moi nen, KHONG co du lieu tick that -> khi 1 nen M1 cham CA SL va TP cung
      luc, dung quy uoc: nen tang (close>=open) gia dinh gia di Low->High trong nen, nen giam
      gia dinh High->Low. Day la quy uoc pho bien trong backtest OHLC, khong hoan toan chinh
      xac nhung la xap xi hop ly khi khong co du lieu tick.
    - KHONG mo phong spread/slippage/phi qua dem - ket qua la "ly tuong hoa", hieu suat that
      se thap hon 1 chut do cac chi phi nay (dac biet spread quan trong voi scalping tan suat cao).
    - Thuc thi tai gia CLOSE cua nen M1 (khong phai gia ASK/BID thoi gian thuc).
    - Gia dinh 1 lot XAUUSD = 100 oz (chuan quoc te pho bien) de quy doi P&L ra USD - KIEM TRA
      LAI voi contract specification that cua broker ban (dung --contract-oz de chinh neu khac).

Cach dung:
    py -3.11 backtest_v6_scalping.py --days 30
        Chay 1 bo tham so DUY NHAT (dung dung gia tri hien tai trong ai_v6/config_live.py).

    py -3.11 backtest_v6_scalping.py --days 30 --grid-search
        Do NHIEU bo tham so (MAX_HOLD_MINUTES, DCA_TRIGGER_ATR_MULTIPLE, SCALP_SL_ATR_MULTIPLE,
        SCALP_REWARD_RISK_RATIO, M15_ADX_TREND_THRESHOLD), in bang so sanh, goi y bo tot nhat.

    py -3.11 backtest_v6_scalping.py --days 14 --grid-search --quick
        Luoi tham so THU GON (it combo hon) de chay thu nhanh truoc khi chay luoi day du.
"""
import argparse
import csv
import itertools
import logging
import time as time_module
from datetime import datetime, timezone

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backtest_v6")

SYMBOL = "XAUUSD"
BARS_PER_DAY = {"M1": 1440, "M5": 288, "M15": 96}
MIN_BARS_WARMUP = {"M15": 220, "M5": 220, "M1": 100}  # giong MIN_CANDLES_REQUIRED cua live_pattern_scanner.py
RESULTS_CSV_PATH = "backtest_v6_grid_results.csv"  # LUU LIEN TUC tung bo tham so - an toan neu bi ngat giua chung


# ============================================================================
# 1. TAI DU LIEU LICH SU (MT5 truc tiep - can terminal MT5 dang mo tren may)
# ============================================================================

def _load_mt5_candles(symbol: str, timeframe_str: str, days_back: int, offset_days: float = 0.0) -> list:
    """Doc lich su truc tiep tu MT5, giu 'time' la Unix timestamp (int, giay) - DONG BO voi
    dinh dang candle dung xuyen suot du an (feature_builder.py, live_pattern_scanner.py deu
    doi hoi 'time' la so, khong phai pandas Timestamp).

    offset_days: BẢN VÁ (kiểm tra OUT-OF-SAMPLE) - dịch điểm bắt đầu lùi về quá khứ offset_days
    ngày TÍNH TỪ HIỆN TẠI, thay vì luôn lấy days_back ngày GẦN NHẤT. Dùng để test 1 bộ tham số
    đã chọn trên 1 KHOẢNG DỮ LIỆU KHÁC, KHÔNG CHỒNG LẤN với khoảng đã dùng để dò tham số (đúng
    nguyên tắc walk-forward: đừng tin tham số chỉ vì nó tốt trên chính dữ liệu đã dùng để chọn nó)."""
    import MetaTrader5 as mt5

    tf_map = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15}
    n = int(days_back * BARS_PER_DAY[timeframe_str])
    start_pos = int(offset_days * BARS_PER_DAY[timeframe_str])

    mt5.symbol_select(symbol, True)
    rates = mt5.copy_rates_from_pos(symbol, tf_map[timeframe_str], start_pos, n)
    if rates is None or len(rates) == 0:
        return []

    candles = [
        {
            "time": int(r["time"]),
            "open": float(r["open"]), "high": float(r["high"]),
            "low": float(r["low"]), "close": float(r["close"]),
            "volume": float(r["tick_volume"]),  # BẢN VÁ giống build_dataset.py: tick_volume -> volume
        }
        for r in rates
    ]
    actual_days = (candles[-1]["time"] - candles[0]["time"]) / 86400 if len(candles) > 1 else 0
    offset_note = f", lùi {offset_days:.0f} ngày so với hiện tại" if offset_days > 0 else ""
    print(f"📂 Đã tải {len(candles)} nến {timeframe_str} ({actual_days:.1f} ngày thực tế, yêu cầu {days_back} ngày{offset_note})")
    return candles


# ============================================================================
# 2. SimPosition - doi tuong nhe thay the MT5 position that, TUONG THICH voi
#    cac ham thuan tuy cua position_group_manager.py (dung chung thuoc tinh)
# ============================================================================

class SimPosition:
    __slots__ = ("volume", "price_open", "time", "type")

    def __init__(self, volume: float, price_open: float, time_: int, pos_type: int):
        self.volume = volume
        self.price_open = price_open
        self.time = time_
        self.type = pos_type


# ============================================================================
# 3. Vong lap mo phong CHINH - di qua tung nen M1 theo THU TU THOI GIAN, dung
#    LAI cac ham tinh toan that cua ai_v6/ai_v5 (xem doc string dau file)
# ============================================================================

def _check_tp_sl_hit(candle: dict, direction: str, sl: float, tp: float):
    """Kiem tra 1 nen M1 co cham SL/TP khong. Quy uoc khi ca 2 cung cham trong 1 nen (xem
    GIOI HAN CAN BIET o dau file): nen tang -> gia dinh Low truoc (SL truoc cho BUY, TP truoc
    cho SELL); nen giam -> nguoc lai."""
    o, h, l, c = candle["open"], candle["high"], candle["low"], candle["close"]
    is_bull_candle = c >= o

    if direction == "BUY":
        hit_sl, hit_tp = l <= sl, h >= tp
        if hit_sl and hit_tp:
            return (sl, "SL") if is_bull_candle else (tp, "TP")
        if hit_sl:
            return sl, "SL"
        if hit_tp:
            return tp, "TP"
    else:
        hit_sl, hit_tp = h >= sl, l <= tp
        if hit_sl and hit_tp:
            return (tp, "TP") if is_bull_candle else (sl, "SL")
        if hit_sl:
            return sl, "SL"
        if hit_tp:
            return tp, "TP"
    return None, None


def _pick_best_match(matches, predictor, regime_res, score_fn):
    best = None
    for source_type, match in matches:
        win_prob = score_fn(predictor, match, source_type, regime_res)
        if best is None or win_prob > best[2]:
            best = (source_type, match, win_prob)
    return best


def simulate(symbol: str, m15_candles: list, m5_candles: list, m1_candles: list,
             predictor, params: dict, contract_oz_per_lot: float = 100.0, digits: int = 2,
             spread_price: float = 0.0) -> list:
    """
    Chay mo phong tuan tu qua toan bo nen M1, tra ve list cac nhom DA DONG (moi phan tu la
    1 dict thong tin ket qua). Dung LAI cac ham thuan tuy that cua du an - xem docstring dau file.

    spread_price: BẢN VÁ - chenh lech bid/ask uoc tinh (USD), tru vao P&L moi lenh mo trong
    nhom (xem _close_group()). Truoc day = 0.0 (KHONG mo phong spread) khien P&L bi thoi phong,
    dac biet voi bo tham so giao dich tan suat cao.
    """
    import MetaTrader5 as mt5
    from ai_v6.live.mtf_scanner import get_m15_trend_bias, m1_entry_confirmed, calc_m1_atr, score_match_with_ml
    from ai_v6.live.scanner_v6 import scan_all_patterns_live   # v6: nhận diện nến đã sửa + loại nhóm lỗi
    from ai_v6.live.position_group_manager import calc_group_average_entry, get_group_direction

    n1, n5, n15 = len(m1_candles), len(m5_candles), len(m15_candles)
    idx_m5, idx_m15 = 0, 0

    # Cache ket qua M15/M5 theo TUNG BAR (chi tinh lai khi bar do vua dong, khong phai moi
    # nen M1) - giam O(n) lap lai vo ich, quan trong de grid-search chay du nhanh.
    cache_m15_idx, cache_bias, cache_regime = -1, None, None
    cache_m5_idx, cache_all_matches = -1, []

    trades = []
    group = None  # None hoac dict {"direction","positions":[SimPosition,...],"opened_time","last_dca_time","sl","tp"}

    LOOKBACK_M15, LOOKBACK_M5, LOOKBACK_M1 = 300, 300, 100

    for i in range(n1):
        candle = m1_candles[i]
        t = candle["time"]

        while idx_m15 < n15 and m15_candles[idx_m15]["time"] + 15 * 60 <= t:
            idx_m15 += 1
        while idx_m5 < n5 and m5_candles[idx_m5]["time"] + 5 * 60 <= t:
            idx_m5 += 1

        if idx_m15 < MIN_BARS_WARMUP["M15"] or idx_m5 < MIN_BARS_WARMUP["M5"] or i < MIN_BARS_WARMUP["M1"]:
            continue

        # --- Kiem tra thoat lenh TRUOC (neu dang co nhom mo) ---
        if group is not None:
            exit_price, exit_reason = _check_tp_sl_hit(candle, group["direction"], group["sl"], group["tp"])
            if exit_price is not None:
                trades.append(_close_group(group, exit_price, t, exit_reason, contract_oz_per_lot,
                                           calc_group_average_entry, spread_price))
                group = None
                continue

            elapsed_min = (t - group["opened_time"]) / 60
            if elapsed_min >= params["MAX_HOLD_MINUTES"]:
                trades.append(_close_group(group, candle["close"], t, "TIMEOUT", contract_oz_per_lot,
                                           calc_group_average_entry, spread_price))
                group = None
                continue

        # --- Cap nhat cache M15 (chi tinh lai khi bar M15 vua dong) ---
        if idx_m15 != cache_m15_idx:
            m15_window = m15_candles[max(0, idx_m15 - LOOKBACK_M15):idx_m15]
            cache_bias, cache_regime = get_m15_trend_bias(
                symbol, m15_window, adx_threshold_override=params.get("M15_ADX_TREND_THRESHOLD"))
            cache_m15_idx = idx_m15

        bias_direction, regime_res = cache_bias, cache_regime

        # --- Cap nhat cache M5 (chi tinh lai khi bar M5 vua dong) ---
        if idx_m5 != cache_m5_idx:
            m5_window = m5_candles[max(0, idx_m5 - LOOKBACK_M5):idx_m5]
            cache_all_matches = scan_all_patterns_live(m5_window, symbol)
            cache_m5_idx = idx_m5

        # BẢN VÁ TỐC ĐỘ: calc_m1_atr() chỉ cần period+1=15 nến gần nhất (không phải cả 100 nến
        # LOOKBACK_M1) - m1_entry_confirmed() cũng chỉ cần nến cuối cùng, nên dùng CHUNG 1 cửa sổ
        # nhỏ (15 nến) cho cả 2 việc thay vì 100 nến như trước - giảm đáng kể chi phí lặp lại MỖI
        # nến M1 (khác với M5/M15 vốn đã có cache, phần này chưa cache vì ATR đổi liên tục theo tick).
        m1_atr_window = m1_candles[max(0, i - 14):i + 1]
        atr_m1 = calc_m1_atr(m1_atr_window)
        if atr_m1 <= 0:
            continue

        if group is None:
            if bias_direction is None:
                continue
            matches = [(s, m) for s, m in cache_all_matches if m["direction"] == bias_direction]
            if not matches:
                continue
            if not m1_entry_confirmed(m1_atr_window, bias_direction, strict=False):
                continue

            picked = _pick_best_match(matches, predictor, regime_res, score_match_with_ml)
            if picked is None:
                continue
            _source_type, _match, win_prob = picked
            if win_prob < params["PROBABILITY_THRESHOLD"]:
                continue

            price = candle["close"]
            pos_type = mt5.POSITION_TYPE_BUY if bias_direction == "BUY" else mt5.POSITION_TYPE_SELL
            pos = SimPosition(params["LOT"], price, t, pos_type)
            sl_dist = params["SCALP_SL_ATR_MULTIPLE"] * atr_m1
            sl = price - sl_dist if bias_direction == "BUY" else price + sl_dist
            tp = price + params["SCALP_REWARD_RISK_RATIO"] * sl_dist if bias_direction == "BUY" \
                else price - params["SCALP_REWARD_RISK_RATIO"] * sl_dist
            group = {"direction": bias_direction, "positions": [pos], "opened_time": t,
                     "last_dca_time": t, "sl": round(sl, digits), "tp": round(tp, digits)}

        else:
            if len(group["positions"]) >= params["MAX_DCA_POSITIONS"]:
                continue
            if (t - group["last_dca_time"]) / 60 < params["DCA_MIN_INTERVAL_MINUTES"]:
                continue

            direction = group["direction"]
            avg_entry = calc_group_average_entry(group["positions"])
            price = candle["close"]
            adverse = (avg_entry - price) if direction == "BUY" else (price - avg_entry)
            trigger = params["DCA_TRIGGER_ATR_MULTIPLE"] * atr_m1
            if adverse < trigger:
                continue

            matches = [(s, m) for s, m in cache_all_matches if m["direction"] == direction]
            if not matches:
                continue
            if not m1_entry_confirmed(m1_atr_window, direction, strict=False):
                continue

            picked = _pick_best_match(matches, predictor, regime_res, score_match_with_ml)
            if picked is None:
                continue
            _source_type, _match, win_prob = picked
            if win_prob < params["PROBABILITY_THRESHOLD"]:
                continue

            pos_type = mt5.POSITION_TYPE_BUY if direction == "BUY" else mt5.POSITION_TYPE_SELL
            group["positions"].append(SimPosition(params["LOT"], price, t, pos_type))
            group["last_dca_time"] = t

            new_avg = calc_group_average_entry(group["positions"])
            sl_dist = params["SCALP_SL_ATR_MULTIPLE"] * atr_m1
            sl = new_avg - sl_dist if direction == "BUY" else new_avg + sl_dist
            tp = new_avg + params["SCALP_REWARD_RISK_RATIO"] * sl_dist if direction == "BUY" \
                else new_avg - params["SCALP_REWARD_RISK_RATIO"] * sl_dist
            group["sl"], group["tp"] = round(sl, digits), round(tp, digits)

    if group is not None:
        trades.append(_close_group(group, m1_candles[-1]["close"], m1_candles[-1]["time"],
                                   "END_OF_DATA", contract_oz_per_lot, calc_group_average_entry, spread_price))

    return trades


def _close_group(group: dict, exit_price: float, exit_time: int, reason: str,
                 contract_oz_per_lot: float, calc_avg_entry_fn, spread_price: float = 0.0) -> dict:
    """
    spread_price: BẢN VÁ - chênh lệch bid/ask ước tính (đơn vị GIÁ, vd 0.25 USD cho XAUUSD
    spread ~25 points) - trước đây backtest KHÔNG trừ chi phí này, khiến P&L bị THỔI PHỒNG,
    đặc biệt nghiêm trọng với các bộ tham số giao dịch TẦN SUẤT CAO (nhiều nhóm/DCA nhiều lệnh
    - mỗi lệnh đều phải trả spread khi mở). Trừ TRỰC TIẾP vào P&L, tính TRÊN TỪNG VỊ THẾ trong
    nhóm (kể cả lệnh DCA - mỗi lệnh mở đều tốn spread riêng).
    """
    positions = group["positions"]
    total_volume = sum(p.volume for p in positions)
    avg_entry = calc_avg_entry_fn(positions)
    direction = group["direction"]
    price_diff = (exit_price - avg_entry) if direction == "BUY" else (avg_entry - exit_price)
    pnl_usd = price_diff * total_volume * contract_oz_per_lot

    spread_cost_usd = spread_price * total_volume * contract_oz_per_lot
    pnl_usd -= spread_cost_usd

    return {
        "direction": direction, "n_positions": len(positions), "avg_entry": avg_entry,
        "exit_price": exit_price, "exit_reason": reason,
        "opened_time": group["opened_time"], "closed_time": exit_time,
        "hold_minutes": (exit_time - group["opened_time"]) / 60,
        "total_volume": total_volume, "pnl_usd": pnl_usd, "spread_cost_usd": spread_cost_usd,
    }


# ============================================================================
# 4. Bao cao ket qua 1 bo tham so
# ============================================================================

def _summarize(trades: list) -> dict:
    if not trades:
        return {"n_trades": 0}
    wins = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] <= 0]
    total_pnl = sum(t["pnl_usd"] for t in trades)

    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        cum += t["pnl_usd"]
        peak = max(peak, cum)
        max_dd = min(max_dd, cum - peak)

    by_reason = {}
    for t in trades:
        by_reason[t["exit_reason"]] = by_reason.get(t["exit_reason"], 0) + 1

    return {
        "n_trades": len(trades),
        "win_rate": len(wins) / len(trades),
        "total_pnl_usd": total_pnl,
        "avg_pnl_usd": total_pnl / len(trades),
        "total_spread_cost_usd": sum(t.get("spread_cost_usd", 0.0) for t in trades),
        "avg_hold_minutes": sum(t["hold_minutes"] for t in trades) / len(trades),
        "max_drawdown_usd": max_dd,
        "avg_dca_count": sum(t["n_positions"] for t in trades) / len(trades),
        "by_exit_reason": by_reason,
    }


def _print_summary(label: str, summary: dict) -> None:
    if summary["n_trades"] == 0:
        print(f"{label}: KHÔNG có giao dịch nào (tham số quá chặt hoặc dữ liệu quá ngắn).")
        return
    reasons = ", ".join(f"{k}={v}" for k, v in summary["by_exit_reason"].items())
    print(f"{label}")
    print(f"   Số nhóm giao dịch: {summary['n_trades']} | Win rate: {summary['win_rate']:.1%} | "
          f"Tổng P&L (đã trừ spread): {summary['total_pnl_usd']:+.2f} USD | "
          f"Chi phí spread ước tính: {summary['total_spread_cost_usd']:.2f} USD")
    print(f"   Thời gian giữ TB: {summary['avg_hold_minutes']:.1f} phút | "
          f"Số lệnh DCA TB/nhóm: {summary['avg_dca_count']:.1f} | Max Drawdown: {summary['max_drawdown_usd']:.2f} USD")
    print(f"   Lý do đóng: {reasons}")


# ============================================================================
# 5. Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Backtest chiến lược DCA scalping M15/M5/M1 của ai_v6")
    parser.add_argument("--days", type=int, default=30, help="Số ngày lịch sử M1 cần dùng")
    parser.add_argument("--grid-search", action="store_true", help="Dò nhiều bộ tham số thay vì chỉ 1 bộ")
    parser.add_argument("--quick", action="store_true", help="Lưới tham số THU GỌN khi grid-search (81 bộ, ~75 phút với --days 7)")
    parser.add_argument("--tiny", action="store_true", help="Lưới tham số CỰC NHỎ (16 bộ, ~15 phút với --days 7) - xem nhanh trước khi chạy lưới lớn hơn")
    parser.add_argument("--contract-oz", type=float, default=100.0,
                        help="Số oz/lot chuẩn của broker (mặc định 100.0 - KIỂM TRA LẠI với broker của bạn)")
    parser.add_argument("--min-trades", type=int, default=8,
                        help="Số nhóm giao dịch tối thiểu để 1 bộ tham số được coi là đáng tin cậy trong grid-search "
                             "(mặc định 8 - phù hợp dữ liệu ngắn ngày; TĂNG lên khi chạy --days lớn hơn)")
    parser.add_argument("--spread-points", type=float, default=25.0,
                        help="Spread ước tính (points) trừ vào P&L mỗi lệnh mở - MẶC ĐỊNH 25, "
                             "KIỂM TRA LẠI với spread thật của broker/symbol bạn dùng (xem MT5 Market Watch).")
    parser.add_argument("--reverify-csv", type=str, default=None,
                        help="Đọc lại 1 file CSV kết quả grid-search TRƯỚC ĐÓ, lấy --top N bộ tham số tốt nhất "
                             "(theo total_pnl_usd cũ), CHẠY LẠI có tính spread để xếp hạng lại chính xác - "
                             "NHANH HƠN NHIỀU so với chạy lại toàn bộ lưới.")
    parser.add_argument("--top", type=int, default=15, help="Số bộ tham số lấy ra khi dùng --reverify-csv")
    args = parser.parse_args()

    print("=" * 90)
    print("BACKTEST AI v6 — DCA SCALPING (M15 bias + M5 xác nhận + M1 entry/exit)")
    print("=" * 90)

    from ai_v6.live import mt5_connector
    if not mt5_connector.init():
        print("❌ Không kết nối được MT5 — kiểm tra terminal MT5 đã mở & đăng nhập tài khoản chưa.")
        return

    try:
        if args.reverify_csv:
            _run_reverify(args)
        else:
            _run_backtest(args)
    finally:
        mt5_connector.shutdown()


def _run_reverify(args) -> None:
    """BẢN VÁ: đọc lại kết quả grid-search TRƯỚC ĐÓ (không tính spread), lấy top N bộ theo
    P&L cũ, CHẠY LẠI với spread thật để xếp hạng lại - phát hiện các bộ tham số "thắng giả"
    do tần suất giao dịch cao (nhiều lệnh -> nhiều spread) mà lần chạy gốc không thấy được."""
    import csv as csv_module

    rows = []
    with open(args.reverify_csv, newline="", encoding="utf-8") as f:
        reader = csv_module.DictReader(f)
        for row in reader:
            if row.get("n_trades") and row["n_trades"] != "0":
                rows.append(row)

    if not rows:
        print(f"❌ Không đọc được dòng nào có giao dịch từ {args.reverify_csv}")
        return

    rows.sort(key=lambda r: float(r["total_pnl_usd"]), reverse=True)
    top_rows = rows[:args.top]
    print(f"📂 Đã đọc {len(rows)} bộ có giao dịch từ {args.reverify_csv} — lấy TOP {len(top_rows)} theo P&L cũ "
          f"(CHƯA trừ spread) để chạy lại CÓ trừ spread ({args.spread_points} points)...\n")

    m15 = _load_mt5_candles(SYMBOL, "M15", args.days)
    m5 = _load_mt5_candles(SYMBOL, "M5", args.days)
    m1 = _load_mt5_candles(SYMBOL, "M1", args.days)
    if not m15 or not m5 or not m1:
        print("❌ Không tải được đủ dữ liệu M15/M5/M1.")
        return

    import MetaTrader5 as mt5
    sym_info = mt5.symbol_info(SYMBOL)
    digits = sym_info.digits if sym_info else 2
    point = 10 ** (-digits)
    spread_price = args.spread_points * point

    from ai_v6.ml.predictor_v6 import AIPredictorV6
    predictor = AIPredictorV6()
    if predictor.model is None:
        print("❌ Chưa có model AI v6.")
        return

    from ai_v6.config_ai import PROBABILITY_THRESHOLD
    from ai_v6.config_live import MAX_DCA_POSITIONS, DCA_MIN_INTERVAL_MINUTES, FIXED_LOT_DEFAULT

    results = []
    for idx, row in enumerate(top_rows, 1):
        params = {
            "LOT": FIXED_LOT_DEFAULT, "MAX_DCA_POSITIONS": MAX_DCA_POSITIONS,
            "DCA_MIN_INTERVAL_MINUTES": DCA_MIN_INTERVAL_MINUTES, "PROBABILITY_THRESHOLD": PROBABILITY_THRESHOLD,
            "MAX_HOLD_MINUTES": float(row["MAX_HOLD_MINUTES"]),
            "DCA_TRIGGER_ATR_MULTIPLE": float(row["DCA_TRIGGER_ATR_MULTIPLE"]),
            "SCALP_SL_ATR_MULTIPLE": float(row["SCALP_SL_ATR_MULTIPLE"]),
            "SCALP_REWARD_RISK_RATIO": float(row["SCALP_REWARD_RISK_RATIO"]),
        }
        old_pnl = float(row["total_pnl_usd"])
        trades = simulate(SYMBOL, m15, m5, m1, predictor, params, args.contract_oz, digits, spread_price)
        summary = _summarize(trades)
        summary["params"] = params
        summary["old_pnl_no_spread"] = old_pnl
        results.append(summary)
        print(f"   [{idx}/{len(top_rows)}] P&L cũ (không spread)={old_pnl:+.2f} → "
              f"P&L mới (có spread)={summary.get('total_pnl_usd', 0):+.2f} "
              f"(MAX_HOLD={params['MAX_HOLD_MINUTES']}, DCA_TRIG={params['DCA_TRIGGER_ATR_MULTIPLE']}, "
              f"SL_MULT={params['SCALP_SL_ATR_MULTIPLE']}, RR={params['SCALP_REWARD_RISK_RATIO']})")

    trusted = [r for r in results if r["n_trades"] >= args.min_trades]
    trusted.sort(key=lambda r: r["total_pnl_usd"], reverse=True)

    print("\n" + "=" * 90)
    print(f"XẾP HẠNG LẠI SAU KHI TRỪ SPREAD ({args.spread_points} points ~ ${spread_price*args.contract_oz*0.01:.2f}/lệnh 0.01 lot)")
    print("=" * 90)
    for rank, r in enumerate(trusted, 1):
        p = r["params"]
        drop_pct = (1 - r["total_pnl_usd"] / r["old_pnl_no_spread"]) * 100 if r["old_pnl_no_spread"] else 0
        print(f"\n#{rank} — P&L có spread: {r['total_pnl_usd']:+.2f} USD (P&L gốc không spread: "
              f"{r['old_pnl_no_spread']:+.2f}, giảm {drop_pct:.0f}%) | Win rate: {r['win_rate']:.1%} | "
              f"Số nhóm: {r['n_trades']} | Chi phí spread: {r['total_spread_cost_usd']:.2f} USD | "
              f"Max DD: {r['max_drawdown_usd']:.2f} USD")
        print(f"   MAX_HOLD_MINUTES={p['MAX_HOLD_MINUTES']} | DCA_TRIGGER_ATR_MULTIPLE={p['DCA_TRIGGER_ATR_MULTIPLE']} | "
              f"SCALP_SL_ATR_MULTIPLE={p['SCALP_SL_ATR_MULTIPLE']} | SCALP_REWARD_RISK_RATIO={p['SCALP_REWARD_RISK_RATIO']}")

    if trusted:
        best = trusted[0]
        bp = best["params"]
        print("\n" + "=" * 90)
        print("👉 GỢI Ý SAU KHI TÍNH SPREAD — dán vào ai_v6/config_live.py:")
        print("=" * 90)
        print(f"MAX_HOLD_MINUTES = {bp['MAX_HOLD_MINUTES']}")
        print(f"DCA_TRIGGER_ATR_MULTIPLE = {bp['DCA_TRIGGER_ATR_MULTIPLE']}")
        print(f"SCALP_SL_ATR_MULTIPLE = {bp['SCALP_SL_ATR_MULTIPLE']}")
        print(f"SCALP_REWARD_RISK_RATIO = {bp['SCALP_REWARD_RISK_RATIO']}")


def _run_backtest(args) -> None:
    import MetaTrader5 as mt5
    sym_info_early = mt5.symbol_info(SYMBOL)
    _digits_early = sym_info_early.digits if sym_info_early else 2
    spread_price = args.spread_points * (10 ** (-_digits_early))

    m15 = _load_mt5_candles(SYMBOL, "M15", args.days)
    m5 = _load_mt5_candles(SYMBOL, "M5", args.days)
    m1 = _load_mt5_candles(SYMBOL, "M1", args.days)

    if not m15 or not m5 or not m1:
        print("❌ Không tải được đủ dữ liệu (M15/M5/M1) — kiểm tra tên symbol có đúng không "
              "(tài khoản cent cần hậu tố 'c'), hoặc broker giới hạn lịch sử lưu trữ cho khung nhỏ.")
        return

    import MetaTrader5 as mt5
    sym_info = mt5.symbol_info(SYMBOL)
    digits = sym_info.digits if sym_info else 2

    from ai_v6.ml.predictor_v6 import AIPredictorV6
    predictor = AIPredictorV6()
    if predictor.model is None:
        print("❌ Chưa có model AI v6 (ai_v6/models/latest_model.pkl). Chạy run_init_train_v6.py trước.")
        return

    from ai_v6.config_ai import PROBABILITY_THRESHOLD
    from ai_v6.config_live import (
        MAX_DCA_POSITIONS, DCA_MIN_INTERVAL_MINUTES, FIXED_LOT_DEFAULT,
        SCALP_SL_ATR_MULTIPLE, SCALP_REWARD_RISK_RATIO, DCA_TRIGGER_ATR_MULTIPLE,
        MAX_HOLD_MINUTES, M15_ADX_TREND_THRESHOLD,
    )

    base_params = {
        "LOT": FIXED_LOT_DEFAULT, "MAX_DCA_POSITIONS": MAX_DCA_POSITIONS,
        "DCA_MIN_INTERVAL_MINUTES": DCA_MIN_INTERVAL_MINUTES, "PROBABILITY_THRESHOLD": PROBABILITY_THRESHOLD,
        "SCALP_SL_ATR_MULTIPLE": SCALP_SL_ATR_MULTIPLE, "SCALP_REWARD_RISK_RATIO": SCALP_REWARD_RISK_RATIO,
        "DCA_TRIGGER_ATR_MULTIPLE": DCA_TRIGGER_ATR_MULTIPLE, "MAX_HOLD_MINUTES": MAX_HOLD_MINUTES,
        "M15_ADX_TREND_THRESHOLD": M15_ADX_TREND_THRESHOLD,
    }

    if not args.grid_search:
        print(f"\n🔍 Chạy 1 bộ tham số (đúng giá trị hiện tại trong ai_v6/config_live.py)...\n")
        start = time_module.time()
        trades = simulate(SYMBOL, m15, m5, m1, predictor, base_params, args.contract_oz, digits, spread_price)
        elapsed = time_module.time() - start
        print(f"(chạy hết {elapsed:.1f}s)\n")
        _print_summary("KẾT QUẢ (tham số hiện tại)", _summarize(trades))
        return

    # --- GRID SEARCH ---
    # BẢN VÁ (sau lần chạy --days 30 đầu tiên): kết quả top 1 rơi vào RÌA lưới ở 3/4 tham số
    # (MAX_HOLD_MINUTES=45 là giá trị LỚN NHẤT, DCA_TRIGGER_ATR_MULTIPLE=0.5 là NHỎ NHẤT,
    # SCALP_REWARD_RISK_RATIO=2.0 là LỚN NHẤT đã thử) - dấu hiệu lưới cũ CHƯA ĐỦ RỘNG. Mở rộng
    # lưới mặc định theo đúng hướng dữ liệu đang chỉ ra, thu hẹp SCALP_SL_ATR_MULTIPLE (không ở
    # rìa, đã tương đối ổn định quanh 1.6) để giữ tổng số bộ trong tầm kiểm soát thời gian.
    if args.tiny:
        grid = {
            "MAX_HOLD_MINUTES": [10, 30],
            "DCA_TRIGGER_ATR_MULTIPLE": [0.5, 1.5],
            "SCALP_SL_ATR_MULTIPLE": [0.8, 1.6],
            "SCALP_REWARD_RISK_RATIO": [1.0, 1.6],
        }
    elif args.quick:
        grid = {
            "MAX_HOLD_MINUTES": [10, 20, 30],
            "DCA_TRIGGER_ATR_MULTIPLE": [0.5, 1.0, 1.5],
            "SCALP_SL_ATR_MULTIPLE": [0.8, 1.2, 1.6],
            "SCALP_REWARD_RISK_RATIO": [1.0, 1.3, 1.6],
        }
    else:
        grid = {
            "MAX_HOLD_MINUTES": [10, 15, 20, 30, 45],
            "DCA_TRIGGER_ATR_MULTIPLE": [0.5, 1.0, 1.5, 2.0],
            "SCALP_SL_ATR_MULTIPLE": [0.8, 1.2, 1.6, 2.0],
            "SCALP_REWARD_RISK_RATIO": [1.0, 1.3, 1.6, 2.0],
        }

    keys = list(grid.keys())
    combos = list(itertools.product(*[grid[k] for k in keys]))
    est_seconds_per_combo = max(1.0, (len(m1) / 10080.0) * 55.4)  # ngoai suy tu 1 lan chay --days 7 thuc te
    est_total_hours = (len(combos) * est_seconds_per_combo) / 3600
    print(f"\n🔍 Grid-search: {len(combos)} bộ tham số | ước tính ~{est_seconds_per_combo:.0f}s/bộ "
          f"→ TỔNG ~{est_total_hours:.1f} giờ (ước lượng thô, có thể lệch). Spread mô phỏng: "
          f"{args.spread_points} points.")
    print(f"   Kết quả được LƯU LIÊN TỤC vào {RESULTS_CSV_PATH} sau mỗi bộ — an toàn nếu phải dừng "
          f"giữa chừng (Ctrl+C) hoặc mất điện, KHÔNG mất dữ liệu đã chạy.\n")

    results = []
    start_all = time_module.time()
    interrupted = False

    with open(RESULTS_CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["combo_idx"] + keys + ["n_trades", "win_rate", "total_pnl_usd", "avg_pnl_usd",
                                                  "avg_hold_minutes", "max_drawdown_usd", "avg_dca_count"])
        f.flush()

        try:
            for idx, combo in enumerate(combos, 1):
                params = dict(base_params)
                params.update(dict(zip(keys, combo)))
                trades = simulate(SYMBOL, m15, m5, m1, predictor, params, args.contract_oz, digits, spread_price)
                summary = _summarize(trades)
                summary["params"] = params
                results.append(summary)

                row = [idx] + list(combo)
                if summary["n_trades"] > 0:
                    row += [summary["n_trades"], f"{summary['win_rate']:.4f}", f"{summary['total_pnl_usd']:.2f}",
                            f"{summary['avg_pnl_usd']:.2f}", f"{summary['avg_hold_minutes']:.1f}",
                            f"{summary['max_drawdown_usd']:.2f}", f"{summary['avg_dca_count']:.2f}"]
                else:
                    row += [0, "", "", "", "", "", ""]
                writer.writerow(row)
                f.flush()  # GHI NGAY xuong dia, khong doi buffer day - dam bao an toan khi bi ngat giua chung

                if idx % 5 == 0 or idx == len(combos):
                    elapsed = time_module.time() - start_all
                    avg_per_combo = elapsed / idx
                    remaining_h = avg_per_combo * (len(combos) - idx) / 3600
                    print(f"   ... {idx}/{len(combos)} bộ xong ({elapsed/60:.1f} phút đã chạy, "
                          f"ước còn ~{remaining_h:.1f} giờ)")
        except KeyboardInterrupt:
            interrupted = True
            print(f"\n⚠️ ĐÃ DỪNG theo yêu cầu (Ctrl+C) sau {len(results)}/{len(combos)} bộ tham số.")
            print(f"   Toàn bộ {len(results)} bộ đã chạy xong vẫn được lưu tại {RESULTS_CSV_PATH} "
                  f"và sẽ được tổng kết ngay dưới đây (dựa trên phần đã chạy, chưa phải toàn bộ lưới).")

    total_elapsed = time_module.time() - start_all
    if not interrupted:
        print(f"\n✅ Grid-search HOÀN TẤT — tổng thời gian: {total_elapsed/3600:.2f} giờ. "
              f"Kết quả đầy đủ đã lưu tại {RESULTS_CSV_PATH}\n")

    trusted = [r for r in results if r["n_trades"] >= args.min_trades]
    if not trusted:
        print(f"⚠️ KHÔNG bộ tham số nào đạt tối thiểu {args.min_trades} nhóm giao dịch (trong số "
              f"{len(results)} bộ đã chạy) — dữ liệu --days={args.days} có thể quá ngắn, hoặc tham số "
              f"quá chặt. Thử tăng --days hoặc giảm --min-trades. File CSV vẫn còn nguyên nếu muốn tự xem lại.")
        return

    trusted.sort(key=lambda r: r["total_pnl_usd"], reverse=True)

    print("=" * 90)
    print(f"TOP 10 BỘ THAM SỐ TỐT NHẤT (theo Tổng P&L, chỉ tính bộ có ≥{args.min_trades} nhóm giao dịch, "
          f"trong số {len(results)}/{len(combos)} bộ đã chạy)")
    print("=" * 90)
    for rank, r in enumerate(trusted[:10], 1):
        p = r["params"]
        print(f"\n#{rank} — Tổng P&L: {r['total_pnl_usd']:+.2f} USD | Win rate: {r['win_rate']:.1%} | "
              f"Số nhóm: {r['n_trades']} | Max DD: {r['max_drawdown_usd']:.2f} USD")
        print(f"   MAX_HOLD_MINUTES={p['MAX_HOLD_MINUTES']} | DCA_TRIGGER_ATR_MULTIPLE={p['DCA_TRIGGER_ATR_MULTIPLE']} | "
              f"SCALP_SL_ATR_MULTIPLE={p['SCALP_SL_ATR_MULTIPLE']} | SCALP_REWARD_RISK_RATIO={p['SCALP_REWARD_RISK_RATIO']}")

    best = trusted[0]
    bp = best["params"]
    print("\n" + "=" * 90)
    print("👉 GỢI Ý — dán vào ai_v6/config_live.py:")
    print("=" * 90)
    print(f"MAX_HOLD_MINUTES = {bp['MAX_HOLD_MINUTES']}")
    print(f"DCA_TRIGGER_ATR_MULTIPLE = {bp['DCA_TRIGGER_ATR_MULTIPLE']}")
    print(f"SCALP_SL_ATR_MULTIPLE = {bp['SCALP_SL_ATR_MULTIPLE']}")
    print(f"SCALP_REWARD_RISK_RATIO = {bp['SCALP_REWARD_RISK_RATIO']}")
    print(f"\n⚠️ Đây là kết quả TỐI ƯU HÓA TRÊN CHÍNH TẬP DỮ LIỆU ĐÃ DÒ (--days={args.days}) — "
          f"có rủi ro overfitting giống hệt bài học đã rút ra với model ML (walk-forward). Nên kiểm "
          f"chứng lại bộ tham số này trên MỘT GIAI ĐOẠN DỮ LIỆU KHÁC (vd chạy lại với ngày gần đây "
          f"hơn/xa hơn) trước khi tin dùng, và luôn nhớ: không mô phỏng spread/slippage — hiệu suất "
          f"live thực tế sẽ thấp hơn con số này.")
    if interrupted:
        print(f"\nℹ️ Lưu ý: kết quả trên chỉ dựa trên {len(results)}/{len(combos)} bộ đã kịp chạy "
              f"(do bị dừng giữa chừng) — có thể chạy lại đầy đủ sau nếu muốn khảo sát toàn bộ lưới.")


if __name__ == "__main__":
    main()
