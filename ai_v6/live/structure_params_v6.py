# ai_v6/live/structure_params_v6.py
"""
CAC MO HINH CAU TRUC CON LAI (Hinh hoc 14, Harmonic 8, Phan ky 8, ICT 6, VSA 6, Continuation 4) - MOI HANG SO TRONG DINH NGHIA LA 1 THAM SO
RIENG CHO TUNG MO HINH (giong thong so indicator), dung CHUNG 1 nguon cho tuner (backtest lich su) va bot live.

    build_ctx(candles, factors)   dung boi canh (swing tho / xen ke / swing lon theo tung he so, ATR, volume...) tu cua so nen DA DONG
    detect_structure(ctx, PP)     [(source_type, match), ...] cung thu tu / cung do chi tiet voi scanner_v6 cu
    ctx = ...; detect_structure(ctx, PP, only="DOUBLE_TOP")  -> chi xet 1 mo hinh (cho tuner)

Voi DEFAULTS ket qua GIONG HET cac module *_v6.py da kiem toan (kiem tra tuong duong trong test_structure_params.py).
Tham so ghi de qua structure_params.json (do structure_tuner_v6.py ghi).
"""
import json
import os
import time

import numpy as np
import pandas as pd

RIGHT_BARS = 5
GEO_NAMES = ["TRIPLE_TOP", "HEAD_AND_SHOULDERS", "TRIPLE_BOTTOM", "INVERTED_HEAD_AND_SHOULDERS", "DOUBLE_TOP", "DOUBLE_BOTTOM",
             "ASCENDING_TRIANGLE", "DESCENDING_TRIANGLE", "BULLISH_SYMMETRICAL_TRIANGLE", "BEARISH_SYMMETRICAL_TRIANGLE",
             "BULLISH_FLAG", "BEARISH_FLAG", "BULLISH_FALLING_WEDGE", "BEARISH_RISING_WEDGE"]
HAR_NAMES = [f"{b}_{d}" for b in ("GARTLEY", "BAT", "BUTTERFLY", "CRAB") for d in ("BULLISH", "BEARISH")]
DIV_NAMES = [f"{i}_{d}_DIVERGENCE_{k}" for i in ("RSI", "MACD") for d in ("BULLISH", "BEARISH") for k in ("REGULAR", "HIDDEN")]
ICT_NAMES = ["BULLISH_ORDER_BLOCK", "BEARISH_ORDER_BLOCK", "BULLISH_FVG", "BEARISH_FVG", "BULLISH_LIQUIDITY_SWEEP", "BEARISH_LIQUIDITY_SWEEP"]
VSA_NAMES = ["VSA_STOPPING_VOLUME_BUY", "VSA_STOPPING_VOLUME_SELL", "VSA_SELLING_CLIMAX", "VSA_BUYING_CLIMAX", "VSA_NO_DEMAND", "VSA_NO_SUPPLY"]
CONT_NAMES = ["ROUNDING_BOTTOM", "ROUNDING_TOP", "CUP_AND_HANDLE", "INVERTED_CUP_AND_HANDLE"]
ALL_NAMES = GEO_NAMES + HAR_NAMES + DIV_NAMES + ICT_NAMES + VSA_NAMES + CONT_NAMES
SOURCE = {**{n: "GEOMETRIC_PATTERN" for n in GEO_NAMES}, **{n: "HARMONIC_PATTERN" for n in HAR_NAMES},
          **{n: "DIVERGENCE_PATTERN" for n in DIV_NAMES}, **{n: "ICT_PATTERN" for n in ICT_NAMES},
          **{n: "VSA_PATTERN" for n in VSA_NAMES}, **{n: "CONTINUATION_PATTERN" for n in CONT_NAMES}}
_SELL_GEO = {"TRIPLE_TOP", "HEAD_AND_SHOULDERS", "DOUBLE_TOP", "DESCENDING_TRIANGLE", "BEARISH_SYMMETRICAL_TRIANGLE", "BEARISH_FLAG", "BEARISH_RISING_WEDGE"}
DIRECTION = {}
for _n in ALL_NAMES:
    if _n in GEO_NAMES:
        DIRECTION[_n] = -1 if _n in _SELL_GEO else 1
    elif _n in VSA_NAMES:
        DIRECTION[_n] = 1 if _n in ("VSA_STOPPING_VOLUME_BUY", "VSA_SELLING_CLIMAX", "VSA_NO_SUPPLY") else -1
    elif _n in CONT_NAMES:
        DIRECTION[_n] = 1 if _n in ("ROUNDING_BOTTOM", "CUP_AND_HANDLE") else -1
    else:
        DIRECTION[_n] = -1 if "BEARISH" in _n else 1

# ---------------------------------------------------------------- THAM SO MAC DINH + LUOI DO ----------------------------------------------------------------
DEFAULTS, PARAM_GRID = {}, {}
for _n in GEO_NAMES:
    d = {"tol_atr": 0.10, "min_height_atr": 0.5, "max_age": 80}
    g = {"tol_atr": [0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0], "min_height_atr": [0.3, 0.5, 1.0, 1.5], "max_age": [40, 80, 150]}
    if _n in ("HEAD_AND_SHOULDERS", "INVERTED_HEAD_AND_SHOULDERS"):
        d["head_min_atr"], g["head_min_atr"] = 0.3, [0.0, 0.3, 0.6]
    if _n in ("BULLISH_FLAG", "BEARISH_FLAG"):
        d["pole_min_widths"], g["pole_min_widths"] = 1.5, [1.0, 1.5, 2.5]
    DEFAULTS[_n], PARAM_GRID[_n] = d, g
for _n in HAR_NAMES:
    DEFAULTS[_n] = {"ratio_scale": 1.0, "major_move_atr": 4.0, "sl_buffer_atr": 0.5}
    PARAM_GRID[_n] = {"ratio_scale": [0.5, 0.75, 1.0, 1.25], "major_move_atr": [2.0, 3.0, 4.0, 6.0]}
for _n in DIV_NAMES:
    rsi = _n.startswith("RSI")
    DEFAULTS[_n] = {"fresh_bars": 3, "min_sep": 6, "max_sep": 80, "min_price_diff_atr": 0.10,
                    "min_ind_diff": 2.0 if rsi else 0.05, "major_move_atr": 4.0}
    PARAM_GRID[_n] = {"fresh_bars": [1, 3, 6], "min_sep": [4, 6, 10], "max_sep": [40, 80, 120], "min_price_diff_atr": [0.0, 0.1, 0.3],
                      "min_ind_diff": [1.0, 2.0, 4.0] if rsi else [0.02, 0.05, 0.1], "major_move_atr": [2.0, 3.0, 4.0, 6.0]}
for _n in ("BULLISH_ORDER_BLOCK", "BEARISH_ORDER_BLOCK"):
    DEFAULTS[_n] = {"displacement_atr": 1.5, "max_swing_age": 80, "fresh_break": 1}
    PARAM_GRID[_n] = {"displacement_atr": [1.0, 1.5, 2.0, 2.5], "max_swing_age": [40, 80, 150], "fresh_break": [0, 1]}
for _n in ("BULLISH_FVG", "BEARISH_FVG"):
    DEFAULTS[_n] = {"min_size_atr": 0.2}
    PARAM_GRID[_n] = {"min_size_atr": [0.05, 0.1, 0.2, 0.4, 0.6, 1.0]}
for _n in ("BULLISH_LIQUIDITY_SWEEP", "BEARISH_LIQUIDITY_SWEEP"):
    DEFAULTS[_n] = {"max_swing_age": 80, "min_wick_atr": 0.0}
    PARAM_GRID[_n] = {"max_swing_age": [20, 40, 80, 150], "min_wick_atr": [0.0, 0.1, 0.3, 0.5]}
for _n in ("VSA_STOPPING_VOLUME_BUY", "VSA_STOPPING_VOLUME_SELL"):
    DEFAULTS[_n] = {"wide_spread": 1.5, "volume_ratio_min": 2.5, "close_thr": 0.3, "min_prior_move_atr": 0.5, "prior_lookback": 5}
    PARAM_GRID[_n] = {"wide_spread": [1.2, 1.5, 2.0], "volume_ratio_min": [2.0, 2.5, 3.5], "close_thr": [0.2, 0.3, 0.4],
                      "min_prior_move_atr": [0.0, 0.5, 1.0], "prior_lookback": [3, 5, 8]}
DEFAULTS["VSA_SELLING_CLIMAX"] = {"wide_spread": 1.5, "volume_ratio_min": 2.0, "close_pos_min": 0.4, "min_prior_move_atr": 0.5, "prior_lookback": 5}
PARAM_GRID["VSA_SELLING_CLIMAX"] = {"wide_spread": [1.2, 1.5, 2.0], "volume_ratio_min": [1.5, 2.0, 3.0], "close_pos_min": [0.3, 0.4, 0.5],
                                    "min_prior_move_atr": [0.0, 0.5, 1.0], "prior_lookback": [3, 5, 8]}
DEFAULTS["VSA_BUYING_CLIMAX"] = {"wide_spread": 1.5, "volume_ratio_min": 2.0, "close_pos_max": 0.6, "min_prior_move_atr": 0.5, "prior_lookback": 5}
PARAM_GRID["VSA_BUYING_CLIMAX"] = {"wide_spread": [1.2, 1.5, 2.0], "volume_ratio_min": [1.5, 2.0, 3.0], "close_pos_max": [0.5, 0.6, 0.7],
                                   "min_prior_move_atr": [0.0, 0.5, 1.0], "prior_lookback": [3, 5, 8]}
for _n in ("VSA_NO_DEMAND", "VSA_NO_SUPPLY"):
    DEFAULTS[_n] = {"narrow_spread": 0.7, "low_volume": 0.7, "quieter": 1, "min_prior_move_atr": 0.5, "prior_lookback": 5}
    PARAM_GRID[_n] = {"narrow_spread": [0.5, 0.7, 0.9], "low_volume": [0.5, 0.7, 0.9], "quieter": [0, 1],
                      "min_prior_move_atr": [0.0, 0.5, 1.0], "prior_lookback": [3, 5, 8]}
for _n in CONT_NAMES:
    DEFAULTS[_n] = {"major_move_atr": 4.0, "min_depth_atr": 0.0}
    PARAM_GRID[_n] = {"major_move_atr": [2.0, 3.0, 4.0, 6.0], "min_depth_atr": [0.0, 1.0, 2.0, 3.0]}
    if "CUP" in _n:
        DEFAULTS[_n]["handle_max_ratio"], PARAM_GRID[_n]["handle_max_ratio"] = 0.5, [0.3, 0.5, 0.7]

RR, MIN_RR, RR_FLOOR = 1.5, 0.8, 1.5


# ---------------------------------------------------------------- cau hinh JSON ----------------------------------------------------------------
def default_config_path():
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(here) == "live":
        return os.path.join(os.path.dirname(here), "structure_params.json")
    return os.path.join(here, "ai_v6", "structure_params.json")


CONFIG_PATH = os.environ.get("AI_V6_STRUCTURE_PARAMS") or default_config_path()
_cache = {"mtime": None, "params": None, "checked": 0.0}


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
    PP = {n: dict(p) for n, p in DEFAULTS.items()}
    if mt is not None:
        try:
            for n, p in json.load(open(path, encoding="utf-8")).get("patterns", {}).items():
                if n in PP:
                    PP[n].update({k: v for k, v in p.items() if k in PP[n]})
        except Exception:
            pass
    _cache.update(mtime=mt, params=PP)
    return PP


def needed_factors(PP):
    return sorted({float(PP[n]["major_move_atr"]) for n in PP if "major_move_atr" in PP[n]})


# ---------------------------------------------------------------- boi canh ----------------------------------------------------------------
def build_ctx(candles, factors=(4.0,), ind=None):
    """Boi canh tai nen DA DONG cuoi cua `candles` (>= 220 nen). ind(kind, idx)->gia tri chi bao (kind 'RSI'|'MACD', idx tuong doi cua so)."""
    from ai_v5.pipeline.swing_detector import find_swing_points, filter_major_swings
    n = len(candles)
    if n < 220:
        return None
    df = pd.DataFrame(candles)
    if "time" not in df.columns:
        df["time"] = range(n)
    swings = find_swing_points(df, left_bars=RIGHT_BARS, right_bars=RIGHT_BARS)
    avg = (df["high"] - df["low"]).rolling(14).mean().median()
    if pd.isna(avg) or avg == 0:
        avg = df["close"].iloc[-1] * 0.001
    i = n - 1
    px = float(df["close"].iloc[i])
    pc = float(candles[i - 1]["close"])
    raw = [s for s in swings if s["index"] < i]
    if len(raw) < 5:
        return None
    sub = pd.DataFrame(candles[max(0, i - 100):i + 1])
    atr = (sub["high"] - sub["low"]).rolling(14).mean().iloc[-1]
    if pd.isna(atr) or atr == 0:
        atr = px * 0.001
    vol = float(df["volume"].rolling(20).mean().iloc[i]) if "volume" in df.columns and not pd.isna(df["volume"].rolling(20).mean().iloc[i]) else 0.0
    if ind is None:
        from ai_v5.pipeline.divergence_patterns import compute_rsi_series, compute_macd_series
        series = {"RSI": compute_rsi_series(df["close"], period=14), "MACD": compute_macd_series(df["close"], fast=12, slow=26)}

        def ind(kind, idx, _s=series):
            if idx < 0 or idx >= len(_s[kind]):
                return None
            v = _s[kind].iloc[idx]
            return None if v != v else float(v)
    return {"i": i, "px": px, "pc": pc, "atr": float(atr), "avg_vol": vol, "raw": raw, "alt": filter_major_swings(raw, 0.0),
            "major": {float(f): [s for s in filter_major_swings(swings, float(f) * float(avg)) if s["index"] < i] for f in factors},
            "recent7": candles[max(0, i - 6):i + 1], "recent12": candles[max(0, i - 11):i + 1], "recent20": candles[max(0, i - 19):i + 1],
            "ind": ind, "rsi_now": ind("RSI", i)}


# ---------------------------------------------------------------- HINH HOC ----------------------------------------------------------------
def _finalize(match, entry):
    risk = abs(entry - match["sl"])
    if risk <= 0:
        return None
    d = match["direction"]
    if abs(match["tp"] - entry) / risk < MIN_RR or (d == "BUY" and match["tp"] <= entry) or (d == "SELL" and match["tp"] >= entry):
        match["tp"] = entry + RR_FLOOR * risk if d == "BUY" else entry - RR_FLOOR * risk
    match["sl"], match["tp"] = float(match["sl"]), float(match["tp"])
    return match


def detect_geo(ctx, PP, only=None):
    alt, i, px, pc, atr = ctx["alt"], ctx["i"], ctx["px"], ctx["pc"], ctx["atr"]
    if atr <= 0 or len(alt) < 4:
        return None

    def up(level):
        return pc <= level < px

    def down(level):
        return pc >= level > px

    for k in (0, 1):
        S = alt[:len(alt) - k]
        if len(S) < 4:
            continue
        age = i - S[-1]["index"]

        def want(name):
            if only is not None and name != only:
                return None
            P = PP[name]
            return P if age <= P["max_age"] else None

        def mk(name, d, sl, tp):
            return _finalize({"pattern": name, "direction": "BUY" if d == 1 else "SELL", "sl": sl, "tp": tp}, px)

        if len(S) >= 5:
            p1, p2, p3, p4, p5 = (s["price"] for s in S[-5:])
            t = [s["type"] for s in S[-5:]]
            if t == ["HIGH", "LOW", "HIGH", "LOW", "HIGH"]:
                neck, top = min(p2, p4), max(p1, p3, p5)
                P = want("TRIPLE_TOP")
                if P:
                    tol, mh = P["tol_atr"] * atr, P["min_height_atr"] * atr
                    if abs(p1 - p3) <= tol and abs(p3 - p5) <= tol and top - neck >= mh and down(neck):
                        return mk("TRIPLE_TOP", -1, top + tol, px - (top - neck))
                P = want("HEAD_AND_SHOULDERS")
                if P:
                    tol, mh = P["tol_atr"] * atr, P["min_height_atr"] * atr
                    if p3 - max(p1, p5) >= P["head_min_atr"] * atr and abs(p1 - p5) <= 1.5 * tol and p3 - neck >= mh and down(neck):
                        return mk("HEAD_AND_SHOULDERS", -1, p3 + tol, px - (p3 - neck))
            elif t == ["LOW", "HIGH", "LOW", "HIGH", "LOW"]:
                neck, bot = max(p2, p4), min(p1, p3, p5)
                P = want("TRIPLE_BOTTOM")
                if P:
                    tol, mh = P["tol_atr"] * atr, P["min_height_atr"] * atr
                    if abs(p1 - p3) <= tol and abs(p3 - p5) <= tol and neck - bot >= mh and up(neck):
                        return mk("TRIPLE_BOTTOM", 1, bot - tol, px + (neck - bot))
                P = want("INVERTED_HEAD_AND_SHOULDERS")
                if P:
                    tol, mh = P["tol_atr"] * atr, P["min_height_atr"] * atr
                    if min(p1, p5) - p3 >= P["head_min_atr"] * atr and abs(p1 - p5) <= 1.5 * tol and neck - p3 >= mh and up(neck):
                        return mk("INVERTED_HEAD_AND_SHOULDERS", 1, p3 - tol, px + (neck - p3))
        for a, b, c in ((S[-3], S[-2], S[-1]), (S[-4], S[-3], S[-2])):
            if a["type"] == "HIGH":
                P = want("DOUBLE_TOP")
                if P:
                    tol, mh = P["tol_atr"] * atr, P["min_height_atr"] * atr
                    neck, top = b["price"], max(a["price"], c["price"])
                    if abs(a["price"] - c["price"]) <= tol and top - neck >= mh and down(neck):
                        return mk("DOUBLE_TOP", -1, top + tol, px - (top - neck))
            else:
                P = want("DOUBLE_BOTTOM")
                if P:
                    tol, mh = P["tol_atr"] * atr, P["min_height_atr"] * atr
                    neck, bot = b["price"], min(a["price"], c["price"])
                    if abs(a["price"] - c["price"]) <= tol and neck - bot >= mh and up(neck):
                        return mk("DOUBLE_BOTTOM", 1, bot - tol, px + (neck - bot))
        Q = S[-4:]
        highs = [s for s in Q if s["type"] == "HIGH"]
        lows = [s for s in Q if s["type"] == "LOW"]
        if len(highs) != 2 or len(lows) != 2:
            continue
        (h_old, h_new), (l_old, l_new) = (highs[0]["price"], highs[1]["price"]), (lows[0]["price"], lows[1]["price"])
        w_old, w_new = h_old - l_old, h_new - l_new
        top, bot = max(h_old, h_new), min(l_old, l_new)

        def geo(name):
            P = want(name)
            if not P or top - bot < P["min_height_atr"] * atr:
                return None, None
            return P, P["tol_atr"] * atr

        P, tol = geo("ASCENDING_TRIANGLE")
        if P and abs(h_old - h_new) <= tol and l_new > l_old and up(top):
            return mk("ASCENDING_TRIANGLE", 1, l_new - tol, px + (top - l_old))
        P, tol = geo("DESCENDING_TRIANGLE")
        if P and abs(l_old - l_new) <= tol and h_new < h_old and down(bot):
            return mk("DESCENDING_TRIANGLE", -1, h_new + tol, px - (h_old - bot))
        if h_new < h_old and l_new > l_old:
            P, tol = geo("BULLISH_SYMMETRICAL_TRIANGLE")
            if P and up(h_new):
                return mk("BULLISH_SYMMETRICAL_TRIANGLE", 1, l_new - tol, px + w_old)
            P, tol = geo("BEARISH_SYMMETRICAL_TRIANGLE")
            if P and down(l_new):
                return mk("BEARISH_SYMMETRICAL_TRIANGLE", -1, h_new + tol, px - w_old)
        pre = S[-5] if len(S) >= 5 else None
        if pre is not None:
            P, tol = geo("BULLISH_FLAG")
            if P and abs(w_old - w_new) <= tol and w_old >= P["min_height_atr"] * atr and h_new < h_old and l_new < l_old \
                    and Q[0]["type"] == "HIGH" and pre["type"] == "LOW" and (h_old - pre["price"]) >= P["pole_min_widths"] * w_old and up(h_new):
                return mk("BULLISH_FLAG", 1, l_new - tol, px + 1.5 * w_old)
            P, tol = geo("BEARISH_FLAG")
            if P and abs(w_old - w_new) <= tol and w_old >= P["min_height_atr"] * atr and h_new > h_old and l_new > l_old \
                    and Q[0]["type"] == "LOW" and pre["type"] == "HIGH" and (pre["price"] - l_old) >= P["pole_min_widths"] * w_old and down(l_new):
                return mk("BEARISH_FLAG", -1, h_new + tol, px - 1.5 * w_old)
        P, tol = geo("BULLISH_FALLING_WEDGE")
        if P and w_old - w_new > tol and h_new < h_old and l_new < l_old and up(h_new):
            return mk("BULLISH_FALLING_WEDGE", 1, l_new - tol, px + w_old)
        P, tol = geo("BEARISH_RISING_WEDGE")
        if P and w_old - w_new > tol and h_new > h_old and l_new > l_old and down(l_new):
            return mk("BEARISH_RISING_WEDGE", -1, h_new + tol, px - w_old)
    return None


# ---------------------------------------------------------------- HARMONIC ----------------------------------------------------------------
_HAR = {"GARTLEY": {"AB_XA": (0.45, 0.78), "BC_AB": (0.30, 1.05), "CD_BC": (0.90, 2.00), "AD_XA": (0.65, 0.95)},
        "BAT": {"AB_XA": (0.28, 0.62), "BC_AB": (0.30, 1.05), "CD_BC": (1.35, 3.00), "AD_XA": (0.78, 1.00)},
        "BUTTERFLY": {"AB_XA": (0.65, 0.92), "BC_AB": (0.30, 1.05), "CD_BC": (1.35, 2.60), "AD_XA": (1.00, 1.55)},
        "CRAB": {"AB_XA": (0.28, 0.75), "BC_AB": (0.30, 1.05), "CD_BC": (1.90, 4.20), "AD_XA": (1.35, 1.90)}}


def _scaled(lo, hi, s):
    c = (lo + hi) / 2
    return c - (c - lo) * s, c + (hi - c) * s


def detect_harmonic(ctx, PP, only=None):
    px, atr = ctx["px"], ctx["atr"]
    if atr <= 0:
        return None
    for base, r in _HAR.items():
        for dirn in ("BULLISH", "BEARISH"):
            name = f"{base}_{dirn}"
            if only is not None and name != only:
                continue
            P = PP[name]
            sw = ctx["major"][float(P["major_move_atr"])]
            if len(sw) < 4:
                continue
            X, A, B, C = sw[-4], sw[-3], sw[-2], sw[-1]
            types = [X["type"], A["type"], B["type"], C["type"]]
            if types not in (["LOW", "HIGH", "LOW", "HIGH"], ["HIGH", "LOW", "HIGH", "LOW"]):
                continue
            bullish = X["type"] == "LOW"
            if bullish != (dirn == "BULLISH"):
                continue
            x, a, b, c = X["price"], A["price"], B["price"], C["price"]
            if bullish and not (x < b < a and b < c < a and px < c):
                continue
            if not bullish and not (x > b > a and b > c > a and px > c):
                continue
            xa, ab, bc = abs(a - x), abs(b - a), abs(c - b)
            if min(xa, ab, bc) < 1e-9:
                continue
            ratios = {"AB_XA": ab / xa, "BC_AB": bc / ab, "CD_BC": abs(px - c) / bc, "AD_XA": abs(px - a) / xa}
            if all(_scaled(*r[k], P["ratio_scale"])[0] <= ratios[k] <= _scaled(*r[k], P["ratio_scale"])[1] for k in ratios):
                buf = P["sl_buffer_atr"] * atr
                return {"pattern": name, "direction": "BUY" if bullish else "SELL", "sl": float(px - buf if bullish else px + buf), "tp": float(c)}
    return None


# ---------------------------------------------------------------- PHAN KY ----------------------------------------------------------------
def detect_divergence(ctx, PP, ind_name, only=None):
    px, atr, i, ind = ctx["px"], ctx["atr"], ctx["i"], ctx["ind"]
    if atr <= 0:
        return None
    for stype in ("LOW", "HIGH"):
        cands = {}
        for kind in ("REGULAR", "HIDDEN"):
            nm = f"{ind_name}_{'BULLISH' if stype == 'LOW' else 'BEARISH'}_DIVERGENCE_{kind}"
            if only is None or nm == only:
                cands[kind] = (nm, PP[nm])
        if not cands:
            continue
        # moi ten co he so swing lon rieng -> lay swing theo ten (cung he so cho ca nhom thi dung chung)
        for kind, (nm, P) in cands.items():
            sw = ctx["major"][float(P["major_move_atr"])]
            same = [s for s in sw if s["type"] == stype]
            if len(same) < 2:
                continue
            s1, s2 = same[-2], same[-1]
            age = i - s2["index"]
            if not (RIGHT_BARS <= age <= RIGHT_BARS + P["fresh_bars"]):
                continue
            if not (P["min_sep"] <= s2["index"] - s1["index"] <= P["max_sep"]):
                continue
            i1, i2 = ind(ind_name, s1["index"]), ind(ind_name, s2["index"])
            if i1 is None or i2 is None:
                continue
            dp, di = s2["price"] - s1["price"], i2 - i1
            min_ind = P["min_ind_diff"] if ind_name == "RSI" else P["min_ind_diff"] * atr
            if abs(dp) < P["min_price_diff_atr"] * atr or abs(di) < min_ind:
                continue
            if stype == "LOW":
                got = "REGULAR" if (dp < 0 and di > 0) else "HIDDEN" if (dp > 0 and di < 0) else None
            else:
                got = "REGULAR" if (dp > 0 and di < 0) else "HIDDEN" if (dp < 0 and di > 0) else None
            if got != kind:
                continue
            if stype == "LOW":
                sl = min(px, s2["price"]) - 0.3 * atr
                risk = px - sl
                if risk <= 0:
                    continue
                return {"pattern": nm, "direction": "BUY", "sl": float(sl), "tp": float(px + 1.5 * risk)}
            sl = max(px, s2["price"]) + 0.3 * atr
            risk = sl - px
            if risk <= 0:
                continue
            return {"pattern": nm, "direction": "SELL", "sl": float(sl), "tp": float(px - 1.5 * risk)}
    return None


# ---------------------------------------------------------------- ICT ----------------------------------------------------------------
def _rr(direction, entry, extreme, atr):
    buf = 0.3 * atr
    if direction == "BUY":
        sl = extreme - buf
        return float(sl), float(entry + 1.5 * (entry - sl))
    sl = extreme + buf
    return float(sl), float(entry - 1.5 * (sl - entry))


def _last_swing(swings, stype, i, max_age):
    for s in reversed(swings):
        if s["type"] == stype and s["index"] < i:
            return s if i - s["index"] <= max_age else None
    return None


def detect_order_block(ctx, PP, name):
    c7, raw, i, px, atr = ctx["recent7"], ctx["raw"], ctx["i"], ctx["px"], ctx["atr"]
    if len(c7) < 6 or not raw or atr <= 0:
        return None
    P = PP[name]
    cur, prev = c7[-1], c7[-2]
    if abs(cur["close"] - cur["open"]) < P["displacement_atr"] * atr:
        return None
    if name == "BULLISH_ORDER_BLOCK":
        hi = _last_swing(raw, "HIGH", i, P["max_swing_age"])
        fresh_ok = (prev["close"] <= hi["price"]) if (hi and P["fresh_break"]) else True
        if hi and cur["close"] > cur["open"] and cur["close"] > hi["price"] and fresh_ok:
            for c in reversed(c7[:-1]):
                if c["close"] < c["open"]:
                    sl, tp = _rr("BUY", px, c["low"], atr)
                    return {"pattern": name, "direction": "BUY", "sl": sl, "tp": tp}
        return None
    lo = _last_swing(raw, "LOW", i, P["max_swing_age"])
    fresh_ok = (prev["close"] >= lo["price"]) if (lo and P["fresh_break"]) else True
    if lo and cur["close"] < cur["open"] and cur["close"] < lo["price"] and fresh_ok:
        for c in reversed(c7[:-1]):
            if c["close"] > c["open"]:
                sl, tp = _rr("SELL", px, c["high"], atr)
                return {"pattern": name, "direction": "SELL", "sl": sl, "tp": tp}
    return None


def detect_fvg(ctx, PP, name):
    c7, atr = ctx["recent7"], ctx["atr"]
    if len(c7) < 3 or atr <= 0:
        return None
    c1, c3 = c7[-3], c7[-1]
    P = PP[name]
    if name == "BULLISH_FVG" and c1["high"] < c3["low"] and c3["low"] - c1["high"] >= P["min_size_atr"] * atr:
        sl, tp = _rr("BUY", c3["close"], c1["high"], atr)
        return {"pattern": name, "direction": "BUY", "sl": sl, "tp": tp}
    if name == "BEARISH_FVG" and c1["low"] > c3["high"] and c1["low"] - c3["high"] >= P["min_size_atr"] * atr:
        sl, tp = _rr("SELL", c3["close"], c1["low"], atr)
        return {"pattern": name, "direction": "SELL", "sl": sl, "tp": tp}
    return None


def detect_sweep(ctx, PP, name):
    c7, raw, i, atr = ctx["recent7"], ctx["raw"], ctx["i"], ctx["atr"]
    if not c7 or not raw or atr <= 0:
        return None
    P = PP[name]
    cur = c7[-1]
    if name == "BEARISH_LIQUIDITY_SWEEP":
        hi = _last_swing(raw, "HIGH", i, P["max_swing_age"])
        if hi and cur["high"] > hi["price"] + P["min_wick_atr"] * atr and cur["close"] < hi["price"]:
            sl, tp = _rr("SELL", cur["close"], cur["high"], atr)
            return {"pattern": name, "direction": "SELL", "sl": sl, "tp": tp}
        return None
    lo = _last_swing(raw, "LOW", i, P["max_swing_age"])
    if lo and cur["low"] < lo["price"] - P["min_wick_atr"] * atr and cur["close"] > lo["price"]:
        sl, tp = _rr("BUY", cur["close"], cur["low"], atr)
        return {"pattern": name, "direction": "BUY", "sl": sl, "tp": tp}
    return None


# ---------------------------------------------------------------- VSA ----------------------------------------------------------------
def detect_vsa(ctx, PP, only=None):
    c20, atr, av = ctx["recent20"], ctx["atr"], ctx["avg_vol"]
    if atr <= 0 or av <= 0 or len(c20) < 4:
        return None
    c, p1, p2 = c20[-1], c20[-2], c20[-3]
    spread = max(c["high"] - c["low"], 1e-9)
    vol = c.get("volume", 0) or 0
    entry = c["close"]
    bull, bear = c["close"] > c["open"], c["close"] < c["open"]
    cpos = (c["close"] - c["low"]) / spread
    sr, vr = spread / atr, vol / av
    quieter_raw = vol < min(p1.get("volume", 0) or 0, p2.get("volume", 0) or 0)

    def prior(P):
        L = int(P["prior_lookback"])
        if len(c20) < L + 3:
            return None
        return c20[-2]["close"] - c20[-2 - L]["close"]

    def res(name, d, extreme):
        buf = 0.3 * atr
        if d == 1:
            sl = extreme - buf
            return {"pattern": name, "direction": "BUY", "sl": float(sl), "tp": float(entry + 1.5 * (entry - sl))}
        sl = extreme + buf
        return {"pattern": name, "direction": "SELL", "sl": float(sl), "tp": float(entry - 1.5 * (sl - entry))}

    for name in VSA_NAMES:
        if only is not None and name != only:
            continue
        P = PP[name]
        pm = prior(P)
        if pm is None:
            continue
        mp = P["min_prior_move_atr"] * atr
        up_ctx, dn_ctx = pm >= mp, pm <= -mp
        if name == "VSA_STOPPING_VOLUME_BUY" and bear and dn_ctx and sr >= P["wide_spread"] and vr >= P["volume_ratio_min"] and cpos >= 1 - P["close_thr"]:
            return res(name, 1, c["low"])
        if name == "VSA_STOPPING_VOLUME_SELL" and bull and up_ctx and sr >= P["wide_spread"] and vr >= P["volume_ratio_min"] and cpos <= P["close_thr"]:
            return res(name, -1, c["high"])
        if name == "VSA_SELLING_CLIMAX" and bear and dn_ctx and sr >= P["wide_spread"] and vr >= P["volume_ratio_min"] and cpos >= P["close_pos_min"]:
            return res(name, 1, c["low"])
        if name == "VSA_BUYING_CLIMAX" and bull and up_ctx and sr >= P["wide_spread"] and vr >= P["volume_ratio_min"] and cpos <= P["close_pos_max"]:
            return res(name, -1, c["high"])
        if name == "VSA_NO_DEMAND" and bull and up_ctx and sr <= P["narrow_spread"] and vr <= P["low_volume"] and (quieter_raw or not P["quieter"]):
            return res(name, -1, c["high"])
        if name == "VSA_NO_SUPPLY" and bear and dn_ctx and sr <= P["narrow_spread"] and vr <= P["low_volume"] and (quieter_raw or not P["quieter"]):
            return res(name, 1, c["low"])
    return None


# ---------------------------------------------------------------- CONTINUATION ----------------------------------------------------------------
def _is_u(p):
    n, k = len(p), p.index(min(p))
    return 1 <= k <= n - 2 and p[0] > p[k] and p[-1] > p[k]


def _is_inv_u(p):
    n, k = len(p), p.index(max(p))
    return 1 <= k <= n - 2 and p[0] < p[k] and p[-1] < p[k]


def _rim(sw, a, b, opp, pick):
    v = [s["price"] for s in sw if s["type"] == opp and a < s["index"] < b]
    return pick(v) if v else None


def _cont_sltp(d, entry, extreme, atr):
    buf, mx = 0.3 * atr, 10 * atr
    if d == "BUY":
        sl = max(extreme - buf, entry - mx)
        return float(sl), float(entry + 1.5 * (entry - sl))
    sl = min(extreme + buf, entry + mx)
    return float(sl), float(entry - 1.5 * (sl - entry))


def detect_continuation(ctx, PP, name):
    px, pc, atr = ctx["px"], ctx["pc"], ctx["atr"]
    P = PP[name]
    sw = ctx["major"][float(P["major_move_atr"])]
    if atr <= 0:
        return None
    md = P["min_depth_atr"] * atr
    if name == "ROUNDING_BOTTOM":
        lows = [s for s in sw if s["type"] == "LOW"]
        if len(lows) < 5:
            return None
        cup = lows[-5:]
        pr = [s["price"] for s in cup]
        if not _is_u(pr):
            return None
        rim = _rim(sw, cup[0]["index"], cup[-1]["index"], "HIGH", max)
        if rim is None or not (px > rim >= pc) or rim - min(pr) < md:
            return None
        sl, tp = _cont_sltp("BUY", px, min(pr), atr)
        return {"pattern": name, "direction": "BUY", "sl": sl, "tp": tp}
    if name == "ROUNDING_TOP":
        highs = [s for s in sw if s["type"] == "HIGH"]
        if len(highs) < 5:
            return None
        cap = highs[-5:]
        pr = [s["price"] for s in cap]
        if not _is_inv_u(pr):
            return None
        rim = _rim(sw, cap[0]["index"], cap[-1]["index"], "LOW", min)
        if rim is None or not (px < rim <= pc) or max(pr) - rim < md:
            return None
        sl, tp = _cont_sltp("SELL", px, max(pr), atr)
        return {"pattern": name, "direction": "SELL", "sl": sl, "tp": tp}
    if name == "CUP_AND_HANDLE":
        lows = [s for s in sw if s["type"] == "LOW"]
        if len(lows) < 6:
            return None
        cup = lows[-6:-1]
        pr = [s["price"] for s in cup]
        if not _is_u(pr):
            return None
        rim = _rim(sw, cup[0]["index"], cup[-1]["index"], "HIGH", max)
        if rim is None:
            return None
        depth, hl = rim - min(pr), lows[-1]["price"]
        hd = rim - hl
        if depth <= 0 or depth < md or not (0 < hd < P["handle_max_ratio"] * depth) or not (px > rim >= pc):
            return None
        sl, tp = _cont_sltp("BUY", px, hl, atr)
        return {"pattern": name, "direction": "BUY", "sl": sl, "tp": tp}
    highs = [s for s in sw if s["type"] == "HIGH"]
    if len(highs) < 6:
        return None
    cap = highs[-6:-1]
    pr = [s["price"] for s in cap]
    if not _is_inv_u(pr):
        return None
    rim = _rim(sw, cap[0]["index"], cap[-1]["index"], "LOW", min)
    if rim is None:
        return None
    depth, hh = max(pr) - rim, highs[-1]["price"]
    hd = hh - rim
    if depth <= 0 or depth < md or not (0 < hd < P["handle_max_ratio"] * depth) or not (px < rim <= pc):
        return None
    sl, tp = _cont_sltp("SELL", px, hh, atr)
    return {"pattern": name, "direction": "SELL", "sl": sl, "tp": tp}


# ---------------------------------------------------------------- TONG HOP ----------------------------------------------------------------
def detect_one(ctx, name, PP):
    """Chi xet DUNG 1 mo hinh `name` (dung cho tuner)."""
    if name in GEO_NAMES:
        return detect_geo(ctx, PP, only=name)
    if name in HAR_NAMES:
        return detect_harmonic(ctx, PP, only=name)
    if name in DIV_NAMES:
        return detect_divergence(ctx, PP, name.split("_")[0], only=name)
    if name in VSA_NAMES:
        return detect_vsa(ctx, PP, only=name)
    if name in ("BULLISH_ORDER_BLOCK", "BEARISH_ORDER_BLOCK"):
        return detect_order_block(ctx, PP, name)
    if name in ("BULLISH_FVG", "BEARISH_FVG"):
        return detect_fvg(ctx, PP, name)
    if name in ("BULLISH_LIQUIDITY_SWEEP", "BEARISH_LIQUIDITY_SWEEP"):
        return detect_sweep(ctx, PP, name)
    return detect_continuation(ctx, PP, name)


def detect_structure(ctx, PP=None):
    """[(source_type, match)] cung thu tu / do chi tiet voi scanner_v6 cu (khong gom nen)."""
    PP = PP or load_params()
    m = [("GEOMETRIC_PATTERN", detect_geo(ctx, PP)), ("HARMONIC_PATTERN", detect_harmonic(ctx, PP)),
         ("DIVERGENCE_PATTERN", detect_divergence(ctx, PP, "RSI")), ("DIVERGENCE_PATTERN", detect_divergence(ctx, PP, "MACD")),
         ("VSA_PATTERN", detect_vsa(ctx, PP)), ("ICT_PATTERN", detect_order_block(ctx, PP, "BULLISH_ORDER_BLOCK") or detect_order_block(ctx, PP, "BEARISH_ORDER_BLOCK")),
         ("ICT_PATTERN", detect_fvg(ctx, PP, "BULLISH_FVG") or detect_fvg(ctx, PP, "BEARISH_FVG")),
         ("ICT_PATTERN", detect_sweep(ctx, PP, "BEARISH_LIQUIDITY_SWEEP") or detect_sweep(ctx, PP, "BULLISH_LIQUIDITY_SWEEP"))]
    for n in ("ROUNDING_BOTTOM", "ROUNDING_TOP", "CUP_AND_HANDLE", "INVERTED_CUP_AND_HANDLE"):
        m.append(("CONTINUATION_PATTERN", detect_continuation(ctx, PP, n)))
    return [(s, x) for s, x in m if x is not None]
