# bot_xutho4/ai_v5/data/data_loader.py
import os
import pandas as pd
import logging
from datetime import datetime
from ai_v5.data.feature_schema import FEATURE_COLUMNS, TARGET_COLUMN, validate_features

logger = logging.getLogger("ai_data_loader")

class DataLoader:
    """
    Bộ tải dữ liệu chuyên dụng của AI v5.
    Chịu trách nhiệm đọc các file dataset CSV, xử lý làm sạch dữ liệu (lấp đầy NaN, loại bỏ nhiễu),
    và phân tách dữ liệu thành tập Đặc trưng (X) và Nhãn mục tiêu (y).
    """
    def __init__(self, dataset_path: str):
        self.dataset_path = os.path.abspath(dataset_path)
        
    def load_and_clean_data(self) -> pd.DataFrame:
        """
        Đọc dataset từ file CSV và thực hiện làm sạch dữ liệu chuẩn hóa.
        """
        if not os.path.exists(self.dataset_path):
            logger.error(f"Không tìm thấy file dataset tại: {self.dataset_path}")
            raise FileNotFoundError(f"Dataset path not found: {self.dataset_path}")
            
        # Đọc dữ liệu
        df = pd.read_csv(self.dataset_path)
        logger.info(f"Đã nạp thành công dataset thô với {len(df)} dòng từ: {self.dataset_path}")
        
        # Kiểm tra sự tồn tại của cột nhãn mục tiêu
        if TARGET_COLUMN not in df.columns:
            raise ValueError(f"Dataset không chứa cột nhãn mục tiêu bắt buộc: '{TARGET_COLUMN}'")
            
        # Làm sạch dữ liệu: Lấp đầy các giá trị NaN/Khuyết thiếu bằng giá trị trung vị (median) hoặc 0
        for col in FEATURE_COLUMNS:
            if col in df.columns:
                if df[col].isnull().any():
                    median_val = df[col].median()
                    df[col] = df[col].fillna(median_val)
                    logger.warning(f"Cột '{col}' chứa giá trị khuyết (NaN). Đã tự động lấp đầy bằng giá trị trung vị: {median_val}")
            else:
                # Nếu thiếu hẳn cột đặc trưng trong dataset cũ, tự động điền 0
                df[col] = 0.0
                logger.warning(f"Cột đặc trưng '{col}' bị thiếu trong file CSV. Đã tự động khởi tạo giá trị mặc định là 0.0")

        # Đảm bảo nhãn target không chứa giá trị null
        df = df.dropna(subset=[TARGET_COLUMN])
        df[TARGET_COLUMN] = df[TARGET_COLUMN].astype("int32")
        
        return df

    def get_train_test_split_data(self, test_size: float = 0.2, random_state: int = 42):
        """
        Làm sạch dữ liệu, kiểm chứng Schema và phân tách thành X (Features) và y (Target)
        để sẵn sàng nạp vào ml_trainer.py
        """
        df = self.load_and_clean_data()
        
        # Xác thực cấu trúc dữ liệu theo đúng Schema
        X = validate_features(df)
        y = df[TARGET_COLUMN]
        
        # Chia tách thủ công hoặc trả về DataFrame hoàn chỉnh để ml_trainer sử dụng train_test_split chuyên sâu hơn
        logger.info(f"Dữ liệu sau khi làm sạch sẵn sàng huấn luyện. Tổng số mẫu: {len(X)}.")
        return X, y

    @staticmethod
    def combine_all_datasets(datasets_dir: str) -> str:
        """
        Gộp TẤT CẢ file dataset_*.csv trong thư mục (cả nguồn V4_SIGNAL lẫn GEOMETRIC_PATTERN)
        thành 1 file DUY NHẤT CỐ ĐỊNH TÊN (dataset_combined_latest.csv - GHI ĐÈ mỗi lần gọi,
        không tạo file mới theo timestamp) để model học được từ cả 2 nguồn thay vì chỉ file
        mới nhất. Trả về đường dẫn file gộp, hoặc "" nếu không có dữ liệu.

        LUU Y QUAN TRONG: truoc day moi lan goi ham nay tao ra 1 file MOI theo timestamp,
        khong bao gio xoa file cu -> moi dataset ~50-100MB, chi vai lan chay Walk-Forward/
        Train la day het dung luong dia (da xay ra thuc te, gay loi "No space left on
        device"). Gio CHI GIU 1 FILE DUY NHAT, tu dong don sach cac file combined cu con sot
        lai tu truoc ban va nay.
        """
        import glob
        list_files = [
            f for f in glob.glob(os.path.join(datasets_dir, "dataset_*.csv"))
            if "dataset_combined_" not in os.path.basename(f)
        ]
        if not list_files:
            logger.warning("Không có file dataset_*.csv nào để gộp.")
            return ""

        frames = []
        for f in list_files:
            try:
                df = pd.read_csv(f)
                if TARGET_COLUMN not in df.columns:
                    continue
                frames.append(df)
                logger.info(f"Đã nạp {len(df)} dòng từ {os.path.basename(f)} để gộp.")
            except Exception as e:
                logger.error(f"Bỏ qua file lỗi khi gộp dataset {f}: {str(e)}")

        if not frames:
            return ""

        combined = pd.concat(frames, ignore_index=True, sort=False)

        # Don sach MOI file dataset_combined_*.csv cu (kem ca file dang ghi de sap toi,
        # tranh giu lai nhieu ban cu tu cac lan chay truoc)
        for old_combined in glob.glob(os.path.join(datasets_dir, "dataset_combined_*.csv")):
            try:
                os.remove(old_combined)
            except Exception as e:
                logger.warning(f"Không xoá được file combined cũ {old_combined}: {e}")

        out_path = os.path.join(datasets_dir, "dataset_combined_latest.csv")
        combined.to_csv(out_path, index=False)
        logger.info(f"✅ Đã gộp {len(list_files)} file thành 1 dataset hợp nhất: {out_path} ({len(combined)} dòng)")
        return out_path

if __name__ == "__main__":
    # Test nhanh tính năng đọc file trực tiếp
    import glob
    from ai_v5.config_ai import DATASETS_DIR
    
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    
    # Tìm file dataset mới nhất trong thư mục datasets
    list_files = glob.glob(os.path.join(DATASETS_DIR, "dataset_*.csv"))
    if list_files:
        latest_file = max(list_files, key=os.path.getctime)
        print(f"\n🔍 Đang chạy thử nghiệm DataLoader trên file mới nhất: {latest_file}")
        loader = DataLoader(latest_file)
        X, y = loader.get_train_test_split_data()
        print("✅ Kiểm tra thành công! Cấu trúc X (Features):")
        print(X.head(3))
        print("Cấu trúc y (Target):")
        print(y.head(3))
    else:
        print("\n⚠️ Chưa có file dataset.csv nào để test loader. Hãy chạy dataset_builder trước.")