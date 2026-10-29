# ai_v6/live/trade_logger.py
"""
Ghi log lenh THAT cua ai_v6 vao SQLite RIENG (ai_v6_trades.db, thu muc goc
bot_xutho4) - tach biet hoan toan voi trades.db (v4) va ai_v5_trades.db.

Them cot dac thu cho chien luoc DCA:
  is_dca         - 0: lenh GOC, 1: lenh DCA (thu 2/3)
  dca_sequence   - vi tri lenh nay trong nhom TAI THOI DIEM mo (1, 2, hoac 3)
  group_avg_entry/group_sl/group_tp - snapshot gia tri NHOM (breakeven + SL/TP)
                   NGAY SAU KHI lenh nay duoc mo (co the thay doi sau do neu
                   co them lenh DCA tiep theo - day chi la snapshot lich su).
"""
import json
import os
import sqlite3
import logging
from datetime import datetime, timedelta

from ai_v6.config_ai import AI_BASE_DIR
from ai_v6.config_live import MAGIC_NUMBER

logger = logging.getLogger("ai_v6_trade_logger")

DB_PATH = os.path.abspath(os.path.join(AI_BASE_DIR, "..", "ai_v6_trades.db"))


def _ensure_table():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_v6_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket INTEGER,
            symbol TEXT,
            pattern TEXT,
            source_type TEXT,
            direction TEXT,
            entry REAL,
            lot REAL,
            win_probability REAL,
            is_dca INTEGER,
            dca_sequence INTEGER,
            group_avg_entry REAL,
            group_sl REAL,
            group_tp REAL,
            open_time TEXT,
            close_time TEXT,
            close_price REAL,
            profit REAL,
            result TEXT,
            features_json TEXT,
            used_for_training INTEGER DEFAULT 0
        )
    """)
    # Migration an toan cho DB CU (khong mat du lieu): them 2 cot neu chua co
    existing = {row[1] for row in conn.execute("PRAGMA table_info(ai_v6_trades)").fetchall()}
    if "features_json" not in existing:
        conn.execute("ALTER TABLE ai_v6_trades ADD COLUMN features_json TEXT")
    if "used_for_training" not in existing:
        conn.execute("ALTER TABLE ai_v6_trades ADD COLUMN used_for_training INTEGER DEFAULT 0")
    conn.commit()
    conn.close()


def log_open_trade(ticket: int, symbol: str, pattern: str, source_type: str, direction: str,
                    entry: float, lot: float, win_probability: float, is_dca: bool, dca_sequence: int,
                    group_avg_entry: float = None, group_sl: float = None, group_tp: float = None,
                    features: dict = None) -> None:
    _ensure_table()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO ai_v6_trades (ticket, symbol, pattern, source_type, direction, entry, lot, "
        "win_probability, is_dca, dca_sequence, group_avg_entry, group_sl, group_tp, open_time, features_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ticket, symbol, pattern, source_type, direction, entry, lot, win_probability,
         int(is_dca), dca_sequence, group_avg_entry, group_sl, group_tp, datetime.now().isoformat(),
         json.dumps(features, ensure_ascii=False, default=float) if features else None),
    )
    conn.commit()
    conn.close()
    logger.info(f"📝 Đã ghi lệnh AI v6 #{ticket} {symbol} {pattern} "
                f"({'DCA #' + str(dca_sequence) if is_dca else 'GỐC'}) vào {DB_PATH}")


def sync_closed_trades(lookback_days: int = 7) -> int:
    """Doi chieu voi MT5 history_deals_get() de cap nhat ket qua lenh da dong. Goi dinh ky."""
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return 0

    _ensure_table()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT ticket FROM ai_v6_trades WHERE close_time IS NULL")
    open_tickets = {row[0] for row in cur.fetchall()}
    if not open_tickets:
        conn.close()
        return 0

    date_from = datetime.now() - timedelta(days=lookback_days)
    date_to = datetime.now() + timedelta(minutes=5)
    deals = mt5.history_deals_get(date_from, date_to) or []
    closing_deals = {d.position_id: d for d in deals if d.magic == MAGIC_NUMBER and d.entry == mt5.DEAL_ENTRY_OUT}

    updated = 0
    for ticket in open_tickets:
        deal = closing_deals.get(ticket)
        if deal is None:
            continue
        result = "WIN" if deal.profit > 0 else ("LOSS" if deal.profit < 0 else "BREAKEVEN")
        cur.execute(
            "UPDATE ai_v6_trades SET close_time=?, close_price=?, profit=?, result=? WHERE ticket=?",
            (datetime.fromtimestamp(deal.time).isoformat(), deal.price, deal.profit, result, ticket),
        )
        updated += 1

    conn.commit()
    conn.close()
    if updated:
        logger.info(f"🔄 Đã đồng bộ {updated} lệnh AI v6 vừa đóng từ MT5.")
    return updated


def get_closed_trades_summary(days: int = 30) -> dict:
    _ensure_table()
    conn = sqlite3.connect(DB_PATH)
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    cur = conn.execute(
        "SELECT result, COUNT(*), SUM(profit) FROM ai_v6_trades "
        "WHERE close_time IS NOT NULL AND close_time >= ? GROUP BY result", (cutoff,)
    )
    rows = cur.fetchall()
    conn.close()

    summary = {"WIN": 0, "LOSS": 0, "BREAKEVEN": 0, "total_profit": 0.0}
    for result, count, profit_sum in rows:
        if result in summary:
            summary[result] = count
        summary["total_profit"] += profit_sum or 0.0
    summary["total_trades"] = summary["WIN"] + summary["LOSS"] + summary["BREAKEVEN"]
    summary["win_rate"] = (summary["WIN"] / summary["total_trades"]) if summary["total_trades"] else None
    return summary
