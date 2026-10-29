"""
bootstrap.py
Chay 1 lan duy nhat khi cai dat bot lan dau.
Tao optimized_params.json tu backtest 90 ngay.

Sau khi chay xong, bot se dung tham so tu file nay thay vi config.py.

Chay: py -3.11 bootstrap.py
"""
import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bootstrap")

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
PARAMS_PATH = os.path.join(BASE_DIR, "optimized_params.json")

import config
import param_loader


def main():
    print("=" * 60)
    print("  BOOTSTRAP — Tao tham so toi uu lan dau")
    print("=" * 60)
    print()

    # Kiem tra da co file chua
    if os.path.exists(PARAMS_PATH):
        print(f"[!] Da co {PARAMS_PATH}")
        ans = input("    Ghi de? (y/n): ").strip().lower()
        if ans != "y":
            print("Huy. Bot se dung tham so hien tai.")
            param_loader.apply()
            print(param_loader.status())
            return

    print(f"[1] Chay backtest 90 ngay cho {len(config.SYMBOLS)} symbols...")
    print(f"    Symbols: {config.SYMBOLS}")
    print(f"    Grid search se thu nhieu to hop ATR x pivot_lookback")
    print()

    try:
        from auto_tuner import _run_all, _is_running
        import auto_tuner

        # Reset timer de buoc chay
        auto_tuner._last_run_ts = 0.0

        t0 = time.time()
        auto_tuner._run_all()
        elapsed = time.time() - t0

        print()
        print(f"[2] Hoan thanh sau {elapsed/60:.1f} phut")

        if os.path.exists(PARAMS_PATH):
            print()
            print("[3] Tham so toi uu da duoc ghi:")
            param_loader.reload()
            for sym in config.SYMBOLS:
                p = param_loader.get_all(sym)
                print(f"    {sym:8s}  ATR({p['atr_period']}) x {p['atr_multiplier']:.2f}"
                      f"  pivot={p['pivot_lookback']}"
                      f"  WR={p.get('win_rate',0):.1f}%"
                      f"  PF={p.get('profit_factor',0):.2f}")
            print()
            print("[4] Chay bot: py -3.11 watcher.py")
        else:
            print()
            print("[!] Chua tao duoc optimized_params.json")
            print("    Co the do backtest chua du du lieu (< 15 lenh/symbol)")
            print("    Bot se dung defaults tu config.py:")
            d = param_loader._config_defaults()
            print(f"    ATR({d['atr_period']}) x {d['atr_multiplier']} pivot={d['pivot_lookback']}")

    except ImportError as e:
        logger.error("Loi import: %s", e)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nDa huy.")


if __name__ == "__main__":
    main()
