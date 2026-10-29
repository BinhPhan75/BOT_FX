# bot_xutho4/ai_v5/data/feature_store.py
import os
import json
import logging
from datetime import datetime
from ai_v5.config_ai import CACHE_DIR
from ai_v5.data.feature_schema import validate_features

logger = logging.getLogger("ai_feature_store")

class FeatureStore:
    """
    Feature Store quản lý việc lưu trữ, truy xuất và đệm dữ liệu đặc trưng (Features).
    Hỗ trợ Shadow Runner lấy nhanh đặc trưng mà không cần tính toán lại từ đầu.
    """
    def __init__(self, store_dir: str = CACHE_DIR):
        self.store_dir = os.path.abspath(store_dir)
        if not os.path.exists(self.store_dir):
            os.makedirs(self.store_dir)
            logger.info(f"Đã tạo thư mục lưu trữ cache đặc trưng: {self.store_dir}")

    def _get_feature_path(self, ticket: int) -> str:
        """Đường dẫn lưu trữ file đặc trưng của một lệnh cụ thể theo mã Ticket"""
        return os.path.join(self.store_dir, f"features_trade_{ticket}.json")

    def save_features(self, ticket: int, features: dict) -> bool:
        """
        Lưu trữ đặc trưng đã trích xuất của một lệnh vào bộ nhớ đệm (Cache) dưới dạng JSON.
        """
        try:
            # Metadata bổ sung để dễ quản lý và debug sau này
            data_to_store = {
                "ticket": ticket,
                "timestamp_created": datetime.now().isoformat(),
                "features": features
            }
            file_path = self._get_feature_path(ticket)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data_to_store, f, indent=4, ensure_ascii=False)
            logger.debug(f"Đã lưu đặc trưng của trade {ticket} vào Feature Store.")
            return True
        except Exception as e:
            logger.error(f"Lỗi khi lưu đặc trưng vào Feature Store cho trade {ticket}: {str(e)}")
            return False

    def get_features(self, ticket: int) -> dict:
        """
        Lấy lại các đặc trưng đã lưu của một trade dựa vào Ticket.
        Trả về None nếu không tồn tại hoặc file bị lỗi cấu trúc.
        """
        file_path = self._get_feature_path(ticket)
        if not os.path.exists(file_path):
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                stored_data = json.load(f)
            return stored_data.get("features", {})
        except Exception as e:
            logger.error(f"Lỗi khi đọc đặc trưng từ Feature Store cho trade {ticket}: {str(e)}")
            return None

    def clean_expired_cache(self, days_to_keep: int = 7):
        """
        Dọn dẹp các file cache đặc trưng đã cũ quá số ngày quy định để giải phóng dung lượng ổ cứng.
        """
        try:
            now = datetime.now()
            count = 0
            for filename in os.listdir(self.store_dir):
                if filename.startswith("features_trade_") and filename.endswith(".json"):
                    file_path = os.path.join(self.store_dir, filename)
                    file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                    if (now - file_time).days > days_to_keep:
                        os.remove(file_path)
                        count += 1
            if count > 0:
                logger.info(f"Đã dọn dẹp thành công {count} file cache đặc trưng cũ hơn {days_to_keep} ngày.")
        except Exception as e:
            logger.error(f"Gặp lỗi khi dọn dẹp cache của Feature Store: {str(e)}")


if __name__ == "__main__":
    # Test thử hoạt động của Feature Store độc lập
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("\n🔍 Đang chạy thử nghiệm thực tế Feature Store...")
    
    store = FeatureStore()
    
    # Giả lập đặc trưng trích xuất được
    test_ticket = 999999
    sample_features = {
        "rsi_14": 55.4,
        "volume_ratio": 1.2,
        "atr_value": 1.5,
        "distance_to_zone_pct": 0.08,
        "pattern_encoded": 1,
        "hour_of_day": 14,
        "day_of_week": 4
    }
    
    # 1. Test lưu
    if store.save_features(test_ticket, sample_features):
        print(f"✅ Thành công: Đã lưu đặc trưng cho test ticket {test_ticket}")
        
    # 2. Test đọc
    retrieved = store.get_features(test_ticket)
    if retrieved and retrieved["rsi_14"] == 55.4:
        print("✅ Thành công: Đã đọc chính xác đặc trưng từ Feature Store!")
    else:
        print("❌ Lỗi: Không lấy được đặc trưng chính xác.")
        
    # 3. Dọn dẹp môi trường test
    file_to_clean = store._get_feature_path(test_ticket)
    if os.path.exists(file_to_clean):
        os.remove(file_to_clean)