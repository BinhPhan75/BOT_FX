"""Scratch script to analyze bot performance from backtest DB."""
import sqlite3
import os
import json

db = "backtest_results.db"
print(f"DB Size: {os.path.getsize(db)/1024/1024:.1f}MB")

conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

# Recent runs
runs = conn.execute("SELECT * FROM bt_runs ORDER BY ran_at DESC LIMIT 30").fetchall()
print(f"\n{'='*80}")
print(f"RECENT BACKTEST RUNS ({len(runs)} total)")
print(f"{'='*80}")
for r in runs:
    print(f"  {r['symbol']:8s} TF={r['timeframe']} days={r['days']:3d} "
          f"signals={r['total_signals']:4d} trades={r['total_trades']:4d} "
          f"W/L/T={r['wins']}/{r['losses']}/{r['timeouts']} "
          f"WR={r['win_rate']:5.1f}% PF={r['profit_factor']:5.2f} "
          f"ATR({r['atr_period']})x{r['atr_multiplier']}")

# Aggregate by symbol
print(f"\n{'='*80}")
print("AGGREGATE BY SYMBOL (all bt_trades)")
print(f"{'='*80}")
rows = conn.execute("""
    SELECT symbol,
           COUNT(*) as total,
           SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins,
           SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) as losses,
           SUM(CASE WHEN result='TIMEOUT' THEN 1 ELSE 0 END) as timeouts,
           ROUND(AVG(profit_pips),1) as avg_pips,
           ROUND(SUM(CASE WHEN result='WIN' THEN profit_pips ELSE 0 END) /
                 NULLIF(ABS(SUM(CASE WHEN result='LOSS' THEN profit_pips ELSE 0 END)),0), 2) as pf
    FROM bt_trades
    GROUP BY symbol
""").fetchall()
for r in rows:
    wr = r['wins']/r['total']*100 if r['total'] else 0
    print(f"  {r['symbol']:8s} total={r['total']:5d} W={r['wins']:4d} L={r['losses']:4d} "
          f"T={r['timeouts']:4d} WR={wr:5.1f}% PF={r['pf'] or 0:5.2f} avg_pips={r['avg_pips']:+.1f}")

# By pattern
print(f"\n{'='*80}")
print("BY PATTERN (all symbols)")
print(f"{'='*80}")
rows = conn.execute("""
    SELECT pattern, direction,
           COUNT(*) as total,
           SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins,
           ROUND(AVG(profit_pips),1) as avg_pips
    FROM bt_trades
    GROUP BY pattern, direction
    ORDER BY COUNT(*) DESC
""").fetchall()
for r in rows:
    wr = r['wins']/r['total']*100 if r['total'] else 0
    print(f"  {r['pattern']:30s} {r['direction']:4s} n={r['total']:5d} "
          f"WR={wr:5.1f}% avg={r['avg_pips']:+7.1f}")

# By pattern + symbol
print(f"\n{'='*80}")
print("BY PATTERN + SYMBOL (top 30 by count)")
print(f"{'='*80}")
rows = conn.execute("""
    SELECT symbol, pattern, direction,
           COUNT(*) as total,
           SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins,
           SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) as losses,
           ROUND(AVG(profit_pips),1) as avg_pips,
           ROUND(SUM(CASE WHEN result='WIN' THEN profit_pips ELSE 0 END) /
                 NULLIF(ABS(SUM(CASE WHEN result='LOSS' THEN profit_pips ELSE 0 END)),0), 2) as pf
    FROM bt_trades
    GROUP BY symbol, pattern, direction
    ORDER BY COUNT(*) DESC
    LIMIT 30
""").fetchall()
for r in rows:
    wr = r['wins']/r['total']*100 if r['total'] else 0
    print(f"  {r['symbol']:8s} {r['pattern']:28s} {r['direction']:4s} "
          f"n={r['total']:4d} W={r['wins']:3d} L={r['losses']:3d} "
          f"WR={wr:5.1f}% PF={r['pf'] or 0:5.2f} avg={r['avg_pips']:+7.1f}")

# By regime
print(f"\n{'='*80}")
print("BY REGIME")
print(f"{'='*80}")
rows = conn.execute("""
    SELECT regime, symbol,
           COUNT(*) as total,
           SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins,
           ROUND(AVG(adx_value),1) as avg_adx,
           ROUND(AVG(profit_pips),1) as avg_pips
    FROM bt_trades
    WHERE regime IS NOT NULL
    GROUP BY regime, symbol
    ORDER BY regime, symbol
""").fetchall()
for r in rows:
    wr = r['wins']/r['total']*100 if r['total'] else 0
    print(f"  {r['regime'] or 'unknown':10s} {r['symbol']:8s} n={r['total']:4d} "
          f"WR={wr:5.1f}% ADX={r['avg_adx']:5.1f} avg_pips={r['avg_pips']:+7.1f}")

# By close_reason
print(f"\n{'='*80}")
print("BY CLOSE REASON")
print(f"{'='*80}")
rows = conn.execute("""
    SELECT close_reason, symbol,
           COUNT(*) as total,
           ROUND(AVG(profit_pips),1) as avg_pips
    FROM bt_trades
    GROUP BY close_reason, symbol
    ORDER BY close_reason, symbol
""").fetchall()
for r in rows:
    print(f"  {r['close_reason'] or 'NULL':8s} {r['symbol']:8s} n={r['total']:4d} avg={r['avg_pips']:+7.1f}")

# SL/TP distance analysis
print(f"\n{'='*80}")
print("SL/TP DISTANCE ANALYSIS (avg |entry-SL| vs |entry-TP|)")
print(f"{'='*80}")
rows = conn.execute("""
    SELECT symbol,
           ROUND(AVG(ABS(entry_price - sl)), 5) as avg_sl_dist,
           ROUND(AVG(ABS(tp - entry_price)), 5) as avg_tp_dist,
           ROUND(AVG(ABS(tp - entry_price)) / NULLIF(AVG(ABS(entry_price - sl)), 0), 2) as actual_rr,
           ROUND(AVG(sl_atr_dist), 2) as avg_sl_atr
    FROM bt_trades
    GROUP BY symbol
""").fetchall()
for r in rows:
    print(f"  {r['symbol']:8s} SL_dist={r['avg_sl_dist']:.5f} TP_dist={r['avg_tp_dist']:.5f} "
          f"actual_RR=1:{r['actual_rr'] or 0:.2f} SL_ATR={r['avg_sl_atr'] or 0:.2f}")

# Win rate by session
print(f"\n{'='*80}")
print("BY SESSION")
print(f"{'='*80}")
rows = conn.execute("""
    SELECT session, symbol,
           COUNT(*) as total,
           SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins,
           ROUND(AVG(profit_pips),1) as avg_pips
    FROM bt_trades
    WHERE session IS NOT NULL
    GROUP BY session, symbol
    ORDER BY session, symbol
""").fetchall()
for r in rows:
    wr = r['wins']/r['total']*100 if r['total'] else 0
    print(f"  {r['session'] or 'unknown':12s} {r['symbol']:8s} n={r['total']:4d} "
          f"WR={wr:5.1f}% avg_pips={r['avg_pips']:+7.1f}")

# Check optimized_params.json
print(f"\n{'='*80}")
print("OPTIMIZED PARAMS")
print(f"{'='*80}")
params_path = "optimized_params.json"
if os.path.exists(params_path):
    with open(params_path) as f:
        data = json.load(f)
    for k, v in data.items():
        if isinstance(v, dict) and not k.startswith("_"):
            print(f"  {k}: WR={v.get('win_rate','?')}% PF={v.get('profit_factor','?')} "
                  f"ATR({v.get('atr_period','?')})x{v.get('atr_multiplier','?')} "
                  f"tp_x{v.get('tp_atr_multiplier','?')} struct={v.get('internal_structure_len','?')} "
                  f"st_factor={v.get('st_factor','?')} ema_fast={v.get('ema_fast_len','?')} "
                  f"pa_len={v.get('pa_length','?')}")
else:
    print("  Chua co optimized_params.json")

conn.close()
