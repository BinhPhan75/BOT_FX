"""
history_importer.py
Import lịch sử giao dịch từ MT5 vào trades.db.

Chạy 1 lần để nạp dữ liệu quá khứ:
    py -3.11 history_importer.py

Có 2 chế độ:
  --all-history   : Import toàn bộ lịch sử tài khoản (kể cả lệnh tay)
  --bot-only      : Chỉ import lệnh của bot (magic = 20260622)

Lệnh tay không có pattern/signal_data → được ghi với pattern="manual"
để sau này learner.py có thể tách riêng hoặc gộp phân tích.
"""

import argparse
import logging
import sys
from datetime import datetime, timezone, timedelta

try:
    import MetaTrader5 as mt5
except ImportError:
    print("Cần cài MetaTrader5: pip install MetaTrader5")
    sys.exit(1)

import trade_logger
from trade_logger import _get_conn, _classify_result, VN_TZ

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("history_importer")

BOT_MAGIC = 20260622   # Magic number của bot (trong trader.py)


# ─── Lấy deals từ MT5 ─────────────────────────────────────────────────────────

def fetch_all_deals(days_back: int = 365 * 3) -> list:
    """Lấy tất cả deals trong N ngày gần nhất."""
    date_from = datetime.now(timezone.utc) - timedelta(days=days_back)
    date_to   = datetime.now(timezone.utc) + timedelta(days=1)
    deals = mt5.history_deals_get(date_from, date_to)
    if deals is None:
        logger.error("Không lấy được history deals: %s", mt5.last_error())
        return []
    logger.info("Tổng số deals trong %d ngày: %d", days_back, len(deals))
    return list(deals)


def fetch_all_orders(days_back: int = 365 * 3) -> dict:
    """Lấy orders history, trả về dict {order_ticket: order}."""
    date_from = datetime.now(timezone.utc) - timedelta(days=days_back)
    date_to   = datetime.now(timezone.utc) + timedelta(days=1)
    orders = mt5.history_orders_get(date_from, date_to)
    if orders is None:
        return {}
    return {o.ticket: o for o in orders}


# ─── Build trade record từ deals ─────────────────────────────────────────────

def build_trade_records(deals: list, orders: dict, bot_only: bool) -> list:
    """
    Ghép các deals IN/OUT thành 1 record trade đầy đủ.
    Mỗi position gồm ít nhất 1 deal IN (mở) và 1 deal OUT (đóng).
    """
    # Group deals theo position_id
    from collections import defaultdict
    by_position = defaultdict(list)
    for d in deals:
        by_position[d.position_id].append(d)

    records = []
    for pos_id, pos_deals in by_position.items():
        in_deals  = [d for d in pos_deals if d.entry == mt5.DEAL_ENTRY_IN]
        out_deals = [d for d in pos_deals if d.entry == mt5.DEAL_ENTRY_OUT]

        if not in_deals or not out_deals:
            continue  # Lệnh chưa đóng hoặc dữ liệu thiếu

        in_deal  = in_deals[0]
        out_deal = out_deals[-1]

        # Filter bot_only
        if bot_only and in_deal.magic != BOT_MAGIC:
            continue

        # Lấy thêm SL/TP từ order gốc
        order = orders.get(in_deal.order, None)
        sl = order.sl if order else 0.0
        tp = order.tp if order else 0.0

        # Tổng profit (bao gồm swap + commission)
        total_profit = sum(d.profit + d.swap + d.commission for d in pos_deals)

        direction = "BUY" if in_deal.type == mt5.ORDER_TYPE_BUY else "SELL"
        open_dt   = datetime.fromtimestamp(in_deal.time, tz=timezone.utc)
        close_dt  = datetime.fromtimestamp(out_deal.time, tz=timezone.utc)
        open_vn   = open_dt.astimezone(VN_TZ)

        result, reason = _classify_result(
            total_profit, sl, tp, out_deal.price, direction
        )

        records.append({
            "ticket":       in_deal.order,
            "symbol":       in_deal.symbol,
            "pattern":      "manual" if in_deal.magic != BOT_MAGIC else "bot_unknown",
            "direction":    direction,
            "timeframe":    "M15",   # không biết chính xác từ deals — đặt M15 làm default
            "htf_trend":    "",
            "volume_ratio": 0.0,
            "entry_price":  in_deal.price,
            "sl":           sl,
            "tp":           tp,
            "lot":          in_deal.volume,
            "open_time":    open_dt.isoformat(),
            "open_hour_vn": open_vn.hour,
            "close_time":   close_dt.isoformat(),
            "close_price":  out_deal.price,
            "profit":       round(total_profit, 4),
            "result":       result,
            "close_reason": reason,
        })

    return records


# ─── Ghi vào DB ───────────────────────────────────────────────────────────────

def insert_records(records: list) -> tuple[int, int]:
    """Trả về (số ghi mới, số bỏ qua vì đã tồn tại)."""
    inserted = 0
    skipped  = 0
    with _get_conn() as conn:
        for r in records:
            cur = conn.execute(
                "SELECT ticket FROM trades WHERE ticket = ?", (r["ticket"],)
            )
            if cur.fetchone():
                skipped += 1
                continue
            conn.execute("""
                INSERT INTO trades
                (ticket,symbol,pattern,direction,timeframe,htf_trend,volume_ratio,
                 entry_price,sl,tp,lot,open_time,open_hour_vn,
                 close_time,close_price,profit,result,close_reason)
                VALUES
                (:ticket,:symbol,:pattern,:direction,:timeframe,:htf_trend,:volume_ratio,
                 :entry_price,:sl,:tp,:lot,:open_time,:open_hour_vn,
                 :close_time,:close_price,:profit,:result,:close_reason)
            """, r)
            inserted += 1
        conn.commit()
    return inserted, skipped


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Import lịch sử giao dịch MT5 vào trades.db")
    parser.add_argument("--bot-only",    action="store_true",
                        help="Chỉ import lệnh của bot (magic=20260622)")
    parser.add_argument("--days",        type=int, default=365,
                        help="Số ngày lịch sử cần lấy (mặc định: 365)")
    parser.add_argument("--show-stats",  action="store_true",
                        help="Hiển thị thống kê sau khi import")
    args = parser.parse_args()

    # Kết nối MT5
    if not mt5.initialize():
        logger.error("Không kết nối được MT5: %s", mt5.last_error())
        sys.exit(1)
    logger.info("Kết nối MT5 thành công.")

    # Khởi tạo DB
    trade_logger.init_db()

    # Lấy dữ liệu
    logger.info("Đang lấy lịch sử %d ngày...", args.days)
    deals  = fetch_all_deals(days_back=args.days)
    orders = fetch_all_orders(days_back=args.days)

    # Build records
    records = build_trade_records(deals, orders, bot_only=args.bot_only)
    logger.info("Số giao dịch đã đóng tìm được: %d", len(records))

    # Insert
    inserted, skipped = insert_records(records)
    logger.info("Đã ghi: %d lệnh mới | Bỏ qua (đã có): %d", inserted, skipped)

    # Stats
    if args.show_stats or True:
        with _get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM trades WHERE result IS NOT NULL").fetchone()[0]
            wins  = conn.execute("SELECT COUNT(*) FROM trades WHERE result='WIN'").fetchone()[0]
            loss  = conn.execute("SELECT COUNT(*) FROM trades WHERE result='LOSS'").fetchone()[0]

            print("\n" + "─" * 40)
            print(f"  Tổng lệnh đã đóng : {total}")
            if total > 0:
                print(f"  WIN               : {wins} ({wins/total*100:.1f}%)")
                print(f"  LOSS              : {loss} ({loss/total*100:.1f}%)")
                print(f"  Win rate          : {wins/total*100:.1f}%")

            print("\n  Win rate theo symbol:")
            rows = conn.execute("""
                SELECT symbol,
                       COUNT(*) as total,
                       SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins
                FROM trades WHERE result IS NOT NULL
                GROUP BY symbol ORDER BY wins*1.0/total DESC
            """).fetchall()
            for r in rows:
                wr = r["wins"] / r["total"] * 100 if r["total"] > 0 else 0
                print(f"    {r['symbol']:10} {r['wins']}/{r['total']} ({wr:.1f}%)")

            print("\n  Win rate theo pattern:")
            rows = conn.execute("""
                SELECT pattern,
                       COUNT(*) as total,
                       SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins
                FROM trades WHERE result IS NOT NULL AND pattern != 'manual'
                GROUP BY pattern ORDER BY wins*1.0/total DESC
            """).fetchall()
            for r in rows:
                wr = r["wins"] / r["total"] * 100 if r["total"] > 0 else 0
                print(f"    {r['pattern']:30} {r['wins']}/{r['total']} ({wr:.1f}%)")
            print("─" * 40)

    mt5.shutdown()


if __name__ == "__main__":
    main()