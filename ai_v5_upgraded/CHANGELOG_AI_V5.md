# CHANGELOG — Nâng cấp ai_v5 (giai đoạn 2)

Cập nhật: 18/07/2026 (bản 2 — sau khi xem log chạy thật trên VPS).
Cách áp dụng: giải nén, ghi đè thư mục `ai_v5/` và file `watcher.py` vào
`C:\Users\Administrator\Desktop\forexai\bot_xutho4\` (VPS) hoặc
`C:\Users\Admin\forexai\bot_xutho4\` (laptop). Các thư mục dữ liệu sinh ra
(`ai_v5/datasets`, `ai_v5/models`, `ai_v5/cache`, `ai_v5/logs`) đã được dọn
rỗng trong gói này — chạy lại pipeline sẽ tự tạo mới.

## ⚠️ ĐỌC TRƯỚC KHI DEPLOY LÊN VPS ĐANG CHẠY LIVE

1. **Dừng `watcher.py` trước khi ghi đè file** (tránh đọc phải file `.py`
   đang bị ghi dở giữa chừng, gây lỗi cú pháp tạm thời).
2. **Backup toàn bộ `ai_v5/` và `watcher.py` hiện tại trên VPS** trước khi
   ghi đè. Lý do: qua log bạn gửi, mình xác nhận code đang chạy thật trên VPS
   đã **lệch nhánh** so với bản trong file `.7z` bạn gửi mình đọc ban đầu —
   cụ thể `swing_detector.py` trên VPS không bị lỗi dán nhầm nội dung như bản
   mình nhận, tức là đã có chỉnh sửa tay ở VPS mà mình không biết hết. Backup
   để có đường lùi.
3. Sau khi ghi đè, chạy lại `run_init_train.py` — model giờ sẽ lưu tại
   `ai_v5/models/latest_model.pkl` (KHÔNG còn là `lgbm_v5_hybrid.pkl` như
   trước).
4. Khởi động lại `watcher.py`.

## 1. Sửa lỗi nền tảng (chặn đường chạy)

- **`config_ai.py`**: viết lại hoàn toàn. Thêm các biến còn thiếu mà nơi khác
  cần: `BASE_DIR`, `LOGS_FILE`, `PROBABILITY_THRESHOLD`, `TELEGRAM_AI_TOKEN`,
  `TELEGRAM_AI_CHAT_ID`, `HISTORICAL_DATA_SOURCE`, `BT_CACHE_DIR`.
  **Token Telegram giờ đọc từ biến môi trường** `AI_V5_TELEGRAM_BOT_TOKEN` /
  `AI_V5_TELEGRAM_CHAT_ID` thay vì hardcode trong code (token cũ đã lộ ra
  trong quá trình mình đọc file — khuyến nghị thu hồi token đó qua BotFather).
- **`pipeline/swing_detector.py`**: trong bản file bạn gửi lần đầu, file này
  bị dán nhầm = bản sao y hệt `build_dataset.py`, không hề có hàm
  `find_swing_points`. Đã viết lại đúng logic fractal Đỉnh/Đáy
  (`left_bars`/`right_bars`). *(Lưu ý: log VPS bạn gửi cho thấy bản swing_detector
  trên VPS thực tế KHÔNG bị lỗi này — có thể VPS đã có bản khác/được sửa tay
  trước đó. Vẫn nên ghi đè bằng bản đã kiểm chứng này để đồng bộ 1 nguồn duy nhất.)*
- **`ml/predictor.py`**: thêm 2 method còn thiếu mà `shadow_runner.py` gọi:
  `predict_probability()` (alias của `predict_signal()`) và
  `save_shadow_log_to_db()` — ghi log quyết định Shadow vào
  `ai_v5/cache/shadow_log.db` để sau này đối chiếu với `trades.db` thật.
- **2 file `telegram_ai.py` trùng tên khác chữ ký hàm** (`ai_v5/telegram_ai.py`
  và `ai_v5/telegram/telegram_ai.py`) → đã hợp nhất về **1 bản duy nhất**
  trong `ai_v5/telegram/telegram_ai.py`, sửa `shadow_runner.py` gọi đúng chữ
  ký, xoá file trùng. Sửa luôn lỗi gõ `response.status_size` → `response.status_code`.
- **`watcher.py`**: khối "V5 SHADOW" bị lỗi `numpy` chưa import, gọi
  `detect_16_patterns()` sai kiểu (`dict` thay vì `float` giá hiện tại), và
  dùng `analysis.find_swings`/`analysis.calculate_volume_ratio` — 2 hàm không
  tồn tại → luôn trả về danh sách swings rỗng, không bao giờ bắn tín hiệu. Đã
  sửa dùng đúng `find_swing_points` thật, đúng kiểu tham số, và model được nạp
  qua `ModelManager` (đồng bộ với `predictor.py`).

## 2. Hợp nhất kiến trúc — 1 schema đặc trưng dùng chung cho cả 2 nguồn

Trước đây có 2 pipeline độc lập, không tương thích nhau:
- **Cách A**: chấm điểm tín hiệu sống của v4 (SMC/SuperTrend/EMA/PriceAction),
  học từ `trades.db`.
- **Cách B**: quét 16 mẫu hình nến cổ điển trực tiếp từ lịch sử MT5.

`ai_v5/data/feature_schema.py` giờ định nghĩa **1 bộ cột chung**
(`FEATURE_COLUMNS`) mà cả 2 nguồn đều xuất ra, phân biệt bởi cột
`source_type_encoded` (0 = V4_SIGNAL, 1 = GEOMETRIC_PATTERN), cột nhãn thống
nhất là `is_win`. Bảng mã hoá pattern (`PATTERN_ENCODING`) gộp chung tên cả
10 pattern của v4 lẫn 16 mẫu hình cổ điển. Nhờ vậy **1 model LightGBM duy
nhất** có thể học từ cả 2 nguồn cùng lúc.

- `data/feature_engine.py` (trích đặc trưng cho Cách A) → cập nhật dùng
  schema chung, tự gắn `source_type_encoded=V4_SIGNAL`.
- `pipeline/build_dataset.py` (Cách B) → viết lại hoàn toàn, xuất ra đúng
  schema chung, `source_type_encoded=GEOMETRIC_PATTERN`.
- `pipeline/train_pipeline.py` → viết lại (xem mục 6 bên dưới, sửa lỗi crash).
- `data/data_loader.py` → thêm `DataLoader.combine_all_datasets()` gộp **mọi**
  file `dataset_*.csv` (cả 2 nguồn) thành 1 tập train.
- `ml/ml_trainer.py` → mặc định train trên tập đã gộp (`use_combined=True`)
  thay vì chỉ lấy file dataset mới nhất.

## 3. `build_dataset.py` giờ chạy được 2 nguồn dữ liệu

```bash
# Dùng CSV cache có sẵn (bt_cache/) — không cần MT5, chạy được ở bất kỳ máy nào:
python -m ai_v5.pipeline.build_dataset --source csv --days 260

# Dùng MT5 sống — CHỈ chạy trên Windows đang mở terminal MT5:
python -m ai_v5.pipeline.build_dataset --source mt5 --days 365
```
Mặc định đọc theo `config_ai.HISTORICAL_DATA_SOURCE` (env `AI_V5_DATA_SOURCE`,
mặc định `"csv"`). `run_init_train.py` gọi `generate_historical_dataset()`
không truyền `source` → sẽ tự dùng biến môi trường này; nếu chạy trên VPS có
MT5, set `AI_V5_DATA_SOURCE=mt5` hoặc để nguyên vì code sẽ tự thử nạp MT5 khi
gọi trực tiếp qua `run_init_train.py` như log bạn gửi cho thấy đã hoạt động.

## 4. Đã kiểm chứng chạy thật (trên bt_cache XAUUSD/EURUSD/GBPUSD M15, 260 ngày)

```
python -m ai_v5.pipeline.build_dataset --source csv --days 260
→ 2434 mẫu hình học (13/16 mẫu hình xuất hiện trong dữ liệu này)

python -m ai_v5.ml.ml_trainer
→ Accuracy 78.6% | Precision 84.1% | Recall 75.3% | F1 79.4%
→ Lưu model: ai_v5/models/latest_model.pkl

python -m ai_v5.ml.predictor    → chạy OK, dự đoán 80.0%
python -m ai_v5.ml.explain      → chạy OK, feature importance hợp lý
shadow_runner.inspect_signal_shadow() với tín hiệu SMC giả lập → chạy OK,
  không crash, ghi log vào shadow_log.db thành công.
python -m ai_v5.bootstrap       → chạy OK, ghi log đúng file ai_v5.log
python -m ai_v5.ml.auto_tuner_ml → chạy OK, tìm được bộ tham số tối ưu
python -m ai_v5.ml.ai_learner   → chạy OK, tự bỏ qua vì trades.db < 20 lệnh
```

⚠️ **Lưu ý về con số 78.6% Accuracy**: đây là kết quả trên tập test tách từ
CHÍNH tập train (train_test_split ngẫu nhiên, không phải walk-forward/out-of-
sample theo thời gian), và nhãn Thắng/Thua được suy từ SL/TP *lý thuyết* của
từng mẫu hình (không phải SL/TP thật đã tối ưu). Con số này chỉ nói lên "code
chạy đúng, pipeline không hỏng" — **chưa nói lên model này có lãi thật khi
live**. Trước khi tin dùng, nên: (1) walk-forward validation theo thời gian
(đã có khung sẵn ở `pipeline/walk_forward.py`, hiện là bản giả lập — cần
triển khai logic thật), (2) chạy Shadow Mode song song một thời gian rồi so
sánh qua `reports/dashboard.py`.

## 5. Vấn đề thiết kế còn tồn (không crash, nhưng vô hiệu hoá tính năng)

- **`ml/ai_learner.py`** đọc thẳng bảng `trades` thô (cột `ticket`,
  `entry_price`...) làm dữ liệu tham chiếu cho `DataDriftDetector`, nhưng
  `DataDriftDetector` lại so sánh theo cột đặc trưng đã trích xuất
  (`rsi_14`, `atr_value`...). Vì 2 bên không cùng tên cột, Drift sẽ **không
  bao giờ được phát hiện** dù dữ liệu có lệch thật. Chưa sửa vì `trades.db`
  hiện đang rỗng (0 lệnh) nên chưa ảnh hưởng — nhưng cần sửa trước khi
  `trades.db` có đủ dữ liệu và bạn muốn tính năng auto re-train hoạt động
  thật. Cách sửa: trong `_fetch_historical_reference_data()`, chạy từng dòng
  của `trades.db` qua `feature_engine.py` để trích đặc trưng, thay vì dùng
  thẳng cột thô.

## 6. Bản vá bổ sung (sau khi xem log chạy thật trên VPS bạn gửi)

Log bạn gửi cho thấy `run_init_train.py` chạy **thành công** trên VPS bằng
**code cũ** (trước bản cập nhật này) — dùng schema cũ (`source_type`,
`pattern`, `regime_type` dạng text) và lưu tại
`ai_v5/models/lgbm_v5_hybrid.pkl`. Điều này xác nhận: bản code đang chạy thật
trên VPS đã lệch nhánh so với bản file bạn gửi mình đọc ban đầu.

Khi rà soát lại toàn bộ gói trước khi gửi bạn lần 2, mình phát hiện và đã sửa
thêm 1 lỗi **sẽ crash ngay nếu bạn deploy bản cập nhật này rồi chạy lại
`run_init_train.py` mà chưa có bản vá này**:

- **`pipeline/train_pipeline.py`** (file cũ, chưa được đồng bộ ở bản gửi lần
  1): hàm `execute_train_pipeline()` tìm cột `df["target"]`, nhưng dataset
  mới do `build_dataset.py` đã hợp nhất sinh ra dùng tên cột `is_win` →
  **`KeyError: 'target'`**. Mình đã mô phỏng lại đúng luồng `run_init_train.py`
  để xác nhận lỗi này xảy ra thật, sau đó viết lại toàn bộ hàm dùng chung
  schema hợp nhất và lưu model qua `ModelManager` (ra `latest_model.pkl`,
  đồng bộ với `predictor.py`/`watcher.py`) thay vì tạo file
  `lgbm_v5_hybrid.pkl` riêng lẻ như trước.
- Đã chạy lại **toàn bộ mô phỏng `run_init_train.py`** bằng code mới (build_dataset
  → 2434 mẫu → train_pipeline), xác nhận **không còn crash**.

## 7. Việc còn lại — cần bạn làm trên máy Windows (có MT5) / VPS

1. Set biến môi trường `AI_V5_TELEGRAM_BOT_TOKEN` / `AI_V5_TELEGRAM_CHAT_ID`
   cho bot Telegram riêng của AI v5 (khuyến nghị **tạo token mới**, không
   dùng lại token cũ đã lộ).
2. Khi `trades.db` của bot v4 bắt đầu có lệnh đóng thật (hiện đang 0 dòng),
   chạy `python -m ai_v5.data.dataset_builder` để sinh thêm dataset nguồn
   V4_SIGNAL, sau đó `ml_trainer.py` sẽ tự gộp cả 2 nguồn khi train lại.
3. Sửa `ai_learner.py` theo mục 5 ở trên trước khi dựa vào tính năng
   auto re-train theo Drift.
4. Triển khai logic thật cho `pipeline/walk_forward.py` (hiện là bản giả
   lập) trước khi tin tưởng số liệu backtest.
