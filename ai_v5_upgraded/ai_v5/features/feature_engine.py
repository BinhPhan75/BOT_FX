"""
=========================================================
XuTho AI V5
Feature Engine
=========================================================
Chuyển dữ liệu giao dịch thành Feature Dataset
"""

import pandas as pd


class FeatureEngine:

    def __init__(self, df: pd.DataFrame):

        self.df = df.copy()

    # -------------------------------------------------

    def process(self):

        df = self.df.copy()

        print(f"Input Trades : {len(df)}")

        # ==========================
        # Direction
        # ==========================

        df["is_buy"] = (
            df["direction"]
            .astype(str)
            .str.upper()
            .eq("BUY")
            .astype(int)
        )

        df["is_sell"] = (
            df["direction"]
            .astype(str)
            .str.upper()
            .eq("SELL")
            .astype(int)
        )

        # ==========================
        # Result
        # ==========================

        df["label"] = (
            df["result"]
            .astype(str)
            .str.upper()
            .eq("WIN")
            .astype(int)
        )

        # ==========================
        # Session
        # ==========================

        session = pd.get_dummies(
            df["session"],
            prefix="session"
        )

        df = pd.concat(
            [
                df,
                session
            ],
            axis=1
        )

        # ==========================
        # Pattern
        # ==========================

        pattern = pd.get_dummies(
            df["pattern"],
            prefix="pattern"
        )

        df = pd.concat(
            [
                df,
                pattern
            ],
            axis=1
        )

        print(
            "Feature Columns :",
            len(df.columns)
        )

        return df