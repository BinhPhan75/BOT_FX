"""
quick_check.py — Backtest NHANH, KHONG toi uu, chi de dem tan suat tin hieu.

Muc dich: truoc khi bo ra 5-6h+ chay full WFO (auto_tuner.py), chay script
nay (vai phut) de biet ngay voi bo tham so HIEN TAI (optimized_params.json
neu co, khong thi default) thi:
  - Bao nhieu tin hieu/ngay (total_signals — TRUOC regime/HTF filter)
  - Bao nhieu lenh thuc su duoc vao/ngay (total_trades — SAU tat ca filter)
  - WR/PF so bo

Neu total_signals qua thap (< 1-2/ngay) → logic entry (BOS/CHoCH + trend +
retest zone) van con qua khac khe, can noi tham so TRUOC khi mat cong chay
WFO day du. Neu total_signals binh thuong nhung total_trades qua thap →
van de nam o market_regime/HTF filter, khong phai analysis.py.

Cach dung:
    py -3.11 quick_check.py                      # tat ca symbol, 14 ngay
    py -3.11 quick_check.py --days 30             # doi so ngay
    py -3.11 quick_check.py --symbol XAUUSD       # chi 1 symbol
"""

import argparse
import logging

import config
import backtest_engine
import param_loader


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14, help="So ngay du lieu (mac dinh 14, nen)")
    parser.add_argument("--symbol", default=None, help="Chi test 1 symbol (vd: XAUUSD)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")  # im lang log chi tiet, chi in ket qua

    param_loader.apply()
    symbols = [args.symbol] if args.symbol else config.SYMBOLS

    print(f"\n{'='*78}")
    print(f"  QUICK CHECK — {args.days} ngay gan nhat — tham so dang dung "
          f"({'optimized_params.json' if param_loader._params else 'DEFAULT indicator'})")
    print(f"{'='*78}")
    print(f"  {'Symbol':<8} {'Signals':>8} {'Trades':>7} {'Sig/ngay':>9} {'Lenh/ngay':>10} "
          f"{'WR%':>6} {'PF':>6}")
    print(f"  {'-'*8} {'-'*8} {'-'*7} {'-'*9} {'-'*10} {'-'*6} {'-'*6}")

    for sym in symbols:
        stats = backtest_engine.run_backtest(
            sym, config.TIMEFRAME, days=args.days, use_htf=True, use_cache=True,
        )
        if not stats:
            print(f"  {sym:<8}  Khong du du lieu / loi backtest.")
            continue

        sig_per_day   = stats["total_signals"] / args.days
        trade_per_day = stats["total_trades"] / args.days
        print(
            f"  {sym:<8} {stats['total_signals']:>8} {stats['total_trades']:>7} "
            f"{sig_per_day:>9.2f} {trade_per_day:>10.2f} "
            f"{stats['win_rate']:>6.1f} {stats['profit_factor']:>6.2f}"
        )

    print(f"{'='*78}")
    print("  Doc ket qua:")
    print("  - Sig/ngay qua thap (<1) → dieu kien BOS/CHoCH + trend + retest")
    print("    van con khac khe, can noi truoc khi chay WFO day du.")
    print("  - Sig/ngay on nhung Lenh/ngay << Sig/ngay → regime/HTF filter")
    print("    (market_regime.py / trend_filter.py) dang chan nhieu, xem xet rieng.")
    print("  - Neu Sig/ngay va Lenh/ngay deu on (~1-5/ngay/symbol) → co the yen")
    print("    tam chay auto_tuner.py --force-all de toi uu tham so.")
    print(f"{'='*78}\n")


if __name__ == "__main__":
    main()