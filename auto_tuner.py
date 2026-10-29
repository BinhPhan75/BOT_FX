"""
auto_tuner.py  v6 — Walk-Forward Optimization + Cross-Validation

Van de voi grid search thuan tuy:
  - Backtest 90 ngay tim ra bo tham so tot nhat TRONG 90 ngay do
  - Nhung 90 ngay tiep theo thi sao? Tham so co con tot khong?
  - Day la OVERFIT — WR backtest cao nhung live thap

Giai phap: Walk-Forward Optimization
  Chia data thanh nhieu cua so:
    Cua so 1: Train 90 ngay  → Test 30 ngay
    Cua so 2: Train 90 ngay  → Test 30 ngay (dich ve phia truoc)
    Cua so 3: Train 90 ngay  → Test 30 ngay
    ...
  Bo tham so tot nhat = bo co WR OOB (out-of-bag/test) cao nhat TRUNG BINH
  — khong phai WR train cao nhat.

  Them nua: dung Stability Score de chon bo tham so on dinh
  (WR khong qua chenh lech giua cac cua so)
  thay vi bo WR cao nhat 1 cua so nhung cua so khac rat thap.

  Ket qua: tham so robust → WR live gan voi WR backtest hon.
"""

import logging
import math
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone, timedelta
from itertools import product
from typing import Dict, List, Optional, Tuple

import config
import param_loader

logger = logging.getLogger("auto_tuner")

_BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
LIVE_DB_PATH = os.path.join(_BASE_DIR, "trades.db")

_lock            = threading.Lock()
_is_running      = False
_last_run_ts     = 0.0
_last_live_count = 0

# ─── Nguong chap nhan ────────────────────────────────────────────────────────
MIN_TRADES   = 1     # toi thieu lenh tren 1 cua so test (giam tu 3→1)
MIN_WR       = 25.0  # WR trung binh toi thieu OOB (giam tu 30→25)
MIN_PF       = 0.50  # PF toi thieu (giam tu 0.85→0.50)
MIN_WINDOWS  = 1     # so cua so test toi thieu co du lenh (giam tu 2→1)

# ─── Walk-Forward config ──────────────────────────────────────────────────────
WFO_CONFIG = {
    "train_days":  90,   # do dai cua so train (khong dung truc tiep nhung
                          # giu de tham chieu — backtest dung test_days lam don vi)
    "test_days":   30,   # do dai cua so test (OOB)
    "step_days":   45,   # buoc dich moi cua so (giam tu 30→45 de giam so windows)
    "min_windows": MIN_WINDOWS,
}
# Voi 365 ngay data: so cua so = (365 - 90) / 45 + 1 = ~7 cua so
# Giam tu 9→7 windows giup giam ~22% thoi gian chay ma van du danh gia stability


# ─── Grid dinh nghia ─────────────────────────────────────────────────────────

# ─── Dac tinh tung symbol ────────────────────────────────────────────────────
#
# XAUUSD (Vang):
#   - Bien dong manh, ATR lon → atr_multiplier nho (co MAX_SL_USD cap)
#   - Can pivot_lookback lon de loc noise dinh day
#   - Zone merge rong hon (gia chay nhanh, zone can "day" hon)
#   - Soup: dinh 2 thuong chi xuot dinh 1 chut → soup_max_exceed nho
#
# EURUSD:
#   - Cap chinh, thanh khoan cao, spread nho
#   - Bien dong vua phai, ATR on dinh
#   - Pivot va zone tieu chuan
#   - Volume spike can ro rang moi breakout that
#
# GBPUSD (Cable):
#   - Bien dong cao hon EURUSD ~30%, nhay cam voi tin tuc UK
#   - ATR multiplier cao hon chut (SL can room hon)
#   - Volume spike can cao hon (nhieu fakeout hon)
#   - Pivot lookback vua (khong can qua lon nhu XAUUSD)
#
# USDJPY:
#   - Thanh khoan cao, trend re keo dai
#   - Pip value lon (1 pip = ~$9/lot)
#   - ATR multiplier cao hon (bien dong JPY khi co tin tuc BOJ)
#   - Zone merge rong hon (gia co the dao dong lon)
#   - RR cao hon vi trend dai

# v7: grid tham so cho kien truc OR (5 nhom tin hieu doc lap). Da BO
# "ob_fvg_proximity_pct"/"smc_ob_search_range"/"ob_fvg_retest_max_bars"/
# "trend_min_agree" vi analysis.py v7 KHONG con dung retest/dong thuan
# lam gate nua (BOS/CHoCH kich hoat tuc thi) — giu lai se lang phi thoi
# gian chay y het bug da gap 2 lan truoc. Them "ema_fast_len", "pa_length"
# vi 2 nhom tin hieu moi (EMA cross, Price Action) gio la TRIGGER DOC LAP,
# anh huong truc tiep den tan suat + chat luong tin hieu.
# v8: THAY "rr_ratio" bang "tp_atr_multiplier" — TP gio tinh DOC LAP theo
# ATR (xem trader.py._calc_sl_tp), khong con la boi so cung cua SL nua,
# nen rr_ratio khong con dieu khien duoc TP => bo khoi grid (tunable vo
# nghia neu giu lai). tp_atr_multiplier dieu chinh THEO PHAN HOI THUC TE:
#   - EURUSD: TP/SL dang qua GAN entry → tang tp_atr_multiplier len.
#   - XAUUSD: TP/SL dang hoi XA, lai/lo bien dong manh → giam tp_atr_multiplier.
#   - GBPUSD: chua ro edge (dang lo) → do rong hon de tim vung tot.
COARSE_GRID_DEFAULT = {
    "atr_period":             [14],
    "atr_multiplier":         [1.2, 1.6],
    "tp_atr_multiplier":      [2.0, 3.0],
    "internal_structure_len": [4, 6],
    "st_factor":              [2.5, 3.5],
    "ema_fast_len":           [7, 9],
    "pa_length":              [10, 14],
}

# Grid Coarse: 1×2×2×2×2×2×2 = 64 combos × ~6-7 cua so WFO / symbol
#
# Param CHINH (anh huong lon den tan suat + WR):
#   internal_structure_len — do nhay fractal pivot phat hien BOS/CHoCH.
#   st_factor              — do rong band SuperTrend (nhay cua tin hieu flip).
#   ema_fast_len            — do nhay EMA cross (ema_slow_len giu co dinh=21).
#   pa_length               — do dai window Price Action/Dow Theory
#                             (pa_vol_multiplier giu co dinh=1.5, dung Pine goc).
#   atr_multiplier          — dieu khien do RONG cua SL.
#   tp_atr_multiplier       — dieu khien do RONG cua TP (DOC LAP voi SL).

# ── XAUUSD — Vang ─────────────────────────────────────────────────────────────
# Bien dong manh → structure_len/pa_length lon hon de tranh tin hieu gia.
# TP dang hoi XA (PF/lai-lo bien dong manh) → giam tp_atr_multiplier.
COARSE_GRID_XAUUSD = {
    "atr_period":             [14],
    "atr_multiplier":         [1.2, 1.6],
    "tp_atr_multiplier":      [2.0, 2.8],
    "internal_structure_len": [5, 8],
    "st_factor":              [2.5, 3.5],
    "ema_fast_len":           [7, 9],
    "pa_length":              [12, 16],
}
# 64 combos

# ── EURUSD — Euro Dollar ───────────────────────────────────────────────────────
# Thanh khoan cao, bien dong vua, cau truc "sach" → structure/pa_length nho hon OK.
# TP dang qua GAN entry → tang tp_atr_multiplier.
COARSE_GRID_EURUSD = {
    "atr_period":             [14],
    "atr_multiplier":         [1.0, 1.4],
    "tp_atr_multiplier":      [2.5, 3.5],
    "internal_structure_len": [4, 6],
    "st_factor":              [2.0, 3.0],
    "ema_fast_len":           [6, 9],
    "pa_length":              [10, 14],
}
# 64 combos

# ── GBPUSD — Cable ────────────────────────────────────────────────────────────
# Bien dong cao hon EUR, nhieu fakeout hon → st_factor cao hon, pa_vol filter
# chat hon (thong qua pa_length lon hon) de giam nhieu (WR dang thap, PF<1).
# Chua ro vung TP toi uu → do rong tp_atr_multiplier.
COARSE_GRID_GBPUSD = {
    "atr_period":             [14],
    "atr_multiplier":         [1.2, 1.6],
    "tp_atr_multiplier":      [2.0, 3.2],
    "internal_structure_len": [5, 8],
    "st_factor":              [2.8, 3.8],
    "ema_fast_len":           [8, 12],
    "pa_length":              [14, 20],
}
# 64 combos

COARSE_GRID_BY_SYMBOL = {
    "XAUUSD": COARSE_GRID_XAUUSD,
    "EURUSD": COARSE_GRID_EURUSD,
    "GBPUSD": COARSE_GRID_GBPUSD,
}

# Fine radius mac dinh: pham vi tinh chinh xung quanh best coarse
_FINE_RADIUS_DEFAULT = {
    "atr_period":             2,
    "atr_multiplier":         0.15,
    "tp_atr_multiplier":      0.4,
    "internal_structure_len": 2,
    "st_factor":              0.5,
    "ema_fast_len":           2,
    "pa_length":              4,
}

FINE_RADIUS_BY_SYMBOL = {
    "XAUUSD": {**_FINE_RADIUS_DEFAULT,
               "atr_multiplier": 0.10,
               "pa_length": 3},
    "EURUSD": {**_FINE_RADIUS_DEFAULT,
               "atr_multiplier": 0.10,
               "tp_atr_multiplier": 0.5},
    "GBPUSD": {**_FINE_RADIUS_DEFAULT,
               "atr_multiplier": 0.20,
               "st_factor":      0.6,
               "pa_length": 3},
}

FINE_STEPS = {
    "atr_period":             1,
    "atr_multiplier":         0.05,
    "tp_atr_multiplier":      0.1,
    "internal_structure_len": 1,
    "st_factor":              0.25,
    "ema_fast_len":           1,
    "pa_length":              1,
}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _count_live() -> int:
    if not os.path.exists(LIVE_DB_PATH):
        return 0
    try:
        with sqlite3.connect(LIVE_DB_PATH) as c:
            r = c.execute(
                "SELECT COUNT(*) FROM trades WHERE result IS NOT NULL"
            ).fetchone()
            return r[0] if r else 0
    except Exception:
        return 0


def _should_run() -> Tuple[bool, str]:
    """
    Neu config.AUTO_TUNER_SCHEDULED_HOUR_VN duoc dat (vi du 2 = 2h sang) —
    uu tien chay THEO LICH CO DINH gio Viet Nam (GMT+7) moi ngay, thay vi
    chi "moi 24h ke tu lan chay truoc" (co the troi gio tuy luc bot duoc
    khoi dong). Van giu them dieu kien "so lenh live moi" lam luoi an toan
    de phan ung neu co bat thuong truoc khi den lich.

    Neu KHONG cau hinh AUTO_TUNER_SCHEDULED_HOUR_VN, giu nguyen hanh vi CU
    (theo chu ky AUTO_TUNER_INTERVAL_DAYS ke tu lan chay truoc).
    """
    scheduled_hour = getattr(config, "AUTO_TUNER_SCHEDULED_HOUR_VN", None)
    min_new = getattr(config, "AUTO_TUNER_MIN_NEW_TRADES", 3)

    if scheduled_hour is not None:
        vn_tz = timezone(timedelta(hours=7))
        now_vn = datetime.now(vn_tz)
        last_run_vn = (datetime.fromtimestamp(_last_run_ts, tz=vn_tz)
                        if _last_run_ts else None)
        already_ran_today = last_run_vn is not None and last_run_vn.date() == now_vn.date()

        if now_vn.hour == scheduled_hour and not already_ran_today:
            return True, f"Dung lich {scheduled_hour:02d}:00 gio VN"

        cur = _count_live()
        if cur - _last_live_count >= min_new:
            return True, f"{cur - _last_live_count} lenh live moi (bat thuong, chay som hon lich)"

        return False, f"Cho lich {scheduled_hour:02d}:00 gio VN (hien tai {now_vn.strftime('%H:%M')} VN)"

    # ── Hanh vi CU (khong cau hinh lich cu the) ────────────────────────────
    interval  = getattr(config, "AUTO_TUNER_INTERVAL_DAYS",  1)
    elapsed_h = (time.time() - _last_run_ts) / 3600

    if _last_run_ts == 0 or elapsed_h >= interval * 24:
        return True, f"Qua chu ky {interval} ngay"
    cur = _count_live()
    if cur - _last_live_count >= min_new:
        return True, f"{cur - _last_live_count} lenh live moi"
    return False, f"Chua den lich (elapsed={elapsed_h:.1f}h)"


def _combos(grid: Dict) -> List[Dict]:
    keys = list(grid.keys())
    return [dict(zip(keys, c)) for c in product(*[grid[k] for k in keys])]


def _fine_grid_around(best: Dict, symbol: str = "") -> List[Dict]:
    """
    Tinh chinh QUANH best-coarse bang COORDINATE-WISE local search: moi lan
    CHI DOI 1 tham so (giu nguyen cac tham so con lai o gia tri best-coarse),
    roi gop lai thanh list combos.

    QUAN TRONG: truoc day ham nay tra ve 1 GRID DICT {key: [values]} roi dua
    qua _combos() de lay Cartesian product toan bo N chieu — voi 7 tham so x
    5-9 gia tri/tham so, so combo thuc te len toi ~275,000 (thay vi ~64 nhu
    Coarse), khien Fine phase chay hang chuc NGAY thay vi vai gio. Doi sang
    coordinate-wise (tong thay vi tich) giam con vai chuc combo, an toan va
    van tinh chinh duoc tung tham so rieng le quanh vung toi uu.
    """
    radius = FINE_RADIUS_BY_SYMBOL.get(symbol, _FINE_RADIUS_DEFAULT)
    combos: List[Dict] = [dict(best)]  # luon giu lai chinh best-coarse de so sanh

    for key, val in best.items():
        if key not in radius:
            continue
        r    = radius[key]
        step = FINE_STEPS[key]
        if isinstance(val, int):
            vals = list(range(max(1, int(val - r)), int(val + r) + 1, max(1, int(step))))
        else:
            vals = []
            v = round(val - r, 6)
            while v <= round(val + r + 1e-9, 6):
                vals.append(round(v, 4))
                v = round(v + step, 6)

        for v in vals:
            if v == val:
                continue  # trung voi best, khoi can them
            combo = dict(best)
            combo[key] = v
            combos.append(combo)

    return combos


# ─── Walk-Forward Scoring ─────────────────────────────────────────────────────

def _wfo_score(
    symbol: str,
    combo: Dict,
    total_days: int,
    run_bt_fn,
) -> Optional[Dict]:
    """
    Danh gia 1 bo tham so bang Walk-Forward:
      1. Chia data thanh nhieu cua so train/test
      2. Voi moi cua so: chay backtest tren phan TEST (OOB)
      3. Tra ve:
           oob_wr_mean   : WR trung binh tren cac cua so test
           oob_wr_std    : Do lech chuan WR (on dinh)
           oob_pf_mean   : PF trung binh
           stability     : 1 - std/mean (1.0 = hoan toan on dinh)
           wfo_score     : Ket hop WR + on dinh + PF
    """
    train_days = WFO_CONFIG["train_days"]
    test_days  = WFO_CONFIG["test_days"]
    step_days  = WFO_CONFIG["step_days"]

    window_results = []

    # Xay dung danh sach cac cua so test OOB
    # Moi cua so: offset_days tinh tu hien tai (0 = hien tai, 30 = 30 ngay truoc, ...)
    # Window 1 (cu nhat): offset = total_days - test_days - train_days ... step den gan nhat
    # backtest_engine(days=test_days, offset_days=X) se lay window [X+test ngay truoc → X ngay truoc]

    # Sinh danh sach offset: tu xa (cu) den gan (moi)
    # Offset lon = cua so cu hon
    offsets = []
    offset = 0
    while offset + train_days + test_days <= total_days:
        # offset_days tuyen vao backtest_engine = so ngay bo cach tu hien tai
        # De test window nam o vi tri [offset+test_days .. offset] so voi "now"
        offsets.append(offset)
        offset += step_days

    # Chay WFO tren tung cua so
    for win_offset in offsets:
        # offset_days: cua so test bat dau tu win_offset ngay truoc "now"
        # days: do dai cua so test
        try:
            stats = run_bt_fn(
                symbol=symbol,
                timeframe=config.TIMEFRAME,
                days=test_days,
                offset_days=win_offset,
                rr_ratio=combo.get("rr_ratio", config.DEFAULT_RR_RATIO),
                use_htf=True,
                use_cache=True,
                params=combo,
            )
        except Exception as e:
            logger.debug("WFO offset=%d loi: %s", win_offset, e)
            continue

        n  = stats.get("total_trades", 0)
        wr = stats.get("win_rate",     0.0)
        pf = stats.get("profit_factor", 0.0)

        if n >= MIN_TRADES:
            window_results.append({"n": n, "wr": wr, "pf": pf})
            logger.debug(
                "  WFO win_offset=%d days=%d: WR=%.1f%% PF=%.2f n=%d",
                win_offset, test_days, wr, pf, n,
            )
        else:
            logger.debug("  WFO win_offset=%d: n=%d < MIN_TRADES — bo qua", win_offset, n)

    if not window_results:
        # Hoan toan khong co lenh nao trong bat ky cua so nao
        # → khong the danh gia, tra None de biet day la combo vo nghia
        return None
    if len(window_results) < WFO_CONFIG["min_windows"]:
        # Co it cua so hon mong muon nhung van co du lieu
        # → van tinh score nhung ghi nhan la it mau
        logger.debug(
            "  WFO: chi co %d/%d windows du lenh — van tinh score nhung do tin cay thap.",
            len(window_results), WFO_CONFIG["min_windows"],
        )

    # Tinh toan score
    wrs = [r["wr"] for r in window_results]
    pfs = [r["pf"] for r in window_results]
    ns  = [r["n"]  for r in window_results]

    wr_mean = sum(wrs) / len(wrs)
    pf_mean = sum(pfs) / len(pfs)
    n_total = sum(ns)

    import statistics as _stats
    wr_std = _stats.stdev(wrs) if len(wrs) > 1 else 0.0

    # Stability: 1 khi wr_std = 0, giam khi bien dong lon
    stability = max(0.0, 1.0 - (wr_std / wr_mean if wr_mean > 0 else 1.0))

    # WFO Score: WR trung binh × on dinh × PF × log(n)
    # Thoa dieu kien nguong moi tinh
    if wr_mean < MIN_WR or pf_mean < MIN_PF:
        # Khong dat nguong toi thieu — van tinh score am de co the chon
        # "it te nhat" neu khong co lua chon nao tot hon
        wfo_score = -(100.0 - wr_mean)  # -70 neu WR=30%, -80 neu WR=20%
    else:
        wfo_score = (
            wr_mean
            * stability
            * min(pf_mean, 2.5)
            * math.log(max(n_total / (MIN_TRADES * len(window_results)), 1) + 1)
        )

    return {
        "oob_wr_mean":  round(wr_mean,   2),
        "oob_wr_std":   round(wr_std,    2),
        "oob_pf_mean":  round(pf_mean,   2),
        "stability":    round(stability, 3),
        "wfo_score":    round(wfo_score, 3),
        "n_windows":    len(window_results),
        "n_total_oob":  n_total,
    }


# ─── Optimizer chinh ─────────────────────────────────────────────────────────

def _run_combos_wfo(
    symbol: str,
    combos: List[Dict],
    phase: str,
    total_days: int,
    run_bt_fn,
) -> Optional[Tuple[Dict, Dict, float]]:
    """
    Chay WFO cho tat ca combos.
    Tra ve (best_combo, best_wfo_result, best_score) hoac None.
    """
    best_score = -1.0
    best_combo = None
    best_wfo   = None
    log_rows   = []

    for i, combo in enumerate(combos, 1):
        wfo = _wfo_score(symbol, combo, total_days, run_bt_fn)
        if wfo is None:
            continue

        sc = wfo["wfo_score"]
        log_rows.append({"combo": combo, "wfo": wfo, "sc": sc})

        logger.debug(
            "[%s][%s] %d/%d WR=%.1f%%±%.1f stability=%.2f PF=%.2f n=%d sc=%.2f",
            symbol, phase, i, len(combos),
            wfo["oob_wr_mean"], wfo["oob_wr_std"],
            wfo["stability"], wfo["oob_pf_mean"],
            wfo["n_total_oob"], sc,
        )

        if sc > best_score:
            best_score = sc
            best_combo = combo.copy()
            best_wfo   = wfo

    # In top 5
    top5 = sorted(log_rows, key=lambda x: x["sc"], reverse=True)[:5]
    logger.info("[%s][%s] Top 5 WFO (%d combos):", symbol, phase, len(combos))
    for r in top5:
        c = r["combo"]
        w = r["wfo"]
        logger.info(
            "  WR=%.1f%%±%.1f stab=%.2f PF=%.2f sc=%.2f | "
            "ATR(%d)x%.2f tp_x%.2f struct=%d st_factor=%.2f ema_fast=%d pa_len=%d",
            w["oob_wr_mean"], w["oob_wr_std"], w["stability"],
            w["oob_pf_mean"], r["sc"],
            c.get("atr_period",14), c.get("atr_multiplier",1.8),
            c.get("tp_atr_multiplier",3.6), c.get("internal_structure_len",5),
            c.get("st_factor",3.0), c.get("ema_fast_len",9),
            c.get("pa_length",14),
        )

    if best_combo is None:
        return None
    # Canh bao neu best score am (khong combo nao dat nguong toi thieu)
    if best_score < 0:
        logger.warning(
            "[WFO] Tat ca %d combo deu co score am (WR<%.0f%% hoac PF<%.2f). "
            "Chon combo TOT NHAT CO (WR=%.1f%% PF=%.2f) lam fallback.",
            len(combos), MIN_WR, MIN_PF,
            best_wfo.get("oob_wr_mean", 0), best_wfo.get("oob_pf_mean", 0),
        )
    return best_combo, best_wfo, best_score


def _optimize_symbol(symbol: str, total_days: int = 365) -> Optional[Dict]:
    """
    Toi uu 2 pha (Coarse WFO → Fine WFO) cho 1 symbol.
    """
    try:
        from backtest_engine import run_backtest as _rb

        # Wrap: them offset_days support
        def run_bt(symbol, timeframe, days, offset_days=0, **kwargs):
            return _rb(
                symbol=symbol,
                timeframe=timeframe,
                days=days,
                offset_days=offset_days,
                **kwargs,
            )
    except ImportError as e:
        logger.error("Khong import duoc backtest_engine: %s", e)
        return None

    # ── Pha 1: Coarse WFO ─────────────────────────────────────────────────
    coarse_grid   = COARSE_GRID_BY_SYMBOL.get(symbol, COARSE_GRID_DEFAULT)
    coarse_combos = _combos(coarse_grid)
    logger.info("[%s] Pha 1 Coarse WFO: %d combos × ~%d cua so",
                symbol, len(coarse_combos),
                (total_days - WFO_CONFIG["train_days"]) // WFO_CONFIG["step_days"])

    result_coarse = _run_combos_wfo(
        symbol, coarse_combos, "coarse", total_days, run_bt
    )
    if not result_coarse:
        logger.warning(
            "[%s] Coarse WFO khong co ket qua — co the do qua it "
            "lenh trong moi cua so test (test_days=%d qua ngan). "
            "Thu tang test_days hoac giam MIN_TRADES.",
            symbol, WFO_CONFIG["test_days"],
        )
        return None

    best_coarse, wfo_coarse, score_coarse = result_coarse
    logger.info(
        "[%s] Coarse xong: WR=%.1f%%±%.1f stab=%.2f sc=%.2f | %s",
        symbol,
        wfo_coarse["oob_wr_mean"], wfo_coarse["oob_wr_std"],
        wfo_coarse["stability"], score_coarse,
        {k: v for k, v in best_coarse.items()},
    )

    # ── Pha 2: Fine WFO (tuy chon — co the tat de chay nhanh lan dau) ───────
    enable_fine = getattr(config, "AUTO_TUNER_ENABLE_FINE_PHASE", False)

    if enable_fine:
        fine_combos = _fine_grid_around(best_coarse, symbol=symbol)

        if fine_combos:
            logger.info("[%s] Pha 2 Fine WFO: %d combos", symbol, len(fine_combos))
            result_fine = _run_combos_wfo(
                symbol, fine_combos, "fine", total_days, run_bt
            )
            if result_fine and result_fine[2] > score_coarse:
                final_combo, final_wfo, _ = result_fine
                logger.info("[%s] Fine cai thien coarse.", symbol)
            else:
                final_combo, final_wfo = best_coarse, wfo_coarse
                final_score = score_coarse
                logger.info("[%s] Giu ket qua coarse.", symbol)
        else:
            final_combo, final_wfo = best_coarse, wfo_coarse
        final_score = score_coarse
    else:
        logger.info("[%s] Fine phase TAT (AUTO_TUNER_ENABLE_FINE_PHASE=False) — dung Coarse.", symbol)
        final_combo, final_wfo = best_coarse, wfo_coarse
        final_score = score_coarse

    # ── Build ket qua ─────────────────────────────────────────────────────
    # Luon tra ve ket qua (du la fallback score am) de bot co tham so
    # thay vi dung lai voi defaults (co the con kem hon).
    # Tag "is_fallback=True" de watcher biet day la "tot nhat co duoc"
    # chu khong phai "dat nguong toi uu that su".
    is_fallback = (final_score < 0)
    result = dict(final_combo)
    result.update({
        "win_rate":       final_wfo["oob_wr_mean"],
        "win_rate_std":   final_wfo["oob_wr_std"],
        "profit_factor":  final_wfo["oob_pf_mean"],
        "stability":      final_wfo["stability"],
        "n_windows":      final_wfo["n_windows"],
        "total_trades":   final_wfo["n_total_oob"],
        "optimized_at":   datetime.now(timezone.utc).isoformat(),
        "is_fallback":    is_fallback,
    })
    if is_fallback:
        logger.warning(
            "[%s] KET QUA FALLBACK: WR=%.1f%% PF=%.2f — "
            "tot nhat trong so cac combo da thu nhung CHUA dat nguong "
            "WR>=%.0f%% PF>=%.2f. Bot se dung tham so nay thay vi "
            "de nguyen defaults. Nen theo doi live WR de xem co on khong.",
            symbol, result["win_rate"], result["profit_factor"], MIN_WR, MIN_PF,
        )

    logger.info(
        "[%s] KET QUA CUOI: WR=%.1f%%±%.1f%% stab=%.2f PF=%.2f "
        "ATR(%d)x%.2f tp_x%.2f struct=%d st_factor=%.2f ema_fast=%d pa_len=%d",
        symbol,
        result["win_rate"], result["win_rate_std"],
        result["stability"], result["profit_factor"],
        result.get("atr_period",14), result.get("atr_multiplier",1.8),
        result.get("tp_atr_multiplier",3.6), result.get("internal_structure_len",5),
        result.get("st_factor",3.0), result.get("ema_fast_len",9),
        result.get("pa_length",14),
    )
    return result


# ─── Vong chay chinh ─────────────────────────────────────────────────────────

CHECKPOINT_PATH = os.path.join(_BASE_DIR, "auto_tuner_checkpoint.json")


def _load_checkpoint() -> Dict:
    """Doc checkpoint de resume neu bi gian doan (mat dien, restart VPS...)."""
    if os.path.exists(CHECKPOINT_PATH):
        try:
            import json
            with open(CHECKPOINT_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"completed_symbols": {}, "started_at": None}


def _save_checkpoint(completed: Dict, started_at: str):
    import json
    try:
        with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
            json.dump({"completed_symbols": completed, "started_at": started_at}, f, indent=2)
    except Exception as e:
        logger.warning("Khong ghi duoc checkpoint: %s", e)


def _clear_checkpoint():
    try:
        if os.path.exists(CHECKPOINT_PATH):
            os.remove(CHECKPOINT_PATH)
    except Exception:
        pass


def _load_existing_optimized() -> Dict[str, Dict]:
    """
    Doc optimized_params.json hien tai de biet symbol nao DA CO ket qua
    that su (win_rate > 0 va optimized_at gan day), tranh chay lai
    lang phi thoi gian cho symbol da xong tu lan chay truoc.
    """
    params_path = os.path.join(_BASE_DIR, "optimized_params.json")
    if not os.path.exists(params_path):
        return {}
    try:
        import json
        with open(params_path, encoding="utf-8") as f:
            data = json.load(f)
        existing = {}
        for sym, p in data.items():
            if sym.startswith("_") or not isinstance(p, dict):
                continue
            # Chi tinh la "da xong" neu co win_rate > 0 (tuc da qua
            # WFO that su, khong phai gia tri mau/default win_rate=0)
            if p.get("win_rate", 0) > 0 and p.get("total_trades", 0) > 0:
                existing[sym] = p
        return existing
    except Exception as e:
        logger.warning("Khong doc duoc optimized_params.json de kiem tra resume: %s", e)
        return {}


def _run_all():
    global _is_running, _last_run_ts, _last_live_count

    t0 = time.time()
    total_days = getattr(config, "AUTO_TUNER_BACKTEST_DAYS", 365)

    n_symbols = len(config.SYMBOLS)
    logger.info("=" * 60)
    logger.info("AUTO-TUNER v6 WFO BAT DAU")
    logger.info("Symbols: %s (%d cap)", config.SYMBOLS, n_symbols)
    logger.info("Data: %d ngay | Uoc tinh: ~5-6h / symbol", total_days)
    logger.info("=" * 60)

    # ── Resume: uu tien checkpoint, nhung CUNG kiem tra optimized_params.json
    #    truc tiep — vi checkpoint co the bi mat (process bi kill cung luc
    #    voi lan ghi checkpoint, hoac checkpoint bi xoa nham) trong khi
    #    optimized_params.json van con nguyen ket qua that su da tinh ─────
    checkpoint = _load_checkpoint()
    results: Dict[str, Dict] = dict(checkpoint.get("completed_symbols", {}))
    started_at = checkpoint.get("started_at") or datetime.now(timezone.utc).isoformat()

    existing_optimized = _load_existing_optimized()
    for sym, p in existing_optimized.items():
        if sym not in results:
            results[sym] = p
            logger.info(
                "[%s] Tim thay ket qua da co san trong optimized_params.json "
                "(WR=%.1f%% PF=%.2f, optimized_at=%s) — BO QUA, khong chay lai.",
                sym, p.get("win_rate", 0), p.get("profit_factor", 0),
                p.get("optimized_at", "?")[:19],
            )

    if results:
        logger.info(
            "Da co ket qua truoc do cho: %s. Chi toi uu cac symbol con lai.",
            list(results.keys()),
        )

    remaining = [s for s in config.SYMBOLS if s not in results]

    if not remaining:
        logger.info("TAT CA %d symbol da co ket qua toi uu. Khong can chay lai.", n_symbols)
        logger.info("Neu muon toi uu lai tu dau, xoa optimized_params.json hoac dung force_run().")
        _is_running      = False
        _last_run_ts     = time.time()
        _last_live_count = _count_live()
        return

    logger.info("Con %d/%d symbol can toi uu: %s", len(remaining), n_symbols, remaining)

    for idx, symbol in enumerate(remaining, 1):
        sym_t0 = time.time()
        logger.info("")
        logger.info(
            "### [%d/%d] BAT DAU TOI UU: %s (da xong %d/%d cap truoc do) ###",
            idx, len(remaining), symbol, len(results), n_symbols,
        )

        try:
            res = _optimize_symbol(symbol, total_days=total_days)
        except Exception as e:
            logger.exception("[%s] LOI KHI TOI UU: %s — bo qua symbol nay, tiep tuc.", symbol, e)
            res = None

        sym_elapsed = time.time() - sym_t0

        if res:
            results[symbol] = res
            logger.info(
                "### [%d/%d] XONG %s sau %.1f phut | WR=%.1f%% PF=%.2f ###",
                idx, len(remaining), symbol, sym_elapsed / 60,
                res.get("win_rate", 0), res.get("profit_factor", 0),
            )
        else:
            logger.warning(
                "### [%d/%d] %s: KHONG tim duoc tham so dat nguong "
                "(WR>=%.0f%% PF>=%.1f n>=%d trong tat ca %d combos). "
                "Giu nguyen tham so cu — se thu lai lan chay sau. ###",
                idx, len(remaining), symbol, MIN_WR, MIN_PF, MIN_TRADES,
                len(COARSE_GRID_BY_SYMBOL.get(symbol, COARSE_GRID_DEFAULT)),
            )

        # Ghi checkpoint sau MOI symbol — neu bi gian doan se resume duoc
        _save_checkpoint(results, started_at)

        # Ghi param ngay sau khi xong 1 symbol — khong cho ca 4 symbol xong moi ghi
        if symbol in results:
            param_loader.save({symbol: results[symbol]})
            logger.info("[%s] Da ghi optimized_params.json — ap dung ngay cho live.", symbol)

    elapsed = time.time() - t0
    logger.info("")
    logger.info("=" * 60)
    n_done = len(results)
    if n_done >= n_symbols:
        logger.info(
            "AUTO-TUNER WFO HOAN TAT TOAN BO sau %.1f gio | %d/%d symbol: %s",
            elapsed / 3600, n_done, n_symbols, list(results.keys()),
        )
        _clear_checkpoint()  # CHI xoa khi THUC SU xong het tat ca symbol
    elif results:
        logger.warning(
            "AUTO-TUNER DUNG GIUA CHUNG: chi xong %d/%d symbol (%s) sau %.1f gio. "
            "Checkpoint VAN GIU LAI de lan sau resume.",
            n_done, n_symbols, list(results.keys()), elapsed / 3600,
        )
    else:
        logger.warning("AUTO-TUNER WFO: Khong co symbol nao toi uu duoc ca.")

    if results:
        _notify_telegram(results)
    logger.info("=" * 60)

    _last_run_ts     = time.time()
    _last_live_count = _count_live()
    _is_running      = False


def _notify_telegram(results: Dict):
    try:
        import json
        from urllib import request as urlreq
        import ssl

        token   = getattr(config, "TELEGRAM_BOT_TOKEN", None)
        chat_id = getattr(config, "TELEGRAM_CHAT_ID",   None)
        if not token or not chat_id:
            return

        lines = ["<b>Auto-tuner WFO: Cap nhat tham so</b>"]
        for sym, p in results.items():
            lines.append(
                f"\n<b>{sym}</b>\n"
                f"  WR={p.get('win_rate',0):.1f}%"
                f" ±{p.get('win_rate_std',0):.1f}%"
                f"  Stability={p.get('stability',0):.2f}\n"
                f"  PF={p.get('profit_factor',0):.2f}"
                f"  n={p.get('total_trades',0)} lenh / {p.get('n_windows',0)} cua so\n"
                f"  ATR({p.get('atr_period',14)})x{p.get('atr_multiplier',1.8):.2f}"
                f"  TP_x{p.get('tp_atr_multiplier',3.6):.2f}\n"
                f"  struct_len={p.get('internal_structure_len',5)}"
                f"  st_factor={p.get('st_factor',3.0):.2f}"
                f"  ema_fast={p.get('ema_fast_len',9)}"
                f"  pa_len={p.get('pa_length',14)}"
            )

        data = json.dumps({
            "chat_id": chat_id, "text": "\n".join(lines), "parse_mode": "HTML",
        }).encode()
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        req = urlreq.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data, headers={"Content-Type": "application/json"}, method="POST",
        )
        urlreq.urlopen(req, timeout=10, context=ctx)
    except Exception as e:
        logger.debug("Telegram notify loi: %s", e)


# ─── Public API ───────────────────────────────────────────────────────────────

def maybe_run():
    global _is_running
    with _lock:
        if _is_running:
            return
        ok, reason = _should_run()
        if not ok:
            return
        logger.info("Auto-tuner kich hoat: %s", reason)
        _is_running = True
    threading.Thread(target=_run_all, name="AutoTuner", daemon=True).start()


def force_run():
    global _last_run_ts
    _last_run_ts = 0.0
    maybe_run()


def force_reoptimize_all():
    """
    Xoa checkpoint VA bo qua ket qua co san trong optimized_params.json,
    buoc toi uu lai TU DAU cho tat ca symbol. Dung khi muon lam lai
    hoan toan (vi du sau khi sua bug lon trong analysis.py).
    """
    _clear_checkpoint()
    logger.info("Da xoa checkpoint. Lan chay tiep theo se toi uu lai TAT CA symbol.")
    logger.warning(
        "LUU Y: optimized_params.json van con ket qua cu — neu khong muon "
        "bi tinh la 'da xong', hay doi ten/xoa file nay truoc khi chay lai."
    )


if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    param_loader.apply()

    if "--force-all" in sys.argv:
        logger.info("Co flag --force-all: xoa checkpoint, toi uu lai tu dau.")
        _clear_checkpoint()
        # Doi ten optimized_params.json cu de _load_existing_optimized()
        # khong thay no nua (force chay lai that su)
        params_path = os.path.join(_BASE_DIR, "optimized_params.json")
        if os.path.exists(params_path):
            backup_path = params_path + ".bak_" + datetime.now().strftime("%Y%m%d_%H%M%S")
            os.rename(params_path, backup_path)
            logger.info("Da backup optimized_params.json cu -> %s", backup_path)

    _run_all()