"""
analysis.py  v7 — 4 NHOM TIN HIEU DOC LAP (OR logic)

THAY DOI KIEN TRUC QUAN TRONG so voi v5/v6: truoc day dung 1 trigger chinh
(BOS/CHoCH) + bat buoc xac nhan cheo tu SuperTrend/EMA + bat buoc retest
OB/FVG — chuoi dieu kien AND nay qua chat, khien tin hieu qua hiem (gan
nhu khong co lenh nao qua duoc du indicator goc tren TradingView van bao
tin hieu deu dan).

v7: 4 nhom tin hieu cua indicator "XuTho v4" hoat dong HOAN TOAN DOC LAP,
dung y nhu 4 loai nhan rieng biet ma indicator ve tren TradingView — bat
ky nhom nao xuat hien la co the vao lenh NGAY, KHONG can nhom khac xac
nhan:

  1. smc_bullish_bos / smc_bearish_bos       — SMC: Break of Structure
  2. smc_bullish_choch / smc_bearish_choch   — SMC: Change of Character
  3. st_flip_bullish / st_flip_bearish       — SuperTrend K-Means doi chieu
  4. ema_cross_bullish / ema_cross_bearish   — EMA 9/21 giao cat
  5. price_action_bullish / price_action_bearish — Dow Theory + volume

Neu nhieu nhom cung xuat hien tren 1 nen, uu tien theo thu tu liet ke o
tren (SMC truoc, roi SuperTrend, EMA, Price Action) — chi tra ve 1 Signal
moi lan goi (gioi han cua kien truc pipeline hien tai, watcher.py/
backtest_engine.py chi xu ly 1 signal/candle/symbol).

Regime filter (market_regime.py) van giu nguyen vai tro RIENG: chan giao
dich khi thi truong qua volatile (an toan von, khong phai "xac nhan cheo"
giua cac mo hinh nen).

[20/07/2026] Da GO BO hoan toan hook goi sang ai_v5 (tung duoc them tam
thoi de thu nghiem Shadow Mode) — theo yeu cau tach bach tuyet doi giua
bot v4 va ai_v5. File nay gio la 100% thuan v4, khong con phu thuoc/goi
sang ai_v5 duoi bat ky hinh thuc nao. ai_v5 gio hoat dong hoan toan doc
lap qua ai_v5/live/live_trader.py (tu quet, tu quyet dinh, tu dat lenh
tren tai khoan demo rieng, khong doc du lieu gi tu v4).
"""

import logging
import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import param_loader
import smc_indicator

logger = logging.getLogger("analysis")


@dataclass
class Signal:
    symbol: str
    pattern: str
    price: float
    timeframe: str
    zone_price: float
    candles_context: List[Dict]
    time: int = 0
    volume_ratio: float = 1.0
    extra: dict = field(default_factory=dict)


def _volume_ratio(candles: List[Dict], period: int = 20) -> float:
    if len(candles) < period + 1:
        return 1.0
    cur = candles[-1].get("volume", 0)
    avg = statistics.mean(c.get("volume", 0) for c in candles[-period - 1:-1])
    return round(cur / avg, 2) if avg > 0 else 1.0


def _make_signal(candles, symbol, timeframe, pattern, zone_price, extra) -> Signal:
    last = candles[-1]
    return Signal(
        symbol=symbol,
        pattern=pattern,
        price=last["close"],
        timeframe=timeframe,
        zone_price=zone_price,
        candles_context=candles,
        time=int(last.get("time", 0)),
        volume_ratio=_volume_ratio(candles),
        extra=extra,
    )


def analyze(candles: List[Dict], symbol: str, timeframe: str, verbose: bool = False) -> Optional[Signal]:
    if len(candles) < 120:
        return None

    p = param_loader.get_all(symbol)
    last_idx = len(candles) - 1
    last_candle = candles[-1]

    # ── Nhom 1+2: SMC BOS/CHoCH — trigger TUC THI tren nen vua dong ────────
    struct_len = int(p.get("internal_structure_len", 5))
    events, trend = smc_indicator.detect_structure_breaks(candles, struct_len)
    if events and events[-1]["index"] == last_idx:
        ev = events[-1]
        pattern = f"smc_{ev['bias']}_{ev['type'].lower()}"
        if verbose:
            logger.info("%s: SMC %s (%s) tai gia %s", symbol, pattern, ev["type"], last_candle["close"])
        return _make_signal(
            candles, symbol, timeframe, pattern, ev["level"],
            extra={"structure_trend": trend, "break_type": ev["type"], "signal_group": "smc"},
        )

    # ── Nhom 3: SuperTrend K-Means doi chieu ───────────────────────────────
    atr_period = int(p.get("st_atr_len", 10))
    factor = float(p.get("st_factor", 3.0))
    kmeans_n = int(p.get("kmeans_training_period", 100))
    hv = float(p.get("kmeans_highvol", 0.75))
    mv = float(p.get("kmeans_midvol", 0.5))
    lv = float(p.get("kmeans_lowvol", 0.25))

    atr_series = smc_indicator.calc_atr_series(candles, atr_period)
    if atr_series[-1] is not None:
        window_atr = atr_series[-kmeans_n:] if len(atr_series) >= kmeans_n else atr_series
        centroids = smc_indicator.kmeans_volatility(window_atr, hv, mv, lv)
        if centroids:
            assigned_atr = smc_indicator.assigned_volatility(atr_series[-1], centroids)
            if assigned_atr > 0:
                st_sig = smc_indicator.supertrend_flip_signal(candles, factor, assigned_atr, lookback=60)
                if st_sig:
                    pattern = f"st_flip_{st_sig}"
                    zone_price = last_candle["low"] if st_sig == "bullish" else last_candle["high"]
                    if verbose:
                        logger.info("%s: SuperTrend doi chieu -> %s", symbol, st_sig)
                    return _make_signal(
                        candles, symbol, timeframe, pattern, zone_price,
                        extra={"signal_group": "supertrend"},
                    )

    # ── Nhom 4: EMA 9/21 cross ──────────────────────────────────────────────
    ema_fast_len = int(p.get("ema_fast_len", 9))
    ema_slow_len = int(p.get("ema_slow_len", 21))
    ema_sig = smc_indicator.ema_cross_signal(candles, ema_fast_len, ema_slow_len)
    if ema_sig:
        pattern = f"ema_cross_{ema_sig}"
        zone_price = last_candle["low"] if ema_sig == "bullish" else last_candle["high"]
        if verbose:
            logger.info("%s: EMA cross -> %s", symbol, ema_sig)
        return _make_signal(
            candles, symbol, timeframe, pattern, zone_price,
            extra={"signal_group": "ema_cross"},
        )

    # ── Nhom 5: Price Action / Dow Theory (volume-confirmed) ────────────────
    pa_length = int(p.get("pa_length", 14))
    pa_vol_mult = float(p.get("pa_vol_multiplier", 1.5))
    pa_sig = smc_indicator.price_action_signal(candles, pa_length, pa_vol_mult)
    if pa_sig:
        pattern = f"price_action_{pa_sig}"
        zone_price = last_candle["low"] if pa_sig == "bullish" else last_candle["high"]
        if verbose:
            logger.info("%s: Price Action -> %s", symbol, pa_sig)
        return _make_signal(
            candles, symbol, timeframe, pattern, zone_price,
            extra={"signal_group": "price_action"},
        )

    if verbose:
        logger.info("%s: khong co nhom tin hieu nao kich hoat tren nen nay.", symbol)
    return None
