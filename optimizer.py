"""
optimizer.py
Tự động tìm bộ tham số tối ưu cho bot bằng Random Search.

Cách hoạt động:
  1. Sinh ngẫu nhiên N tổ hợp tham số (volume, ATR, RR, pivot...)
  2. Chạy backtest_engine với từng tổ hợp (dùng cache nến → nhanh)
  3. Chấm điểm: expectancy × sqrt(total_trades) × profit_factor
  4. Lưu top params per symbol → optimized_params.json
  5. param_loader.py đọc file này, override config lúc watcher khởi động

Chạy:
    py -3.11 optimizer.py                          # tất cả symbol, 60 iterations
    py -3.11 optimizer.py --symbol XAUUSD --n 100  # 1 symbol, 100 iterations
    py -3.11 optimizer.py --n 40 --days 180        # nhanh hơn với ít ngày hơn

Thời gian ước tính:
    60 iterations × 4 symbol × ~3s/backtest ≈ ~12 phút
"""

import argparse
import contextlib
import json
import logging
import math
import os
import random
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import config
import backtest_engine
from data_loader import load_candles_multi

logger = logging.getLogger("optimizer")

PARAMS_PATH = os.path.join(os.path.dirname(__file__), "optimized_params.json")

# ─── Không gian tham số cần tìm ───────────────────────────────────────────────
#
# Mỗi entry: (tên config, [danh sách giá trị thử])
# Tham số global: áp dụng cho tất cả symbol
# Tham số per-symbol: tìm riêng cho từng symbol
#
SEARCH_SPACE_GLOBAL = {
    "VOLUME_SPIKE_MULTIPLIER":    [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.7, 2.0],
    "BREAKOUT_THRESHOLD_PERCENT": [0.02, 0.03, 0.04, 0.05, 0.06, 0.08],
    "PIVOT_LOOKBACK":             [2, 3, 4, 5],
    "MIN_TOUCHES":                [1, 2],
    "VOLUME_AVG_PERIOD":          [14, 20, 26],
}

SEARCH_SPACE_PER_SYMBOL = {
    "DEFAULT_RR_RATIO":    [1.5, 2.0, 2.5, 3.0, 3.5],
    "ATR_SL_FACTOR_VALUE": [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0],
}

# Số lệnh tối thiểu để kết quả có ý nghĩa thống kê
MIN_TRADES_THRESHOLD = 20


# ─── Patch config tạm thời ────────────────────────────────────────────────────

@contextlib.contextmanager
def _patch_config(overrides: Dict[str, Any]):
    """
    Context manager: patch config module với giá trị override,
    khôi phục lại sau khi xong.
    Không thread-safe — optimizer chạy tuần tự nên OK.
    """
    original = {}
    for key, value in overrides.items():
        original[key] = getattr(config, key, None)
        setattr(config, key, value)
    try:
        yield
    finally:
        for key, value in original.items():
            if value is None:
                try:
                    delattr(config, key)
                except AttributeError:
                    pass
            else:
                setattr(config, key, value)


# ─── Scoring function ─────────────────────────────────────────────────────────

def _score(stats: Dict) -> float:
    """
    Chấm điểm 1 bộ tham số.

    Công thức: expectancy × log2(total_trades) × profit_factor

    Expectancy (kỳ vọng pips/lệnh) = wr × avg_win_pips - (1-wr) × avg_loss_pips
    Nhân log2(trades) để thưởng cho bộ tham số tạo ra nhiều lệnh (đủ sample)
    Nhân profit_factor để thưởng cho bộ tham số có tỉ lệ lời/lỗ cao

    Trả về 0 nếu không đủ điều kiện.
    """
    n  = stats.get("total_trades", 0)
    wr = stats.get("win_rate", 0) / 100
    pf = stats.get("profit_factor", 0)
    avg_pips = stats.get("avg_profit", 0)

    if n < MIN_TRADES_THRESHOLD:
        return 0.0
    if pf <= 0 or avg_pips <= 0:
        return 0.0

    # Expectancy: wr * avg_win - (1-wr) * avg_loss
    # Ước tính avg_win và avg_loss từ avg_pips và profit_factor
    # avg_win / avg_loss ≈ profit_factor / (wr/(1-wr)) nếu wr < 1
    if wr > 0 and wr < 1:
        implied_avg_loss = avg_pips / (wr - (1 - wr) / pf) if pf > 0 else 1
        implied_avg_win  = implied_avg_loss * pf
        expectancy       = wr * implied_avg_win - (1 - wr) * implied_avg_loss
    else:
        expectancy = avg_pips

    if expectancy <= 0:
        return 0.0

    # Cộng thêm trade count reward và profit factor
    score = expectancy * math.log2(max(n, 2)) * min(pf, 5.0)
    return round(score, 4)


# ─── Random sampling ──────────────────────────────────────────────────────────

def _sample_params(symbol: str, rng: random.Random) -> Dict[str, Any]:
    """Sinh ngẫu nhiên 1 bộ tham số từ search space."""
    params: Dict[str, Any] = {}

    for key, choices in SEARCH_SPACE_GLOBAL.items():
        params[key] = rng.choice(choices)

    for key, choices in SEARCH_SPACE_PER_SYMBOL.items():
        params[key] = rng.choice(choices)

    return params


def _build_config_overrides(params: Dict, symbol: str) -> Dict[str, Any]:
    """
    Chuyển params dict thành overrides cho config module.
    ATR_SL_FACTOR_VALUE được đặt vào dict ATR_SL_FACTOR của symbol.
    """
    overrides: Dict[str, Any] = {}

    for key, value in params.items():
        if key == "ATR_SL_FACTOR_VALUE":
            # Override chỉ cho symbol đang optimize
            current = deepcopy(getattr(config, "ATR_SL_FACTOR", {}))
            if isinstance(current, dict):
                current[symbol] = value
            else:
                current = {symbol: value}
            overrides["ATR_SL_FACTOR"] = current
        elif key == "DEFAULT_RR_RATIO":
            overrides["DEFAULT_RR_RATIO"] = value
        else:
            overrides[key] = value

    return overrides


# ─── Chạy 1 iteration ────────────────────────────────────────────────────────

def _run_iteration(
    symbol: str,
    params: Dict,
    candles_cache: Dict,
    days: int,
    iteration: int,
) -> Tuple[float, Dict]:
    """
    Patch config → chạy backtest → tính score → trả về (score, stats).
    Dùng candles_cache để không download lại mỗi lần.
    """
    overrides = _build_config_overrides(params, symbol)

    # Tắt log backtest_engine trong lúc optimize để không spam
    bt_logger = logging.getLogger("backtest")
    prev_level = bt_logger.level
    bt_logger.setLevel(logging.WARNING)

    try:
        with _patch_config(overrides):
            stats = backtest_engine.run_backtest(
                symbol    = symbol,
                timeframe = config.TIMEFRAME,
                days      = days,
                rr_ratio  = params.get("DEFAULT_RR_RATIO"),
                use_htf   = True,
                use_cache = True,
            )
    finally:
        bt_logger.setLevel(prev_level)

    score = _score(stats) if stats else 0.0
    return score, stats


# ─── Main optimizer per symbol ────────────────────────────────────────────────

def optimize_symbol(
    symbol: str,
    n_iter: int,
    days: int,
    seed: int = 42,
) -> Dict:
    """
    Random search cho 1 symbol.
    Trả về best_params dict.
    """
    rng = random.Random(seed)
    logger.info("══ Optimize %s | %d iterations | %d ngày ══", symbol, n_iter, days)

    best_score  = -1.0
    best_params = {}
    best_stats  = {}
    history     = []

    t0 = time.time()

    for i in range(1, n_iter + 1):
        params = _sample_params(symbol, rng)
        score, stats = _run_iteration(symbol, params, {}, days, i)

        history.append({"params": params, "score": score, "stats": stats})

        if score > best_score:
            best_score  = score
            best_params = params
            best_stats  = stats
            marker = " ★ NEW BEST"
        else:
            marker = ""

        # Progress line
        elapsed = time.time() - t0
        eta     = (elapsed / i) * (n_iter - i)
        n       = stats.get("total_trades", 0)
        wr      = stats.get("win_rate", 0)
        pf      = stats.get("profit_factor", 0)
        print(
            f"\r  [{i:3d}/{n_iter}] score={score:7.1f} | "
            f"trades={n:4d} WR={wr:4.1f}% PF={pf:.2f} | "
            f"ETA {eta:4.0f}s{marker}",
            end="", flush=True,
        )

    print()  # newline sau progress
    elapsed = time.time() - t0
    logger.info(
        "Xong %s: best_score=%.1f | WR=%.1f%% | PF=%.2f | trades=%d | %.0fs",
        symbol, best_score,
        best_stats.get("win_rate", 0),
        best_stats.get("profit_factor", 0),
        best_stats.get("total_trades", 0),
        elapsed,
    )

    return {
        "symbol":      symbol,
        "best_score":  best_score,
        "best_params": best_params,
        "best_stats":  best_stats,
        "top_history": sorted(history, key=lambda x: x["score"], reverse=True)[:5],
    }


# ─── Lưu / đọc kết quả ───────────────────────────────────────────────────────

def _load_existing() -> Dict:
    if not os.path.exists(PARAMS_PATH):
        return {}
    try:
        with open(PARAMS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_results(results: List[Dict]):
    """
    Ghi optimized_params.json.
    Format:
    {
      "generated_at": "...",
      "XAUUSD": { "params": {...}, "score": 123.4, "stats": {...} },
      ...
    }
    """
    existing = _load_existing()
    existing["generated_at"] = datetime.now(timezone.utc).isoformat()

    for r in results:
        sym = r["symbol"]
        # Chỉ cập nhật nếu score tốt hơn lần trước
        prev_score = existing.get(sym, {}).get("score", -1)
        if r["best_score"] > prev_score:
            existing[sym] = {
                "score":  r["best_score"],
                "params": r["best_params"],
                "stats":  r["best_stats"],
            }
            logger.info(
                "✅ %s: score %.1f → %.1f (cải thiện)",
                sym, prev_score, r["best_score"],
            )
        else:
            logger.info(
                "⏭️  %s: score %.1f không tốt hơn cũ %.1f → giữ params cũ",
                sym, r["best_score"], prev_score,
            )

    with open(PARAMS_PATH, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    logger.info("Đã lưu → %s", PARAMS_PATH)


# ─── Print report ─────────────────────────────────────────────────────────────

def print_report(results: List[Dict]):
    div = "─" * 60
    print(f"\n{div}")
    print("  KẾT QUẢ OPTIMIZER")
    print(div)

    for r in results:
        sym    = r["symbol"]
        p      = r["best_params"]
        s      = r["best_stats"]
        score  = r["best_score"]

        print(f"\n  {sym}  (score={score:.1f})")
        print(f"    Win rate       : {s.get('win_rate', 0):.1f}%")
        print(f"    Profit factor  : {s.get('profit_factor', 0):.2f}")
        print(f"    Tổng lệnh      : {s.get('total_trades', 0)}")
        print(f"    Avg pips       : {s.get('avg_profit', 0):+.1f}")
        print(f"  Tham số tốt nhất:")
        for k, v in p.items():
            print(f"    {k:<35} = {v}")

        print(f"\n  Top 5 iterations khác:")
        for rank, h in enumerate(r["top_history"][:5], 1):
            hp = h["params"]
            hs = h["stats"]
            print(
                f"    #{rank} score={h['score']:7.1f} | "
                f"WR={hs.get('win_rate',0):.1f}% PF={hs.get('profit_factor',0):.2f} "
                f"trades={hs.get('total_trades',0)} | "
                f"RR={hp.get('DEFAULT_RR_RATIO','?')} "
                f"VOL={hp.get('VOLUME_SPIKE_MULTIPLIER','?')} "
                f"ATR={hp.get('ATR_SL_FACTOR_VALUE','?')}"
            )

    print(f"\n  → {PARAMS_PATH}")
    print(div)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Tối ưu tham số bot bằng random search trên backtest data"
    )
    parser.add_argument("--symbol",  default=None,
                        help="Symbol cụ thể (mặc định: tất cả trong config.SYMBOLS)")
    parser.add_argument("--n",       type=int, default=60,
                        help="Số iterations mỗi symbol (mặc định: 60)")
    parser.add_argument("--days",    type=int, default=365,
                        help="Số ngày dữ liệu lịch sử (mặc định: 365)")
    parser.add_argument("--seed",    type=int, default=42,
                        help="Random seed (mặc định: 42)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Tắt log noise từ analysis/backtest trong lúc optimize
    for mod in ["analysis", "candlestick_patterns", "smc_patterns",
                "triangle_patterns", "trend_filter"]:
        logging.getLogger(mod).setLevel(logging.WARNING)

    symbols = [args.symbol] if args.symbol else config.SYMBOLS
    total_runs = len(symbols) * args.n

    print(f"\n{'═'*60}")
    print(f"  FOREX BOT OPTIMIZER")
    print(f"  Symbols   : {symbols}")
    print(f"  Iterations: {args.n} mỗi symbol ({total_runs} tổng)")
    print(f"  Dữ liệu   : {args.days} ngày")
    print(f"  ETA ước   : ~{total_runs * 3 // 60} phút")
    print(f"{'═'*60}\n")

    # Pre-warm cache — tải nến 1 lần trước khi bắt đầu
    print("Đang tải cache nến...")
    for sym in symbols:
        load_candles_multi(
            symbols=[sym],
            timeframe=config.TIMEFRAME,
            htf_timeframe=config.HTF_TIMEFRAME,
            days=args.days,
            use_cache=True,
        )
    print("Cache sẵn sàng.\n")

    all_results = []
    for sym in symbols:
        result = optimize_symbol(
            symbol = sym,
            n_iter = args.n,
            days   = args.days,
            seed   = args.seed,
        )
        all_results.append(result)

    save_results(all_results)
    print_report(all_results)


if __name__ == "__main__":
    main()
