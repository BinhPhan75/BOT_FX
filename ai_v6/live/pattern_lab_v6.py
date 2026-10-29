# pattern_lab_v6.py
"""
PHONG THI NGHIEM MO HINH (pattern lab) - kiem chung tung mo hinh tren LICH SU NHIEU NAM (H1/M15/M5), khong cho live.

CAU HOI NO TRA LOI cho tung mo hinh (ten + chieu):
    "Vao lenh theo tin hieu nay co TOT HON vao lenh NGAU NHIEN (cung SL/TP/thoi gian giu) khong, va co ben vung giua
     nua dau (IS) va nua sau (OOS) cua lich su khong?"

VI SAO CAN SO VOI NGAU NHIEN: voi SL=k*ATR, TP=RR*SL, vao lenh NGAU NHIEN da cho win rate ~ 1/(1+RR)
(RR=1.3 -> ~43.5%). Dataset live cua ai_v6 dang o ~43% => TIN HIEU HIEN TAI KHONG HON NGAU NHIEN, khong phai "SL/TP sai".
Chi so dung de danh gia mo hinh la LIFT (EV tin hieu - EV ngau nhien) va z-score, khong phai win rate tuyet doi.

QUY UOC CHONG ROI RO / LOOKAHEAD:
    - Tin hieu chi dung nen DA DONG toi bar i; vao lenh tai OPEN cua bar i+1.
    - Cung 1 nen cham ca SL va TP -> tinh la SL truoc (bao thu).
    - Cac tin hieu cung ten+chieu cach nhau < H bar bi gop (declustering) de ket qua khong chong lan.
    - Nua dau (IS) / nua sau (OOS) theo thoi gian; ket luan chi "CO LOI THE" khi cung chieu o CA HAI nua va z >= 2.5.
    - Sweep tham so: chon tham so tren IS, bao cao ket qua OOS (walk-forward), khong chon tren toan bo.

CACH DUNG:
    py -3.11 pattern_lab_v6.py --selftest
    py -3.11 pattern_lab_v6.py --csv bt_cache\\XAUUSD_M15.csv --tf M15 --detector candle_old,candle_v6
    py -3.11 pattern_lab_v6.py --mt5 --years 3 --tf M15 --detector candle_old,candle_v6 --save-csv
    py -3.11 pattern_lab_v6.py --csv ... --tf M15 --detector candle_v6 --sweep
    py -3.11 pattern_lab_v6.py --csv ... --tf M15 --detector v5_live --step 3 --max-bars 40000
    py -3.11 pattern_lab_v6.py --csv ... --tf M15 --detector v5_live --set ai_v5.pipeline.ict_patterns.MIN_FVG_SIZE_ATR=0.5
"""
import argparse
import ast
import glob
import importlib
import importlib.util
import itertools
import os
import random
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}
MIN_N = 30            # it hon -> "it mau"
Z_STRONG = 2.5        # nguong z de ket luan (da tinh den viec thu nhieu mau hinh)
WARMUP = 300
ATR_PERIOD = 14


# =============================== NAP DU LIEU ===============================
def _sniff_sep(path: str) -> str:
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        head = f.readline()
    return max([",", "\t", ";", "|"], key=head.count)


def _to_epoch_seconds(t: pd.Series) -> pd.Series:
    """Datetime (UTC) -> epoch giay, khong phu thuoc do phan giai ns/us/s cua pandas."""
    return ((t - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(seconds=1)).astype("int64")


def _parse_dt(series: pd.Series) -> pd.Series:
    """Parse chuoi thoi gian da dang (ca dinh dang MT5 'YYYY.MM.DD'); thu tung format co dinh truoc."""
    ser = series.astype(str).str.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y.%m.%d %H:%M",
                "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%d.%m.%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        t = pd.to_datetime(ser, format=fmt, utc=True, errors="coerce")
        if t.notna().mean() >= 0.95:
            return t
    return pd.to_datetime(ser, utc=True, errors="coerce", format="mixed")


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, sep=_sniff_sep(path), encoding="utf-8-sig")
    df.columns = [str(c).strip().lower().strip("<>").replace(" ", "_") for c in df.columns]
    if "date" in df.columns and "time" in df.columns and not pd.api.types.is_numeric_dtype(df["time"]):   # xuat tu MT5: <DATE> <TIME>
        t = _to_epoch_seconds(_parse_dt(df["date"].astype(str) + " " + df["time"].astype(str)))
    else:
        col = next((c for c in ("time", "datetime", "timestamp", "date") if c in df.columns), None)
        if col is None:
            raise ValueError(f"{path}: không tìm thấy cột thời gian trong {list(df.columns)}")
        if pd.api.types.is_numeric_dtype(df[col]):
            v = df[col].astype("int64")
            t = v // 1000 if v.max() > 10**12 else v          # epoch ms hoac giay
        else:
            t = _to_epoch_seconds(_parse_dt(df[col]))
    vol = next((c for c in ("tick_volume", "tickvol", "volume", "vol") if c in df.columns), None)
    out = pd.DataFrame({"time": t, "open": df["open"], "high": df["high"], "low": df["low"],
                        "close": df["close"], "volume": df[vol] if vol else 0.0})
    out = out.dropna().drop_duplicates("time").sort_values("time").reset_index(drop=True)
    return out.astype({"time": "int64", "open": float, "high": float, "low": float, "close": float, "volume": float})


def load_mt5(symbol: str, tf: str, years: float) -> pd.DataFrame:
    """Keo lich su tu MT5. Thu copy_rates_range; neu terminal tu choi (vd -2 Invalid params) thi lay tung doan
    bang copy_rates_from_pos (cach bot dang dung). Tra ve DataFrame chi gom nen DA DONG."""
    import MetaTrader5 as mt5
    from datetime import datetime, timedelta, timezone
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize thất bại: {mt5.last_error()}")
    try:
        tf_const = getattr(mt5, f"TIMEFRAME_{tf}")
        info = mt5.symbol_info(symbol)
        if info is None:
            names = [x.name for x in (mt5.symbols_get() or []) if "XAU" in x.name.upper() or "GOLD" in x.name.upper()]
            raise RuntimeError(f"Không thấy symbol '{symbol}' trên terminal. Symbol vàng của broker: {names[:15]} → dùng --symbol <tên>")
        if not info.visible:
            mt5.symbol_select(symbol, True)
        ti = mt5.terminal_info()
        print(f"ℹ️  MT5: max bars/chart = {getattr(ti, 'maxbars', '?')} | symbol {symbol} | khung {tf}")

        d_to = datetime.now(timezone.utc).replace(tzinfo=None)             # thu bang datetime NAIVE (UTC)
        d_from = d_to - timedelta(days=int(365 * years))
        rates = mt5.copy_rates_range(symbol, tf_const, d_from, d_to)
        method = "copy_rates_range"
        drop_last = True                                                    # range co the gom nen dang chay
        if rates is None or len(rates) == 0:
            print(f"⚠️ copy_rates_range lỗi {mt5.last_error()} → chuyển sang copy_rates_from_pos theo từng đoạn")
            target = int(years * 365 * (86400 / TF_SECONDS[tf]) * 5 / 7)    # so nen can (xap xi, bo cuoi tuan)
            chunks, pos, chunk = [], 1, 20000                               # pos=1 bo qua nen dang chay
            while sum(len(c) for c in chunks) < target:
                r = mt5.copy_rates_from_pos(symbol, tf_const, pos, chunk)
                if r is None or len(r) == 0:
                    print(f"   dừng ở pos={pos}: {mt5.last_error()}")
                    break
                chunks.append(r)
                pos += len(r)
                if len(r) < chunk:
                    break
            rates = np.concatenate(chunks[::-1]) if chunks else None
            method, drop_last = "copy_rates_from_pos (từng đoạn)", False
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"MT5 không trả dữ liệu {symbol} {tf}: {mt5.last_error()}. Thử: mở chart {symbol} {tf} trong MT5, "
                               f"cuộn về quá khứ cho tải đủ lịch sử, đặt Tools→Options→Charts→Max bars in chart = Unlimited rồi chạy lại.")
        df = pd.DataFrame(rates)
        out = pd.DataFrame({"time": df["time"].astype("int64"), "open": df["open"], "high": df["high"], "low": df["low"],
                            "close": df["close"], "volume": df["tick_volume"].astype(float)})
        out = out.drop_duplicates("time").sort_values("time").reset_index(drop=True)
        if drop_last:
            out = out.iloc[:-1]
        cutoff = out["time"].iloc[-1] - int(365 * years * 86400)
        out = out[out["time"] >= cutoff].reset_index(drop=True)
        print(f"✅ Lấy được {len(out)} nến bằng {method}")
        return out
    finally:
        mt5.shutdown()


def autodiscover(bt_dir: str, symbol: str, tf: str):
    pats = [f"*{symbol}*{tf}*.csv", f"*{tf}*{symbol}*.csv", f"*{tf}*.csv"]
    for p in pats:
        hits = glob.glob(os.path.join(bt_dir, p))
        if hits:
            return max(hits, key=os.path.getsize)
    return None


def describe(df: pd.DataFrame, tf: str):
    n = len(df)
    span_y = (df["time"].iloc[-1] - df["time"].iloc[0]) / 86400 / 365
    step = int(df["time"].diff().median())
    print(f"📂 {n} nến {tf} | {pd.to_datetime(df['time'].iloc[0], unit='s')} → {pd.to_datetime(df['time'].iloc[-1], unit='s')} "
          f"(~{span_y:.1f} năm) | bước thời gian trung vị {step}s (kỳ vọng {TF_SECONDS.get(tf)}s)")
    if TF_SECONDS.get(tf) and step != TF_SECONDS[tf]:
        print("⚠️ Bước thời gian không khớp khung — kiểm tra lại --tf hoặc file CSV.")


# =============================== MO PHONG TIEN VE ===============================
def calc_atr(h, l, period=ATR_PERIOD):
    """TB (high-low) `period` nen - GIONG ATR trong live_pattern_scanner cua ai_v5."""
    rng = pd.Series(h - l)
    return rng.rolling(period).mean().to_numpy()


def forward_R(o, h, l, c, atr, k, rr, H, dirn):
    """R thuc te cua lenh vao tai OPEN nen i+1, SL=k*ATR, TP=rr*SL, giu toi da H nen. NaN neu thieu du lieu."""
    n = len(c)
    entry = np.full(n, np.nan)
    entry[:-1] = o[1:]
    sl_d = k * atr
    valid = (~np.isnan(entry)) & (~np.isnan(atr)) & (atr > 0)
    valid[max(n - H, 0):] = False
    sl = entry - dirn * sl_d
    tp = entry + dirn * rr * sl_d
    R = np.full(n, np.nan)
    alive = valid.copy()
    for j in range(1, H + 1):
        m = n - j
        hi, lo = h[j:j + m], l[j:j + m]
        a = alive[:m]
        if dirn == 1:
            hit_sl, hit_tp = lo <= sl[:m], hi >= tp[:m]
        else:
            hit_sl, hit_tp = hi >= sl[:m], lo <= tp[:m]
        sl_now = a & hit_sl
        tp_now = a & hit_tp & ~hit_sl
        Rv = R[:m]
        Rv[sl_now] = -1.0
        Rv[tp_now] = rr
        alive[:m] = a & ~(hit_sl | hit_tp)
        if j == H:
            fin = alive[:m]
            Rv[fin] = (c[j:j + m][fin] - entry[:m][fin]) * dirn / sl_d[:m][fin]
            alive[:m] = False
    R[~valid] = np.nan
    return R


class Market:
    """Chuan bi 1 lan: R ngau nhien (baseline) cho moi chieu + drift, theo (k, rr, H, spread)."""

    def __init__(self, df: pd.DataFrame, k: float, rr: float, H: int, spread: float, mask=None):
        self.o, self.h, self.l, self.c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
        self.n, self.H, self.k, self.rr = len(df), H, k, rr
        self.atr = calc_atr(self.h, self.l)
        self.mask = mask if mask is not None else {1: np.ones(self.n, bool), -1: np.ones(self.n, bool)}
        self.R, self.drift = {}, {}
        cost = spread / (k * self.atr) if spread else 0.0
        for d in (1, -1):
            self.R[d] = forward_R(self.o, self.h, self.l, self.c, self.atr, k, rr, H, d) - cost
            dr = np.full(self.n, np.nan)
            idx = np.arange(0, self.n - H - 1)
            dr[idx] = (self.c[idx + H] - self.o[idx + 1]) * d / self.atr[idx]
            self.drift[d] = dr


def _seg_stats(m: Market, idxs, dirn, lo, hi):
    """Thong ke 1 nhom tin hieu (cung ten+chieu) trong doan [lo,hi): declustered, so voi baseline cung doan."""
    H = m.H
    ev, last = [], -10 ** 9
    for i in idxs:
        if lo <= i < hi and i - last >= H and m.mask[dirn][i]:
            ev.append(i)
            last = i
    ev = np.array(ev, dtype=int)
    Rs = m.R[dirn][ev] if len(ev) else np.array([])
    Rs = Rs[~np.isnan(Rs)]
    seg = np.arange(lo, hi)
    Rb = m.R[dirn][seg][m.mask[dirn][seg]]
    Rb = Rb[~np.isnan(Rb)]
    Ds = m.drift[dirn][ev] if len(ev) else np.array([])
    Ds = Ds[~np.isnan(Ds)]
    Db = m.drift[dirn][seg][m.mask[dirn][seg]]
    Db = Db[~np.isnan(Db)]
    out = {"n": len(Rs), "wr": np.nan, "ev": np.nan, "lift": np.nan, "z": np.nan,
           "drift_lift": np.nan, "base_wr": (Rb > 0).mean() if len(Rb) else np.nan,
           "base_ev": Rb.mean() if len(Rb) else np.nan}
    if len(Rs) >= 5 and len(Rb) > 50:
        neff_b = max(len(Rb) / H, 5)
        se = np.sqrt(Rs.var(ddof=1) / len(Rs) + Rb.var(ddof=1) / neff_b)
        out.update(wr=(Rs > 0).mean(), ev=Rs.mean(), lift=Rs.mean() - Rb.mean(),
                   z=(Rs.mean() - Rb.mean()) / se if se > 0 else 0.0)
        if len(Ds) >= 5 and len(Db) > 50:
            out["drift_lift"] = Ds.mean() - Db.mean()
    return out


def evaluate(m: Market, signals, split_frac=0.67):
    """signals: list (i, ten, chieu). Tra ve dict {(ten,chieu): {'ALL':..,'IS':..,'OOS':..}}."""
    n, H = m.n, m.H
    split = int(WARMUP + (n - WARMUP) * split_frac)
    groups = defaultdict(list)
    for i, name, d in signals:
        groups[(name, d)].append(i)
    res = {}
    for key, idxs in groups.items():
        idxs.sort()
        d = key[1]
        res[key] = {"ALL": _seg_stats(m, idxs, d, WARMUP, n), "IS": _seg_stats(m, idxs, d, WARMUP, split - H),
                    "OOS": _seg_stats(m, idxs, d, split, n)}
    return res


def verdict(r):
    a, i, o = r["ALL"], r["IS"], r["OOS"]
    if a["n"] < MIN_N or i["n"] < MIN_N // 3 or o["n"] < MIN_N // 3:
        return "ÍT MẪU"
    si, so = np.sign(i["lift"]), np.sign(o["lift"])
    if a["z"] >= Z_STRONG and si > 0 and so > 0:
        return "CÓ LỢI THẾ"
    if a["z"] <= -Z_STRONG and si < 0 and so < 0:
        return "NGƯỢC CHIỀU"
    return "= NGẪU NHIÊN"


def print_report(title, res, m: Market, min_n=MIN_N):
    be = 1 / (1 + m.rr)
    print("\n" + "=" * 118)
    print(f"{title}")
    bw = {d: (lambda r: float(np.mean(r > 0)) if len(r) else float('nan'))(m.R[d][m.mask[d] & ~np.isnan(m.R[d])]) for d in (1, -1)}
    print(f"Ngẫu nhiên (cùng SL={m.k}×ATR, RR={m.rr}, giữ ≤{m.H} nến): WR BUY {bw[1]:.1%} | WR SELL {bw[-1]:.1%} | "
          f"hòa vốn lý thuyết {be:.1%}  ← WR của tín hiệu chỉ có nghĩa khi CAO HƠN các mức này")
    print("=" * 118)
    print(f"{'mô hình':34s}{'chiều':>5s}{'n':>6s}{'WR':>7s}{'EV(R)':>8s}{'lift':>8s}{'z':>6s}{'z IS':>7s}{'z OOS':>7s}{'drift+':>8s}  kết luận")
    rows = sorted(res.items(), key=lambda kv: -(kv[1]["ALL"]["z"] if not np.isnan(kv[1]["ALL"]["z"]) else -99))
    for (name, d), r in rows:
        a = r["ALL"]
        if a["n"] < min_n:
            continue
        print(f"{name:34s}{'BUY' if d == 1 else 'SELL':>5s}{a['n']:>6d}{a['wr']:>7.1%}{a['ev']:>8.3f}{a['lift']:>8.3f}"
              f"{a['z']:>6.1f}{r['IS']['z']:>7.1f}{r['OOS']['z']:>7.1f}{a['drift_lift']:>8.3f}  {verdict(r)}")
    k = sum(1 for _, r in res.items() if r["ALL"]["n"] >= min_n)
    print(f"({k} mô hình có ≥{min_n} mẫu; thử nhiều mô hình cùng lúc nên chỉ tin kết luận khi z ≥ {Z_STRONG} VÀ cùng chiều ở cả IS lẫn OOS)")


def results_to_df(res, tag):
    rows = []
    for (name, d), r in res.items():
        for seg in ("ALL", "IS", "OOS"):
            s = r[seg]
            rows.append({"detector": tag, "pattern": name, "dir": "BUY" if d == 1 else "SELL", "segment": seg, **s,
                         "verdict": verdict(r) if seg == "ALL" else ""})
    return pd.DataFrame(rows)


# =============================== LOC BIAS XU HUONG + GIO GIAO DICH ===============================
def wilder_adx(h, l, c, period=14):
    """ADX/DI kieu Wilder (xap xi market_regime.calc_adx cua bot; co the lech nho)."""
    up = np.diff(h, prepend=h[0])
    dn = -np.diff(l, prepend=l[0])
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    pc = np.roll(c, 1)
    pc[0] = c[0]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    sm = lambda x: pd.Series(x).ewm(alpha=1 / period, adjust=False).mean().to_numpy()
    atr = np.where(sm(tr) > 0, sm(tr), np.nan)
    pdi, mdi = 100 * sm(pdm) / atr, 100 * sm(mdm) / atr
    dx = 100 * np.abs(pdi - mdi) / np.where((pdi + mdi) > 0, pdi + mdi, np.nan)
    adx = sm(np.nan_to_num(dx))
    return adx, pdi, mdi


def map_bias(times, tf_sec, bias_df, bias_sec, adx_thr, period=14):
    """Bias (+1 BUY, -1 SELL, 0 khong ro) tai moi nen danh gia, chi dung nen bias DA DONG luc nen danh gia dong."""
    adx, pdi, mdi = wilder_adx(bias_df["high"].to_numpy(float), bias_df["low"].to_numpy(float),
                               bias_df["close"].to_numpy(float), period)
    b = np.zeros(len(bias_df), int)
    ok = (adx >= adx_thr) & ~np.isnan(pdi) & ~np.isnan(mdi)
    b[ok & (pdi > mdi)] = 1
    b[ok & (mdi > pdi)] = -1
    b[: period * 3] = 0                                         # warmup chua on dinh
    close_times = bias_df["time"].to_numpy(np.int64) + bias_sec
    idx = np.searchsorted(close_times, np.asarray(times, np.int64) + tf_sec, side="right") - 1
    out = np.zeros(len(times), int)
    good = idx >= 0
    out[good] = b[idx[good]]
    return out


def build_mask(df, tf, bias_csv, bias_tf, bias_adx, hours_vn):
    t = df["time"].to_numpy(np.int64)
    tf_sec = TF_SECONDS[tf]
    ok = np.ones(len(df), bool)
    if hours_vn:
        h0, h1 = (int(x) for x in hours_vn.split("-"))
        hv = ((t + tf_sec + 7 * 3600) // 3600) % 24             # gio VN luc nen dong
        ok &= (hv >= h0) & (hv < h1)
    bias = None
    if bias_csv:
        bias = map_bias(t, tf_sec, load_csv(bias_csv), TF_SECONDS[bias_tf], bias_adx)
    mask = {1: ok & ((bias == 1) if bias is not None else True), -1: ok & ((bias == -1) if bias is not None else True)}
    print(f"🎛️  Bộ lọc kiểu bot: giờ VN {hours_vn or 'mọi giờ'} | bias {bias_tf + ' ADX>=' + str(bias_adx) if bias_csv else 'không'} "
          f"→ nến được phép BUY {mask[1].mean():.1%} | SELL {mask[-1].mean():.1%}")
    return mask


# =============================== BO PHAT HIEN ===============================
def make_candles(df):
    return df[["time", "open", "high", "low", "close", "volume"]].to_dict("records")


def sig_candle(candles, atr, detect_fn, key_dir="direction"):
    sigs = []
    for i in range(WARMUP, len(candles)):
        a = atr[i]
        if not (a > 0):
            continue
        r = detect_fn(candles[i - 11:i + 1], float(a))
        if r:
            sigs.append((i, r["pattern"], 1 if r[key_dir] == "BUY" else -1))
    return sigs


def load_module_from(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def get_old_candle_module(path):
    if path:
        return load_module_from(path, "old_candle")
    from ai_v5.pipeline import candlestick_patterns as old
    return old


def apply_overrides(items):
    for it in items or []:
        target, val = it.split("=", 1)
        modname, attr = target.rsplit(".", 1)
        mod = importlib.import_module(modname)
        setattr(mod, attr, ast.literal_eval(val))
        print(f"⚙️  {target} = {val}")


def sig_v5_live(df, step, max_bars, symbol="XAUUSD", which="v5"):
    if which == "v6":
        from ai_v6.live.scanner_v6 import scan_all_patterns_live      # scanner voi detector DA SUA LOGIC
    else:
        from ai_v5.live.live_pattern_scanner import scan_all_patterns_live   # scanner ai_v5 GOC
    candles = make_candles(df)
    sigs = []
    start = max(WARMUP, len(candles) - max_bars) if max_bars else WARMUP
    total = len(range(start, len(candles), step))
    for cnt, i in enumerate(range(start, len(candles), step)):
        for _stype, mt in scan_all_patterns_live(candles[i - 299:i + 1], symbol):
            sigs.append((i, mt["pattern"], 1 if mt["direction"] == "BUY" else -1))
        if cnt and cnt % 2000 == 0:
            print(f"   … quét {cnt}/{total} vị trí")
    return sigs


# =============================== SWEEP THAM SO (candle_v6) ===============================
DEFAULT_GRID = {
    "MIN_BODY_ATR": [0.0, 0.15, 0.30, 0.50],
    "MIN_PRIOR_MOVE_ATR": [0.0, 0.5, 1.0, 1.5],
    "PRIOR_LOOKBACK": [3, 5, 8],
    "GAP_TOL_ATR": [0.1, 0.3, 99.0],
    "MIN_RANGE_ATR": [0.0, 0.6],
}
QUICK_GRID = {"MIN_BODY_ATR": [0.0, 0.3], "MIN_PRIOR_MOVE_ATR": [0.0, 0.5, 1.0], "PRIOR_LOOKBACK": [5],
              "GAP_TOL_ATR": [0.1, 99.0], "MIN_RANGE_ATR": [0.0, 0.6]}


def run_sweep(df, m: Market, grid, max_combos, seed=1):
    import candlestick_v6 as v6
    candles = make_candles(df)
    names = list(grid)
    combos = list(itertools.product(*[grid[k] for k in names]))
    if max_combos and len(combos) > max_combos:
        random.Random(seed).shuffle(combos)
        combos = combos[:max_combos]
    keep = {k: getattr(v6, k) for k in names}
    store = {}      # combo -> eval result
    print(f"🔬 Sweep {len(combos)} tổ hợp tham số candlestick_v6 (chọn trên IS, báo cáo OOS)...")
    for ci, combo in enumerate(combos):
        for k, v in zip(names, combo):
            setattr(v6, k, v)
        sigs = sig_candle(candles, m.atr, v6.detect_candlestick_patterns_v6)
        store[combo] = evaluate(m, sigs)
        if ci % 20 == 0:
            print(f"   … {ci + 1}/{len(combos)}")
    for k, v in keep.items():
        setattr(v6, k, v)
    return names, store


def report_sweep(names, store, m: Market):
    print("\n" + "=" * 118)
    print("SWEEP — chọn tổ hợp tham số TỐT NHẤT trên nửa ĐẦU (IS), rồi xem nó chạy ra sao trên nửa SAU (OOS, chưa dùng để chọn)")
    print("=" * 118)
    pats = sorted({k for res in store.values() for k in res})
    print(f"{'mô hình':34s}{'chiều':>5s}  {'tham số chọn trên IS':62s}{'n IS':>6s}{'z IS':>7s}{'n OOS':>7s}{'WR OOS':>8s}{'lift OOS':>9s}{'z OOS':>7s}")
    survivors = 0
    for key in pats:
        best, bz = None, -99
        for combo, res in store.items():
            r = res.get(key)
            if not r:
                continue
            i = r["IS"]
            if i["n"] >= MIN_N and not np.isnan(i["z"]) and i["z"] > bz:
                best, bz = combo, i["z"]
        if best is None:
            continue
        r = store[best][key]
        o = r["OOS"]
        p = " ".join(f"{k.replace('MIN_', '').replace('_ATR', '')}={v}" for k, v in zip(names, best))
        flag = "  ✅ giữ được ở OOS" if (o["n"] >= MIN_N // 3 and o["z"] >= 1.5) else ""
        survivors += bool(flag)
        print(f"{key[0]:34s}{'BUY' if key[1] == 1 else 'SELL':>5s}  {p[:62]:62s}{r['IS']['n']:>6d}{r['IS']['z']:>7.1f}{o['n']:>7d}"
              f"{(o['wr'] if o['n'] else float('nan')):>8.1%}{o['lift']:>9.3f}{o['z']:>7.1f}{flag}")
    print(f"→ {survivors}/{len(pats)} mô hình giữ được lợi thế ở OOS (z OOS ≥ 1.5). Phần còn lại: tham số tốt trên IS chỉ là nhiễu.")


# =============================== SELFTEST ===============================
def synth(n=30000, seed=11, plant=False):
    """Chuoi gia M15-like. plant=True: sau moi tin hieu BULLISH/BEARISH_ENGULFING (v6) co drift 6 nen (canh tranh dung huong)."""
    import candlestick_v6 as v6
    r = random.Random(seed)
    p, rows, drift_left, drift_dir = 2000.0, [], 0, 0
    for k in range(n):
        o = p + r.gauss(0, 0.1)
        mu = 0.3 * drift_dir if drift_left > 0 else 0.0
        drift_left = max(0, drift_left - 1)
        c = o + r.gauss(mu, 1.0)
        rows.append({"time": 1_600_000_000 + k * 900, "open": o, "high": max(o, c) + abs(r.gauss(0, 0.5)),
                     "low": min(o, c) - abs(r.gauss(0, 0.5)), "close": c, "volume": 100.0})
        p = c
        if plant and k > 30:
            w = rows[-12:]
            atr = sum(x["high"] - x["low"] for x in rows[-14:]) / 14
            s = v6.detect_candlestick_patterns_v6(w, atr)
            if s and s["pattern"] in ("BULLISH_ENGULFING", "BEARISH_ENGULFING"):
                drift_left, drift_dir = 6, 1 if s["direction"] == "BUY" else -1
    return pd.DataFrame(rows)


def selftest():
    import candlestick_v6 as v6
    print("🧪 SELFTEST 1/2 — dữ liệu NGẪU NHIÊN thuần: không mô hình nào được kết luận 'CÓ LỢI THẾ' (đo tỉ lệ dương tính giả)")
    df = synth(plant=False)
    m = Market(df, 1.0, 1.3, 12, 0.0)
    res = evaluate(m, sig_candle(make_candles(df), m.atr, v6.detect_candlestick_patterns_v6))
    v = [verdict(r) for r in res.values() if r["ALL"]["n"] >= MIN_N]
    fp = sum(x in ("CÓ LỢI THẾ", "NGƯỢC CHIỀU") for x in v)
    bw = np.nanmean(m.R[1] > 0)
    print(f"   WR ngẫu nhiên đo được = {bw:.1%} (lý thuyết ≈ {1 / 2.3:.1%}) | dương tính giả {fp}/{len(v)}")
    assert fp <= max(1, len(v) // 8), "Quá nhiều dương tính giả!"
    print("🧪 SELFTEST 2/2 — CẤY lợi thế vào BULLISH/BEARISH_ENGULFING: lab phải phát hiện")
    df2 = synth(plant=True, seed=5)
    m2 = Market(df2, 1.0, 1.3, 12, 0.0)
    res2 = evaluate(m2, sig_candle(make_candles(df2), m2.atr, v6.detect_candlestick_patterns_v6))
    zs = {k[0]: r["ALL"]["z"] for k, r in res2.items() if k[0] in ("BULLISH_ENGULFING", "BEARISH_ENGULFING")}
    print("   z:", {k: round(v, 1) for k, v in zs.items()})
    assert all(z >= Z_STRONG for z in zs.values()), "Không phát hiện được lợi thế đã cấy!"
    print("✅ SELFTEST đạt: lab không bịa ra lợi thế (dữ liệu nhiễu) và bắt được lợi thế thật (dữ liệu cấy).")


# =============================== MAIN ===============================
def main(argv=None):
    ap = argparse.ArgumentParser(description="Kiểm chứng mô hình trên lịch sử nhiều năm so với vào lệnh ngẫu nhiên")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--csv", type=str)
    ap.add_argument("--bt-cache", type=str, default="bt_cache")
    ap.add_argument("--mt5", action="store_true")
    ap.add_argument("--years", type=float, default=3.0)
    ap.add_argument("--save-csv", action="store_true")
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--tf", default="M15")
    ap.add_argument("--detector", default="candle_old,candle_v6", help="candle_old,candle_v6,v5_live,v6_live (phân tách bằng dấu phẩy)")
    ap.add_argument("--old-candle", type=str, default=None, help="đường dẫn candlestick_patterns.py của ai_v5 (nếu không import được)")
    ap.add_argument("--k", type=float, default=1.0, help="SL = k × ATR(khung đánh giá)")
    ap.add_argument("--rr", type=float, default=1.3)
    ap.add_argument("--horizon", type=int, default=12, help="giữ tối đa H nến")
    ap.add_argument("--spread", type=float, default=0.0, help="spread USD mỗi lệnh (trừ vào R)")
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--max-combos", type=int, default=0)
    ap.add_argument("--step", type=int, default=3, help="v5_live: quét mỗi N nến")
    ap.add_argument("--max-bars", type=int, default=0, help="v5_live: chỉ quét N nến cuối")
    ap.add_argument("--set", action="append", help="module.ATTR=giá_trị (ghi đè hằng số của detector)")
    ap.add_argument("--bias-csv", type=str, default=None, help="CSV khung bias (vd M15) - chi xet tin hieu CUNG CHIEU bias ADX/DI, giong bot")
    ap.add_argument("--bias-tf", default="M15")
    ap.add_argument("--bias-adx", type=float, default=12.0, help="nguong ADX bias (bot: M15_ADX_TREND_THRESHOLD=12)")
    ap.add_argument("--hours-vn", type=str, default=None, help="chi xet tin hieu trong khung gio VN, vd 8-18")
    ap.add_argument("--out", type=str, default=None)
    a = ap.parse_args(argv)

    if a.selftest:
        selftest()
        return 0

    if a.mt5:
        df = load_mt5(a.symbol, a.tf, a.years)
        if a.save_csv:
            p = os.path.join(a.bt_cache, f"{a.symbol}_{a.tf}_{a.years:g}y.csv")
            os.makedirs(a.bt_cache, exist_ok=True)
            df.to_csv(p, index=False)
            print(f"💾 Đã lưu {p}")
    else:
        path = a.csv or autodiscover(a.bt_cache, a.symbol, a.tf)
        if not path or not os.path.exists(path):
            print(f"❌ Không thấy CSV. Thử: --csv đường_dẫn | các file trong {a.bt_cache}: "
                  f"{[os.path.basename(x) for x in glob.glob(os.path.join(a.bt_cache, '*.csv'))][:20]}")
            return 1
        print(f"📄 Dùng {path}")
        df = load_csv(path)
    describe(df, a.tf)
    if len(df) < WARMUP + 1000:
        print("❌ Quá ít dữ liệu.")
        return 1

    apply_overrides(a.set)
    mask = build_mask(df, a.tf, a.bias_csv, a.bias_tf, a.bias_adx, a.hours_vn) if (a.bias_csv or a.hours_vn) else None
    m = Market(df, a.k, a.rr, a.horizon, a.spread, mask)
    dets = [x.strip() for x in a.detector.split(",") if x.strip()]
    all_rows = []

    for det in dets:
        if det == "candle_old":
            old = get_old_candle_module(a.old_candle)
            sigs = sig_candle(make_candles(df), m.atr, old.detect_candlestick_patterns)
            title = f"ai_v5 candlestick_patterns (ĐỊNH NGHĨA GỐC) — {a.symbol} {a.tf}"
        elif det == "candle_v6":
            import candlestick_v6 as v6
            sigs = sig_candle(make_candles(df), m.atr, v6.detect_candlestick_patterns_v6)
            title = f"candlestick_v6 (định nghĩa sửa, tham số mặc định) — {a.symbol} {a.tf}"
        elif det == "v5_live":
            sigs = sig_v5_live(df, a.step, a.max_bars, a.symbol, "v5")
            title = f"ai_v5 scan_all_patterns_live (cả 7 nhóm, ĐỊNH NGHĨA GỐC) — {a.symbol} {a.tf}"
        elif det == "v6_live":
            sigs = sig_v5_live(df, a.step, a.max_bars, a.symbol, "v6")
            title = f"ai_v6 scanner_v6 (cả 7 nhóm, detector ĐÃ SỬA LOGIC) — {a.symbol} {a.tf}"
        else:
            print(f"Bỏ qua detector lạ: {det}")
            continue
        res = evaluate(m, sigs)
        print_report(title, res, m)
        all_rows.append(results_to_df(res, det))

    if a.sweep:
        grid = QUICK_GRID if a.quick else DEFAULT_GRID
        names, store = run_sweep(df, m, grid, a.max_combos)
        report_sweep(names, store, m)

    out = a.out or f"pattern_lab_{a.symbol}_{a.tf}.csv"
    if all_rows:
        pd.concat(all_rows).to_csv(out, index=False)
        print(f"\n💾 Báo cáo chi tiết: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
