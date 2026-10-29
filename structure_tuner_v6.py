# structure_tuner_v6.py
"""
DO THAM SO 46 MO HINH CAU TRUC (Hinh hoc 14 | Harmonic 8 | Phan ky 8 | ICT 6 | VSA 6 | Continuation 4), tung mo hinh, tren lich su.
Cung quy trinh voi pattern_tuner_v6.py (mo hinh nen): xep hang tren 70% dau (TRAIN), kiem tra tren 30% sau (TEST), chi ghi bo DAT.

    py -3.11 structure_tuner_v6.py --csv bt_cache\\XAUUSD_M5_1y.csv --tf M5 --patterns DOUBLE_TOP,DOUBLE_BOTTOM \\
        --k 1.0 --rr 1.3 --horizon 6 --spread 0.25 --hours-vn 8-18 --max-bars 40000 [--write-config]

    --patterns: ten (phay) | GEO | HARMONIC | DIVERGENCE | ICT | VSA | CONT | ALL
    --cache ctx.pkl : luu boi canh da dung (buoc cham nhat) de chay lai nhanh khi doi mo hinh/tham so.

Boi canh (swing, ATR, volume...) duoc dung bang CHINH build_ctx() cua bot tren cua so 300 nen DA DONG; chi bao RSI/MACD lay tu chuoi toan bo
du lieu (sai khac khong dang ke so voi chuoi 300 nen sau ~100 nen khoi dong).
"""
import argparse
import json
import os
import pickle
import random
import sys
import itertools
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import structure_params_v6 as SP  # noqa: E402
import pattern_lab_v6 as L  # noqa: E402
import pattern_tuner_v6 as T  # noqa: E402

GROUPS = {"GEO": SP.GEO_NAMES, "HARMONIC": SP.HAR_NAMES, "DIVERGENCE": SP.DIV_NAMES, "ICT": SP.ICT_NAMES, "VSA": SP.VSA_NAMES,
          "CONT": SP.CONT_NAMES, "ALL": SP.ALL_NAMES}
WINDOW = 300


def make_ind(G, off):
    def ind(kind, idx):
        j = off + idx
        if idx < 0 or j < 0 or j >= len(G[kind]):
            return None
        v = G[kind][j]
        return None if v != v else float(v)
    return ind


def build_cache(df, factors, start, step, G):
    candles = L.make_candles(df)
    ctxs = []
    t0 = datetime.now()
    total = len(range(start, len(df), step))
    for cnt, i in enumerate(range(start, len(df), step)):
        off = i - WINDOW + 1
        if off < 0:
            continue
        ctx = SP.build_ctx(candles[off:i + 1], factors, ind=make_ind(G, off))
        if ctx is not None:
            ctx["bar"], ctx["_off"] = i, off
            ctx.pop("ind", None)
            ctxs.append(ctx)
        if cnt and cnt % 5000 == 0:
            el = (datetime.now() - t0).total_seconds()
            print(f"   … dựng bối cảnh {cnt}/{total} ({el:.0f}s)")
    return ctxs


def tune_one(name, ctxs, m, split, start, a):
    d = SP.DIRECTION[name]
    grid = SP.PARAM_GRID[name]
    keys = list(grid)
    combos = list(itertools.product(*[grid[k] for k in keys]))
    total = len(combos)
    default_combo = tuple(SP.DEFAULTS[name][k] for k in keys)
    if a.max_combos and total > a.max_combos:
        random.Random(1).shuffle(combos)
        combos = combos[:a.max_combos]
    if default_combo not in combos:
        combos.append(default_combo)

    def run(P):
        PPc = {n: SP.DEFAULTS[n] for n in (name,)}
        PPc[name] = {**SP.DEFAULTS[name], **P}
        idx = []
        for ctx in ctxs:
            if SP.detect_one(ctx, name, PPc) is not None:
                idx.append(ctx["bar"])
        idx = np.array(idx, dtype=int)
        return T.perf(m, idx, d, start, split - m.H), T.perf(m, idx, d, split, m.n)

    rows = []
    for ci, combo in enumerate(combos):
        P = dict(zip(keys, combo))
        tr, te = run(P)
        rows.append(({**SP.DEFAULTS[name], **P}, tr, te))
        if a.progress and ci % 10 == 0:
            print(f"      {name}: {ci + 1}/{len(combos)}")
    score = a.score
    valid = [r for r in rows if r[1]["n"] >= a.min_trades and not np.isnan(r[1][score])]
    valid.sort(key=lambda r: -r[1][score])
    seen, uniq = set(), []
    for r in valid:
        sig = (r[1]["n"], round(r[1]["ev"], 6), r[2]["n"], round(r[2]["ev"], 6) if not np.isnan(r[2]["ev"]) else None)
        if sig not in seen:
            seen.add(sig)
            uniq.append(r)
    valid = uniq
    print("\n" + "=" * 140)
    print(f"{name} ({'BUY' if d == 1 else 'SELL'}) — {len(combos)}/{total} tổ hợp thử | {len(valid)} bộ kết quả khác nhau có ≥{a.min_trades} lệnh ở TRAIN | xếp hạng theo {score.upper()} (TRAIN)")
    b_tr, b_te = T.perf(m, np.array([], int), d, start, split - m.H), T.perf(m, np.array([], int), d, split, m.n)
    print(f"Ngẫu nhiên cùng bộ lọc/SL/TP/spread — EV mỗi lệnh: TRAIN {b_tr['base']:+.3f}R | TEST {b_te['base']:+.3f}R")
    print("=" * 140)
    print(f"{'hạng':>4s}  {'tham số':62s} | {'TRAIN n':>7s} {'WR':>6s} {'EV(R)':>7s} {'PF':>5s} | {'TEST n':>6s} {'WR':>6s} {'EV(R)':>7s} {'PF':>5s} {'lift':>6s} {'z':>5s}")
    for rank, (P, tr, te) in enumerate(valid[:a.top], 1):
        print(T.row_str(str(rank), P, keys, tr, te))
    dtr, dte = run({k: SP.DEFAULTS[name][k] for k in keys})
    print(T.row_str("mđ", SP.DEFAULTS[name], keys, dtr, dte))
    if not valid:
        print("→ KẾT LUẬN: không tổ hợp nào đủ số lệnh ở TRAIN (mô hình hiếm — tăng dữ liệu hoặc giảm --min-trades).")
        return None
    best = valid[0]
    top5 = [r[2]["ev"] for r in valid[:5] if r[2]["n"] >= a.min_test and not np.isnan(r[2]["ev"])]
    ok = (best[2]["n"] >= a.min_test and best[2]["ev"] > 0 and not np.isnan(best[2]["lift"]) and best[2]["lift"] > 0
          and not np.isnan(best[2]["z"]) and best[2]["z"] >= a.zthr)
    print(f"→ Tốt nhất (TRAIN): {T.fmt_params(best[0], keys)}")
    if best[2]["n"] >= 3:
        print(f"  TEST: {best[2]['n']} lệnh, WR {best[2]['wr']:.1%}, EV {best[2]['ev']:+.3f}R (ngẫu nhiên {best[2]['base']:+.3f}R, lift {best[2]['lift']:+.3f}, z {best[2]['z']:.1f})")
    else:
        print(f"  TEST: chỉ {best[2]['n']} lệnh — không đủ để kiểm tra")
    if top5:
        print(f"  EV TEST trung bình của top-5 theo TRAIN: {np.mean(top5):+.3f}R")
    print("  " + (f"✅ ĐẠT: giữ được EV dương và hơn ngẫu nhiên có ý nghĩa (z ≥ {a.zthr:.2f}) trên dữ liệu kiểm tra" if ok else
                  f"❌ KHÔNG ĐẠT: trên dữ liệu kiểm tra cần EV > 0, hơn ngẫu nhiên với z ≥ {a.zthr:.2f} và ≥ {a.min_test} lệnh"))
    return {"params": dict(best[0]), "train": best[1], "test": best[2], "ok": bool(ok)}


def print_summary(results, a):
    """Bang tong ket cuoi cung cho nhieu mo hinh: de doc nhanh mo hinh nao DAT."""
    print("\n" + "=" * 118)
    print(f"TỔNG KẾT ({len(results)} mô hình) — ngưỡng ĐẠT: TEST EV > 0, lift > 0, z ≥ {a.zthr:.2f}, ≥ {a.min_test} lệnh")
    print("=" * 118)
    print(f"{'mô hình':34s}{'TRAIN n':>8s}{'EV(R)':>8s}{'TEST n':>8s}{'WR':>7s}{'EV(R)':>8s}{'lift':>8s}{'z':>6s}  kết quả")
    f = lambda v, p: ("   -" if v is None or (isinstance(v, float) and np.isnan(v)) else format(v, p))
    for name, r in results.items():
        if r is None:
            print(f"{name:34s}{'-':>8s}{'-':>8s}{'-':>8s}{'-':>7s}{'-':>8s}{'-':>8s}{'-':>6s}  không đủ lệnh ở TRAIN")
            continue
        tr, te = r["train"], r["test"]
        print(f"{name:34s}{tr['n']:>8d}{f(tr['ev'], '+.3f'):>8s}{te['n']:>8d}{f(te['wr'], '.1%'):>7s}{f(te['ev'], '+.3f'):>8s}"
              f"{f(te['lift'], '+.3f'):>8s}{f(te['z'], '.1f'):>6s}  {'✅ ĐẠT' if r['ok'] else '❌ không đạt'}")


def wf_structure(name, ctxs, m, start, a, times):
    d = SP.DIRECTION[name]
    grid = SP.PARAM_GRID[name]
    keys = list(grid)
    combos = list(itertools.product(*[grid[k] for k in keys]))
    default_combo = tuple(SP.DEFAULTS[name][k] for k in keys)
    if a.max_combos and len(combos) > a.max_combos:
        random.Random(1).shuffle(combos)
        combos = combos[:a.max_combos]
    if default_combo not in combos:
        combos.append(default_combo)
    plist, idxlist = [], []
    for combo in combos:
        P = {**SP.DEFAULTS[name], **dict(zip(keys, combo))}
        PPc = {name: P}
        idxlist.append(np.array([c["bar"] for c in ctxs if SP.detect_one(c, name, PPc) is not None], dtype=int))
        plist.append(P)
    return T.walk_forward(name, d, m, plist, idxlist, keys, start, a, times)


def write_config(path, results, a, df):
    cfg = {"_meta": {}, "patterns": {}}
    if os.path.exists(path):
        try:
            cfg.update(json.load(open(path, encoding="utf-8")))
        except Exception:
            pass
    wrote = []
    for name, r in results.items():
        if r is None or not (r["ok"] or a.force):
            continue
        cfg["patterns"][name] = r["params"]
        cfg["_meta"][name] = {"validated_on_test": r["ok"], "tf": a.tf, "k": a.k, "rr": a.rr, "horizon": a.horizon, "spread": a.spread,
                              "hours_vn": a.hours_vn, "data_to": pd.to_datetime(int(df["time"].iloc[-1]), unit="s").isoformat(),
                              "train": {k: (None if np.isnan(v) else v) for k, v in r["train"].items() if k in ("n", "wr", "ev", "pf")},
                              "test": {k: (None if np.isnan(v) else v) for k, v in r["test"].items() if k in ("n", "wr", "ev", "pf", "lift", "z")},
                              "written": datetime.now().isoformat(timespec="seconds")}
        wrote.append(name)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    json.dump(cfg, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return wrote


def main(argv=None):
    ap = argparse.ArgumentParser(description="Dò tham số từng mô hình cấu trúc trên dữ liệu lịch sử")
    ap.add_argument("--patterns", default="")
    ap.add_argument("--csv", type=str)
    ap.add_argument("--bt-cache", type=str, default="bt_cache")
    ap.add_argument("--mt5", action="store_true")
    ap.add_argument("--years", type=float, default=1.0)
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--tf", default="M5")
    ap.add_argument("--k", type=float, default=1.0)
    ap.add_argument("--rr", type=float, default=1.3)
    ap.add_argument("--horizon", type=int, default=6)
    ap.add_argument("--spread", type=float, default=0.25)
    ap.add_argument("--hours-vn", type=str, default=None)
    ap.add_argument("--bias-csv", type=str, default=None)
    ap.add_argument("--bias-tf", default="M15")
    ap.add_argument("--bias-adx", type=float, default=12.0)
    ap.add_argument("--max-bars", type=int, default=40000, help="chi dung N nen cuoi (boi canh dung rat lau)")
    ap.add_argument("--step", type=int, default=1)
    ap.add_argument("--train-frac", type=float, default=0.7)
    ap.add_argument("--min-trades", type=int, default=30)
    ap.add_argument("--min-test", type=int, default=15)
    ap.add_argument("--min-z", type=float, default=1.65, help="TEST: lift phai co z >= nguong nay (tu dong tang theo so mo hinh thu cung luc - Bonferroni)")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--score", choices=["lcb", "ev", "pf"], default="lcb")
    ap.add_argument("--max-combos", type=int, default=100)
    ap.add_argument("--walk-forward", type=int, default=0, help="K>0: walk-forward K doan (khuyen nghi 4) thay cho chia 70/30")
    ap.add_argument("--cache", type=str, default=None)
    ap.add_argument("--progress", action="store_true")
    ap.add_argument("--write-config", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--config-path", type=str, default=None)
    a = ap.parse_args(argv)

    if not a.patterns:
        print("Chọn mô hình bằng --patterns. Nhóm:", ", ".join(GROUPS))
        for g, ns in GROUPS.items():
            if g != "ALL":
                print(f"  {g:10s}: {', '.join(ns)}")
        return 1
    names = []
    for tok in [x.strip().upper() for x in a.patterns.split(",") if x.strip()]:
        for n in (GROUPS[tok] if tok in GROUPS else [tok]):
            if n not in names:
                names.append(n)
    bad = [n for n in names if n not in SP.ALL_NAMES]
    if bad:
        print("Tên không hợp lệ:", bad)
        return 1

    if a.mt5:
        df = L.load_mt5(a.symbol, a.tf, a.years)
    else:
        path = a.csv or L.autodiscover(a.bt_cache, a.symbol, a.tf)
        if not path:
            print("❌ Không thấy CSV (--csv ...)")
            return 1
        print(f"📄 {path}")
        df = L.load_csv(path)
    L.describe(df, a.tf)
    mask, parts = L.build_mask(df, a.tf, a.bias_csv, a.bias_tf, a.bias_adx, a.hours_vn) if (a.bias_csv or a.hours_vn) else (None, None)
    m = L.Market(df, a.k, a.rr, a.horizon, a.spread, mask)
    start = max(L.WARMUP, WINDOW, len(df) - a.max_bars)
    split = int(start + (m.n - start) * a.train_frac)

    factors = sorted({float(v) for n in names for v in SP.PARAM_GRID[n].get("major_move_atr", [])} | {4.0})
    from ai_v5.pipeline.divergence_patterns import compute_rsi_series, compute_macd_series
    G = {"RSI": compute_rsi_series(df["close"], period=14).to_numpy(), "MACD": compute_macd_series(df["close"], fast=12, slow=26).to_numpy()}
    ctxs = None
    if a.cache and os.path.exists(a.cache):
        try:
            blob = pickle.load(open(a.cache, "rb"))
            if blob["meta"] == (len(df), int(df["time"].iloc[-1]), start, a.step) and set(factors) <= set(blob["factors"]):
                ctxs = blob["ctxs"]
                print(f"♻️  Dùng bối cảnh đã lưu: {a.cache} ({len(ctxs)} nến)")
        except Exception:
            ctxs = None
    if ctxs is None:
        allf = sorted({float(v) for n in SP.ALL_NAMES for v in SP.PARAM_GRID[n].get("major_move_atr", [])} | {4.0}) if a.cache else factors
        print(f"🔧 Dựng bối cảnh {len(range(start, len(df), a.step))} nến (hệ số swing lớn: {allf}) — bước này lâu nhất, chỉ làm 1 lần...")
        ctxs = build_cache(df, allf, start, a.step, G)
        if a.cache:
            pickle.dump({"meta": (len(df), int(df["time"].iloc[-1]), start, a.step), "factors": allf, "ctxs": ctxs}, open(a.cache, "wb"))
            print(f"💾 Đã lưu bối cảnh vào {a.cache}")
    for ctx in ctxs:                                  # gan lai ham chi bao (closure khong luu duoc vao cache)
        ctx["ind"] = make_ind(G, ctx["_off"])
    print(f"Chia dữ liệu: TRAIN {pd.to_datetime(int(df['time'].iloc[start]), unit='s'):%Y-%m-%d} → {pd.to_datetime(int(df['time'].iloc[split]), unit='s'):%Y-%m-%d} | "
          f"TEST → {pd.to_datetime(int(df['time'].iloc[-1]), unit='s'):%Y-%m-%d} | SL={a.k}×ATR RR={a.rr} giữ ≤{a.horizon} nến spread={a.spread}")

    from statistics import NormalDist
    a.zthr = max(a.min_z, NormalDist().inv_cdf(1 - 0.05 / max(len(names), 1)))
    print(f"Ngưỡng ĐẠT trên TEST: z ≥ {a.zthr:.2f} (một phía 5%, hiệu chỉnh cho {len(names)} mô hình tuner cùng lúc)")
    results = {n: (wf_structure(n, ctxs, m, start, a, df['time'].to_numpy()) if a.walk_forward else tune_one(n, ctxs, m, split, start, a)) for n in names}
    if len(results) > 1:
        print_summary(results, a)
    if a.write_config:
        cp = a.config_path or SP.CONFIG_PATH
        wrote = write_config(cp, results, a, df)
        print(f"\n💾 Đã ghi {len(wrote)} mô hình vào {cp}: {wrote}" if wrote else
              "\n⚠️ Không có mô hình nào đạt kiểm tra TEST nên chưa ghi gì (dùng --force để ghi bộ tốt nhất dù không đạt).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
