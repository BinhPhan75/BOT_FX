"""
data_loader.py
Lấy nến lịch sử từ MT5 để phục vụ backtesting.

Dùng độc lập:
    py -3.11 data_loader.py --symbol XAUUSD --timeframe M15 --days 365

Hoặc import trong backtest_engine.py:
    from data_loader import load_candles, load_candles_multi
"""

import argparse
import csv
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

logger = logging.getLogger("data_loader")

TIMEFRAME_MAP = {
    "M1":  "TIMEFRAME_M1",
    "M5":  "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1":  "TIMEFRAME_H1",
    "H4":  "TIMEFRAME_H4",
    "D1":  "TIMEFRAME_D1",
}

# Cache thư mục lưu CSV (tránh download lại mỗi lần chạy)
CACHE_DIR = os.path.join(os.path.dirname(__file__), "bt_cache")


# ─── MT5 helpers ──────────────────────────────────────────────────────────────

def _ensure_mt5():
    if mt5 is None:
        raise RuntimeError("Cần cài MetaTrader5: pip install MetaTrader5")
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize() thất bại: {mt5.last_error()}")


def _tf_value(timeframe_str: str):
    attr = TIMEFRAME_MAP.get(timeframe_str.upper())
    if not attr:
        raise ValueError(f"Timeframe không hỗ trợ: {timeframe_str}")
    return getattr(mt5, attr)


def _rates_to_candles(rates) -> List[Dict]:
    """Chuyển numpy array từ MT5 → list[dict] chuẩn."""
    return [
        {
            "time":   int(r["time"]),
            "open":   float(r["open"]),
            "high":   float(r["high"]),
            "low":    float(r["low"]),
            "close":  float(r["close"]),
            "volume": float(r["tick_volume"]),
        }
        for r in rates
    ]


# ─── Download từ MT5 ──────────────────────────────────────────────────────────

def download_candles(
    symbol: str,
    timeframe: str,
    date_from: datetime,
    date_to: datetime,
) -> List[Dict]:
    """
    Tải nến từ MT5 trong khoảng thời gian cho trước.
    Trả về list dict sắp từ cũ → mới.
    """
    _ensure_mt5()
    tf = _tf_value(timeframe)

    rates = mt5.copy_rates_range(symbol, tf, date_from, date_to)
    if rates is None or len(rates) == 0:
        logger.warning(
            "Không lấy được dữ liệu %s %s [%s → %s]: %s",
            symbol, timeframe, date_from.date(), date_to.date(), mt5.last_error()
        )
        return []

    candles = _rates_to_candles(rates)
    logger.info(
        "Đã tải %d nến %s %s [%s → %s]",
        len(candles), symbol, timeframe,
        date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"),
    )
    return candles


# ─── Cache CSV ────────────────────────────────────────────────────────────────

def _cache_path(symbol: str, timeframe: str, days: int) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{symbol}_{timeframe}_{days}d.csv")


def _save_cache(candles: List[Dict], path: str):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["time","open","high","low","close","volume"])
        writer.writeheader()
        writer.writerows(candles)
    logger.info("Đã lưu cache → %s", path)


def _load_cache(path: str) -> Optional[List[Dict]]:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        candles = []
        for row in reader:
            candles.append({
                "time":   int(row["time"]),
                "open":   float(row["open"]),
                "high":   float(row["high"]),
                "low":    float(row["low"]),
                "close":  float(row["close"]),
                "volume": float(row["volume"]),
            })
    logger.info("Đọc từ cache %s (%d nến)", path, len(candles))
    return candles


# ─── Public API ───────────────────────────────────────────────────────────────

def load_candles(
    symbol: str,
    timeframe: str,
    days: int = 365,
    use_cache: bool = True,
    force_download: bool = False,
) -> List[Dict]:
    """
    Hàm chính: trả về list nến lịch sử.
    - Ưu tiên đọc cache CSV nếu có và use_cache=True.
    - force_download=True bỏ qua cache và tải lại từ MT5.
    """
    cache_path = _cache_path(symbol, timeframe, days)

    if use_cache and not force_download:
        cached = _load_cache(cache_path)
        if cached:
            return cached

    date_to   = datetime.now(timezone.utc)
    date_from = date_to - timedelta(days=days)

    candles = download_candles(symbol, timeframe, date_from, date_to)
    if candles and use_cache:
        _save_cache(candles, cache_path)

    return candles


def load_candles_multi(
    symbols: List[str],
    timeframe: str,
    htf_timeframe: Optional[str],
    days: int = 365,
    use_cache: bool = True,
) -> Dict[str, Dict[str, List[Dict]]]:
    """
    Tải nến cho nhiều symbol + HTF cùng lúc.
    Trả về dict: { symbol: { "M15": [...], "H1": [...] } }
    """
    result: Dict[str, Dict[str, List[Dict]]] = {}
    for symbol in symbols:
        result[symbol] = {}
        result[symbol][timeframe] = load_candles(symbol, timeframe, days, use_cache)
        if htf_timeframe:
            # HTF cần ít dữ liệu hơn để tính trend
            result[symbol][htf_timeframe] = load_candles(
                symbol, htf_timeframe, days, use_cache
            )
    return result


def get_htf_candles_at(
    htf_all: List[Dict],
    timestamp: int,
    count: int = 100,
) -> List[Dict]:
    """
    Lấy N nến HTF tính đến thời điểm `timestamp` (không dùng dữ liệu tương lai).
    Dùng binary search để tìm vị trí đúng trong array đã sort theo thời gian.
    """
    lo, hi = 0, len(htf_all) - 1
    pos = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if htf_all[mid]["time"] <= timestamp:
            pos = mid
            lo = mid + 1
        else:
            hi = mid - 1
    start = max(0, pos - count + 1)
    return htf_all[start : pos + 1]


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Tải nến lịch sử từ MT5")
    parser.add_argument("--symbol",    default="XAUUSD")
    parser.add_argument("--timeframe", default="M15")
    parser.add_argument("--days",      type=int, default=365)
    parser.add_argument("--no-cache",  action="store_true")
    parser.add_argument("--force",     action="store_true", help="Tải lại dù đã có cache")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    candles = load_candles(
        symbol=args.symbol,
        timeframe=args.timeframe,
        days=args.days,
        use_cache=not args.no_cache,
        force_download=args.force,
    )

    if not candles:
        print("Không lấy được dữ liệu.")
        sys.exit(1)

    first = datetime.fromtimestamp(candles[0]["time"], tz=timezone.utc)
    last  = datetime.fromtimestamp(candles[-1]["time"], tz=timezone.utc)
    print(f"\nSymbol   : {args.symbol} {args.timeframe}")
    print(f"Số nến   : {len(candles):,}")
    print(f"Từ       : {first.strftime('%Y-%m-%d %H:%M')}")
    print(f"Đến      : {last.strftime('%Y-%m-%d %H:%M')}")
    print(f"Cache    : {_cache_path(args.symbol, args.timeframe, args.days)}")

    if mt5 and mt5.initialize():
        mt5.shutdown()


if __name__ == "__main__":
    main()
