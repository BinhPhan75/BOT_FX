# test_candlestick_v6.py
"""
Chay:  py -3.11 test_candlestick_v6.py [duong_dan_candlestick_patterns_cu.py]
Kiem tra detector moi voi cac truong hop sach giao khoa + (neu co file cu) so sanh voi ai_v5 tren chuoi gia ngau nhien.
"""
import importlib.util
import os
import random
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import candlestick_v6 as v6  # noqa: E402

ATR = 4.0


def C(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c}


def trend(start, step, n):
    out, p = [], start
    for _ in range(n):
        q = p + step
        out.append(C(p, max(p, q) + .3, min(p, q) - .3, q))
        p = q
    return out


def name(ctx, pat):
    r = v6.detect_candlestick_patterns_v6(ctx + pat, ATR)
    return r["pattern"] if r else None


def run_tests():
    down, up, flat = trend(2020, -1.0, 8), trend(2000, +1.0, 8), trend(2000, 0.0, 8)
    # Piercing: khong gap (open == close truoc) va co gap 1 cent -> DEU phai khop
    c2 = C(2012, 2012.3, 2004.7, 2005)
    c3 = C(2005, 2009.6, 2004.8, 2009.2)
    assert name(down, [c2, c3]) == "PIERCING_LINE"
    assert name(down, [c2, dict(c3, open=2004.99)]) == "PIERCING_LINE"
    # Dark cloud
    d2 = C(2008, 2015.3, 2007.7, 2015)
    d3 = C(2015, 2015.2, 2010.7, 2011)
    assert name(up, [d2, d3]) == "DARK_CLOUD_COVER"
    assert name(up, [d2, dict(d3, open=2015.01)]) == "DARK_CLOUD_COVER"
    # Morning star: dung sau xu huong GIAM, SAI sau xu huong TANG
    m1, m2, m3 = C(2005, 2005.3, 1999.7, 2000), C(1999.8, 2000.5, 1998.9, 1999.3), C(1999.5, 2005.3, 1999.3, 2004)
    assert name(trend(2012, -1.5, 10), [m1, m2, m3]) == "MORNING_STAR"
    assert name(trend(1990, +1.5, 10), [m1, m2, m3]) != "MORNING_STAR"
    # Engulfing hop le sau pullback; nen vi mo 0.04$ bi loai
    e2, e3 = C(2006, 2006.2, 1999.8, 2000), C(1999.9, 2007.2, 1999.7, 2006.8)
    assert name(down, [e2, e3]) == "BULLISH_ENGULFING"
    assert name(flat, [C(2000.04, 2000.06, 1999.99, 2000.0), C(1999.99, 2000.1, 1999.98, 2000.05)]) is None
    # Hammer sau giam khop; nen don qua nho bi loai
    h = v6.detect_candlestick_patterns_v6(down + [C(2012, 2012.0, 2007.0, 2011.5)], ATR)
    assert h and h["pattern"] == "HAMMER", h
    assert v6.detect_candlestick_patterns_v6(down + [C(2012, 2012.0, 2011.7, 2011.9)], ATR) is None
    # Ablation: tat bo loc ngu canh thi Morning star sau xu huong tang lai khop
    v6.REQUIRE_CONTEXT = False
    assert name(trend(1990, +1.5, 10), [m1, m2, m3]) == "MORNING_STAR"
    v6.REQUIRE_CONTEXT = True
    print("✅ Tất cả test đơn vị đạt.")


def synthetic(n=20000, seed=7):
    r = random.Random(seed)
    p, out = 2000.0, []
    for _ in range(n):
        o = p + r.gauss(0, 0.12)                    # open ~ close truoc (24h, gan nhu khong gap)
        c = o + r.gauss(0, 1.8)
        h = max(o, c) + abs(r.gauss(0, 1.0))
        l = min(o, c) - abs(r.gauss(0, 1.0))
        out.append(C(o, h, l, c))
        p = c
    return out


def compare_with_old(old_path):
    spec = importlib.util.spec_from_file_location("old_candle", old_path)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    candles = synthetic()
    co, cn = Counter(), Counter()
    for i in range(30, len(candles)):
        w = candles[i - 11:i + 1]
        atr = sum(c["high"] - c["low"] for c in candles[i - 13:i + 1]) / 14
        a = old.detect_candlestick_patterns(w, atr)
        b = v6.detect_candlestick_patterns_v6(w, atr)
        if a: co[a["pattern"]] += 1
        if b: cn[b["pattern"]] += 1
    print(f"\nTần suất khớp trên {len(candles)-30} nến M5 giả lập (đi ngẫu nhiên, KHÔNG có cấu trúc thật):")
    print(f"{'pattern':26s}{'ai_v5 cũ':>10s}{'v6 mới':>10s}")
    for k in sorted(set(co) | set(cn), key=lambda x: -co.get(x, 0)):
        print(f"{k:26s}{co.get(k, 0):>10d}{cn.get(k, 0):>10d}")
    print(f"{'TỔNG':26s}{sum(co.values()):>10d}{sum(cn.values()):>10d}")


if __name__ == "__main__":
    run_tests()
    if len(sys.argv) > 1:
        compare_with_old(sys.argv[1])
