"""
Margin trading (融資融券) feature expansion (M4, SPEC Chapter 8/10).

Computes, from a stacked multi-day margin-balance history (columns: trade_date,
stock_id, margin_balance, margin_buy, margin_sell, short_balance, ... any may be
NaN per row/stock, per B-02/M1's no-zero-fill contract):

  - margin_balance_chg_pct_{3,5}d: percentage change in margin_balance over the
    window (rolling pct_change equivalent), NaN if either endpoint is missing.
  - margin_usage_rate_proxy: margin_balance / margin_quota if a quota column is
    present, else margin_balance / margin_balance.rolling(20d max) as a coarse
    proxy (documented, not a real regulatory utilization rate) -- NaN if
    insufficient basis.
  - short_margin_ratio (券資比): short_balance / margin_balance, NaN if
    margin_balance is 0/missing (never divide-by-zero coerced to 0).

Null discipline: never fills missing history with 0.
"""

import numpy as np
import pandas as pd


class MarginFeatures:
    def __init__(self):
        pass

    def calculate_margin_change_features(self, df_margin_history: pd.DataFrame) -> pd.DataFrame:
        """
        Adds margin_balance_chg_pct_3d/5d and short_margin_ratio to a stacked
        multi-day margin history DataFrame, computed per stock_id via
        groupby+transform (strictly backward-looking, no future leakage).
        """
        if df_margin_history.empty:
            return df_margin_history

        df = df_margin_history.sort_values(["stock_id", "trade_date"]).copy()

        for col in ("margin_balance", "short_balance"):
            if col not in df.columns:
                df[col] = np.nan

        g_balance = df.groupby("stock_id")["margin_balance"]

        for window in (3, 5):
            df[f"margin_balance_chg_pct_{window}d"] = g_balance.transform(
                lambda x, w=window: x.pct_change(periods=w)
            )

        df["short_margin_ratio"] = np.where(
            (df["margin_balance"].isna()) | (df["margin_balance"] <= 0) | (df["short_balance"].isna()),
            np.nan,
            df["short_balance"] / df["margin_balance"],
        )

        return df

    def calculate_usage_rate_proxy(self, df_margin_history: pd.DataFrame,
                                    quota_col: str = "margin_quota") -> pd.DataFrame:
        """
        Adds `margin_usage_rate` = margin_balance / <quota_col> when a real quota
        column is present and non-null/non-zero for a row (this is the real
        regulatory utilization rate, e.g. TPEx's MarginPurchaseUtilizationRate).

        When no quota column is available at all, falls back to a documented
        PROXY: margin_balance / rolling-60-trading-day max(margin_balance) per
        stock (min_periods=20), labeled `margin_usage_rate_proxy` so downstream
        consumers cannot mistake it for the real regulatory rate. NaN when neither
        basis is available (never a fabricated 0/1).
        """
        if df_margin_history.empty:
            return df_margin_history

        df = df_margin_history.sort_values(["stock_id", "trade_date"]).copy()

        if quota_col in df.columns and df[quota_col].notna().any():
            df["margin_usage_rate"] = np.where(
                (df[quota_col].isna()) | (df[quota_col] <= 0) | (df["margin_balance"].isna()),
                np.nan,
                df["margin_balance"] / df[quota_col],
            )
        else:
            g_balance = df.groupby("stock_id")["margin_balance"]
            rolling_max = g_balance.transform(lambda x: x.rolling(60, min_periods=20).max())
            df["margin_usage_rate_proxy"] = np.where(
                (rolling_max.isna()) | (rolling_max <= 0) | (df["margin_balance"].isna()),
                np.nan,
                df["margin_balance"] / rolling_max,
            )

        return df
