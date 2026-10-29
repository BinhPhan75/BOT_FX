"""
deep_tuner.py — Backtest SAU, dung NHIEU NAM du lieu lich su, chay RIENG
BIET voi auto_tuner.py (chay tu dong 2h sang moi ngay).

Muc dich: auto_tuner.py hang ngay chi toi uu tren AUTO_TUNER_BACKTEST_DAYS
(mac dinh 365 ngay = ~1 nam) de chay nhanh (~1h/symbol). Script nay dung
DE RIENG cho nhung lan toi uu "sau" hon — vi du 3-5 nam du lieu — de tim
bo tham so on dinh qua nhieu chu ky thi truong khac nhau, khong chi dua
vao du lieu live/gan day.

KHAC BIET voi auto_tuner.py:
  - Dung checkpoint RIENG (deep_tuner_checkpoint.json) — KHONG dung chung
    voi auto_tuner.py, tranh xung dot/lam sai lich chay 2h sang hang ngay.
  - total_days LON HON NHIEU (mac dinh 1095 = 3 nam, co the chinh qua --days).
  - Van ghi ket qua vao CUNG optimized_params.json (ap dung ngay cho live),
    dung y het _optimize_symbol()/COARSE_GRID cua auto_tuner.py — KHONG
    trung lap logic, chi goi lai.

LUU Y QUAN TRONG ve du lieu lich su:
  MT5 chi cung cap duoc du lieu M15/H1 xa den dau tuy theo BROKER va
  TERMINAL da tai ve truoc do chua (Tools > Options > Charts > "Max bars
  in history", hoac phai tu cuon chart M15/H1 ve qua khu that xa it nhat
  1 lan trong terminal MT5 dang mo de no tai du lieu). Neu --days qua lon
  so voi du lieu terminal co, cac cua so WFO xa nhat se tra ve loi "khong
  du du lieu" — xem log de biet chinh xac symbol/cua so nao thieu du lieu.

Cach dung (khuyen nghi chay cuoi tuan, thi truong dong cua, khong anh
huong bot dang giao dich live vi day la process RIENG, doc lap):
    py -3.11 deep_tuner.py                          # 3 nam, tat ca symbol
    py -3.11 deep_tuner.py --days 1825               # 5 nam
    py -3.11 deep_tuner.py --symbols XAUUSD,EURUSD   # chi 1 vai symbol
    py -3.11 deep_tuner.py --force                   # xoa checkpoint rieng, chay lai tu dau

Dat lich tu dong cuoi tuan (Windows Task Scheduler), vi du chay 00:30 sang
Thu Bay hang tuan:
    schtasks /create /tn "DeepTuner" /tr "py -3.11 C:\\path\\to\\bot_xutho4\\deep_tuner.py" ^
        /sc weekly /d SAT /st 00:30
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import config
import param_loader
import auto_tuner

logger = logging.getLogger("deep_tuner")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEEP_CHECKPOINT_PATH = os.path.join(_BASE_DIR, "deep_tuner_checkpoint.json")


def _load_checkpoint() -> dict:
    if os.path.exists(DEEP_CHECKPOINT_PATH):
        try:
            with open(DEEP_CHECKPOINT_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Khong doc duoc checkpoint rieng: %s", e)
    return {}


def _save_checkpoint(completed: dict, started_at: str, total_days: int):
    try:
        with open(DEEP_CHECKPOINT_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "started_at": started_at,
                "total_days": total_days,
                "completed_symbols": completed,
            }, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error("Khong ghi duoc checkpoint rieng: %s", e)


def _clear_checkpoint():
    if os.path.exists(DEEP_CHECKPOINT_PATH):
        os.remove(DEEP_CHECKPOINT_PATH)
        logger.info("Da xoa deep_tuner_checkpoint.json — chay lai tu dau.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=1095,
                         help="So ngay du lieu lich su (mac dinh 1095 = ~3 nam)")
    parser.add_argument("--symbols", type=str, default=None,
                         help="Danh sach symbol cach nhau boi dau phay, vd XAUUSD,EURUSD "
                              "(mac dinh: dung config.SYMBOLS)")
    parser.add_argument("--force", action="store_true",
                         help="Xoa checkpoint RIENG cua deep_tuner (khong dung den "
                              "checkpoint/optimized_params.json cua auto_tuner.py)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    symbols = args.symbols.split(",") if args.symbols else list(config.SYMBOLS)
    total_days = args.days

    if args.force:
        _clear_checkpoint()

    logger.info("=" * 60)
    logger.info("DEEP TUNER — Backtest SAU %d ngay (~%.1f nam)", total_days, total_days / 365)
    logger.info("Symbols: %s", symbols)
    logger.info("Checkpoint RIENG: %s (khong dung chung voi auto_tuner.py)", DEEP_CHECKPOINT_PATH)
    logger.info("CANH BAO: can MT5 terminal da co du du lieu lich su xa den vay —")
    logger.info("  neu chua, hay cuon chart M15/H1 ve qua khu that xa it nhat 1 lan")
    logger.info("  trong terminal MT5 dang mo de no tai du lieu ve truoc khi chay.")
    logger.info("=" * 60)

    checkpoint = _load_checkpoint()
    results: dict = dict(checkpoint.get("completed_symbols", {}))
    started_at = checkpoint.get("started_at") or datetime.now(timezone.utc).isoformat()

    remaining = [s for s in symbols if s not in results]
    if not remaining:
        logger.info("Tat ca %d symbol da co ket qua trong checkpoint rieng nay.", len(symbols))
        logger.info("Dung --force neu muon chay lai tu dau.")
        return

    logger.info("Con %d/%d symbol can toi uu sau: %s", len(remaining), len(symbols), remaining)

    t0 = time.time()
    for idx, symbol in enumerate(remaining, 1):
        sym_t0 = time.time()
        logger.info("")
        logger.info("### [%d/%d] DEEP TUNE: %s (%d ngay du lieu) ###",
                     idx, len(remaining), symbol, total_days)

        try:
            res = auto_tuner._optimize_symbol(symbol, total_days=total_days)
        except Exception as e:
            logger.exception("[%s] LOI: %s — bo qua, tiep tuc symbol khac.", symbol, e)
            res = None

        sym_elapsed = time.time() - sym_t0

        if res:
            results[symbol] = res
            logger.info(
                "### [%d/%d] XONG %s sau %.1f phut | WR=%.1f%% PF=%.2f (tren %d ngay) ###",
                idx, len(remaining), symbol, sym_elapsed / 60,
                res.get("win_rate", 0), res.get("profit_factor", 0), total_days,
            )
            # Ghi ngay vao optimized_params.json — ap dung cho live ngay lap tuc,
            # giong het hanh vi cua auto_tuner.py hang ngay.
            param_loader.save({symbol: res})
            logger.info("[%s] Da ghi optimized_params.json (deep-tuned).", symbol)
        else:
            logger.warning(
                "### [%d/%d] %s: KHONG tim duoc tham so dat nguong tren %d ngay du lieu. "
                "Giu nguyen tham so hien tai. ###",
                idx, len(remaining), symbol, total_days,
            )

        _save_checkpoint(results, started_at, total_days)

    elapsed = time.time() - t0
    logger.info("")
    logger.info("=" * 60)
    logger.info("DEEP TUNER HOAN TAT sau %.1f gio | %d/%d symbol: %s",
                elapsed / 3600, len(results), len(symbols), list(results.keys()))
    logger.info("=" * 60)

    try:
        auto_tuner._notify_telegram(results)
    except Exception as e:
        logger.warning("Khong gui duoc Telegram summary: %s", e)


if __name__ == "__main__":
    main()