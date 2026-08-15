import pandas as pd
import numpy as np
from typing import Optional

class StockFeatures:
    """
    Computes stock-level features.

    Two families of methods are provided:
    1. Single/two-day comparison methods (calculate_ranks) used for rank-improvement
       tracking between "today" and "yesterday" snapshots (kept for backward
       compatibility with the M1 pipeline wiring).
    2. Multi-day rolling history methods (calculate_rolling_features) that require a
       stacked DataFrame of multiple trading days (trade_date, stock_id, close, volume,
       turnover, ...) sorted chronologically. All rolling windows use `min_periods`
       so that insufficient history returns NaN instead of a misleading value, and no
       lookahead is possible because every rolling window at day T only ever consumes
       rows with trade_date <= T (pandas rolling() is strictly backward-looking).
    """

    def __init__(self):
        pass

    def calculate_ranks(self,
                        df_current: pd.DataFrame,
                        df_previous: Optional[pd.DataFrame] = None,
                        penalty_value: int = 100) -> pd.DataFrame:
        if df_current.empty:
            return df_current

        df = df_current.copy()
        df["daily_return"] = (df["close"] - df["open"]) / df["open"]
        df["current_rank"] = df["daily_return"].rank(ascending=False, method="min").astype(int)

        if df_previous is not None and not df_previous.empty:
            prev_ranks = {}
            df_prev_calc = df_previous.copy()
            if "daily_return" not in df_prev_calc:
                df_prev_calc["daily_return"] = (df_prev_calc["close"] - df_prev_calc["open"]) / df_prev_calc["open"]
            df_prev_calc["prev_rank"] = df_prev_calc["daily_return"].rank(ascending=False, method="min").astype(int)

            for _, r in df_prev_calc.iterrows():
                prev_ranks[r["stock_id"]] = r["prev_rank"]

            max_prev_rank = max(prev_ranks.values()) if prev_ranks else 300

            improvements = []
            is_new_entries = []
            for _, row in df.iterrows():
                ticker = row["stock_id"]
                if ticker in prev_ranks:
                    improvements.append(prev_ranks[ticker] - row["current_rank"])
                    is_new_entries.append(0)
                else:
                    improvements.append((max_prev_rank + penalty_value) - row["current_rank"])
                    is_new_entries.append(1)

            df["rank_improvement"] = improvements
            df["is_new_entry"] = is_new_entries
        else:
            df["rank_improvement"] = 0
            df["is_new_entry"] = 1

        return df

    def calculate_technical_features(self, df_history: pd.DataFrame) -> pd.DataFrame:
        if df_history.empty:
            return df_history

        df = df_history.sort_values(["stock_id", "trade_date"]).copy()
        df["ma5"] = df.groupby("stock_id")["close"].transform(lambda x: x.rolling(5, min_periods=3).mean())
        df["ma20"] = df.groupby("stock_id")["close"].transform(lambda x: x.rolling(20, min_periods=10).mean())
        df["ma60"] = df.groupby("stock_id")["close"].transform(lambda x: x.rolling(60, min_periods=30).mean())

        df["vol_ma5"] = df.groupby("stock_id")["volume"].transform(lambda x: x.rolling(5, min_periods=3).mean())
        df["relative_volume"] = df["volume"] / (df["vol_ma5"] + 1e-8)

        return df

    def calculate_rolling_features(self, df_history: pd.DataFrame) -> pd.DataFrame:
        """
        Computes multi-day rolling stock features from a stacked history DataFrame.

        Required columns: trade_date, stock_id, close, volume, turnover
        (open/high are optional but used for daily_return / distance-to-high if present).

        Rolling windows and their `min_periods` (below which the feature is NaN, never
        backfilled or forward-filled):
          - vol_ma5 / vol_ma20: 5/20-day mean volume, min_periods=3/10
          - turnover_ma5 / turnover_ma20: 5/20-day mean turnover, min_periods=3/10
          - relative_volume_5d / relative_volume_20d: today's volume / rolling mean volume
          - high_20d: rolling 20-day high of `close` (min_periods=10)
          - dist_from_20d_high: (close - high_20d) / high_20d (<=0, 0 = at new high)
          - return_1d/3d/5d/10d/20d: percentage close-to-close returns over the window

        All rolling ops are computed per stock_id via groupby+transform and are strictly
        backward-looking (pandas rolling never uses rows after the current index), so
        truncating the input history to any earlier cutoff date T cannot change values
        computed for dates <= T (no future-function leakage).
        """
        if df_history.empty:
            return df_history

        df = df_history.sort_values(["stock_id", "trade_date"]).copy()

        if "daily_return" not in df.columns and "open" in df.columns:
            df["daily_return"] = (df["close"] - df["open"]) / df["open"]

        g_close = df.groupby("stock_id")["close"]
        g_volume = df.groupby("stock_id")["volume"]
        g_turnover = df.groupby("stock_id")["turnover"] if "turnover" in df.columns else None

        # Volume rolling means (min_periods enforced -> NaN when history insufficient)
        df["vol_ma5"] = g_volume.transform(lambda x: x.rolling(5, min_periods=3).mean())
        df["vol_ma20"] = g_volume.transform(lambda x: x.rolling(20, min_periods=10).mean())
        df["relative_volume_5d"] = df["volume"] / df["vol_ma5"]
        df["relative_volume_20d"] = df["volume"] / df["vol_ma20"]

        if g_turnover is not None:
            df["turnover_ma5"] = g_turnover.transform(lambda x: x.rolling(5, min_periods=3).mean())
            df["turnover_ma20"] = g_turnover.transform(lambda x: x.rolling(20, min_periods=10).mean())

            # Individual stock's share of its own group's daily turnover is computed at the
            # sector level (see SectorFeatures); here we just expose the stock's own rolling
            # turnover stats used as inputs to that calculation.

        # 20-day new-high distance. min_periods=10: fewer than 10 days of history -> NaN
        df["high_20d"] = g_close.transform(lambda x: x.rolling(20, min_periods=10).max())
        df["dist_from_20d_high"] = (df["close"] - df["high_20d"]) / df["high_20d"]

        # N-day returns (close today vs close N trading days ago). Requires at least N+1
        # observations for the stock, otherwise NaN (no synthetic/backfilled value).
        for n in (1, 3, 5, 10, 20):
            df[f"return_{n}d"] = g_close.transform(lambda x, n=n: x.pct_change(periods=n))

        return df
