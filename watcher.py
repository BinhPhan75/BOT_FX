# watcher.py
"""
watcher.py
Script chinh: vong lap chinh theo doi nen moi tren MT5,
phan tich pattern, gui Telegram, tu dong dat lenh (bot v4 thuan, doc lap hoan toan voi ai_v5).
"""

import json
import logging
import os
import ssl
import sys
import time
from datetime import datetime, timezone, timedelta
from urllib import request as urlreq

import config
import mt5_client
import analysis
import trend_filter
import notifier
import trader
import trade_logger
import adaptive_filter
import trailing_stop
import param_loader
import auto_tuner
import market_regime
import telegram_commander

# [20/07/2026] Da go bo hoan toan tich hop AI v5 khoi watcher.py (theo yeu cau
# tach bach tuyet doi giua bot v4 va ai_v5). ai_v5 gio chay doc lap hoan toan
# qua ai_v5/live/live_trader.py tren tai khoan demo rieng, khong con phu
# thuoc/duoc goi tu watcher.py duoi bat ky hinh thuc nao.

# Dedupe dung chung cho notifier + trader
_last_signal_sent: dict = {}


def _is_trading_hours() -> bool:
    if not getattr(config, "TRADING_HOURS_ENABLED", False):
        return True
    start_h = getattr(config, "TRADING_HOURS_START_VN", 7) % 24
    end_h   = getattr(config, "TRADING_HOURS_END_VN", 24)
    vn_tz = timezone(timedelta(hours=7))
    hour  = datetime.now(vn_tz).hour
    if end_h >= 24:
        return hour >= start_h
    if start_h <= end_h:
        return start_h <= hour < end_h
    return hour >= start_h or hour < end_h


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def _load_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


def _ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _get_tg_creds():
    token   = os.environ.get("TELEGRAM_BOT_TOKEN") or getattr(config, "TELEGRAM_BOT_TOKEN", None)
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")   or getattr(config, "TELEGRAM_CHAT_ID",   None)
    return token, chat_id


def _send_trade_notify(signal, result: trader.TradeResult):
    token, chat_id = _get_tg_creds()
    if not token or not chat_id:
        return
    p = param_loader.get_all(signal.symbol)
    if result.success:
        reverse_line = ""
        if result.reversed_ticket:
            reverse_line = f"🔄 <i>Da dong lenh nguoc #{result.reversed_ticket} (P&L={result.reversed_pnl:+.2f}) de mo lenh nay.</i>\n\n"
        msg = (
            f"<b>DA DAT LENH (V4 LIVE)</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"{reverse_line}"
            f"{'BUY' if result.direction=='BUY' else 'SELL'} "
            f"<b>{result.symbol}</b> #{result.ticket}\n\n"
            f"Entry: <code>{result.entry}</code>\n"
            f"SL:    <code>{result.sl}</code>\n"
            f"TP:    <code>{result.tp}</code>\n\n"
            f"Lot: <code>{result.lot}</code> | R:R=1:{result.rr}\n\n"
            f"<i>Pattern: {signal.pattern} | {signal.timeframe}</i>\n"
            f"<i>ATR({p['atr_period']})x{p['atr_multiplier']} TP_x{p['tp_atr_multiplier']}</i>"
        )
    else:
        msg = f"<b>BO QUA LENH (V4)</b>\n{result.error}\n<i>{signal.pattern} | {signal.symbol}</i>"

    try:
        data = json.dumps({"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}).encode()
        req = urlreq.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data, headers={"Content-Type": "application/json"}, method="POST")
        urlreq.urlopen(req, timeout=10, context=_ssl_ctx())
    except Exception as e:
        logging.getLogger("watcher").warning("Gui Telegram that bai: %s", e)


def main():
    _load_env()
    setup_logging()
    logger = logging.getLogger("watcher")

    param_loader.apply()
    auto_trade = getattr(config, "AUTO_TRADE_ENABLED", False)
    logger.info("=== AI Forex Watcher (bot v4) ===")
    logger.info("Symbols: %s | TF: %s | Auto V4: %s", config.SYMBOLS, config.TIMEFRAME, "ON" if auto_trade else "OFF")

    if not mt5_client.init():
        logger.error("Khong ket noi duoc MT5.")
        sys.exit(1)

    trade_logger.init_db()

    token, chat_id = _get_tg_creds()
    if token and chat_id:
        tg = telegram_commander.start(token, chat_id)
        logger.info("TelegramCommander: %s", tg.name)
        telegram_commander._send(token, chat_id, f"Bot v4 khoi dong!\n/help xem lenh.")
    else:
        logger.warning("Khong co Telegram credentials — commander bi tat.")

    last_processed = {sym: None for sym in config.SYMBOLS}

    try:
        while True:
            for symbol in config.SYMBOLS:
                if symbol in getattr(config, "DISABLED_SYMBOLS", set()):
                    continue
                try:
                    last_time = mt5_client.get_last_closed_time(symbol, config.TIMEFRAME)
                    if last_time is None or last_processed[symbol] == last_time:
                        continue

                    # Lay danh sach nến từ MT5
                    candles = mt5_client.get_candles(symbol, config.TIMEFRAME, config.BARS_COUNT)
                    if not candles:
                        continue

                    last_processed[symbol] = last_time

                    # [20/07/2026] Da go bo khoi "SHADOW MODE AI V5" tung nam o day
                    # (quet 16 mau hinh + goi model ai_v5 + gui Telegram). ai_v5 gio
                    # chay hoan toan doc lap qua ai_v5/live/live_trader.py, khong con
                    # duoc goi tu watcher.py cua v4 nua.

                    # ====================================================================
                    # 📊 [NHÁNH XỬ LÝ GỐC - LIVE TRADING BOT V4]
                    # ====================================================================
                    regime_result = market_regime.get_regime(candles, symbol)
                    if not regime_result.allowed:
                        logger.info("Volatile skip %s: %s", symbol, regime_result.reason)
                        continue

                    signal = analysis.analyze(candles, symbol, config.TIMEFRAME, verbose=True)
                    if not signal:
                        continue

                    htf_ok    = True
                    htf_label = "off"
                    if config.HTF_TIMEFRAME:
                        htf_candles = mt5_client.get_candles(symbol, config.HTF_TIMEFRAME, config.HTF_BARS_COUNT)
                        if htf_candles:
                            htf_res   = trend_filter.get_trend(htf_candles, config.HTF_TIMEFRAME)
                            htf_label = htf_res.trend
                            htf_ok    = trend_filter.is_confirmed_by_trend(signal.pattern, htf_res.trend)
                            signal.extra["htf_trend"]     = htf_res.trend
                            signal.extra["htf_timeframe"] = config.HTF_TIMEFRAME

                    if not htf_ok:
                        logger.info("HTF skip %s %s (%s)", symbol, signal.pattern, htf_label)
                        continue

                    p = param_loader.get_all(symbol)
                    logger.info(
                        "SIGNAL V4: %s | %s | price=%s | regime=%s(ADX=%.1f) | HTF=%s",
                        signal.symbol, signal.pattern, signal.price, regime_result.regime, regime_result.adx, htf_label
                    )

                    af = adaptive_filter.should_trade(signal, regime=regime_result)
                    if not af.passed:
                        logger.info("AF skip: %s", af.reason)
                        continue

                    logger.info("AF PASS score=%d/100 — %s", af.score, af.reason)

                    dedupe_key = (symbol, signal.pattern)
                    now_ts = time.time()
                    last_ts = _last_signal_sent.get(dedupe_key)
                    if last_ts is not None and (now_ts - last_ts) < getattr(config, "DEDUPE_MINUTES", 60) * 60:
                        logger.info("Dedupe V4: bo qua %s %s", symbol, signal.pattern)
                        continue
                    _last_signal_sent[dedupe_key] = now_ts

                    notifier.send_signal(signal)

                    if not _is_trading_hours():
                        logger.info("Ngoai khung gio giao dich — bo qua mo lenh V4.")
                    elif getattr(config, "AUTO_TRADE_ENABLED", False):
                        result = trader.place_trade(signal)
                        _send_trade_notify(signal, result)
                        if result.success:
                            logger.info("LENH THANH CONG V4: #%d %s", result.ticket, result.symbol)
                            trade_logger.log_open_trade(
                                ticket=result.ticket, signal=signal,
                                direction=result.direction, lot=result.lot,
                                entry=result.entry, sl=result.sl, tp=result.tp,
                            )
                    else:
                        logger.info("Auto trade V4 OFF — chi quan sat.")

                except Exception as e:
                    logging.getLogger("watcher").exception("Loi xu ly %s: %s", symbol, e)

            trailing_stop.update(mt5_client.get_candles)
            trade_logger.check_closed_trades()
            auto_tuner.maybe_run()   

            time.sleep(config.POLL_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        logger.info("Nhan Ctrl+C — dang dung...")
    finally:
        mt5_client.shutdown()
        logger.info("Da dung watcher.")


if __name__ == "__main__":
    main()