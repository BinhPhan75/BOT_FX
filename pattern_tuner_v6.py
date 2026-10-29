# pattern_tuner_v6.py
"""
DO THAM SO TUNG MO HINH NEN tren du lieu lich su - giong chinh thong so indicator:
    1. Chon 1-2 mo hinh (--patterns BULLISH_ENGULFING,BEARISH_ENGULFING).
    2. Chay hang tram to hop tham so cua DINH NGHIA mo hinh (than nen, ty le bong, do xuyen, boi canh...) tren lich su.
    3. Xep hang theo ket qua (EV/lenh sau spread, WR, PF) tren 70% du lieu dau (TRAIN).
    4. Kiem tra bo tot nhat tren 30% du lieu sau (TEST - chua dung de chon gi). Chi bo nao giu duoc ket qua moi duoc ghi vao bot.
    5. --write-config ghi tham so vao ai_v6/candle_params.json; bot (scanner_v6) doc file nay.

Cac tham so la hang so trong dinh nghia ly thuyet cua mo hinh; bo "ai_v5 goc" (da kiem tra tuuong duong 100%) va "v6 mac dinh" luon
duoc in ra de so sanh.

CACH DUNG:
    py -3.11 pattern_tuner_v6.py --csv bt_cache\\XAUUSD_M5_1y.csv --tf M5 --patterns BULLISH_ENGULFING,BEARISH_ENGULFING \\
        --k 1.0 --rr 1.3 --horizon 6 --spread 0.25 --hours-vn 8-18
    ... them --write-config de ghi bo tham so DAT vao bot (--force de ghi ca bo khong dat).
    --patterns ORIGINAL (12 mo hinh ai_v5) | EXTRA (12 mo hinh bo sung) | ALL
"""
import argparse
import itertools
import json
import os
import random
import sys
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import candle_params_v6 as CP  # noqa: E402
import pattern_lab_v6 as L  # noqa: E402


def perf(m, idx, d, lo, hi):
    """Thong ke tin hieu (declustered) trong [lo,hi) so voi baseline ngau nhien CUNG bo loc."""
    H = m.H
    ev, last = [], -10 ** 9
    for i in idx:
        if i < lo:
            continue
        if i >= hi:
            break
        if i - last >= H and m.mask[d][i]:
            ev.append(i)
            last = i
    seg = m.R[d][lo:hi][m.mask[d][lo:hi]]
    seg = seg[~np.isnan(seg)]
    rs = m.R[d][ev] if ev else np.array([])
    rs = rs[~np.isnan(rs)]
    out = {"n": len(rs), "wr": np.nan, "ev": np.nan, "pf": np.nan, "lcb": np.nan, "lift": np.nan, "z": np.nan,
           "base": float(seg.mean()) if len(seg) else np.nan}
    if len(rs) >= 3:
        pos, neg = rs[rs > 0].sum(), -rs[rs < 0].sum()
        se = rs.std(ddof=1) / np.sqrt(len(rs))
        out.update(wr=float((rs > 0).mean()), ev=float(rs.mean()), pf=float(pos / neg) if neg > 0 else float("inf"),
                   lcb=float(rs.mean() - se))
        if len(seg) > 50:
            se_b = seg.std(ddof=1) / np.sqrt(max(len(seg) / H, 5))
            out.update(lift=float(rs.mean() - seg.mean()), z=float((rs.mean() - seg.mean()) / np.sqrt(se ** 2 + se_b ** 2)))
    return out


def fmt_params(P, keys):
    return " ".join(f"{k.replace('_atr', '').replace('ctx_min', 'ctx').replace('ctx_lookback', 'L').replace('min_body', 'body')}={P[k]}" for k in keys)


def row_str(tag, P, keys, tr, te):
    f = lambda v, p=".1%": ("   -  " if v is None or (isinstance(v, float) and np.isnan(v)) else format(v, p))
    return (f"{tag:>4s}  {fmt_params(P, keys):62.62s} | {tr['n']:4d} {f(tr['wr']):>6s} {f(tr['ev'], '+.3f'):>7s} {f(tr['pf'], '.2f'):>5s}"
            f" | {te['n']:4d} {f(te['wr']):>6s} {f(te['ev'], '+.3f'):>7s} {f(te['pf'], '.2f'):>5s} {f(te['lift'], '+.2f'):>6s} {f(te['z'], '.1f'):>5s}")


def tune_pattern(name, A, m, split, a):
    d = CP.DIRECTION[name]
    grid = CP.PARAM_GRID[name]
    keys = list(grid)
    combos = list(itertools.product(*[grid[k] for k in keys]))
    total = len(combos)
    if a.max_combos and total > a.max_combos:
        random.Random(1).shuffle(combos)
        combos = combos[:a.max_combos]
    rows = []
    for combo in combos:
        P = {**CP.DEFAULTS[name], **dict(zip(keys, combo))}
        idx = np.nonzero(CP.mask(name, A, P))[0]
        rows.append((P, perf(m, idx, d, L.WARMUP, split - m.H), perf(m, idx, d, split, m.n)))

    def ref(P):
        idx = np.nonzero(CP.mask(name, A, P))[0]
        return perf(m, idx, d, L.WARMUP, split - m.H), perf(m, idx, d, split, m.n)

    score = {"lcb": "lcb", "ev": "ev", "pf": "pf"}[a.score]
    valid = [r for r in rows if r[1]["n"] >= a.min_trades and not np.isnan(r[1][score])]
    valid.sort(key=lambda r: -r[1][score])
    seen, uniq = set(), []                       # nhieu to hop tham so cho CUNG tap tin hieu -> chi giu 1 (dung dau bang xep hang)
    for r in valid:
        sig = (r[1]["n"], round(r[1]["ev"], 6), r[2]["n"], round(r[2]["ev"], 6) if not np.isnan(r[2]["ev"]) else None)
        if sig not in seen:
            seen.add(sig)
            uniq.append(r)
    valid = uniq
    print("\n" + "=" * 140)
    print(f"{name} ({'BUY' if d == 1 else 'SELL'}) — {len(combos)}/{total} tổ hợp thử | {len(valid)} bộ kết quả khác nhau có ≥{a.min_trades} lệnh ở TRAIN | xếp hạng theo {a.score.upper()} (TRAIN)")
    b_tr = perf(m, np.array([], int), d, L.WARMUP, split - m.H)
    b_te = perf(m, np.array([], int), d, split, m.n)
    print(f"Ngẫu nhiên cùng bộ lọc/SL/TP/spread — EV mỗi lệnh: TRAIN {b_tr['base']:+.3f}R | TEST {b_te['base']:+.3f}R")
    print("=" * 140)
    print(f"{'hạng':>4s}  {'tham số':62s} | {'TRAIN n':>7s} {'WR':>6s} {'EV(R)':>7s} {'PF':>5s} | {'TEST n':>6s} {'WR':>6s} {'EV(R)':>7s} {'PF':>5s} {'lift':>6s} {'z':>5s}")
    for rank, (P, tr, te) in enumerate(valid[:a.top], 1):
        print(row_str(str(rank), P, keys, tr, te))
    if name in CP.ORDER:
        tr, te = ref(CP.ORIGINAL[name])
        print(row_str("gốc", CP.ORIGINAL[name], keys, tr, te))
    tr, te = ref(CP.DEFAULTS[name])
    print(row_str("v6", CP.DEFAULTS[name], keys, tr, te))
    if not valid:
        print("→ KẾT LUẬN: không tổ hợp nào đủ số lệnh ở TRAIN (tăng dữ liệu hoặc giảm --min-trades).")
        return None
    best = valid[0]
    top5_te = [r[2]["ev"] for r in valid[:5] if r[2]["n"] >= a.min_test and not np.isnan(r[2]["ev"])]
    ok = (best[2]["n"] >= a.min_test and best[2]["ev"] > 0 and not np.isnan(best[2]["lift"]) and best[2]["lift"] > 0
          and not np.isnan(best[2]["z"]) and best[2]["z"] >= a.zthr)
    print(f"→ Tốt nhất (TRAIN): {fmt_params(best[0], keys)}")
    print(f"  TEST: {best[2]['n']} lệnh, WR {best[2]['wr']:.1%}, EV {best[2]['ev']:+.3f}R (ngẫu nhiên {best[2]['base']:+.3f}R, lift {best[2]['lift']:+.3f}, z {best[2]['z']:.1f})"
          if best[2]["n"] >= 3 else f"  TEST: chỉ {best[2]['n']} lệnh — không đủ để kiểm tra")
    if top5_te:
        print(f"  EV TEST trung bình của top-5 theo TRAIN: {np.mean(top5_te):+.3f}R (nếu thấp hơn nhiều so với TRAIN = bộ tham số 'tốt' chủ yếu do may mắn)")
    print("  " + (f"✅ ĐẠT: giữ được EV dương và hơn ngẫu nhiên có ý nghĩa (z ≥ {a.zthr:.2f}) trên dữ liệu kiểm tra" if ok else
                  f"❌ KHÔNG ĐẠT: trên dữ liệu kiểm tra cần EV > 0, hơn ngẫu nhiên với z ≥ {a.zthr:.2f} và ≥ {a.min_test} lệnh"))
    return {"params": {k: best[0][k] for k in best[0]}, "train": best[1], "test": best[2], "ok": bool(ok)}


def wf_candle(name, A, m, a):
    d = CP.DIRECTION[name]
    grid = CP.PARAM_GRID[name]
    keys = list(grid)
    combos = list(itertools.product(*[grid[k] for k in keys]))
    if a.max_combos and len(combos) > a.max_combos:
        random.Random(1).shuffle(combos)
        combos = combos[:a.max_combos]
    plist = [{**CP.DEFAULTS[name], **dict(zip(keys, c))} for c in combos]
    idxlist = [np.nonzero(CP.mask(name, A, P))[0] for P in plist]
    return walk_forward(name, d, m, plist, idxlist, keys, L.WARMUP, a, A.get("_times"))


def print_summary(results, a):
    """Bang tong ket cuoi cung cho nhieu mo hinh: de doc nhanh mo hinh nao DAT."""
    print("\n" + "=" * 118)
    wf = bool(getattr(a, "walk_forward", 0))
    print(f"TỔNG KẾT ({len(results)} mô hình) — " + ("GỘP OOS walk-forward: " if wf else "") + f"ngưỡng ĐẠT: EV > 0, lift > 0, z ≥ {a.zthr:.2f}, ≥ {a.min_test} lệnh")
    print("=" * 118)
    print(f"{'mô hình':34s}{('chọn n' if wf else 'TRAIN n'):>8s}{'EV(R)':>8s}{('OOS n' if wf else 'TEST n'):>8s}{'WR':>7s}{'EV(R)':>8s}{'lift':>8s}{'z':>6s}  kết quả")
    f = lambda v, p: ("   -" if v is None or (isinstance(v, float) and np.isnan(v)) else format(v, p))
    for name, r in results.items():
        if r is None:
            print(f"{name:34s}{'-':>8s}{'-':>8s}{'-':>8s}{'-':>7s}{'-':>8s}{'-':>8s}{'-':>6s}  không đủ lệnh ở TRAIN")
            continue
        tr, te = r["train"], r["test"]
        print(f"{name:34s}{tr['n']:>8d}{f(tr['ev'], '+.3f'):>8s}{te['n']:>8d}{f(te['wr'], '.1%'):>7s}{f(te['ev'], '+.3f'):>8s}"
              f"{f(te['lift'], '+.3f'):>8s}{f(te['z'], '.1f'):>6s}  {'✅ ĐẠT' if r['ok'] else '❌ không đạt'}")


def events_R(m, idx, d, lo, hi):
    """R cua cac tin hieu (declustered) va baseline ngau nhien cung bo loc trong [lo,hi)."""
    H = m.H
    ev, last = [], -10 ** 9
    for i in idx:
        if i < lo:
            continue
        if i >= hi:
            break
        if i - last >= H and m.mask[d][i]:
            ev.append(i)
            last = i
    rs = m.R[d][ev] if ev else np.array([])
    rs = rs[~np.isnan(rs)]
    seg = m.R[d][lo:hi][m.mask[d][lo:hi]]
    return rs, seg[~np.isnan(seg)]


def pooled_stats(rs_list, seg_list, H):
    rs = np.concatenate(rs_list) if rs_list else np.array([])
    seg = np.concatenate(seg_list) if seg_list else np.array([])
    out = {"n": len(rs), "wr": np.nan, "ev": np.nan, "pf": np.nan, "lcb": np.nan, "lift": np.nan, "z": np.nan,
           "base": float(seg.mean()) if len(seg) else np.nan}
    if len(rs) >= 3 and len(seg) > 50:
        pos, neg = rs[rs > 0].sum(), -rs[rs < 0].sum()
        se = rs.std(ddof=1) / np.sqrt(len(rs))
        se_b = seg.std(ddof=1) / np.sqrt(max(len(seg) / H, 5))
        out.update(wr=float((rs > 0).mean()), ev=float(rs.mean()), pf=float(pos / neg) if neg > 0 else float("inf"), lcb=float(rs.mean() - se),
                   lift=float(rs.mean() - seg.mean()), z=float((rs.mean() - seg.mean()) / np.sqrt(se ** 2 + se_b ** 2)))
    return out


def walk_forward(name, d, m, plist, idxlist, keys, start, a, times=None):
    """WALK-FORWARD (mo rong dan): chia [start,n) thanh K+1 doan; voi doan j=1..K chon tham so tot nhat tren du lieu TRUOC doan j,
    roi do tren doan j (chua tung dung de chon). Gop ket qua cac doan -> kiem tra tren ~K/(K+1) du lieu thay vi 30%."""
    n, H, K = m.n, m.H, a.walk_forward
    segs = np.linspace(start, n, K + 2).astype(int)
    fmt_t = (lambda i: f"{pd.to_datetime(int(times[min(i, n - 1)]), unit='s'):%y-%m-%d}") if times is not None else (lambda i: str(i))
    print("\n" + "=" * 140)
    print(f"{name} ({'BUY' if d == 1 else 'SELL'}) — WALK-FORWARD {K} đoạn | {len(plist)} tổ hợp | chọn theo {a.score.upper()} trên dữ liệu TRƯỚC, đo trên đoạn kế tiếp")
    print("=" * 140)
    print(f"{'đoạn kiểm tra':>20s}  {'tham số chọn (trên dữ liệu trước đó)':56s} | {'chọn n':>6s} {'EV':>7s} | {'OOS n':>5s} {'WR':>6s} {'EV(R)':>7s} {'ngẫu nhiên':>10s}")
    rs_l, seg_l, pos = [], [], 0
    folds = 0
    for j in range(1, K + 1):
        thr = max(10, int(round(a.min_trades * (segs[j] - start) / (0.7 * (n - start)))))
        best, best_i = None, -1
        for pi, (P, idx) in enumerate(zip(plist, idxlist)):
            t = perf(m, idx, d, start, segs[j] - H)
            if t["n"] >= thr and not np.isnan(t[a.score]) and (best is None or t[a.score] > best[1][a.score]):
                best, best_i = (P, t), pi
        lab = f"{fmt_t(segs[j])}→{fmt_t(segs[j + 1])}"
        if best is None:
            print(f"{lab:>20s}  (không bộ nào đủ {thr} lệnh trên dữ liệu trước đó — bỏ qua đoạn này)")
            continue
        rs, seg = events_R(m, idxlist[best_i], d, segs[j], segs[j + 1])
        rs_l.append(rs)
        seg_l.append(seg)
        folds += 1
        ev = rs.mean() if len(rs) else float("nan")
        bs = seg.mean() if len(seg) else float("nan")
        pos += int(len(rs) >= 3 and ev > bs)
        print(f"{lab:>20s}  {fmt_params(best[0], keys):56.56s} | {best[1]['n']:6d} {best[1]['ev']:+7.3f} | {len(rs):5d} "
              f"{((rs > 0).mean() if len(rs) else float('nan')):6.1%} {ev:+7.3f} {bs:+10.3f}")
    pool = pooled_stats(rs_l, seg_l, H)
    # tham so cuoi cung (neu dat): tot nhat tren TOAN BO du lieu
    full = [(perf(m, idx, d, start, n), P) for P, idx in zip(plist, idxlist)]
    full = [x for x in full if x[0]["n"] >= a.min_trades and not np.isnan(x[0][a.score])]
    full.sort(key=lambda x: -x[0][a.score])
    print("-" * 140)
    if pool["n"] >= 3 and not np.isnan(pool["z"]):
        print(f"GỘP OOS: {pool['n']} lệnh | WR {pool['wr']:.1%} | EV {pool['ev']:+.3f}R | ngẫu nhiên {pool['base']:+.3f}R | lift {pool['lift']:+.3f}R | z {pool['z']:.1f} | "
              f"{pos}/{folds} đoạn hơn ngẫu nhiên")
    else:
        print(f"GỘP OOS: chỉ {pool['n']} lệnh — không đủ để kết luận")
    ok = bool(pool["n"] >= a.min_test and not np.isnan(pool["z"]) and pool["ev"] > 0 and pool["lift"] > 0 and pool["z"] >= a.zthr and folds >= 2)
    print("  " + (f"✅ ĐẠT: gộp OOS có EV dương và hơn ngẫu nhiên (z ≥ {a.zthr:.2f})" if ok else
                  f"❌ KHÔNG ĐẠT: cần gộp OOS có EV > 0, hơn ngẫu nhiên với z ≥ {a.zthr:.2f}, ≥ {a.min_test} lệnh và ≥ 2 đoạn"))
    if not full:
        return {"params": dict(plist[0]), "train": perf(m, np.array([], int), d, start, n), "test": pool, "ok": False}
    return {"params": dict(full[0][1]), "train": full[0][0], "test": pool, "ok": ok}


def write_config(path, results, a, df):
    cfg = {"_meta": {}, "patterns": {}, "enabled_extra": []}
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
                              "hours_vn": a.hours_vn, "bias": bool(a.bias_csv), "data_to": pd.to_datetime(int(df['time'].iloc[-1]), unit='s').isoformat(),
                              "train": {k: (None if np.isnan(v) else v) for k, v in r["train"].items() if k in ("n", "wr", "ev", "pf")},
                              "test": {k: (None if np.isnan(v) else v) for k, v in r["test"].items() if k in ("n", "wr", "ev", "pf", "lift", "z")},
                              "written": datetime.now().isoformat(timespec="seconds")}
        if name in CP.ORDER_EXTRA and name not in cfg["enabled_extra"]:
            cfg["enabled_extra"].append(name)
        wrote.append(name)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    json.dump(cfg, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return wrote


def main(argv=None):
    ap = argparse.ArgumentParser(description="Dò tham số từng mô hình nến trên dữ liệu lịch sử")
    ap.add_argument("--patterns", required=False, default="", help="tên, cách nhau dấu phẩy | ORIGINAL | EXTRA | ALL")
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
    ap.add_argument("--train-frac", type=float, default=0.7)
    ap.add_argument("--min-trades", type=int, default=30)
    ap.add_argument("--min-test", type=int, default=15)
    ap.add_argument("--min-z", type=float, default=1.65, help="TEST: lift phai co z >= nguong nay (tu dong tang theo so mo hinh thu cung luc - Bonferroni)")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--score", choices=["lcb", "ev", "pf"], default="lcb", help="lcb = EV trừ 1 sai số chuẩn (tránh mẫu nhỏ may mắn)")
    ap.add_argument("--max-combos", type=int, default=0)
    ap.add_argument("--walk-forward", type=int, default=0, help="K>0: walk-forward K doan (khuyen nghi 4) thay cho chia 70/30")
    ap.add_argument("--write-config", action="store_true")
    ap.add_argument("--force", action="store_true", help="ghi cả bộ KHÔNG đạt kiểm tra TEST")
    ap.add_argument("--config-path", type=str, default=None)
    a = ap.parse_args(argv)

    if not a.patterns:
        print("Chọn mô hình bằng --patterns. Có sẵn:\n  ORIGINAL:", ", ".join(CP.ORDER), "\n  EXTRA   :", ", ".join(CP.ORDER_EXTRA))
        return 1
    groups = {"ORIGINAL": CP.ORDER, "EXTRA": CP.ORDER_EXTRA, "ALL": CP.ALL_PATTERNS}
    names = []
    for tok in [x.strip().upper() for x in a.patterns.split(",") if x.strip()]:
        for n in (groups[tok] if tok in groups else [tok]):
            if n not in names:
                names.append(n)
    bad = [n for n in names if n not in CP.ALL_PATTERNS]
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
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    A = CP.prep(o, h, l, c, m.atr)
    split = int(L.WARMUP + (m.n - L.WARMUP) * a.train_frac)
    print(f"Chia dữ liệu: TRAIN {pd.to_datetime(int(df['time'].iloc[L.WARMUP]), unit='s'):%Y-%m-%d} → {pd.to_datetime(int(df['time'].iloc[split]), unit='s'):%Y-%m-%d} | "
          f"TEST → {pd.to_datetime(int(df['time'].iloc[-1]), unit='s'):%Y-%m-%d} | SL={a.k}×ATR RR={a.rr} giữ ≤{a.horizon} nến spread={a.spread}")

    from statistics import NormalDist
    a.zthr = max(a.min_z, NormalDist().inv_cdf(1 - 0.05 / max(len(names), 1)))
    print(f"Ngưỡng ĐẠT trên TEST: z ≥ {a.zthr:.2f} (một phía 5%, hiệu chỉnh cho {len(names)} mô hình tuner cùng lúc)")
    A["_times"] = df["time"].to_numpy()
    results = {n: (wf_candle(n, A, m, a) if a.walk_forward else tune_pattern(n, A, m, split, a)) for n in names}
    if len(results) > 1:
        print_summary(results, a)
    if a.write_config:
        cp = a.config_path or CP.CONFIG_PATH
        wrote = write_config(cp, results, a, df)
        print(f"\n💾 Đã ghi {len(wrote)} mô hình vào {cp}: {wrote}" if wrote else
              "\n⚠️ Không có mô hình nào đạt kiểm tra TEST nên chưa ghi gì (dùng --force để ghi bộ tốt nhất dù không đạt).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
