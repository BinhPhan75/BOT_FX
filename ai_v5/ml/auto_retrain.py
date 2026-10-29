# ai_v5/ml/auto_retrain.py
"""
VONG PHAN HOI TU HOC - PHAN 3: lich TU DONG train lai model dinh ky, khep
kin ca chu trinh (truoc day phai go lenh tay run_init_train.py moi khi
muon train lai, khong co lich tu dong nao).

Quy trinh moi lan chay 1 chu ky train lai:
    1. Dua ket qua THAT cua cac lenh vua dong vao dataset (live_feedback.py)
    2. Backup model hien tai (latest_model.pkl + meta.json) - phong truong
       hop model moi te hon, can khoi phuc lai.
    3. Gop toan bo dataset (lich su + phan hoi that) va train lai model moi
       (qua MLTrainer - da tu dong do tim tham so toi uu tu ban 23).
    4. SO SANH Precision cua model MOI voi model CU (doc tu file meta.json).
       Neu model moi TE HON qua nguong PRECISION_DROP_TOLERANCE -> TU DONG
       KHOI PHUC lai model cu (khong danh doi chat luong lay "tu dong" mu
       quang).
    5. Gui thong bao Telegram ve ket qua (thanh cong / bi khoi phuc / loi).

An toan quan trong: KHONG sua doi ml_trainer.py/model_manager.py - chi bao
quanh (orchestrate) bang cach sao chep/khoi phuc file, tranh phai dong vao
noi bo 2 module do.

Cach dung (chay 1 lan):
    python -m ai_v5.ml.auto_retrain

Cach dung (chay nen, tu lap lich):
    from ai_v5.ml.auto_retrain import start_scheduler
    start_scheduler()   # goi tu live_trader.py, chay ngam trong thread rieng

---------------------------------------------------------------------------
BẢN VÁ (xem "FIX #" trong code):
FIX #1 - _read_model_precision(): model_manager.save_model() luu precision
         LONG trong metadata["metrics"]["precision"], khong phai o cap goc
         metadata["precision"]. Ban cu doc sai vi tri -> luon tra ve None ->
         co che so sanh/khoi phuc model chua bao gio thuc su chay.
FIX #2 - _notify_telegram(): result.get(key, 0) khong bat duoc truong hop
         key TON TAI nhung gia tri la None (chi bat truong hop THIEU key) ->
         f"{None:.1%}" crash. Sua bang cach dung "or 0" de ep None -> 0.
---------------------------------------------------------------------------
"""
import os
import json
import shutil
import logging
import threading
import time
from datetime import datetime

from ai_v5.config_ai import MODELS_DIR, DATASETS_DIR
from ai_v5.config_live import (
    AUTO_RETRAIN_ENABLED, RETRAIN_CHECK_INTERVAL_SECONDS, RETRAIN_INTERVAL_DAYS,
    MIN_NEW_TRADES_TO_RETRAIN, PRECISION_DROP_TOLERANCE,
)

logger = logging.getLogger("ai_v5_auto_retrain")

_STATE_FILE = os.path.join(MODELS_DIR, "auto_retrain_state.json")
_LATEST_MODEL = os.path.join(MODELS_DIR, "latest_model.pkl")
_LATEST_META = os.path.join(MODELS_DIR, "latest_model_meta.json")
_BACKUP_MODEL = os.path.join(MODELS_DIR, "latest_model_backup.pkl")
_BACKUP_META = os.path.join(MODELS_DIR, "latest_model_backup_meta.json")


def _load_state() -> dict:
    if os.path.exists(_STATE_FILE):
        try:
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_retrain_time": None, "last_retrain_trade_count": 0}


def _save_state(state: dict) -> None:
    os.makedirs(MODELS_DIR, exist_ok=True)
    with open(_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _read_model_precision(meta_path: str) -> float:
    """
    Doc Precision tu file meta.json cua model.

    FIX #1: model_manager.ModelManager.save_model() luu metadata theo cau
    truc LONG NHAU:
        {
          "model_name": ...,
          "timestamp": ...,
          "metrics": {"accuracy": ..., "precision": ..., ...},   # <-- o day
          "features_used": [...],
          "framework": "LightGBM"
        }
    Ban cu doc `meta.get("precision")` (cap goc) nen luon None. Phai doc
    qua `meta["metrics"]["precision"]`.
    """
    if not os.path.exists(meta_path):
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        return meta.get("metrics", {}).get("precision")
    except Exception:
        return None


def _count_new_closed_trades_since(last_time: str) -> int:
    import sqlite3
    from ai_v5.config_ai import AI_BASE_DIR
    db_path = os.path.abspath(os.path.join(AI_BASE_DIR, "..", "ai_v5_trades.db"))
    if not os.path.exists(db_path):
        return 0
    conn = sqlite3.connect(db_path)
    if last_time:
        cur = conn.execute("SELECT COUNT(*) FROM ai_v5_trades WHERE close_time IS NOT NULL AND close_time > ?",
                           (last_time,))
    else:
        cur = conn.execute("SELECT COUNT(*) FROM ai_v5_trades WHERE close_time IS NOT NULL")
    count = cur.fetchone()[0]
    conn.close()
    return count


def run_retrain_cycle(force: bool = False) -> dict:
    """
    Chay 1 chu ky train lai day du. Tra ve dict ket qua de log/thong bao.
    force=True: bo qua kiem tra dieu kien (so luong lenh moi/thoi gian), luon chay.
    """
    from ai_v5.ml.live_feedback import export_new_closed_trades_to_dataset
    from ai_v5.data.data_loader import DataLoader
    from ai_v5.ml.ml_trainer import MLTrainer

    state = _load_state()
    n_new_trades = _count_new_closed_trades_since(state.get("last_retrain_time"))

    if not force and n_new_trades < MIN_NEW_TRADES_TO_RETRAIN:
        logger.info(f"Chỉ có {n_new_trades} lệnh mới đóng kể từ lần train trước "
                    f"(cần ≥{MIN_NEW_TRADES_TO_RETRAIN}) — chưa cần train lại.")
        return {"status": "skipped", "reason": "not_enough_new_trades", "n_new_trades": n_new_trades}

    logger.info(f"🔄 Bắt đầu chu kỳ train lại tự động ({n_new_trades} lệnh mới)...")

    # Buoc 1: dua ket qua that vao dataset
    try:
        n_added = export_new_closed_trades_to_dataset()
        logger.info(f"Đã thêm {n_added} mẫu từ lệnh thật vào dataset.")
    except Exception as e:
        logger.error(f"Lỗi export live feedback: {e}", exc_info=True)
        return {"status": "error", "reason": f"live_feedback_error: {e}"}

    # Buoc 2: backup model hien tai (neu co) truoc khi train de over-write
    old_precision = _read_model_precision(_LATEST_META)
    had_previous_model = os.path.exists(_LATEST_MODEL)
    if had_previous_model:
        shutil.copy2(_LATEST_MODEL, _BACKUP_MODEL)
        if os.path.exists(_LATEST_META):
            shutil.copy2(_LATEST_META, _BACKUP_META)
        # FIX #2 (rải rác): dùng "or 0" để tránh crash nếu old_precision vẫn None
        _old_p_log = old_precision if old_precision is not None else None
        logger.info(
            f"Đã backup model hiện tại (Precision cũ = {_old_p_log:.2%})."
            if _old_p_log is not None else "Đã backup model hiện tại (chưa có Precision cũ để đối chiếu)."
        )

    # Buoc 3: gop dataset (lich su + phan hoi that) va train lai
    try:
        combined_path = DataLoader.combine_all_datasets(DATASETS_DIR)
        trainer = MLTrainer(dataset_path=combined_path) if combined_path else MLTrainer()
        trainer.train()  # MLTrainer tu luu + cap nhat latest_model.pkl (hanh vi co san tu ban 23)
    except Exception as e:
        logger.error(f"Lỗi trong quá trình train lại: {e}", exc_info=True)
        return {"status": "error", "reason": f"train_error: {e}"}

    new_precision = _read_model_precision(_LATEST_META)

    # Buoc 4: so sanh, quyet dinh giu hay khoi phuc
    rolled_back = False
    if had_previous_model and old_precision is not None and new_precision is not None:
        if new_precision < old_precision - PRECISION_DROP_TOLERANCE:
            logger.warning(f"⚠️ Model mới TỆ HƠN đáng kể (Precision {new_precision:.2%} < "
                           f"{old_precision:.2%} - {PRECISION_DROP_TOLERANCE:.0%}) — KHÔI PHỤC lại model cũ.")
            shutil.copy2(_BACKUP_MODEL, _LATEST_MODEL)
            if os.path.exists(_BACKUP_META):
                shutil.copy2(_BACKUP_META, _LATEST_META)
            rolled_back = True
        else:
            logger.info(f"✅ Model mới đạt yêu cầu (Precision {new_precision:.2%} so với "
                        f"{old_precision:.2%} cũ) — GIỮ model mới.")
    elif had_previous_model:
        # FIX #1 lam lo ro truong hop nay: neu van None sau khi da sua duong
        # dan doc, nghia la ml_trainer.py chua ghi "precision" vao metrics khi
        # goi save_model() -> can kiem tra rieng ml_trainer.py.
        logger.warning("⚠️ Không đọc được Precision cũ/mới để so sánh (thiếu 'precision' trong "
                       "metrics) — GIỮ model mới nhưng KHÔNG có bảo vệ rollback cho lần này. "
                       "Kiểm tra ml_trainer.py có đang ghi 'precision' vào metrics khi gọi "
                       "save_model() hay không.")

    state["last_retrain_time"] = datetime.now().isoformat()
    state["last_retrain_trade_count"] = state.get("last_retrain_trade_count", 0) + n_new_trades
    _save_state(state)

    return {
        "status": "rolled_back" if rolled_back else "success",
        "n_new_trades": n_new_trades,
        "old_precision": old_precision,
        "new_precision": new_precision,
    }


def _should_retrain_now(state: dict) -> bool:
    last_time = state.get("last_retrain_time")
    if last_time is None:
        return True  # Chua tung train tu dong lan nao
    try:
        last_dt = datetime.fromisoformat(last_time)
    except Exception:
        return True
    days_since = (datetime.now() - last_dt).total_seconds() / 86400
    if days_since >= RETRAIN_INTERVAL_DAYS:
        return True

    # Kiem tra them: neu phat hien DRIFT thi khong cho doi du ngay, train som hon
    try:
        from ai_v5.ml.drift_monitor import check_drift
        drift_result = check_drift()
        if drift_result.get("has_drift"):
            logger.info("Phát hiện drift — kích hoạt train lại sớm hơn lịch thường lệ.")
            return True
    except Exception as e:
        logger.debug(f"Không kiểm tra được drift: {e}")

    return False


def _retrain_loop():
    logger.info(f"AI v5 Auto-Retrain scheduler sẵn sàng (kiểm tra mỗi "
                f"{RETRAIN_CHECK_INTERVAL_SECONDS}s, chu kỳ thường lệ {RETRAIN_INTERVAL_DAYS} ngày).")
    while True:
        try:
            state = _load_state()
            if _should_retrain_now(state):
                result = run_retrain_cycle()
                logger.info(f"Kết quả chu kỳ train lại: {result}")
                _notify_telegram(result)
        except Exception as e:
            logger.error(f"Lỗi trong vòng lặp Auto-Retrain: {e}", exc_info=True)
        time.sleep(RETRAIN_CHECK_INTERVAL_SECONDS)


def _notify_telegram(result: dict) -> None:
    """
    FIX #2: result.get('old_precision', 0) chi tra ve 0 khi THIEU key
    'old_precision'. Trong thuc te key nay LUON TON TAI nhung gia tri co the
    la None (chua co model cu de so sanh) -> .get(key, 0) van tra ve None ->
    f"{None:.1%}" nem loi "unsupported format string passed to
    NoneType.__format__". Dung "or 0" de ep ca truong hop None lan thieu key
    ve 0 an toan.
    """
    try:
        from ai_v5.config_ai import TELEGRAM_AI_TOKEN, TELEGRAM_AI_CHAT_ID
        from ai_v5.live.telegram_commander import _send
    except Exception:
        return
    if not TELEGRAM_AI_TOKEN or not TELEGRAM_AI_CHAT_ID:
        return

    status = result.get("status")
    if status == "skipped":
        return  # Khong lam phien Telegram khi khong co gi xay ra

    old_p = result.get("old_precision") or 0  # FIX #2
    new_p = result.get("new_precision") or 0  # FIX #2

    if status == "success":
        msg = (f"🧠 <b>AI v5 — Train lại tự động THÀNH CÔNG</b>\n"
               f"Lệnh mới đóng: {result.get('n_new_trades')}\n"
               f"Precision: {old_p:.1%} → {new_p:.1%}")
    elif status == "rolled_back":
        msg = (f"⚠️ <b>AI v5 — Train lại tự động: model MỚI TỆ HƠN, đã KHÔI PHỤC model cũ</b>\n"
               f"Precision cũ giữ nguyên: {old_p:.1%} "
               f"(model mới chỉ đạt {new_p:.1%})")
    else:
        msg = f"❌ <b>AI v5 — Train lại tự động LỖI</b>\n{result.get('reason', 'Không rõ lý do')}"

    try:
        _send(TELEGRAM_AI_TOKEN, TELEGRAM_AI_CHAT_ID, msg)
    except Exception:
        pass


def start_scheduler() -> threading.Thread:
    """Khoi dong daemon thread train lai tu dong. Goi tu live_trader.py main()."""
    if not AUTO_RETRAIN_ENABLED:
        logger.info("AUTO_RETRAIN_ENABLED = False — không khởi động lịch train lại tự động.")
        return None
    t = threading.Thread(target=_retrain_loop, name="AI_v5_AutoRetrain", daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    result = run_retrain_cycle(force=True)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
