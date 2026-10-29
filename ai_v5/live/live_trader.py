# ai_v5/live/live_trader.py
"""
Diem khoi dong CHINH cho AI v5 chay THAT.

Chay doc lap voi watcher.py cua v4 (co the chay tren may/VPS khac, hoac
cung may nhung terminal MT5 khac tro toi tai khoan rieng).

Cach chay:
    1. Tu mo MT5 terminal, dang nhap tai khoan bang tay (rieng, khac tai
       khoan v4).
    2. Dam bao da co model: ai_v5/models/latest_model.pkl (chay
       run_init_train.py truoc neu chua co).
    3. Chay: py -3.11 -m ai_v5.live.live_trader
       (Bot se tu ket noi vao terminal MT5 dang mo san o buoc 1 - KHONG can
       khai bao them gi ca. Chi can khai bao 4 bien moi truong
       AI_V5_MT5_TERMINAL_PATH/LOGIN/PASSWORD/SERVER neu muon ep ket noi
       DUNG 1 terminal cu the, vi du khi chay nhieu terminal MT5 cung luc.)
    4. (Tuy chon) Set AI_V5_TELEGRAM_BOT_TOKEN / AI_V5_TELEGRAM_CHAT_ID de
       nhan thong bao khi co lenh moi va dieu khien qua Telegram.

---------------------------------------------------------------------------
BẢN VÁ:
FIX #1 (cooldown) - truoc day KHONG co kiem tra "pattern nay + symbol nay
    vua duoc duyet/dat lenh gan day chua" -> 1 pattern hinh hoc/harmonic ton
    tai xuyen suot nhieu nen (vd DOUBLE_BOTTOM) co the duoc duyet lai lien
    tuc o moi nen moi trong khi R:R thuc te dang co hep dan (da xac nhan xay
    ra that trong ai_v5_live.log, 23/07). Them _RECENT_TRADE_KEYS + kiem tra
    cooldown truoc khi goi trade_executor.
FIX #2 (thong bao Telegram) - truoc day chi gui so tho (Entry/SL/TP/Lot/R:R/
    Pattern/WinProb). Gio them doan "PHAN TICH" dien giai bang loi (giong
    dinh dang bot v4) + gui kem anh chart qua chart_renderer.py, dung
    sendPhoto (multipart) thay vi chi sendMessage (JSON).
---------------------------------------------------------------------------
"""
import json
import logging
import mimetypes
import ssl
import time
import uuid
from datetime import datetime, timezone, timedelta
from urllib import request as urlreq

import pandas as pd

import mt5_client  # Tai su dung ham get_candles/get_last_closed_time (khong quan tam dang ket noi tk nao)
import market_regime

from ai_v5.config_ai import PROBABILITY_THRESHOLD, LOGS_DIR, TELEGRAM_AI_TOKEN, TELEGRAM_AI_CHAT_ID
from ai_v5.config_live import (
    SYMBOLS, TIMEFRAME, SCAN_INTERVAL_SECONDS, CANDLES_LOOKBACK,
    TRADING_HOURS_ENABLED, TRADING_HOURS_START_VN, TRADING_HOURS_END_VN,
)
from ai_v5.live import mt5_connector, trade_executor, trade_logger, telegram_commander
from ai_v5.live.live_pattern_scanner import scan_all_patterns_live
from ai_v5.data.feature_schema import encode_pattern, encode_regime, encode_source_type, encode_trend_alignment
from ai_v5.live.feature_builder import build_feature_dict
from ai_v5.live.chart_renderer import render_pattern_chart
from ai_v5.ml.predictor import AIPredictor
from ai_v5.ml.auto_retrain import start_scheduler as start_auto_retrain_scheduler

logger = logging.getLogger("ai_v5_live_trader")

# Tranh xu ly trung 1 nen nhieu lan (moi vong quet SCAN_INTERVAL_SECONDS co the roi vao cung 1 nen)
_last_processed_candle_time = {}

# FIX #1: cooldown theo (symbol, pattern) - tranh duyet lai lien tuc cung 1
# pattern con dang "song" tren nhieu nen lien tiep trong khi R:R thuc te da
# co hep. Co the doi thanh doc tu config_live.py (COOLDOWN_MINUTES_PER_PATTERN)
# neu muon chinh khong can sua code - de mac dinh o day cho don gian truoc.
_COOLDOWN_MINUTES = 60
_recent_trade_keys = {}  # {(symbol, pattern): datetime lenh/duyet gan nhat}


def _ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _is_trading_hours() -> bool:
    """
    Gioi han GIO GIAO DICH cho ai_v5 - giong logic cua bot v4
    (watcher.py._is_trading_hours()). Chi anh huong buoc DAT LENH MOI,
    khong anh huong quet/phan tich/gui Telegram/quan ly lenh dang mo.
    """
    if not TRADING_HOURS_ENABLED:
        return True
    start_h = TRADING_HOURS_START_VN % 24
    end_h = TRADING_HOURS_END_VN
    vn_tz = timezone(timedelta(hours=7))
    hour = datetime.now(vn_tz).hour
    if end_h >= 24:
        return hour >= start_h
    if start_h <= end_h:
        return start_h <= hour < end_h
    return hour >= start_h or hour < end_h


def _is_in_cooldown(symbol: str, pattern: str) -> bool:
    """FIX #1: True neu (symbol, pattern) nay vua duoc duyet/dat lenh trong _COOLDOWN_MINUTES gan day."""
    key = (symbol, pattern)
    last_time = _recent_trade_keys.get(key)
    if last_time is None:
        return False
    elapsed_minutes = (datetime.now() - last_time).total_seconds() / 60
    return elapsed_minutes < _COOLDOWN_MINUTES


def _mark_trade_key(symbol: str, pattern: str) -> None:
    _recent_trade_keys[(symbol, pattern)] = datetime.now()


# ─── FIX #2: đoạn diễn giải "PHÂN TÍCH" theo phong cách bot v4 ──────────────

_SOURCE_TYPE_EXPLAIN = {
    "GEOMETRIC_PATTERN": "Mẫu hình giá cổ điển (Double Top/Bottom, H&S, Triangle, Wedge...) — "
                          "dựa trên cấu trúc đỉnh/đáy đã xác nhận.",
    "HARMONIC_PATTERN": "Mẫu hình Harmonic (Gartley/Bat/Butterfly/Crab) — dựa trên tỷ lệ Fibonacci giữa các đoạn XABCD.",
    "CANDLESTICK_PATTERN": "Mẫu hình nến Nhật — tín hiệu đảo chiều/tiếp diễn ngắn hạn tại vùng giá hiện tại.",
    "DIVERGENCE_PATTERN": "Phân kỳ giữa giá và chỉ báo dao động (RSI/MACD) — giá và động lượng đang lệch hướng nhau.",
    "VSA_PATTERN": "Volume Spread Analysis — đọc mối quan hệ giữa biên độ nến và khối lượng để suy ra áp lực mua/bán.",
    "ICT_PATTERN": "Smart Money Concept (Order Block/FVG/Liquidity Sweep) — vùng giá tổ chức lớn có thể đã can thiệp.",
    "CONTINUATION_PATTERN": "Mẫu hình tiếp diễn dài hạn (Rounding/Cup & Handle) — kỳ vọng xu hướng chính tiếp tục.",
}


def _build_analysis_text(symbol: str, pattern: str, source_type: str, direction: str,
                          win_prob: float, regime_res, entry: float, sl: float, tp: float) -> str:
    """FIX #2: sinh đoạn 'PHÂN TÍCH' bằng lời, giống định dạng bot v4 — dùng template theo source_type
    thay vì tự do sinh văn bản (an toàn, không phụ thuộc thêm 1 lệnh gọi AI/LLM nào khác)."""
    rr = abs(tp - entry) / abs(entry - sl) if entry != sl else 0
    explain = _SOURCE_TYPE_EXPLAIN.get(source_type, "Tín hiệu từ hệ thống quét mẫu hình AI v5.")

    regime_txt = ""
    if regime_res is not None:
        regime_map = {"SIDEWAYS": "đi ngang", "TRENDING": "có xu hướng rõ", "VOLATILE": "biến động mạnh", "UNKNOWN": "chưa rõ"}
        trend_map = {"bullish": "TĂNG", "bearish": "GIẢM", "neutral": "trung lập"}
        regime_txt = (f"\n• Thị trường hiện đang <b>{regime_map.get(regime_res.regime, regime_res.regime)}</b>"
                      f", ADX={regime_res.adx:.1f}, xu hướng chính <b>{trend_map.get(regime_res.trend_dir, regime_res.trend_dir)}</b>.")

    conf_txt = ("mức tin cậy CAO" if win_prob >= 0.7 else
                "mức tin cậy khá" if win_prob >= 0.6 else
                "mức tin cậy vừa đủ ngưỡng — cân nhắc quản trị rủi ro chặt hơn")

    return (
        f"🤖 <b>PHÂN TÍCH (tự động, dựa trên dữ liệu)</b>\n"
        f"• {explain}\n"
        f"• Hướng <b>{direction}</b>, tỷ lệ R:R thiết kế <b>1:{rr:.2f}</b>."
        f"{regime_txt}\n"
        f"• Model AI v5 chấm xác suất thắng <b>{win_prob:.1%}</b> — {conf_txt}.\n"
        f"• Mất hiệu lực nếu giá đóng cửa vượt ngược lại qua SL (<code>{sl}</code>)."
    )


def _send_photo(token: str, chat_id: str, image_bytes: bytes, caption: str = "") -> None:
    """Gửi ảnh qua Telegram sendPhoto (multipart/form-data, tự dựng bằng urllib, không cần thêm thư viện ngoài)."""
    if not image_bytes:
        return
    boundary = uuid.uuid4().hex
    parts = []

    def _field(name, value):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())

    _field("chat_id", chat_id)
    if caption:
        _field("caption", caption[:1024])
        _field("parse_mode", "HTML")

    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"chart.png\"\r\n"
        f"Content-Type: image/png\r\n\r\n".encode()
    )
    parts.append(image_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode())

    body = b"".join(parts)
    try:
        req = urlreq.Request(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        urlreq.urlopen(req, timeout=20, context=_ssl_ctx())
    except Exception as e:
        logger.warning(f"Gửi ảnh chart Telegram AI v5 thất bại: {e}")


def _send_ai_v5_telegram_notify(symbol: str, pattern: str, source_type: str, win_prob: float,
                                 result: dict, regime_res=None, candles: list = None) -> None:
    """
    FIX #2: Gui thong bao Telegram theo dinh dang MO RONG - gom (1) tin nhan
    text chinh voi so lieu + doan PHAN TICH dien giai, va (2) 1 anh chart minh
    hoa vung Entry/SL/TP (neu render_pattern_chart() thanh cong), giong dinh
    dang 2 tin nhan lien tiep cua bot v4 (text truoc, chart sau).
    """
    if not TELEGRAM_AI_TOKEN or not TELEGRAM_AI_CHAT_ID:
        logger.warning("Chưa cấu hình AI_V5_TELEGRAM_BOT_TOKEN/CHAT_ID — bỏ qua gửi Telegram.")
        return

    if result.get("success"):
        reverse_note = ""
        if result.get("reversed_ticket"):
            pnl = result.get("reversed_pnl", 0.0)
            reverse_note = f"\n🔄 <i>Đã đóng lệnh ngược #{result['reversed_ticket']} (P&L={pnl:+.2f}) để mở lệnh này.</i>\n"
        msg = (
            f"<b>ĐÃ ĐẶT LỆNH (AI V5)</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"{'BUY' if result['direction'] == 'BUY' else 'SELL'} "
            f"<b>{result['symbol']}</b> #{result['ticket']}\n"
            f"{reverse_note}\n"
            f"Entry: <code>{result['entry']}</code>\n"
            f"SL:    <code>{result['sl']}</code>\n"
            f"TP:    <code>{result['tp']}</code>\n\n"
            f"Lot: <code>{result['lot']}</code> | R:R=1:{result['rr']}\n\n"
            f"<i>Pattern: {pattern} ({source_type}) | WinProb: {win_prob:.1%}</i>\n\n"
        )
        msg += _build_analysis_text(symbol, pattern, source_type, result["direction"], win_prob,
                                     regime_res, result["entry"], result["sl"], result["tp"])
    else:
        msg = (
            f"<b>BỎ QUA LỆNH (AI V5)</b>\n"
            f"{result.get('error', 'Không rõ lý do')}\n"
            f"<i>{pattern} ({source_type}) | {symbol} | WinProb: {win_prob:.1%}</i>"
        )

    try:
        data = json.dumps({"chat_id": TELEGRAM_AI_CHAT_ID, "text": msg, "parse_mode": "HTML"}).encode()
        req = urlreq.Request(
            f"https://api.telegram.org/bot{TELEGRAM_AI_TOKEN}/sendMessage",
            data=data, headers={"Content-Type": "application/json"}, method="POST",
        )
        urlreq.urlopen(req, timeout=10, context=_ssl_ctx())
    except Exception as e:
        logger.warning(f"Gửi Telegram AI v5 thất bại: {e}")

    # FIX #2: chỉ vẽ + gửi chart khi lệnh THÀNH CÔNG (tránh vẽ chart cho các lệnh bị bỏ qua, đỡ tốn CPU)
    if result.get("success") and candles:
        try:
            png = render_pattern_chart(
                candles=candles, symbol=symbol, pattern=pattern, direction=result["direction"],
                entry=result["entry"], sl=result["sl"], tp=result["tp"],
            )
            if png:
                _send_photo(TELEGRAM_AI_TOKEN, TELEGRAM_AI_CHAT_ID, png, caption=f"{symbol} — {pattern}")
        except Exception as e:
            logger.warning(f"Vẽ/gửi chart Telegram AI v5 thất bại (không ảnh hưởng lệnh đã đặt): {e}")


def run_once(predictor: AIPredictor) -> None:
    for symbol in SYMBOLS:
        try:
            if not telegram_commander.is_symbol_enabled(symbol):
                continue  # Auto Trade dang TAT hoac symbol nay dang bi tam dung qua Telegram

            last_closed = mt5_client.get_last_closed_time(symbol, TIMEFRAME)
            if last_closed is None:
                continue
            if _last_processed_candle_time.get(symbol) == last_closed:
                continue  # Chua co nen moi dong, bo qua vong nay

            candles = mt5_client.get_candles(symbol, TIMEFRAME, CANDLES_LOOKBACK)
            if not candles or len(candles) < 220:
                continue

            _last_processed_candle_time[symbol] = last_closed

            matches = scan_all_patterns_live(candles, symbol)
            if not matches:
                continue

            regime_res = market_regime.get_regime(candles, symbol)

            for source_type, match in matches:
                features = build_feature_dict(match, source_type, regime_res)
                win_prob = predictor.predict_probability(features)
                decision = win_prob >= PROBABILITY_THRESHOLD

                logger.info(f"[SCAN] {symbol} | {match['pattern']} ({source_type}) | "
                            f"Hướng={match['direction']} | WinProb={win_prob:.1%} | "
                            f"{'✅ DUYỆT' if decision else '⛔ BỎ QUA'}")

                if not decision:
                    continue

                # FIX #1: kiểm tra cooldown TRƯỚC khi xét giờ giao dịch/đặt lệnh — nếu cùng
                # (symbol, pattern) vừa được duyệt gần đây thì bỏ qua, tránh đuổi theo 1 setup
                # đang co hẹp dần dư địa lợi nhuận qua nhiều nến liên tiếp.
                if _is_in_cooldown(symbol, match["pattern"]):
                    logger.info(f"[AI v5 LIVE] {symbol}/{match['pattern']} đang trong cooldown "
                               f"({_COOLDOWN_MINUTES} phút) — bỏ qua dù đã duyệt WinProb.")
                    continue

                if not _is_trading_hours():
                    logger.info(f"[AI v5 LIVE] Ngoài khung giờ giao dịch ({TRADING_HOURS_START_VN}h-"
                               f"{TRADING_HOURS_END_VN}h VN) — bỏ qua mở lệnh {symbol} dù đã duyệt.")
                    continue

                result = trade_executor.place_ai_v5_trade(
                    symbol=symbol, direction=match["direction"], sl=match["sl"], tp=match["tp"],
                    pattern_name=match["pattern"], win_prob=win_prob,
                )

                if result["success"]:
                    _mark_trade_key(symbol, match["pattern"])  # FIX #1: chỉ đánh dấu cooldown khi ĐẶT LỆNH THÀNH CÔNG
                    try:
                        trade_logger.log_open_trade(
                            ticket=result["ticket"], symbol=symbol, pattern=match["pattern"],
                            source_type=source_type, direction=match["direction"],
                            entry=result["entry"], sl=result["sl"], tp=result["tp"],
                            lot=result["lot"], win_probability=win_prob, features=features,
                        )
                    except Exception as e:
                        logger.error(f"[AI v5 LIVE] Lỗi ghi log lệnh vào DB (lệnh #{result['ticket']} vẫn đã đặt "
                                     f"THÀNH CÔNG trên MT5, chỉ lỗi ghi log): {e}", exc_info=True)
                else:
                    logger.warning(f"[AI v5 LIVE] Đặt lệnh thất bại: {result['error']}")

                try:
                    _send_ai_v5_telegram_notify(symbol, match["pattern"], source_type, win_prob, result,
                                                 regime_res=regime_res, candles=candles)
                except Exception as e:
                    logger.error(f"[AI v5 LIVE] Lỗi gửi Telegram (không ảnh hưởng lệnh đã đặt): {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Lỗi khi quét {symbol} trong AI v5 Live Trader: {e}", exc_info=True)


def main():
    import os
    log_file = os.path.join(LOGS_DIR, "ai_v5_live.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()],
    )

    logger.info("=" * 70)
    logger.info("=== AI v5 LIVE TRADER ===")
    logger.info("=" * 70)

    if not mt5_connector.init():
        logger.error("❌ Không thể kết nối MT5. Dừng chương trình.")
        return

    predictor = AIPredictor()
    if predictor.model is None:
        logger.error("❌ Chưa có model AI v5 (ai_v5/models/latest_model.pkl). "
                     "Hãy chạy run_init_train.py trước khi khởi động Live Trader.")
        mt5_connector.shutdown()
        return

    if TELEGRAM_AI_TOKEN and TELEGRAM_AI_CHAT_ID:
        telegram_commander.start(TELEGRAM_AI_TOKEN, TELEGRAM_AI_CHAT_ID, predictor=predictor)
        logger.info("✅ AI v5 TelegramCommander đã khởi động (lắng nghe lệnh /start /stop /status ...).")
        try:
            telegram_commander._send(
                TELEGRAM_AI_TOKEN, TELEGRAM_AI_CHAT_ID,
                "🟢 <b>AI v5 Live Trader đã khởi động</b>\n"
                f"Symbols: {', '.join(SYMBOLS)} | TF: {TIMEFRAME}\n"
                f"Ngưỡng quyết định: {PROBABILITY_THRESHOLD:.0%}\n"
                f"Giờ giao dịch: {TRADING_HOURS_START_VN}h–{TRADING_HOURS_END_VN}h VN "
                f"({'BẬT' if TRADING_HOURS_ENABLED else 'TẮT'})\n"
                f"Cooldown mỗi pattern: {_COOLDOWN_MINUTES} phút\n"
                "<i>/help để xem danh sách lệnh.</i>",
            )
        except Exception as e:
            logger.warning(f"Gửi tin nhắn khởi động thất bại: {e}")
    else:
        logger.warning("⚠️ Chưa cấu hình AI_V5_TELEGRAM_BOT_TOKEN/CHAT_ID — bot chạy nhưng không có "
                       "kênh Telegram để theo dõi/điều khiển.")

    try:
        start_auto_retrain_scheduler()
        logger.info("✅ AI v5 Auto-Retrain scheduler đã khởi động (vòng phản hồi tự học).")
    except Exception as e:
        logger.error(f"Không khởi động được Auto-Retrain scheduler: {e}", exc_info=True)

    logger.info(f"✅ Sẵn sàng. Symbols={SYMBOLS} | TF={TIMEFRAME} | "
                f"Ngưỡng quyết định={PROBABILITY_THRESHOLD:.0%} | Quét mỗi {SCAN_INTERVAL_SECONDS}s | "
                f"Giờ giao dịch={TRADING_HOURS_START_VN}h-{TRADING_HOURS_END_VN}h "
                f"({'BẬT' if TRADING_HOURS_ENABLED else 'TẮT'}) | Cooldown={_COOLDOWN_MINUTES}ph")

    sync_counter = 0
    try:
        while True:
            run_once(predictor)
            sync_counter += 1
            if sync_counter % 20 == 0:  # Dong bo ket qua lenh da dong dinh ky (khong can moi vong quet)
                trade_logger.sync_closed_trades()
            time.sleep(SCAN_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        logger.info("Dừng AI v5 Live Trader theo yêu cầu người dùng.")
    finally:
        mt5_connector.shutdown()


if __name__ == "__main__":
    main()
