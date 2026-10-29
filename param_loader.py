"""
param_loader.py  v3 — Full dynamic params cho toan bo he thong

Tham so hoc may (tat ca deu dong, khong con hardcode):

  Nhom 1 - ATR / SL:
    atr_period          int     14     ADX period
    atr_multiplier      float   1.8    He so ATR tinh SL
    max_sl_usd          float   15.0   Cap SL tinh bang USD (XAUUSD)

  Nhom 2 - Pivot / Zone:
    pivot_lookback      int     7      So nen hai ben de xac dinh pivot
    zone_merge_pct      float   0.08   % gop zone gan nhau
    min_touches         int     2      So lan cham zone toi thieu

  Nhom 3 - Candlestick pattern:
    body_strength_min   float   0.35   Than nen / range toi thieu (filter doji)
    pin_bar_body_pct    float   0.35   Than nen / range toi da cho pin bar
    pin_bar_wick_ratio  float   2.0    Wick / than toi thieu cho hammer/shooting star
    engulf_strength     float   1.5    Than nen lon hon trung binh bao nhieu lan = "strong"

  Nhom 4 - Breakout:
    breakout_thr_pct    float   0.03   % vuot zone moi tinh la breakout
    volume_spike_mult   float   1.5    Volume / trung binh toi thieu
    volume_avg_period   int     20     So nen tinh volume trung binh

  Nhom 5 - Turtle Soup (Double Top/Bottom):
    soup_max_exceed     float   0.005  Dinh 2 cao hon dinh 1 toi da bao nhieu %
    soup_body_min       float   0.35   Than nen xac nhan
    soup_close_pct_sell float   0.40   Dong cua phai o 40% duoi range (SELL)
    soup_close_pct_buy  float   0.60   Dong cua phai o 60% tren range (BUY)

  Nhom 6 - SMC:
    smc_ob_search_range int     15     Tim Order Block trong bao nhieu nen truoc BOS
    smc_require_fvg     bool    False  Bat buoc FVG de xac nhan OB

  Nhom 7 - Bot behavior:
    dedupe_minutes      int     60     Khong lap lai cung pattern trong bao nhieu phut
    rr_ratio            float   2.0    Risk:Reward mac dinh
    adaptive_score_thr  int     55     Diem toi thieu de adaptive filter cho qua
"""

import json
import logging
import os
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger("param_loader")

_BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PARAMS_PATH = os.path.join(_BASE_DIR, "optimized_params.json")

_params: Dict[str, Dict[str, Any]] = {}
_mtime:  float = 0.0

# ─── Thread-local override (dung cho backtest_engine chay song song) ───────
# QUAN TRONG: auto_tuner.py chay WFO trong 1 background thread CUNG PROCESS
# voi watcher.py (thread chinh dang giao dich live). Neu backtest ghi de
# truc tiep vao _params (bien toan cuc), thread live se co the doc NHAM
# tham so cua combo dang duoc test (race condition), khien bot "chay sai
# thong so" ngay trong luc auto-tuner dang chay nen.
#
# Giai phap: dung threading.local() — moi thread co "the gioi" tham so
# rieng. backtest_engine.py set override CHI cho thread cua no; thread
# live (watcher.py) khong bao gio thay override nay, luon doc dung
# _params/defaults that.
_thread_local = threading.local()


def set_thread_override(symbol: str, params: Dict[str, Any]) -> None:
    """Chi anh huong toi thread dang goi ham nay (dung trong backtest)."""
    if not hasattr(_thread_local, "overrides"):
        _thread_local.overrides = {}
    _thread_local.overrides[symbol] = dict(params)


def clear_thread_override(symbol: str) -> None:
    if hasattr(_thread_local, "overrides"):
        _thread_local.overrides.pop(symbol, None)

# ─── DEFAULTS ────────────────────────────────────────────────────────────────
# Gia tri nay la last-resort. Uu tien: optimized_params.json > config.py > day

_HARDCODED_DEFAULTS: Dict[str, Any] = {
    # ATR / SL
    "atr_period":          14,
    "atr_multiplier":      1.8,
    "tp_atr_multiplier":   3.6,   # v8: TP tinh DOC LAP theo ATR, khong con la boi so cung cua SL
    "max_sl_atr_mult":     1.5,   # v9: gioi han SL-tu-entry toi da bao nhieu lan ATR buffer,
                                   # tranh zone_price/anchor keo SL qua xa so voi TP
    "fomo_guard_atr_mult": 0.5,   # v9.2: chan tin hieu neu gia da chay qua X lan ATR so voi
                                   # gia dong lenh CUNG CHIEU gan nhat (tranh duoi gia/FOMO)
    "max_sl_usd":          15.0,
    # Pivot / Zone
    "pivot_lookback":      7,
    "zone_merge_pct":      0.08,
    "min_touches":         2,
    # Candlestick
    "body_strength_min":   0.35,
    "pin_bar_body_pct":    0.35,
    "pin_bar_wick_ratio":  2.0,
    "engulf_strength":     1.5,
    # Breakout
    "breakout_thr_pct":    0.03,
    "volume_spike_mult":   1.5,
    "volume_avg_period":   20,
    # Turtle Soup
    "soup_max_exceed":     0.005,
    "soup_body_min":       0.35,
    "soup_close_pct_sell": 0.40,
    "soup_close_pct_buy":  0.60,
    # SMC
    "smc_ob_search_range": 15,
    "smc_require_fvg":     False,
    # Bot behavior
    "dedupe_minutes":      60,
    "rr_ratio":            2.0,
    "adaptive_score_thr":  55,

    # ── SMC INDICATOR (v5 — thay the hoan toan pattern nen cu) ──────────
    # SuperTrend + K-Means
    "st_atr_len":              10,     # ATR period cho SuperTrend
    "st_factor":               3.0,    # He so nhan ATR (bien do band)
    "kmeans_training_period":  100,    # So nen ATR dua vao K-Means
    "kmeans_highvol":          0.75,   # Percentile khoi tao centroid cao
    "kmeans_midvol":           0.5,
    "kmeans_lowvol":           0.25,
    # EMA cross (dung lam bo loc xu huong, khong phai trigger)
    "ema_fast_len":            9,
    "ema_slow_len":            21,
    # Market structure BOS/CHoCH
    "internal_structure_len":  5,      # Fractal lookback — cang nho cang nhieu tin hieu
    "swing_structure_len":     50,     # (danh cho phan tich/so sanh, chua dung truc tiep trong entry)
    # Order Block / Fair Value Gap
    "fvg_lookback_bars":       100,    # So nen quet tim FVG con "song" (chua mitigate)
    "ob_fvg_proximity_pct":    0.3,    # % gia toi da de tinh la "gan" zone OB/FVG
    "ob_fvg_retest_max_bars":  20,     # (khong con dung lam gate bat buoc tu v7, giu lai cho tham khao)
    "trend_min_agree":         1,      # (khong con dung lam gate bat buoc tu v7, giu lai cho tham khao)
    # Price Action / Dow Theory (nhom tin hieu doc lap thu 5)
    "pa_length":               14,     # Length for Trend Detection (dung Pine goc)
    "pa_vol_multiplier":       1.5,    # Volume Multiplier for Trend Confirmation (dung Pine goc)
}


def _config_defaults() -> Dict[str, Any]:
    """
    Lay defaults tu config.py neu co, fallback ve _HARDCODED_DEFAULTS.
    Mapping ten bien config.py → ten param_loader.
    """
    defaults = dict(_HARDCODED_DEFAULTS)
    try:
        import config as _c
        mapping = {
            "ATR_PERIOD_DEFAULT":      "atr_period",
            "ATR_MULTIPLIER_DEFAULT":  "atr_multiplier",
            "PIVOT_LOOKBACK":          "pivot_lookback",
            "ZONE_MERGE_PERCENT":      "zone_merge_pct",
            "MIN_TOUCHES":             "min_touches",
            "BODY_STRENGTH_MIN":       "body_strength_min",
            "BREAKOUT_THRESHOLD_PERCENT": "breakout_thr_pct",
            "VOLUME_SPIKE_MULTIPLIER": "volume_spike_mult",
            "VOLUME_AVG_PERIOD":       "volume_avg_period",
            "SMC_ORDER_BLOCK_SEARCH_RANGE": "smc_ob_search_range",
            "DEDUPE_MINUTES":          "dedupe_minutes",
            "DEFAULT_RR_RATIO":        "rr_ratio",
            "ADAPTIVE_SCORE_THRESHOLD": "adaptive_score_thr",
        }
        for cfg_key, param_key in mapping.items():
            val = getattr(_c, cfg_key, None)
            if val is not None:
                # MAX_SL_USD co the la dict {symbol: val}
                if cfg_key == "MAX_SL_USD" and isinstance(val, dict):
                    pass  # xu ly per-symbol o cho khac
                else:
                    defaults[param_key] = val
    except ImportError:
        pass
    return defaults


def _load() -> None:
    """Doc optimized_params.json vao cache, tu dong reload khi file thay doi."""
    global _params, _mtime

    if not os.path.exists(PARAMS_PATH):
        _params = {}
        return

    try:
        mtime = os.path.getmtime(PARAMS_PATH)
        if _params and mtime == _mtime:
            return

        with open(PARAMS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "symbols" in data:
            raw = data["symbols"]
        else:
            raw = {k: v for k, v in data.items()
                   if isinstance(v, dict) and not k.startswith("_")}

        defaults = _config_defaults()
        validated: Dict[str, Dict] = {}

        for sym, p in raw.items():
            entry = dict(defaults)
            entry.update(p)
            # Type coercion
            int_keys   = {"atr_period","pivot_lookback","min_touches",
                          "volume_avg_period","smc_ob_search_range",
                          "dedupe_minutes","adaptive_score_thr",
                          "st_atr_len","kmeans_training_period",
                          "ema_fast_len","ema_slow_len",
                          "internal_structure_len","swing_structure_len",
                          "fvg_lookback_bars","ob_fvg_retest_max_bars",
                          "trend_min_agree","pa_length"}
            float_keys = {"atr_multiplier","tp_atr_multiplier","max_sl_atr_mult",
                          "fomo_guard_atr_mult","max_sl_usd","zone_merge_pct",
                          "body_strength_min","pin_bar_body_pct","pin_bar_wick_ratio",
                          "engulf_strength","breakout_thr_pct","volume_spike_mult",
                          "soup_max_exceed","soup_body_min","soup_close_pct_sell",
                          "soup_close_pct_buy","rr_ratio",
                          "st_factor","kmeans_highvol","kmeans_midvol","kmeans_lowvol",
                          "ob_fvg_proximity_pct","pa_vol_multiplier"}
            bool_keys  = {"smc_require_fvg"}
            for k in int_keys:
                if k in entry:
                    entry[k] = int(float(entry[k]))
            for k in float_keys:
                if k in entry:
                    entry[k] = round(float(entry[k]), 4)
            for k in bool_keys:
                if k in entry:
                    entry[k] = bool(entry[k])
            validated[sym] = entry

        _params = validated
        _mtime  = mtime

        logger.info("param_loader: Tai optimized_params.json — %d symbols", len(_params))
        for sym, p in _params.items():
            logger.info(
                "  %-8s ATR(%d)x%.2f TP_x%.2f struct=%d st_factor=%.2f "
                "ema_fast=%d pa_len=%d WR=%.1f%%",
                sym,
                p.get("atr_period",14), p.get("atr_multiplier",1.8),
                p.get("tp_atr_multiplier",3.6), p.get("internal_structure_len",5),
                p.get("st_factor",3.0), p.get("ema_fast_len",9),
                p.get("pa_length",14), p.get("win_rate",0),
            )

    except Exception as e:
        logger.error("param_loader: Loi doc %s: %s", PARAMS_PATH, e)
        _params = {}


# ─── Public API ───────────────────────────────────────────────────────────────

def get_param(symbol: str, key: str, fallback: Any = None) -> Any:
    """Lay 1 tham so. Thu tu uu tien: thread-override (backtest) > JSON > config > fallback."""
    overrides = getattr(_thread_local, "overrides", None)
    if overrides and symbol in overrides and key in overrides[symbol]:
        return overrides[symbol][key]

    _load()
    if symbol in _params and key in _params[symbol]:
        return _params[symbol][key]
    d = _config_defaults()
    if key in d:
        return d[key]
    return fallback


def get_all(symbol: str) -> Dict[str, Any]:
    """Lay toan bo tham so cua symbol. Merge defaults + optimized + thread-override."""
    _load()
    merged = _config_defaults()
    merged.update(_params.get(symbol, {}))

    overrides = getattr(_thread_local, "overrides", None)
    if overrides and symbol in overrides:
        merged.update(overrides[symbol])

    return merged


def reload() -> None:
    global _mtime
    _mtime = 0.0
    _load()
    logger.info("param_loader: Da reload.")


def apply() -> None:
    """Goi khi watcher khoi dong."""
    _load()
    if _params:
        logger.info("param_loader: Dung tham so tu optimized_params.json")
    else:
        logger.info("param_loader: Chua co optimized_params.json — dung defaults")
        logger.info("  Chay: py -3.11 bootstrap.py de tao lan dau")


def save(symbol_params: Dict[str, Dict[str, Any]]) -> None:
    """Ghi ket qua toi uu. Merge voi file cu, khong xoa symbol khac."""
    import datetime

    try:
        existing: Dict = {}
        if os.path.exists(PARAMS_PATH):
            try:
                with open(PARAMS_PATH, "r", encoding="utf-8") as f:
                    old = json.load(f)
                existing = {k: v for k, v in old.items()
                            if isinstance(v, dict) and not k.startswith("_")}
            except Exception:
                pass

        for sym, params in symbol_params.items():
            p = dict(params)
            existing[sym] = p

        out = {
            "_generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "_note": "Auto-generated by auto_tuner.py",
        }
        out.update(existing)

        with open(PARAMS_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)

        logger.info("param_loader: Ghi optimized_params.json OK (%d symbols)", len(existing))
        reload()

    except Exception as e:
        logger.error("param_loader: Loi ghi: %s", e)


def status() -> str:
    """Mo ta ngan gon trang thai (dung cho /params Telegram va log)."""
    _load()
    if not _params:
        d = _config_defaults()
        return (f"[defaults] ATR({d['atr_period']})x{d['atr_multiplier']} "
                f"TP_x{d['tp_atr_multiplier']}")
    lines = []
    for sym, p in _params.items():
        lines.append(
            f"{sym}: ATR({p.get('atr_period',14)})x{p.get('atr_multiplier',1.8):.2f} "
            f"TP_x{p.get('tp_atr_multiplier',3.6):.2f} "
            f"struct={p.get('internal_structure_len',5)} "
            f"st_factor={p.get('st_factor',3.0):.2f} "
            f"ema_fast={p.get('ema_fast_len',9)} "
            f"pa_len={p.get('pa_length',14)} "
            f"WR={p.get('win_rate',0):.1f}%"
        )
    return "\n".join(lines)