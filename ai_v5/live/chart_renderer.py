# ai_v5/live/chart_renderer.py
"""
Ve chart nen (candlestick) kem vung Entry/SL/TP cho 1 tin hieu AI v5, tra ve
PNG bytes de gui qua Telegram sendPhoto - muc dich lam thong bao AI v5 truc
quan giong bot v4 (v4 gui kem anh chart trong watcher.py).

Khong phu thuoc mplfinance (co the chua duoc cai san tren VPS) - chi dung
matplotlib thuan, tu ve nen bang Rectangle/Line2D de giam rui ro thieu thu vien.

Cach dung:
    from ai_v5.live.chart_renderer import render_pattern_chart
    png_bytes = render_pattern_chart(
        candles=candles,           # list dict OHLCV, da co san trong live_trader.py
        symbol=symbol, pattern=pattern_name, direction=direction,
        entry=entry, sl=sl, tp=tp, lookback=60,
    )
    # png_bytes la None neu ve loi (vi du thieu matplotlib) - luon kiem tra truoc khi gui
"""
import io
import logging

logger = logging.getLogger("ai_v5_chart_renderer")

try:
    import matplotlib
    matplotlib.use("Agg")  # khong can GUI/display tren VPS
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    _MATPLOTLIB_OK = True
except Exception as e:
    _MATPLOTLIB_OK = False
    logger.warning(f"matplotlib không khả dụng ({e}) — chart_renderer sẽ trả về None, "
                   f"Telegram AI v5 sẽ chỉ gửi text, không kèm ảnh.")


def render_pattern_chart(candles: list, symbol: str, pattern: str, direction: str,
                          entry: float, sl: float, tp: float, lookback: int = 60) -> bytes:
    """
    candles: list dict {"time","open","high","low","close",...}, da sap xep TANG DAN,
             candles[-1] la nen da dong gan nhat (giong dinh dang dung trong
             live_pattern_scanner.py).
    Tra ve: PNG bytes, hoac None neu khong ve duoc (vi du thieu matplotlib).
    """
    if not _MATPLOTLIB_OK:
        return None
    if not candles:
        return None

    try:
        data = candles[-lookback:] if len(candles) > lookback else candles
        n = len(data)

        fig, ax = plt.subplots(figsize=(9, 5.5), dpi=130)

        up_color = "#26a69a"
        down_color = "#ef5350"
        width = 0.6
        wick_width = 0.08

        for idx, c in enumerate(data):
            o, h, l, cl = c["open"], c["high"], c["low"], c["close"]
            color = up_color if cl >= o else down_color
            # Bóng nến (wick)
            ax.add_patch(Rectangle((idx - wick_width / 2, min(o, cl)), wick_width,
                                    max(abs(h - max(o, cl)), 0.0000001) + abs(h - l), alpha=0))  # placeholder no-op
            ax.plot([idx, idx], [l, h], color=color, linewidth=1, zorder=2)
            # Thân nến
            body_bottom = min(o, cl)
            body_height = max(abs(cl - o), (h - l) * 0.01)  # tránh thân nến cao=0 khi doji
            ax.add_patch(Rectangle((idx - width / 2, body_bottom), width, body_height,
                                    facecolor=color, edgecolor=color, zorder=3))

        # Đường Entry / SL / TP
        line_specs = [
            (entry, "#42a5f5", "Entry", "-"),
            (sl, "#ef5350", "SL", "--"),
            (tp, "#26a69a", "TP", "--"),
        ]
        for level, color, label, style in line_specs:
            if level is None:
                continue
            ax.axhline(level, color=color, linestyle=style, linewidth=1.3, zorder=1)
            ax.text(n - 1 + 0.6, level, f"{label} {level:.5g}", color=color,
                    fontsize=9, va="center", fontweight="bold")

        title_dir = "BUY ▲" if direction == "BUY" else "SELL ▼"
        ax.set_title(f"{symbol} — {pattern} — {title_dir}", fontsize=12, fontweight="bold", loc="left")
        ax.set_xlim(-1, n + 4)
        ax.set_xticks([])
        ax.grid(axis="y", alpha=0.25, linewidth=0.5)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)

        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor="white")
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    except Exception as e:
        logger.warning(f"Vẽ chart thất bại ({symbol}/{pattern}): {e}", exc_info=True)
        return None
