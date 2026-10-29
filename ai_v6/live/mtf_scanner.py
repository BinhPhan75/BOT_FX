# ai_v6/live/mtf_scanner.py
"""
Logic da khung thoi gian rieng cho ai_v6:

    - M15 (TF_TREND): xac dinh XU HUONG LON (bias BUY/SELL cho ca nhom DCA)
      qua market_regime.get_regime() (module dung chung voi bot v4/ai_v5).
      Neu trend_dir = "neutral" -> KHONG mo nhom moi (chua du ro rang de
      cam ket vao 1 chieu duy nhat cho ca chuoi DCA).

    - M5 (TF_CONFIRM): xac nhan vung/pattern - dung LAI NGUYEN VEN 7 nhom
      detector cua ai_v5 (scan_all_patterns_live, khong sua logic), CHI LOC
      lai cac match CUNG HUONG voi bias M15.

    - M1 (TF_ENTRY): thoi diem vao lenh/kich hoat DCA - CHU DICH khong chay
      lai bo detector pattern nao tren M1 (dung theo yeu cau: M1 chi de tim
      diem vao chinh xac hon, SL/TP van neo theo cau truc M5/M15). Chi dung
      1 dieu kien don gian: nen M1 DA DONG gan nhat phai CUNG HUONG voi tin
      hieu, tranh vao lenh dung luc dong luong M1 dang danh vong nguoc lai.

QUAN TRONG: toan bo logic phat hien pattern (7 nhom) va cham diem ML deu
TAI SU DUNG NGUYEN VEN tu ai_v5 (import truc tiep) - dung dung yeu cau "giu
nguyen cac phuong phap phan tich ky thuat" cua bot v5.
"""
import logging

from ai_v6.live.scanner_v6 import scan_all_patterns_live   # v6: nhận diện nến đã sửa + loại nhóm lỗi
from ai_v5.live.feature_builder import build_feature_dict

logger = logging.getLogger("ai_v6_mtf_scanner")


def get_m15_trend_bias(symbol: str, m15_candles: list, adx_threshold_override: float = None):
    """
    Tra ve (direction, regime_res). direction la None neu M15 chua co xu huong ro rang.

    adx_threshold_override: CHI dung boi backtest_v6_scalping.py de do nhieu nguong ADX khac
    nhau ma khong phai sua config_live.py moi lan - neu None (mac dinh, dung trong live that),
    dung DUNG ngương M15_ADX_TREND_THRESHOLD trong config_live.py nhu binh thuong.
    """
    import market_regime
    from ai_v6.config_live import M15_ADX_TREND_THRESHOLD

    threshold = adx_threshold_override if adx_threshold_override is not None else M15_ADX_TREND_THRESHOLD

    adx_data = market_regime.calc_adx(m15_candles, period=14)
    if adx_data is None:
        logger.warning(f"Không tính được ADX M15 cho {symbol} (chưa đủ dữ liệu nến).")
        return None, None

    adx = adx_data["adx"]
    di_plus = adx_data["di_plus"]
    di_minus = adx_data["di_minus"]

    if adx < threshold:
        trend_dir = "neutral"
        regime_label = market_regime.REGIME_RANGING
    else:
        trend_dir = "bullish" if di_plus > di_minus else "bearish"
        regime_label = market_regime.REGIME_TRENDING

    regime_res = market_regime.RegimeResult(
        regime=regime_label, adx=adx, di_plus=di_plus, di_minus=di_minus,
        trend_dir=trend_dir, allowed=True,
        reason=f"[ai_v6 riêng] ADX={adx:.1f} so với ngưỡng riêng={threshold} "
               f"(KHÔNG dùng ngưỡng chung 25 của v4/ai_v5)",
    )

    if trend_dir == "bullish":
        return "BUY", regime_res
    if trend_dir == "bearish":
        return "SELL", regime_res
    return None, regime_res


def get_m5_confirmed_matches(symbol: str, m5_candles: list, bias_direction: str) -> list:
    """Quet 7 nhom pattern tren M5 (dung LAI ai_v5.live_pattern_scanner nguyen ven),
    chi giu lai cac match CUNG HUONG voi bias M15. Tra ve [(source_type, match), ...]."""
    all_matches = scan_all_patterns_live(m5_candles, symbol)
    return [(stype, m) for stype, m in all_matches if m["direction"] == bias_direction]


def m1_entry_confirmed(m1_candles: list, direction: str, strict: bool = True) -> bool:
    """
    Xac nhan DIEM VAO tren M1. Co 2 CHE DO:

    strict=True (mac dinh CU, khat khe): nen M1 DA DONG gan nhat PHAI cung chieu tuyet doi
    voi tin hieu (BUY -> nen tang, SELL -> nen giam). Day la dieu kien AND thu 3 (sau M15+M5),
    khien tin hieu rat hiem - LAP LAI dung loi thiet ke da ghi nhan voi bot v4 ("AND-logic
    kills signal frequency" - xem README_HANDOFF_1.md).

    strict=False (BẢN VÁ, KHUYẾN NGHỊ mặc định mới): chỉ TỪ CHỐI khi nến M1 NGƯỢC CHIỀU RÕ RỆT
    (thân nến chiếm > 55% biên độ nến - động lượng ngược THỰC SỰ mạnh). Nến cùng chiều, nến
    yếu, hoặc doji đều được cho qua - đúng tinh thần ban đầu "M1 chỉ để tìm điểm vào chính xác
    hơn", không phải 1 lớp AND cứng thứ 3 chồng lên M15+M5.

    Dieu chinh qua M1_STRICT_CONFIRMATION trong config_live.py.
    """
    if not m1_candles or len(m1_candles) < 1:
        return False
    last = m1_candles[-1]
    is_bullish_candle = last["close"] > last["open"]

    if strict:
        return is_bullish_candle if direction == "BUY" else not is_bullish_candle

    body = abs(last["close"] - last["open"])
    rng = max(last["high"] - last["low"], 1e-9)
    is_strong_opposing = (body / rng > 0.55) and (
        (direction == "BUY" and not is_bullish_candle) or (direction == "SELL" and is_bullish_candle)
    )
    return not is_strong_opposing


def score_match_with_ml(predictor, match: dict, source_type: str, regime_res) -> float:
    """Dung LAI feature_builder.build_feature_dict() + AIPredictor cua ai_v5 (khong sua)
    de cham diem 1 match. Luu y: features duoc tinh tu ngu canh M5 (match["_atr"],
    "_rsi_14"... duoc gan boi scan_all_patterns_live khi quet tren candles M5)."""
    features = build_feature_dict(match, source_type, regime_res)
    return predictor.predict_probability(features)


def calc_m1_atr(m1_candles: list, period: int = 14) -> float:
    """
    BẢN VÁ (thiết kế lại thành SCALPING): tính ATR THEO KHUNG M1 (khác atr của match, vốn
    tính trên M5) - dùng làm cơ sở SL/TP/DCA kiểu scalping thay vì trend/swing. Biên độ M1
    nhỏ hơn nhiều biên độ M5, giúp SL/TP sát giá hơn, khớp đúng ý định "vào nhanh ra nhanh".
    Công thức True Range chuẩn (không dùng thư viện ngoài, tính tay giống feature_engine.py
    của ai_v5), lấy trung bình đơn giản `period` giá trị True Range gần nhất.
    """
    if not m1_candles or len(m1_candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(m1_candles)):
        h = m1_candles[i]["high"]
        l = m1_candles[i]["low"]
        pc = m1_candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    recent = trs[-period:]
    return sum(recent) / len(recent) if recent else 0.0
    
def calc_m1_atr_rolling_mean(m1_candles: list, period: int = 14, lookback: int = 60) -> float:
    """
    BAN VA (chan ATR spike bat thuong): tinh ATR(M1) TRUNG BINH cua nhieu cua so gan day - dung
    lam "muc binh thuong" de SO SANH TUONG DOI voi ATR hien tai, phat hien SPIKE bat thuong thay
    vi dung 1 nguong USD co dinh (bien dong "binh thuong" cua vang thay doi theo tung giai doan
    thi truong). CUNG TINH THAN voi market_regime.py._calc_adx_rolling_mean() da lam cho ADX.

    m1_candles: can >= period + lookback nen de tinh du tin cay, neu khong tra ve 0.0 (bao hieu
    "chua du du lieu, khong ap dung duoc bo loc nay" - ben goi nen COI NHU KHONG SPIKE trong
    truong hop nay, tranh chan lenh oan vi thieu du lieu).
    """
    if len(m1_candles) < period + lookback:
        return 0.0

    values = []
    step = max(1, lookback // 20)  # lay mau thua de nhanh, khong can tinh MOI diem
    start = len(m1_candles) - period - lookback
    end = len(m1_candles) - period
    for i in range(start, end, step):
        window = m1_candles[max(0, i):i + period]
        if len(window) < period:
            continue
        trs = []
        for j in range(1, len(window)):
            h, l = window[j]["high"], window[j]["low"]
            pc = window[j - 1]["close"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        if trs:
            values.append(sum(trs) / len(trs))

    return sum(values) / len(values) if values else 0.0