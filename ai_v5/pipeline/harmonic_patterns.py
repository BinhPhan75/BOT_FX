# ai_v5/pipeline/harmonic_patterns.py
"""
Bo phat hien Mau hinh Harmonic (Gartley, Bat, Butterfly, Crab) dua tren
5 diem cau truc X-A-B-C-D va cac ty le Fibonacci giua cac chan gia.

Quy uoc dau ra GIONG HET pattern_rules.detect_16_patterns() de build_dataset.py
co the goi thong nhat ca 3 nhom:
    {"pattern": str, "direction": "BUY"|"SELL", "sl": float, "tp": float}
hoac None neu khong khop mau hinh nao.

X, A, B, C: lay tu 4 diem Dinh/Day cau truc gan nhat (da xac nhan, xen ke
HIGH/LOW). D: diem hoan thanh mau hinh, chinh la gia hien tai (current_price)
dang duoc kiem tra tai moi buoc quet.
"""

# (ty_le_toi_thieu, ty_le_toi_da) cho tung chan cua tung mau hinh.
# LUU Y: da noi rong ~40-60% so voi ty le "sach giao khoa" (vd Gartley AB/XA=0.618 dung tuyet doi)
# vi du lieu thi truong thuc te nhieu, hiem khi khop chinh xac ty le ly thuyet. Day la dung sai
# thuc hanh pho bien khi quet Harmonic tren du lieu that (khong phai ve tay tren bieu do dep).
HARMONIC_RATIOS = {
    "GARTLEY": {"AB_XA": (0.45, 0.78), "BC_AB": (0.30, 1.05), "CD_BC": (0.90, 2.00), "XD_XA": (0.65, 0.95)},
    "BAT":     {"AB_XA": (0.28, 0.62), "BC_AB": (0.30, 1.05), "CD_BC": (1.35, 3.00), "XD_XA": (0.78, 1.00)},
    "BUTTERFLY": {"AB_XA": (0.65, 0.92), "BC_AB": (0.30, 1.05), "CD_BC": (1.35, 2.60), "XD_XA": (1.00, 1.55)},
    "CRAB":    {"AB_XA": (0.28, 0.75), "BC_AB": (0.30, 1.05), "CD_BC": (1.90, 4.20), "XD_XA": (1.35, 1.90)},
}

SL_BUFFER_ATR = 0.5


def _in_range(value, bounds):
    lo, hi = bounds
    return lo <= value <= hi


def detect_harmonic_patterns(swings: list, current_price: float, atr: float) -> dict:
    """
    swings: danh sach Dinh/Day da xac nhan (thu tu thoi gian tang dan), can >= 4 diem gan nhat cho X-A-B-C.
    current_price: gia hien tai, dong vai tro diem D dang hinh thanh.
    """
    if len(swings) < 4 or atr <= 0:
        return None

    X, A, B, C = swings[-4], swings[-3], swings[-2], swings[-1]
    D = current_price

    # Bat buoc xen ke dung thu tu HIGH/LOW/HIGH/LOW hoac LOW/HIGH/LOW/HIGH
    types = [X["type"], A["type"], B["type"], C["type"]]
    if types not in (["LOW", "HIGH", "LOW", "HIGH"], ["HIGH", "LOW", "HIGH", "LOW"]):
        return None

    xa = A["price"] - X["price"]
    ab = B["price"] - A["price"]
    bc = C["price"] - B["price"]
    cd = D - C["price"]
    xd = D - X["price"]

    xa_range = abs(xa)
    ab_range = abs(ab)
    bc_range = abs(bc)
    if xa_range < 1e-9 or ab_range < 1e-9 or bc_range < 1e-9:
        return None

    ratio_ab_xa = ab_range / xa_range
    ratio_bc_ab = bc_range / ab_range
    ratio_cd_bc = abs(cd) / bc_range
    ratio_xd_xa = abs(xd) / xa_range

    # X la LOW -> A la HIGH -> B la LOW -> C la HIGH -> D dang hinh thanh la LOW -> mau hinh TANG (BUY tai D)
    is_bullish_shape = X["type"] == "LOW"

    for pattern_name, r in HARMONIC_RATIOS.items():
        if not _in_range(ratio_ab_xa, r["AB_XA"]):
            continue
        if not _in_range(ratio_bc_ab, r["BC_AB"]):
            continue
        if not _in_range(ratio_cd_bc, r["CD_BC"]):
            continue
        if not _in_range(ratio_xd_xa, r["XD_XA"]):
            continue

        if is_bullish_shape:
            # D phai thap hon C (dang tao day moi) de hop le la diem hoan thanh
            if D >= C["price"]:
                continue
            direction = "BUY"
            sl = D - SL_BUFFER_ATR * atr
            tp = C["price"]  # Muc tieu dau tien chuan cua Harmonic: hoi ve diem C
            pattern_label = f"{pattern_name}_BULLISH"
        else:
            if D <= C["price"]:
                continue
            direction = "SELL"
            sl = D + SL_BUFFER_ATR * atr
            tp = C["price"]
            pattern_label = f"{pattern_name}_BEARISH"

        return {"pattern": pattern_label, "direction": direction, "sl": float(sl), "tp": float(tp)}

    return None
