"""
check_params.py — Script chan doan doc lap.

Muc dich: tra loi cau hoi "bot dang chay DUNG tham so nhu indicator goc
hay da bi optimizer ghi de?" — khong can doi auto_tuner chay xong, khong
can bat MT5.

Cach dung:
    py -3.11 check_params.py                # kiem tra tat ca symbol
    py -3.11 check_params.py --symbol XAUUSD # kiem tra rieng 1 symbol

In ra 2 phan:
  1. Gia tri THUC TE param_loader.get_all(symbol) se tra ve cho analysis.py
     dung (nghia la dung y het nhung gi bot live dang doc), so sanh voi
     default goc cua indicator XuTho v4 — danh dau KHAC BIET.
  2. Canh bao neu optimized_params.json con sot lai KEY CUA HE THONG CU
     (pivot_lookback, zone_merge_pct, volume_spike_mult, soup_max_exceed,
     min_touches...) — day la du lieu tu truoc khi doi sang SMC, khong con
     duoc analysis.py doc nhung co the gay nham lan khi xem /params.
"""

import argparse
import json
import os
import sys

import config
import param_loader

# Tham so GOC cua indicator "XuTho v4" (doc truc tiep tu Pine Script input.*)
# — day la nguon su that de so sanh.
INDICATOR_DEFAULTS = {
    "st_atr_len":              10,    # input.int(10, 'ATR Length', group='SuperTrend Settings')
    "st_factor":               3.0,   # input.float(3, 'SuperTrend Factor')
    "kmeans_training_period":  100,   # input.int(100, 'Training Data Length')
    "kmeans_highvol":          0.75,
    "kmeans_midvol":           0.5,
    "kmeans_lowvol":           0.25,
    "ema_fast_len":            9,     # input.int(9, title="EMA Nhanh")
    "ema_slow_len":            21,    # input.int(21, title="EMA Chậm")
    "internal_structure_len":  5,     # getCurrentStructure(5, false, true) — fixed trong Pine
    "swing_structure_len":     50,    # swingsLengthInput = input.int(50, ...)
    "pa_length":               14,    # Length for Trend Detection (Price Action/Dow Theory)
    "pa_vol_multiplier":       1.5,   # Volume Multiplier for Trend Confirmation
}

# Cac key thuoc he thong PATTERN NEN CU (da bi go bo khoi analysis.py) —
# neu con trong optimized_params.json thi la du lieu "rac" tu truoc khi
# doi sang SMC, khong anh huong bot nhung gay nham lan khi doc /params.
# (v8: them ca cac key OB/FVG-retest cua kien truc v5/v6 — da bi go bo
# khi chuyen sang OR-logic v7, gio cung la "rac" neu con sot lai)
LEGACY_KEYS = {
    "pivot_lookback", "zone_merge_pct", "min_touches",
    "breakout_thr_pct", "volume_spike_mult", "volume_avg_period",
    "soup_max_exceed", "soup_body_min", "soup_close_pct_sell",
    "soup_close_pct_buy", "pin_bar_body_pct", "pin_bar_wick_ratio",
    "engulf_strength", "rr_ratio",
    "ob_fvg_proximity_pct", "smc_ob_search_range", "ob_fvg_retest_max_bars",
    "trend_min_agree",
}

# Cac key dang duoc auto_tuner.py toi uu (neu bi optimizer doi thi
# KHONG bao gio "sai" — day la muc dich cua auto-tuner. Script nay chi
# canh bao de BAN BIET no da bi doi, khong phai loi).
TUNABLE_KEYS = {
    "atr_period", "atr_multiplier", "tp_atr_multiplier",
    "internal_structure_len", "st_factor", "ema_fast_len", "pa_length",
}


def check_symbol(symbol: str):
    print(f"\n{'='*70}\n  {symbol}\n{'='*70}")

    live_params = param_loader.get_all(symbol)
    raw = param_loader._params.get(symbol)  # None neu chua co trong JSON

    if raw is None:
        print("  Nguon: [DEFAULT] — chua co trong optimized_params.json")
        print("  => Bot dang chay 100% theo tham so goc cua indicator.\n")
    else:
        print(f"  Nguon: [JSON] optimized_at={raw.get('optimized_at','?')[:19]}")
        if raw.get("is_fallback"):
            print("  ⚠ is_fallback=True — auto-tuner CHUA tim duoc combo dat nguong,")
            print("    day la 'tot nhat trong nhung gi da thu', khong phai toi uu that.")
        print(f"  WR={raw.get('win_rate','?')}%  PF={raw.get('profit_factor','?')}"
              f"  n={raw.get('total_trades','?')} lenh\n")

        legacy_found = LEGACY_KEYS & set(raw.keys())
        if legacy_found:
            print(f"  ⚠ CANH BAO: JSON con sot key cua he thong CU (khong con dung):")
            print(f"    {sorted(legacy_found)}")
            print(f"    => Day la du lieu backtest TU TRUOC khi doi sang SMC.")
            print(f"    => Cac so WR/PF o tren CO THE la cua he thong cu, KHONG phan anh")
            print(f"       hieu suat cua analysis.py (SMC BOS/CHoCH) hien tai.")
            print(f"    => Nen xoa/backup optimized_params.json va chay lai auto_tuner.\n")

    print(f"  {'Tham so':<26} {'Dang dung':>12} {'Goc indicator':>15}   Trang thai")
    print(f"  {'-'*26} {'-'*12} {'-'*15}   {'-'*20}")
    for key, default_val in INDICATOR_DEFAULTS.items():
        actual = live_params.get(key)
        same = (actual == default_val)
        tag = "= goc (default)" if same else f"⚠ DA BI DOI (optimizer)"
        print(f"  {key:<26} {str(actual):>12} {str(default_val):>15}   {tag}")

    # Cac tham so tunable khac (khong co "default indicator" tuong duong,
    # nhung anh huong SL/TP) — chi hien thi gia tri dang dung.
    print(f"\n  Tham so SL/TP (khong co trong Pine goc, tu auto_tuner toi uu):")
    for key in ("atr_period", "atr_multiplier", "tp_atr_multiplier"):
        print(f"    {key:<26} = {live_params.get(key)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None, help="Chi kiem tra 1 symbol (vd: XAUUSD)")
    args = parser.parse_args()

    param_loader.apply()

    symbols = [args.symbol] if args.symbol else config.SYMBOLS
    for sym in symbols:
        check_symbol(sym)

    print(f"\n{'='*70}")
    print("  Ghi chu:")
    print("  - 'DA BI DOI (optimizer)' KHONG phai loi — do la auto_tuner.py")
    print("    da tim ra combo tot hon va ghi vao optimized_params.json.")
    print("  - Chi can LO NGAI neu thay canh bao 'key cua he thong CU' o tren —")
    print("    do moi la dau hieu du lieu rac/stale can don dep.")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
