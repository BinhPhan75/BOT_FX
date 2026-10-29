# ai_v6/live/divergence_v6.py
"""
Phan ky (Divergence) RSI/MACD - SUA LOI LOGIC cua ai_v5/pipeline/divergence_patterns.detect_divergence().

LOI GOC (da chay thu):
  - Chi so GIA HIEN TAI voi 1 swing gan nhat, khong so sanh 2 swing cung loai. Phan ky la quan he giua HAI dinh/day
    lien tiep: gia lam day moi (thap hon/cao hon) trong khi chi bao lam day moi nguoc huong.
  - "Hidden bullish" cu: `gia hien tai > day cu` (gan nhu LUON dung vi day cu la cuc tieu cuc bo) va `chi bao hien tai < chi bao tai day`
    => khop ca khi xu huong giam THUAN TUY (khong co phan ky) => tin hieu rac. Dataset: 1696/1754 mau divergence la HIDDEN,
    chi 33 mau REGULAR - dau hieu bo loc "hidden" gan nhu luon dung.
  - Phan ky thuong dung sach giao khoa lai khong duoc nhan khi gia da bat len tren day moi.
  - Khong gioi han do "tuoi": cung 1 phan ky bao lap lai o moi nen cho toi khi swing moi xuat hien.

SUA: dung 2 swing cung loai gan nhat da xac nhan (S1 cu, S2 moi) + chi bao tai CHI SO swing:
    REGULAR bullish : gia S2 < gia S1  VA  chi bao S2 > chi bao S1        (dao chieu tang)
    HIDDEN  bullish : gia S2 > gia S1  VA  chi bao S2 < chi bao S1        (tiep dien tang)
    REGULAR bearish : gia S2 > gia S1  VA  chi bao S2 < chi bao S1
    HIDDEN  bearish : gia S2 < gia S1  VA  chi bao S2 > chi bao S1
  + do lech toi thieu (gia >= MIN_PRICE_DIFF_ATR*ATR, chi bao >= nguong), khoang cach S1-S2 hop ly, va CHI BAO KHI VUA XAC NHAN
  (S2 moi duoc xac nhan <= FRESH_BARS nen) de moi phan ky chi bao 1 lan.
"""
SL_BUFFER_ATR = 0.3
REWARD_RISK_RATIO = 1.5
RIGHT_BARS = 5            # so nen xac nhan swing (find_swing_points right_bars=5)
FRESH_BARS = 3            # chi bao trong FRESH_BARS nen ke tu khi S2 duoc xac nhan
MIN_SEP, MAX_SEP = 6, 80  # khoang cach (nen) giua S1 va S2
MIN_PRICE_DIFF_ATR = 0.10
MIN_IND_DIFF = {"RSI": 2.0, "MACD_ATR": 0.05}   # RSI: 2 diem; MACD: 5% ATR


def _ind_at(series, idx):
    if idx < 0 or idx >= len(series):
        return None
    v = series.iloc[idx]
    return None if v != v else float(v)


def detect_divergence_v6(swings_before: list, cur_index: int, current_price: float, indicator_series, atr: float,
                          indicator_name: str):
    if atr <= 0 or len(swings_before) < 2:
        return None
    min_ind = MIN_IND_DIFF["RSI"] if indicator_name == "RSI" else MIN_IND_DIFF["MACD_ATR"] * atr

    for stype in ("LOW", "HIGH"):
        same = [s for s in swings_before if s["type"] == stype]
        if len(same) < 2:
            continue
        s1, s2 = same[-2], same[-1]
        age = cur_index - s2["index"]
        if not (RIGHT_BARS <= age <= RIGHT_BARS + FRESH_BARS):
            continue
        if not (MIN_SEP <= s2["index"] - s1["index"] <= MAX_SEP):
            continue
        i1, i2 = _ind_at(indicator_series, s1["index"]), _ind_at(indicator_series, s2["index"])
        if i1 is None or i2 is None:
            continue
        dp, di = s2["price"] - s1["price"], i2 - i1
        if abs(dp) < MIN_PRICE_DIFF_ATR * atr or abs(di) < min_ind:
            continue

        if stype == "LOW":
            if dp < 0 and di > 0:
                kind = "REGULAR"
            elif dp > 0 and di < 0:
                kind = "HIDDEN"
            else:
                continue
            sl = min(current_price, s2["price"]) - SL_BUFFER_ATR * atr
            risk = current_price - sl
            if risk <= 0:
                continue
            return {"pattern": f"{indicator_name}_BULLISH_DIVERGENCE_{kind}", "direction": "BUY", "sl": float(sl),
                    "tp": float(current_price + REWARD_RISK_RATIO * risk)}
        else:
            if dp > 0 and di < 0:
                kind = "REGULAR"
            elif dp < 0 and di > 0:
                kind = "HIDDEN"
            else:
                continue
            sl = max(current_price, s2["price"]) + SL_BUFFER_ATR * atr
            risk = sl - current_price
            if risk <= 0:
                continue
            return {"pattern": f"{indicator_name}_BEARISH_DIVERGENCE_{kind}", "direction": "SELL", "sl": float(sl),
                    "tp": float(current_price - REWARD_RISK_RATIO * risk)}
    return None
