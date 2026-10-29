# ai_v6/live/mt5_connector.py
"""
Ket noi MT5 cho ai_v6 - GIONG HET co che cua ai_v5/live/mt5_connector.py
(mac dinh dung terminal dang mo san), CHI khac ten 4 bien moi truong tuy
chon (AI_V6_MT5_* thay vi AI_V5_MT5_*) de phan biet khi chay nhieu terminal
MT5 cung luc tren cung 1 may (v4 + ai_v5 + ai_v6 deu co the chay song song).
"""
import logging

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

from ai_v6.config_live import AI_V6_MT5_TERMINAL_PATH, AI_V6_MT5_LOGIN, AI_V6_MT5_PASSWORD, AI_V6_MT5_SERVER

logger = logging.getLogger("ai_v6_mt5")


def init() -> bool:
    if mt5 is None:
        raise RuntimeError(
            "Thư viện MetaTrader5 chưa cài hoặc không chạy trên Windows. Chạy: pip install MetaTrader5"
        )

    if AI_V6_MT5_TERMINAL_PATH:
        kwargs = {"path": AI_V6_MT5_TERMINAL_PATH}
        if AI_V6_MT5_LOGIN:
            kwargs.update(login=int(AI_V6_MT5_LOGIN), password=AI_V6_MT5_PASSWORD, server=AI_V6_MT5_SERVER)
        ok = mt5.initialize(**kwargs)
        logger.info("AI v6 mt5.initialize(path=%s, login=%s, server=%s)",
                    AI_V6_MT5_TERMINAL_PATH, AI_V6_MT5_LOGIN, AI_V6_MT5_SERVER)
    else:
        ok = mt5.initialize()
        logger.info("AI v6 mt5.initialize() — kết nối vào terminal MT5 đang mở sẵn trên máy.")

    if not ok:
        logger.error("AI v6 MT5 initialize() thất bại: %s", mt5.last_error())
        logger.error("Kiểm tra: đã mở sẵn MT5 và đăng nhập tài khoản (RIÊNG cho ai_v6) chưa?")
        return False

    acct = mt5.account_info()
    if not acct:
        logger.error("Kết nối MT5 thành công nhưng không lấy được account_info() — có thể chưa đăng nhập tài khoản.")
        return False

    logger.info("✅ AI v6 đã kết nối MT5 thành công. Account: login=%s server=%s balance=%s %s",
                acct.login, acct.server, acct.balance, acct.currency)

    if AI_V6_MT5_LOGIN and str(acct.login) != str(AI_V6_MT5_LOGIN):
        logger.warning("⚠️ CẢNH BÁO: yêu cầu login=%s nhưng terminal đang dùng login=%s.",
                        AI_V6_MT5_LOGIN, acct.login)

    if acct.trade_mode == 0 and "demo" not in (acct.server or "").lower() and "trial" not in (acct.server or "").lower():
        logger.warning(
            "⚠️ CHÚ Ý: server '%s' không có chữ 'demo'/'trial' — hãy xác nhận LẠI đây đúng là "
            "tài khoản DEMO trước khi để bot DCA đặt lệnh thật.", acct.server,
        )

    return True


def shutdown():
    if mt5 is not None:
        mt5.shutdown()
