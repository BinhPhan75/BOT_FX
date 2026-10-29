import os
import logging
import pandas as pd
import mplfinance as mpf
from ai_v5.config_ai import REPORTS_DIR

logger = logging.getLogger("telegram_chart")

def generate_signal_chart(df: pd.DataFrame, symbol: str, pattern_name: str, entry: float, sl: float, tp: float, lookback: int = 40) -> str:
    """
    Vẽ biểu đồ nến Japanese kèm theo đường Entry, SL, TP và lưu thành file ảnh tạm.
    """
    try:
        if df.empty or len(df) < 5:
            return ""

        # Lấy lookback nến gần nhất để biểu đồ rõ nét
        df_sub = df.tail(lookback).copy()

        # Đảm bảo index là DatetimeIndex cho mplfinance
        if 'time' in df_sub.columns:
            df_sub['time'] = pd.to_datetime(df_sub['time'])
            df_sub.set_index('time', inplace=True)

        # Chuẩn hóa tên cột
        df_sub.rename(columns={
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'volume': 'Volume'
        }, inplace=True)

        # Tạo đường nằm ngang cho Entry, SL, TP
        lines = []
        colors = []
        styles = []

        if entry > 0:
            lines.append(entry)
            colors.append('blue')
            styles.append('--')
        if sl > 0:
            lines.append(sl)
            colors.append('red')
            styles.append('-')
        if tp > 0:
            lines.append(tp)
            colors.append('green')
            styles.append('-')

        hlines_dict = dict(hlines=lines, colors=colors, linestyle=styles, linewidths=1.2) if lines else None

        # Phong cách biểu đồ custom
        mc = mpf.make_marketcolors(up='green', down='red', edge='inherit', wick='inherit', volume='in')
        s = mpf.make_mpf_style(marketcolors=mc, gridstyle=':', y_on_right=True)

        # Đường dẫn file ảnh đầu ra
        out_file = os.path.join(REPORTS_DIR, f"chart_{symbol}_{pattern_name}.png")

        # Tiến hành vẽ biểu đồ
        if hlines_dict:
            mpf.plot(
                df_sub,
                type='candle',
                style=s,
                hlines=hlines_dict,
                title=f"\nAI V5 SIGNAL: {symbol} - {pattern_name}",
                savefig=out_file,
                volume=False,
                figratio=(12, 7),
                figscale=1.1
            )
        else:
            mpf.plot(
                df_sub,
                type='candle',
                style=s,
                title=f"\nAI V5 SIGNAL: {symbol} - {pattern_name}",
                savefig=out_file,
                volume=False,
                figratio=(12, 7),
                figscale=1.1
            )

        if os.path.exists(out_file):
            return out_file
        return ""

    except Exception as e:
        logger.error(f"Lỗi khi vẽ biểu đồ tín hiệu cho {symbol}: {e}")
        return ""