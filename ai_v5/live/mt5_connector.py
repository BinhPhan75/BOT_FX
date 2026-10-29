# ai_v5/live/mt5_connector.py
"""
Ket noi MT5 cho ai_v5 - MAC DINH ket noi vao terminal MT5 dang MO SAN tren
may (nguoi dung tu mo MT5, dang nhap tai khoan bang tay TRUOC khi chay
live_trader.py) - giong het cach mt5_client.py cua v4 hoat dong khi khong
khai bao gi ca.

Neu muon ep bot ket noi DUNG 1 terminal/tai khoan cu the (vi du chay nhieu
terminal MT5 cung luc tren may, hoac chay tu dong khong nguoi truc), co the
KHAI BAO THEM (tuy chon) 4 bien moi truong AI_V5_MT5_TERMINAL_PATH /
AI_V5_MT5_LOGIN / AI_V5_MT5_PASSWORD / AI_V5_MT5_SERVER - neu khong khai
bao gi, bot se tu dong dung terminal dang mo san (mac dinh, don gian nhat).
"""
import logging

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

from ai_v5.config_live import AI_V5_MT5_TERMINAL_PATH, AI_V5_MT5_LOGIN, AI_V5_MT5_PASSWORD, AI_V5_MT5_SERVER

logger = logging.getLogger("ai_v5_mt5")


def init() -> bool:
    if mt5 is None:
        raise RuntimeError(
            "Thư viện MetaTrader5 chưa cài hoặc không chạy trên Windows. Chạy: pip install MetaTrader5"
        )

    if AI_V5_MT5_TERMINAL_PATH:
        # Che do CHI DINH terminal/tai khoan cu the (tuy chon, chi dung khi khai bao bien moi truong)
        kwargs = {"path": AI_V5_MT5_TERMINAL_PATH}
        if AI_V5_MT5_LOGIN:
            kwargs.update(login=int(AI_V5_MT5_LOGIN), password=AI_V5_MT5_PASSWORD, server=AI_V5_MT5_SERVER)
        ok = mt5.initialize(**kwargs)
        logger.info("AI v5 mt5.initialize(path=%s, login=%s, server=%s)",
                    AI_V5_MT5_TERMINAL_PATH, AI_V5_MT5_LOGIN, AI_V5_MT5_SERVER)
    else:
        # Che do MAC DINH: ket noi vao terminal MT5 dang MO SAN tren may
        # (nguoi dung tu mo MT5 + dang nhap tai khoan bang tay truoc do)
        ok = mt5.initialize()
        logger.info("AI v5 mt5.initialize() — kết nối vào terminal MT5 đang mở sẵn trên máy.")

    if not ok:
        logger.error("AI v5 MT5 initialize() thất bại: %s", mt5.last_error())
        logger.error("Kiểm tra: đã mở sẵn MT5 và đăng nhập tài khoản chưa? "
                     "Terminal có đang bị treo/chưa load xong không?")
        return False

    acct = mt5.account_info()
    if not acct:
        logger.error("Kết nối MT5 thành công nhưng không lấy được account_info() — "
                     "có thể chưa đăng nhập tài khoản nào trong terminal đang mở.")
        return False

    logger.info("✅ AI v5 đã kết nối MT5 thành công. Account: login=%s server=%s balance=%s %s",
                acct.login, acct.server, acct.balance, acct.currency)

    if AI_V5_MT5_LOGIN and str(acct.login) != str(AI_V5_MT5_LOGIN):
        logger.warning(
            "⚠️ CẢNH BÁO: yêu cầu login=%s nhưng terminal đang dùng login=%s.",
            AI_V5_MT5_LOGIN, acct.login,
        )

    # Canh bao neu day co ve la tai khoan LIVE (khong phai demo) - an toan them 1 lop
    if acct.trade_mode == 0 and "demo" not in (acct.server or "").lower() and "trial" not in (acct.server or "").lower():
        logger.warning(
            "⚠️ CHÚ Ý: server '%s' không có chữ 'demo'/'trial' trong tên — hãy xác nhận LẠI "
            "đây đúng là tài khoản DEMO trước khi để bot đặt lệnh thật. Nếu chắc chắn đây là "
            "demo (chỉ tên server không có chữ demo), có thể bỏ qua cảnh báo này.", acct.server,
        )

    return True


def shutdown():
    if mt5 is not None:
        mt5.shutdown()
