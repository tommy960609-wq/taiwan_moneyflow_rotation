"""
Institutional flow feature expansion (M4, SPEC Chapter 8.4 / 10.7, SPEC_ADDENDUM C-1).

Two levels of features:
  1. Individual-stock: 3/5/10/20-day cumulative net buy, consecutive-buy-day streak,
     buy-as-pct-of-volume, foreign+trust same-direction-buy flag.
  2. Sector-level aggregation: count of net-buying stocks, total net buy amount,
     net-buy as pct of sector turnover.

Plus C-1: investment-trust quarter-end window flag (季底作帳窗口), True for the last
5 trading days of March/June/September/December.

Null discipline (constitution 3.3 / BEHAVIOR_RULES #1): any calculation whose inputs
are missing/insufficient returns NaN/None, never 0. A stock with no institutional
row at all contributes NaN to every derived feature, not a zero net-buy.
"""

import numpy as np
import pandas as pd
from typing import Optional


QUARTER_END_MONTHS = (3, 6, 9, 12)
QUARTER_END_WINDOW_DAYS = 5


class InstitutionalFeatures:
    def __init__(self):
        pass

    # ---------------------------------------------------------------- individual

    def calculate_cumulative_features(self, df_inst_history: pd.DataFrame) -> pd.DataFrame:
        """
        Computes, per stock_id from a stacked multi-day institutional-flow history
        (columns: trade_date, stock_id, foreign_net_buy, investment_trust_net_buy,
        dealer_net_buy -- any may be NaN per row):

          - foreign_cum_{3,5,10,20}d / trust_cum_{3,5,10,20}d: rolling sums with
            min_periods = window size (NaN below that, never a partial sum passed
            off as the full window).
          - consecutive_buy_days: count of consecutive trailing trading days (ending
            today) where (foreign_net_buy + investment_trust_net_buy) > 0. Resets to
            0 the day net flow is <= 0 or missing. NaN for a day whose own combined
            net buy value is NaN (can't say whether that day was a "buy day").
          - foreign_trust_same_direction: True/False flag for whether foreign and
            trust both bought (>0) on that day; NaN if either side is missing.

        All rolling ops run per-stock via groupby+transform, strictly backward-
        looking (no future leakage): truncating the input to an earlier cutoff date
        cannot change any value computed for dates on/before that cutoff.
        """
        if df_inst_history.empty:
            return df_inst_history

        df = df_inst_history.sort_values(["stock_id", "trade_date"]).copy()

        for col in ("foreign_net_buy", "investment_trust_net_buy", "dealer_net_buy"):
            if col not in df.columns:
                df[col] = np.nan

        g_foreign = df.groupby("stock_id")["foreign_net_buy"]
        g_trust = df.groupby("stock_id")["investment_trust_net_buy"]

        for window in (3, 5, 10, 20):
            df[f"foreign_cum_{window}d"] = g_foreign.transform(
                lambda x, w=window: x.rolling(w, min_periods=w).sum()
            )
            df[f"trust_cum_{window}d"] = g_trust.transform(
                lambda x, w=window: x.rolling(w, min_periods=w).sum()
            )

        # combined net buy per day (NaN only if BOTH foreign and trust are NaN that day)
        both_nan = df["foreign_net_buy"].isna() & df["investment_trust_net_buy"].isna()
        combined = df["foreign_net_buy"].fillna(0) + df["investment_trust_net_buy"].fillna(0)
        df["_combined_net_buy"] = np.where(both_nan, np.nan, combined)

        df["consecutive_buy_days"] = df.groupby("stock_id")["_combined_net_buy"].transform(
            self._consecutive_buy_streak
        )

        df["foreign_trust_same_direction"] = np.where(
            df["foreign_net_buy"].isna() | df["investment_trust_net_buy"].isna(),
            np.nan,
            (df["foreign_net_buy"] > 0) & (df["investment_trust_net_buy"] > 0),
        )

        df = df.drop(columns=["_combined_net_buy"])
        return df

    @staticmethod
    def _consecutive_buy_streak(series: pd.Series) -> pd.Series:
        """
        Per-row trailing consecutive-buy-day count (>0 counts as a buy day; a day
        with NaN net buy breaks the streak into NaN for that row and resets the
        counter for subsequent days rather than silently propagating a stale streak).
        """
        result = []
        streak = 0
        for val in series:
            if pd.isna(val):
                result.append(np.nan)
                streak = 0
            elif val > 0:
                streak += 1
                result.append(streak)
            else:
                streak = 0
                result.append(0)
        return pd.Series(result, index=series.index)

    def calculate_buy_pct_of_volume(self, df_inst_day: pd.DataFrame, df_price_day: pd.DataFrame) -> pd.DataFrame:
        """
        Adds `inst_buy_pct_of_volume` = (foreign_net_buy + investment_trust_net_buy)
        / volume for a single trading day, merging institutional flow onto price
        volume by stock_id. NaN when either side is missing or volume is 0 (never
        divide-by-zero silently coerced to 0).
        """
        if df_inst_day.empty or df_price_day.empty:
            return df_inst_day

        merged = df_inst_day.merge(
            df_price_day[["stock_id", "volume"]], on="stock_id", how="left"
        )
        both_nan = merged["foreign_net_buy"].isna() & merged["investment_trust_net_buy"].isna()
        combined = merged["foreign_net_buy"].fillna(0) + merged["investment_trust_net_buy"].fillna(0)
        combined = np.where(both_nan, np.nan, combined)

        merged["inst_buy_pct_of_volume"] = np.where(
            (merged["volume"].isna()) | (merged["volume"] <= 0),
            np.nan,
            combined / merged["volume"],
        )
        return merged

    # ------------------------------------------------------------------- C-1

    def flag_quarter_end_window(self, trading_dates: pd.Series) -> pd.Series:
        """
        Returns a boolean Series (same index as `trading_dates`) marking whether
        each date falls within the last QUARTER_END_WINDOW_DAYS (5) *trading* days
        of a quarter-end month (Mar/Jun/Sep/Dec), per SPEC_ADDENDUM C-1
        (投信季底作帳窗口旗標 quarter_end_window=True). Determined using only the
        set of trading dates actually present within that stock's/market's own
        quarter-end month slice (no external trading-calendar dependency), so it
        is robust to holidays.
        """
        dates = pd.to_datetime(trading_dates)
        df = pd.DataFrame({"date": dates})
        df["year_month"] = df["date"].dt.to_period("M")
        df["month"] = df["date"].dt.month

        flags = pd.Series(False, index=trading_dates.index)
        for ym, group in df.groupby("year_month"):
            if group["month"].iloc[0] not in QUARTER_END_MONTHS:
                continue
            sorted_group = group.sort_values("date")
            last_n_idx = sorted_group.index[-QUARTER_END_WINDOW_DAYS:]
            flags.loc[last_n_idx] = True
        return flags

    # ------------------------------------------------------------------ sector

    def aggregate_sector_institutional(self, df_stock_inst: pd.DataFrame,
                                        df_mapped_prices: pd.DataFrame) -> pd.DataFrame:
        """
        Aggregates individual-stock institutional flow (foreign_net_buy +
        investment_trust_net_buy, i.e. "外資+投信合計") up to primary_sector level:
          - net_buying_stock_count: count of stocks in the sector with combined
            net buy > 0 (only counting stocks with non-missing data).
          - sector_net_buy_total: sum of combined net buy across stocks with data
            (NaN if no stock in the sector has any institutional data at all).
          - sector_net_buy_pct_of_turnover: sector_net_buy_total / sector turnover.

        Requires df_mapped_prices to carry `primary_sector` and `turnover` per
        stock_id (output of IndustryMapper.map_dataframe). Sectors with zero stocks
        carrying institutional data get NaN aggregates, never 0.
        """
        if df_stock_inst.empty or df_mapped_prices.empty:
            return pd.DataFrame()

        merged = df_mapped_prices[["stock_id", "primary_sector", "turnover"]].merge(
            df_stock_inst[["stock_id", "foreign_net_buy", "investment_trust_net_buy"]],
            on="stock_id", how="left",
        )
        both_nan = merged["foreign_net_buy"].isna() & merged["investment_trust_net_buy"].isna()
        merged["_combined"] = np.where(
            both_nan, np.nan,
            merged["foreign_net_buy"].fillna(0) + merged["investment_trust_net_buy"].fillna(0),
        )

        records = []
        for sector, group in merged.groupby("primary_sector"):
            if sector in ("待分類", "未分類"):
                continue
            valid = group.dropna(subset=["_combined"])
            if valid.empty:
                records.append({
                    "sector_name": sector,
                    "net_buying_stock_count": np.nan,
                    "sector_net_buy_total": np.nan,
                    "sector_net_buy_pct_of_turnover": np.nan,
                })
                continue
            net_buy_total = valid["_combined"].sum()
            net_buying_count = int((valid["_combined"] > 0).sum())
            sector_turnover = group["turnover"].sum()
            pct_of_turnover = net_buy_total / sector_turnover if sector_turnover > 0 else np.nan
            records.append({
                "sector_name": sector,
                "net_buying_stock_count": net_buying_count,
                "sector_net_buy_total": net_buy_total,
                "sector_net_buy_pct_of_turnover": pct_of_turnover,
            })

        return pd.DataFrame(records)
