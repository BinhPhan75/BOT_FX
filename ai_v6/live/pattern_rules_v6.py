# ai_v6/live/pattern_rules_v6.py
"""
14 mau hinh hinh hoc (Double/Triple Top-Bottom, Head&Shoulders, Tam giac, Wedge, Flag) - SUA LOI LOGIC cua
ai_v5/pipeline/pattern_rules.py. Giu nguyen TEN pattern.

LOI GOC (da chay thu tren code that):
 1. find_swing_points tra ve swing THO KHONG xen ke DINH/DAY (~17% cap lien ke cung loai) nhung pattern_rules gia dinh xen ke
    (p2/p4 la day, p3 la dinh...) va khong kiem tra loai cua p2/p4.
 2. DOUBLE_TOP / DOUBLE_BOTTOM: dung P1 va P3 la hai dinh roi doi P5 phai la DAY. Voi swing xen ke, P1,P3 la dinh thi P5 BAT BUOC la
    dinh => nhanh nay CHI chay duoc khi swing KHONG xen ke (rac). Thuc nghiem: 100% cac lan nhan Double Top/Bottom nam tren duoi swing
    khong xen ke; Double Top sach giao khoa khong bao gio duoc nhan ra.
 3. Moi mau hinh chi xet duoi bat dau bang DINH (p1=HIGH) => bo sot ~mot nua cac cau truc (vd tam giac tang khi swing cuoi la DAY).
 4. BEARISH_RISING_WEDGE: so sanh `(p2-p1) > (p4-p3)` tuc la bien do MO RONG (w1 < w2) thay vi HOI TU (w1 > w2) - dao dau. Nem hoi tu that
    khong duoc nhan, cau truc mo rong lai bi nhan thanh Rising Wedge (cung ho dao dau voi loi TP da tung vá).
 5. Khong co dieu kien "pha MOI": chi can gia dang nam ben kia duong co/dinh la bao tin hieu o MOI nen cho toi khi co swing moi
    (tam giac tang van bao khi gia da vuot dinh 20$) => vao lenh muon, lap lai.
 6. Flag khong kiem tra "cot co" (xung luc truoc do) - dac trung dinh nghia cua mau hinh.

SUA: (a) dau vao la swing XEN KE (filter_major_swings(swings, 0.0)); (b) moi mau hinh xet tren 4-5 swing cuoi, ca khi swing cuoi la dinh
lan day, va khi co them 1 swing hoi sau mau hinh (k=1); (c) breakout phai MOI: nen truoc chua vuot moc, nen hien tai da vuot;
(d) Rising Wedge hoi tu dung; (e) Flag can cot co; (f) mau hinh khong qua cu (MAX_PATTERN_AGE).

THAM SO TOL_ATR (dung sai "bang nhau") giu 0.10*ATR nhu ban goc de tach bach SUA LOGIC khoi HIEU CHUAN - rat chat, nen hieu chuan bang
pattern_lab_v6.py (--set ai_v6.live.pattern_rules_v6.TOL_ATR=0.3).
"""
TOL_ATR = 0.10
MIN_HEIGHT_ATR = 0.5        # chieu cao mau hinh toi thieu (tranh mau hinh suy bien)
HEAD_MIN_ATR = 0.3          # dau phai cao hon vai it nhat 0.3 ATR
POLE_MIN_WIDTHS = 1.5       # cot co phai >= 1.5 lan be rong co
MAX_PATTERN_AGE = 80        # swing cuoi cua mau hinh khong cu hon 80 nen
MIN_ACCEPTABLE_RR = 0.8
RR_FLOOR = 1.5


def _finalize(match, entry):
    risk = abs(entry - match["sl"])
    if risk <= 0:
        return None
    d = match["direction"]
    reward = abs(match["tp"] - entry)
    if reward / risk < MIN_ACCEPTABLE_RR or (d == "BUY" and match["tp"] <= entry) or (d == "SELL" and match["tp"] >= entry):
        match["tp"] = entry + RR_FLOOR * risk if d == "BUY" else entry - RR_FLOOR * risk
    match["sl"], match["tp"] = float(match["sl"]), float(match["tp"])
    return match


def detect_16_patterns_v6(alt_swings: list, cur_index: int, current_price: float, prev_close: float, atr: float):
    """alt_swings: swing XEN KE DINH/DAY (index < cur_index). Tra ve match hoac None."""
    if atr <= 0 or len(alt_swings) < 4:
        return None
    tol = TOL_ATR * atr
    min_h = MIN_HEIGHT_ATR * atr
    px, pc = current_price, prev_close

    def up(level):      # pha MOI len tren moc
        return pc <= level < px

    def down(level):    # pha MOI xuong duoi moc
        return pc >= level > px

    for k in (0, 1):    # k=1: swing moi nhat la nhip hoi SAU mau hinh
        S = alt_swings[:len(alt_swings) - k]
        if len(S) < 4 or cur_index - S[-1]["index"] > MAX_PATTERN_AGE:
            continue

        # ---------- Triple / Double Top & Bottom, Head & Shoulders (can day du 5 swing cho Triple / H&S) ----------
        if len(S) >= 5:
            p1, p2, p3, p4, p5 = (s["price"] for s in S[-5:])
            t = [s["type"] for s in S[-5:]]
            if t == ["HIGH", "LOW", "HIGH", "LOW", "HIGH"]:
                neck = min(p2, p4)
                top = max(p1, p3, p5)
                if abs(p1 - p3) <= tol and abs(p3 - p5) <= tol and top - neck >= min_h and down(neck):
                    return _finalize({"pattern": "TRIPLE_TOP", "direction": "SELL", "sl": top + tol, "tp": px - (top - neck)}, px)
                if p3 - max(p1, p5) >= HEAD_MIN_ATR * atr and abs(p1 - p5) <= 1.5 * tol and p3 - neck >= min_h and down(neck):
                    return _finalize({"pattern": "HEAD_AND_SHOULDERS", "direction": "SELL", "sl": p3 + tol, "tp": px - (p3 - neck)}, px)
            elif t == ["LOW", "HIGH", "LOW", "HIGH", "LOW"]:
                neck = max(p2, p4)
                bot = min(p1, p3, p5)
                if abs(p1 - p3) <= tol and abs(p3 - p5) <= tol and neck - bot >= min_h and up(neck):
                    return _finalize({"pattern": "TRIPLE_BOTTOM", "direction": "BUY", "sl": bot - tol, "tp": px + (neck - bot)}, px)
                if min(p1, p5) - p3 >= HEAD_MIN_ATR * atr and abs(p1 - p5) <= 1.5 * tol and neck - p3 >= min_h and up(neck):
                    return _finalize({"pattern": "INVERTED_HEAD_AND_SHOULDERS", "direction": "BUY", "sl": p3 - tol, "tp": px + (neck - p3)}, px)

        # Double Top/Bottom: 2 dinh (day) lien tiep + day (dinh) o giua lam co; swing cuoi la dinh thu hai HOAC nhip hoi sau do
        for a, b, c in ((S[-3], S[-2], S[-1]), (S[-4], S[-3], S[-2])):    # 2 cach: swing cuoi la cuc tri thu hai, hoac sau nhip hoi
            if a["type"] == "HIGH":
                neck, top = b["price"], max(a["price"], c["price"])
                if abs(a["price"] - c["price"]) <= tol and top - neck >= min_h and down(neck):
                    return _finalize({"pattern": "DOUBLE_TOP", "direction": "SELL", "sl": top + tol, "tp": px - (top - neck)}, px)
            else:
                neck, bot = b["price"], min(a["price"], c["price"])
                if abs(a["price"] - c["price"]) <= tol and neck - bot >= min_h and up(neck):
                    return _finalize({"pattern": "DOUBLE_BOTTOM", "direction": "BUY", "sl": bot - tol, "tp": px + (neck - bot)}, px)

        # ---------- Tam giac / Wedge / Flag tren 4 swing cuoi (2 dinh + 2 day) ----------
        Q = S[-4:]
        highs = [s for s in Q if s["type"] == "HIGH"]
        lows = [s for s in Q if s["type"] == "LOW"]
        if len(highs) != 2 or len(lows) != 2:
            continue
        (h_old, h_new), (l_old, l_new) = (highs[0]["price"], highs[1]["price"]), (lows[0]["price"], lows[1]["price"])
        w_old, w_new = h_old - l_old, h_new - l_new
        top, bot = max(h_old, h_new), min(l_old, l_new)
        if top - bot < min_h:
            continue

        if abs(h_old - h_new) <= tol and l_new > l_old and up(top):
            return _finalize({"pattern": "ASCENDING_TRIANGLE", "direction": "BUY", "sl": l_new - tol, "tp": px + (top - l_old)}, px)
        if abs(l_old - l_new) <= tol and h_new < h_old and down(bot):
            return _finalize({"pattern": "DESCENDING_TRIANGLE", "direction": "SELL", "sl": h_new + tol, "tp": px - (h_old - bot)}, px)
        if h_new < h_old and l_new > l_old:      # hoi tu: dinh ha, day nang
            if up(h_new):
                return _finalize({"pattern": "BULLISH_SYMMETRICAL_TRIANGLE", "direction": "BUY", "sl": l_new - tol, "tp": px + w_old}, px)
            if down(l_new):
                return _finalize({"pattern": "BEARISH_SYMMETRICAL_TRIANGLE", "direction": "SELL", "sl": h_new + tol, "tp": px - w_old}, px)

        pre = S[-5] if len(S) >= 5 else None
        parallel = abs(w_old - w_new) <= tol
        if parallel and w_old >= min_h and pre is not None:
            if h_new < h_old and l_new < l_old and Q[0]["type"] == "HIGH" and pre["type"] == "LOW" \
                    and (h_old - pre["price"]) >= POLE_MIN_WIDTHS * w_old and up(h_new):
                return _finalize({"pattern": "BULLISH_FLAG", "direction": "BUY", "sl": l_new - tol, "tp": px + 1.5 * w_old}, px)
            if h_new > h_old and l_new > l_old and Q[0]["type"] == "LOW" and pre["type"] == "HIGH" \
                    and (pre["price"] - l_old) >= POLE_MIN_WIDTHS * w_old and down(l_new):
                return _finalize({"pattern": "BEARISH_FLAG", "direction": "SELL", "sl": h_new + tol, "tp": px - 1.5 * w_old}, px)

        if w_old - w_new > tol:                  # hoi tu that su
            if h_new < h_old and l_new < l_old and up(h_new):
                return _finalize({"pattern": "BULLISH_FALLING_WEDGE", "direction": "BUY", "sl": l_new - tol, "tp": px + w_old}, px)
            if h_new > h_old and l_new > l_old and down(l_new):
                return _finalize({"pattern": "BEARISH_RISING_WEDGE", "direction": "SELL", "sl": h_new + tol, "tp": px - w_old}, px)
    return None
