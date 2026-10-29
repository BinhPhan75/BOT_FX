# ai_v5/telegram/chart_plotter.py
import os
import logging
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Chạy không cần GUI
import matplotlib.pyplot as plt
import mplfinance as mpf

logger = logging.getLogger("ai_chart_plotter")

def generate_signal_chart(candles_df: pd.DataFrame, symbol: str, pattern: str, entry: float, sl: float, tp: float, output_path: str = "temp_signal_v5.png") -> str:
    """
    Vẽ nến candlestick 30-50 nến gần nhất + các đường Entry, SL, TP và lưu thành file ảnh PNG.
    """
    try:
        df = candles_df.copy()
        if 'time' in df.columns:
            df['time'] = pd.to_datetime(df['time'], unit='s', errors='coerce')
            df.set_index('time', inplace=True)
            
        # Lấy 40 nến gần nhất để biểu đồ nhìn rõ nét
        df_sub = df.tail(40).copy()

        # Tạo màu sắc nến chuẩn TradingView (Tăng: Xanh green, Giảm: Đỏ)
        mc = mpf.make_marketcolors(
            up='#089981', down='#f23645',
            edge='inherit', wick='inherit', volume='in'
        )
        style = mpf.make_mpf_style(
            marketcolors=mc, gridcolor='#2a2e39',
            figcolor='#131722', facecolor='#131722',
            rc={'ytick.color': '#d1d4dc', 'xtick.color': '#d1d4dc'}
        )

        # Định vị các đường Entry, SL, TP
        hlines = dict(
            hlines=[entry, sl, tp],
            colors=['#2962ff', '#f23645', '#089981'],
            linestyle=['--', '--', '--'],
            linewidths=[1.5, 1.5, 1.5]
        )

        title = f"\n{symbol} | {pattern}"
        fig, axlist = mpf.plot(
            df_sub, type='candle', style=style,
            title=title, hlines=hlines,
            returnfig=True, figsize=(9, 5)
        )
        
        # Thêm chú thích cho các đường
        ax = axlist[0]
        ax.text(df_sub.index[-1], entry, f" Entry: {entry:.5f}", color='#2962ff', verticalalignment='center', fontweight='bold')
        ax.text(df_sub.index[-1], sl, f" SL: {sl:.5f}", color='#f23645', verticalalignment='center', fontweight='bold')
        ax.text(df_sub.index[-1], tp, f" TP: {tp:.5f}", color='#089981', verticalalignment='center', fontweight='bold')

        plt.savefig(output_path, bbox_inches='tight', dpi=150)
        plt.close(fig)
        return output_path
    except Exception as e:
        logger.error(f"Lỗi khi vẽ biểu đồ nến V5: {e}")
        return ""