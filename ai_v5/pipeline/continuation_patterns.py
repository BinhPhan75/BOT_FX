# ai_v5/pipeline/continuation_patterns.py
"""
Bo phat hien mau hinh gia dai han: Rounding Top/Bottom va Cup & Handle.
Khac voi 16 mau hinh hinh hoc (dua tren vai diem Dinh/Day ro net), nhom nay
dua tren HINH DANG TONG THE cua nhieu Dinh/Day lien tiep (dang cong/vong
cung), phan anh qua trinh tich luy/phan phoi dan dan cua thi truong.

Quy uoc dau ra GIONG HET cac module pattern khac de build_dataset.py goi
thong nhat: {"pattern": str, "direction": "BUY"|"SELL", "sl": float, "tp": float}
hoac None neu khong khop.

LUU Y: day la ban trien khai DON GIAN HOA (dung 5 diem Dinh/Day gan nhat de
uoc luong hinh dang cong/vong cung), khong phai thuat toan fit duong cong
chinh xac. Phu hop de tao tin hieu tho cho model ML hoc, chua phai la bo
nhan dien hinh hoc hoan chinh.
"""

SL_BUFFER_ATR = 0.3
REWARD_RISK_RATIO = 1.5
MAX_SL_ATR_MULTIPLE = 10  # Gioi han khoang cach SL toi da = 10x ATR, tranh truong hop
                          # "cup" qua lich su xa (dinh/day tu nhieu thang truoc) khien
                          # SL/TP bi keo qua xa gia hien tai mot cach phi thuc te.


def _rr_sl_tp(direction, entry, extreme, atr):
    buffer = SL_BUFFER_ATR * atr
    max_distance = MAX_SL_ATR_MULTIPLE * atr

    if direction == "BUY":
        raw_sl = extreme - buffer
        # Gioi han: SL khong duoc xa hon max_distance so voi entry
        sl = max(raw_sl, entry - max_distance)
        risk = entry - sl
        tp = entry + REWARD_RISK_RATIO * risk
    else:
        raw_sl = extreme + buffer
        sl = min(raw_sl, entry + max_distance)
        risk = sl - entry
        tp = entry - REWARD_RISK_RATIO * risk
    return float(sl), float(tp)


def _is_u_shape(prices: list) -> bool:
    """5 diem Day: diem thap nhat nam o giua (vi tri 1,2,3 trong 5), 2 dau cao hon ro ret."""
    n = len(prices)
    min_idx = prices.index(min(prices))
    if not (1 <= min_idx <= n - 2):
        return False
    return prices[0] > prices[min_idx] and prices[-1] > prices[min_idx]


def _is_inverted_u_shape(prices: list) -> bool:
    """5 diem Dinh: diem cao nhat nam o giua, 2 dau thap hon ro ret."""
    n = len(prices)
    max_idx = prices.index(max(prices))
    if not (1 <= max_idx <= n - 2):
        return False
    return prices[0] < prices[max_idx] and prices[-1] < prices[max_idx]


def detect_rounding_bottom(swings: list, current_price: float, atr: float) -> dict:
    lows = [s for s in swings if s["type"] == "LOW"]
    if len(lows) < 5 or atr <= 0:
        return None

    recent = lows[-5:]
    prices = [x["price"] for x in recent]
    if not _is_u_shape(prices):
        return None

    rim_level = max(prices[0], prices[-1])  # Muc khang cu "vanh cup" uoc luong
    if current_price <= rim_level:
        return None  # Chua breakout khoi vanh cup

    sl, tp = _rr_sl_tp("BUY", current_price, min(prices), atr)
    return {"pattern": "ROUNDING_BOTTOM", "direction": "BUY", "sl": sl, "tp": tp}


def detect_rounding_top(swings: list, current_price: float, atr: float) -> dict:
    highs = [s for s in swings if s["type"] == "HIGH"]
    if len(highs) < 5 or atr <= 0:
        return None

    recent = highs[-5:]
    prices = [x["price"] for x in recent]
    if not _is_inverted_u_shape(prices):
        return None

    rim_level = min(prices[0], prices[-1])  # Muc ho tro "vanh cup nguoc" uoc luong
    if current_price >= rim_level:
        return None  # Chua breakdown khoi vanh cup nguoc

    sl, tp = _rr_sl_tp("SELL", current_price, max(prices), atr)
    return {"pattern": "ROUNDING_TOP", "direction": "SELL", "sl": sl, "tp": tp}


def detect_cup_and_handle(swings: list, current_price: float, atr: float) -> dict:
    """Cup (Rounding Bottom bang 5 Day cu, khong tinh Day gan nhat) + Handle (nhip dieu chinh
    nong hon <50% do sau Cup, gan vanh cup) + breakout khoi vanh cup."""
    lows = [s for s in swings if s["type"] == "LOW"]
    if len(lows) < 6 or atr <= 0:
        return None

    cup_lows = lows[-6:-1]
    prices = [x["price"] for x in cup_lows]
    if not _is_u_shape(prices):
        return None

    rim_level = max(prices[0], prices[-1])
    cup_depth = rim_level - min(prices)
    if cup_depth <= 0:
        return None

    handle_low_price = lows[-1]["price"]
    handle_depth = rim_level - handle_low_price
    if not (0 < handle_depth < 0.5 * cup_depth):
        return None  # Handle phai nong hon nhieu so voi Cup, khong duoc sau qua 50% Cup

    if current_price <= rim_level:
        return None  # Chua breakout khoi vanh cup

    sl, tp = _rr_sl_tp("BUY", current_price, handle_low_price, atr)
    return {"pattern": "CUP_AND_HANDLE", "direction": "BUY", "sl": sl, "tp": tp}


def detect_inverted_cup_and_handle(swings: list, current_price: float, atr: float) -> dict:
    """Ban doi xung (giam gia) cua Cup & Handle."""
    highs = [s for s in swings if s["type"] == "HIGH"]
    if len(highs) < 6 or atr <= 0:
        return None

    cup_highs = highs[-6:-1]
    prices = [x["price"] for x in cup_highs]
    if not _is_inverted_u_shape(prices):
        return None

    rim_level = min(prices[0], prices[-1])
    cup_depth = max(prices) - rim_level
    if cup_depth <= 0:
        return None

    handle_high_price = highs[-1]["price"]
    handle_depth = handle_high_price - rim_level
    if not (0 < handle_depth < 0.5 * cup_depth):
        return None

    if current_price >= rim_level:
        return None

    sl, tp = _rr_sl_tp("SELL", current_price, handle_high_price, atr)
    return {"pattern": "INVERTED_CUP_AND_HANDLE", "direction": "SELL", "sl": sl, "tp": tp}
