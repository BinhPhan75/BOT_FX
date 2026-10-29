# ai_v6/live/harmonic_v6.py
"""
Harmonic (Gartley / Bat / Butterfly / Crab) - SUA LOI LOGIC cua ai_v5/pipeline/harmonic_patterns.py.

LOI GOC: dai ty le "XD_XA" trong HARMONIC_RATIOS la TY LE HOI cua XA do TU DIEM A (Gartley 0.786, Bat 0.886,
Butterfly 1.27, Crab 1.618), nhung code goc tinh `abs(D - X) / abs(XA)` = do tu X. Cho D dung 0.786 retracement:
|D-X|/XA = 0.214, khong bao gio roi vao dai (0.65, 0.95). Ket qua: ca 4 mau hinh DUNG TY LE FIBONACCI SACH GIAO KHOA
deu KHONG BAO GIO duoc nhan ra (da chay thu) - khop voi viec Harmonic co 0 mau trong dataset va 0 lenh live.

SUA: do AD/XA = |D - A| / |XA|. Them dieu kien hinh hoc con thieu: B nam giua X-A, C nam giua A va B (dung cau truc XABCD).
Giu nguyen dai ty le goc (da noi rong theo ghi chu cua tac gia).
"""
HARMONIC_RATIOS = {
    "GARTLEY": {"AB_XA": (0.45, 0.78), "BC_AB": (0.30, 1.05), "CD_BC": (0.90, 2.00), "AD_XA": (0.65, 0.95)},
    "BAT": {"AB_XA": (0.28, 0.62), "BC_AB": (0.30, 1.05), "CD_BC": (1.35, 3.00), "AD_XA": (0.78, 1.00)},
    "BUTTERFLY": {"AB_XA": (0.65, 0.92), "BC_AB": (0.30, 1.05), "CD_BC": (1.35, 2.60), "AD_XA": (1.00, 1.55)},
    "CRAB": {"AB_XA": (0.28, 0.75), "BC_AB": (0.30, 1.05), "CD_BC": (1.90, 4.20), "AD_XA": (1.35, 1.90)},
}
SL_BUFFER_ATR = 0.5


def _in(v, b):
    return b[0] <= v <= b[1]


def detect_harmonic_patterns_v6(swings: list, current_price: float, atr: float):
    if len(swings) < 4 or atr <= 0:
        return None
    X, A, B, C = swings[-4], swings[-3], swings[-2], swings[-1]
    D = current_price
    types = [X["type"], A["type"], B["type"], C["type"]]
    if types not in (["LOW", "HIGH", "LOW", "HIGH"], ["HIGH", "LOW", "HIGH", "LOW"]):
        return None
    bullish = X["type"] == "LOW"
    x, a, b, c = X["price"], A["price"], B["price"], C["price"]

    # Cau truc XABCD hop le: B nam giua X va A; C nam giua B va A
    if bullish and not (x < b < a and b < c < a and D < c):
        return None
    if not bullish and not (x > b > a and b > c > a and D > c):
        return None

    xa, ab, bc = abs(a - x), abs(b - a), abs(c - b)
    if min(xa, ab, bc) < 1e-9:
        return None
    ratios = {"AB_XA": ab / xa, "BC_AB": bc / ab, "CD_BC": abs(D - c) / bc, "AD_XA": abs(D - a) / xa}

    for name, r in HARMONIC_RATIOS.items():
        if all(_in(ratios[k], r[k]) for k in ("AB_XA", "BC_AB", "CD_BC", "AD_XA")):
            if bullish:
                return {"pattern": f"{name}_BULLISH", "direction": "BUY", "sl": float(D - SL_BUFFER_ATR * atr), "tp": float(c)}
            return {"pattern": f"{name}_BEARISH", "direction": "SELL", "sl": float(D + SL_BUFFER_ATR * atr), "tp": float(c)}
    return None
