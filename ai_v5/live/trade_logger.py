# ai_v5/live/trade_logger.py
"""
Ghi log lenh THAT cua ai_v5 vao SQLite RIENG (ai_v5_trades.db, thu muc goc
bot_xutho4) - hoan toan tach biet voi trades.db cua bot v4, de danh gia
hieu suat 2 bot doc lap, khong lam nhieu du lieu cua nhau.

[Mo rong cho VONG PHAN HOI TU HOC] Luu THEM toan bo vector dac trung
(features_json) dung tai thoi diem quyet dinh - can thiet de sau khi lenh
dong, tai tao dung mau du lieu training (dac trung + nhan Thang/Thua THAT)
ma khong phai tinh lai tu boi canh gan dung (co the sai lech thoi diem).
Them cot used_for_training de danh dau lenh nao da duoc dua vao dataset,
tranh dua trung lap khi live_feedback.py chay dinh ky.
"""
import os
import json
import sqlite3
import logging
from datetime import datetime, timedelta

from ai_v5.config_ai import AI_BASE_DIR
from ai_v5.config_live import MAGIC_NUMBER

logger = logging.getLogger("ai_v5_trade_logger")

DB_PATH = os.path.abspath(os.path.join(AI_BASE_DIR, "..", "ai_v5_trades.db"))


def _ensure_table():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_v5_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket INTEGER,
            symbol TEXT,
            pattern TEXT,
            source_type TEXT,
            direction TEXT,
            entry REAL,
            sl REAL,
            tp REAL,
            lot REAL,
            win_probability REAL,
            features_json TEXT,
            open_time TEXT,
            close_time TEXT,
            close_price REAL,
            profit REAL,
            result TEXT,
            used_for_training INTEGER DEFAULT 0
        )
    """)
    conn.commit()

    # Nang cap nhe nhang cho DB cu (truoc khi co features_json/used_for_training)
    # neu bang da ton tai tu ban truoc, tranh loi "no such column" khi chay tren
    # DB cu da co san du lieu.
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(ai_v5_trades)")}
    if "features_json" not in existing_cols:
        conn.execute("ALTER TABLE ai_v5_trades ADD COLUMN features_json TEXT")
    if "used_for_training" not in existing_cols:
        conn.execute("ALTER TABLE ai_v5_trades ADD COLUMN used_for_training INTEGER DEFAULT 0")
    conn.commit()
    conn.close()


def log_open_trade(ticket: int, symbol: str, pattern: str, source_type: str, direction: str,
                    entry: float, sl: float, tp: float, lot: float, win_probability: float,
                    features: dict = None) -> None:
    """
    features: dict dung SCHEMA HOP NHAT (dung nhu ket qua cua
    feature_builder.build_feature_dict()) - luu lai NGUYEN VEN de sau nay
    live_feedback.py tai tao dung mau training tu ket qua that cua lenh nay.
    """
    _ensure_table()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO ai_v5_trades (ticket, symbol, pattern, source_type, direction, entry, sl, tp, lot, "
        "win_probability, features_json, open_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ticket, symbol, pattern, source_type, direction, entry, sl, tp, lot,
         win_probability, json.dumps(features) if features else None, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()
    logger.info(f"📝 Đã ghi lệnh AI v5 #{ticket} {symbol} {pattern} vào {DB_PATH}")


def sync_closed_trades(lookback_days: int = 7) -> int:
    """
    Doi chieu voi MT5 history_deals_get() de cap nhat ket qua cac lenh da dong.
    Goi dinh ky (khong can moi vong quet, ton chi phi goi MT5 API).
    Tra ve so luong lenh vua duoc cap nhat.
    """
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return 0

    _ensure_table()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT ticket FROM ai_v5_trades WHERE close_time IS NULL")
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
            "UPDATE ai_v5_trades SET close_time=?, close_price=?, profit=?, result=? WHERE ticket=?",
            (datetime.fromtimestamp(deal.time).isoformat(), deal.price, deal.profit, result, ticket),
        )
        updated += 1

    conn.commit()
    conn.close()
    if updated:
        logger.info(f"🔄 Đã đồng bộ {updated} lệnh AI v5 vừa đóng từ MT5.")
    return updated


def get_closed_trades_summary(days: int = 30) -> dict:
    """Thong ke nhanh hieu suat that cua ai_v5 trong N ngay gan nhat - dung cho /status hoac bao cao."""
    _ensure_table()
    conn = sqlite3.connect(DB_PATH)
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    cur = conn.execute(
        "SELECT result, COUNT(*), SUM(profit) FROM ai_v5_trades "
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
