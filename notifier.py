"""
notifier.py  v4 — 100% OFFLINE, KHONG con goi Gemini/AI nao.

Lich su:
  v1/v2: POST payload -> Vercel /api/analyze -> Gemini + QuickChart + Telegram.
  v3:    Bo Vercel, goi thang Gemini tu Python.
  v4 (hien tai): Bo LUON Gemini — dung SO LIEU THAT tinh boi trader.py
        (cung 1 ham _calc_sl_tp/_get_direction dung khi dat lenh that, nen
        Entry/SL/TP hien trong Telegram LUON KHOP voi lenh thuc te — khong
        con truong hop AI "doan" ra so khac voi lenh that nhu truoc).
        Mo ta (bullets) dung template co san dua tren du lieu thuc (break_type,
        volume_ratio, order_block, trend filter agree count) — khong can
        goi AI nao, khong can API key nao.

Van con 1 phu thuoc mang ngoai (khong bat buoc, best-effort, khong can
API key): QuickChart.io — chi de VE ANH chart tu JSON, khong xu ly logic.
Neu muon bo luon (100% khong goi ra ngoai), xoa loi goi _build_chart_url()
trong send_signal() — tin nhan text van gui binh thuong.

Interface public GIU NGUYEN: send_signal(signal) -> bool
(watcher.py khong can sua gi ca).
"""

import json
import logging
import os
import ssl
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from urllib import request, error

import config

logger = logging.getLogger("notifier")


def _ssl_ctx() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception as e:
        # v9.5: truoc day chi bat ImportError — neu certifi CO CAI nhung
        # file cacert.pem bi thieu/hong (FileNotFoundError, thuong do
        # antivirus/moi truong VPS loi), ham se raise loi lien tuc thay vi
        # fallback, khien MOI ket noi HTTPS (Telegram, QuickChart) that bai.
        # Nay bat rong hon, luon fallback ve SSL context mac dinh he thong.
        logger.warning("certifi loi (%s) — dung SSL context mac dinh he thong.", e)
        return ssl.create_default_context()


# ─── Dedupe ──────────────────────────────────────────────────────────────────
# v9.4: DA CHUYEN dedupe len watcher.py de dung CHUNG cho ca notifier va
# trader.py (truoc day notifier tu dedupe rieng, trader khong dedupe — gay
# tinh huong trader van vao lenh binh thuong nhung notifier lai im lang bo
# qua thong bao, gay hieu lam "vao lenh ma khong thay bao"). Ham nay GIU LAI
# (luon tra ve True) chi de tuong thich nguoc phong khi co noi khac goi truc
# tiep notifier.send_signal() ngoai watcher.py (vi du chay thu/test doc lap).

def _should_send(symbol: str, pattern: str) -> bool:
    return True


# ─── Pattern labels + emoji ──────────────────────────────────────────────────

PATTERN_LABELS = {
    "smc_bullish_bos": "BOS TĂNG (phá cấu trúc)",
    "smc_bearish_bos": "BOS GIẢM (phá cấu trúc)",
    "smc_bullish_choch": "CHoCH TĂNG (đảo chiều)",
    "smc_bearish_choch": "CHoCH GIẢM (đảo chiều)",
    "st_flip_bullish": "SUPERTREND ĐỔI CHIỀU TĂNG",
    "st_flip_bearish": "SUPERTREND ĐỔI CHIỀU GIẢM",
    "ema_cross_bullish": "EMA 9/21 GIAO CẮT TĂNG",
    "ema_cross_bearish": "EMA 9/21 GIAO CẮT GIẢM",
    "price_action_bullish": "PRICE ACTION TĂNG (volume xác nhận)",
    "price_action_bearish": "PRICE ACTION GIẢM (volume xác nhận)",
    "breakout_resistance": "BREAKOUT KHÁNG CỰ", "breakout_support": "BREAKOUT HỖ TRỢ (giảm)",
    "double_top": "ĐỈNH ĐÔI", "double_bottom": "ĐÁY ĐÔI",
    "bullish_engulfing": "NHẤN CHÌM TĂNG", "bearish_engulfing": "NHẤN CHÌM GIẢM",
    "hammer": "NẾN BÚA (đảo chiều tăng)", "shooting_star": "SAO BĂNG (đảo chiều giảm)",
    "doji": "DOJI (lưỡng lự)",
    "ascending_triangle": "TAM GIÁC TĂNG", "descending_triangle": "TAM GIÁC GIẢM",
    "symmetrical_triangle": "TAM GIÁC CÂN",
    "bos_bullish": "BOS TĂNG", "bos_bearish": "BOS GIẢM",
    "choch_bullish": "CHoCH TĂNG", "choch_bearish": "CHoCH GIẢM",
}


def _pattern_label(pattern: str) -> str:
    return PATTERN_LABELS.get(pattern, pattern)


def _pattern_emoji(direction: Optional[str]) -> str:
    if direction == "BUY":
        return "🟢"
    if direction == "SELL":
        return "🔴"
    return "🟡"


# ─── Tinh Entry/SL/TP THAT — dung CHUNG ham voi trader.py ──────────────────

def _compute_trade_levels(signal) -> Optional[Dict]:
    """
    Goi THANG ham tinh toan cua trader.py (_get_direction, _calc_sl_tp) —
    CUNG 1 nguon voi luc dat lenh that — de so hien trong Telegram luon
    khop voi lenh thuc te (hoac lenh SE duoc dat neu AUTO_TRADE dang OFF).
    """
    try:
        import trader
    except ImportError:
        return None

    direction = trader._get_direction(signal.pattern)
    if direction is None:
        return None

    entry = signal.price
    try:
        sl, tp = trader._calc_sl_tp(
            direction, entry, signal.zone_price, signal.candles_context, signal.symbol
        )
    except Exception as e:
        logger.warning("Không tính được SL/TP thật: %s", e)
        return None

    digits = _price_digits(signal.symbol)
    sl = round(sl, digits)
    tp = round(tp, digits)
    entry = round(entry, digits)

    rr = round(abs(tp - entry) / abs(entry - sl), 2) if sl != entry else 0.0

    return {"direction": direction, "entry": entry, "sl": sl, "tp": tp, "rr": rr}


def _price_digits(symbol: str) -> int:
    """Uu tien lay digits that tu MT5 (bot dang chay live nen co san ket noi).
    Fallback theo heuristic ten symbol neu MT5 khong kha dung."""
    try:
        import MetaTrader5 as mt5
        info = mt5.symbol_info(symbol)
        if info:
            return info.digits
    except Exception:
        pass
    if "JPY" in symbol:
        return 3
    if symbol.startswith("XAU") or symbol.startswith("XAG"):
        return 2
    return 5


_SIGNAL_GROUP_LABELS = {
    "smc": "SMC (BOS/CHoCH)",
    "supertrend": "SuperTrend K-Means",
    "ema_cross": "EMA 9/21 Cross",
    "price_action": "Price Action / Dow Theory",
}


def _signal_group_label(signal) -> str:
    group = (signal.extra or {}).get("signal_group", "smc")
    return _SIGNAL_GROUP_LABELS.get(group, group)


# ─── Bullets template (khong AI, dua tren du lieu that) ─────────────────────

def _build_bullets(signal, direction: str, levels: Dict) -> List[str]:
    extra = signal.extra or {}
    bias_word = "TĂNG" if direction == "BUY" else "GIẢM"
    group = extra.get("signal_group", "smc")

    bullets = []
    if group == "smc":
        break_type = extra.get("break_type", "BOS")
        bullets.append(f"{break_type} xác nhận cấu trúc {bias_word} tại vùng {signal.zone_price}.")
    elif group == "supertrend":
        bullets.append(f"SuperTrend (K-Means volatility) vừa đổi chiều {bias_word}.")
    elif group == "ema_cross":
        bullets.append(f"EMA 9 vừa giao cắt EMA 21 theo chiều {bias_word}.")
    elif group == "price_action":
        bullets.append(f"Cấu trúc giá {bias_word} (Dow Theory) được xác nhận bởi volume đột biến.")
    else:
        bullets.append(f"Tín hiệu {bias_word} tại vùng {signal.zone_price}.")

    if signal.volume_ratio >= 1.3:
        bullets.append(f"Volume {signal.volume_ratio}x trung bình — xác nhận lực {bias_word.lower()} tốt.")
    elif signal.volume_ratio >= 1.0:
        bullets.append(f"Volume {signal.volume_ratio}x trung bình — xác nhận ở mức vừa phải.")
    else:
        bullets.append(f"Volume {signal.volume_ratio}x trung bình — thấp, thận trọng lực đẩy yếu.")

    ob = extra.get("order_block")
    bars_ago = extra.get("bars_since_break")
    active_zones = extra.get("active_zones")
    if ob and bars_ago is not None:
        bullets.append(f"Giá đã hồi về vùng Order Block sau {bars_ago} nến — entry tại điểm retest.")
    elif active_zones:
        bullets.append(f"Entry tại điểm giá chạm vùng Fair Value Gap (còn {active_zones} vùng đang theo dõi).")

    bullets.append(f"Mất hiệu lực nếu giá đóng cửa vượt ngược lại qua SL ({levels['sl']}).")
    return bullets


# ─── Format tin nhắn Telegram ────────────────────────────────────────────────

def _format_telegram_message(signal, direction: str, levels: Dict) -> str:
    pattern_label = _pattern_label(signal.pattern)
    p_emoji = _pattern_emoji(direction)
    trend_word = "TĂNG" if direction == "BUY" else "GIẢM"
    trend_emoji = "📈" if direction == "BUY" else "📉"

    ts = datetime.fromtimestamp(signal.time, tz=timezone.utc) + timedelta(hours=7)
    time_str = ts.strftime("%Y/%m/%d %H:%M")

    group_label = _signal_group_label(signal)
    bullets = _build_bullets(signal, direction, levels)
    bullets_str = "\n".join(f"• {b}" for b in bullets)
    div = "━━━━━━━━━━━━━━"

    return (
        f"🚨 <b>{signal.symbol}</b> | {signal.timeframe}\n"
        f"{p_emoji} <b>{pattern_label}</b>\n\n"
        f"💰 Giá hiện tại: <code>{signal.price}</code>\n"
        f"📍 Vùng S/R: <code>{signal.zone_price}</code>\n"
        f"{trend_emoji} Hướng lệnh: <b>{direction} ({trend_word})</b>\n"
        f"🔎 Nhóm tín hiệu: <b>{group_label}</b>\n\n"
        f"📌 Entry: <code>{levels['entry']}</code>\n"
        f"🛑 Stop Loss: <code>{levels['sl']}</code>\n"
        f"💵 Take Profit: <code>{levels['tp']}</code>\n"
        f"⚖️ R:R = 1:{levels['rr']}\n\n"
        f"📊 Volume: {signal.volume_ratio}x trung bình\n"
        f"{div}\n"
        f"🤖 <b>PHÂN TÍCH (tự động, dựa trên dữ liệu)</b>\n"
        f"{bullets_str}\n"
        f"{div}\n"
        f"🕐 {time_str} (GMT+7)\n"
        f"<i>⚠️ Tự động sinh từ dữ liệu, không phải lời khuyên đầu tư.</i>"
    )


def _format_photo_caption(signal, direction: str, levels: Dict) -> str:
    pattern_label = _pattern_label(signal.pattern)
    p_emoji = _pattern_emoji(direction)
    trend_word = "TĂNG" if direction == "BUY" else "GIẢM"

    caption = (
        f"🚨 <b>{signal.symbol}</b> | {signal.timeframe}\n"
        f"{p_emoji} <b>{pattern_label}</b>\n\n"
        f"💰 Giá: <code>{signal.price}</code>  📍 Zone: <code>{signal.zone_price}</code>\n"
        f"Hướng: <b>{direction} ({trend_word})</b>\n\n"
        f"📌 Entry: <code>{levels['entry']}</code>\n"
        f"🛑 SL: <code>{levels['sl']}</code>  💵 TP: <code>{levels['tp']}</code>  "
        f"⚖️ 1:{levels['rr']}\n\n"
        f"📊 Volume: {signal.volume_ratio}x"
    )
    return caption[:1024]


# ─── Chart (QuickChart.io — best-effort, khong can API key, co the bo) ─────

def _build_chart_config(signal, levels: Dict) -> dict:
    chart_candles = signal.candles_context[-60:]
    data = [
        {"x": c["time"] * 1000, "o": c["open"], "h": c["high"], "l": c["low"], "c": c["close"]}
        for c in chart_candles
    ]

    annotations = {
        "zoneLine": {
            "type": "line", "yMin": signal.zone_price, "yMax": signal.zone_price,
            "borderColor": "rgba(255, 99, 132, 0.9)", "borderWidth": 2, "borderDash": [6, 4],
            "label": {"display": True, "content": f"Zone {signal.zone_price}",
                      "position": "end", "backgroundColor": "rgba(255, 99, 132, 0.85)"},
        },
        "slLine": {
            "type": "line", "yMin": levels["sl"], "yMax": levels["sl"],
            "borderColor": "rgba(220, 38, 38, 0.9)", "borderWidth": 1.5, "borderDash": [3, 3],
            "label": {"display": True, "content": f"SL {levels['sl']}", "position": "start",
                      "backgroundColor": "rgba(220, 38, 38, 0.85)", "font": {"size": 10}},
        },
        "tpLine": {
            "type": "line", "yMin": levels["tp"], "yMax": levels["tp"],
            "borderColor": "rgba(22, 163, 74, 0.9)", "borderWidth": 1.5, "borderDash": [3, 3],
            "label": {"display": True, "content": f"TP {levels['tp']}", "position": "start",
                      "backgroundColor": "rgba(22, 163, 74, 0.85)", "font": {"size": 10}},
        },
    }

    ob = (signal.extra or {}).get("order_block")
    if ob and ob.get("top") is not None and ob.get("bottom") is not None:
        is_bull = ob.get("bias") == "bullish"
        annotations["orderBlockBox"] = {
            "type": "box", "yMin": ob["bottom"], "yMax": ob["top"],
            "backgroundColor": "rgba(34, 197, 94, 0.18)" if is_bull else "rgba(239, 68, 68, 0.18)",
            "borderColor": "rgba(34, 197, 94, 0.6)" if is_bull else "rgba(239, 68, 68, 0.6)",
            "borderWidth": 1,
            "label": {"display": True, "content": "OB (mua)" if is_bull else "OB (bán)",
                      "position": "start", "font": {"size": 10}},
        }

    pattern_label = _pattern_label(signal.pattern)
    return {
        "type": "candlestick",
        "data": {"datasets": [{"label": f"{signal.symbol} {signal.timeframe}", "data": data}]},
        "options": {
            "plugins": {
                "title": {"display": True, "text": f"{signal.symbol} {signal.timeframe} — {pattern_label}"},
                "legend": {"display": False},
                "annotation": {"annotations": annotations},
            },
            "scales": {"x": {"type": "timeseries"}},
        },
    }


def _build_chart_url(signal, levels: Dict) -> Optional[str]:
    try:
        body = json.dumps({
            "chart": _build_chart_config(signal, levels),
            "width": 800, "height": 450,
            "backgroundColor": "white", "version": "3",
        }).encode()
        req = request.Request(
            "https://quickchart.io/chart/create",
            data=body, headers={"Content-Type": "application/json"}, method="POST",
        )
        with request.urlopen(req, timeout=10, context=_ssl_ctx()) as resp:
            data = json.loads(resp.read())
        return data.get("url")
    except Exception as e:
        logger.warning("Lỗi tạo chart (bỏ qua, vẫn gửi tin nhắn text): %s", e)
        return None


# ─── Telegram senders ────────────────────────────────────────────────────────

def _get_tg_creds():
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or getattr(config, "TELEGRAM_BOT_TOKEN", None)
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or getattr(config, "TELEGRAM_CHAT_ID", None)
    return token, chat_id


def _send_telegram_message(token: str, chat_id: str, text: str) -> None:
    data = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
    req = request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data, headers={"Content-Type": "application/json"}, method="POST",
    )
    with request.urlopen(req, timeout=15, context=_ssl_ctx()):
        pass


def _send_telegram_photo(token: str, chat_id: str, photo_url: str, caption: str) -> None:
    data = json.dumps({
        "chat_id": chat_id, "photo": photo_url,
        "caption": caption[:1024], "parse_mode": "HTML",
    }).encode()
    req = request.Request(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        data=data, headers={"Content-Type": "application/json"}, method="POST",
    )
    with request.urlopen(req, timeout=15, context=_ssl_ctx()):
        pass


# ─── Entry point (interface GIU NGUYEN cho watcher.py) ──────────────────────

def send_signal(signal) -> bool:
    """Xu ly va gui tin hieu qua Telegram — 100% offline, khong AI, khong API key."""
    if not _should_send(signal.symbol, signal.pattern):
        return False

    token, chat_id = _get_tg_creds()
    if not token or not chat_id:
        logger.warning("Thiếu TELEGRAM_BOT_TOKEN/CHAT_ID — không gửi được tín hiệu.")
        return False

    levels = _compute_trade_levels(signal)
    if levels is None:
        logger.warning("Không tính được Entry/SL/TP cho pattern '%s' — bỏ qua thông báo.",
                        signal.pattern)
        return False
    direction = levels["direction"]

    message = _format_telegram_message(signal, direction, levels)
    try:
        _send_telegram_message(token, chat_id, message)
        logger.info("Đã gửi tín hiệu %s %s qua Telegram.", signal.symbol, signal.pattern)
    except Exception as e:
        logger.error("Lỗi gửi Telegram (text): %s", e)
        return False

    chart_url = _build_chart_url(signal, levels)
    if chart_url:
        try:
            caption = _format_photo_caption(signal, direction, levels)
            _send_telegram_photo(token, chat_id, chart_url, caption)
        except Exception as e:
            logger.warning("Lỗi gửi Telegram (photo): %s", e)

    return True