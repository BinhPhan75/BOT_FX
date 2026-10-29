# pattern_audit_v6.py
"""
KIEM TRA LOGIC NHAN DIEN (khong lien quan SL/TP, WinProb, gio giao dich): moi ham nhan dien duoc chay tren cac tinh huong
SACH GIAO KHOA ma ket qua dung la da biet truoc (phai nhan ra / khong duoc nhan ra) va so sanh ai_v5 GOC voi v6.

    py -3.11 pattern_audit_v6.py --orig-dir ai_v5\\pipeline

Can dat cac file *_v6.py cung thu muc voi script nay (thu muc goc bot_xutho4).
"""
import argparse
import importlib.util
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def S(t, p, i):
    return {"type": t, "price": p, "index": i}


def C(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c}


def trend(start, step, n):
    out, p = [], start
    for _ in range(n):
        q = p + step
        out.append(C(p, max(p, q) + .3, min(p, q) - .3, q))
        p = q
    return out


def name(r):
    return r["pattern"] if r else None


def run(orig_dir):
    import candlestick_v6 as cv, harmonic_v6 as hv, divergence_v6 as dv, ict_v6 as iv, continuation_v6 as kv
    import pattern_rules_v6 as gv, vsa_v6 as sv
    oc = load(os.path.join(orig_dir, "candlestick_patterns.py"), "o_c")
    oh = load(os.path.join(orig_dir, "harmonic_patterns.py"), "o_h")
    od = load(os.path.join(orig_dir, "divergence_patterns.py"), "o_d")
    oi = load(os.path.join(orig_dir, "ict_patterns.py"), "o_i")
    ok = load(os.path.join(orig_dir, "continuation_patterns.py"), "o_k")
    og = load(os.path.join(orig_dir, "pattern_rules.py"), "o_g")
    osd = load(os.path.join(orig_dir, "swing_detector.py"), "o_sd")
    ov = load(os.path.join(orig_dir, "vsa_patterns.py"), "o_v")
    T = []   # (nhom, tinh huong, ky vong, ket qua goc, ket qua v6)

    # ---------------- HARMONIC ----------------
    def hbuild(ab_xa, bc_ab, ad_xa):
        X, A = 100.0, 200.0
        B = A - ab_xa * 100
        Cc = B + bc_ab * (A - B)
        return [S("LOW", X, 0), S("HIGH", A, 20), S("LOW", B, 40), S("HIGH", Cc, 60)], A - ad_xa * 100

    def mirror(sw, D):
        return [S("HIGH" if s["type"] == "LOW" else "LOW", 300 - s["price"], s["index"]) for s in sw], 300 - D

    for nm, (a, b, d) in {"GARTLEY": (0.618, 0.618, 0.786), "BAT": (0.5, 0.5, 0.886),
                          "BUTTERFLY": (0.786, 0.5, 1.27), "CRAB": (0.5, 0.886, 1.618)}.items():
        sw, D = hbuild(a, b, d)
        T.append(("Harmonic", f"{nm} tăng đúng tỉ lệ Fibonacci", f"{nm}_BULLISH",
                  name(oh.detect_harmonic_patterns(sw, D, 5.0)), name(hv.detect_harmonic_patterns_v6(sw, D, 5.0))))
        sw2, D2 = mirror(sw, D)
        T.append(("Harmonic", f"{nm} giảm đúng tỉ lệ Fibonacci", f"{nm}_BEARISH",
                  name(oh.detect_harmonic_patterns(sw2, D2, 5.0)), name(hv.detect_harmonic_patterns_v6(sw2, D2, 5.0))))
    sw, D = hbuild(0.2, 0.2, 0.3)
    T.append(("Harmonic", "Cấu trúc ngẫu nhiên (AB/XA=0.2)", None, name(oh.detect_harmonic_patterns(sw, D, 5.0)),
              name(hv.detect_harmonic_patterns_v6(sw, D, 5.0))))

    # ---------------- DIVERGENCE ----------------
    def series(**vals):
        s = pd.Series([50.0] * 140)
        for k, v in vals.items():
            s[int(k[1:])] = v
        return s

    def dcase(label, sw, price, ind_now, ser, cur_index, expect, nm="RSI"):
        T.append(("Divergence", label, expect, name(od.detect_divergence(sw, price, ind_now, ser, 3.0, nm)),
                  name(dv.detect_divergence_v6(sw, cur_index, price, ser, 3.0, nm))))

    dcase("Phân kỳ THƯỜNG tăng (đáy thấp hơn, RSI cao hơn)", [S("LOW", 100, 30), S("LOW", 98, 60)], 99, 40,
          series(i30=30, i60=38), 66, "RSI_BULLISH_DIVERGENCE_REGULAR")
    dcase("Phân kỳ ẨN tăng (đáy cao hơn, RSI thấp hơn)", [S("LOW", 100, 30), S("LOW", 103, 60)], 104, 27,
          series(i30=35, i60=28), 66, "RSI_BULLISH_DIVERGENCE_HIDDEN")
    dcase("Phân kỳ THƯỜNG giảm (đỉnh cao hơn, RSI thấp hơn)", [S("HIGH", 100, 30), S("HIGH", 103, 60)], 102, 60,
          series(i30=70, i60=62), 66, "RSI_BEARISH_DIVERGENCE_REGULAR")
    dcase("Phân kỳ ẨN giảm (đỉnh thấp hơn, RSI cao hơn)", [S("HIGH", 100, 30), S("HIGH", 97, 60)], 96, 70,
          series(i30=60, i60=68), 66, "RSI_BEARISH_DIVERGENCE_HIDDEN")
    dcase("Xu hướng GIẢM thuần túy, KHÔNG có phân kỳ", [S("LOW", 100, 30), S("LOW", 90, 60)], 95, 20,
          series(i30=40, i60=25), 66, None)
    dcase("Xu hướng TĂNG thuần túy, KHÔNG có phân kỳ", [S("HIGH", 100, 30), S("HIGH", 110, 60)], 105, 80,
          series(i30=60, i60=75), 66, None)
    dcase("Phân kỳ thường tăng nhưng đã CŨ 30 nến (chỉ báo 1 lần khi vừa xác nhận)", [S("LOW", 100, 30), S("LOW", 98, 60)],
          99, 40, series(i30=30, i60=38), 90, None)

    # ---------------- ICT ----------------
    base = [C(104, 105, 102, 103), C(103, 104, 100, 101), C(101, 104, 100, 103), C(103, 107, 102, 106), C(106, 108, 105, 107)]
    bos = C(106.5, 113, 106, 112.8)                               # than 6.3 >= 1.5*ATR(4)
    sw_low_last = [S("HIGH", 110, 80), S("LOW", 104, 90)]
    sw_high_last = [S("LOW", 104, 80), S("HIGH", 110, 90)]
    T.append(("ICT", "BOS tăng phá đỉnh cũ, swing cuối là ĐÁY (có nhịp hồi)", "BULLISH_ORDER_BLOCK",
              name(oi.detect_order_block(base + [bos], sw_low_last, 112.8, 4.0)),
              name(iv.detect_order_block_v6(base + [bos], sw_low_last, 100, 112.8, 4.0))))
    T.append(("ICT", "BOS tăng, swing cuối là ĐỈNH (đối chứng)", "BULLISH_ORDER_BLOCK",
              name(oi.detect_order_block(base + [bos], sw_high_last, 112.8, 4.0)),
              name(iv.detect_order_block_v6(base + [bos], sw_high_last, 100, 112.8, 4.0))))
    already = base[:-1] + [C(106, 112, 105, 111.5), bos]          # nến trước ĐÃ đóng trên đỉnh 110 (BOS xảy ra từ trước)
    T.append(("ICT", "Đỉnh đã bị phá từ nến trước (không phải BOS mới)", None,
              name(oi.detect_order_block(already, sw_high_last, 112.8, 4.0)),
              name(iv.detect_order_block_v6(already, sw_high_last, 100, 112.8, 4.0))))
    sweep_hi = C(109, 111, 106, 108)
    T.append(("ICT", "Quét thanh khoản qua đỉnh 110, swing cuối là ĐÁY", "BEARISH_LIQUIDITY_SWEEP",
              name(oi.detect_liquidity_sweep(base + [sweep_hi], sw_low_last, 4.0)),
              name(iv.detect_liquidity_sweep_v6(base + [sweep_hi], sw_low_last, 100, 4.0))))
    sweep_lo = C(105, 106, 102.5, 104.8)
    T.append(("ICT", "Quét thanh khoản dưới đáy 104, swing cuối là ĐỈNH", "BULLISH_LIQUIDITY_SWEEP",
              name(oi.detect_liquidity_sweep(base + [sweep_lo], [S("HIGH", 110, 80), S("LOW", 104, 85), S("HIGH", 109, 90)], 4.0)),
              name(iv.detect_liquidity_sweep_v6(base + [sweep_lo], [S("HIGH", 110, 80), S("LOW", 104, 85), S("HIGH", 109, 90)], 100, 4.0))))
    T.append(("ICT", "Swing quá cũ (cách 200 nến) không được dùng làm mốc", None,
              name(oi.detect_liquidity_sweep(base + [sweep_hi], [S("HIGH", 110, 0)], 4.0)),
              name(iv.detect_liquidity_sweep_v6(base + [sweep_hi], [S("HIGH", 110, 0)], 200, 4.0))))

    # ---------------- CONTINUATION ----------------
    sw = sorted([S("HIGH", 110, 5), S("LOW", 100, 0), S("LOW", 96, 10), S("HIGH", 111, 15), S("LOW", 92, 20), S("HIGH", 111, 25),
                 S("LOW", 95, 30), S("HIGH", 110, 35), S("LOW", 99, 40)], key=lambda s: s["index"])
    T.append(("Continuation", "Rounding Bottom, giá 101 còn cách vành cốc (111) ~10$", None,
              name(ok.detect_rounding_bottom(sw, 101.0, 4.0)), name(kv.detect_rounding_bottom_v6(sw, 101.0, 100.5, 4.0))))
    T.append(("Continuation", "Rounding Bottom, giá vừa phá vành cốc (đóng 112, nến trước 110.5)", "ROUNDING_BOTTOM",
              name(ok.detect_rounding_bottom(sw, 112.0, 4.0)), name(kv.detect_rounding_bottom_v6(sw, 112.0, 110.5, 4.0))))
    T.append(("Continuation", "Rounding Bottom, giá đã nằm trên vành từ trước (nến trước 111.5)", None,
              name(ok.detect_rounding_bottom(sw, 112.5, 4.0)), name(kv.detect_rounding_bottom_v6(sw, 112.5, 111.5, 4.0))))
    swm = sorted([S("LOW", 200 - s["price"] + 0, s["index"]) if s["type"] == "HIGH" else S("HIGH", 200 - s["price"], s["index"]) for s in sw],
                 key=lambda s: s["index"])
    T.append(("Continuation", "Rounding Top, giá 99 còn cách vành (89) — chưa phá", None,
              name(ok.detect_rounding_top(swm, 99.0, 4.0)), name(kv.detect_rounding_top_v6(swm, 99.0, 99.5, 4.0))))

    # ---------------- CANDLESTICK ----------------
    down, up = trend(2020, -1.0, 8), trend(2000, +1.0, 8)
    flat = trend(2000, 0.0, 8)

    def cc(ctx, pat, expect, label):
        T.append(("Nến", label, expect, name(oc.detect_candlestick_patterns(ctx + pat, 4.0)),
                  name(cv.detect_candlestick_patterns_v6(ctx + pat, 4.0))))

    cc(down, [C(2012, 2012.3, 2004.7, 2005), C(2005, 2009.6, 2004.8, 2009.2)], "PIERCING_LINE", "Piercing Line (thị trường 24h: open = close nến trước)")
    cc(up, [C(2008, 2015.3, 2007.7, 2015), C(2015, 2015.2, 2010.7, 2011)], "DARK_CLOUD_COVER", "Dark Cloud Cover (open = close nến trước)")
    cc(down, [C(2006, 2006.2, 1999.8, 2000), C(1999.9, 2007.2, 1999.7, 2006.8)], "BULLISH_ENGULFING", "Bullish Engulfing sau nhịp giảm, thân lớn")
    m1, m2, m3 = C(2005, 2005.3, 1999.7, 2000), C(1999.8, 2000.5, 1998.9, 1999.3), C(1999.5, 2005.3, 1999.3, 2004)
    cc(trend(2012, -1.5, 10), [m1, m2, m3], "MORNING_STAR", "Morning Star sau xu hướng GIẢM")
    cc(trend(1990, +1.5, 10), [m1, m2, m3], None, "Morning Star sau xu hướng TĂNG (không hợp lệ)")
    cc(flat, [C(2000.04, 2000.06, 1999.99, 2000.0), C(1999.99, 2000.1, 1999.98, 2000.05)], None, "Engulfing bằng nến vi mô 0.04$ (nhiễu)")

    # ---------------- SWING (xen ke dinh/day) ----------------
    import random
    rr = random.Random(1)
    pp, rows = 2000.0, []
    for _ in range(12000):
        o = pp + rr.gauss(0, .1); c = o + rr.gauss(0, 1.6)
        rows.append({"open": o, "high": round(max(o, c) + abs(rr.gauss(0, .6)), 2), "low": round(min(o, c) - abs(rr.gauss(0, .6)), 2), "close": c})
        pp = c
    dfr = pd.DataFrame(rows)
    raw = osd.find_swing_points(dfr, 5, 5)
    alt_sw = osd.filter_major_swings(raw, 0.0)
    cnt = lambda L: sum(1 for x, y in zip(L, L[1:]) if x["type"] == y["type"])
    T.append(("Swing", f"Số cặp swing LIỀN KỀ CÙNG LOẠI trên {len(raw)} swing (phải = 0 để pattern_rules đúng giả định xen kẽ)",
              "0", str(cnt(raw)), str(cnt(alt_sw))))

    # ---------------- GEOMETRIC ----------------
    def gcase(label, sw, price, prev, expect, atr=2.0, idx=50):
        T.append(("Hình học", label, expect, name(og.detect_16_patterns(sw, price, atr)),
                  name(gv.detect_16_patterns_v6(sw, idx, price, prev, atr))))

    gcase("Double Top chuẩn (tail L H L H L), giá phá cổ 2000 xuống 1998",
          [S("LOW", 1990, 0), S("HIGH", 2010, 10), S("LOW", 2000, 20), S("HIGH", 2010.1, 30), S("LOW", 2003, 40)], 1998, 2001, "DOUBLE_TOP")
    gcase("Double Top chuẩn (tail kết thúc bằng đỉnh thứ hai)",
          [S("HIGH", 2020, 0), S("LOW", 1990, 10), S("HIGH", 2010, 20), S("LOW", 2000, 30), S("HIGH", 2010.1, 40)], 1998, 2001, "DOUBLE_TOP")
    gcase("Double Bottom chuẩn (tail H L H L H), giá phá cổ 2000 lên 2002",
          [S("HIGH", 2010, 0), S("LOW", 1990, 10), S("HIGH", 2000, 20), S("LOW", 1990.1, 30), S("HIGH", 1997, 40)], 2002, 1999, "DOUBLE_BOTTOM")
    tri = [S("HIGH", 2010, 0), S("LOW", 1995, 10), S("HIGH", 2010.1, 20), S("LOW", 2000, 30), S("HIGH", 2010.0, 40)]
    gcase("Ascending Triangle, vừa phá MỚI lên 2011 (nến trước 2009.5)", tri, 2011, 2009.5, "ASCENDING_TRIANGLE")
    gcase("Ascending Triangle, giá đã ở 2030 từ lâu (đỉnh 2010) — không phải phá mới", tri, 2030, 2029, None)
    gcase("Ascending Triangle, tail kết thúc bằng ĐÁY (đỉnh 2010/2010.1, đáy tăng)",
          [S("LOW", 1990, 0), S("HIGH", 2010, 10), S("LOW", 1995, 20), S("HIGH", 2010.1, 30), S("LOW", 2000, 40)], 2011, 2009, "ASCENDING_TRIANGLE")
    gcase("Rising Wedge HỘI TỤ (biên độ 24 -> 16), phá xuống 1999",
          [S("HIGH", 2010, 0), S("LOW", 1990, 10), S("HIGH", 2014, 20), S("LOW", 2000, 30), S("HIGH", 2016, 40)], 1999, 2001, "BEARISH_RISING_WEDGE")
    gcase("Cấu trúc MỞ RỘNG đi lên (không phải wedge)",
          [S("HIGH", 2005, 0), S("LOW", 1998, 10), S("HIGH", 2012, 20), S("LOW", 1999, 30), S("HIGH", 2013, 40)], 1998.5, 1999.5, None)
    gcase("Head & Shoulders chuẩn, phá cổ 2000 xuống 1999",
          [S("HIGH", 2010, 0), S("LOW", 2000, 10), S("HIGH", 2020, 20), S("LOW", 2001, 30), S("HIGH", 2010.2, 40)], 1999, 2000.5, "HEAD_AND_SHOULDERS")
    gcase("Head & Shoulders, có thêm 1 đáy hồi SAU vai phải",
          [S("HIGH", 2010, 0), S("LOW", 2000, 10), S("HIGH", 2020, 20), S("LOW", 2001, 30), S("HIGH", 2010.2, 40), S("LOW", 2003, 50)], 1999, 2000.5, "HEAD_AND_SHOULDERS", idx=60)
    gcase("Bullish Flag có cột cờ (đáy 1980 -> đỉnh 2020, kênh giảm song song), phá lên 2017",
          [S("LOW", 1980, 0), S("HIGH", 2020, 10), S("LOW", 2006, 20), S("HIGH", 2016, 30), S("LOW", 2002, 40)], 2017, 2015.5, "BULLISH_FLAG")
    gcase("Kênh giảm song song KHÔNG có cột cờ (không phải flag)",
          [S("LOW", 2015, 0), S("HIGH", 2020, 10), S("LOW", 2006, 20), S("HIGH", 2016, 30), S("LOW", 2002, 40)], 2017, 2015.5, None)

    # ---------------- VSA ----------------
    def vc(o, h, l, c_, v):
        return {"open": o, "high": h, "low": l, "close": c_, "volume": v}
    dctx = [dict(x, volume=100.0) for x in trend(2020, -1.0, 8)]
    uctx = [dict(x, volume=100.0) for x in trend(2000, +1.0, 8)]

    def vcase(label, ctx, bar, expect):
        T.append(("VSA", label, expect, name(ov.detect_vsa_patterns(ctx + [bar], 100.0, 3.0)),
                  name(sv.detect_vsa_patterns_v6(ctx + [bar], 100.0, 3.0))))

    vcase("Nến giảm rộng, volume 5x, ĐÓNG SÁT ĐÁY (bán mạnh, không phải kiệt sức)", dctx, vc(2012, 2012.2, 2006, 2006.3, 500), None)
    vcase("Stopping Volume: giảm rộng, volume 5x, đóng gần đỉnh nến, sau nhịp giảm", dctx, vc(2012, 2012.2, 2006, 2011.5, 500), "VSA_STOPPING_VOLUME_BUY")
    vcase("Selling Climax: giảm rộng, volume 3x, đóng giữa nến, sau nhịp giảm", dctx, vc(2012, 2012.1, 2006, 2009, 300), "VSA_SELLING_CLIMAX")
    vcase("Selling Climax giữa XU HƯỚNG TĂNG (sai bối cảnh)", uctx, vc(2012, 2012.1, 2006, 2009, 300), None)
    vcase("No Demand: nến tăng nhỏ, volume thấp, sau nhịp TĂNG", uctx, vc(2008, 2008.9, 2008, 2008.7, 40), "VSA_NO_DEMAND")
    vcase("No Demand trong XU HƯỚNG GIẢM (không có đợt tăng trước)", dctx, vc(2012, 2012.9, 2012, 2012.7, 40), None)
    return T


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--orig-dir", default=os.path.join("ai_v5", "pipeline"))
    a = ap.parse_args()
    T = run(a.orig_dir)
    w = max(len(t[1]) for t in T) + 1
    print(f"{'nhóm':13s}{'tình huống':{w}s}{'kỳ vọng':34s}{'ai_v5 GỐC':32s}{'v6':32s}")
    stats = {}
    for g, label, exp, o, n in T:
        po, pn = o == exp, n == exp
        st = stats.setdefault(g, [0, 0, 0])
        st[0] += 1; st[1] += po; st[2] += pn
        print(f"{g:13s}{label:{w}s}{str(exp):34s}{('✔ ' if po else '✘ ') + str(o):32s}{('✔ ' if pn else '✘ ') + str(n):32s}")
    print("\nTổng kết (số tình huống đúng / tổng):")
    tot = [0, 0, 0]
    for g, (n, po, pn) in stats.items():
        print(f"  {g:13s} ai_v5 gốc {po}/{n}   v6 {pn}/{n}")
        for i, v in enumerate((n, po, pn)):
            tot[i] += v
    print(f"  {'TỔNG':13s} ai_v5 gốc {tot[1]}/{tot[0]}   v6 {tot[2]}/{tot[0]}")
    return 0 if tot[2] == tot[0] else 1


if __name__ == "__main__":
    sys.exit(main())
