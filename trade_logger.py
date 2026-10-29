"""
trade_logger.py
Ghi kết quả từng lệnh bot vào SQLite để làm dữ liệu học.

Luồng:
  1. place_trade() thành công → log_open_trade()  (ghi lệnh vừa mở)
  2. Watcher poll mỗi vòng → check_closed_trades() (phát hiện lệnh đã đóng, cập nhật kết quả)

Schema bảng trades:
  ticket        INT  PRIMARY KEY   — ticket MT5
  symbol        TEXT
  pattern       TEXT               — tên pattern phát hiện
  direction     TEXT               — BUY / SELL
  timeframe     TEXT               — M15 / H1 ...
  htf_trend     TEXT               — xu hướng H1 lúc vào lệnh
  volume_ratio  REAL               — volume_ratio lúc phát tín hiệu
  entry_price   REAL
  sl            REAL
  tp            REAL
  lot           REAL
  open_time     TEXT               — ISO datetime UTC
  open_hour_vn  INT                — giờ Việt Nam (UTC+7) lúc vào lệnh (0-23)
  close_time    TEXT               — NULL khi chưa đóng
  close_price   REAL               — NULL khi chưa đóng
  profit        REAL               — NULL khi chưa đóng (USD)
  result        TEXT               — WIN / LOSS / BREAKEVEN / NULL
  close_reason  TEXT               — SL / TP / MANUAL / NULL
"""

import logging
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

import config

logger = logging.getLogger("trade_logger")

# File DB cùng thư mục với script
DB_PATH = os.path.join(os.path.dirname(__file__), "trades.db")

VN_TZ = timezone(timedelta(hours=7))


# ─── DB setup ─────────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Tạo bảng nếu chưa có. Gọi 1 lần khi khởi động watcher."""
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                ticket       INTEGER PRIMARY KEY,
                symbol       TEXT NOT NULL,
                pattern      TEXT NOT NULL,
                direction    TEXT NOT NULL,
                timeframe    TEXT NOT NULL,
                htf_trend    TEXT,
                volume_ratio REAL,
                entry_price  REAL,
                sl           REAL,
                tp           REAL,
                lot          REAL,
                open_time    TEXT,
                open_hour_vn INTEGER,
                close_time   TEXT,
                close_price  REAL,
                profit       REAL,
                result       TEXT,
                close_reason TEXT
            )
        """)
        # Index để query theo pattern / symbol nhanh
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pattern ON trades(pattern)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_symbol  ON trades(symbol)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_result  ON trades(result)")
        conn.commit()
    logger.info("SQLite DB sẵn sàng: %s", DB_PATH)


# ─── Ghi lệnh mới mở ─────────────────────────────────────────────────────────

def log_open_trade(ticket: int, signal, direction: str,
                   lot: float, entry: float, sl: float, tp: float):
    """
    Gọi ngay sau khi order_send thành công.
    signal    : object Signal từ analysis.py
    direction : "BUY" hoặc "SELL" từ TradeResult
    """
    now_utc = datetime.now(timezone.utc)
    now_vn  = now_utc.astimezone(VN_TZ)

    row = {
        "ticket":       ticket,
        "symbol":       signal.symbol,
        "pattern":      signal.pattern,
        "direction":    direction,
        "timeframe":    signal.timeframe,
        "htf_trend":    signal.extra.get("htf_trend", ""),
        "volume_ratio": round(signal.volume_ratio, 3),
        "entry_price":  entry,
        "sl":           sl,
        "tp":           tp,
        "lot":          lot,
        "open_time":    now_utc.isoformat(),
        "open_hour_vn": now_vn.hour,
        "close_time":   None,
        "close_price":  None,
        "profit":       None,
        "result":       None,
        "close_reason": None,
    }

    try:
        with _get_conn() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO trades
                (ticket,symbol,pattern,direction,timeframe,htf_trend,volume_ratio,
                 entry_price,sl,tp,lot,open_time,open_hour_vn,
                 close_time,close_price,profit,result,close_reason)
                VALUES
                (:ticket,:symbol,:pattern,:direction,:timeframe,:htf_trend,:volume_ratio,
                 :entry_price,:sl,:tp,:lot,:open_time,:open_hour_vn,
                 :close_time,:close_price,:profit,:result,:close_reason)
            """, row)
            conn.commit()
        logger.info("📝 Đã ghi lệnh #%d %s %s vào DB", ticket, signal.symbol, signal.pattern)
    except Exception as e:
        logger.error("Lỗi ghi trade_logger: %s", e)


# ─── Theo dõi và cập nhật lệnh đã đóng ───────────────────────────────────────

def _classify_result(profit: float, sl: float, tp: float,
                     close_price: float, direction: str) -> tuple[str, str]:
    """
    Phân loại WIN / LOSS / BREAKEVEN và lý do đóng SL/TP/MANUAL.
    Dùng khoảng cách close_price đến SL/TP để đoán lý do.
    """
    if profit > 0:
        result = "WIN"
    elif profit < 0:
        result = "LOSS"
    else:
        result = "BREAKEVEN"

    # Đoán lý do đóng: nếu close_price gần TP/SL trong ngưỡng 5 pips
    tol = abs(tp - sl) * 0.05   # 5% khoảng SL-TP làm tolerance
    if direction == "BUY":
        if abs(close_price - tp) <= tol:
            reason = "TP"
        elif abs(close_price - sl) <= tol:
            reason = "SL"
        else:
            reason = "MANUAL"
    else:
        if abs(close_price - tp) <= tol:
            reason = "TP"
        elif abs(close_price - sl) <= tol:
            reason = "SL"
        else:
            reason = "MANUAL"

    return result, reason


def check_closed_trades():
    """
    Gọi mỗi vòng poll trong watcher.
    Lấy danh sách ticket chưa đóng trong DB, so với positions đang mở trên MT5.
    Nếu ticket không còn trong positions → đã đóng → lấy deal history cập nhật DB.
    """
    if mt5 is None:
        return

    try:
        with _get_conn() as conn:
            open_rows = conn.execute(
                "SELECT ticket, symbol, direction, sl, tp FROM trades WHERE close_time IS NULL"
            ).fetchall()
    except Exception as e:
        logger.error("Lỗi đọc DB: %s", e)
        return

    if not open_rows:
        return

    # Ticket đang còn mở trên MT5
    positions = mt5.positions_get() or []
    open_tickets = {p.ticket for p in positions}

    for row in open_rows:
        ticket = row["ticket"]
        if ticket in open_tickets:
            continue  # Lệnh vẫn đang mở, bỏ qua

        # Lệnh đã đóng — tìm deal trong history (30 ngày trở về)
        from datetime import date
        date_from = datetime(2020, 1, 1, tzinfo=timezone.utc)
        date_to   = datetime.now(timezone.utc) + timedelta(days=1)

        deals = mt5.history_deals_get(date_from, date_to) or []
        # Lọc deal thuộc order này (DEAL_ENTRY_OUT = đóng lệnh)
        close_deals = [
            d for d in deals
            if d.order == ticket and d.entry == mt5.DEAL_ENTRY_OUT
        ]

        if not close_deals:
            # Thử tìm qua position_id
            close_deals = [
                d for d in deals
                if d.position_id == ticket and d.entry == mt5.DEAL_ENTRY_OUT
            ]

        if not close_deals:
            logger.debug("Chưa tìm được deal đóng cho ticket #%d", ticket)
            continue

        deal = close_deals[-1]  # Lấy deal đóng cuối cùng
        close_price  = deal.price
        profit       = deal.profit + deal.swap + deal.commission
        close_dt_utc = datetime.fromtimestamp(deal.time, tz=timezone.utc)

        result, reason = _classify_result(
            profit, row["sl"], row["tp"], close_price, row["direction"]
        )

        try:
            with _get_conn() as conn:
                conn.execute("""
                    UPDATE trades SET
                        close_time  = ?,
                        close_price = ?,
                        profit      = ?,
                        result      = ?,
                        close_reason = ?
                    WHERE ticket = ?
                """, (close_dt_utc.isoformat(), close_price, round(profit, 4),
                      result, reason, ticket))
                conn.commit()

            icon = "✅" if result == "WIN" else "❌" if result == "LOSS" else "➡️"
            logger.info(
                "%s Lệnh #%d %s %s đóng: %s | profit=%.2f | lý do=%s",
                icon, ticket, row["symbol"], row["direction"],
                result, profit, reason
            )
        except Exception as e:
            logger.error("Lỗi cập nhật kết quả ticket #%d: %s", ticket, e)