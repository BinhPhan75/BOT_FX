# ai_v6/adaptive_controller.py
"""
Bo dieu khien TU DIEU CHINH cho ai_v6 (giai doan 1 cua "tu hoc").

Y tuong: doc ket qua lenh THAT da dong trong ai_v6_trades.db, gom thanh NHOM (1 lenh goc + cac
lenh DCA), roi tu dong:
  1. TAT DCA neu cac nhom co DCA lo ro rang (co khoang tin cay thong ke), thu lai sau DCA_PROBATION_DAYS ngay.
  2. CHAN TAM gio / pattern / nhom pattern dang lo ro rang (co "co chan" de khong over-react).
  3. THEO DOI suc khoe model (WinProb co con phan biet thang/thua khong) -> canh bao can retrain.

NGUYEN TAC AN TOAN (rut tu cac loi da gap trong README_HANDOFF):
  - Chi quyet dinh khi du mau (MIN_GROUPS_*), dung shrinkage keo ve trung binh chung (tranh over-fit mau nho).
  - Moi "chan" CO HAN SU DUNG (BLOCK_DAYS) roi tu thu lai - bo loc khong bao gio vo han.
  - Tran so luong gio/pattern duoc phep chan (khong cho bot tu "tat" chinh no).
  - KHONG tu sua SL/TP/ATR/nguong WinProb: nhung tham so do can backtest/retrain co kiem duyet.
  - Loi doc/ghi file -> FAIL-OPEN (cho phep giao dich nhu binh thuong), khong bao gio chan oan do loi.

Dung:
    from ai_v6 import adaptive_controller as adaptive
    changes = adaptive.refresh_state()            # goi dinh ky (tu giới han 30 phut/lan)
    adaptive.is_hour_blocked(hour_vn) / is_pattern_blocked(pattern, source_type) / is_dca_allowed()

Chay thu (khong ghi gi, chi in bao cao):
    py -3.11 -m ai_v6.adaptive_controller --dry-run [--db duong_dan_db]
"""
import argparse
import json
import logging
import math
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta

logger = logging.getLogger("ai_v6_adaptive")

try:
    from ai_v6.config_ai import AI_BASE_DIR
except Exception:  # chay doc lap de thu nghiem
    AI_BASE_DIR = os.getcwd()
try:
    from ai_v6.config_live import TRADING_HOURS_START_VN, TRADING_HOURS_END_VN
except Exception:
    TRADING_HOURS_START_VN, TRADING_HOURS_END_VN = 8, 18

DB_PATH = os.path.abspath(os.path.join(AI_BASE_DIR, "..", "ai_v6_trades.db"))
STATE_PATH = os.path.abspath(os.path.join(AI_BASE_DIR, "..", "ai_v6_adaptive_state.json"))

# ------------------------- THAM SO CUA BO DIEU KHIEN (GIA TRI TAM) -------------------------
LOOKBACK_DAYS = 30                 # chi xet nhom lenh trong N ngay gan nhat
REFRESH_MIN_INTERVAL_MIN = 30      # tinh lai toi da 30 phut / lan
SHRINK_K = 12                      # "so mau ao" keo trung binh tung nhom ve trung binh chung

# DCA
DCA_MIN_GROUPS = 25                # can >= 25 nhom co DCA moi du tin de quyet dinh
DCA_Z = 1.645                      # 90% mot phia: tat DCA neu (mean + z*se) < 0
DCA_DISABLE_DAYS = 14              # tat bao lau truoc khi cho thu lai (probation)

# Gio / pattern / nhom pattern
MIN_GROUPS_HOUR = 15
MIN_GROUPS_PATTERN = 15
MIN_GROUPS_SOURCE = 20
BLOCK_EV_FRACTION = 0.15           # chan neu EV (sau shrinkage) < -15% quy mo lo/lai trung binh
BLOCK_T_STAT = -1.0                # VA thong ke t cua trung binh tho < -1.0
BLOCK_DAYS = 7                     # moi lan chan co hieu luc toi da 7 ngay
MAX_BLOCKED_HOURS = 3              # tran an toan
MAX_BLOCKED_PATTERNS = 4
MAX_BLOCKED_SOURCES = 2
MIN_OPEN_HOURS_LEFT = 5            # luon con it nhat 5 gio giao dich

# Suc khoe model
MODEL_HEALTH_WINDOW = 150          # so nhom gan nhat de do tuong quan WinProb <-> thang/thua
MODEL_MIN_RANK_CORR = 0.0          # <= 0: WinProb khong con phan biet duoc -> canh bao


# ------------------------------------ doc du lieu ------------------------------------
def load_groups(db_path: str = DB_PATH, lookback_days: int = LOOKBACK_DAYS):
    """Tra ve list dict cac NHOM DA DONG HOAN TOAN (tat ca lenh trong nhom deu co ket qua)."""
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM ai_v6_trades ORDER BY open_time, id").fetchall()
    conn.close()

    groups, cur = [], None
    for r in rows:
        if not r["is_dca"] or cur is None:       # lenh goc -> mo nhom moi
            cur = {"orders": []}
            groups.append(cur)
        cur["orders"].append(r)

    cutoff = datetime.now() - timedelta(days=lookback_days)
    out = []
    for g in groups:
        o = g["orders"]
        if any(x["result"] is None or x["profit"] is None for x in o):
            continue                              # nhom con mo / chua dong bo -> bo qua
        first = o[0]
        start = datetime.fromisoformat(first["open_time"])
        if start < cutoff:
            continue
        pnl = sum(x["profit"] for x in o)
        out.append({
            "start": start, "n": len(o), "pnl": pnl, "pnl_per_lot": pnl / len(o),
            "win": 1 if pnl > 0 else 0, "hour": start.hour,
            "pattern": first["pattern"], "source": first["source_type"],
            "prob": first["win_probability"],
        })
    return out


# ------------------------------------ thong ke ------------------------------------
def _mean_std(v):
    n = len(v)
    m = sum(v) / n
    var = sum((x - m) ** 2 for x in v) / (n - 1) if n > 1 else 0.0
    return m, math.sqrt(var)


def _evaluate(values, mu_global, scale):
    """Tra ve dict thong ke 1 nhom khoa (gio/pattern/...). EV da shrinkage."""
    n = len(values)
    m, sd = _mean_std(values)
    shrunk = (n * m + SHRINK_K * mu_global) / (n + SHRINK_K)
    t = m / (sd / math.sqrt(n)) if sd > 0 and n > 1 else 0.0
    return {"n": n, "mean": round(m, 1), "shrunk": round(shrunk, 1), "t": round(t, 2),
            "bad": shrunk < -BLOCK_EV_FRACTION * scale and t < BLOCK_T_STAT}


def _rank_corr(x, y):
    """Spearman don gian (khong can scipy)."""
    n = len(x)
    if n < 10:
        return None

    def ranks(a):
        order = sorted(range(len(a)), key=lambda i: a[i])
        r = [0.0] * len(a)
        i = 0
        while i < len(a):
            j = i
            while j + 1 < len(a) and a[order[j + 1]] == a[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r

    rx, ry = ranks(x), ranks(y)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else None


# ------------------------------------ trang thai ------------------------------------
def _default_state():
    return {"updated_at": None, "dca": {"enabled": True, "disabled_until": None, "ignore_before": None},
            "blocked_hours": {}, "blocked_patterns": {}, "blocked_sources": {}, "model_health": {}}


def _load_state(path=STATE_PATH):
    try:
        with open(path, "r", encoding="utf-8") as f:
            s = json.load(f)
        base = _default_state()
        base.update(s)
        return base
    except Exception:
        return _default_state()


def _save_state(state, path=STATE_PATH):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, path)                          # ghi nguyen tu, tranh doc file do dang


def _iso(dt):
    return dt.isoformat() if dt else None


def _parse(s):
    return datetime.fromisoformat(s) if s else None


def compute_state(groups, prev_state, now=None):
    """Tinh trang thai moi tu danh sach nhom + trang thai cu. Tra ve (state, changes[list str])."""
    now = now or datetime.now()
    state = json.loads(json.dumps(prev_state, default=str))
    changes = []
    state["updated_at"] = _iso(now)
    if not groups:
        return state, changes

    all_pl = [g["pnl_per_lot"] for g in groups]
    mu_global, _ = _mean_std(all_pl) if len(all_pl) > 1 else (all_pl[0], 0)
    scale = sum(abs(x) for x in all_pl) / len(all_pl)

    # ---------- 1) DCA ----------
    dca = state["dca"]
    until = _parse(dca.get("disabled_until"))
    if not dca["enabled"] and until and now >= until:
        dca["enabled"] = True                      # het han -> cho thu lai, chi xet nhom MOI tu luc nay
        dca["ignore_before"] = _iso(now)
        changes.append("DCA: hết hạn tắt → BẬT lại thử nghiệm (cần ≥%d nhóm DCA mới để đánh giá lại)" % DCA_MIN_GROUPS)
    ib = _parse(dca.get("ignore_before"))
    dca_groups = [g["pnl"] for g in groups if g["n"] >= 2 and (ib is None or g["start"] >= ib)]
    if dca["enabled"] and len(dca_groups) >= DCA_MIN_GROUPS:
        m, sd = _mean_std(dca_groups)
        se = sd / math.sqrt(len(dca_groups))
        if m + DCA_Z * se < 0:
            dca["enabled"] = False
            dca["disabled_until"] = _iso(now + timedelta(days=DCA_DISABLE_DAYS))
            changes.append(f"DCA: TẮT {DCA_DISABLE_DAYS} ngày — {len(dca_groups)} nhóm có DCA lỗ TB "
                           f"{m:,.0f}/nhóm (khoảng tin cậy 90% vẫn < 0)")
    state["dca_stats"] = {"n_groups": len(dca_groups),
                          "mean": round(_mean_std(dca_groups)[0], 1) if dca_groups else None}

    # ---------- 2) Chan gio / pattern / nhom pattern ----------
    def process(key_name, bucket, keyfn, min_n, max_blocked, extra_ok=None):
        blocked = state[bucket]
        for k in list(blocked):                    # het han -> go chan, danh dau ignore_before
            exp = _parse(blocked[k].get("expires_at"))
            if exp and now >= exp:
                blocked.pop(k)
                state.setdefault("ignore_before_" + key_name, {})[str(k)] = _iso(now)
                changes.append(f"{key_name} {k}: hết hạn chặn → cho giao dịch lại để đánh giá từ đầu")
        ign = state.get("ignore_before_" + key_name, {})
        buckets = {}
        for g in groups:
            k = str(keyfn(g))
            if ign.get(k) and g["start"] < _parse(ign[k]):
                continue
            buckets.setdefault(k, []).append(g["pnl_per_lot"])
        cands = []
        for k, v in buckets.items():
            if k in blocked or len(v) < min_n:
                continue
            if extra_ok and not extra_ok(k):
                continue
            ev = _evaluate(v, mu_global, scale)
            if ev["bad"]:
                cands.append((ev["shrunk"], k, ev))
        cands.sort()                               # te nhat truoc
        for _, k, ev in cands:
            if len(blocked) >= max_blocked:
                break
            blocked[k] = {"since": _iso(now), "expires_at": _iso(now + timedelta(days=BLOCK_DAYS)), **ev}
            changes.append(f"{key_name} {k}: CHẶN {BLOCK_DAYS} ngày — n={ev['n']}, EV/lot={ev['mean']:,.0f}, "
                           f"EV co-giãn={ev['shrunk']:,.0f}, t={ev['t']}")

    window = range(TRADING_HOURS_START_VN, TRADING_HOURS_END_VN)

    def hour_ok(k):                                # chi chan gio nam trong khung giao dich, va luon chua lai gio
        h = int(k)
        open_left = len([x for x in window if str(x) not in state["blocked_hours"]])
        return h in window and open_left > MIN_OPEN_HOURS_LEFT

    process("giờ", "blocked_hours", lambda g: g["hour"], MIN_GROUPS_HOUR, MAX_BLOCKED_HOURS, hour_ok)
    process("pattern", "blocked_patterns", lambda g: g["pattern"], MIN_GROUPS_PATTERN, MAX_BLOCKED_PATTERNS)
    process("nhóm", "blocked_sources", lambda g: g["source"], MIN_GROUPS_SOURCE, MAX_BLOCKED_SOURCES)

    # ---------- 3) Suc khoe model ----------
    recent = sorted(groups, key=lambda g: g["start"])[-MODEL_HEALTH_WINDOW:]
    rho = _rank_corr([g["prob"] for g in recent], [g["pnl_per_lot"] for g in recent])
    was_bad = state.get("model_health", {}).get("uninformative", False)
    bad = rho is not None and rho <= MODEL_MIN_RANK_CORR and len(recent) >= 60
    state["model_health"] = {"n": len(recent), "rank_corr_prob_vs_pnl": None if rho is None else round(rho, 3),
                             "uninformative": bool(bad)}
    if bad and not was_bad:
        changes.append(f"MODEL: WinProb không còn phân biệt thắng/thua (rank-corr={rho:.2f} trên {len(recent)} nhóm) "
                       f"→ nên retrain/xem lại nhãn, KHÔNG nên tăng ngưỡng WinProb để 'lọc tốt hơn'")
    return state, changes


# ------------------------------------ API cho live_trader ------------------------------------
_state_cache = {"state": None, "loaded": None, "last_refresh": None}


def refresh_state(force: bool = False):
    """Goi dinh ky trong vong lap chinh. Tra ve list cac thay doi (de gui Telegram). Fail-open."""
    now = datetime.now()
    last = _state_cache["last_refresh"]
    if not force and last and (now - last).total_seconds() < REFRESH_MIN_INTERVAL_MIN * 60:
        return []
    _state_cache["last_refresh"] = now
    try:
        prev = _load_state()
        state, changes = compute_state(load_groups(), prev, now)
        _save_state(state)
        _state_cache["state"], _state_cache["loaded"] = state, now
        for c in changes:
            logger.info(f"[ADAPTIVE] {c}")
        return changes
    except Exception as e:
        logger.error(f"[ADAPTIVE] Lỗi cập nhật trạng thái (giữ nguyên, KHÔNG chặn giao dịch): {e}", exc_info=True)
        return []


def _state():
    s = _state_cache["state"]
    if s is None or (datetime.now() - _state_cache["loaded"]).total_seconds() > 300:
        s = _load_state()
        _state_cache["state"], _state_cache["loaded"] = s, datetime.now()
    return s


def _active(entry):
    exp = _parse(entry.get("expires_at"))
    return exp is None or datetime.now() < exp


def is_hour_blocked(hour_vn: int) -> bool:
    e = _state()["blocked_hours"].get(str(hour_vn))
    return bool(e and _active(e))


def is_pattern_blocked(pattern: str, source_type: str = None) -> bool:
    s = _state()
    e = s["blocked_patterns"].get(str(pattern))
    if e and _active(e):
        return True
    e = s["blocked_sources"].get(str(source_type)) if source_type else None
    return bool(e and _active(e))


def is_dca_allowed() -> bool:
    return bool(_state()["dca"].get("enabled", True))


# ------------------------------------ bao cao / dry-run ------------------------------------
def _print_report(groups, state, changes):
    print(f"Số nhóm đã đóng trong {LOOKBACK_DAYS} ngày: {len(groups)} | tổng P&L: {sum(g['pnl'] for g in groups):,.0f}")
    for lbl, sel in (("1 lệnh", lambda g: g["n"] == 1), ("2 lệnh (DCA)", lambda g: g["n"] == 2),
                     ("3 lệnh (DCA)", lambda g: g["n"] >= 3)):
        s = [g for g in groups if sel(g)]
        if s:
            print(f"  {lbl:14s} n={len(s):4d}  WR={sum(g['win'] for g in s)/len(s):.1%}  "
                  f"P&L={sum(g['pnl'] for g in s):>12,.0f}  TB/nhóm={sum(g['pnl'] for g in s)/len(s):>10,.0f}")
    print("Quyết định:" if changes else "Không có thay đổi nào.")
    for c in changes:
        print("  •", c)
    print("Model health:", state["model_health"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--days", type=int, default=LOOKBACK_DAYS)
    ap.add_argument("--dry-run", action="store_true", help="chi in bao cao, khong ghi state")
    a = ap.parse_args()
    grs = load_groups(a.db, a.days)
    st, ch = compute_state(grs, _default_state() if a.dry_run else _load_state())
    _print_report(grs, st, ch)
    if not a.dry_run:
        _save_state(st)
        print("Đã ghi", STATE_PATH)
