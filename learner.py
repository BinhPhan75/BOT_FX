"""
learner.py  v3 — Regime-aware + Session-aware + ATR-param aware

Phan tich WR theo 5 chieu:
  1. pattern|direction                (tong hop)
  2. pattern|direction|regime         (chinh - phan biet trending vs ranging)
  3. pattern|direction|session        (phien giao dich)
  4. gio VN (bad hours)
  5. symbol
  6. atr_params: tim bo tham so ATR nao cho WR cao nhat tu DB bt_trades

Xuat signal_weights.json v3 de adaptive_filter.py dung.
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List

logger = logging.getLogger("learner")

_BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
BT_DB_PATH   = os.path.join(_BASE_DIR, "backtest_results.db")
LIVE_DB_PATH = os.path.join(_BASE_DIR, "trades.db")
WEIGHTS_PATH = os.path.join(_BASE_DIR, "signal_weights.json")


# ─── Doc du lieu ─────────────────────────────────────────────────────────────

def _fetch(db_path: str, table: str) -> List[Dict]:
    if not os.path.exists(db_path):
        logger.warning("Khong tim thay DB: %s", db_path)
        return []
    try:
        # timeout=10: cho phep cho toi da 10s neu DB dang bi lock boi
        # process khac (vi du auto_tuner.py dang ghi backtest_results.db
        # song song). Khong co timeout se TREO VO THOI HAN khong bao loi.
        #
        # uri=True + mode=ro: mo o che do READ-ONLY, giam nguy co bi
        # block boi writer khac va khong vo tinh ghi nham vao DB cua
        # process khac dang dung.
        uri_path = f"file:{db_path}?mode=ro"
        with sqlite3.connect(uri_path, uri=True, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]

            def col(name, alias=None, default="NULL"):
                if name in cols:
                    return name if not alias else f"{name} as {alias}"
                return f"{default} as {alias or name}"

            profit_col = "profit_pips" if "profit_pips" in cols else "profit"
            q = f"""
                SELECT symbol, pattern, direction,
                       open_hour_vn,
                       result,
                       {profit_col} as profit_pips,
                       {col('regime')},
                       {col('session')},
                       {col('atr_period')},
                       {col('atr_multiplier')},
                       {col('pivot_lookback')}
                FROM {table}
                WHERE result IN ('WIN','LOSS','TIMEOUT','BREAKEVEN')
            """
            return [dict(r) for r in conn.execute(q).fetchall()]
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            logger.error(
                "DB %s dang bi LOCK boi process khac (co the auto_tuner.py "
                "dang ghi du lieu song song). Doi auto_tuner xong roi chay lai, "
                "hoac dung tam auto_tuner truoc khi chay learner.py.",
                db_path,
            )
        else:
            logger.error("Loi SQL doc %s: %s", db_path, e)
        return []
    except Exception as e:
        logger.error("Loi doc %s: %s", db_path, e)
        return []


def load_all(live_weight: float = 3.0) -> List[Dict]:
    bt   = _fetch(BT_DB_PATH,   "bt_trades")
    live = _fetch(LIVE_DB_PATH, "trades")

    for t in live:
        if not t.get("regime"):   t["regime"]   = "unknown"
        if not t.get("session"):  t["session"]  = "unknown"
        if not t.get("profit_pips"): t["profit_pips"] = t.get("profit", 0)

    logger.info("BT trades: %d | Live trades: %d (x%.0f)", len(bt), len(live), live_weight)
    return bt + live * int(live_weight)


# ─── Win rate helpers ────────────────────────────────────────────────────────

def _wr(trades: List[Dict]):
    n    = len(trades)
    wins = sum(1 for t in trades if t["result"] == "WIN")
    avg  = sum(t.get("profit_pips", 0) for t in trades) / n if n else 0
    return round(wins / n * 100, 1) if n else 0.0, n, wins, round(avg, 1)


# ─── Phan tich ───────────────────────────────────────────────────────────────

def analyze_patterns(trades, min_n):
    g = defaultdict(list)
    for t in trades:
        g[f"{t['pattern']}|{t['direction']}"].append(t)
    return {k: dict(zip(("win_rate","total","wins","avg_pips"), _wr(v)))
            for k, v in g.items() if len(v) >= min_n}


def analyze_by_regime(trades, min_n):
    g = defaultdict(list)
    for t in trades:
        r = t.get("regime") or "unknown"
        if r == "volatile": continue
        g[f"{t['pattern']}|{t['direction']}|{r}"].append(t)
    return {k: dict(zip(("win_rate","total","wins","avg_pips"), _wr(v)))
            for k, v in g.items() if len(v) >= min_n}


def analyze_by_session(trades, min_n):
    g = defaultdict(list)
    for t in trades:
        s = t.get("session") or "unknown"
        if s == "unknown": continue
        g[f"{t['pattern']}|{t['direction']}|{s}"].append(t)
    return {k: dict(zip(("win_rate","total","wins","avg_pips"), _wr(v)))
            for k, v in g.items() if len(v) >= min_n}


def analyze_hours(trades, min_n):
    g = defaultdict(list)
    for t in trades:
        h = t.get("open_hour_vn")
        if h is not None: g[int(h)].append(t)
    result = {}
    for h, lst in g.items():
        wr, n, _, _ = _wr(lst)
        if n >= min_n:
            result[str(h)] = {"win_rate": wr, "total": n}
    return result


def analyze_symbols(trades, min_n):
    g = defaultdict(list)
    for t in trades: g[t["symbol"]].append(t)
    result = {}
    for sym, lst in g.items():
        wr, n, _, _ = _wr(lst)
        if n >= min_n:
            result[sym] = {"win_rate": wr, "total": n}
    return result


def analyze_atr_params(trades, min_n) -> Dict:
    """
    Tim bo (atr_period, atr_multiplier, pivot_lookback) cho WR cao nhat
    per symbol|pattern. Dung de confirm voi optimized_params.json.
    """
    g = defaultdict(list)
    for t in trades:
        ap = t.get("atr_period")
        am = t.get("atr_multiplier")
        pl = t.get("pivot_lookback")
        if ap and am and pl:
            key = f"{t['symbol']}|{t['pattern']}|{t['direction']}|atr{ap}x{am}p{pl}"
            g[key].append(t)

    result = {}
    for key, lst in g.items():
        wr, n, _, avg = _wr(lst)
        if n >= min_n:
            result[key] = {"win_rate": wr, "total": n, "avg_pips": avg}

    # Best params per symbol
    best_by_symbol: Dict[str, Dict] = {}
    for key, s in result.items():
        sym = key.split("|")[0]
        if sym not in best_by_symbol or s["win_rate"] > best_by_symbol[sym]["win_rate"]:
            best_by_symbol[sym] = {**s, "key": key}

    return {"details": result, "best_by_symbol": best_by_symbol}


# ─── Build weights ───────────────────────────────────────────────────────────

def build_weights(
    pat_stats, regime_stats, session_stats,
    hour_stats, sym_stats, atr_stats,
    min_wr_pat, min_wr_hour, min_wr_sym,
) -> Dict:

    # Pattern tong hop
    pat_enabled = {}
    pat_scores  = {}
    for k, s in pat_stats.items():
        enabled = s["win_rate"] >= min_wr_pat and s["avg_pips"] > 0
        pat_enabled[k] = enabled
        pat_scores[k]  = {**s, "enabled": enabled}

    # Regime
    regime_scores = {}
    for k, s in regime_stats.items():
        enabled = s["win_rate"] >= min_wr_pat and s["avg_pips"] > 0
        regime_scores[k] = {**s, "enabled": enabled}

    # Session
    session_scores = {}
    for k, s in session_stats.items():
        enabled = s["win_rate"] >= min_wr_pat and s["avg_pips"] > 0
        session_scores[k] = {**s, "enabled": enabled}

    # Bad hours
    bad_hours   = []
    hour_scores = {}
    for h, s in hour_stats.items():
        avoid = s["win_rate"] < min_wr_hour
        hour_scores[h] = {**s, "avoid": avoid}
        if avoid: bad_hours.append(int(h))

    # Symbol
    sym_enabled = {sym: s["win_rate"] >= min_wr_sym for sym, s in sym_stats.items()}

    return {
        "generated_at":          datetime.now(timezone.utc).isoformat(),
        "version":               "3",
        "config": {
            "min_wr_pattern": min_wr_pat,
            "min_wr_hour":    min_wr_hour,
            "min_wr_symbol":  min_wr_sym,
        },
        "pattern_enabled":        pat_enabled,
        "pattern_scores":         pat_scores,
        "regime_pattern_scores":  regime_scores,
        "session_pattern_scores": session_scores,
        "bad_hours":              sorted(bad_hours),
        "hour_scores":            hour_scores,
        "symbol_enabled":         sym_enabled,
        "atr_param_analysis":     atr_stats.get("best_by_symbol", {}),
    }


# ─── Report ──────────────────────────────────────────────────────────────────

def print_report(w: Dict):
    d = "-" * 60
    print(f"\n{d}")
    print(f"  signal_weights.json v{w.get('version','?')} — {w['generated_at'][:19]}")
    print(d)

    print(f"\n  {'Pattern tong hop':<42} {'WR%':>5} {'Avg':>7} {'N':>6} {'ST'}")
    for k, s in sorted(w["pattern_scores"].items(),
                        key=lambda x: x[1]["win_rate"], reverse=True):
        print(f"  {k:<42} {s['win_rate']:>4.0f}% {s['avg_pips']:>+7.1f} {s['total']:>6} "
              f"{'ON' if s['enabled'] else 'OFF'}")

    rps = w.get("regime_pattern_scores", {})
    if rps:
        print(f"\n  {'Regime-aware':<48} {'WR%':>5} {'N':>6}")
        for k, s in sorted(rps.items(), key=lambda x: x[1]["win_rate"], reverse=True)[:15]:
            print(f"  {k:<48} {s['win_rate']:>4.0f}% {s['total']:>6} "
                  f"{'ON' if s['enabled'] else 'OFF'}")

    print(f"\n  Bad hours: {w['bad_hours']}")
    print(f"\n  Symbol: {w['symbol_enabled']}")

    atr = w.get("atr_param_analysis", {})
    if atr:
        print(f"\n  ATR params tot nhat tu DB:")
        for sym, info in atr.items():
            print(f"    {sym}: {info.get('key','?')} — WR={info.get('win_rate','?')}%")

    print(d)


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-trades",        type=int,   default=20)
    parser.add_argument("--min-wr",            type=float, default=38.0)
    parser.add_argument("--min-wr-hour",       type=float, default=30.0)
    parser.add_argument("--min-wr-symbol",     type=float, default=28.0)
    parser.add_argument("--min-trades-hour",   type=int,   default=30)
    parser.add_argument("--min-trades-regime", type=int,   default=15)
    parser.add_argument("--live-weight",       type=float, default=3.0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    logger.info("learner.py bat dau...")
    logger.info("Tham so: min_trades=%d min_wr=%.0f%% min_wr_hour=%.0f%% "
                "min_wr_symbol=%.0f%% live_weight=%.1f",
                args.min_trades, args.min_wr, args.min_wr_hour,
                args.min_wr_symbol, args.live_weight)
    logger.info("Doc backtest_results.db (%s)...", BT_DB_PATH)

    trades = load_all(live_weight=args.live_weight)
    if not trades:
        logger.error("Khong co du lieu. Chay backtest truoc.")
        sys.exit(1)

    logger.info("Tong trades de hoc: %d", len(trades))

    pat_stats     = analyze_patterns(trades,   args.min_trades)
    regime_stats  = analyze_by_regime(trades,  args.min_trades_regime)
    session_stats = analyze_by_session(trades, args.min_trades_regime)
    hour_stats    = analyze_hours(trades,      args.min_trades_hour)
    sym_stats     = analyze_symbols(trades,    args.min_trades)
    atr_stats     = analyze_atr_params(trades, args.min_trades_regime)

    weights = build_weights(
        pat_stats, regime_stats, session_stats,
        hour_stats, sym_stats, atr_stats,
        args.min_wr, args.min_wr_hour, args.min_wr_symbol,
    )

    with open(WEIGHTS_PATH, "w", encoding="utf-8") as f:
        json.dump(weights, f, ensure_ascii=False, indent=2)

    print_report(weights)
    logger.info("Da luu -> %s", WEIGHTS_PATH)


if __name__ == "__main__":
    main()