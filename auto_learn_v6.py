# auto_learn_v6.py
"""
Dat o thu muc GOC bot_xutho4/ (cung cap voi build_train_v6_scalping.py).

VONG TU HOC THAT cho ai_v6 (model + nguong WinProb). Moi lan chay:

  1. Xay dataset moi nhat tu lich su MT5 (dung lai build_scalping_dataset, nhan theo DUNG co che
     scalping hien hanh trong config_live.py) - hoac doc dataset co san qua --dataset.
  2. Chia THEO THOI GIAN (khong xao tron): TRAIN (cu nhat) | VALID | TEST (moi nhat, chua tung dung de chon gi).
  3. Train model "thach thuc" (challenger) tren TRAIN, co TRONG SO THEO THOI GIAN (du lieu moi nang hon).
  4. Chon nguong WinProb tren VALID theo EV (khong theo Precision cao nhat), chi nhan nguong co can duoi
     Wilson cua Precision >= diem hoa von 1/(1+RR).
  5. Danh gia tren TEST (chi gio giao dich 8-18h VN - dung noi bot thuc su vao lenh) va so voi model
     DANG CHAY (champion) tren CUNG cac mau MOI HON ngay champion duoc train (cong bang, khong ro ri).
  6. CHI THAY model neu qua TAT CA cac cong (xem GATES). Khong qua -> giu nguyen model cu.
  7. Khi thay: sao luu champion, ghi model moi + "decision_threshold" vao metadata, chay SMOKE TEST qua
     AIPredictorV6 that (diem so predictor == diem so model); loi -> TU DONG khoi phuc champion.

MAC DINH la che do BAO CAO (khong ghi/thay gi). Them --apply de cho phep thay model that.

Cach dung:
    py -3.11 auto_learn_v6.py --days 90                 # chi bao cao (khuyen nghi chay vai ngay dau)
    py -3.11 auto_learn_v6.py --days 90 --apply --notify
    py -3.11 auto_learn_v6.py --dataset ai_v6\\datasets\\dataset_patterns_scalping_xxx.csv   # bo qua buoc tai/quet
    py -3.11 auto_learn_v6.py --rollback                # quay lai champion gan nhat da sao luu

GIOI HAN CAN BIET:
  - Nhan thang/thua la 1 lenh don theo co che scalping (khong mo phong DCA, spread, timeout tinh theo dau P&L);
    EV tinh xap xi: thang = +RR, thua = -1 (timeout khong dung 100%).
  - Day la tin hieu tu-dieu-chinh model + nguong. SL/TP/ATR/MAX_HOLD KHONG tu doi o day.
"""
import argparse
import glob
import json
import logging
import math
import os
import shutil
import sys
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger("auto_learn_v6")

# ----------------------------- THAM SO (GIA TRI TAM, co the chinh bang CLI) -----------------------------
THRESHOLD_GRID = [round(x, 2) for x in np.arange(0.45, 0.701, 0.01)]
HALF_LIFE_DAYS = 30            # mau cu 30 ngay co trong so 0.5 so voi mau moi nhat
VALID_FRAC, TEST_FRAC = 0.12, 0.12
MIN_SAMPLES = 3000             # it hon -> khong train
MIN_VALID_APPROVALS = 30
MIN_TEST_APPROVALS = 60
WILSON_Z = 1.2816              # khoang tin cay 80% mot phia
WF_FOLDS = 3
WF_MEAN_AUC_MIN, WF_MIN_AUC_MIN = 0.52, 0.50
TEST_AUC_MIN = 0.52
KEEP_AUTO_DATASETS = 3

LGB_PARAMS = dict(  # Nhieu regularization hon ai_v5 (100 cay/depth 5) vi walk-forward cho Precision thap hon random split
    n_estimators=150, learning_rate=0.03, max_depth=4, num_leaves=15, min_child_samples=60,
    subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=5.0, random_state=42, verbose=-1,
)


# ----------------------------- thong ke -----------------------------
def wilson_lb(k: int, n: int, z: float = WILSON_Z) -> float:
    if n <= 0:
        return 0.0
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    adj = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - adj) / denom


def breakeven_precision(rr: float) -> float:
    return 1.0 / (1.0 + rr)


def eval_at_threshold(proba: np.ndarray, y: np.ndarray, thr: float, rr: float) -> dict:
    mask = proba >= thr
    n = int(mask.sum())
    wins = int(y[mask].sum()) if n else 0
    return {"thr": float(thr), "n": n, "wins": wins,
            "precision": (wins / n) if n else None,
            "wilson_lb": wilson_lb(wins, n),
            "ev_total_R": wins * rr - (n - wins),
            "ev_per_trade_R": ((wins * rr - (n - wins)) / n) if n else None}


def choose_threshold(proba, y, rr, min_n):
    """Chon nguong co EV tong lon nhat trong so nguong du mau VA can duoi Wilson >= hoa von."""
    be = breakeven_precision(rr)
    table, best = [], None
    for thr in THRESHOLD_GRID:
        r = eval_at_threshold(proba, y, thr, rr)
        r["qualifies"] = bool(r["n"] >= min_n and r["wilson_lb"] >= be)
        table.append(r)
        if r["qualifies"] and (best is None or r["ev_total_R"] > best["ev_total_R"]):
            best = r
    return best, table


def safe_auc(y, proba):
    from sklearn.metrics import roc_auc_score
    if len(y) < 30 or len(set(y)) < 2:
        return None
    return float(roc_auc_score(y, proba))


# ----------------------------- du lieu / model -----------------------------
def vn_hour(ts: pd.Series) -> pd.Series:
    return (ts + pd.Timedelta(hours=7)).dt.hour


def prepare(df: pd.DataFrame, feats: list, target: str) -> pd.DataFrame:
    df = df.copy()
    df["_ts"] = pd.to_datetime(df["entry_time"], utc=True)
    df = df.sort_values("_ts").reset_index(drop=True)
    df[feats] = df[feats].astype(float)
    df[target] = df[target].astype(int)
    return df


def time_weights(ts: pd.Series, ref: pd.Timestamp, half_life: float) -> np.ndarray:
    age_days = (ref - ts).dt.total_seconds().to_numpy() / 86400.0
    return np.power(0.5, np.clip(age_days, 0, None) / half_life)


def fit_model(df_train, feats, target, half_life):
    import lightgbm as lgb
    w = time_weights(df_train["_ts"], df_train["_ts"].max(), half_life)
    m = lgb.LGBMClassifier(**LGB_PARAMS)
    m.fit(df_train[feats], df_train[target], sample_weight=w)
    return m


def walk_forward_auc(df_dev, feats, target, half_life, folds=WF_FOLDS):
    chunks = np.array_split(np.arange(len(df_dev)), folds + 1)
    aucs = []
    for k in range(1, folds + 1):
        tr = df_dev.iloc[np.concatenate(chunks[:k])]
        te = df_dev.iloc[chunks[k]]
        m = fit_model(tr, feats, target, half_life)
        aucs.append(safe_auc(te[target].to_numpy(), m.predict_proba(te[feats])[:, 1]))
    return aucs


# ----------------------------- champion -----------------------------
def load_champion(models_dir: str, default_threshold: float):
    """Tra ve dict {model, feats, threshold, trained_utc} hoac None."""
    pkl = os.path.join(models_dir, "latest_model.pkl")
    meta_p = os.path.join(models_dir, "latest_model_meta.json")
    if not os.path.exists(pkl):
        return None
    try:
        import joblib
        model = joblib.load(pkl)
        meta = json.load(open(meta_p, encoding="utf-8")) if os.path.exists(meta_p) else {}
        metrics = meta.get("metrics", {})
        trained = None
        if meta.get("timestamp"):
            try:  # timestamp ModelManager = gio may chay bot (gio dia phuong)
                trained = pd.Timestamp(datetime.strptime(meta["timestamp"], "%Y%m%d_%H%M%S").astimezone(timezone.utc))
            except Exception:
                trained = None
        return {"model": model, "feats": meta.get("features_used") or None,
                "threshold": float(metrics.get("decision_threshold", default_threshold)),
                "trained_utc": trained, "meta": meta}
    except Exception as e:
        logger.error(f"Không nạp được champion: {e}")
        return None


# ----------------------------- QUYET DINH CHINH (ham thuan, de test) -----------------------------
def decide(df_raw: pd.DataFrame, feats: list, target: str, rr: float, window: tuple,
           champion=None, half_life=HALF_LIFE_DAYS, valid_frac=VALID_FRAC, test_frac=TEST_FRAC,
           min_test_approvals=MIN_TEST_APPROVALS) -> tuple:
    """Tra ve (report, challenger_model_or_None). report['accept'] la quyet dinh cuoi."""
    rep = {"time": datetime.now().isoformat(), "rr": rr, "breakeven_precision": breakeven_precision(rr),
           "gates": {}, "reasons": [], "accept": False}
    if len(df_raw) < MIN_SAMPLES:
        rep["reasons"].append(f"Dataset chỉ có {len(df_raw)} mẫu (< {MIN_SAMPLES}) — không đủ để train đáng tin")
        return rep, None

    df = prepare(df_raw, feats, target)
    n = len(df)
    i_test, i_valid = int(n * (1 - test_frac)), int(n * (1 - test_frac - valid_frac))
    train, valid, test = df.iloc[:i_valid], df.iloc[i_valid:i_test], df.iloc[i_test:]
    h0, h1 = window
    in_win = lambda d: vn_hour(d["_ts"]).between(h0, h1 - 1).to_numpy()
    rep["data"] = {"n": n, "base_win_rate": float(df[target].mean()), "train": len(train), "valid": len(valid),
                   "test": len(test), "test_start": str(test["_ts"].iloc[0]), "test_end": str(test["_ts"].iloc[-1])}

    # G1: on dinh qua thoi gian
    aucs = walk_forward_auc(pd.concat([train, valid]), feats, target, half_life)
    rep["walk_forward_auc"] = aucs
    valid_aucs = [a for a in aucs if a is not None]
    g1 = bool(valid_aucs and np.mean(valid_aucs) >= WF_MEAN_AUC_MIN and min(valid_aucs) >= WF_MIN_AUC_MIN)
    rep["gates"]["G1_walk_forward_auc"] = g1
    if not g1:
        rep["reasons"].append(f"Walk-forward AUC không đạt (TB≥{WF_MEAN_AUC_MIN}, min≥{WF_MIN_AUC_MIN}): "
                              f"{[None if a is None else round(a, 3) for a in aucs]}")

    # Train challenger + chon nguong tren VALID (chi gio giao dich)
    chal = fit_model(train, feats, target, half_life)
    vmask = in_win(valid)
    pv = chal.predict_proba(valid[feats])[:, 1][vmask]
    yv = valid[target].to_numpy()[vmask]
    best, table = choose_threshold(pv, yv, rr, MIN_VALID_APPROVALS)
    rep["valid_threshold_table"] = table
    g2 = best is not None
    rep["gates"]["G2_threshold_has_edge_on_valid"] = g2
    if not g2:
        rep["reasons"].append("Không có ngưỡng WinProb nào trên VALID có cận dưới Precision ≥ điểm hòa vốn "
                              f"({breakeven_precision(rr):.1%}) với ≥{MIN_VALID_APPROVALS} lệnh — model chưa chứng minh có lợi thế")
    thr = best["thr"] if best else 0.55
    rep["chosen_threshold"] = thr if best else None

    # TEST (moi nhat, chi gio giao dich) - chua tung dung de chon gi
    tmask = in_win(test)
    test_w = test[tmask]
    p_test = chal.predict_proba(test_w[feats])[:, 1]
    y_test = test_w[target].to_numpy()
    ch = eval_at_threshold(p_test, y_test, thr, rr)
    ch["auc"] = safe_auc(y_test, p_test)
    rep["challenger_test"] = ch
    g3 = ch["n"] >= min_test_approvals
    rep["gates"]["G3_test_enough_approvals"] = g3
    if not g3:
        rep["reasons"].append(f"TEST chỉ duyệt {ch['n']} lệnh (< {min_test_approvals}) — không đủ mẫu kết luận")
    g4 = bool(ch["n"] > 0 and ch["wilson_lb"] >= breakeven_precision(rr))
    rep["gates"]["G4_test_precision_above_breakeven"] = g4
    if not g4:
        pr = ch["precision"]
        rep["reasons"].append(f"TEST: Precision {('N/A' if pr is None else f'{pr:.1%}')} (cận dưới 80% = {ch['wilson_lb']:.1%}) "
                              f"chưa vượt hòa vốn {breakeven_precision(rr):.1%}")
    g6 = bool(ch["auc"] is not None and ch["auc"] >= TEST_AUC_MIN)
    rep["gates"]["G6_test_auc"] = g6
    if not g6:
        rep["reasons"].append(f"TEST AUC={ch['auc']} < {TEST_AUC_MIN} — WinProb chưa phân biệt được thắng/thua")

    # G5: so voi champion tren CUNG cac mau MOI HON ngay champion duoc train
    g5, champ_rep = True, {"available": champion is not None}
    if champion is not None:
        try:
            cf = champion["feats"] or feats
            sub = test_w
            if champion["trained_utc"] is not None:
                sub = test_w[test_w["_ts"] > champion["trained_utc"]]
            champ_rep["fair_rows"] = int(len(sub))
            if len(sub) >= 100:
                y_s = sub[target].to_numpy()
                pc = champion["model"].predict_proba(sub[cf].astype(float))[:, 1]
                pn = chal.predict_proba(sub[feats])[:, 1]
                champ_rep["champion"] = {**eval_at_threshold(pc, y_s, champion["threshold"], rr), "auc": safe_auc(y_s, pc)}
                champ_rep["challenger_same_rows"] = {**eval_at_threshold(pn, y_s, thr, rr), "auc": safe_auc(y_s, pn)}
                g5 = champ_rep["challenger_same_rows"]["ev_total_R"] >= champ_rep["champion"]["ev_total_R"]
                if not g5:
                    rep["reasons"].append("Challenger KHÔNG vượt champion trên cùng mẫu mới (EV tổng R thấp hơn)")
            else:
                champ_rep["note"] = "Không đủ mẫu công bằng (mới hơn ngày champion train) — bỏ qua so sánh trực tiếp"
        except Exception as e:
            champ_rep["error"] = str(e)
            champ_rep["note"] = "Không chấm được champion trên dataset này (lệch feature?) — bỏ qua so sánh"
    rep["champion_compare"] = champ_rep
    rep["gates"]["G5_beats_champion"] = g5

    rep["accept"] = bool(all(rep["gates"].values()))
    return rep, (chal if rep["accept"] else None)


# ----------------------------- trien khai an toan -----------------------------
def _archive_dir(models_dir):
    d = os.path.join(models_dir, "archive")
    os.makedirs(d, exist_ok=True)
    return d


def backup_champion(models_dir) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    pkl = os.path.join(models_dir, "latest_model.pkl")
    if not os.path.exists(pkl):
        return ""
    dst = os.path.join(_archive_dir(models_dir), f"champion_{ts}.pkl")
    shutil.copy2(pkl, dst)
    meta = os.path.join(models_dir, "latest_model_meta.json")
    if os.path.exists(meta):
        shutil.copy2(meta, dst.replace(".pkl", "_meta.json"))
    return dst


def restore_champion(models_dir, backup_pkl: str) -> bool:
    if not backup_pkl or not os.path.exists(backup_pkl):
        return False
    shutil.copy2(backup_pkl, os.path.join(models_dir, "latest_model.pkl"))
    bm = backup_pkl.replace(".pkl", "_meta.json")
    if os.path.exists(bm):
        shutil.copy2(bm, os.path.join(models_dir, "latest_model_meta.json"))
    return True


def smoke_test(model, df_sample: pd.DataFrame, feats: list, predictor_factory) -> tuple:
    """Diem so cua predictor THAT (duong live dung) phai trung voi model.predict_proba."""
    try:
        p = predictor_factory()
        if p.model is None:
            return False, "AIPredictorV6 không nạp được model mới"
        for _, row in df_sample.iterrows():
            d = {f: float(row[f]) for f in feats}
            got = float(p.predict_probability(d))
            exp = float(model.predict_proba(pd.DataFrame([d])[feats])[0, 1])
            if abs(got - exp) > 1e-6:
                return False, f"predictor ({got:.6f}) ≠ model ({exp:.6f}) — lệch đường tính điểm live"
        thr = (getattr(p, "metadata", None) or {}).get("metrics", {}).get("decision_threshold")
        if thr is None:
            return False, "metadata thiếu decision_threshold"
        return True, "OK"
    except Exception as e:
        return False, f"Smoke test lỗi: {e}"


def deploy(model, thr, rep, df_prepared, feats, models_dir, model_manager_cls, predictor_factory) -> dict:
    backup = backup_champion(models_dir)
    metrics = {"decision_threshold": float(thr), "trained_by": "auto_learn_v6", "features_used": feats,
               "dataset_rows": rep["data"]["n"], "test_precision": rep["challenger_test"]["precision"],
               "test_auc": rep["challenger_test"]["auc"], "test_ev_per_trade_R": rep["challenger_test"]["ev_per_trade_R"],
               "walk_forward_auc": rep["walk_forward_auc"], "half_life_days": HALF_LIFE_DAYS}
    path, _ = model_manager_cls(models_dir=models_dir).save_model(model, metrics)
    if not path:
        restore_champion(models_dir, backup)
        return {"deployed": False, "why": "Lưu model thất bại — đã khôi phục champion", "backup": backup}
    sample = df_prepared.tail(25)
    ok, msg = smoke_test(model, sample, feats, predictor_factory)
    if not ok:
        restore_champion(models_dir, backup)
        return {"deployed": False, "why": f"SMOKE TEST THẤT BẠI → đã khôi phục champion: {msg}", "backup": backup}
    return {"deployed": True, "model_path": path, "backup": backup, "smoke": msg}


def rollback(models_dir) -> str:
    cands = sorted(glob.glob(os.path.join(models_dir, "archive", "champion_*.pkl")))
    if not cands:
        return ""
    return cands[-1] if restore_champion(models_dir, cands[-1]) else ""


# ----------------------------- bao cao -----------------------------
def format_report(rep: dict, deployed: dict = None, apply: bool = False) -> str:
    L = []
    d = rep.get("data", {})
    L.append("=" * 78)
    L.append(f"AUTO-LEARN AI v6 — {rep['time'][:19]} | mẫu={d.get('n')} | WR nền={d.get('base_win_rate', 0):.1%} | "
             f"hòa vốn Precision={rep['breakeven_precision']:.1%} (RR={rep['rr']})")
    if "walk_forward_auc" in rep:
        L.append("Walk-forward AUC: " + ", ".join("N/A" if a is None else f"{a:.3f}" for a in rep["walk_forward_auc"]))
    ct = rep.get("challenger_test")
    if ct:
        pr = "N/A" if ct["precision"] is None else f"{ct['precision']:.1%}"
        L.append(f"Challenger @TEST (giờ 8-18): ngưỡng={rep.get('chosen_threshold')} | duyệt {ct['n']} lệnh | Precision {pr} "
                 f"| EV/lệnh {ct['ev_per_trade_R'] if ct['ev_per_trade_R'] is None else round(ct['ev_per_trade_R'], 3)} R | AUC {ct['auc']}")
    cc = rep.get("champion_compare", {})
    if cc.get("champion"):
        c, n = cc["champion"], cc["challenger_same_rows"]
        L.append(f"Cùng {cc['fair_rows']} mẫu mới: champion EV tổng {c['ev_total_R']:.1f}R ({c['n']} lệnh, AUC {c['auc']}) "
                 f"vs challenger {n['ev_total_R']:.1f}R ({n['n']} lệnh, AUC {n['auc']})")
    elif cc.get("note"):
        L.append("Champion: " + cc["note"])
    L.append("Các cổng: " + " | ".join(f"{k.split('_')[0]}={'✔' if v else '✘'}" for k, v in rep["gates"].items()))
    if rep["accept"]:
        L.append("→ QUYẾT ĐỊNH: model MỚI đạt tất cả các cổng.")
        if deployed:
            L.append("  " + ("ĐÃ THAY model (đã sao lưu champion). " if deployed.get("deployed") else "KHÔNG thay: ")
                     + str(deployed.get("why") or deployed.get("smoke", "")))
        elif not apply:
            L.append("  (chế độ báo cáo — thêm --apply để thay model thật)")
    else:
        L.append("→ QUYẾT ĐỊNH: GIỮ model hiện tại. Lý do:")
        for r in rep["reasons"]:
            L.append("   • " + r)
    L.append("=" * 78)
    return "\n".join(L)


# ----------------------------- main -----------------------------
def _build_dataset_from_mt5(days: int):
    from ai_v6.live import mt5_connector
    from backtest_v6_scalping import _load_mt5_candles
    from build_train_v6_scalping import build_scalping_dataset, SYMBOL
    from ai_v6.config_live import SCALP_SL_ATR_MULTIPLE, SCALP_REWARD_RISK_RATIO, MAX_HOLD_MINUTES
    if not mt5_connector.init():
        raise RuntimeError("Không kết nối được MT5")
    try:
        m15, m5, m1 = (_load_mt5_candles(SYMBOL, tf, days) for tf in ("M15", "M5", "M1"))
        if not (m15 and m5 and m1):
            raise RuntimeError("Không tải đủ dữ liệu M15/M5/M1")
        return build_scalping_dataset(SYMBOL, m15, m5, m1, SCALP_SL_ATR_MULTIPLE, SCALP_REWARD_RISK_RATIO, MAX_HOLD_MINUTES)
    finally:
        mt5_connector.shutdown()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Vòng tự học AI v6 (model + ngưỡng) có kiểm chứng và an toàn")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--dataset", type=str, default=None)
    ap.add_argument("--apply", action="store_true", help="CHO PHÉP thay model thật (mặc định chỉ báo cáo)")
    ap.add_argument("--notify", action="store_true", help="Gửi kết quả qua Telegram của ai_v6")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--half-life", type=float, default=HALF_LIFE_DAYS)
    ap.add_argument("--min-test-approvals", type=int, default=MIN_TEST_APPROVALS)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    from ai_v6.config_ai import MODELS_DIR, DATASETS_DIR, REPORTS_DIR, PROBABILITY_THRESHOLD
    from ai_v6.config_live import SCALP_REWARD_RISK_RATIO, TRADING_HOURS_START_VN, TRADING_HOURS_END_VN
    from ai_v5.data.feature_schema import FEATURE_COLUMNS, TARGET_COLUMN
    from ai_v5.ml.model_manager import ModelManager

    if a.rollback:
        r = rollback(MODELS_DIR)
        print(f"✅ Đã khôi phục champion từ {r}" if r else "❌ Không có bản sao lưu champion nào.")
        return 0

    if a.dataset:
        df = pd.read_csv(a.dataset)
    else:
        df = _build_dataset_from_mt5(a.days)
        if df is None or df.empty:
            print("❌ Không tạo được dataset.")
            return 1
        os.makedirs(DATASETS_DIR, exist_ok=True)
        out = os.path.join(DATASETS_DIR, f"dataset_patterns_scalping_auto_{datetime.now():%Y%m%d_%H%M%S}.csv")
        df.to_csv(out, index=False)
        for old in sorted(glob.glob(os.path.join(DATASETS_DIR, "dataset_patterns_scalping_auto_*.csv")))[:-KEEP_AUTO_DATASETS]:
            os.remove(old)

    champion = load_champion(MODELS_DIR, PROBABILITY_THRESHOLD)
    rep, chal = decide(df, FEATURE_COLUMNS, TARGET_COLUMN, SCALP_REWARD_RISK_RATIO,
                       (TRADING_HOURS_START_VN, TRADING_HOURS_END_VN), champion,
                       half_life=a.half_life, min_test_approvals=a.min_test_approvals)

    deployed = None
    if rep["accept"] and a.apply:
        from ai_v6.ml.predictor_v6 import AIPredictorV6
        deployed = deploy(chal, rep["chosen_threshold"], rep, prepare(df, FEATURE_COLUMNS, TARGET_COLUMN),
                          FEATURE_COLUMNS, MODELS_DIR, ModelManager, AIPredictorV6)
        rep["deploy"] = deployed
    text = format_report(rep, deployed, a.apply)
    print(text)

    os.makedirs(REPORTS_DIR, exist_ok=True)
    with open(os.path.join(REPORTS_DIR, f"learn_report_{datetime.now():%Y%m%d_%H%M%S}.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2, default=str)
    if a.notify:
        try:
            from ai_v6.config_ai import TELEGRAM_AI_TOKEN, TELEGRAM_AI_CHAT_ID
            from ai_v6.live import telegram_commander
            telegram_commander._send(TELEGRAM_AI_TOKEN, TELEGRAM_AI_CHAT_ID, "🧠 <b>AI v6 tự học</b>\n<pre>" + text[-3500:] + "</pre>")
        except Exception as e:
            logger.warning(f"Gửi Telegram thất bại: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
