# ai_v6/live/candle_params_v6.py
"""
12 MO HINH NEN NHAT THEO LY THUYET, MOI HANG SO TRONG DINH NGHIA LA 1 THAM SO (nhu thong so indicator).

MOT nguon su that duy nhat: cac ham mask() ben duoi duoc DUNG CHUNG boi
    - pattern_tuner_v6.py  (chay vector hoa tren lich su nhieu nam de do tham so)
    - bot live / backtest / dataset (detect_last() goi dung cac mask nay tren 12 nen cuoi)
=> bo tham so tuner chon se cho dung ket qua nhu khi chay live (khong co lech giua "backtest" va "bot").

ORIGINAL[ten] = bo tham so TAI TAO CHINH XAC ai_v5/pipeline/candlestick_patterns.py (da kiem tra tuong duong tren du lieu ngau nhien,
xem test_candle_params.py). DEFAULTS[ten] = ban v6 hien tai. File cau hinh candle_params.json (do tuner ghi) ghi de DEFAULTS tung mo hinh.

Quy uoc tham so chung:
    min_body_atr   than nen tin hieu >= min_body_atr * ATR
    ctx_min_atr    con song TRUOC mau hinh phai di NGUOC chieu tin hieu >= ctx_min_atr * ATR trong ctx_lookback nen
                   (-1 = TAT kiem tra boi canh; 0 = chi can co xu huong nguoc chieu - giong ai_v5 voi nen don)
    gap_tol_atr    dung sai thay cho "gap" (thi truong 24h gan nhu khong co gap that)
"""
import json
import os
import time

import numpy as np

REWARD_RISK_RATIO = 1.5
ORDER = ["MORNING_STAR", "EVENING_STAR", "THREE_WHITE_SOLDIERS", "THREE_BLACK_CROWS", "BULLISH_ENGULFING", "BEARISH_ENGULFING",
         "PIERCING_LINE", "DARK_CLOUD_COVER", "HAMMER", "SHOOTING_STAR", "DOJI_BULLISH_REVERSAL", "DOJI_BEARISH_REVERSAL"]
DIRECTION = {"MORNING_STAR": 1, "EVENING_STAR": -1, "THREE_WHITE_SOLDIERS": 1, "THREE_BLACK_CROWS": -1, "BULLISH_ENGULFING": 1,
             "BEARISH_ENGULFING": -1, "PIERCING_LINE": 1, "DARK_CLOUD_COVER": -1, "HAMMER": 1, "SHOOTING_STAR": -1,
             "DOJI_BULLISH_REVERSAL": 1, "DOJI_BEARISH_REVERSAL": -1}

_STAR_O = dict(c1_body_rng=0.5, star_max=0.4, pen=0.5, min_body_atr=0.0, ctx_min_atr=-1, ctx_lookback=5)
_STAR_D = dict(c1_body_rng=0.5, star_max=0.4, pen=0.5, min_body_atr=0.3, ctx_min_atr=0.5, ctx_lookback=5)
_SOL_O = dict(min_body_atr=0.0, close_pos=0.0, open_in_body=0)
_SOL_D = dict(min_body_atr=0.3, close_pos=0.0, open_in_body=0)
_ENG_O = dict(min_body_atr=0.0, prev_body_atr=0.0, gap_tol_atr=0.0, engulf_ratio=0.0, ctx_min_atr=-1, ctx_lookback=5)
_ENG_D = dict(min_body_atr=0.3, prev_body_atr=0.0, gap_tol_atr=0.1, engulf_ratio=0.0, ctx_min_atr=0.5, ctx_lookback=5)
_PIE_O = dict(min_body_atr=0.0, gap_tol_atr=0.0, pen=0.5, ctx_min_atr=-1, ctx_lookback=5)
_PIE_D = dict(min_body_atr=0.3, gap_tol_atr=0.1, pen=0.5, ctx_min_atr=0.5, ctx_lookback=5)
_HAM_O = dict(min_range_atr=0.0, wick_ratio=2.0, upper_max=0.3, ctx_min_atr=0.0, ctx_lookback=3)
_HAM_D = dict(min_range_atr=0.6, wick_ratio=2.0, upper_max=0.3, ctx_min_atr=0.5, ctx_lookback=5)
_DOJ_O = dict(min_range_atr=0.0, body_max=0.1, ctx_min_atr=0.0, ctx_lookback=3)
_DOJ_D = dict(min_range_atr=0.6, body_max=0.1, ctx_min_atr=0.5, ctx_lookback=5)

ORIGINAL = {n: dict(p) for n, p in {
    "MORNING_STAR": _STAR_O, "EVENING_STAR": _STAR_O, "THREE_WHITE_SOLDIERS": _SOL_O, "THREE_BLACK_CROWS": _SOL_O,
    "BULLISH_ENGULFING": _ENG_O, "BEARISH_ENGULFING": _ENG_O, "PIERCING_LINE": _PIE_O, "DARK_CLOUD_COVER": _PIE_O,
    "HAMMER": _HAM_O, "SHOOTING_STAR": _HAM_O, "DOJI_BULLISH_REVERSAL": _DOJ_O, "DOJI_BEARISH_REVERSAL": _DOJ_O}.items()}
DEFAULTS = {n: dict(p) for n, p in {
    "MORNING_STAR": _STAR_D, "EVENING_STAR": _STAR_D, "THREE_WHITE_SOLDIERS": _SOL_D, "THREE_BLACK_CROWS": _SOL_D,
    "BULLISH_ENGULFING": _ENG_D, "BEARISH_ENGULFING": _ENG_D, "PIERCING_LINE": _PIE_D, "DARK_CLOUD_COVER": _PIE_D,
    "HAMMER": _HAM_D, "SHOOTING_STAR": _HAM_D, "DOJI_BULLISH_REVERSAL": _DOJ_D, "DOJI_BEARISH_REVERSAL": _DOJ_D}.items()}

_G_STAR = dict(c1_body_rng=[0.5, 0.6, 0.7], star_max=[0.2, 0.3, 0.4], pen=[0.5, 0.6, 0.75], min_body_atr=[0.0, 0.3, 0.5],
               ctx_min_atr=[-1, 0, 0.5, 1.0])
_G_SOL = dict(min_body_atr=[0.0, 0.3, 0.5, 0.8], close_pos=[0.0, 0.6, 0.75], open_in_body=[0, 1])
_G_ENG = dict(min_body_atr=[0.0, 0.3, 0.5], engulf_ratio=[0.0, 1.0, 1.5, 2.0], gap_tol_atr=[0.0, 0.1, 0.3],
              ctx_min_atr=[-1, 0, 0.5, 1.0], ctx_lookback=[3, 5, 8], prev_body_atr=[0.0, 0.3])
_G_PIE = dict(min_body_atr=[0.0, 0.3, 0.5], gap_tol_atr=[0.0, 0.1, 0.3], pen=[0.5, 0.6, 0.75], ctx_min_atr=[-1, 0, 0.5, 1.0],
              ctx_lookback=[3, 5])
_G_HAM = dict(min_range_atr=[0.0, 0.6, 1.0], wick_ratio=[2.0, 2.5, 3.0], upper_max=[0.1, 0.3, 0.5], ctx_min_atr=[-1, 0, 0.5, 1.0],
              ctx_lookback=[3, 5, 8])
_G_DOJ = dict(min_range_atr=[0.0, 0.6, 1.0], body_max=[0.05, 0.1, 0.15], ctx_min_atr=[0, 0.5, 1.0, 1.5], ctx_lookback=[3, 5, 8])
PARAM_GRID = {"MORNING_STAR": _G_STAR, "EVENING_STAR": _G_STAR, "THREE_WHITE_SOLDIERS": _G_SOL, "THREE_BLACK_CROWS": _G_SOL,
              "BULLISH_ENGULFING": _G_ENG, "BEARISH_ENGULFING": _G_ENG, "PIERCING_LINE": _G_PIE, "DARK_CLOUD_COVER": _G_PIE,
              "HAMMER": _G_HAM, "SHOOTING_STAR": _G_HAM, "DOJI_BULLISH_REVERSAL": _G_DOJ, "DOJI_BEARISH_REVERSAL": _G_DOJ}


# ------------------------------------------------------------------ 12 MO HINH BO SUNG ------------------------------------------------------------------
# Khong co trong ai_v5 => KHONG co ten trong pattern_encoding cua model hien tai. Mac dinh CHI dung trong tuner/lab; chi vao bot live
# khi duoc bat trong candle_params.json ("enabled_extra") SAU KHI da them ten vao feature_schema.PATTERN_ENCODING.
ORDER_EXTRA = ["BULLISH_HARAMI", "BEARISH_HARAMI", "TWEEZER_BOTTOM", "TWEEZER_TOP", "HANGING_MAN", "INVERTED_HAMMER",
               "DRAGONFLY_DOJI", "GRAVESTONE_DOJI", "THREE_INSIDE_UP", "THREE_INSIDE_DOWN", "BULLISH_MARUBOZU", "BEARISH_MARUBOZU"]
DIRECTION.update({"BULLISH_HARAMI": 1, "BEARISH_HARAMI": -1, "TWEEZER_BOTTOM": 1, "TWEEZER_TOP": -1, "HANGING_MAN": -1,
                  "INVERTED_HAMMER": 1, "DRAGONFLY_DOJI": 1, "GRAVESTONE_DOJI": -1, "THREE_INSIDE_UP": 1, "THREE_INSIDE_DOWN": -1,
                  "BULLISH_MARUBOZU": 1, "BEARISH_MARUBOZU": -1})
_HAR_D = dict(big_body_atr=0.5, inside_max=0.5, need_color=1, ctx_min_atr=0.5, ctx_lookback=5)
_TWZ_D = dict(tol_atr=0.1, min_body_atr=0.3, ctx_min_atr=0.5, ctx_lookback=5)
_HNG_D = dict(min_range_atr=0.6, wick_ratio=2.0, upper_max=0.3, ctx_min_atr=0.5, ctx_lookback=5)
_DRG_D = dict(min_range_atr=0.6, body_max=0.1, wick_min=0.6, other_wick_max=0.1, ctx_min_atr=0.5, ctx_lookback=5)
_TIN_D = dict(big_body_atr=0.5, conf=1.0, ctx_min_atr=0.5, ctx_lookback=5)
_MAR_D = dict(body_rng=0.9, min_body_atr=1.0)
for _n, _p in {"BULLISH_HARAMI": _HAR_D, "BEARISH_HARAMI": _HAR_D, "TWEEZER_BOTTOM": _TWZ_D, "TWEEZER_TOP": _TWZ_D,
               "HANGING_MAN": _HNG_D, "INVERTED_HAMMER": _HNG_D, "DRAGONFLY_DOJI": _DRG_D, "GRAVESTONE_DOJI": _DRG_D,
               "THREE_INSIDE_UP": _TIN_D, "THREE_INSIDE_DOWN": _TIN_D, "BULLISH_MARUBOZU": _MAR_D, "BEARISH_MARUBOZU": _MAR_D}.items():
    DEFAULTS[_n] = dict(_p)
    ORIGINAL[_n] = dict(_p)          # khong co ban goc ai_v5
_GX_HAR = dict(big_body_atr=[0.5, 0.8, 1.0], inside_max=[0.3, 0.5, 0.7], need_color=[0, 1], ctx_min_atr=[-1, 0, 0.5, 1.0], ctx_lookback=[3, 5, 8])
_GX_TWZ = dict(tol_atr=[0.05, 0.1, 0.2, 0.3], min_body_atr=[0.0, 0.3, 0.5], ctx_min_atr=[-1, 0, 0.5, 1.0], ctx_lookback=[3, 5, 8])
_GX_HNG = dict(min_range_atr=[0.0, 0.6, 1.0], wick_ratio=[2.0, 2.5, 3.0], upper_max=[0.1, 0.3, 0.5], ctx_min_atr=[-1, 0, 0.5, 1.0], ctx_lookback=[3, 5, 8])
_GX_DRG = dict(min_range_atr=[0.0, 0.6, 1.0], body_max=[0.05, 0.1, 0.15], wick_min=[0.5, 0.6, 0.7], other_wick_max=[0.05, 0.1, 0.2],
               ctx_min_atr=[-1, 0, 0.5, 1.0], ctx_lookback=[3, 5])
_GX_TIN = dict(big_body_atr=[0.5, 0.8], conf=[0.75, 1.0], ctx_min_atr=[-1, 0, 0.5, 1.0], ctx_lookback=[3, 5])
_GX_MAR = dict(body_rng=[0.85, 0.9, 0.95], min_body_atr=[0.6, 1.0, 1.5])
PARAM_GRID.update({"BULLISH_HARAMI": _GX_HAR, "BEARISH_HARAMI": _GX_HAR, "TWEEZER_BOTTOM": _GX_TWZ, "TWEEZER_TOP": _GX_TWZ,
                   "HANGING_MAN": _GX_HNG, "INVERTED_HAMMER": _GX_HNG, "DRAGONFLY_DOJI": _GX_DRG, "GRAVESTONE_DOJI": _GX_DRG,
                   "THREE_INSIDE_UP": _GX_TIN, "THREE_INSIDE_DOWN": _GX_TIN, "BULLISH_MARUBOZU": _GX_MAR, "BEARISH_MARUBOZU": _GX_MAR})
ALL_PATTERNS = ORDER + ORDER_EXTRA


# ------------------------------------------------------------------ vector hoa ------------------------------------------------------------------
def S(a, k):
    """Dich a xuong k nen (gia tri nen i-k tai vi tri i). Thieu du lieu -> NaN (so sanh bool = False)."""
    if k == 0:
        return a
    out = np.zeros(len(a), dtype=bool) if a.dtype == bool else np.full(len(a), np.nan)
    if k < len(a):
        out[k:] = a[:-k]
    return out


def prep(o, h, l, c, atr):
    body = np.abs(c - o)
    return {"o": o, "h": h, "l": l, "c": c, "atr": atr, "body": body, "rng": np.maximum(h - l, 1e-9), "bull": c > o, "bear": c < o,
            "up": h - np.maximum(o, c), "lo": np.minimum(o, c) - l}


def _ctx(A, dirn, n, P):
    if P["ctx_min_atr"] < 0:
        return np.ones(len(A["c"]), dtype=bool)
    prior = S(A["c"], n) - S(A["c"], n + int(P["ctx_lookback"]))
    thr = P["ctx_min_atr"] * A["atr"]
    return (prior < -thr) if dirn == 1 else (prior > thr)


def mask(name, A, P):
    """Mang bool: tai nen i co mo hinh `name` (nen i la nen cuoi cua mau hinh) hay khong. Doc lap tung mo hinh."""
    o, h, l, c, atr, body, rng, bull, bear = (A[k] for k in ("o", "h", "l", "c", "atr", "body", "rng", "bull", "bear"))
    mb = P.get("min_body_atr", 0.0) * atr
    with np.errstate(invalid="ignore"):
        if name in ("MORNING_STAR", "EVENING_STAR"):
            first_ok = S(body, 2) > P["c1_body_rng"] * S(rng, 2)
            m = first_ok & (S(body, 2) >= mb) & (S(body, 1) < P["star_max"] * S(body, 2)) & (body >= mb)
            c1o, c1c = S(o, 2), S(c, 2)
            if name == "MORNING_STAR":
                return m & S(bear, 2) & bull & (c > c1c + P["pen"] * (c1o - c1c)) & _ctx(A, 1, 3, P)
            return m & S(bull, 2) & bear & (c < c1c - P["pen"] * (c1c - c1o)) & _ctx(A, -1, 3, P)
        if name in ("THREE_WHITE_SOLDIERS", "THREE_BLACK_CROWS"):
            bodies = np.minimum.reduce([body, S(body, 1), S(body, 2)]) >= mb
            if name == "THREE_WHITE_SOLDIERS":
                cp = (c - l) / rng
                m = bull & S(bull, 1) & S(bull, 2) & bodies & (S(c, 1) > S(c, 2)) & (c > S(c, 1)) & (S(o, 1) > S(o, 2)) & (o > S(o, 1))
                m &= np.minimum.reduce([cp, S(cp, 1), S(cp, 2)]) >= P["close_pos"]
                if P["open_in_body"]:
                    m &= (S(o, 1) <= S(c, 2)) & (o <= S(c, 1))
                return m
            cp = (h - c) / rng
            m = bear & S(bear, 1) & S(bear, 2) & bodies & (S(c, 1) < S(c, 2)) & (c < S(c, 1)) & (S(o, 1) < S(o, 2)) & (o < S(o, 1))
            m &= np.minimum.reduce([cp, S(cp, 1), S(cp, 2)]) >= P["close_pos"]
            if P["open_in_body"]:
                m &= (S(o, 1) >= S(c, 2)) & (o >= S(c, 1))
            return m
        gap = P.get("gap_tol_atr", 0.0) * atr
        if name == "BULLISH_ENGULFING":
            return (S(bear, 1) & bull & (body >= mb) & (S(body, 1) >= P["prev_body_atr"] * atr) & (o <= S(c, 1) + gap) & (c >= S(o, 1))
                    & (body >= P["engulf_ratio"] * S(body, 1)) & _ctx(A, 1, 2, P))
        if name == "BEARISH_ENGULFING":
            return (S(bull, 1) & bear & (body >= mb) & (S(body, 1) >= P["prev_body_atr"] * atr) & (o >= S(c, 1) - gap) & (c <= S(o, 1))
                    & (body >= P["engulf_ratio"] * S(body, 1)) & _ctx(A, -1, 2, P))
        if name == "PIERCING_LINE":
            return (S(bear, 1) & bull & (S(body, 1) >= mb) & (body >= mb) & (o < S(c, 1) + gap)
                    & (c > S(c, 1) + P["pen"] * (S(o, 1) - S(c, 1))) & (c < S(o, 1)) & _ctx(A, 1, 2, P))
        if name == "DARK_CLOUD_COVER":
            return (S(bull, 1) & bear & (S(body, 1) >= mb) & (body >= mb) & (o > S(c, 1) - gap)
                    & (c < S(c, 1) - P["pen"] * (S(c, 1) - S(o, 1))) & (c > S(o, 1)) & _ctx(A, -1, 2, P))
        size_ok = rng >= P.get("min_range_atr", 0.0) * atr
        if name == "HAMMER":
            return size_ok & (body > 0) & (A["lo"] >= P["wick_ratio"] * body) & (A["up"] <= P["upper_max"] * body) & _ctx(A, 1, 1, P)
        if name == "SHOOTING_STAR":
            return size_ok & (body > 0) & (A["up"] >= P["wick_ratio"] * body) & (A["lo"] <= P["upper_max"] * body) & _ctx(A, -1, 1, P)
        if name == "DOJI_BULLISH_REVERSAL":
            return size_ok & (body <= P["body_max"] * rng) & _ctx(A, 1, 1, P)
        if name == "DOJI_BEARISH_REVERSAL":
            return size_ok & (body <= P["body_max"] * rng) & _ctx(A, -1, 1, P)
        if name in ("BULLISH_HARAMI", "BEARISH_HARAMI"):
            big = S(body, 1) >= P["big_body_atr"] * atr
            small = body <= P["inside_max"] * S(body, 1)
            if name == "BULLISH_HARAMI":
                inside = (np.maximum(o, c) <= S(o, 1)) & (np.minimum(o, c) >= S(c, 1))
                col = bull if P["need_color"] else np.ones(len(c), dtype=bool)
                return S(bear, 1) & big & inside & small & col & _ctx(A, 1, 2, P)
            inside = (np.maximum(o, c) <= S(c, 1)) & (np.minimum(o, c) >= S(o, 1))
            col = bear if P["need_color"] else np.ones(len(c), dtype=bool)
            return S(bull, 1) & big & inside & small & col & _ctx(A, -1, 2, P)
        if name == "TWEEZER_BOTTOM":
            return (S(bear, 1) & bull & (np.abs(S(l, 1) - l) <= P["tol_atr"] * atr) & (S(body, 1) >= mb) & (body >= mb) & _ctx(A, 1, 2, P))
        if name == "TWEEZER_TOP":
            return (S(bull, 1) & bear & (np.abs(S(h, 1) - h) <= P["tol_atr"] * atr) & (S(body, 1) >= mb) & (body >= mb) & _ctx(A, -1, 2, P))
        if name == "HANGING_MAN":
            return size_ok & (body > 0) & (A["lo"] >= P["wick_ratio"] * body) & (A["up"] <= P["upper_max"] * body) & _ctx(A, -1, 1, P)
        if name == "INVERTED_HAMMER":
            return size_ok & (body > 0) & (A["up"] >= P["wick_ratio"] * body) & (A["lo"] <= P["upper_max"] * body) & _ctx(A, 1, 1, P)
        if name == "DRAGONFLY_DOJI":
            return (size_ok & (body <= P["body_max"] * rng) & (A["lo"] >= P["wick_min"] * rng) & (A["up"] <= P["other_wick_max"] * rng)
                    & _ctx(A, 1, 1, P))
        if name == "GRAVESTONE_DOJI":
            return (size_ok & (body <= P["body_max"] * rng) & (A["up"] >= P["wick_min"] * rng) & (A["lo"] <= P["other_wick_max"] * rng)
                    & _ctx(A, -1, 1, P))
        if name in ("THREE_INSIDE_UP", "THREE_INSIDE_DOWN"):
            big = S(body, 2) >= P["big_body_atr"] * atr
            c1o, c1c = S(o, 2), S(c, 2)
            if name == "THREE_INSIDE_UP":
                inside = (np.maximum(S(o, 1), S(c, 1)) <= c1o) & (np.minimum(S(o, 1), S(c, 1)) >= c1c)
                return S(bear, 2) & big & inside & S(bull, 1) & bull & (c > c1c + P["conf"] * (c1o - c1c)) & _ctx(A, 1, 3, P)
            inside = (np.maximum(S(o, 1), S(c, 1)) <= c1c) & (np.minimum(S(o, 1), S(c, 1)) >= c1o)
            return S(bull, 2) & big & inside & S(bear, 1) & bear & (c < c1c - P["conf"] * (c1c - c1o)) & _ctx(A, -1, 3, P)
        if name == "BULLISH_MARUBOZU":
            return bull & (body >= P["body_rng"] * rng) & (body >= mb)
        if name == "BEARISH_MARUBOZU":
            return bear & (body >= P["body_rng"] * rng) & (body >= mb)
    raise ValueError(name)


# ------------------------------------------------------------------ cau hinh JSON ------------------------------------------------------------------
def default_config_path():
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(here) == "live":                         # ai_v6/live/candle_params_v6.py
        return os.path.join(os.path.dirname(here), "candle_params.json")
    return os.path.join(here, "ai_v6", "candle_params.json")     # ban sao o thu muc goc


CONFIG_PATH = os.environ.get("AI_V6_CANDLE_PARAMS") or default_config_path()
_cache = {"mtime": None, "params": None, "checked": 0.0, "enabled": []}


def load_params(path=None, force=False):
    path = path or CONFIG_PATH
    now = time.time()
    if not force and _cache["params"] is not None and now - _cache["checked"] < 30:
        return _cache["params"]
    _cache["checked"] = now
    try:
        mt = os.path.getmtime(path)
    except OSError:
        mt = None
    if not force and _cache["params"] is not None and mt == _cache["mtime"]:
        return _cache["params"]
    params = {n: dict(p) for n, p in DEFAULTS.items()}
    if mt is not None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            _cache["enabled"] = [n for n in raw.get("enabled_extra", []) if n in ORDER_EXTRA]
            cfg = raw.get("patterns", {})
            for n, p in cfg.items():
                if n in params:
                    params[n].update({k: v for k, v in p.items() if k in params[n]})
        except Exception:
            pass                                               # file loi -> dung DEFAULTS (fail-safe)
    _cache.update(mtime=mt, params=params)
    return params


# ------------------------------------------------------------------ nhan dien tren nen cuoi ------------------------------------------------------------------
def _extreme(name, l, h):
    return {"MORNING_STAR": lambda: l[-3:].min(), "EVENING_STAR": lambda: h[-3:].max(), "THREE_WHITE_SOLDIERS": lambda: l[-3],
            "THREE_BLACK_CROWS": lambda: h[-3], "BULLISH_ENGULFING": lambda: l[-2:].min(), "BEARISH_ENGULFING": lambda: h[-2:].max(),
            "PIERCING_LINE": lambda: l[-2:].min(), "DARK_CLOUD_COVER": lambda: h[-2:].max(), "HAMMER": lambda: l[-1],
            "SHOOTING_STAR": lambda: h[-1], "DOJI_BULLISH_REVERSAL": lambda: l[-1], "DOJI_BEARISH_REVERSAL": lambda: h[-1],
            "BULLISH_HARAMI": lambda: l[-2:].min(), "BEARISH_HARAMI": lambda: h[-2:].max(), "TWEEZER_BOTTOM": lambda: l[-2:].min(),
            "TWEEZER_TOP": lambda: h[-2:].max(), "HANGING_MAN": lambda: h[-1], "INVERTED_HAMMER": lambda: l[-1],
            "DRAGONFLY_DOJI": lambda: l[-1], "GRAVESTONE_DOJI": lambda: h[-1], "THREE_INSIDE_UP": lambda: l[-3:].min(),
            "THREE_INSIDE_DOWN": lambda: h[-3:].max(), "BULLISH_MARUBOZU": lambda: l[-1], "BEARISH_MARUBOZU": lambda: h[-1]}[name]()


def detect_last(candles: list, atr: float, params=None, include_extra=None):
    """Mo hinh dau tien (theo ORDER, giong ai_v5) khop tai nen DA DONG cuoi cung, hoac None. Can >= 12 nen de ctx_lookback toi 8.
    include_extra: None = chi cac mo hinh bo sung duoc bat trong candle_params.json ("enabled_extra"); True = tat ca; False = khong co."""
    if atr <= 0 or len(candles) < 5:
        return None
    P = params or load_params()
    extra = ORDER_EXTRA if include_extra else ([] if include_extra is False else list(_cache.get("enabled", [])))
    c = candles[-16:]
    o = np.array([x["open"] for x in c], float)
    h = np.array([x["high"] for x in c], float)
    l = np.array([x["low"] for x in c], float)
    cl = np.array([x["close"] for x in c], float)
    A = prep(o, h, l, cl, np.full(len(c), float(atr)))
    for name in ORDER + extra:
        if mask(name, A, P[name])[-1]:
            d = DIRECTION[name]
            entry, ext, buf = cl[-1], _extreme(name, l, h), 0.3 * atr
            if d == 1:
                sl = ext - buf
                tp = entry + REWARD_RISK_RATIO * (entry - sl)
            else:
                sl = ext + buf
                tp = entry - REWARD_RISK_RATIO * (sl - entry)
            return {"pattern": name, "direction": "BUY" if d == 1 else "SELL", "sl": float(sl), "tp": float(tp)}
    return None
