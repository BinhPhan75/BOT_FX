"""
market_regime.py
Xác định chế độ thị trường (Market Regime) dựa trên ADX + EMA để lọc tín hiệu.

Tại sao cần điều này?
  Learner học được "shooting_star|SELL|XAUUSD WR=47%" — nhưng con số đó ẩn chứa:
    - WR 65% trong trending market (giá đang có xu hướng rõ)
    - WR 25% trong ranging market (giá đang đi ngang dao động)
  Bot liên tục vào lệnh ở cả 2 chế độ → WR trung bình bị kéo xuống thấp.

  Giải pháp: Phát hiện chế độ thị trường TRƯỚC khi phân tích pattern.
  Chỉ cho phép pattern phù hợp với chế độ đó.

Chế độ thị trường:
  TRENDING  (ADX ≥ 20) → Ưu tiên: BOS, CHoCH, Breakout, Engulfing
  RANGING   (ADX < 20) → Ưu tiên: Double Top/Bottom, Hammer/Shooting Star tại zone
  VOLATILE  (ADX > 40) → Tránh vào lệnh (chaos, spread rộng, SL dễ bị quét)

ADX:
  - Đo CƯỜNG ĐỘ xu hướng (không phải hướng)
  - ADX < 20 = không có xu hướng (ranging)
  - ADX 20-40 = xu hướng rõ (trending)
  - ADX > 40 = xu hướng cực mạnh / biến động bất thường

Tích hợp:
  - watcher.py: gọi get_regime() mỗi khi có signal, lọc pattern không phù hợp
  - backtest_engine.py: ghi thêm cột 'regime' để learner học có context
  - learner.py: phân tích WR theo (pattern|direction|symbol|regime)
"""

from dataclasses import dataclass
from typing import List, Dict, Optional

import config

# v6: SMC pattern (BOS/CHoCH) da co bo loc xu huong RIENG (SuperTrend +
# EMA trong analysis.py), nen KHONG can ADX-regime chan them lan nua theo
# kieu "pattern xu huong ma xay ra luc ranging la gia" (logic nay danh cho
# pattern nen cu, khong con hop ly voi SMC). Xep vao UNIVERSAL — chi bi
# chan khi regime=VOLATILE (van giu nguyen, xem is_volatile ben duoi).
TRENDING_PATTERNS: set = set()
RANGING_PATTERNS: set = set()
UNIVERSAL_PATTERNS = {
    "smc_bullish_bos", "smc_bullish_choch",
    "smc_bearish_bos", "smc_bearish_choch",
}

REGIME_TRENDING  = "trending"
REGIME_RANGING   = "ranging"
REGIME_VOLATILE  = "volatile"
REGIME_UNKNOWN   = "unknown"


@dataclass
class RegimeResult:
    regime: str         # "trending" | "ranging" | "volatile" | "unknown"
    adx: float          # giá trị ADX tính được
    di_plus: float      # +DI (áp lực mua)
    di_minus: float     # -DI (áp lực bán)
    trend_dir: str      # "bullish" | "bearish" | "neutral"
    allowed: bool       # True nếu nên vào lệnh trong chế độ này
    reason: str         # giải thích


def _calc_true_range(candles: List[Dict]) -> List[float]:
    """Tính True Range cho từng nến."""
    trs = []
    for i in range(1, len(candles)):
        h = candles[i]["high"]
        l = candles[i]["low"]
        pc = candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return trs


def calc_adx(candles: List[Dict], period: int = 14) -> Optional[Dict]:
    """
    Wilder ADX chuan xac. Ket qua luon trong [0, 100].
    Seed = MEAN (khong phai SUM) cua period dau — day la diem khac biet
    quan trong giup tranh ADX bi nhan luy len qua cao (vi du 200-400).
    """
    n = len(candles)
    if n < period * 2 + 2:
        return None

    plus_dms, minus_dms, trs = [], [], []
    for i in range(1, n):
        h,  l  = candles[i]["high"],   candles[i]["low"]
        ph, pl = candles[i-1]["high"], candles[i-1]["low"]
        pc     = candles[i-1]["close"]
        up   = h - ph
        down = pl - l
        plus_dms.append(up   if up > down and up > 0   else 0.0)
        minus_dms.append(down if down > up and down > 0 else 0.0)
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))

    def wilder(vals):
        if len(vals) < period:
            return None
        s = sum(vals[:period]) / period   # seed = MEAN, khong phai sum
        result = [s]
        for v in vals[period:]:
            s = (s * (period - 1) + v) / period
            result.append(s)
        return result

    sm_plus  = wilder(plus_dms)
    sm_minus = wilder(minus_dms)
    sm_tr    = wilder(trs)

    if sm_plus is None or sm_tr is None:
        return None

    dx_list = []
    last_dip, last_dim = 0.0, 0.0
    for sp, sm, st in zip(sm_plus, sm_minus, sm_tr):
        if st == 0:
            continue
        dip  = 100.0 * sp / st
        dim  = 100.0 * sm / st
        dsum = dip + dim
        dx   = 100.0 * abs(dip - dim) / dsum if dsum > 0 else 0.0
        dx_list.append(dx)
        last_dip, last_dim = dip, dim

    if len(dx_list) < period:
        return None

    adx_s = sum(dx_list[:period]) / period
    for dx in dx_list[period:]:
        adx_s = (adx_s * (period - 1) + dx) / period

    adx_s    = max(0.0, min(100.0, adx_s))
    last_dip = max(0.0, min(100.0, last_dip))
    last_dim = max(0.0, min(100.0, last_dim))

    return {
        "adx":      round(adx_s,    2),
        "di_plus":  round(last_dip, 2),
        "di_minus": round(last_dim, 2),
    }


def _calc_adx_rolling_mean(candles: List[Dict], period: int, lookback: int = 100) -> float:
    """
    Tính trung bình ADX của `lookback` nến gần nhất để so sánh tương đối.
    Dùng để phát hiện spike bất thường thay vì ngưỡng tuyệt đối.
    """
    values = []
    step = max(1, len(candles) // lookback)
    for i in range(period * 2, len(candles), step):
        sub = candles[max(0, i - period * 2): i + 1]
        r = calc_adx(sub, period)
        if r:
            values.append(r["adx"])
        if len(values) >= lookback:
            break
    return statistics.mean(values) if values else 0.0


def get_regime(candles: List[Dict], symbol: str = "") -> RegimeResult:
    """
    Xác định chế độ thị trường: trending / ranging / volatile.

    Logic mới — kết hợp ngưỡng tuyệt đối + tương đối:

    VOLATILE chỉ khi CẢ HAI điều kiện đúng:
      1. ADX > volatile_thr (config, mặc định XAUUSD=70, EURUSD=55)
      2. ADX > mean_adx × spike_mult (spike bất thường, mặc định 1.8×)
    → Tránh tình trạng XAUUSD trending mạnh bị phân loại nhầm là volatile.

    TRENDING khi ADX > trending_thr (mặc định XAUUSD=25, EURUSD=20).
    RANGING  khi ADX ≤ trending_thr.
    """
    period = getattr(config, "ADX_PERIOD", 14)

    # ── Ngưỡng per-symbol ─────────────────────────────────────────────────────
    trending_cfg = getattr(config, "ADX_TRENDING_THRESHOLD", {})
    volatile_cfg = getattr(config, "ADX_VOLATILE_THRESHOLD", {})

    # Nâng ngưỡng volatile mặc định: XAUUSD bull run 2025-2026 ADX thường 50-80
    default_trending = 25
    default_volatile = 70  # tăng từ 40 → 70 để không block trending mạnh

    trending_thr = (trending_cfg.get(symbol, default_trending)
                    if isinstance(trending_cfg, dict) else int(trending_cfg))
    volatile_thr = (volatile_cfg.get(symbol, default_volatile)
                    if isinstance(volatile_cfg, dict) else int(volatile_cfg))

    adx_data = calc_adx(candles, period)

    if adx_data is None:
        return RegimeResult(
            regime=REGIME_UNKNOWN, adx=0, di_plus=0, di_minus=0,
            trend_dir="neutral", allowed=True,
            reason="Không đủ dữ liệu tính ADX — cho qua (failsafe)"
        )

    adx       = adx_data["adx"]
    di_plus   = adx_data["di_plus"]
    di_minus  = adx_data["di_minus"]
    trend_dir = "bullish" if di_plus > di_minus else "bearish"

    # ── VOLATILE: ngưỡng tuyệt đối + spike tương đối ─────────────────────────
    is_volatile = False
    volatile_reason = ""

    if adx >= volatile_thr:
        # Xác nhận thêm: so với mean ADX lịch sử
        spike_mult = getattr(config, "ADX_SPIKE_MULT", 1.8)
        mean_adx   = _calc_adx_rolling_mean(candles, period, lookback=80)
        if mean_adx > 0 and adx > mean_adx * spike_mult:
            is_volatile = True
            volatile_reason = (
                f"ADX={adx:.1f} ≥ {volatile_thr} và spike {adx/mean_adx:.1f}× "
                f"mean({mean_adx:.1f}) — hỗn loạn thực sự"
            )
        else:
            # ADX cao nhưng không phải spike — đây là trending mạnh bình thường
            volatile_reason = (
                f"ADX={adx:.1f} ≥ {volatile_thr} nhưng không spike "
                f"(mean={mean_adx:.1f}) — vẫn là trending mạnh"
            )

    if is_volatile:
        return RegimeResult(
            regime=REGIME_VOLATILE, adx=adx, di_plus=di_plus, di_minus=di_minus,
            trend_dir=trend_dir, allowed=False,
            reason=volatile_reason,
        )
    elif adx >= trending_thr:
        return RegimeResult(
            regime=REGIME_TRENDING, adx=adx, di_plus=di_plus, di_minus=di_minus,
            trend_dir=trend_dir, allowed=True,
            reason=f"ADX={adx:.1f} ≥ {trending_thr} — trending ({trend_dir})",
        )
    else:
        return RegimeResult(
            regime=REGIME_RANGING, adx=adx, di_plus=di_plus, di_minus=di_minus,
            trend_dir="neutral", allowed=True,
            reason=f"ADX={adx:.1f} < {trending_thr} — ranging/sideways",
        )


def is_pattern_suitable(pattern: str, regime: RegimeResult) -> tuple:
    """
    Kiểm tra pattern có phù hợp với chế độ thị trường không.
    Trả về (suitable: bool, reason: str).

    Logic:
      - VOLATILE → không cho phép BẤT KỲ pattern nào
      - TRENDING → chỉ cho TRENDING_PATTERNS + UNIVERSAL
      - RANGING  → chỉ cho RANGING_PATTERNS + UNIVERSAL
      - UNKNOWN  → cho qua hết (failsafe)
    """
    if regime.regime == REGIME_VOLATILE:
        return False, f"Thị trường hỗn loạn (ADX={regime.adx:.1f}) — bỏ qua tất cả pattern"

    if regime.regime == REGIME_UNKNOWN:
        return True, "Regime không xác định — cho qua (failsafe)"

    if pattern in UNIVERSAL_PATTERNS:
        return True, f"Universal pattern — OK trong mọi chế độ"

    if regime.regime == REGIME_TRENDING:
        if pattern in TRENDING_PATTERNS:
            return True, f"Pattern phù hợp trending (ADX={regime.adx:.1f})"
        elif pattern in RANGING_PATTERNS:
            return False, (
                f"Pattern '{pattern}' là mean-reversion — không phù hợp trending "
                f"(ADX={regime.adx:.1f}), dễ bị trend cuốn"
            )
        else:
            return True, f"Pattern chưa phân loại — cho qua trending"

    if regime.regime == REGIME_RANGING:
        if pattern in RANGING_PATTERNS:
            return True, f"Pattern phù hợp ranging (ADX={regime.adx:.1f})"
        elif pattern in TRENDING_PATTERNS:
            # Cho phép engulfing + BOS/CHoCH ngay cả trong ranging nếu ADX gần ngưỡng (18-20)
            adx_near_threshold = regime.adx >= 16
            if "engulfing" in pattern and adx_near_threshold:
                return True, f"Engulfing tại zone — OK dù ranging nhẹ (ADX={regime.adx:.1f})"
            return False, (
                f"Pattern '{pattern}' cần xu hướng — không phù hợp ranging "
                f"(ADX={regime.adx:.1f}), tín hiệu giả nhiều"
            )
        else:
            return True, f"Pattern chưa phân loại — cho qua ranging"

    return True, "OK"