# ai_v6/live/live_trader.py
"""
Diem khoi dong CHINH cho AI v6 - chien luoc DCA 1 CHIEU KIEU SCALPING, CHI giao dich
XAUUSD, phan tich da khung M15 (xu huong) + M5 (xac nhan) + M1 (entry/DCA timing/SL-TP).
Chay doc lap HOAN TOAN voi bot v4 va ai_v5 (magic number/DB/Telegram bot rieng) - co the
chay song song ca 3 tren cung 1 may/VPS.

TOM TAT CAC BAN VA DA AP DUNG (theo thu tu thoi gian):
  1. Heartbeat log moi ~60s (HEARTBEAT_EVERY_N_CYCLES) - xac nhan vong lap van chay.
  2. Log chi tiet ADX/regime khi M15 "neutral" - biet dang ket o buoc nao.
  3. Thiet ke lai thanh SCALPING: SL/TP theo ATR khung M1 (khong con ATR M5), DCA trigger
     theo boi so ATR M1 (khong con USD co dinh), DCA cooldown rut ngan, chot lenh cuong buc
     theo MAX_HOLD_MINUTES neu chua cham TP/SL.
  4. M1 entry confirmation chuyen sang che do "soft" (chi chan khi nen M1 nguoc chieu RO
     RET), tranh lap lai loi "AND-logic kills signal frequency" da ghi nhan voi bot v4.
  5. Chong FOMO duoi gia: theo doi lan dong nhom gan nhat (ca dong tu nhien qua TP/SL cua
     MT5 lan dong do bot chu dong qua timeout), chan mo lai CUNG CHIEU qua som/qua xa.
  6. BAN VA #2 cho co che chong FOMO: them CHASE_GUARD_MAX_AGE_MINUTES - truoc day lop
     chan theo GIA khong co gioi han thoi gian, khien 1 lan dong tu 12+ TIENG TRUOC van
     tiep tuc chan lenh moi. Gio toan bo co che (ca cooldown lan chase-guard theo gia) chi
     con hieu luc trong CHASE_GUARD_MAX_AGE_MINUTES ke tu luc dong - qua moc nay TAT HAN.
  7. BAN VA #3: chan vao lenh (ca goc lan DCA) khi ATR(M1) dang spike bat thuong so voi
     muc binh thuong gan day - bien dong cuc doan de gay truot gia/gap qua SL.

Cach chay:
    1. Mo MT5 terminal RIENG cho ai_v6 (khac terminal cua v4/ai_v5), dang nhap tai khoan bang tay.
    2. Dam bao da co model ML RIENG: ai_v6/models/latest_model.pkl (train bang
       build_train_v6_scalping.py - nhan THANG/THUA phai khop DUNG co che scalping dang dung,
       KHONG dung run_init_train_v6.py cu vi nhan sai co che).
    3. (Tuy chon) Set AI_V6_TELEGRAM_BOT_TOKEN / AI_V6_TELEGRAM_CHAT_ID.
    4. Chay: py -3.11 -m ai_v6.live.live_trader
"""
import logging
import os
import time
from datetime import datetime, timezone, timedelta

import mt5_client  # Tai su dung ham get_candles/get_last_closed_time (khong quan tam dang ket noi tk nao)

from ai_v6.config_ai import PROBABILITY_THRESHOLD, LOGS_DIR, TELEGRAM_AI_TOKEN, TELEGRAM_AI_CHAT_ID
from ai_v6.config_live import (
    SYMBOLS, TF_TREND, TF_CONFIRM, TF_ENTRY, SCAN_INTERVAL_SECONDS,
    CANDLES_LOOKBACK_TREND, CANDLES_LOOKBACK_CONFIRM, CANDLES_LOOKBACK_ENTRY,
    MAX_DCA_POSITIONS, DCA_TRIGGER_ATR_MULTIPLE, DCA_MIN_INTERVAL_MINUTES, MAX_HOLD_MINUTES,
    POST_CLOSE_SAME_DIRECTION_COOLDOWN_MINUTES, CHASE_GUARD_ATR_MULTIPLE, CHASE_GUARD_MAX_AGE_MINUTES,
    MAX_ATR_SPIKE_MULTIPLE, ATR_ROLLING_BASELINE_PERIOD,
    TRADING_HOURS_ENABLED, TRADING_HOURS_START_VN, TRADING_HOURS_END_VN,
)
from ai_v6.live import mt5_connector, trade_executor, trade_logger, telegram_commander
from ai_v6.live import position_group_manager as group_mgr
from ai_v6.live.mtf_scanner import (
    get_m15_trend_bias, get_m5_confirmed_matches, m1_entry_confirmed, score_match_with_ml, calc_m1_atr,
    calc_m1_atr_rolling_mean,
)
from ai_v6.ml.predictor_v6 import AIPredictorV6 as AIPredictor

logger = logging.getLogger("ai_v6_live_trader")

_last_processed_m1_time = {}   # {symbol: last_closed_m1_time} - tranh xu ly trung 1 nen M1
_last_dca_time = {}            # {symbol: datetime lan DCA gan nhat} - ap dung DCA_MIN_INTERVAL_MINUTES

# Chong FOMO duoi gia: theo doi trang thai nhom o CHU KY TRUOC (phat hien nhom vua dong "tu
# nhien" qua TP/SL cua MT5, khong chi dong do bot chu dong) va thong tin lan dong gan nhat.
_last_known_group_snapshot = {}  # {symbol: {"direction","sl","tp"} hoac None}
_last_group_close = {}           # {symbol: {"direction","exit_price","exit_time"}}

# Heartbeat: cu moi N chu ky (mac dinh 6 x SCAN_INTERVAL_SECONDS ~ 60s) in 1 dong log de
# XAC NHAN vong lap van dang chay, du khong tim thay tin hieu nao.
HEARTBEAT_EVERY_N_CYCLES = 6
_cycle_count = 0


def _is_atr_spiking(symbol: str, m1_candles: list, atr_m1: float) -> tuple:
    """
    BẢN VÁ (sau audit 88 lệnh thật cho thấy win rate thấp hơn hẳn kỳ vọng): chặn vào lệnh khi
    ATR(M1) hiện tại đang cao BẤT THƯỜNG so với mức bình thường gần đây - biến động cực đoan dễ
    gây trượt giá/gap qua SL nhiều hơn con số ATR 14 nến "trailing" thể hiện được (cửa sổ 14 nến
    phản ứng CHẬM với 1 cú spike đột ngột). Dùng SO SÁNH TƯƠNG ĐỐI (giống market_regime.py chặn
    ADX spike cho VOLATILE) thay vì ngưỡng USD cố định.

    Tra ve (should_block: bool, reason: str).
    """
    baseline = calc_m1_atr_rolling_mean(m1_candles, period=14, lookback=ATR_ROLLING_BASELINE_PERIOD)
    if baseline <= 0:
        return False, ""  # Chua du du lieu de tinh baseline - KHONG chan oan, coi nhu binh thuong

    ratio = atr_m1 / baseline
    if ratio > MAX_ATR_SPIKE_MULTIPLE:
        return True, (f"ATR(M1)={atr_m1:.2f} đang gấp {ratio:.1f}× mức bình thường gần đây "
                      f"({baseline:.2f}, vượt ngưỡng {MAX_ATR_SPIKE_MULTIPLE}×) — biến động quá cực đoan, "
                      f"chờ ổn định lại thay vì vào lệnh ngay")
    return False, ""


def _is_trading_hours() -> bool:
    if not TRADING_HOURS_ENABLED:
        return True
    start_h = TRADING_HOURS_START_VN % 24
    end_h = TRADING_HOURS_END_VN
    vn_tz = timezone(timedelta(hours=7))
    hour = datetime.now(vn_tz).hour
    if end_h >= 24:
        return hour >= start_h
    if start_h <= end_h:
        return start_h <= hour < end_h
    return hour >= start_h or hour < end_h


def _is_dca_cooldown_active(symbol: str) -> bool:
    last_time = _last_dca_time.get(symbol)
    if last_time is None:
        return False
    return (datetime.now() - last_time).total_seconds() / 60 < DCA_MIN_INTERVAL_MINUTES


def _current_price(symbol: str):
    import MetaTrader5 as mt5
    tick = mt5.symbol_info_tick(symbol)
    return tick.bid if tick else None


def _guess_exit_price(current_price: float, sl: float, tp: float) -> float:
    """Uoc luong gia dong lenh THAT (TP hay SL) khi phat hien nhom vua dong ma khong ro
    nguyen nhan chinh xac (dong "tu nhien" qua MT5, bot khong chu dong dong) - chon muc GAN
    gia hien tai HON trong 2 muc SL/TP, vi gia thuong chua kip di qua xa trong vai giay-vai
    chuc giay tu luc lenh dong den luc bot phat hien (chu ky quet moi SCAN_INTERVAL_SECONDS)."""
    return tp if abs(current_price - tp) <= abs(current_price - sl) else sl


def _record_group_closed(symbol: str, direction: str, exit_price: float) -> None:
    """Ghi nhan 1 nhom VUA dong (bat ke ly do: TP/SL tu nhien qua MT5, hoac bot chu dong dong
    do timeout) - dung lam co so cho _is_chasing_after_recent_close() chan FOMO duoi gia."""
    _last_group_close[symbol] = {"direction": direction, "exit_price": exit_price, "exit_time": datetime.now()}
    logger.info(f"[{symbol}] Ghi nhận nhóm {direction} vừa đóng tại ~{exit_price:.2f} — áp dụng "
                f"cơ chế chống FOMO trong tối đa {CHASE_GUARD_MAX_AGE_MINUTES} phút tới trước khi "
                f"cho phép mở lại CÙNG CHIỀU không giới hạn.")


def _is_chasing_after_recent_close(symbol: str, bias_direction: str, current_price: float, atr_m1: float):
    """
    Chong FOMO duoi gia: bot vua chot 1 nhom, gia van dang chay manh cung chieu nen tin hieu
    M15+M5+M1 tiep tuc dong thuan NGAY LAP TUC, khien bot mo lai dung luc gia da di qua xa.
    CHI ap dung khi nhom moi CUNG CHIEU voi nhom vua dong (di nguoc chieu la thiet lap dao
    chieu moi, khong phai FOMO tiep dien).

    BẢN VÁ #2: truoc day lop chan theo GIA (sau khi qua cooldown) KHONG co gioi han thoi gian,
    khien 1 lan dong tu 12+ TIENG TRUOC van tiep tuc chan lenh moi. Gio toan bo co che (ca
    cooldown lan chase-guard theo gia) chi con hieu luc trong CHASE_GUARD_MAX_AGE_MINUTES ke
    tu luc dong - qua moc nay TAT HAN, khong con xet gia nua.

    Tra ve (should_block: bool, reason: str).
    """
    last_close = _last_group_close.get(symbol)
    if last_close is None or last_close["direction"] != bias_direction:
        return False, ""

    elapsed_min = (datetime.now() - last_close["exit_time"]).total_seconds() / 60

    # BẢN VÁ #2: qua khoi thoi gian hieu luc toi da -> co che TAT HAN, khong xet gia nua.
    if elapsed_min >= CHASE_GUARD_MAX_AGE_MINUTES:
        return False, ""

    if elapsed_min < POST_CLOSE_SAME_DIRECTION_COOLDOWN_MINUTES:
        return True, (f"vừa đóng nhóm {bias_direction} cách đây {elapsed_min:.1f} phút "
                      f"(cần ≥{POST_CLOSE_SAME_DIRECTION_COOLDOWN_MINUTES} phút để tránh FOMO đuổi giá)")

    guard_distance = CHASE_GUARD_ATR_MULTIPLE * atr_m1
    if bias_direction == "BUY":
        is_chasing = current_price > last_close["exit_price"] + guard_distance
    else:
        is_chasing = current_price < last_close["exit_price"] - guard_distance

    if is_chasing:
        return True, (f"giá đã đi quá xa so với lần đóng {bias_direction} gần nhất "
                      f"(đóng tại {last_close['exit_price']:.2f}, hiện tại {current_price:.2f}, "
                      f"vượt {CHASE_GUARD_ATR_MULTIPLE}×ATR={guard_distance:.2f}) — chờ hồi lại thay vì đuổi giá")
    return False, ""


def _pick_best_match(matches: list, predictor, regime_res):
    """Neu nhieu nhom pattern cung khop cung huong tai 1 thoi diem, chon match co WinProb cao nhat."""
    best = None
    for source_type, match in matches:
        win_prob = score_match_with_ml(predictor, match, source_type, regime_res)
        if best is None or win_prob > best[2]:
            best = (source_type, match, win_prob)
    return best  # (source_type, match, win_prob) hoac None neu matches rong


def _handle_trade_result(symbol, source_type, match, win_prob, result, is_dca,
                          regime_res=None, chart_candles=None, adverse_distance=None):
    if result.get("success"):
        try:
            trade_logger.log_open_trade(
                ticket=result["ticket"], symbol=symbol, pattern=match["pattern"], source_type=source_type,
                direction=result["direction"], entry=result["entry"], lot=result["lot"],
                win_probability=win_prob, is_dca=is_dca, dca_sequence=result["n_positions_in_group"],
                group_avg_entry=result.get("group_avg_entry"), group_sl=result.get("group_sl"),
                group_tp=result.get("group_tp"),
            )
        except Exception as e:
            logger.error(f"[AI v6] Lỗi ghi log lệnh #{result['ticket']} (lệnh vẫn ĐÃ ĐẶT thành công "
                         f"trên MT5, chỉ lỗi ghi log): {e}", exc_info=True)
    else:
        logger.warning(f"[AI v6] Không mở được lệnh {'DCA' if is_dca else 'GỐC'} {symbol}: {result.get('error')}")

    try:
        telegram_commander.notify_trade(symbol, match["pattern"], source_type, win_prob, result, is_dca,
                                         match=match, regime_res=regime_res, chart_candles=chart_candles,
                                         adverse_distance=adverse_distance)
    except Exception as e:
        logger.error(f"[AI v6] Lỗi gửi Telegram (không ảnh hưởng lệnh đã đặt): {e}", exc_info=True)


def _try_open_initial_group(symbol: str, predictor: AIPredictor) -> None:
    """Chua co nhom nao dang mo tren symbol - tim tin hieu M15+M5+M1 dong thuan de mo LENH GOC."""
    m15_candles = mt5_client.get_candles(symbol, TF_TREND, CANDLES_LOOKBACK_TREND)
    if not m15_candles or len(m15_candles) < 220:
        logger.info(f"[{symbol}] Không lấy được đủ nến M15 ({len(m15_candles) if m15_candles else 0}/220) — bỏ qua chu kỳ này.")
        return

    bias_direction, regime_res = get_m15_trend_bias(symbol, m15_candles)
    if bias_direction is None:
        trend_dir = (regime_res.trend_dir if regime_res else "N/A")
        adx_val = (getattr(regime_res, "adx", None) if regime_res else None)
        regime_type = (getattr(regime_res, "regime", None) if regime_res else None)
        logger.info(f"[{symbol}] M15 chưa có xu hướng rõ (trend_dir={trend_dir}, adx={adx_val}, "
                    f"regime={regime_type}) — bỏ qua mở nhóm mới.")
        return

    m5_candles = mt5_client.get_candles(symbol, TF_CONFIRM, CANDLES_LOOKBACK_CONFIRM)
    if not m5_candles or len(m5_candles) < 220:
        logger.info(f"[{symbol}] Không lấy được đủ nến M5 ({len(m5_candles) if m5_candles else 0}/220) — bỏ qua chu kỳ này.")
        return

    confirmed_matches = get_m5_confirmed_matches(symbol, m5_candles, bias_direction)
    if not confirmed_matches:
        logger.info(f"[{symbol}] M15 bias={bias_direction} nhưng M5 KHÔNG có pattern nào cùng chiều tại nến này.")
        return

    m1_candles = mt5_client.get_candles(symbol, TF_ENTRY, CANDLES_LOOKBACK_ENTRY)
    # M1 "soft": chi chan khi nen M1 ngược chiều RÕ RỆT, không đòi khớp tuyệt đối - tránh lặp
    # lại lỗi "AND-logic kills signal frequency" đã ghi nhận với bot v4.
    if not m1_entry_confirmed(m1_candles, bias_direction, strict=False):
        logger.info(f"[{symbol}] M15+M5 đồng thuận {bias_direction} ({len(confirmed_matches)} pattern) "
                    f"nhưng M1 đang có nến ngược chiều RÕ RỆT — bỏ qua thời điểm này.")
        return

    picked = _pick_best_match(confirmed_matches, predictor, regime_res)
    if picked is None:
        return
    source_type, match, win_prob = picked

    logger.info(f"[SCAN] {symbol} | {match['pattern']} ({source_type}) | M15 bias={bias_direction} | "
                f"WinProb={win_prob:.1%} | {'✅ DUYỆT' if win_prob >= PROBABILITY_THRESHOLD else '⛔ BỎ QUA'}")

    if win_prob < PROBABILITY_THRESHOLD:
        return
    if not _is_trading_hours():
        logger.info(f"[AI v6 LIVE] Ngoài khung giờ giao dịch ({TRADING_HOURS_START_VN}h-"
                     f"{TRADING_HOURS_END_VN}h VN) — bỏ qua mở nhóm mới {symbol}.")
        return

    # SCALPING: dùng ATR khung M1 (không phải ATR M5 của match) làm cơ sở SL/TP - biên độ nhỏ
    # hơn nhiều, khớp đúng bản chất "vào nhanh ra nhanh" thay vì trend/swing.
    atr = calc_m1_atr(m1_candles)
    if atr <= 0:
        logger.warning(f"[{symbol}] Không tính được ATR M1 (thiếu dữ liệu nến) — bỏ qua mở lệnh.")
        return

    # BẢN VÁ: chặn nếu ATR đang spike bất thường (biến động cực đoan) - kiểm tra TRƯỚC chase-guard
    # vì đây là rủi ro nghiêm trọng hơn (có thể gây trượt giá/gap qua SL bất kể FOMO hay không).
    should_block_atr, atr_block_reason = _is_atr_spiking(symbol, m1_candles, atr)
    if should_block_atr:
        logger.info(f"[{symbol}] Bỏ qua vào lệnh {bias_direction} — {atr_block_reason}.")
        return

    # Chống FOMO đuổi giá: kiểm tra CUỐI CÙNG trước khi thực sự vào lệnh.
    current_price = _current_price(symbol)
    if current_price is not None:
        should_block, block_reason = _is_chasing_after_recent_close(symbol, bias_direction, current_price, atr)
        if should_block:
            logger.info(f"[{symbol}] Bỏ qua vào lệnh {bias_direction} — {block_reason}.")
            return

    result = trade_executor.place_v6_trade(symbol, bias_direction, match["pattern"], win_prob, atr, is_dca=False)
    _handle_trade_result(symbol, source_type, match, win_prob, result, is_dca=False,
                          regime_res=regime_res, chart_candles=m5_candles)


def _try_add_dca(symbol: str, predictor: AIPredictor, existing_positions: list) -> None:
    """Da co 1-2 lenh trong nhom - kiem tra CA 2 dieu kien DCA truoc khi them lenh."""
    if len(existing_positions) >= MAX_DCA_POSITIONS:
        return
    if _is_dca_cooldown_active(symbol):
        logger.info(f"[{symbol}] Nhóm DCA đang trong thời gian cooldown ({DCA_MIN_INTERVAL_MINUTES} phút) — bỏ qua.")
        return

    direction = group_mgr.get_group_direction(existing_positions)
    avg_entry = group_mgr.calc_group_average_entry(existing_positions)
    price = _current_price(symbol)
    if price is None:
        logger.warning(f"[{symbol}] Không lấy được giá hiện tại để kiểm tra DCA.")
        return

    # SCALPING: tính ATR M1 SỚM (trước khi kiểm tra điều kiện a) để dùng ngưỡng DCA ĐỘNG (theo
    # bội số ATR hiện tại) thay vì 1 con số USD CỐ ĐỊNH - tự động co giãn theo biến động thực tế.
    m1_candles = mt5_client.get_candles(symbol, TF_ENTRY, CANDLES_LOOKBACK_ENTRY)
    atr = calc_m1_atr(m1_candles)
    if atr <= 0:
        logger.warning(f"[{symbol}] Không tính được ATR M1 (thiếu dữ liệu nến) — bỏ qua kiểm tra DCA.")
        return

    # BẢN VÁ: chặn thêm DCA nếu ATR đang spike bất thường - DCA vào lúc biến động cực đoan còn
    # rủi ro hơn cả lệnh gốc (đang gánh thêm rủi ro lên vị thế đã lỗ).
    should_block_atr, atr_block_reason = _is_atr_spiking(symbol, m1_candles, atr)
    if should_block_atr:
        logger.info(f"[{symbol}] Bỏ qua DCA {direction} — {atr_block_reason}.")
        return

    dca_trigger_distance = DCA_TRIGGER_ATR_MULTIPLE * atr

    # Điều kiện (a): giá đã đi NGƯỢC hướng nhóm đủ xa (theo ATR M1 HIỆN TẠI, không còn USD cứng)
    adverse_distance = (avg_entry - price) if direction == "BUY" else (price - avg_entry)
    if adverse_distance < dca_trigger_distance:
        logger.info(f"[{symbol}] Nhóm DCA {direction} ({len(existing_positions)} lệnh) | Entry TB={avg_entry:.2f} | "
                    f"Giá hiện tại={price:.2f} | Lệch={adverse_distance:.2f} / cần ≥{dca_trigger_distance:.2f} "
                    f"(={DCA_TRIGGER_ATR_MULTIPLE}×ATR_M1={atr:.2f}) — chưa đủ điều kiện (a) để xét DCA.")
        return

    # Điều kiện (b): cần 1 tín hiệu XÁC NHẬN MỚI cùng hướng trên M5 (7 nhóm pattern ai_v5)
    m5_candles = mt5_client.get_candles(symbol, TF_CONFIRM, CANDLES_LOOKBACK_CONFIRM)
    if not m5_candles or len(m5_candles) < 220:
        return
    confirmed_matches = get_m5_confirmed_matches(symbol, m5_candles, direction)
    if not confirmed_matches:
        logger.info(f"[{symbol}] Đủ điều kiện (a) (lệch {adverse_distance:.2f} USD) nhưng CHƯA có tín hiệu "
                    f"M5 xác nhận mới cùng chiều {direction} — chưa thêm DCA.")
        return

    # M1 "soft" - chỉ chặn DCA khi nến M1 ngược chiều RÕ RỆT, không đòi khớp tuyệt đối.
    if not m1_entry_confirmed(m1_candles, direction, strict=False):
        logger.info(f"[{symbol}] Đủ điều kiện (a)+(b) nhưng M1 đang có nến ngược chiều RÕ RỆT — chưa thêm DCA.")
        return

    m15_candles = mt5_client.get_candles(symbol, TF_TREND, CANDLES_LOOKBACK_TREND)
    _, regime_res = get_m15_trend_bias(symbol, m15_candles or [])

    picked = _pick_best_match(confirmed_matches, predictor, regime_res)
    if picked is None:
        return
    source_type, match, win_prob = picked

    logger.info(f"[DCA-CHECK] {symbol} | giá lệch {adverse_distance:.2f} USD ≥ {dca_trigger_distance:.2f} | "
                f"tín hiệu mới: {match['pattern']} ({source_type}) | WinProb={win_prob:.1%} | "
                f"{'✅ DCA' if win_prob >= PROBABILITY_THRESHOLD else '⛔ BỎ QUA'}")

    if win_prob < PROBABILITY_THRESHOLD:
        return
    if not _is_trading_hours():
        return

    result = trade_executor.place_v6_trade(symbol, direction, match["pattern"], win_prob, atr, is_dca=True)
    if result.get("success"):
        _last_dca_time[symbol] = datetime.now()
    _handle_trade_result(symbol, source_type, match, win_prob, result, is_dca=True,
                          regime_res=regime_res, chart_candles=m5_candles, adverse_distance=adverse_distance)


def _check_and_close_timed_out_group(symbol: str, existing_positions: list) -> bool:
    """
    SCALPING: chốt TOÀN BỘ nhóm nếu đã giữ quá MAX_HOLD_MINUTES mà CHƯA chạm TP/SL - đặc
    trưng bắt buộc của scalping (không "ôm" lệnh vô thời hạn chờ TP xa). Trả về True nếu đã
    đóng nhóm (để run_once() biết mà bỏ qua các bước xử lý khác trong chu kỳ này)."""
    if not existing_positions:
        return False

    open_time = group_mgr.get_group_open_time(existing_positions)
    if open_time is None:
        return False

    elapsed_minutes = (datetime.now(timezone.utc).timestamp() - open_time) / 60
    if elapsed_minutes < MAX_HOLD_MINUTES:
        return False

    logger.info(f"[{symbol}] Nhóm đã giữ {elapsed_minutes:.1f} phút ≥ {MAX_HOLD_MINUTES} phút "
                f"(giới hạn scalping) mà chưa chạm TP/SL — đóng toàn bộ nhóm.")
    direction_before_close = group_mgr.get_group_direction(existing_positions)
    close_result = trade_executor.close_group_positions(symbol, reason="max_hold_timeout")

    # Chống FOMO đuổi giá: ghi nhận lần đóng này để áp dụng cooldown/chase-guard cho lần mở
    # nhóm mới tiếp theo - dùng giá hiện tại làm gần đúng (đóng bằng lệnh thị trường tại đây).
    price_now = _current_price(symbol)
    if price_now is not None:
        _record_group_closed(symbol, direction_before_close, price_now)
    _last_known_group_snapshot[symbol] = None

    try:
        if TELEGRAM_AI_TOKEN and TELEGRAM_AI_CHAT_ID:
            telegram_commander._send(
                TELEGRAM_AI_TOKEN, TELEGRAM_AI_CHAT_ID,
                f"⏱ <b>AI v6 — Đóng nhóm {symbol} theo giới hạn thời gian (scalping)</b>\n"
                f"Đã giữ {elapsed_minutes:.1f} phút ≥ {MAX_HOLD_MINUTES} phút mà chưa chạm TP/SL.\n"
                f"Đóng thành công {close_result['closed']}/{close_result['total']} lệnh.",
            )
    except Exception as e:
        logger.warning(f"[AI v6] Lỗi gửi Telegram khi đóng nhóm theo timeout: {e}")

    return True


def _heartbeat(symbol: str, last_closed_m1, existing_positions: list) -> None:
    """Log XÁC NHẬN vòng lặp vẫn đang chạy + đang xử lý đúng nến, ngay cả khi không có gì
    đáng báo cáo ở các bước phía trên (phân biệt "đang quét bình thường" với "bị treo")."""
    if existing_positions:
        direction = group_mgr.get_group_direction(existing_positions)
        avg_entry = group_mgr.calc_group_average_entry(existing_positions)
        status = f"Nhóm DCA {direction}: {len(existing_positions)}/{MAX_DCA_POSITIONS} lệnh, Entry TB={avg_entry:.2f}"
    else:
        status = "Chưa có nhóm DCA nào mở, đang tìm tín hiệu vào lệnh gốc"
    logger.info(f"[HEARTBEAT] {symbol} | Nến M1 gần nhất đã xử lý: {last_closed_m1} | {status}")


def run_once(predictor: AIPredictor) -> None:
    global _cycle_count
    _cycle_count += 1
    do_heartbeat = (_cycle_count % HEARTBEAT_EVERY_N_CYCLES == 0)

    for symbol in SYMBOLS:
        try:
            if not telegram_commander.is_symbol_enabled(symbol):
                if do_heartbeat:
                    logger.info(f"[HEARTBEAT] {symbol} | Auto Trade đang TẮT (dùng /start trên Telegram để bật lại).")
                continue

            last_closed_m1 = mt5_client.get_last_closed_time(symbol, TF_ENTRY)
            if last_closed_m1 is None:
                logger.warning(f"[{symbol}] Không lấy được thời gian nến M1 gần nhất từ MT5 — "
                               f"kiểm tra kết nối/symbol có đúng tên không (vd tài khoản cent cần hậu tố 'c').")
                continue

            is_new_candle = _last_processed_m1_time.get(symbol) != last_closed_m1
            if is_new_candle:
                _last_processed_m1_time[symbol] = last_closed_m1

            existing_positions = group_mgr.get_group_positions(symbol)

            # Chống FOMO đuổi giá: phát hiện nhóm VỪA đóng "tự nhiên" (TP/SL do MT5 tự khớp
            # giữa 2 chu kỳ quét, bot không chủ động đóng - khác với timeout ở dưới, vốn tự
            # ghi nhận rồi) - so sánh snapshot chu kỳ trước với hiện tại.
            prev_snapshot = _last_known_group_snapshot.get(symbol)
            if not existing_positions and prev_snapshot is not None:
                price_now = _current_price(symbol)
                if price_now is not None:
                    exit_price = _guess_exit_price(price_now, prev_snapshot["sl"], prev_snapshot["tp"])
                    _record_group_closed(symbol, prev_snapshot["direction"], exit_price)
                _last_known_group_snapshot[symbol] = None
            elif existing_positions:
                _last_known_group_snapshot[symbol] = {
                    "direction": group_mgr.get_group_direction(existing_positions),
                    "sl": existing_positions[0].sl, "tp": existing_positions[0].tp,
                }

            if do_heartbeat:
                _heartbeat(symbol, last_closed_m1, existing_positions)

            # Kiểm tra chốt lệnh theo thời gian MỖI CHU KỲ (không chỉ khi có nến M1 mới), vì
            # giới hạn thời gian có thể tới bất cứ lúc nào giữa 2 lần đóng nến.
            if _check_and_close_timed_out_group(symbol, existing_positions):
                continue

            if not is_new_candle:
                continue  # Chưa có nến M1 mới đóng, chờ chu kỳ sau

            if not existing_positions:
                _try_open_initial_group(symbol, predictor)
            else:
                _try_add_dca(symbol, predictor, existing_positions)

        except Exception as e:
            logger.error(f"[AI v6] Lỗi khi xử lý {symbol}: {e}", exc_info=True)


def main():
    log_file = os.path.join(LOGS_DIR, "ai_v6_live.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()],
    )

    logger.info("=" * 70)
    logger.info("=== AI v6 LIVE TRADER (DCA 1 chiều kiểu SCALPING, XAUUSD, M15/M5/M1) ===")
    logger.info("=" * 70)

    if not mt5_connector.init():
        logger.error("❌ Không thể kết nối MT5. Dừng chương trình.")
        return

    predictor = AIPredictor()
    if predictor.model is None:
        logger.error("❌ Chưa có model AI v6 (ai_v6/models/latest_model.pkl). "
                     "Hãy chạy build_train_v6_scalping.py trước khi khởi động Live Trader.")
        mt5_connector.shutdown()
        return

    if TELEGRAM_AI_TOKEN and TELEGRAM_AI_CHAT_ID:
        telegram_commander.start(TELEGRAM_AI_TOKEN, TELEGRAM_AI_CHAT_ID, predictor=predictor)
        logger.info("✅ AI v6 TelegramCommander đã khởi động.")
        try:
            telegram_commander._send(
                TELEGRAM_AI_TOKEN, TELEGRAM_AI_CHAT_ID,
                "🟢 <b>AI v6 Live Trader đã khởi động (chế độ SCALPING)</b>\n"
                f"Symbol: <b>XAUUSD</b> (duy nhất) | M15(xu hướng)/M5(xác nhận)/M1(entry, SL/TP theo ATR M1)\n"
                f"DCA tối đa: {MAX_DCA_POSITIONS} lệnh cùng chiều | Ngưỡng ML: {PROBABILITY_THRESHOLD:.0%}\n"
                f"Chốt lệnh nếu giữ quá {MAX_HOLD_MINUTES} phút chưa chạm TP/SL\n"
                f"Giờ giao dịch: {TRADING_HOURS_START_VN}h–{TRADING_HOURS_END_VN}h VN\n"
                "<i>/help để xem danh sách lệnh.</i>",
            )
        except Exception as e:
            logger.warning(f"Gửi tin nhắn khởi động thất bại: {e}")
    else:
        logger.warning("⚠️ Chưa cấu hình AI_V6_TELEGRAM_BOT_TOKEN/CHAT_ID — bot chạy nhưng không có "
                       "kênh Telegram để theo dõi/điều khiển.")

    logger.info(f"✅ Sẵn sàng (chế độ SCALPING). Symbol=XAUUSD | Quét mỗi {SCAN_INTERVAL_SECONDS}s | "
                f"Max DCA={MAX_DCA_POSITIONS} | Trigger DCA={DCA_TRIGGER_ATR_MULTIPLE}×ATR(M1) | "
                f"Max giữ lệnh={MAX_HOLD_MINUTES} phút | Chống FOMO: cooldown "
                f"{POST_CLOSE_SAME_DIRECTION_COOLDOWN_MINUTES}′/chase-guard tới {CHASE_GUARD_MAX_AGE_MINUTES}′ | "
                f"Giờ giao dịch={TRADING_HOURS_START_VN}h-{TRADING_HOURS_END_VN}h VN | "
                f"Heartbeat mỗi {HEARTBEAT_EVERY_N_CYCLES * SCAN_INTERVAL_SECONDS}s")

    sync_counter = 0
    try:
        while True:
            run_once(predictor)
            sync_counter += 1
            if sync_counter % 60 == 0:  # Đồng bộ kết quả lệnh đã đóng định kỳ
                trade_logger.sync_closed_trades()
            time.sleep(SCAN_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        logger.info("Dừng AI v6 Live Trader theo yêu cầu người dùng.")
    finally:
        mt5_connector.shutdown()


if __name__ == "__main__":
    main()