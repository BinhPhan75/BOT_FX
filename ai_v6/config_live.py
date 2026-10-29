# ai_v6/config_live.py
"""
Cau hinh rieng cho ai_v6 - chien luoc DCA 1 CHIEU tren XAUUSD, phan tich
da khung: M15 (xu huong lon) + M5 (xac nhan pattern/vung) + M1 (diem vao
va thoi diem kich hoat DCA).

TACH BACH HOAN TOAN voi v4 va ai_v5: MAGIC_NUMBER rieng, DB rieng
(ai_v6_trades.db), Telegram bot rieng (AI_V6_TELEGRAM_*), khong doc/ghi
file cau hinh cua ai_v5.

Phuong phap phan tich ky thuat (7 nhom pattern: 16 mau hinh hinh hoc,
Harmonic, Candlestick, Divergence RSI/MACD, VSA, ICT/SMC, Continuation) VA
model LightGBM GIU NGUYEN tu ai_v5 - ai_v6 IMPORT TRUC TIEP
ai_v5.pipeline.* / ai_v5.ml.* (khong copy/sua logic detect pattern). Diem
khac biet DUY NHAT la CACH DUNG cac tin hieu do: khung thoi gian quet, so
luong lenh toi da, va co che DCA/quan ly SL-TP theo nhom.
"""
import os

# --- Ket noi MT5 rieng cho ai_v6 (mac dinh: tu dung terminal dang mo san,
# giong ai_v5 - chi khai bao 4 bien duoi day NEU can ep dung 1 terminal cu the) ---
AI_V6_MT5_TERMINAL_PATH = os.environ.get("AI_V6_MT5_TERMINAL_PATH")
AI_V6_MT5_LOGIN = os.environ.get("AI_V6_MT5_LOGIN")
AI_V6_MT5_PASSWORD = os.environ.get("AI_V6_MT5_PASSWORD")
AI_V6_MT5_SERVER = os.environ.get("AI_V6_MT5_SERVER")

# --- Symbol / khung thoi gian ---
# CHI GIAO DICH XAUUSD (khac ai_v5 dang chay ca XAUUSD/EURUSD/GBPUSD).
# Neu tai khoan la tai khoan cent, doi thanh "XAUUSDc" (CHU HOA/THUONG phai
# khop chinh xac ten symbol tren sang - xem canh bao muc 6.1 trong README_HANDOFF_1.md gac).
SYMBOLS = ["XAUUSD"]

TF_TREND = "M15"     # Xac dinh XU HUONG LON (bias BUY/SELL) cho ca nhom DCA
TF_CONFIRM = "M5"    # Xac nhan vung/pattern - dung LAI 7 nhom detector cua ai_v5.pipeline
TF_ENTRY = "M1"      # Diem vao chinh xac hon + thoi diem kich hoat DCA (KHONG chay pattern detector rieng tren M1)

# Nguong ADX RIENG cua ai_v6 de xac dinh M15 co "du xu huong" hay khong (tach biet hoan
# toan voi nguong dung chung config.ADX_TRENDING_THRESHOLD cua v4/ai_v5, mac dinh 25 cho
# XAUUSD - nguong do duoc hieu chinh cho muc dich KHAC: loc pattern nao hop CHE DO thi
# truong, khong phai de quyet dinh "co nen mo nhom DCA moi hay khong").
#
# BẢN VÁ (28/08 - phản hồi thực tế "khó vào lệnh, không phù hợp scalping"): toàn bộ log quan
# sát được từ trước đến giờ, ADX(M15) của XAUUSD CHƯA BAO GIỜ vượt 18 (dao động thực tế quanh
# 11-15) - ngưỡng 18 ban đầu (chọn tạm, chưa backtest) đang khóa gần như toàn bộ thời gian một
# cách không chủ ý, mâu thuẫn với mục tiêu tần suất cao của scalping. HẠ xuống 12 để khớp với
# hành vi ADX thực tế quan sát được, vẫn giữ được việc lọc bỏ các giai đoạn PHẲNG LẶNG THẬT SỰ
# (ADX < 12). GIÁ TRỊ VẪN LÀ TẠM THỜI - nên đưa vào backtest_v6_scalping.py để dò chính xác
# (script đã hỗ trợ sẵn qua adx_threshold_override trong get_m15_trend_bias()).
M15_ADX_TREND_THRESHOLD = 12

SCAN_INTERVAL_SECONDS = 10          # Quet thuong xuyen hon ai_v5 (30s) vi entry/DCA can theo doi tung nen M1
CANDLES_LOOKBACK_TREND = 300        # So nen M15 tai ve moi lan quet (du cho regime/ADX)
CANDLES_LOOKBACK_CONFIRM = 300      # So nen M5 tai ve (du cho swing/ATR/RSI/MACD - giong CANDLES_LOOKBACK cua ai_v5)
CANDLES_LOOKBACK_ENTRY = 100        # So nen M1 tai ve (chi can it, dung de xac nhan thoi diem)

# --- Quan ly lenh / rui ro ---
MAGIC_NUMBER = 20260810             # RIENG BIET voi v4 (20260702) va ai_v5 (20260720)

FIXED_LOT = {"XAUUSD": 0.01}        # 0.01 lot/lenh CO DINH, ap dung cho MOI lenh trong nhom DCA (goc + DCA)
FIXED_LOT_DEFAULT = 0.01

# --- DCA (Dollar-Cost Averaging) 1 CHIEU — SCALPING (thiet ke lai theo phan hoi nguoi dung 25/08) ---
MAX_DCA_POSITIONS = 2                # Toi da 3 lenh CUNG CHIEU / nhom (1 lenh goc + toi da 2 lenh DCA)

# BẢN VÁ (thiết kế lại thành SCALPING THẬT): trước đây SL/TP tính theo ATR khung M5 (biên độ
# lớn, phù hợp trend/swing hold nhiều giờ) trong khi TF_ENTRY=M1 mang tính scalp - gây ra tình
# trạng "TP xa, giá đảo chiều liên tục ở nến nhỏ nên chưa cán TP đã quay lại dính SL" (phản hồi
# thực tế kèm ảnh chụp lệnh live). Giải pháp: chuyển TOÀN BỘ cơ sở tính SL/TP/DCA sang ATR khung
# M1 (biên độ nhỏ hơn nhiều, khớp đúng bản chất "vào nhanh ra nhanh"), và dùng BỘI SỐ ATR thay vì
# số USD cố định để tự co giãn theo biến động thực tế (quan trọng vì gold hiện dao động rất mạnh).
SCALP_SL_ATR_MULTIPLE = 2          # SL = 1.2 x ATR(M1) — GIÁ TRỊ TẠM, CẦN BACKTEST RIÊNG
SCALP_REWARD_RISK_RATIO = 1.3        # TP = 1.3 x khoảng cách SL — hạ nhẹ từ 1.5 để dễ "cán" TP hơn
DCA_TRIGGER_ATR_MULTIPLE = 0.5       # Kích hoạt DCA khi giá đi ngược >= 1.0 x ATR(M1) hiện tại
                                      # (THAY THẾ DCA_TRIGGER_PRICE_DISTANCE cố định trước đây)
DCA_MIN_INTERVAL_MINUTES = 3         # RÚT NGẮN từ 15 -> 2 phút (scalping cần phản ứng nhanh)

# BẢN VÁ MỚI: chốt TOÀN BỘ nhóm nếu giữ quá lâu mà CHƯA chạm TP/SL — đặc trưng bắt buộc của
# scalping (không "ôm" lệnh vô thời hạn). Tính từ thời điểm lệnh GỐC (đầu tiên) mở.
MAX_HOLD_MINUTES = 30                # GIÁ TRỊ TẠM, CẦN BACKTEST RIÊNG

# BẢN VÁ (chống FOMO đuổi giá — phản hồi thực tế 26/08): bot vừa chốt TP 1 nhóm, giá vẫn đang
# chạy mạnh cùng chiều (đó là lý do TP vừa cán được) nên M15+M5+M1 tiếp tục đồng thuận y hệt
# hướng cũ NGAY LẬP TỨC — bot mở lại nhóm mới đúng lúc giá đã đi quá xa, không còn là điểm vào
# hợp lý (đuổi theo con sóng vừa ăn xong, thay vì đợi thiết lập mới). 2 lớp chặn, CHỈ áp dụng khi
# nhóm mới CÙNG CHIỀU với nhóm vừa đóng (đi ngược chiều là thiết lập đảo chiều mới, không phải FOMO):
#   (a) Không mở nhóm mới cùng chiều trong X phút đầu sau khi đóng (cooldown thời gian)
#   (b) Dù đã qua cooldown, vẫn chặn nếu giá đã đi xa hơn điểm đóng trước đó >= Y lần ATR(M1)
#       (đang đuổi giá, chưa có nhịp hồi)
POST_CLOSE_SAME_DIRECTION_COOLDOWN_MINUTES = 5   # GIÁ TRỊ TẠM, CẦN BACKTEST RIÊNG
CHASE_GUARD_ATR_MULTIPLE = 1.0                    # GIÁ TRỊ TẠM, CẦN BACKTEST RIÊNG
CHASE_GUARD_MAX_AGE_MINUTES = 10   # Sau mốc này, cơ chế chống FOMO TẮT HOÀN TOÀN dù giá thế nào

# --- Quan ly SL/TP THEO NHOM (khong phai theo tung lenh rieng le) ---
# Sau MOI LAN mo/them lenh trong nhom, tinh lai GIA VAO TRUNG BINH (co trong
# so theo khoi luong - dung dinh nghia DCA/breakeven chuan) cua CA NHOM, roi
# GAN CUNG 1 cap SL/TP cho TAT CA lenh dang mo trong nhom -> khi gia cham 1
# trong 2 muc, toan bo nhom dong gan nhu dong thoi.

# Chien luoc 1 CHIEU TUYET DOI - khong dao lenh, khong hedging, khac
# ALLOW_REVERSE_ON_LOSS=True cua ai_v5 (co che do KHONG phu hop voi 1 nhom
# DCA dang tich luy vi the cung huong).
ALLOW_REVERSE_ON_LOSS = False

ORDER_DEVIATION = 20
MIN_SL_POINTS_DEFAULT = 30

MAX_SPREAD_POINTS = {"XAUUSD": 200}   # Giong nguong XAUUSD cua ai_v5
MAX_SPREAD_POINTS_DEFAULT = 200

# Tran an toan khoang cach SL toi da (USD) - RONG HON ai_v5 (15.0) mot chut
# vi chien luoc DCA chap nhan gia di nguoc sau hon truoc khi nhom dong lo.
MAX_SL_DISTANCE = {"XAUUSD": 20.0}

# --- Gio giao dich (GIU NGUYEN theo yeu cau - giong ai_v5/v4) ---
TRADING_HOURS_ENABLED = True
TRADING_HOURS_START_VN = 7
TRADING_HOURS_END_VN = 23

# --- Vong phan hoi tu hoc (tuy chon) ---
# TAT MAC DINH: model v6 can tich luy du lieu M5 rieng va duoc train/kiem
# chung truoc (xem run_init_train_v6.py + README_V6.md) truoc khi bat an
# toan vong tu dong train lai - giong nguyen tac "khong danh doi chat luong
# lay tu dong mu quang" da ap dung cho auto_retrain.py cua ai_v5.
AUTO_RETRAIN_ENABLED = False
RETRAIN_CHECK_INTERVAL_SECONDS = 3600
RETRAIN_INTERVAL_DAYS = 7
MIN_NEW_TRADES_TO_RETRAIN = 10
PRECISION_DROP_TOLERANCE = 0.05
MAX_ATR_SPIKE_MULTIPLE = 2.0      # Chan neu ATR(M1) hien tai > 2.0 x ATR trung binh cua ATR_ROLLING_BASELINE_PERIOD nen gan day - GIA TRI TAM, CAN BACKTEST
ATR_ROLLING_BASELINE_PERIOD = 60  # So nen M1 dung lam "muc binh thuong" de so sanh