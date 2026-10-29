"""
backtest_engine.py  v4 — Regime-aware, Dynamic params, ATR-based SL/TP

Thay doi so voi v3:
  - _calc_sl_tp dong: doc atr_period, atr_multiplier tu param (truyen vao)
    thay vi dung buf_pct co dinh — dong bo chinh xac voi trader.py
  - Ghi them cac cot: regime, session, adx_value, atr_period, atr_multiplier,
    pivot_lookback, sl_atr_dist (SL tinh bang ATR de learner phan tich)
  - run_backtest nhan them tham so params={} de auto_tuner truyen vao
    khi chay grid search — khong can thay doi config global
  - Thong ke per-pattern va per-regime in ra cuoi moi run
"""

import argparse
import logging
import os
import sqlite3
import statistics
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

import config
import analysis
import trend_filter
import market_regime
import param_loader
from data_loader import load_candles_multi, get_htf_candles_at

logger = logging.getLogger("backtest")

_BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
BT_DB_PATH = os.path.join(_BASE_DIR, "backtest_results.db")


# ─── DB init / migrate ────────────────────────────────────────────────────────

def init_bt_db():
    conn = sqlite3.connect(BT_DB_PATH)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bt_trades (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id          TEXT,
                symbol          TEXT,
                timeframe       TEXT,
                pattern         TEXT,
                direction       TEXT,
                htf_trend       TEXT,
                volume_ratio    REAL,
                entry_price     REAL,
                sl              REAL,
                tp              REAL,
                rr_ratio        REAL,
                sl_buf_pct      REAL,
                open_time       TEXT,
                open_hour_vn    INTEGER,
                close_time      TEXT,
                close_price     REAL,
                profit_pips     REAL,
                result          TEXT,
                close_reason    TEXT,
                regime          TEXT,
                session         TEXT,
                adx_value       REAL,
                atr_period      INTEGER,
                atr_multiplier  REAL,
                pivot_lookback  INTEGER,
                sl_atr_dist     REAL
            )
        """)
        conn.commit()

        # Migrate DB cu
        for col, ctype in [
            ("regime","TEXT"), ("session","TEXT"), ("adx_value","REAL"),
            ("atr_period","INTEGER"), ("atr_multiplier","REAL"),
            ("pivot_lookback","INTEGER"), ("sl_atr_dist","REAL"),
        ]:
            try:
                conn.execute(f"ALTER TABLE bt_trades ADD COLUMN {col} {ctype}")
                conn.commit()
            except sqlite3.OperationalError:
                pass

        conn.execute("""
            CREATE TABLE IF NOT EXISTS bt_runs (
                run_id          TEXT PRIMARY KEY,
                symbol          TEXT,
                timeframe       TEXT,
                days            INTEGER,
                total_signals   INTEGER,
                total_trades    INTEGER,
                wins            INTEGER,
                losses          INTEGER,
                timeouts        INTEGER,
                win_rate        REAL,
                avg_profit      REAL,
                profit_factor   REAL,
                atr_period      INTEGER,
                atr_multiplier  REAL,
                pivot_lookback  INTEGER,
                ran_at          TEXT
            )
        """)
        conn.commit()

        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_bt_pattern ON bt_trades(pattern)",
            "CREATE INDEX IF NOT EXISTS idx_bt_symbol  ON bt_trades(symbol)",
            "CREATE INDEX IF NOT EXISTS idx_bt_regime  ON bt_trades(regime)",
            "CREATE INDEX IF NOT EXISTS idx_bt_session ON bt_trades(session)",
            "CREATE INDEX IF NOT EXISTS idx_bt_run     ON bt_trades(run_id)",
        ]:
            try:
                conn.execute(idx_sql)
            except sqlite3.OperationalError:
                pass
        conn.commit()
    finally:
        conn.close()
    logger.info("Backtest DB: %s", BT_DB_PATH)


# ─── Helpers ──────────────────────────────────────────────────────────────────

# v5: pattern tu smc_indicator.py (BOS/CHoCH) — dong bo voi trader.py
# v7: pattern tu 5 nhom tin hieu doc lap (OR logic) — dong bo voi trader.py
BULLISH = {"smc_bullish_bos", "smc_bullish_choch",
           "st_flip_bullish", "ema_cross_bullish", "price_action_bullish"}
BEARISH = {"smc_bearish_bos", "smc_bearish_choch",
           "st_flip_bearish", "ema_cross_bearish", "price_action_bearish"}

def _direction(pattern: str) -> Optional[str]:
    if pattern in BULLISH: return "BUY"
    if pattern in BEARISH: return "SELL"
    return None


def _get_session(hour_utc: int) -> str:
    if 0  <= hour_utc < 7:  return "asia"
    if 7  <= hour_utc < 12: return "london"
    if 12 <= hour_utc < 17: return "london_ny"
    if 17 <= hour_utc < 21: return "ny"
    return "off"


def _calc_atr(candles: list, period: int = 14) -> float:
    if len(candles) < period + 1:
        return statistics.mean(c["high"] - c["low"] for c in candles) if candles else 0.0
    trs = []
    for i in range(1, len(candles)):
        h  = candles[i]["high"]; l = candles[i]["low"]
        pc = candles[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return statistics.mean(trs[-period:])


def _calc_sl_tp_dynamic(
    direction: str,
    entry: float,
    zone_price: float,
    candles_context: list,
    symbol: str,
    rr_ratio: float,
    atr_period: int,
    atr_multiplier: float,
    tp_atr_multiplier: float = None,
    max_sl_atr_mult: float = None,
) -> tuple:
    """
    Tinh SL/TP bang ATR dong — dong bo chinh xac voi trader.py (v9).

    TP tinh DOC LAP theo `tp_atr_multiplier` (khong con la boi so cung
    cua SL qua rr_ratio nua). SL bi GIOI HAN toi da `max_sl_atr_mult` lan
    ATR buffer tinh tu entry — tranh zone_price/anchor keo SL qua xa so
    voi TP (da gap: EURUSD/GBPUSD RR≈0.5 thay vi dung ty le
    tp_atr_multiplier/atr_multiplier toi uu, vi zone qua xa entry).

    Tra ve (sl, tp, atr_value, sl_atr_dist).
    """
    atr = _calc_atr(candles_context, period=atr_period)
    atr_buf = atr * atr_multiplier
    if tp_atr_multiplier is None:
        tp_atr_multiplier = atr_multiplier * rr_ratio  # fallback tuong duong hanh vi cu
    tp_buf = atr * tp_atr_multiplier
    if max_sl_atr_mult is None:
        max_sl_atr_mult = 1.5

    buf_cfg = getattr(config, "SL_BUFFER_PERCENT", {})
    buf_pct = (buf_cfg.get(symbol, getattr(config, "SL_BUFFER_PERCENT_DEFAULT", 0.06))
               if isinstance(buf_cfg, dict) else float(buf_cfg))
    fixed_buf = zone_price * buf_pct / 100

    tp_buf_cfg = getattr(config, "TP_BUFFER_PERCENT", {})
    tp_buf_pct = (tp_buf_cfg.get(symbol, getattr(config, "TP_BUFFER_PERCENT_DEFAULT", 0.06))
                  if isinstance(tp_buf_cfg, dict) else float(tp_buf_cfg))
    fixed_tp_buf = entry * tp_buf_pct / 100

    buf = max(atr_buf, fixed_buf)
    tp_buf = max(tp_buf, fixed_tp_buf)

    # Cap MAX_SL_USD
    max_sl_cfg = getattr(config, "MAX_SL_USD", {})
    max_sl_def = getattr(config, "MAX_SL_USD_DEFAULT", None)
    max_sl = (max_sl_cfg.get(symbol, max_sl_def) if isinstance(max_sl_cfg, dict)
              else max_sl_cfg or max_sl_def)
    if max_sl and buf > max_sl:
        buf = max_sl

    max_sl_from_entry = buf * max_sl_atr_mult
    tp_sl_ratio = tp_atr_multiplier / atr_multiplier if atr_multiplier > 0 else 1.0

    last = candles_context[-1] if candles_context else {}
    if direction == "BUY":
        anchor = last.get("low", zone_price)
        zone_sl = min(zone_price, anchor) - buf
        sl_dist = min(entry - zone_sl, max_sl_from_entry)
        sl = entry - sl_dist
        tp_dist = max(sl_dist * tp_sl_ratio, tp_buf)
        tp = entry + tp_dist
    else:
        anchor = last.get("high", zone_price)
        zone_sl = max(zone_price, anchor) + buf
        sl_dist = min(zone_sl - entry, max_sl_from_entry)
        sl = entry + sl_dist
        tp_dist = max(sl_dist * tp_sl_ratio, tp_buf)
        tp = entry - tp_dist

    sl_atr_dist = abs(entry - sl) / atr if atr > 0 else 0.0
    return sl, tp, atr, sl_atr_dist


def _simulate_trade(
    candles_future: List[Dict],
    direction: str,
    entry: float,
    sl: float,
    tp: float,
    max_candles: int = 100,
) -> tuple:
    """Conservative: neu cung nen cham ca SL va TP → tinh la LOSS."""
    for i, c in enumerate(candles_future[:max_candles]):
        if direction == "BUY":
            if c["low"] <= sl:  return "LOSS", sl, c["time"], i + 1
            if c["high"] >= tp: return "WIN",  tp, c["time"], i + 1
        else:
            if c["high"] >= sl: return "LOSS", sl, c["time"], i + 1
            if c["low"] <= tp:  return "WIN",  tp, c["time"], i + 1
    last = candles_future[min(max_candles - 1, len(candles_future) - 1)]
    return "TIMEOUT", last["close"], last["time"], max_candles


def _get_point(symbol: str, entry: float) -> float:
    """Uoc tinh point size tu gia."""
    if entry > 100: return 0.01   # XAUUSD, USDJPY
    return 0.00001                 # EURUSD, GBPUSD


# ─── Engine chinh ─────────────────────────────────────────────────────────────

def run_backtest(
    symbol: str,
    timeframe: str,
    days: int = 365,
    rr_ratio: float = None,
    use_htf: bool = True,
    max_candles_timeout: int = 100,
    use_cache: bool = True,
    params: Dict = None,
    offset_days: int = 0,
) -> Dict:
    """
    offset_days: bo qua N ngay cuoi (dung cho WFO test windows).
    offset_days=0 → backtest tu (now - days) den now (mac dinh).
    offset_days=30 → backtest tu (now - 30 - days) den (now - 30).
    """
    """
    Chay backtest cho 1 symbol.

    params: override tham so dong (tu auto_tuner grid search).
    Neu None, doc tu param_loader (file optimized_params.json).

    Tra ve dict thong ke.
    """
    rr_ratio = rr_ratio or getattr(config, "DEFAULT_RR_RATIO", 2.0)
    htf_tf   = config.HTF_TIMEFRAME if use_htf else None

    # ── Lay tham so dong ─────────────────────────────────────────────────────
    if params:
        atr_period     = int(params.get("atr_period",     14))
        atr_multiplier = float(params.get("atr_multiplier", 1.8))
        pivot_lookback = int(params.get("pivot_lookback",  7))  # legacy, khong con dung boi analysis.py
    else:
        atr_period     = int(param_loader.get_param(symbol, "atr_period",     14))
        atr_multiplier = float(param_loader.get_param(symbol, "atr_multiplier", 1.8))
        pivot_lookback = int(param_loader.get_param(symbol, "pivot_lookback",  7))

    # Tham so v7 dang duoc dung THUC SU cho lan backtest nay — lay tu
    # `params` (combo dang test) neu co, nguoc lai tu param_loader (default/JSON).
    # In day du de co the XAC MINH bang mat auto_tuner co dang xoay dung
    # tham so moi hay khong (thay vi chi thay ATR/pivot cu, gay hieu nham).
    _smc = dict(params) if params else {}
    _struct_len = _smc.get("internal_structure_len", param_loader.get_param(symbol, "internal_structure_len", 5))
    _st_factor  = _smc.get("st_factor", param_loader.get_param(symbol, "st_factor", 3.0))
    _ema_fast   = _smc.get("ema_fast_len", param_loader.get_param(symbol, "ema_fast_len", 9))
    _pa_len     = _smc.get("pa_length", param_loader.get_param(symbol, "pa_length", 14))

    logger.info(
        "=== Backtest %s %s | %d ngay | offset=%d | R:R=1:%.1f | "
        "ATR(%d)x%.2f | struct=%s st_factor=%.2f ema_fast=%s pa_len=%s ===",
        symbol, timeframe, days, offset_days, rr_ratio, atr_period, atr_multiplier,
        _struct_len, float(_st_factor), _ema_fast, _pa_len,
    )

    # ── Tai du lieu ───────────────────────────────────────────────────────────
    # Can tai days + offset_days ngay de sau khi cat offset van con du data
    total_load_days = days + offset_days + 5  # +5 buffer
    data = load_candles_multi(
        symbols=[symbol], timeframe=timeframe,
        htf_timeframe=htf_tf, days=total_load_days, use_cache=use_cache,
    )
    candles_all = data[symbol][timeframe]
    htf_all     = data[symbol].get(htf_tf, []) if htf_tf else []

    # Cat theo offset_days: bo phan CUOI (gan nhat) di
    # offset=30 → bot qua 30 ngay cuoi, chi lay data truoc do
    #
    # QUAN TRONG: khong dung gia dinh "96 nen/ngay" (24h lien tuc) vi forex
    # dong cua T7-CN → thuc te chi ~64 nen M15/ngay, ~16 nen H1/ngay (trung binh).
    # Phai tinh ty le THUC TE tu chinh du lieu da tai de cat dung vi tri.
    if offset_days > 0:
        total_m15 = len(candles_all)
        total_h1  = len(htf_all) if htf_all else 0

        # Ty le nen/ngay thuc te (dua tren total_load_days da tai)
        m15_per_day = total_m15 / total_load_days if total_load_days > 0 else 96
        h1_per_day  = total_h1  / total_load_days if total_load_days > 0 and total_h1 > 0 else 24

        m15_keep  = int(days * m15_per_day)
        m15_drop  = int(offset_days * m15_per_day)
        h1_keep   = int(days * h1_per_day)
        h1_drop   = int(offset_days * h1_per_day)

        end_m15   = total_m15 - m15_drop
        start_m15 = max(0, end_m15 - m15_keep * 2)  # lay rong hon de du pivot

        if end_m15 > config.BARS_COUNT + 10:
            candles_all = candles_all[start_m15:end_m15]
        else:
            logger.warning(
                "Khong du nen sau offset: end_m15=%d (total=%d, m15_drop=%d, "
                "m15_per_day=%.1f, offset=%d, days=%d)",
                end_m15, total_m15, m15_drop, m15_per_day, offset_days, days,
            )
            return {}

        if htf_all and total_h1 > 0:
            end_h1   = total_h1 - h1_drop
            start_h1 = max(0, end_h1 - h1_keep * 2)
            if end_h1 > 20:
                htf_all = htf_all[start_h1:end_h1]
            else:
                htf_all = []  # khong du HTF, bo qua filter HTF cho window nay

    if len(candles_all) < config.BARS_COUNT + 10:
        logger.warning("Khong du nen: %d (can %d)", len(candles_all), config.BARS_COUNT + 10)
        return {}

    logger.info("Nen M15: %d | HTF: %d | window=[offset=%d, days=%d]",
                len(candles_all), len(htf_all), offset_days, days)

    init_bt_db()
    run_id = (datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
              + f"_{symbol}_atr{atr_period}x{atr_multiplier}_p{pivot_lookback}")

    VN_OFFSET  = 7 * 3600
    dedupe_secs = getattr(config, "DEDUPE_MINUTES", 30) * 60

    # Dua TOAN BO combo tham so (params) vao param_loader NHUNG CHI cho
    # THREAD hien tai (thread-local) — khong anh huong thread live
    # (watcher.py) dang doc param_loader song song. Xem ghi chu trong
    # param_loader.set_thread_override().
    override_params = dict(params) if params else {
        "atr_period":     atr_period,
        "atr_multiplier": atr_multiplier,
        "pivot_lookback": pivot_lookback,
    }
    param_loader.set_thread_override(symbol, override_params)

    try:
        total_signals = 0
        trades: list  = []
        skip_until    = 0
        last_signal_time: Dict[str, int] = {}
        start_idx = max(config.BARS_COUNT, config.HTF_BARS_COUNT)

        for i in range(start_idx, len(candles_all) - 1):
            window  = candles_all[max(0, i - config.BARS_COUNT + 1): i + 1]
            current = candles_all[i]
            ts      = current["time"]

            if ts < skip_until:
                continue

            # ── Regime filter ─────────────────────────────────────────────
            regime_result = market_regime.get_regime(window, symbol)
            if regime_result.regime == market_regime.REGIME_VOLATILE:
                continue

            # ── HTF trend ─────────────────────────────────────────────────
            htf_trend = "neutral"
            if htf_all:
                htf_window = get_htf_candles_at(htf_all, ts, count=config.HTF_BARS_COUNT)
                if len(htf_window) >= 20:
                    htf_res   = trend_filter.get_trend(htf_window, htf_tf)
                    htf_trend = htf_res.trend

            # ── Pattern detection ─────────────────────────────────────────
            signal = analysis.analyze(window, symbol, timeframe)
            if not signal:
                continue

            total_signals += 1
            direction = _direction(signal.pattern)
            if direction is None:
                continue

            # ── Regime suitability ────────────────────────────────────────
            suitable, _ = market_regime.is_pattern_suitable(signal.pattern, regime_result)
            if not suitable:
                continue

            # ── HTF filter ────────────────────────────────────────────────
            if htf_all and not trend_filter.is_confirmed_by_trend(signal.pattern, htf_trend):
                continue

            # ── Dedup ─────────────────────────────────────────────────────
            last_st = last_signal_time.get(signal.pattern, 0)
            if ts - last_st < dedupe_secs:
                continue
            last_signal_time[signal.pattern] = ts

            entry = current["close"]

            # ── SL/TP dong ────────────────────────────────────────────────
            tp_atr_multiplier = float(
                (params or {}).get("tp_atr_multiplier",
                 param_loader.get_param(symbol, "tp_atr_multiplier", atr_multiplier * rr_ratio))
            )
            max_sl_atr_mult = float(
                (params or {}).get("max_sl_atr_mult",
                 param_loader.get_param(symbol, "max_sl_atr_mult", 1.5))
            )
            sl, tp, atr_val, sl_atr_dist = _calc_sl_tp_dynamic(
                direction, entry, signal.zone_price,
                signal.candles_context, symbol, rr_ratio,
                atr_period, atr_multiplier, tp_atr_multiplier, max_sl_atr_mult,
            )

            # MIN_SL check
            point     = _get_point(symbol, entry)
            sl_points = abs(entry - sl) / point if point else 0
            min_sl_cfg = getattr(config, "MIN_SL_POINTS", {})
            min_sl_def = getattr(config, "MIN_SL_POINTS_DEFAULT", 30)
            min_sl = (min_sl_cfg.get(symbol, min_sl_def)
                      if isinstance(min_sl_cfg, dict) else min_sl_def)
            if sl_points < min_sl:
                continue

            # ── Simulate ──────────────────────────────────────────────────
            future = candles_all[i + 1:]
            result, close_price, close_time, held = _simulate_trade(
                future, direction, entry, sl, tp, max_candles_timeout
            )

            if result == "WIN":
                profit_pips = abs(tp - entry) / point
            elif result == "LOSS":
                profit_pips = -abs(entry - sl) / point
            else:
                profit_pips = ((close_price - entry) / point if direction == "BUY"
                               else (entry - close_price) / point)

            open_dt   = datetime.fromtimestamp(ts, tz=timezone.utc)
            close_dt  = datetime.fromtimestamp(close_time, tz=timezone.utc)
            open_hour = (ts + VN_OFFSET) % 86400 // 3600

            buf_cfg   = getattr(config, "SL_BUFFER_PERCENT", {})
            sl_buf_pct = (buf_cfg.get(symbol, 0.06) if isinstance(buf_cfg, dict)
                          else float(buf_cfg))

            trades.append({
                "run_id":         run_id,
                "symbol":         symbol,
                "timeframe":      timeframe,
                "pattern":        signal.pattern,
                "direction":      direction,
                "htf_trend":      htf_trend,
                "volume_ratio":   signal.volume_ratio,
                "entry_price":    entry,
                "sl":             round(sl, 5),
                "tp":             round(tp, 5),
                "rr_ratio":       rr_ratio,
                "sl_buf_pct":     sl_buf_pct,
                "open_time":      open_dt.isoformat(),
                "open_hour_vn":   open_hour,
                "close_time":     close_dt.isoformat(),
                "close_price":    round(close_price, 5),
                "profit_pips":    round(profit_pips, 1),
                "result":         result,
                "close_reason":   ("TP" if result == "WIN" else
                                   "SL" if result == "LOSS" else "TIMEOUT"),
                "regime":         regime_result.regime,
                "session":        _get_session(open_dt.hour),
                "adx_value":      regime_result.adx,
                "atr_period":     atr_period,
                "atr_multiplier": atr_multiplier,
                "pivot_lookback": pivot_lookback,
                "sl_atr_dist":    round(sl_atr_dist, 2),
            })

            skip_until = ts + dedupe_secs
            icon = "W" if result == "WIN" else "L" if result == "LOSS" else "T"
            logger.debug(
                "[%s] %s %s @%.4f SL=%.4f TP=%.4f | regime=%s | pips=%.1f",
                icon, signal.pattern, direction, entry, sl, tp,
                regime_result.regime, profit_pips,
            )

    finally:
        # Xoa thread-local override — khong dung toi bien toan cum _params
        # nua nen khong con nguy co anh huong thread live.
        param_loader.clear_thread_override(symbol)

    # ── Ghi DB ───────────────────────────────────────────────────────────────
    if trades:
        conn = sqlite3.connect(BT_DB_PATH)
        try:
            conn.executemany("""
                INSERT INTO bt_trades
                (run_id,symbol,timeframe,pattern,direction,htf_trend,volume_ratio,
                 entry_price,sl,tp,rr_ratio,sl_buf_pct,open_time,open_hour_vn,
                 close_time,close_price,profit_pips,result,close_reason,
                 regime,session,adx_value,atr_period,atr_multiplier,
                 pivot_lookback,sl_atr_dist)
                VALUES
                (:run_id,:symbol,:timeframe,:pattern,:direction,:htf_trend,:volume_ratio,
                 :entry_price,:sl,:tp,:rr_ratio,:sl_buf_pct,:open_time,:open_hour_vn,
                 :close_time,:close_price,:profit_pips,:result,:close_reason,
                 :regime,:session,:adx_value,:atr_period,:atr_multiplier,
                 :pivot_lookback,:sl_atr_dist)
            """, trades)
            conn.commit()
        finally:
            conn.close()

    # ── Thong ke ─────────────────────────────────────────────────────────────
    wins     = [t for t in trades if t["result"] == "WIN"]
    losses   = [t for t in trades if t["result"] == "LOSS"]
    timeouts = [t for t in trades if t["result"] == "TIMEOUT"]
    n        = len(trades)
    win_rate  = len(wins) / n * 100 if n else 0
    avg_profit = sum(t["profit_pips"] for t in trades) / n if n else 0
    gross_win  = sum(t["profit_pips"] for t in wins)
    gross_loss = abs(sum(t["profit_pips"] for t in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")

    stats = {
        "run_id":         run_id,
        "symbol":         symbol,
        "timeframe":      timeframe,
        "days":           days,
        "total_signals":  total_signals,
        "total_trades":   n,
        "wins":           len(wins),
        "losses":         len(losses),
        "timeouts":       len(timeouts),
        "win_rate":       round(win_rate, 1),
        "avg_profit":     round(avg_profit, 1),
        "profit_factor":  round(pf, 2),
        "atr_period":     atr_period,
        "atr_multiplier": atr_multiplier,
        "pivot_lookback": pivot_lookback,
    }

    conn = sqlite3.connect(BT_DB_PATH)
    try:
        conn.execute("""
            INSERT OR REPLACE INTO bt_runs
            (run_id,symbol,timeframe,days,total_signals,total_trades,
             wins,losses,timeouts,win_rate,avg_profit,profit_factor,
             atr_period,atr_multiplier,pivot_lookback,ran_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            run_id, symbol, timeframe, days,
            total_signals, n, len(wins), len(losses), len(timeouts),
            win_rate, avg_profit, pf,
            atr_period, atr_multiplier, pivot_lookback,
            datetime.now(timezone.utc).isoformat(),
        ))
        conn.commit()
    finally:
        conn.close()

    return stats


# ─── Print report ─────────────────────────────────────────────────────────────

def print_report(stats: Dict, symbol: str):
    if not stats:
        return
    d = "-" * 56
    print(f"\n{d}")
    print(f"  {stats['symbol']} {stats['timeframe']} ({stats['days']} ngay)")
    print(f"  ATR({stats['atr_period']}) x {stats['atr_multiplier']} | pivot={stats['pivot_lookback']}")
    print(d)
    print(f"  Tin hieu  : {stats['total_signals']}")
    print(f"  Lenh      : {stats['total_trades']}")
    print(f"  WIN/LOSS/T: {stats['wins']}/{stats['losses']}/{stats['timeouts']}")
    print(f"  Win rate  : {stats['win_rate']}%")
    print(f"  Avg pips  : {stats['avg_profit']:+.1f}")
    print(f"  PF        : {stats['profit_factor']:.2f}")

    conn = sqlite3.connect(BT_DB_PATH)
    try:
        rows = conn.execute("""
            SELECT pattern, direction,
                   COUNT(*) t,
                   SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) w,
                   ROUND(AVG(profit_pips),1) ap
            FROM bt_trades WHERE run_id=? AND symbol=?
            GROUP BY pattern,direction ORDER BY w*1.0/t DESC
        """, (stats["run_id"], symbol)).fetchall()
        if rows:
            print(f"\n  {'Pattern':<30} {'Dir':<5} {'N':>5} {'WR%':>5} {'Avg':>7}")
            for r in rows:
                wr = r[3]/r[2]*100 if r[2] else 0
                print(f"  {r[0]:<30} {r[1]:<5} {r[2]:>5} {wr:>4.0f}% {r[4]:>+7.1f}")

        regime_rows = conn.execute("""
            SELECT regime, COUNT(*) t,
                   SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) w,
                   ROUND(AVG(adx_value),1) adx
            FROM bt_trades WHERE run_id=? AND symbol=?
            GROUP BY regime ORDER BY w*1.0/t DESC
        """, (stats["run_id"], symbol)).fetchall()
        if regime_rows:
            print(f"\n  {'Regime':<12} {'N':>6} {'WR%':>5} {'ADX avg':>8}")
            for r in regime_rows:
                wr = r[2]/r[1]*100 if r[1] else 0
                print(f"  {(r[0] or 'unknown'):<12} {r[1]:>6} {wr:>4.0f}% {r[3]:>8.1f}")

        hours = conn.execute("""
            SELECT open_hour_vn, COUNT(*) t,
                   SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) w
            FROM bt_trades WHERE run_id=? AND symbol=?
            GROUP BY open_hour_vn ORDER BY open_hour_vn
        """, (stats["run_id"], symbol)).fetchall()
        if hours:
            print(f"\n  Gio (GMT+7):")
            for h in hours:
                wr = h[2]/h[1]*100 if h[1] else 0
                bar = "#" * int(wr/10) + "." * (10 - int(wr/10))
                print(f"  {h[0]:02d}h [{bar}] {wr:4.0f}% ({h[1]} lenh)")
    finally:
        conn.close()

    print(d)
    print(f"  Chi tiet -> {BT_DB_PATH}")
    print(d)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol",    default="XAUUSD")
    parser.add_argument("--timeframe", default="M15")
    parser.add_argument("--days",      type=int,   default=365)
    parser.add_argument("--rr",        type=float, default=None)
    parser.add_argument("--no-htf",    action="store_true")
    parser.add_argument("--no-cache",  action="store_true")
    parser.add_argument("--verbose",   action="store_true")
    parser.add_argument("--all",       action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    symbols = config.SYMBOLS if args.all else [args.symbol]
    for sym in symbols:
        stats = run_backtest(
            symbol=sym, timeframe=args.timeframe, days=args.days,
            rr_ratio=args.rr, use_htf=not args.no_htf,
            use_cache=not args.no_cache,
        )
        print_report(stats, sym)


if __name__ == "__main__":
    main()