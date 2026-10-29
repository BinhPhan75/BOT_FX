"""
smc_indicator.py
Ban dich Python cua indicator TradingView "XuTho v4" (Pine v6):

  1. SuperTrend + K-Means volatility clustering (adaptive ATR)
  2. EMA nhanh/cham (mac dinh 9/21)
  3. Market Structure: Internal + Swing BOS / CHoCH (phien ban rut gon,
     dung fixed-lookback fractal pivot thay cho state-machine "leg()" cua
     Pine — ve mat khai niem tuong duong nhung de kiem tra/backtest hon)
  4. Order Blocks (nen doi dien ngay truoc diem BOS/CHoCH)
  5. Fair Value Gaps (khoang trong 3 nen)

TOAN BO tham so doc dong qua param_loader.get_all(symbol) — xem danh sach
key moi trong param_loader.py (nhom "SMC INDICATOR").

Khong phu thuoc vao analysis.py / trader.py de co the unit-test doc lap.
Dinh dang candle: dict co it nhat cac key open/high/low/close, khuyen
khich co them 'time' (unix ts) va 'volume'.
"""

import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ─── ATR (Wilder) ──────────────────────────────────────────────────────────

def calc_atr_series(candles: List[Dict], period: int) -> List[Optional[float]]:
    """
    Tra ve list cung do dai candles. atr[i] = None cho toi khi du du lieu.
    Dung Wilder smoothing (seed = MEAN, giong market_regime.calc_adx).
    """
    n = len(candles)
    atr: List[Optional[float]] = [None] * n
    if n <= period:
        return atr

    trs = [None] * n
    for i in range(1, n):
        h, l = candles[i]["high"], candles[i]["low"]
        pc = candles[i - 1]["close"]
        trs[i] = max(h - l, abs(h - pc), abs(l - pc))

    seed = sum(trs[1:period + 1]) / period
    atr[period] = seed
    prev = seed
    for i in range(period + 1, n):
        prev = (prev * (period - 1) + trs[i]) / period
        atr[i] = prev
    return atr


# ─── EMA ─────────────────────────────────────────────────────────────────

def calc_ema_series(candles: List[Dict], period: int) -> List[Optional[float]]:
    closes = [c["close"] for c in candles]
    n = len(closes)
    ema: List[Optional[float]] = [None] * n
    if n < period:
        return ema
    k = 2 / (period + 1)
    seed = sum(closes[:period]) / period
    ema[period - 1] = seed
    prev = seed
    for i in range(period, n):
        prev = closes[i] * k + prev * (1 - k)
        ema[i] = prev
    return ema


# ─── K-Means volatility clustering (3 cluster: high/medium/low) ──────────

def kmeans_volatility(
    atr_window: List[Optional[float]],
    highvol_pct: float = 0.75,
    midvol_pct: float = 0.5,
    lowvol_pct: float = 0.25,
    max_iter: int = 25,
) -> Optional[Tuple[float, float, float]]:
    """
    Tuong duong logic K-Means trong Pine (init centroid theo percentile
    cua range ATR, lap toi khi hoi tu). Tra ve (c_high, c_mid, c_low).
    """
    vals = [v for v in atr_window if v is not None]
    if len(vals) < 10:
        return None

    upper, lower = max(vals), min(vals)
    if upper == lower:
        return upper, upper, upper

    c_high = lower + (upper - lower) * highvol_pct
    c_mid = lower + (upper - lower) * midvol_pct
    c_low = lower + (upper - lower) * lowvol_pct

    for _ in range(max_iter):
        hv, mv, lv = [], [], []
        for v in vals:
            d = (abs(v - c_high), abs(v - c_mid), abs(v - c_low))
            idx = d.index(min(d))
            (hv if idx == 0 else mv if idx == 1 else lv).append(v)
        n_high = statistics.mean(hv) if hv else c_high
        n_mid = statistics.mean(mv) if mv else c_mid
        n_low = statistics.mean(lv) if lv else c_low
        converged = (
            abs(n_high - c_high) < 1e-9
            and abs(n_mid - c_mid) < 1e-9
            and abs(n_low - c_low) < 1e-9
        )
        c_high, c_mid, c_low = n_high, n_mid, n_low
        if converged:
            break

    return c_high, c_mid, c_low


def assigned_volatility(current_atr: float, centroids: Tuple[float, float, float]) -> float:
    """Chon centroid gan nhat voi ATR hien tai — day la 'atr' dua vao SuperTrend."""
    c_high, c_mid, c_low = centroids
    dists = (abs(current_atr - c_high), abs(current_atr - c_mid), abs(current_atr - c_low))
    return centroids[dists.index(min(dists))]


# ─── SuperTrend (dung atr_value co dinh = centroid da gan cluster) ───────

def supertrend_direction(
    candles: List[Dict],
    factor: float,
    atr_value: float,
    lookback: int = 60,
) -> List[Tuple[float, int]]:
    """
    Tra ve list (supertrend_value, direction) cho `lookback` nen cuoi.
    direction: -1 = bullish (dung lowerBand, gia > ST), 1 = bearish (dung
    upperBand, gia < ST) — giu dung quy uoc dau cua Pine goc.
    atr_value duoc coi la HANG SO trong khoang lookback (xap xi hop ly vi
    cum K-Means chi doi cham qua tung nen).
    """
    n = len(candles)
    start = max(1, n - lookback)
    prev_upper = prev_lower = None
    st_val = None
    direction = 1
    results: List[Tuple[float, int]] = []

    for i in range(start, n):
        hl2 = (candles[i]["high"] + candles[i]["low"]) / 2
        basic_upper = hl2 + factor * atr_value
        basic_lower = hl2 - factor * atr_value

        if prev_lower is None:
            lower_band, upper_band = basic_lower, basic_upper
        else:
            prev_close = candles[i - 1]["close"]
            lower_band = basic_lower if (basic_lower > prev_lower or prev_close < prev_lower) else prev_lower
            upper_band = basic_upper if (basic_upper < prev_upper or prev_close > prev_upper) else prev_upper

        close = candles[i]["close"]
        if st_val is None:
            direction = 1
        elif st_val == prev_upper:
            direction = -1 if close > upper_band else 1
        else:
            direction = 1 if close < lower_band else -1

        st_val = lower_band if direction == -1 else upper_band
        prev_upper, prev_lower = upper_band, lower_band
        results.append((st_val, direction))

    return results


# ─── Market structure: pivot fractal + BOS/CHoCH ─────────────────────────

def find_swing_pivots(candles: List[Dict], lookback: int) -> List[Tuple[int, float, str]]:
    """
    Pivot fractal chuan (khong nhin tuong lai qua lookback nen sau khi
    duoc XAC NHAN — gia tri duoc coi la 'biet' tu bar (index+lookback)).
    Tra ve [(index, price, 'high'|'low'), ...] theo thu tu index tang dan.
    """
    n = len(candles)
    pivots = []
    for i in range(lookback, n - lookback):
        window = candles[i - lookback: i + lookback + 1]
        highs = [c["high"] for c in window]
        lows = [c["low"] for c in window]
        if candles[i]["high"] == max(highs):
            pivots.append((i, candles[i]["high"], "high"))
        if candles[i]["low"] == min(lows):
            pivots.append((i, candles[i]["low"], "low"))
    return pivots


def detect_structure_breaks(candles: List[Dict], lookback: int) -> Tuple[List[Dict], int]:
    """
    Mo phong BOS/CHoCH tuong duong displayStructure() trong Pine, dung
    pivot fractal co do tre xac nhan = lookback nen (giong Pine, khong
    repaint tin hieu qua khu).

    Tra ve (events, current_trend)
      events: [{"index","type":"BOS"/"CHOCH","bias":"bullish"/"bearish","level":price}, ...]
      current_trend: 1 bullish / -1 bearish / 0 chua xac dinh
    """
    n = len(candles)
    pivots = find_swing_pivots(candles, lookback)

    by_confirm_idx: Dict[int, List[Tuple[float, str]]] = {}
    for idx, price, kind in pivots:
        by_confirm_idx.setdefault(idx + lookback, []).append((price, kind))

    trend = 0
    last_high = last_low = None
    high_crossed = low_crossed = False
    events: List[Dict] = []

    for i in range(lookback, n):
        for price, kind in by_confirm_idx.get(i, []):
            if kind == "high":
                last_high, high_crossed = price, False
            else:
                last_low, low_crossed = price, False

        close = candles[i]["close"]

        if last_high is not None and not high_crossed and close > last_high:
            tag = "CHOCH" if trend == -1 else "BOS"
            events.append({"index": i, "type": tag, "bias": "bullish", "level": last_high})
            high_crossed = True
            trend = 1

        if last_low is not None and not low_crossed and close < last_low:
            tag = "CHOCH" if trend == 1 else "BOS"
            events.append({"index": i, "type": tag, "bias": "bearish", "level": last_low})
            low_crossed = True
            trend = -1

    return events, trend


# ─── Order Blocks ──────────────────────────────────────────────────────────

def find_order_block(candles: List[Dict], event_index: int, bias: str, search_range: int = 15) -> Optional[Dict]:
    """
    OB = nen doi chieu GAN NHAT truoc diem BOS/CHoCH (giong storeOrdeBlock
    trong Pine — nen bearish cuoi cung truoc breakout tang, hoac nguoc lai).
    """
    start = max(0, event_index - search_range)
    for j in range(event_index - 1, start - 1, -1):
        c = candles[j]
        bullish_candle = c["close"] > c["open"]
        if bias == "bullish" and not bullish_candle:
            return {"top": c["high"], "bottom": c["low"], "index": j, "bias": "bullish", "kind": "OB"}
        if bias == "bearish" and bullish_candle:
            return {"top": c["high"], "bottom": c["low"], "index": j, "bias": "bearish", "kind": "OB"}
    return None


# ─── Fair Value Gaps ───────────────────────────────────────────────────────

def find_fvgs(candles: List[Dict], lookback_bars: int = 100) -> List[Dict]:
    """
    FVG 3-nen chuan: gap giua high/low cua nen i-2 va nen i.
    Loai bo FVG da bi 'mitigate' (gia da quay lai lap day khoang trong).
    """
    n = len(candles)
    start = max(2, n - lookback_bars)
    fvgs: List[Dict] = []
    for i in range(start, n):
        c0, c2 = candles[i - 2], candles[i]
        if c2["low"] > c0["high"]:
            fvgs.append({"top": c2["low"], "bottom": c0["high"], "index": i, "bias": "bullish", "kind": "FVG"})
        elif c2["high"] < c0["low"]:
            fvgs.append({"top": c0["low"], "bottom": c2["high"], "index": i, "bias": "bearish", "kind": "FVG"})

    # Loc mitigated: sau khi hinh thanh, neu gia sau do da chay xuyen qua vung → bo
    active = []
    for gap in fvgs:
        mitigated = False
        for k in range(gap["index"] + 1, n):
            low_k, high_k = candles[k]["low"], candles[k]["high"]
            if gap["bias"] == "bullish" and low_k < gap["bottom"]:
                mitigated = True
                break
            if gap["bias"] == "bearish" and high_k > gap["top"]:
                mitigated = True
                break
        if not mitigated:
            active.append(gap)
    return active


# ─── Tin hieu doc lap #1: SuperTrend K-Means FLIP ────────────────────────

def supertrend_flip_signal(
    candles: List[Dict], factor: float, atr_value: float, lookback: int = 60
) -> Optional[str]:
    """
    Tra ve 'bullish'/'bearish' neu SuperTrend VUA DOI CHIEU o nen CUOI CUNG
    (giong plotshape crossunder/crossover(dir,0) trong Pine — trigger DOC LAP,
    khong can xac nhan tu nhom khac).
    """
    results = supertrend_direction(candles, factor, atr_value, lookback)
    if len(results) < 2:
        return None
    prev_dir = results[-2][1]
    cur_dir = results[-1][1]
    if prev_dir == cur_dir:
        return None
    return "bullish" if cur_dir == -1 else "bearish"


# ─── Tin hieu doc lap #2: EMA 9/21 cross ──────────────────────────────────

def ema_cross_signal(candles: List[Dict], fast_len: int, slow_len: int) -> Optional[str]:
    """Tra ve 'bullish'/'bearish' neu EMA nhanh VUA cat EMA cham o nen cuoi."""
    fast = calc_ema_series(candles, fast_len)
    slow = calc_ema_series(candles, slow_len)
    if len(fast) < 2 or fast[-1] is None or fast[-2] is None or slow[-1] is None or slow[-2] is None:
        return None
    if fast[-2] <= slow[-2] and fast[-1] > slow[-1]:
        return "bullish"
    if fast[-2] >= slow[-2] and fast[-1] < slow[-1]:
        return "bearish"
    return None


# ─── Tin hieu doc lap #3: Price Action / Dow Theory (co xac nhan volume) ──

def price_action_signal(
    candles: List[Dict], length: int = 14, vol_multiplier: float = 1.5
) -> Optional[str]:
    """
    Dich tu Pine goc:
      highs1 = highest(high, length); lows1 = lowest(low, length)
      uptrend   = high > highs1[1] and low > lows1[1]
      downtrend = high < highs1[1] and low < lows1[1]
      volume_confirmed_* = volume > sma(volume, length) * vol_multiplier and (up/down)trend
    Tra ve 'bullish'/'bearish' cho nen CUOI CUNG, hoac None.
    """
    n = len(candles)
    if n < length + 2:
        return None

    last = candles[-1]
    window_prev = candles[n - 1 - length: n - 1]  # length nen NGAY TRUOC nen cuoi (shift 1)
    if len(window_prev) < length:
        return None
    highs1_prev = max(c["high"] for c in window_prev)
    lows1_prev = min(c["low"] for c in window_prev)

    uptrend = last["high"] > highs1_prev and last["low"] > lows1_prev
    downtrend = last["high"] < highs1_prev and last["low"] < lows1_prev
    if not uptrend and not downtrend:
        return None

    vol_window = candles[n - length: n]
    volumes = [c.get("volume", 0) for c in vol_window]
    vol_avg = sum(volumes) / len(volumes) if volumes else 0
    vol_ok = last.get("volume", 0) > vol_avg * vol_multiplier
    if not vol_ok:
        return None

    return "bullish" if uptrend else "bearish"


# ─── Proximity filter (dung cho ca OB va FVG) ─────────────────────────────

def is_near_zone(price: float, zones: List[Dict], bias: str, proximity_pct: float) -> bool:
    """
    True neu `price` nam TRONG mot zone cung bias, hoac cach mid-point cua
    zone do khong qua proximity_pct % gia.
    """
    for z in zones:
        if z.get("bias") != bias:
            continue
        top, bottom = z["top"], z["bottom"]
        if bottom <= price <= top:
            return True
        mid = (top + bottom) / 2
        if mid <= 0:
            continue
        if abs(price - mid) / mid * 100 <= proximity_pct:
            return True
    return False


def zone_touched(candle: Dict, zones: List[Dict], bias: str, proximity_pct: float) -> bool:
    """
    True neu NEN (khong chi gia dong cua) thuc su cham vao mot zone cung
    bias — dung range [low, high] cua nen de bat wick cham vao zone, day
    du hon is_near_zone() (chi xet 1 diem gia). Dung cho logic RETEST:
    cho gia hoi ve vung OB/FVG sau khi BOS/CHoCH da xay ra truoc do.
    """
    for z in zones:
        if z.get("bias") != bias:
            continue
        top, bottom = z["top"], z["bottom"]
        if candle["low"] <= top and candle["high"] >= bottom:
            return True
        mid = (top + bottom) / 2
        if mid <= 0:
            continue
        if abs(candle["close"] - mid) / mid * 100 <= proximity_pct:
            return True
    return False
