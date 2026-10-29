"""
trend_filter.py
Xác định xu hướng tổng quát trên khung thời gian lớn hơn (ví dụ H1 khi đang
trade tín hiệu M15), dùng để LỌC tín hiệu — chỉ giữ lại tín hiệu cùng chiều
với xu hướng lớn, loại bỏ phần lớn tín hiệu nhiễu ngược xu hướng.

Phương pháp: EMA-based trend (EMA nhanh vs EMA chậm) + so sánh vị trí giá.
Đơn giản, dễ hiểu, không cần thư viện ngoài.
"""

from typing import List, Dict, Literal
from dataclasses import dataclass

import config

Trend = Literal["bullish", "bearish", "sideways"]


@dataclass
class TrendResult:
    trend: Trend
    fast_ema: float
    slow_ema: float
    timeframe: str


def _ema(values: List[float], period: int) -> List[float]:
    """Tính EMA (Exponential Moving Average) cho dãy giá."""
    if len(values) < period:
        return []

    k = 2 / (period + 1)
    ema_values = [sum(values[:period]) / period]  # SMA làm giá trị khởi đầu

    for price in values[period:]:
        ema_values.append(price * k + ema_values[-1] * (1 - k))

    return ema_values


def get_trend(candles: List[Dict], timeframe: str, fast_period: int = 20, slow_period: int = 50) -> TrendResult:
    """
    Xác định xu hướng dựa trên vị trí tương đối của EMA nhanh và EMA chậm.
    - EMA nhanh > EMA chậm rõ rệt -> bullish
    - EMA nhanh < EMA chậm rõ rệt -> bearish
    - 2 đường gần nhau / đan xen -> sideways (không đủ rõ ràng để tin tưởng)
    """
    closes = [c["close"] for c in candles]

    if len(closes) < slow_period + 1:
        # Không đủ dữ liệu để tính EMA chậm -> coi như sideways (an toàn, không lọc nhầm)
        last_price = closes[-1] if closes else 0
        return TrendResult(trend="sideways", fast_ema=last_price, slow_ema=last_price, timeframe=timeframe)

    fast_ema_series = _ema(closes, fast_period)
    slow_ema_series = _ema(closes, slow_period)

    fast_ema = fast_ema_series[-1]
    slow_ema = slow_ema_series[-1]

    avg_price = sum(closes[-slow_period:]) / slow_period
    diff_percent = abs(fast_ema - slow_ema) / avg_price * 100

    # Cần chênh lệch tối thiểu 0.05% mới coi là xu hướng rõ ràng, tránh nhiễu
    # khi 2 đường EMA đan xen sát nhau (thị trường đi ngang thực sự)
    min_diff_percent = 0.05

    if diff_percent < min_diff_percent:
        trend: Trend = "sideways"
    elif fast_ema > slow_ema:
        trend = "bullish"
    else:
        trend = "bearish"

    return TrendResult(trend=trend, fast_ema=round(fast_ema, 5), slow_ema=round(slow_ema, 5), timeframe=timeframe)


# Pattern nào cần xu hướng nào để được xác nhận (None = không áp dụng filter, ví dụ doji trung lập)
PATTERN_REQUIRED_TREND = {
    "breakout_resistance": "bullish",
    "breakout_support": "bearish",
    "double_top": "bearish",
    "double_bottom": "bullish",
    "bullish_engulfing": "bullish",
    "bearish_engulfing": "bearish",
    "hammer": "bullish",
    "shooting_star": "bearish",
    "ascending_triangle": "bullish",
    "descending_triangle": "bearish",
    "bos_bullish": "bullish",
    "bos_bearish": "bearish",
    # CHoCH cố ý KHÔNG đưa vào đây: bản chất CHoCH là tín hiệu báo xu hướng
    # H1 hiện tại (cũ) có thể sắp đổi chiều. Nếu lọc theo xu hướng H1 cũ,
    # CHoCH sẽ luôn bị loại bỏ ngay từ tín hiệu đầu tiên — mất đi đúng giá
    # trị cảnh báo sớm mà CHoCH mang lại. Để mặc định không lọc (None).

    # v9.6 — He thong MOI (bot_xutho4, OR-logic 5 nhom tin hieu doc lap).
    # TRUOC BAN SUA NAY: khong co pattern nao trong nhom duoi day duoc liet
    # ke, khien is_confirmed_by_trend() LUON tra ve True (bo loc H1 khong
    # co tac dung gi voi bot moi tu truoc toi gio). Bo sung day du:
    "smc_bullish_bos":     "bullish",
    "smc_bearish_bos":     "bearish",
    # smc_bullish_choch / smc_bearish_choch: co tinh giu KHONG loc, cung ly
    # do nhu bos_bullish/choch o tren — CHoCH la canh bao dao chieu som.
    "st_flip_bullish":     "bullish",
    "st_flip_bearish":     "bearish",
    "ema_cross_bullish":   "bullish",
    "ema_cross_bearish":   "bearish",
    "price_action_bullish": "bullish",
    "price_action_bearish": "bearish",
}


def is_confirmed_by_trend(pattern: str, htf_trend: Trend) -> bool:
    """
    Kiểm tra pattern phát hiện trên khung nhỏ (M15) có khớp xu hướng khung lớn (H1) không.
    Pattern không có trong PATTERN_REQUIRED_TREND (vd: doji, symmetrical_triangle)
    luôn được coi là "không bị lọc" vì bản chất chúng trung lập / chờ xác nhận hướng.
    """
    required = PATTERN_REQUIRED_TREND.get(pattern)
    if required is None:
        return True
    return required == htf_trend