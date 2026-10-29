Mình đang phát triển bot forex tự động giao dịch trên MT5, cần bạn tiếp tục hỗ trợ từ trạng thái hiện tại. Đây là tóm tắt đầy đủ bối cảnh:

## Bối cảnh chung
- Có **2 bot hoàn toàn độc lập**:
  - **Bot CŨ** (pattern nến: hammer, engulfing, double top...): chạy trên VPS, thư mục `mt5-watcher`, MT5 account riêng, Telegram bot riêng ("trading_bot").
  - **Bot MỚI** (chủ đề chính của cuộc trò chuyện này): tên `bot_xutho4`, chạy **song song ở cả laptop và VPS** (cùng 1 bộ code, copy tay giữa 2 nơi), MT5 account riêng, Telegram bot riêng ("Forex Signal Bot"). `MAGIC_NUMBER = 20260702` (khác với bot cũ `20260622`).
- Bot mới dựa trên 1 indicator TradingView tên "XuTho v4" (Pine Script), gồm 4 nhóm tín hiệu độc lập:
  1. SuperTrend + K-Means volatility clustering (đổi chiều)
  2. EMA 9/21 cross
  3. Price Action/Dow Theory (volume-confirmed uptrend/downtrend)
  4. Smart Money Concepts — BOS/CHoCH (phá cấu trúc), Order Block, Fair Value Gap

## Kiến trúc hiện tại (v9.x) — QUAN TRỌNG
- **`analysis.py`**: dùng **OR-logic** — bất kỳ 1 trong 5 loại pattern sau xuất hiện là vào lệnh ngay, KHÔNG cần các nhóm khác xác nhận chéo (đã thử kiến trúc AND/xác nhận chéo trước đó nhưng quá chặt, gần như không ra tín hiệu — đã bỏ):
  - `smc_bullish_bos` / `smc_bearish_bos` / `smc_bullish_choch` / `smc_bearish_choch`
  - `st_flip_bullish` / `st_flip_bearish`
  - `ema_cross_bullish` / `ema_cross_bearish`
  - `price_action_bullish` / `price_action_bearish`
- **`smc_indicator.py`**: chứa toàn bộ hàm tính chỉ báo (ATR, EMA, K-Means, SuperTrend, BOS/CHoCH, Order Block, FVG, Price Action).
- **`trader.py`**: tính SL/TP **độc lập** theo ATR riêng (`atr_multiplier` cho SL, `tp_atr_multiplier` cho TP — KHÔNG còn dùng `rr_ratio` cố định như trước). Có thêm:
  - `max_sl_atr_mult` (giới hạn SL không bị zone_price kéo giãn quá xa so với ATR thuần).
  - `TP_BUFFER_PERCENT` (sàn tối thiểu % cho TP, tránh TP co quá bé lúc ATR nhỏ — tương tự `SL_BUFFER_PERCENT` đã có cho SL).
  - **FOMO guard**: chặn tín hiệu nếu giá đã chạy quá `fomo_guard_atr_mult` (mặc định 0.5x ATR) so với giá đóng lệnh CÙNG CHIỀU gần nhất — tránh đuổi giá.
  - **Đảo lệnh**: nếu đã đủ `MAX_OPEN_TRADES_PER_SYMBOL` (=1) và có tín hiệu mới NGƯỢC CHIỀU với lệnh đang mở VÀ lệnh đang mở đang LỖ → tự đóng lệnh cũ, mở lệnh mới (`config.ALLOW_REVERSE_ON_LOSS`).
- **`notifier.py`**: gửi Telegram **100% offline, không dùng AI/Gemini/Vercel** — SL/TP hiển thị lấy trực tiếp từ `trader._calc_sl_tp()` (số thật), mô tả bằng template cố định. Có vẽ chart qua QuickChart.io (không cần API key).
- **`market_regime.py`**: tất cả pattern đều thuộc nhóm UNIVERSAL (không bị chặn theo trending/ranging nữa), chỉ chặn khi regime=VOLATILE thật sự.
- **`auto_tuner.py`**: WFO (Walk-Forward Optimization), chạy tự động **mỗi ngày lúc 2h sáng giờ VN** (`config.AUTO_TUNER_SCHEDULED_HOUR_VN = 2`). Tối ưu: `atr_multiplier`, `tp_atr_multiplier`, `internal_structure_len`, `st_factor`, `ema_fast_len`, `pa_length` (per-symbol grid riêng cho XAUUSD/EURUSD/GBPUSD). Fine-tune dùng coordinate-wise local search (KHÔNG dùng Cartesian product — từng gây bug nổ combo lên 275,625, đã sửa còn ~30-40 combo).
- **`param_loader.py`**: đọc `optimized_params.json` (tự sinh bởi auto_tuner), fallback về default = đúng giá trị gốc indicator TradingView.
- **`config.py`**: `SYMBOLS = ["XAUUSD", "EURUSD", "GBPUSD"]` (USDJPY đã loại bỏ do quá ít lệnh khi backtest). Có `DISABLED_SYMBOLS` (set runtime, KHÔNG lưu file — mất khi restart) để bật/tắt symbol qua Telegram.
- **`telegram_commander.py`**: lệnh `/start /stop /status /params /tune /disable SYMBOL /enable SYMBOL /help`.
- **`quick_check.py`**: backtest nhanh (không tối ưu) để đếm tần suất tín hiệu/lệnh trước khi chạy WFO đầy đủ.
- **`check_params.py`**: script đối chiếu tham số đang dùng vs default gốc indicator.

## Các bug quan trọng đã sửa (theo thứ tự phát hiện)
1. Race condition `auto_tuner` ghi đè tham số dùng chung với thread live → sửa bằng `threading.local()`.
2. Logic OB/FVG proximity kiểm tra ngay tại nến break (luôn fail vì giá đã chạy xa khỏi chính OB đó) → đổi sang chờ retest, rồi sau đó **bỏ hẳn yêu cầu retest** khi chuyển sang OR-logic.
3. `trader.py` hardcode `config.DEFAULT_RR_RATIO=2.0`, không đọc `rr_ratio`/`tp_atr_multiplier` tối ưu riêng từng symbol từ `param_loader` → đã sửa đọc động.
4. SL bị `zone_price`/đỉnh-đáy kéo giãn xa hơn ATR nhiều, trong khi TP (sau khi tách độc lập) không giãn theo → RR thực tế lệch xa danh nghĩa (từng thấy GBPUSD RR=1:0.56) → thêm `max_sl_atr_mult` giới hạn.
5. TP không có sàn tối thiểu như SL → lúc ATR co nhỏ (thị trường ít biến động), TP co xuống <10 pip → thêm `TP_BUFFER_PERCENT`.
6. `notifier.py` tự dedupe riêng (60 phút/pattern) trong khi `trader.py` không dedupe → có lúc lệnh vào thật nhưng Telegram im lặng bỏ qua → chuyển dedupe lên `watcher.py` dùng chung cho cả 2.
7. `trailing_stop.py` hardcode `MAGIC_NUMBER` cũ (20260622 của bot pattern-nến) thay vì 20260702 → trailing stop không bao giờ áp dụng được → sửa import trực tiếp từ `trader.py`.
8. Lỗi `certifi` (SSL) trên VPS làm hỏng Telegram Commander (và có thể cả `notifier.py`) → thêm fallback SSL context rộng hơn (bắt mọi Exception, không chỉ ImportError) + khuyến nghị `pip install --upgrade --force-reinstall certifi`.
9. Nhiều lý do bot bỏ qua lệnh (FOMO guard, spread rộng...) chỉ hiện trong tin nhắn Telegram, KHÔNG ghi vào `watcher.log` → đã sửa ghi log đầy đủ.

## Trạng thái hiện tại (10/07/2026)
Tham số tối ưu mới nhất (`optimized_params.json`):
- **XAUUSD**: ATR(14)×1.60, TP_x1.60, struct=8, st_factor=2.50, ema_fast=7, pa_len=12 — WR=54.1%, PF=1.08 ✅ có lãi
- **EURUSD**: ATR(14)×1.40, TP_x2.00, struct=6, st_factor=2.00, ema_fast=9, pa_len=14 — WR=46.7%, PF=0.94 ⚠️ lỗ nhẹ dù WR cao hơn breakeven — đang theo dõi thêm, CHƯA loại khỏi live
- **GBPUSD**: ATR(14)×1.60, TP_x2.00, struct=5, st_factor=3.80, ema_fast=8, pa_len=14 — WR=51.1%, PF=1.05 ✅ có lãi (đã phục hồi tốt so với trước)

## Việc còn để ngỏ / có thể cần làm tiếp
- Theo dõi PF của EURUSD sau vài lần auto-tune (2h sáng mỗi ngày) xem cải thiện hay xấu đi.
- Cân nhắc thêm `fomo_guard_atr_mult` vào grid tối ưu của `auto_tuner.py` (hiện đang cố định 0.5 cho mọi symbol).
- Có thể viết script đọc `trades.db` để so sánh RR *thực tế* đã đạt được vs RR danh nghĩa từ `optimized_params.json`, làm rõ nguyên nhân PF thấp hơn kỳ vọng của EURUSD.
- Còn 2 file mình chưa từng xem qua: `trend_filter.py`, `adaptive_filter.py` (dùng để lọc tín hiệu theo xu hướng HTF và điểm số) — nếu sau này bot có hành vi lạ liên quan đến việc lọc HTF/điểm số, có thể cần xin lại 2 file này để kiểm tra.

Nếu bạn cần code cụ thể của file nào trong số trên, mình sẽ gửi lại khi được yêu cầu.
