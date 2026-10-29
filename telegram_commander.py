"""
telegram_commander.py  v2
Daemon thread lang nghe lenh Telegram.

Lenh:
  /start   — Bat auto trade
  /stop    — Tat auto trade
  /status  — Tai khoan + lenh dang mo + tham so hien tai
  /params  — Xem chi tiet optimized_params.json
  /help    — Danh sach lenh
"""

import json
import logging
import ssl
import threading
import time
from urllib import request as urlreq
from urllib.error import URLError

import config

logger = logging.getLogger("tg_commander")

try:
    import MetaTrader5 as _mt5
except Exception:
    _mt5 = None


# ─── SSL ─────────────────────────────────────────────────────────────────────

def _ssl():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception as e:
        logger.warning("certifi loi (%s) — dung SSL context mac dinh he thong.", e)
        return ssl.create_default_context()


# ─── HTTP ─────────────────────────────────────────────────────────────────────

def _get(token, method, params=None, timeout=30):
    url = f"https://api.telegram.org/bot{token}/{method}"
    if params:
        from urllib.parse import urlencode
        url += "?" + urlencode(params)
    with urlreq.urlopen(urlreq.Request(url), timeout=timeout, context=_ssl()) as r:
        return json.loads(r.read())


def _send(token: str, chat_id: str, text: str) -> None:
    """Gui tin nhan HTML. Dung duoc tu module khac."""
    try:
        data = json.dumps({
            "chat_id": chat_id, "text": text, "parse_mode": "HTML",
        }).encode()
        req = urlreq.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data, headers={"Content-Type": "application/json"}, method="POST",
        )
        urlreq.urlopen(req, timeout=10, context=_ssl())
    except Exception as e:
        logger.warning("Gui Telegram that bai: %s", e)


# ─── Status builders ─────────────────────────────────────────────────────────

def _build_account_status() -> str:
    lines = ["<b>Trang thai bot</b>", "━━━━━━━━━━━━━━"]
    auto = getattr(config, "AUTO_TRADE_ENABLED", False)
    lines.append(f"Auto Trade: <b>{'ON' if auto else 'OFF'}</b>")
    disabled = getattr(config, "DISABLED_SYMBOLS", set())
    sym_lines = []
    for s in getattr(config, "SYMBOLS", []):
        sym_lines.append(f"{s} ⏸️" if s in disabled else s)
    lines.append(f"Symbols: {', '.join(sym_lines)}")

    if _mt5 is not None:
        try:
            acct = _mt5.account_info()
            if acct:
                currency = acct.currency
                lines += [
                    "━━━━━━━━━━━━━━",
                    "<b>Tai khoan</b>",
                    f"Login:   <code>{acct.login}</code> ({acct.server})",
                    f"Balance: <code>{acct.balance:,.0f} {currency}</code>",
                    f"Equity:  <code>{acct.equity:,.0f} {currency}</code>",
                    f"Free:    <code>{acct.margin_free:,.0f}</code>",
                ]

            # Lenh dang mo
            try:
                from trader import MAGIC_NUMBER
                pos = [p for p in (_mt5.positions_get() or [])
                       if p.magic == MAGIC_NUMBER]
                if pos:
                    lines += ["━━━━━━━━━━━━━━",
                              f"<b>{len(pos)} lenh dang mo</b>"]
                    for p in pos:
                        sign = "+" if p.profit >= 0 else ""
                        icon = "🟢" if p.type == 0 else "🔴"
                        lines.append(
                            f"{icon} <b>{p.symbol}</b> #{p.ticket} "
                            f"{'BUY' if p.type==0 else 'SELL'} {p.volume}lot "
                            f"P&L:<code>{sign}{p.profit:,.0f}</code>"
                        )
                else:
                    lines += ["━━━━━━━━━━━━━━", "Khong co lenh dang mo."]
            except Exception:
                pass

        except Exception as e:
            lines.append(f"MT5 error: {e}")
    else:
        lines.append("MT5 khong kha dung.")

    return "\n".join(lines)


def _build_params_status() -> str:
    """Hien thi tham so dong dang dung cho tung symbol (he SMC — v5)."""
    try:
        import param_loader
        lines = ["<b>Tham so toi uu hien tai</b>", "━━━━━━━━━━━━━━"]

        import os
        params_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "optimized_params.json"
        )
        has_file = os.path.exists(params_path)
        json_symbols = set()

        if has_file:
            import json
            with open(params_path, encoding="utf-8") as f:
                data = json.load(f)
            raw = data.get("symbols", data)
            json_symbols = {k for k, v in raw.items()
                            if isinstance(v, dict) and not k.startswith("_")}
            generated = data.get("_generated_at", "?")
            lines.append(f"<i>Cap nhat: {generated[:19]}</i>")
            lines.append("━━━━━━━━━━━━━━")

        for sym in getattr(config, "SYMBOLS", []):
            p = param_loader.get_all(sym)
            src = "JSON" if sym in json_symbols else "default"
            wr  = p.get("win_rate", 0)
            pf  = p.get("profit_factor", 0)
            lines.append(
                f"<b>{sym}</b> [{src}]\n"
                f"  ATR({p['atr_period']}) × {p['atr_multiplier']:.2f}  "
                f"TP_x{p['tp_atr_multiplier']:.2f}\n"
                f"  struct={p['internal_structure_len']}  "
                f"st_factor={p['st_factor']:.2f}  "
                f"ema_fast={p['ema_fast_len']}  pa_len={p['pa_length']}"
                + (f"\n  WR={wr:.1f}% PF={pf:.2f}" if wr > 0 else "")
            )

        if not has_file:
            lines.append("\n<i>Chua co optimized_params.json</i>")
            lines.append("<i>Chay: py -3.11 bootstrap.py de tao</i>")

        return "\n".join(lines)
    except Exception as e:
        return f"Loi doc params: {e}"


# ─── Command handler ─────────────────────────────────────────────────────────

def _handle(token: str, chat_id: str, text: str, allowed: str) -> None:
    if str(chat_id) != str(allowed):
        logger.warning("Lenh tu chat_id la: %s — bo qua.", chat_id)
        return

    cmd = text.strip().lower().split()[0]

    if cmd in ("/start", "/start_trade"):
        config.AUTO_TRADE_ENABLED = True
        logger.info("AUTO_TRADE bat qua Telegram.")
        _send(token, chat_id,
            "✅ <b>Auto Trade BAT</b>\n"
            "Bot se tu dong vao lenh khi gia PHA VO cau truc (BOS/CHoCH), "
            "duoc xac nhan boi SuperTrend + EMA cung chieu va gan vung "
            "Order Block/FVG.\n"
            "<i>/stop de dung lai.</i>"
        )

    elif cmd in ("/stop", "/stop_trade"):
        config.AUTO_TRADE_ENABLED = False
        logger.info("AUTO_TRADE tat qua Telegram.")
        _send(token, chat_id,
            "🔴 <b>Auto Trade TAT</b>\n"
            "Bot chuyen sang che do chi quan sat.\n"
            "Lenh cu van giu nguyen.\n"
            "<i>/start de bat lai.</i>"
        )

    elif cmd == "/status":
        _send(token, chat_id, _build_account_status())

    elif cmd in ("/disable", "/pause"):
        parts = text.strip().upper().split()
        if len(parts) < 2:
            _send(token, chat_id,
                f"Cu phap: <code>/disable SYMBOL</code>\n"
                f"Vi du: <code>/disable XAUUSD</code>\n"
                f"Symbol dang giao dich: {', '.join(getattr(config, 'SYMBOLS', []))}"
            )
        else:
            sym = parts[1]
            if sym not in getattr(config, "SYMBOLS", []):
                _send(token, chat_id, f"Khong nhan dien duoc symbol '{sym}'.")
            else:
                if not hasattr(config, "DISABLED_SYMBOLS"):
                    config.DISABLED_SYMBOLS = set()
                config.DISABLED_SYMBOLS.add(sym)
                logger.info("Symbol %s bi TAM DUNG giao dich qua Telegram.", sym)
                _send(token, chat_id,
                    f"⏸️ <b>{sym} — TAM DUNG giao dich</b>\n"
                    f"Bot se bo qua hoan toan {sym} (khong phan tich, khong tin hieu, "
                    f"khong vao lenh moi) cho toi khi <code>/enable {sym}</code>.\n"
                    f"Lenh {sym} dang mo (neu co) van giu nguyen, khong tu dong dong."
                )

    elif cmd in ("/enable", "/resume"):
        parts = text.strip().upper().split()
        if len(parts) < 2:
            disabled = getattr(config, "DISABLED_SYMBOLS", set())
            _send(token, chat_id,
                f"Cu phap: <code>/enable SYMBOL</code>\n"
                f"Dang tam dung: {', '.join(sorted(disabled)) if disabled else '(khong co)'}"
            )
        else:
            sym = parts[1]
            disabled = getattr(config, "DISABLED_SYMBOLS", set())
            if sym in disabled:
                disabled.discard(sym)
                logger.info("Symbol %s duoc BAT LAI giao dich qua Telegram.", sym)
                _send(token, chat_id, f"▶️ <b>{sym} — Da BAT LAI giao dich.</b>")
            else:
                _send(token, chat_id, f"{sym} hien khong bi tam dung.")

    elif cmd == "/params":
        _send(token, chat_id, _build_params_status())

    elif cmd == "/tune":
        # Kich hoat toi uu ngay lap tuc
        _send(token, chat_id, "⚙️ Dang chay grid search toi uu tham so...")
        try:
            import auto_tuner
            auto_tuner.force_run()
            _send(token, chat_id,
                "✅ Grid search da duoc kich hoat (chay trong background).\n"
                "Ket qua se duoc thong bao sau vai phut.\n"
                "<i>/params de xem tham so sau khi xong.</i>"
            )
        except Exception as e:
            _send(token, chat_id, f"Loi: {e}")

    elif cmd == "/help":
        _send(token, chat_id,
            "<b>Danh sach lenh</b>\n"
            "━━━━━━━━━━━━━━\n"
            "/start  — Bat auto trade\n"
            "/stop   — Tat auto trade\n"
            "/disable SYMBOL — Tam dung 1 symbol (vd: XAUUSD)\n"
            "/enable SYMBOL  — Bat lai 1 symbol\n"
            "/status — Tai khoan &amp; lenh dang mo\n"
            "/params — Tham so toi uu dang dung\n"
            "/tune   — Kich hoat toi uu tham so ngay\n"
            "/help   — Danh sach lenh nay"
        )

    else:
        _send(token, chat_id,
            f"Lenh khong ro: <code>{text[:40]}</code>\n/help de xem danh sach."
        )


# ─── Polling loop ─────────────────────────────────────────────────────────────

def _poll(token: str, chat_id: str) -> None:
    offset = None
    logger.info("TelegramCommander san sang.")

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
                msg    = upd.get("message") or upd.get("edited_message")
                if not msg:
                    continue
                txt  = msg.get("text", "")
                from_chat = str(msg["chat"]["id"])
                if txt.startswith("/"):
                    logger.info("Lenh tu %s: %s", from_chat, txt)
                    _handle(token, from_chat, txt, chat_id)

        except URLError as e:
            logger.warning("Polling loi mang: %s — thu lai sau 10s", e)
            time.sleep(10)
        except Exception as e:
            logger.exception("Polling loi: %s", e)
            time.sleep(10)


# ─── Public API ───────────────────────────────────────────────────────────────

def start(token: str, chat_id: str) -> threading.Thread:
    """Khoi dong daemon thread. Goi boi watcher.py."""
    t = threading.Thread(
        target=_poll, args=(token, chat_id),
        name="TelegramCommander", daemon=True,
    )
    t.start()
    return t