# ai_v6/live/telegram_commander.py
"""
Telegram Commander rieng cho ai_v6 (bot Telegram RIENG, dung AI_V6_TELEGRAM_*).
Cau truc giong ai_v5/live/telegram_commander.py nhung /status va thong bao
lenh duoc thiet ke lai de hien thi thong tin NHOM DCA (so lenh trong nhom,
gia vao trung binh, SL/TP nhom) thay vi tung lenh rieng le.

Lenh:
  /start /stop  — Bat/tat auto trade
  /status       — Trang thai nhom DCA dang mo + tai khoan
  /params       — Cau hinh DCA hien tai
  /help         — Danh sach lenh
"""
import json
import logging
import ssl
import threading
import time
from urllib import request as urlreq
from urllib.error import URLError

from ai_v6 import config_live
from ai_v6.config_live import MAGIC_NUMBER

logger = logging.getLogger("ai_v6_tg_commander")

try:
    import MetaTrader5 as _mt5
except Exception:
    _mt5 = None

# Dung cho sendPhoto (gui kem chart) - can multipart/form-data, urllib thuan lam viec nay
# phuc tap hon nhieu so voi requests (da co san trong moi truong, xem bot_listener.py cua
# ai_v5 cung dung requests). Neu thieu thu vien requests, gracefully bo qua chart, chi gui text.
try:
    import requests
    _REQUESTS_OK = True
except Exception:
    _REQUESTS_OK = False
    logger.warning("Thư viện requests chưa cài — sẽ không gửi kèm ảnh chart (chỉ gửi tin nhắn text). "
                    "Chạy: pip install requests")

try:
    import certifi
    _CERT_PATH = certifi.where()
except Exception:
    _CERT_PATH = True  # fallback: dung xac thuc mac dinh cua requests

# Mo ta ngan gon TUNG NHOM pattern (dung cho phan "PHAN TICH tu dong") - giai thich BAN CHAT
# cua nhom nao dang kich hoat tin hieu, giup nguoi doc hieu NHANH ly do vao lenh la gi.
_PATTERN_GROUP_EXPLANATIONS = {
    "GEOMETRIC_PATTERN": "Cấu trúc giá hình thành mô hình hình học cổ điển (đỉnh/đáy) — phá vỡ vùng cổ (neckline) xác nhận hướng đi.",
    "CANDLESTICK_PATTERN": "Mô hình nến Nhật xác nhận tại vùng giá quan trọng — phản ánh sự thay đổi tâm lý phe mua/bán.",
    "HARMONIC_PATTERN": "Cấu trúc XABCD hoàn thành đúng tỷ lệ Fibonacci — vùng đảo chiều tiềm năng.",
    "DIVERGENCE_PATTERN": "Phân kỳ giữa giá và chỉ báo dao động (RSI/MACD) — giá và động lượng đang lệch hướng nhau.",
    "VSA_PATTERN": "Phân tích khối lượng-biên độ (VSA) phát hiện dấu hiệu Tiền Thông Minh đang hành động ngược đám đông.",
    "ICT_PATTERN": "Cấu trúc SMC/ICT (Order Block/FVG/Liquidity Sweep) xác nhận vùng giá tổ chức lớn đã/đang hoạt động.",
    "CONTINUATION_PATTERN": "Mô hình tích lũy dài hạn (Rounding/Cup&Handle) phá vỡ vùng vành — xác nhận tiếp diễn xu hướng.",
}

AUTO_TRADE_ENABLED = True
DISABLED_SYMBOLS = set()
_predictor = None


def _ssl():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception as e:
        logger.warning("certifi lỗi (%s) — dùng SSL context mặc định.", e)
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


def _confidence_label(win_prob: float) -> str:
    if win_prob >= 0.65:
        return "cao"
    if win_prob >= 0.55:
        return "khá"
    return "vừa phải"


def _send_photo(token: str, chat_id: str, photo_bytes: bytes, caption: str) -> None:
    """Gui anh chart qua Telegram sendPhoto (multipart/form-data qua requests). Neu that bai
    hoac thieu thu vien requests, tu dong fallback sang gui tin nhan text (khong lam mat thong bao)."""
    if not _REQUESTS_OK:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        files = {"photo": ("chart.png", photo_bytes, "image/png")}
        data = {"chat_id": chat_id, "caption": caption[:1024], "parse_mode": "HTML"}
        resp = requests.post(url, data=data, files=files, timeout=20, verify=_CERT_PATH)
        if not resp.ok:
            logger.warning("Gửi ảnh chart Telegram thất bại (%s): %s", resp.status_code, resp.text[:300])
    except Exception as e:
        logger.warning("Gửi ảnh chart Telegram lỗi: %s", e)


def _build_analysis_text(symbol: str, pattern: str, source_type: str, direction: str, win_prob: float,
                          match: dict, regime_res, result: dict, is_dca: bool,
                          adverse_distance: float = None) -> str:
    """Dung template GIONG PHONG CACH thong bao cua ai_v5 (Lot/R:R/Pattern/WinProb + khoi
    PHAN TICH tu dong), CO BO SUNG rieng cho v6: thong tin NHOM DCA (v5 khong co khai niem
    nay vi moi lenh v5 doc lap, khong gop nhom)."""
    sl = match.get("sl")
    tp = match.get("tp")
    entry_signal = match.get("_entry_price")
    risk = abs(entry_signal - sl) if (entry_signal is not None and sl is not None) else None
    reward = abs(tp - entry_signal) if (entry_signal is not None and tp is not None) else None
    rr = (reward / risk) if (risk and risk > 0) else None

    lines = [f"Lot: {result.get('lot')}" + (f" | R:R=1:{rr:.2f}" if rr else "")]
    lines.append("")
    lines.append(f"<i>Pattern: {pattern} ({source_type}) | WinProb: {win_prob:.1%}</i>")
    lines.append("")
    lines.append("🤖 <b>PHÂN TÍCH (tự động, dựa trên dữ liệu)</b>")

    explain = _PATTERN_GROUP_EXPLANATIONS.get(source_type)
    if explain:
        lines.append(f"• {explain}")
    lines.append(f"• Hướng <b>{direction}</b>, tỷ lệ R:R thiết kế " + (f"1:{rr:.2f}." if rr else "N/A."))

    if regime_res is not None:
        regime_label = {"trending": "TRENDING", "ranging": "RANGING"}.get(regime_res.regime, regime_res.regime.upper())
        trend_word = {"bullish": "TĂNG", "bearish": "GIẢM", "neutral": "TRUNG LẬP"}.get(regime_res.trend_dir, regime_res.trend_dir)
        lines.append(f"• Thị trường M15 hiện đang <b>{regime_label}</b>, ADX={regime_res.adx:.1f}, "
                     f"xu hướng chính <b>{trend_word}</b>.")

    lines.append(f"• Model AI v6 chấm xác suất thắng <b>{win_prob:.1%}</b> — mức tin cậy {_confidence_label(win_prob)}.")
    if sl is not None:
        lines.append(f"• Mất hiệu lực nếu giá đóng cửa vượt ngược lại qua SL tín hiệu gốc ({sl:.2f}).")

    lines.append("")
    if is_dca:
        lines.append(f"🔁 <b>Đây là lệnh DCA thứ {result.get('n_positions_in_group')}/{config_live.MAX_DCA_POSITIONS} "
                     f"trong nhóm</b>")
        if adverse_distance is not None:
            lines.append(f"Mở thêm vì giá đã đi ngược ${adverse_distance:.2f} + có tín hiệu xác nhận mới cùng chiều.")
        lines.append(f"Entry lệnh này: <code>{result.get('entry')}</code> | "
                     f"Entry TB nhóm: <code>{result.get('group_avg_entry')}</code>")
    else:
        lines.append(f"🆕 <b>Lệnh GỐC mở nhóm DCA mới (1/{config_live.MAX_DCA_POSITIONS})</b>")
        lines.append(f"Entry: <code>{result.get('entry')}</code>")
    lines.append(f"SL/TP NHÓM (áp dụng cho toàn bộ vị thế): <code>{result.get('group_sl')}</code> / "
                 f"<code>{result.get('group_tp')}</code>")

    return "\n".join(lines)


def notify_trade(symbol: str, pattern: str, source_type: str, win_prob: float, result: dict, is_dca: bool,
                  match: dict = None, regime_res=None, chart_candles: list = None,
                  adverse_distance: float = None) -> None:
    """Goi tu live_trader.py sau moi lan thu mo lenh (thanh cong hoac bi tu choi).

    match/regime_res/chart_candles/adverse_distance la THAM SO TUY CHON (giu tuong thich
    nguoc): neu khong truyen (vd goi cu chua cap nhat), van gui duoc tin nhan ngan gon nhu
    truoc. Neu co day du, gui THEM 1 tin nhan phan tich chi tiet (giong phong cach ai_v5)
    va 1 anh chart (dung lai ai_v5.live.chart_renderer, khong sua)."""
    from ai_v6.config_ai import TELEGRAM_AI_TOKEN, TELEGRAM_AI_CHAT_ID
    if not TELEGRAM_AI_TOKEN or not TELEGRAM_AI_CHAT_ID:
        return

    label = "DCA (thêm lệnh)" if is_dca else "LỆNH GỐC"

    if not result.get("success"):
        msg = (f"<b>BỎ QUA {label} (AI V6)</b>\n{result.get('error', 'Không rõ lý do')}\n"
               f"<i>{pattern} ({source_type}) | {symbol} | WinProb: {win_prob:.1%}</i>")
        _send(TELEGRAM_AI_TOKEN, TELEGRAM_AI_CHAT_ID, msg)
        return

    header = (f"<b>✅ ĐÃ MỞ {label} (AI V6)</b>\n"
              f"{result['direction']} <b>{symbol}</b> #{result['ticket']}\n\n")

    if match is not None:
        body = header + _build_analysis_text(symbol, pattern, source_type, result['direction'], win_prob,
                                              match, regime_res, result, is_dca, adverse_distance)
    else:
        body = (header + f"Entry: <code>{result.get('entry')}</code> | Lot: {result.get('lot')}\n"
                f"<i>Pattern: {pattern} ({source_type}) | WinProb: {win_prob:.1%}</i>")

    _send(TELEGRAM_AI_TOKEN, TELEGRAM_AI_CHAT_ID, body)

    # Gui kem chart neu du du lieu - DUNG LAI NGUYEN VEN ai_v5.live.chart_renderer (khong sua
    # logic ve), chi truyen vao muc SL/TP NHOM (thuc te dang bao ve vi the) thay vi SL/TP
    # cua rieng 1 tin hieu, vi day moi la muc thuc su quyet dinh khi nao nhom dong lenh.
    if match is not None and chart_candles and _REQUESTS_OK:
        try:
            from ai_v5.live.chart_renderer import render_pattern_chart
            png_bytes = render_pattern_chart(
                candles=chart_candles, symbol=symbol, pattern=pattern, direction=result['direction'],
                entry=result.get('group_avg_entry') or result.get('entry'),
                sl=result.get('group_sl'), tp=result.get('group_tp'), lookback=60,
            )
            if png_bytes:
                _send_photo(TELEGRAM_AI_TOKEN, TELEGRAM_AI_CHAT_ID, png_bytes, caption=f"{symbol} — {pattern}")
        except Exception as e:
            logger.warning(f"Không vẽ/gửi được chart cho {symbol}/{pattern}: {e}")


def _build_status() -> str:
    from ai_v6.live import position_group_manager as group_mgr
    lines = ["<b>AI v6 — Trạng thái bot (DCA XAUUSD)</b>", "━━━━━━━━━━━━━━"]
    lines.append(f"Auto Trade: <b>{'ON' if AUTO_TRADE_ENABLED else 'OFF'}</b>")

    for symbol in config_live.SYMBOLS:
        positions = group_mgr.get_group_positions(symbol) if _mt5 else []
        if not positions:
            lines.append(f"\n<b>{symbol}</b>: không có nhóm DCA nào đang mở.")
            continue
        direction = group_mgr.get_group_direction(positions)
        avg_entry = group_mgr.calc_group_average_entry(positions)
        total_vol = sum(p.volume for p in positions)
        total_pnl = sum(p.profit for p in positions)
        sl_now = positions[0].sl if positions else None
        tp_now = positions[0].tp if positions else None
        lines.append(
            f"\n<b>{symbol}</b>: {direction} | {len(positions)}/{config_live.MAX_DCA_POSITIONS} lệnh\n"
            f"Volume: {total_vol:.2f} | Entry TB: {avg_entry:.2f}\n"
            f"SL: {sl_now} | TP: {tp_now}\n"
            f"P&L hiện tại: <b>{total_pnl:+.2f}</b>"
        )

    if _mt5 is not None:
        try:
            acct = _mt5.account_info()
            if acct:
                lines += ["\n━━━━━━━━━━━━━━",
                          f"Login: <code>{acct.login}</code> ({acct.server})",
                          f"Balance: <code>{acct.balance:,.0f} {acct.currency}</code>"]
        except Exception:
            pass

    return "\n".join(lines)


def _build_params() -> str:
    lines = ["<b>AI v6 — Cấu hình SCALPING</b>", "━━━━━━━━━━━━━━"]
    lines += [
        f"Symbol: <b>{', '.join(config_live.SYMBOLS)}</b>",
        f"Khung: M15 (xu hướng) / M5 (xác nhận) / M1 (entry + SL/TP theo ATR M1)",
        f"Lot cố định: <b>{config_live.FIXED_LOT_DEFAULT}</b>/lệnh",
        f"Tối đa DCA: <b>{config_live.MAX_DCA_POSITIONS}</b> lệnh cùng chiều/nhóm",
        f"Kích hoạt DCA: giá ngược ≥ <b>{config_live.DCA_TRIGGER_ATR_MULTIPLE}×ATR(M1)</b> hiện tại "
        f"+ có tín hiệu xác nhận mới cùng chiều",
        f"Cách nhau tối thiểu giữa 2 lần DCA: <b>{config_live.DCA_MIN_INTERVAL_MINUTES} phút</b>",
        f"SL/TP nhóm: SL={config_live.SCALP_SL_ATR_MULTIPLE}×ATR(M1), R:R={config_live.SCALP_REWARD_RISK_RATIO}",
        f"Chốt lệnh theo thời gian: <b>{config_live.MAX_HOLD_MINUTES} phút</b> nếu chưa chạm TP/SL",
        f"Giờ giao dịch: <b>{config_live.TRADING_HOURS_START_VN}h–{config_live.TRADING_HOURS_END_VN}h</b> VN",
        f"Magic number: <code>{MAGIC_NUMBER}</code>",
    ]
    try:
        from ai_v6.config_ai import PROBABILITY_THRESHOLD
        lines.append(f"Ngưỡng ML duyệt lệnh: <b>{PROBABILITY_THRESHOLD:.0%}</b>")
    except Exception:
        pass
    return "\n".join(lines)


def _handle(token: str, chat_id: str, text: str, allowed: str) -> None:
    global AUTO_TRADE_ENABLED
    if str(chat_id) != str(allowed):
        logger.warning("Lệnh từ chat_id lạ: %s — bỏ qua.", chat_id)
        return

    cmd = text.strip().lower().split()[0]

    if cmd in ("/start", "/start_trade"):
        AUTO_TRADE_ENABLED = True
        _send(token, chat_id, "✅ <b>AI v6 Auto Trade BẬT</b>\n<i>/stop để dừng lại.</i>")
    elif cmd in ("/stop", "/stop_trade"):
        AUTO_TRADE_ENABLED = False
        _send(token, chat_id, "🔴 <b>AI v6 Auto Trade TẮT</b>\nNhóm DCA đang mở (nếu có) vẫn giữ nguyên.\n<i>/start để bật lại.</i>")
    elif cmd == "/status":
        _send(token, chat_id, _build_status())
    elif cmd == "/params":
        _send(token, chat_id, _build_params())
    elif cmd == "/help":
        _send(token, chat_id,
              "<b>AI v6 — Danh sách lệnh</b>\n━━━━━━━━━━━━━━\n"
              "/start  — Bật auto trade\n"
              "/stop   — Tắt auto trade\n"
              "/status — Trạng thái nhóm DCA hiện tại &amp; tài khoản\n"
              "/params — Cấu hình DCA hiện tại\n"
              "/help   — Danh sách lệnh này")
    else:
        _send(token, chat_id, f"Lệnh không rõ: <code>{text[:40]}</code>\n/help để xem danh sách.")


def _poll(token: str, chat_id: str) -> None:
    offset = None
    logger.info("AI v6 TelegramCommander sẵn sàng.")
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
                    logger.info("AI v6 lệnh từ %s: %s", from_chat, txt)
                    _handle(token, from_chat, txt, chat_id)
        except URLError as e:
            logger.warning("AI v6 polling lỗi mạng: %s — thử lại sau 10s", e)
            time.sleep(10)
        except Exception as e:
            logger.exception("AI v6 polling lỗi: %s", e)
            time.sleep(10)


def start(token: str, chat_id: str, predictor=None) -> threading.Thread:
    global _predictor
    _predictor = predictor
    t = threading.Thread(target=_poll, args=(token, chat_id), name="AI_v6_TelegramCommander", daemon=True)
    t.start()
    return t


def is_symbol_enabled(symbol: str) -> bool:
    return AUTO_TRADE_ENABLED and symbol not in DISABLED_SYMBOLS
