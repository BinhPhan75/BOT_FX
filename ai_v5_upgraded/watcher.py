# watcher.py  v5 (Shadow Mode Integrated)
"""
watcher.py  v5
Script chinh: vong lap chinh theo doi nen moi tren MT5,
phan tich pattern, gui Telegram, tu dong dat lenh (V4 Live + V5 Shadow Mode).
"""

import json
import logging
import os
import ssl
import sys
import time
import pickle
import numpy as np
import pandas as pd
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
from ai_v5.ml.ai_learner import AILearner  
import market_regime
import telegram_commander

# --- [TÍCH HỢP V5] ---
from ai_v5.pipeline.pattern_rules import detect_16_patterns
from ai_v5.pipeline.swing_detector import find_swing_points
from ai_v5.ml.model_manager import ModelManager
from ai_v5.data.feature_schema import validate_features

# Tải bộ não AI V5 đã huấn luyện thành công (dùng chung ModelManager với predictor.py
# để tránh 2 nguồn model_path lệch nhau — model được lưu vào ai_v5/models/latest_model.pkl)
_v5_model_manager = ModelManager()
lgbm_model_v5, _v5_model_meta = _v5_model_manager.load_latest_model()
if lgbm_model_v5 is not None:
    logging.getLogger("watcher").info("[V5] Da tai bo nao AI V5 thanh cong (%s).", _v5_model_meta.get("model_name", "N/A") if _v5_model_meta else "N/A")
else:
    logging.getLogger("watcher").warning("[V5] Chua co model 'latest_model.pkl'. Chuc nang V5 se tam bo qua.")

# Dedupe dung chung cho notifier + trader
_last_signal_sent: dict = {}
_last_v5_signal_sent: dict = {} # Thêm bộ chặn trùng tín hiệu cho V5


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


def _send_v5_telegram_alert(symbol, match, win_prob):
    """
    [V5 SHADOW FUNCTION] Ham gui thong bao tin hieu mo hinh hinh hoc dac biet cua AI V5 ve Telegram
    """
    token, chat_id = _get_tg_creds()
    if not token or not chat_id:
        return

    msg = (
        f"🚨 <b>[AI V5 - SHADOW ALERT]</b> 🚨\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Cap tien: <b>{symbol}</b> | Khung: {config.TIMEFRAME}\n"
        f"📐 Mo hinh: <code>{match['pattern']}</code>\n"
        f"📈 Huong khuyen nghi: <b>{'BUY 🟢' if match['direction']=='BUY' else 'SELL 🔴'}</b>\n\n"
        f"🧠 <b>AI V5 Cham diem:</b>\n"
        f" ├─ Xac suat thang: <code>{win_prob*100:.1f}%</code>\n"
        f" └─ Trang thai: <b>[DUYET TIN HIEU]</b>\n\n"
        f"📐 <b>Thiet lap ky thuat chuẩn:</b>\n"
        f" ├─ Entry (Close): <code>{match.get('entry', 'Theo nen dong cua')}</code>\n"
        f" ├─ SL: <code>{match['sl']:.5f}</code>\n"
        f" └─ TP: <code>{match['tp']:.5f}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 <i>Trang thai: Chay thu nghiem song song V4 (Khong vao lenh)</i>"
    )

    try:
        data = json.dumps({"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}).encode()
        req = urlreq.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data, headers={"Content-Type": "application/json"}, method="POST",
        )
        urlreq.urlopen(req, timeout=10, context=_ssl_ctx())
    except Exception as e:
        logging.getLogger("watcher").warning("[V5] Gui Telegram alert that bai: %s", e)


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
    logger.info("=== AI Forex Watcher v5 (V4 Live + V5 Shadow) ===")
    logger.info("Symbols: %s | TF: %s | Auto V4: %s", config.SYMBOLS, config.TIMEFRAME, "ON" if auto_trade else "OFF")

    if not mt5_client.init():
        logger.error("Khong ket noi duoc MT5.")
        sys.exit(1)

    trade_logger.init_db()

    token, chat_id = _get_tg_creds()
    if token and chat_id:
        tg = telegram_commander.start(token, chat_id)
        logger.info("TelegramCommander: %s", tg.name)
        telegram_commander._send(token, chat_id, f"Bot V5 (V4 Live + V5 Shadow) khoi dong!\n/help xem lenh.")
    else:
        logger.warning("Khong co Telegram credentials — commander bi tat.")

    import threading
    def start_ai_learner_bg():
        try:
            ai_daemon = AILearner(check_interval_seconds=86400)
            ai_daemon.run_forever()
        except Exception as e:
            logging.getLogger("watcher").error("Khong the khoi chay AI Learner ngam: %s", e)

    threading.Thread(target=start_ai_learner_bg, name="AI_Learner_Loop", daemon=True).start()

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

                    # Chuyển đổi candles sang định dạng DataFrame để tính toán cho V5
                    df_rates = pd.DataFrame(candles)

                    # ====================================================================
                    # 🚀 [NHÁNH XỬ LÝ SONG SONG - SHADOW MODE AI V5]
                    # ====================================================================
                    if lgbm_model_v5 is not None:
                        try:
                            # 1. Vẽ đỉnh/đáy cấu trúc bằng swing_detector chính thức của ai_v5
                            #    (dùng cửa sổ ~150 nến gần nhất để không phải quét lại toàn bộ mỗi vòng lặp)
                            swings_list = find_swing_points(df_rates.tail(150).reset_index(drop=True), left_bars=5, right_bars=5)

                            # 2. Tính chỉ báo ATR động cho cây nến hiện tại
                            df_rates['tr'] = np.maximum(
                                df_rates['high'] - df_rates['low'],
                                np.maximum(abs(df_rates['high'] - df_rates['close'].shift(1)),
                                           abs(df_rates['low'] - df_rates['close'].shift(1)))
                            )
                            current_atr = df_rates['tr'].rolling(window=14).mean().iloc[-1]
                            if pd.isna(current_atr) or current_atr == 0:
                                current_atr = float(df_rates['close'].iloc[-1]) * 0.001

                            current_close = float(df_rates['close'].iloc[-1])

                            # 3. Khớp 16 mô hình toán học — LƯU Ý: detect_16_patterns cần current_price
                            #    dạng float (không phải dict nến), khớp đúng chữ ký trong pattern_rules.py
                            match_v5 = detect_16_patterns(swings_list, current_close, float(current_atr))

                            if match_v5:
                                match_v5['entry'] = current_close
                                regime_result_v5 = market_regime.get_regime(candles, symbol)

                                prev_close = float(df_rates['close'].iloc[-2]) if len(df_rates) > 1 else current_close
                                momentum_ratio = (current_close - prev_close) / current_atr if current_atr else 0.0
                                now_vn = datetime.now(timezone(timedelta(hours=7)))

                                # Tạo Vector Features đúng SCHEMA HỢP NHẤT (ai_v5/data/feature_schema.py)
                                from ai_v5.data.feature_schema import encode_pattern, encode_regime, encode_source_type
                                features_v5 = pd.DataFrame([{
                                    'source_type_encoded': encode_source_type('GEOMETRIC_PATTERN'),
                                    'pattern_encoded': encode_pattern(match_v5['pattern']),
                                    'regime_type_encoded': encode_regime(regime_result_v5.regime if regime_result_v5 else "UNKNOWN"),
                                    'adx_value': float(regime_result_v5.adx) if regime_result_v5 else 25.0,
                                    'rsi_14': 50.0,
                                    'volume_ratio': float(momentum_ratio),
                                    'atr_value': float(current_atr),
                                    'distance_to_zone_pct': 0.0,
                                    'hour_of_day': now_vn.hour,
                                    'day_of_week': now_vn.weekday(),
                                }])
                                features_v5 = validate_features(features_v5)

                                # Bộ não AI V5 dự đoán xác suất chiến thắng
                                win_prob = lgbm_model_v5.predict_proba(features_v5)[0][1]

                                logger.info("[V5 SHADOW] Phat hien %s | Win Prob: %.2f%%", match_v5['pattern'], win_prob * 100)

                                # Nếu xác suất thắng vượt bộ lọc tinh lọc (> 55%), thực hiện gửi Telegram
                                if win_prob >= 0.55:
                                    dedupe_key_v5 = (symbol, match_v5['pattern'])
                                    now_ts = time.time()
                                    last_ts_v5 = _last_v5_signal_sent.get(dedupe_key_v5)
                                    
                                    # Kiểm tra tránh lặp tin nhắn trong vòng 60 phút
                                    if last_ts_v5 is None or (now_ts - last_ts_v5) > getattr(config, "DEDUPE_MINUTES", 60) * 60:
                                        _last_v5_signal_sent[dedupe_key_v5] = now_ts
                                        _send_v5_telegram_alert(symbol, match_v5, win_prob)
                                        logger.info("[V5 SHADOW] -> DA BAN TIN HIEU QUA TELEGRAM.")
                        except Exception as eV5:
                            logger.error("Loi trong nhanh quet Shadow V5: %s", eV5, exc_info=True)

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