"""
mt5_client.py
Wrapper quanh thư viện MetaTrader5 để lấy dữ liệu nến.
CHỈ chạy được trên Windows có cài MT5 terminal.

v2 — Ho tro chon DUNG terminal/tai khoan khi chay nhieu bot song song
(vi du: bot_xutho4 dung tai khoan demo rieng, khac voi bot cu tren VPS).
mt5.initialize() khong tham so CHI ket noi vao terminal dang mo san —
neu may co nhieu terminal MT5 cai o cac thu muc khac nhau, PHAI chi ro
`path` (va tuy chon login/password/server) de dam bao dung tai khoan.

Cau hinh qua .env (watcher.py da tu load .env o cung thu muc):
    MT5_TERMINAL_PATH=C:\\Program Files\\Exness MT5 Terminal 2\\terminal64.exe
    MT5_LOGIN=123456789
    MT5_PASSWORD=xxxxx
    MT5_SERVER=Exness-MT5Trial6

Neu khong set gi ca (mac dinh), hanh vi GIU NGUYEN nhu truoc — chi goi
mt5.initialize() suong, ket noi vao terminal dang mo san.
"""

import logging
import os
from typing import List, Dict, Optional

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None  # Cho phép import module này trên máy không phải Windows để test logic khác

logger = logging.getLogger("mt5_client")

TIMEFRAME_MAP = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}


def init() -> bool:
    """
    Khoi tao ket noi toi MT5 terminal.

    Neu co bien moi truong MT5_TERMINAL_PATH (va tuy chon MT5_LOGIN/
    MT5_PASSWORD/MT5_SERVER) → ket noi CHI DINH DUNG terminal/tai khoan do.
    Nguoc lai → hanh vi cu: ket noi vao terminal dang mo san tren may.
    """
    if mt5 is None:
        raise RuntimeError(
            "Thư viện MetaTrader5 chưa cài hoặc không chạy trên Windows. "
            "Chạy: pip install MetaTrader5"
        )

    path     = os.environ.get("MT5_TERMINAL_PATH")
    login    = os.environ.get("MT5_LOGIN")
    password = os.environ.get("MT5_PASSWORD")
    server   = os.environ.get("MT5_SERVER")

    if path:
        kwargs = {"path": path}
        if login:
            kwargs.update(login=int(login), password=password, server=server)
        ok = mt5.initialize(**kwargs)
        logger.info("mt5.initialize(path=%s, login=%s, server=%s)", path, login, server)
    else:
        ok = mt5.initialize()

    if not ok:
        logger.error("MT5 initialize() thất bại: %s", mt5.last_error())
        return False

    acct = mt5.account_info()
    logger.info("Kết nối MT5 thành công. Account: %s", acct)

    # Canh bao neu login thuc te KHAC voi MT5_LOGIN yeu cau — tranh truong
    # hop code chi dinh 1 tai khoan nhung terminal dang login tai khoan khac
    # (vi du quen dang xuat tai khoan cu truoc khi bot chay).
    if login and acct and str(acct.login) != str(login):
        logger.warning(
            "CANH BAO: Yeu cau login=%s nhung terminal dang dung login=%s — "
            "kiem tra lai .env / dang nhap dung tai khoan trong terminal.",
            login, acct.login,
        )

    return True


def shutdown():
    if mt5 is not None:
        mt5.shutdown()


def get_candles(symbol: str, timeframe_str: str, count: int) -> Optional[List[Dict]]:
    """
    Lấy N nến gần nhất đã đóng (không tính nến đang chạy) cho symbol/timeframe.
    Trả về list dict sắp xếp từ cũ -> mới.
    """
    if mt5 is None:
        raise RuntimeError("MetaTrader5 module không khả dụng trên môi trường này.")

    tf_attr = TIMEFRAME_MAP.get(timeframe_str)
    if tf_attr is None:
        raise ValueError(f"Timeframe không hỗ trợ: {timeframe_str}")
    tf_value = getattr(mt5, tf_attr)

    # position=1 để bỏ qua nến hiện tại đang chạy (chưa đóng), lấy từ nến đã đóng gần nhất
    rates = mt5.copy_rates_from_pos(symbol, tf_value, 1, count)

    if rates is None or len(rates) == 0:
        logger.warning("Không lấy được dữ liệu cho %s %s: %s", symbol, timeframe_str, mt5.last_error())
        return None

    candles = []
    for r in rates:
        candles.append(
            {
                "time": int(r["time"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r["tick_volume"]),  # MT5 forex không có real volume, dùng tick_volume
            }
        )
    return candles


def get_last_closed_time(symbol: str, timeframe_str: str) -> Optional[int]:
    """Lấy timestamp của nến đã đóng gần nhất, dùng để biết khi nào có nến mới."""
    candles = get_candles(symbol, timeframe_str, 1)
    if not candles:
        return None
    return candles[-1]["time"]