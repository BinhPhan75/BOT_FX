# ai_v5/storage/parquet_writer.py
import os
import pandas as pd
import logging

logger = logging.getLogger("watcher.ai_learner")

def save_to_parquet(df: pd.DataFrame, file_path: str):
    """Lưu DataFrame xuống định dạng nén Parquet tối ưu."""
    try:
        import pyarrow
    except ImportError:
        logger.warning("⚠️ Thiếu thư viện pyarrow. Đang lưu tạm dạng dự phòng CSV.")
        df.to_csv(file_path.replace(".parquet", ".csv"), index=False)
        return
        
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    df.to_parquet(file_path, engine='pyarrow', compression='snappy', index=False)
    logger.info(f"✅ Đã lưu trữ dữ liệu nén thành công: {file_path}")