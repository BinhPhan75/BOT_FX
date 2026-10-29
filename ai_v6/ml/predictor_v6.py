# ai_v6/ml/predictor_v6.py
"""
Wrapper MONG quanh ai_v5.ml.predictor.AIPredictor: TAI SU DUNG 100% logic
predict_signal()/predict_probability() (khong sua 1 dong nao trong do), CHI
thay doi ModelManager de tro toi ai_v6/models/ (RIENG BIET voi ai_v5/models/).

VI SAO CAN MODEL RIENG (khong dung chung latest_model.pkl cua ai_v5):
ai_v6 quet 7 nhom pattern tren khung M5 (TF_CONFIRM), trong khi model goc
cua ai_v5 duoc train tren phan phoi swing/pattern cua khung M15. Cau truc
dinh/day, ATR, RSI... tren M5 co phan phoi thong ke KHAC han M15 (nhieu
swing hon, bien do nho hon) - dung tam model M15 de cham diem tin hieu M5
se cho ra xac suat KHONG DANG TIN CAY, giong dung bai hoc "feature
distribution changes require retraining" da rut ra khi sua loi
distance_to_zone_pct trong README_HANDOFF_1.md.

=> BAT BUOC train model rieng cho ai_v6 truoc khi chay live that (xem
run_init_train_v6.py o thu muc goc). Neu chua co model rieng,
AIPredictorV6().model se la None va live_trader.py se TU CHOI khoi dong
(giong co che an toan cua ai_v5 khi thieu latest_model.pkl).
"""
import logging

from ai_v5.ml.predictor import AIPredictor
from ai_v5.ml.model_manager import ModelManager
from ai_v6.config_ai import MODELS_DIR

logger = logging.getLogger("ai_v6_predictor")


class AIPredictorV6(AIPredictor):
    def __init__(self):
        # KHONG goi super().__init__() vi no se tao ModelManager() mac dinh tro toi
        # ai_v5/models/ - can tu khoi tao lai voi models_dir RIENG cua ai_v6.
        self.model_manager = ModelManager(models_dir=MODELS_DIR)
        self.model = None
        self.metadata = None
        self._load_active_model()
        if self.model is None:
            logger.warning("⚠️ Chưa có model AI v6 riêng (ai_v6/models/latest_model.pkl). "
                            "Chạy run_init_train_v6.py trước khi live trading thật.")
