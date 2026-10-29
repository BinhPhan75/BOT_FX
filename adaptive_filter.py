"""
adaptive_filter.py  v3 — Score-based, Regime+Session aware

Score 0-100:
  35pt  pattern WR tong hop
  35pt  regime-specific WR (quan trong nhat)
  20pt  session WR
  10pt  hour (bad hour check)

Chi cho lenh qua khi score >= ADAPTIVE_SCORE_THRESHOLD (mac dinh 55).
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger("adaptive_filter")

WEIGHTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signal_weights.json")
VN_TZ        = timezone(timedelta(hours=7))

_cache      = None
_cache_mtime = 0.0


def _load():
    global _cache, _cache_mtime
    if not os.path.exists(WEIGHTS_PATH):
        return None
    mtime = os.path.getmtime(WEIGHTS_PATH)
    if _cache and mtime == _cache_mtime:
        return _cache
    try:
        with open(WEIGHTS_PATH, encoding="utf-8") as f:
            _cache = json.load(f)
        _cache_mtime = mtime
        logger.info("Tai signal_weights.json v%s (%s)",
                    _cache.get("version","?"), _cache.get("generated_at","?")[:19])
    except Exception as e:
        logger.error("Loi doc signal_weights.json: %s", e)
        return None
    return _cache


def _session_from_utc(h: int) -> str:
    if 0  <= h < 7:  return "asia"
    if 7  <= h < 12: return "london"
    if 12 <= h < 17: return "london_ny"
    if 17 <= h < 21: return "ny"
    return "off"


BULLISH = {
    "breakout_resistance","double_bottom","bullish_engulfing",
    "hammer","ascending_triangle","bos_bullish","choch_bullish",
}
BEARISH = {
    "breakout_support","double_top","bearish_engulfing",
    "shooting_star","descending_triangle","bos_bearish","choch_bearish",
}


class FilterResult:
    def __init__(self, passed: bool, score: int = 100, reason: str = ""):
        self.passed = passed
        self.score  = score
        self.reason = reason

    def __bool__(self): return self.passed
    def __repr__(self):
        return f"FilterResult({'OK' if self.passed else 'BLOCK'} score={self.score} {self.reason})"


def should_trade(signal, regime=None) -> FilterResult:
    w = _load()
    if w is None:
        return FilterResult(True, 100, "no weights — failsafe")

    pattern   = signal.pattern
    symbol    = signal.symbol
    direction = "BUY" if pattern in BULLISH else "SELL"
    base_key  = f"{pattern}|{direction}"

    now_vn  = datetime.now(VN_TZ)
    now_utc = datetime.now(timezone.utc)
    hour_vn = now_vn.hour
    session = _session_from_utc(now_utc.hour)

    # Hard block: symbol tat
    sym_enabled = w.get("symbol_enabled", {})
    if symbol in sym_enabled and not sym_enabled[symbol]:
        return FilterResult(False, 0, f"Symbol {symbol} tat")

    score = 0
    notes = []

    # ── Component 1: Pattern WR tong hop (35pt) ───────────────────────────────
    pat_scores = w.get("pattern_scores", {})
    if base_key in pat_scores:
        ps = pat_scores[base_key]
        if not ps.get("enabled", True):
            return FilterResult(False, 0,
                f"Pattern {base_key} tat tong hop (WR={ps.get('win_rate',0)}%)")
        wr  = ps["win_rate"]
        pts = min(35, max(0, int((wr - 33) * 35 / 17)))  # 33%=0pt, 50%=35pt
        score += pts
        notes.append(f"pat={wr}%->+{pts}")
    else:
        score += 15
        notes.append("pat=nodata->+15")

    # ── Component 2: Regime WR (35pt) ────────────────────────────────────────
    cur_regime = "unknown"
    if regime is not None:
        cur_regime = getattr(regime, "regime", "unknown")

    rps = w.get("regime_pattern_scores", {})
    reg_key = f"{base_key}|{cur_regime}"

    if cur_regime not in ("unknown", "volatile") and reg_key in rps:
        rs  = rps[reg_key]
        rwr = rs["win_rate"]
        if not rs.get("enabled", True) and rs.get("total", 0) >= 15:
            # Hard block neu du mau va WR thap trong regime nay
            return FilterResult(False, score,
                f"Regime block: {reg_key} WR={rwr}%")
        pts = min(35, max(0, int((rwr - 33) * 35 / 17)))
        score += pts
        notes.append(f"regime_{cur_regime}={rwr}%->+{pts}")
    elif cur_regime == "unknown":
        score += 18
        notes.append("regime=unknown->+18")
    else:
        score += 20
        notes.append(f"regime={cur_regime}_nodata->+20")

    # ── Component 3: Session WR (20pt) ───────────────────────────────────────
    sps = w.get("session_pattern_scores", {})
    ses_key = f"{base_key}|{session}"
    if ses_key in sps:
        ss  = sps[ses_key]
        swr = ss["win_rate"]
        if not ss.get("enabled", True) and ss.get("total", 0) >= 15:
            score -= 10
            notes.append(f"session_{session}={swr}%->-10")
        else:
            pts = min(20, max(0, int((swr - 33) * 20 / 17)))
            score += pts
            notes.append(f"session_{session}={swr}%->+{pts}")
    else:
        score += 10
        notes.append(f"session={session}_nodata->+10")

    # ── Component 4: Bad hour (10pt) ─────────────────────────────────────────
    bad_hours = w.get("bad_hours", [])
    if hour_vn in bad_hours:
        hs = w.get("hour_scores", {}).get(str(hour_vn), {})
        score -= 15
        notes.append(f"bad_hour={hour_vn}h({hs.get('win_rate',0)}%)->-15")
    else:
        score += 10
        notes.append(f"hour={hour_vn}h_ok->+10")

    score  = max(0, min(100, score))
    import config as _cfg
    thr    = getattr(_cfg, "ADAPTIVE_SCORE_THRESHOLD", 55)
    passed = score >= thr

    reason = f"score={score}/100 [{', '.join(notes)}] {'PASS' if passed else f'BLOCK(thr={thr})'}"
    if not passed:
        logger.info("Adaptive filter BLOCK %s %s — %s", symbol, base_key, reason)
    else:
        logger.debug("Adaptive filter PASS %s %s — %s", symbol, base_key, reason)

    return FilterResult(passed, score, reason)


def get_lot_multiplier(signal, regime=None) -> float:
    """Nhan lot theo score: score>=80->1.5x, 70->1.2x, 60->1.0x, <60->0.8x."""
    r = should_trade(signal, regime=regime)
    if not r.passed: return 0.0
    if r.score >= 80: return 1.5
    if r.score >= 70: return 1.2
    if r.score >= 60: return 1.0
    return 0.8
