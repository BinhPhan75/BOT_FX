# ai_v6/live/scanner_v6.py
"""
Scanner 7 nhom pattern cua ai_v6 (cung chu ky / cung khoa phu tro voi ai_v5/live/live_pattern_scanner.py).

TAT CA cac mo hinh deu THAM SO HOA, moi mo hinh co bo tham so rieng:
    - 24 mo hinh nen        : candle_params_v6.py     -> ai_v6/candle_params.json      (do bang pattern_tuner_v6.py)
    - 46 mo hinh cau truc   : structure_params_v6.py  -> ai_v6/structure_params.json   (do bang structure_tuner_v6.py)
      (Hinh hoc 14, Harmonic 8, Phan ky 8, ICT 6, VSA 6, Continuation 4)
Khong co file cau hinh -> dung DEFAULTS (da kiem toan logic). MAC DINH KHONG TAT mo hinh nao.

Doi dong import o mtf_scanner.py, build_train_v6_scalping.py, backtest_v6_scalping.py de live / dataset / backtest dung CHUNG.
"""
import logging

from ai_v6.live import structure_params_v6 as SP
from ai_v6.live.candle_params_v6 import detect_last as detect_candle_params

logger = logging.getLogger("ai_v6_scanner")

MIN_CANDLES_REQUIRED = 220
DISABLED_SOURCES = set()
DISABLED_PATTERNS = set()


def scan_all_patterns_live(candles: list, symbol: str) -> list:
    """candles: dict OHLCV tang dan, candles[-1] la nen DA DONG gan nhat. Tra ve [(source_type, match), ...]."""
    if len(candles) < MIN_CANDLES_REQUIRED:
        return []
    PP = SP.load_params()
    ctx = SP.build_ctx(candles, SP.needed_factors(PP))
    if ctx is None:
        return []
    matches = SP.detect_structure(ctx, PP)
    cm = detect_candle_params(ctx["recent12"], ctx["atr"])
    if cm is not None:
        matches.append(("CANDLESTICK_PATTERN", cm))
    matches = [(st, m) for st, m in matches if st not in DISABLED_SOURCES and m["pattern"] not in DISABLED_PATTERNS]

    atr, px, pc = ctx["atr"], ctx["px"], ctx["pc"]
    momentum = (px - pc) / atr if atr else 0.0
    rsi = ctx["rsi_now"] if ctx["rsi_now"] is not None else 50.0
    ctime = candles[ctx["i"]].get("time", 0)
    for _st, m in matches:
        m["_atr"], m["_momentum_ratio"], m["_candle_time"], m["_rsi_14"], m["_entry_price"] = atr, momentum, ctime, rsi, px
    return matches
