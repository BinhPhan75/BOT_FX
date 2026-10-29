# ai_v5/storage/model_registry.py
import os
import shutil
import glob
import logging

logger = logging.getLogger("watcher.ai_learner")

class ModelRegistry:
    def __init__(self, registry_dir="ai_v5/models"):
        self.registry_dir = registry_dir
        os.makedirs(self.registry_dir, exist_ok=True)
        self.latest_link = os.path.join(self.registry_dir, "latest_model.pkl")

    def register_model(self, source_path: str, metrics: dict) -> str:
        """Đăng ký mô hình mới kèm theo các chỉ số hiệu suất."""
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        pf = metrics.get("profit_factor", 0.0)
        
        # Đặt tên file lưu vết tường minh kèm hiệu suất tài chính
        filename = f"model_{timestamp}_pf_{pf:.2f}.pkl"
        dest_path = os.path.join(self.registry_dir, filename)
        
        shutil.copy(source_path, dest_path)
        logger.info(f"💾 Đã đăng ký mô hình mới vào Registry: {filename}")
        
        # Cập nhật liên kết mô hình mới nhất (latest)
        if os.path.exists(self.latest_link):
            if os.path.islink(self.latest_link) or os.path.isfile(self.latest_link):
                os.remove(self.latest_link)
        
        shutil.copy(dest_path, self.latest_link)
        return dest_path

    def rollback_to_previous(self) -> bool:
        """Hạ cấp (Rollback) về mô hình tốt nhất trước đó nếu mô hình hiện tại gặp sự cố."""
        all_models = glob.glob(os.path.join(self.registry_dir, "model_*.pkl"))
        if len(all_models) < 2:
            logger.warning("⚠️ Không tìm thấy phiên bản mô hình cũ hơn để Rollback.")
            return False
        
        # Sắp xếp theo thời gian khởi tạo (mô hình gần nhất đứng cuối)
        all_models.sort(key=os.path.getmtime)
        previous_model = all_models[-2] # Lấy mô hình sát gần nhất trước bản lỗi
        
        if os.path.exists(self.latest_link):
            os.remove(self.latest_link)
        shutil.copy(previous_model, self.latest_link)
        logger.critical(f"🚨 ĐÃ ROLLBACK MÔ HÌNH THÀNH CÔNG VỀ PHIÊN BẢN: {os.path.basename(previous_model)}")
        return True