# ai_v5/live/telegram_commander.py
"""
telegram_commander.py cho AI v5 — daemon thread lang nghe lenh Telegram,
DUNG BOT TELEGRAM RIENG cua AI v5 (AI_V5_TELEGRAM_BOT_TOKEN/CHAT_ID),
hoan toan doc lap voi telegram_commander.py cua bot v4.

Lenh:
  /start   — Bat auto trade (AI v5 tiep tuc dat lenh khi du dieu kien)
  /stop    — Tat auto trade (AI v5 chuyen sang che do chi quan sat/log, khong dat lenh moi)
  /disable SYMBOL — Tam dung 1 symbol
  /enable SYMBOL  — Bat lai 1 symbol
  /analyze SYMBOL [KHUNG] — Phan tich real-time (mac dinh ca H1+M15+M5)
  /status  — Tai khoan + lenh dang mo + trang thai
  /params  — Nguong quyet dinh & cau hinh risk hien tai
  /tune    — Huong dan train lai model
  /help    — Danh sach lenh
"""
import json
import logging
import ssl
import threading
import time
from urllib import request as urlreq
from urllib.error import URLError

from ai_v5 import config_live
from ai_v5.config_live import MAGIC_NUMBER

logger = logging.getLogger("ai_v5_tg_commander")

try:
    import MetaTrader5 as _mt5
except Exception:
    _mt5 = None

# Trang thai runtime (doc/ghi boi ca live_trader.py va commander nay)
AUTO_TRADE_ENABLED = True
DISABLED_SYMBOLS = set()

# Predictor da nap san (truyen vao qua start(), de lenh /analyze khong phai
# nap lai model tu dia moi lan goi - tiet kiem thoi gian + dam bao dung
# model dang dung cho giao dich that).
_predictor = None


def _resolve_symbol_case(user_input: str) -> str:
    """
    MT5 phan biet CHU HOA/THUONG trong ten symbol (vd XAUUSDc voi c thuong,
    khac han XAUUSDC). Nguoi dung go lenh Telegram thuong go hoa toan bo
    (thoi quen tu nhien), nen can tu dong khop lai DUNG chu hoa/thuong theo
    danh sach symbol da cau hinh (config_live.SYMBOLS), thay vi ep buoc
    .upper() toan bo chuoi nhu truoc day (gay loi "khong du du lieu nen"
    vi symbol sai chu, khong ton tai tren MT5).
    """
    for s in config_live.SYMBOLS:
        if s.upper() == user_input.upper():
            return s
    return user_input  # Khong khop cau hinh nao -> giu nguyen nhu nguoi dung go (co the la symbol khac ngoai danh sach)


# ─── SSL / HTTP ────────────────────────────────────────────────────────────

def _ssl():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception as e:
        logger.warning("certifi lỗi (%s) — dùng SSL context mặc định hệ thống.", e)
        return ssl.create_default_context()


def _get(token, method, params=None, timeout=30):
    url = f"https://api.telegram.org/bot{token}/{method}"
    if params:
        from urllib.parse import urlencode
        url += "?" + urlencode(params)
    with urlreq.urlopen(urlreq.Request(url), timeout=timeout, context=_ssl()) as r:
        return json.loads(r.read())


def _send(token: str, chat_id: str, text: str) -> None:
    try:
        data = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
        req = urlreq.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data, headers={"Content-Type": "application/json"}, method="POST",
        )
        urlreq.urlopen(req, timeout=10, context=_ssl())
    except Exception as e:
        logger.warning("Gửi Telegram thất bại: %s", e)


# ─── Real-time multi-timeframe analysis ────────────────────────────────────

def _analyze_one_timeframe(symbol: str, timeframe: str) -> str:
    """Quet 1 khung thoi gian, tra ve doan text ket qua (khong bao gom header chung)."""
    try:
        import mt5_client
        import market_regime
        from ai_v5.live.live_pattern_scanner import scan_all_patterns_live
        from ai_v5.live.feature_builder import build_feature_dict
        from ai_v5.config_ai import PROBABILITY_THRESHOLD
        from ai_v5.config_live import CANDLES_LOOKBACK
    except Exception as e:
        return f"❌ Lỗi nạp module: {e}"

    try:
        candles = mt5_client.get_candles(symbol, timeframe, CANDLES_LOOKBACK)
    except Exception as e:
        return f"❌ Lỗi lấy nến {timeframe}: {e}"

    if not candles or len(candles) < 220:
        return f"⚠️ Không đủ dữ liệu nến {timeframe} (nhận được {len(candles) if candles else 0}, cần ≥220)."

    try:
        matches = scan_all_patterns_live(candles, symbol)
    except Exception as e:
        return f"❌ Lỗi quét mẫu hình {timeframe}: {e}"

    if not matches:
        return "Không phát hiện mẫu hình nào tại nến hiện tại."

    try:
        regime_res = market_regime.get_regime(candles, symbol)
    except Exception:
        regime_res = None

    parts = []
    for source_type, match in matches:
        try:
            features = build_feature_dict(match, source_type, regime_res)
            win_prob = _predictor.predict_probability(features)
        except Exception as e:
            parts.append(f"⚠️ {match.get('pattern', '?')}: lỗi tính điểm ({e})")
            continue
        decision = "✅ SẼ DUYỆT" if win_prob >= PROBABILITY_THRESHOLD else "⛔ Dưới ngưỡng"
        parts.append(
            f"<b>{match['pattern']}</b> ({source_type})\n"
            f"Hướng: {match['direction']} | WinProb: <b>{win_prob:.1%}</b> | {decision}"
        )
    return "\n\n".join(parts)


_TF_LABELS = {
    "H1": "🕐 H1 (xu hướng lớn)",
    "M15": "🕒 M15 (khung giao dịch chính)",
    "M5": "🕔 M5 (thời điểm vào lệnh)",
}


def _run_realtime_analysis(symbol: str, timeframes: list = None) -> str:
    """
    Quet ngay lap tuc 1 symbol tren NHIEU khung thoi gian (mac dinh H1+M15+M5)
    tai nen moi dong gan nhat cua tung khung - dung DUNG cac ham detector/
    predictor giong het live_trader.py de dam bao ket qua nhat quan voi luc
    bot tu quyet dinh that.
    """
    if _mt5 is None:
        return "❌ MetaTrader5 không khả dụng trên môi trường này."
    if _predictor is None or _predictor.model is None:
        return "❌ Chưa nạp được model AI v5 (latest_model.pkl) — không thể phân tích."

    timeframes = timeframes or ["H1", "M15", "M5"]

    header = f"<b>📊 Phân tích đa khung: {symbol}</b>\n━━━━━━━━━━━━━━"
    sections = [header]
    for tf in timeframes:
        label = _TF_LABELS.get(tf, tf)
        result = _analyze_one_timeframe(symbol, tf)
        sections.append(f"{label}\n{result}")

    try:
        from ai_v5.config_ai import PROBABILITY_THRESHOLD
        sections.append(f"━━━━━━━━━━━━━━\n<i>Ngưỡng duyệt lệnh hiện tại: {PROBABILITY_THRESHOLD:.0%}</i>")
    except Exception:
        pass

    return "\n\n".join(sections)


# ─── Status builders ─────────────────────────────────────────────────────────

def _build_account_status() -> str:
    lines = ["<b>AI v5 — Trạng thái bot</b>", "━━━━━━━━━━━━━━"]
    lines.append(f"Auto Trade: <b>{'ON' if AUTO_TRADE_ENABLED else 'OFF'}</b>")
    sym_lines = []
    for s in config_live.SYMBOLS:
        sym_lines.append(f"{s} ⏸️" if s in DISABLED_SYMBOLS else s)
    lines.append(f"Symbols: {', '.join(sym_lines)}")

    if _mt5 is not None:
        try:
            acct = _mt5.account_info()
            if acct:
                lines += [
                    "━━━━━━━━━━━━━━",
                    "<b>Tài khoản (AI v5)</b>",
                    f"Login:   <code>{acct.login}</code> ({acct.server})",
                    f"Balance: <code>{acct.balance:,.0f} {acct.currency}</code>",
                    f"Equity:  <code>{acct.equity:,.0f} {acct.currency}</code>",
                    f"Free:    <code>{acct.margin_free:,.0f}</code>",
                ]

            try:
                pos = [p for p in (_mt5.positions_get() or []) if p.magic == MAGIC_NUMBER]
                if pos:
                    lines += ["━━━━━━━━━━━━━━", f"<b>{len(pos)} lệnh AI v5 đang mở</b>"]
                    for p in pos:
                        sign = "+" if p.profit >= 0 else ""
                        icon = "🟢" if p.type == 0 else "🔴"
                        lines.append(
                            f"{icon} <b>{p.symbol}</b> #{p.ticket} "
                            f"{'BUY' if p.type == 0 else 'SELL'} {p.volume}lot "
                            f"P&L:<code>{sign}{p.profit:,.0f}</code>"
                        )
                else:
                    lines += ["━━━━━━━━━━━━━━", "Không có lệnh AI v5 đang mở."]
            except Exception:
                pass
        except Exception as e:
            lines.append(f"MT5 error: {e}")
    else:
        lines.append("MT5 không khả dụng.")

    return "\n".join(lines)


def _build_params_status() -> str:
    lines = ["<b>AI v5 — Cấu hình hiện tại</b>", "━━━━━━━━━━━━━━"]
    try:
        from ai_v5.config_ai import PROBABILITY_THRESHOLD
        lines.append(f"Ngưỡng quyết định: <b>{PROBABILITY_THRESHOLD:.0%}</b>")
    except Exception:
        pass

    spread_lines = ", ".join(f"{s}:{config_live.MAX_SPREAD_POINTS.get(s, config_live.MAX_SPREAD_POINTS_DEFAULT)}pts"
                              for s in config_live.SYMBOLS)
    lot_lines = ", ".join(f"{s}:{config_live.FIXED_LOT.get(s, config_live.FIXED_LOT_DEFAULT)}lot"
                           for s in config_live.SYMBOLS)
    lines += [
        f"Khối lượng cố định: <b>{lot_lines}</b>",
        f"Tối đa lệnh/symbol: <b>{config_live.MAX_OPEN_TRADES_PER_SYMBOL}</b> "
        f"(tối đa <b>{config_live.MAX_OPEN_TRADES_PER_SYMBOL_HIGH_CONFIDENCE}</b> "
        f"nếu WinProb ≥ {config_live.HIGH_CONFIDENCE_EXTRA_SLOT_THRESHOLD:.0%})",
        f"Tối đa tổng lệnh: <b>{config_live.MAX_TOTAL_OPEN_TRADES}</b>",
        f"Spread tối đa cho phép: <b>{spread_lines}</b>",
        f"Giờ giao dịch: <b>{config_live.TRADING_HOURS_START_VN}h–{config_live.TRADING_HOURS_END_VN}h</b> "
        f"({'BẬT' if config_live.TRADING_HOURS_ENABLED else 'TẮT'})",
        f"Đảo lệnh khi lỗ: <b>{'BẬT' if config_live.ALLOW_REVERSE_ON_LOSS else 'TẮT'}</b>",
        f"Magic number: <code>{MAGIC_NUMBER}</code>",
        f"Quét mỗi: <b>{config_live.SCAN_INTERVAL_SECONDS}s</b>",
    ]

    try:
        import os
        from ai_v5.config_ai import MODELS_DIR
        model_path = os.path.join(MODELS_DIR, "latest_model.pkl")
        if os.path.exists(model_path):
            mtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(model_path)))
            lines.append(f"Model hiện tại: <i>cập nhật {mtime}</i>")
        else:
            lines.append("⚠️ Chưa có model latest_model.pkl")
    except Exception:
        pass

    return "\n".join(lines)


# ─── Command handler ─────────────────────────────────────────────────────────

def _handle(token: str, chat_id: str, text: str, allowed: str) -> None:
    global AUTO_TRADE_ENABLED

    if str(chat_id) != str(allowed):
        logger.warning("Lệnh từ chat_id lạ: %s — bỏ qua.", chat_id)
        return

    cmd = text.strip().lower().split()[0]

    if cmd in ("/start", "/start_trade"):
        AUTO_TRADE_ENABLED = True
        logger.info("AI v5 AUTO_TRADE bật qua Telegram.")
        _send(token, chat_id,
              "✅ <b>AI v5 Auto Trade BẬT</b>\n"
              "Bot sẽ tiếp tục đặt lệnh khi phát hiện tín hiệu vượt ngưỡng.\n"
              "<i>/stop để dừng lại.</i>")

    elif cmd in ("/stop", "/stop_trade"):
        AUTO_TRADE_ENABLED = False
        logger.info("AI v5 AUTO_TRADE tắt qua Telegram.")
        _send(token, chat_id,
              "🔴 <b>AI v5 Auto Trade TẮT</b>\n"
              "Bot chuyển sang chế độ chỉ quét/log, không đặt lệnh mới.\n"
              "Lệnh cũ vẫn giữ nguyên.\n"
              "<i>/start để bật lại.</i>")

    elif cmd == "/status":
        _send(token, chat_id, _build_account_status())

    elif cmd in ("/disable", "/pause"):
        parts = text.strip().split()
        if len(parts) < 2:
            _send(token, chat_id,
                  f"Cú pháp: <code>/disable SYMBOL</code>\n"
                  f"Ví dụ: <code>/disable {config_live.SYMBOLS[0]}</code>\n"
                  f"Symbol đang giao dịch: {', '.join(config_live.SYMBOLS)}")
        else:
            sym = _resolve_symbol_case(parts[1])
            if sym not in config_live.SYMBOLS:
                _send(token, chat_id, f"Không nhận diện được symbol '{parts[1]}'.")
            else:
                DISABLED_SYMBOLS.add(sym)
                logger.info("AI v5: symbol %s bị TẠM DỪNG qua Telegram.", sym)
                _send(token, chat_id,
                      f"⏸️ <b>{sym} — TẠM DỪNG (AI v5)</b>\n"
                      f"Bot sẽ bỏ qua hoàn toàn {sym} cho tới khi <code>/enable {sym}</code>.\n"
                      f"Lệnh {sym} đang mở (nếu có) vẫn giữ nguyên.")

    elif cmd in ("/enable", "/resume"):
        parts = text.strip().split()
        if len(parts) < 2:
            _send(token, chat_id,
                  f"Cú pháp: <code>/enable SYMBOL</code>\n"
                  f"Đang tạm dừng: {', '.join(sorted(DISABLED_SYMBOLS)) if DISABLED_SYMBOLS else '(không có)'}")
        else:
            sym = _resolve_symbol_case(parts[1])
            if sym in DISABLED_SYMBOLS:
                DISABLED_SYMBOLS.discard(sym)
                logger.info("AI v5: symbol %s được BẬT LẠI qua Telegram.", sym)
                _send(token, chat_id, f"▶️ <b>{sym} — Đã BẬT LẠI (AI v5).</b>")
            else:
                _send(token, chat_id, f"{sym} hiện không bị tạm dừng.")

    elif cmd in ("/analyze", "/check", "/scan"):
        parts = text.strip().split()
        if len(parts) < 2:
            _send(token, chat_id,
                  f"Cú pháp: <code>/analyze SYMBOL [KHUNG]</code>\n"
                  f"Ví dụ: <code>/analyze {config_live.SYMBOLS[0]}</code> (mặc định quét cả H1+M15+M5)\n"
                  f"Hoặc: <code>/analyze {config_live.SYMBOLS[0]} M15</code> (chỉ 1 khung)\n"
                  f"Symbol đang giao dịch: {', '.join(config_live.SYMBOLS)}")
        else:
            sym = _resolve_symbol_case(parts[1])
            tf_override = [parts[2].upper()] if len(parts) >= 3 else None
            _send(token, chat_id, f"⏳ Đang phân tích {sym}{' (' + tf_override[0] + ')' if tf_override else ' (H1+M15+M5)'}...")
            result_text = _run_realtime_analysis(sym, tf_override)
            _send(token, chat_id, result_text)

    elif cmd == "/params":
        _send(token, chat_id, _build_params_status())

    elif cmd == "/tune":
        _send(token, chat_id,
              "⚙️ AI v5 hiện chưa có auto-tuner tự động riêng cho vòng lặp live.\n"
              "Để train lại model, chạy trên VPS: <code>py -3.11 run_init_train.py</code>\n"
              "Sau đó khởi động lại <code>ai_v5.live.live_trader</code> để nạp model mới.")

    elif cmd == "/help":
        _send(token, chat_id,
              "<b>AI v5 — Danh sách lệnh</b>\n"
              "━━━━━━━━━━━━━━\n"
              "/start  — Bật auto trade\n"
              "/stop   — Tắt auto trade\n"
              "/disable SYMBOL — Tạm dừng 1 symbol (vd: XAUUSD)\n"
              "/enable SYMBOL  — Bật lại 1 symbol\n"
              "/analyze SYMBOL [KHUNG] — Phân tích real-time (mặc định H1+M15+M5)\n"
              "/status — Tài khoản &amp; lệnh đang mở\n"
              "/params — Ngưỡng quyết định &amp; cấu hình hiện tại\n"
              "/tune   — Hướng dẫn train lại model\n"
              "/help   — Danh sách lệnh này")

    else:
        _send(token, chat_id, f"Lệnh không rõ: <code>{text[:40]}</code>\n/help để xem danh sách.")


# ─── Polling loop ─────────────────────────────────────────────────────────────

def _poll(token: str, chat_id: str) -> None:
    offset = None
    logger.info("AI v5 TelegramCommander sẵn sàng.")

    while True:
        try:
            params = {"timeout": 25, "allowed_updates": ["message"]}
            if offset is not None:
                params["offset"] = offset

            resp = _get(token, "getUpdates", params, timeout=30)
            if not resp.get("ok"):
                time.sleep(5)
                continue

            for upd in resp.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or upd.get("edited_message")
                if not msg:
                    continue
                txt = msg.get("text", "")
                from_chat = str(msg["chat"]["id"])
                if txt.startswith("/"):
                    logger.info("AI v5 lệnh từ %s: %s", from_chat, txt)
                    _handle(token, from_chat, txt, chat_id)

        except URLError as e:
            logger.warning("AI v5 polling lỗi mạng: %s — thử lại sau 10s", e)
            time.sleep(10)
        except Exception as e:
            logger.exception("AI v5 polling lỗi: %s", e)
            time.sleep(10)


# ─── Public API ───────────────────────────────────────────────────────────────

def start(token: str, chat_id: str, predictor=None) -> threading.Thread:
    """Khởi động daemon thread. Gọi bởi live_trader.py.
    predictor: instance AIPredictor đã nạp sẵn model - truyền vào để lệnh
               /analyze tái sử dụng, không phải nạp lại model từ đĩa mỗi lần gọi."""
    global _predictor
    _predictor = predictor
    t = threading.Thread(target=_poll, args=(token, chat_id), name="AI_v5_TelegramCommander", daemon=True)
    t.start()
    return t


def is_symbol_enabled(symbol: str) -> bool:
    return AUTO_TRADE_ENABLED and symbol not in DISABLED_SYMBOLS
