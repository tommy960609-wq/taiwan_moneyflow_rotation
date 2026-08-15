import pandas as pd
import numpy as np
from typing import Dict, List, Optional

class SectorFeatures:
    """
    Computes sector (primary industry) and theme aggregate features for a single
    trading day, plus rolling relative-strength features across multiple days.

    P0-05 compliance (no double counting of turnover/volume):
      - `primary_sector` aggregates are computed once per stock (each stock belongs to
        exactly one primary_sector), so summing turnover across all primary sectors
        reproduces total market turnover with no double counting. These rows are
        flagged `may_double_count=False`.
      - `theme` aggregates (theme_1/theme_2/theme_3) intentionally allow a stock to be
        counted in multiple themes (a stock can have up to 3 themes), so summing
        turnover across themes can legitimately exceed total market turnover. These
        rows are flagged `may_double_count=True` so downstream consumers/report
        writers cannot silently misinterpret theme totals as a non-overlapping
        partition of the market.
    """

    def __init__(self):
        pass

    def calculate_sector_metrics(self,
                                 df_mapped_prices: pd.DataFrame,
                                 df_inst_flow: pd.DataFrame = pd.DataFrame()) -> pd.DataFrame:
        if df_mapped_prices.empty:
            return pd.DataFrame()

        df = df_mapped_prices.copy()

        if "daily_return" not in df:
            df["daily_return"] = (df["close"] - df["open"]) / df["open"]

        market_turnover_sum = df["turnover"].sum()
        market_median_return = df["daily_return"].median()

        if not df_inst_flow.empty:
            # Drop columns if they exist to prevent duplicates
            cols_to_drop = [c for c in ["foreign_net_buy", "investment_trust_net_buy", "dealer_net_buy"] if c in df.columns]
            if cols_to_drop:
                df = df.drop(columns=cols_to_drop)
            df = df.merge(df_inst_flow, on="stock_id", how="left")
            # B-02 compliance downstream behavior: DO NOT fillna with 0.0! Keep missing values as NaN (None)
        else:
            df["foreign_net_buy"] = np.nan
            df["investment_trust_net_buy"] = np.nan
            df["dealer_net_buy"] = np.nan

        sectors = df["primary_sector"].unique()
        sector_records = []

        for sector in sectors:
            if sector in ("待分類", "未分類"):
                continue

            sector_df = df[df["primary_sector"] == sector]
            record = self._build_group_record(
                group_df=sector_df,
                name=sector,
                group_type="primary",
                market_turnover_sum=market_turnover_sum,
                market_median_return=market_median_return,
                may_double_count=False,
            )
            if record is not None:
                sector_records.append(record)

        themes = set()
        for col in ["theme_1", "theme_2", "theme_3"]:
            if col in df.columns:
                themes.update(df[col].dropna().unique())

        for theme in themes:
            if not theme or str(theme).strip() == "":
                continue

            theme_df = df[(df["theme_1"] == theme) | (df["theme_2"] == theme) | (df["theme_3"] == theme)]
            record = self._build_group_record(
                group_df=theme_df,
                name=theme,
                group_type="theme",
                market_turnover_sum=market_turnover_sum,
                market_median_return=market_median_return,
                may_double_count=True,
            )
            if record is not None:
                sector_records.append(record)

        return pd.DataFrame(sector_records)

    def _build_group_record(self,
                             group_df: pd.DataFrame,
                             name: str,
                             group_type: str,
                             market_turnover_sum: float,
                             market_median_return: float,
                             may_double_count: bool) -> Optional[dict]:
        if group_df.empty:
            return None

        total_stocks = len(group_df)
        up_stocks = int((group_df["daily_return"] > 0).sum())
        # Real breadth (A-1 compliance): sector-up-count / full sector membership using
        # full-market data, NOT a leaderboard-derived proxy.
        breadth = up_stocks / total_stocks if total_stocks > 0 else np.nan

        group_turnover = group_df["turnover"].sum()
        volume_share = group_turnover / market_turnover_sum if market_turnover_sum > 0 else np.nan

        group_median_return = group_df["daily_return"].median()
        relative_strength_1d = group_median_return - market_median_return

        if group_turnover > 0:
            shares = (group_df["turnover"] / group_turnover).sort_values(ascending=False)
            hhi = float((shares ** 2).sum())
            top1_concentration = float(shares.iloc[0]) if len(shares) >= 1 else np.nan
            top3_concentration = float(shares.iloc[:3].sum()) if len(shares) >= 1 else np.nan
            top5_concentration = float(shares.iloc[:5].sum()) if len(shares) >= 1 else np.nan
        else:
            hhi = np.nan
            top1_concentration = np.nan
            top3_concentration = np.nan
            top5_concentration = np.nan

        group_volume = group_df["volume"].sum()

        valid_idx = group_df["foreign_net_buy"].dropna().index.union(group_df["investment_trust_net_buy"].dropna().index)
        if not valid_idx.empty:
            total_inst_buy = (group_df["foreign_net_buy"].fillna(0) + group_df["investment_trust_net_buy"].fillna(0)).sum()
            inst_flow_ratio = total_inst_buy / group_volume if group_volume > 0 else np.nan
        else:
            inst_flow_ratio = np.nan

        return {
            "sector_name": name,
            "sector_type": group_type,
            "may_double_count": may_double_count,
            "breadth": breadth,
            "volume_share": volume_share,
            "relative_strength": relative_strength_1d,
            "relative_strength_1d": relative_strength_1d,
            "hhi": hhi,
            "top1_concentration": top1_concentration,
            "top3_concentration": top3_concentration,
            "top5_concentration": top5_concentration,
            "inst_flow_ratio": inst_flow_ratio,
            "total_turnover": group_turnover,
            "stock_count": total_stocks,
            "up_stock_count": up_stocks,
        }

    def calculate_relative_strength_history(self, df_sector_history: pd.DataFrame) -> pd.DataFrame:
        """
        Adds 3-day and 5-day relative strength (rolling sum of the daily
        group_median_return - market_median_return series) to a stacked, multi-day
        sector-metrics history DataFrame (one row per sector_name per trade_date,
        must include `relative_strength_1d` and `trade_date`, sorted chronologically).

        min_periods equals the window size (3 or 5): fewer trading days of history for
        a given sector_name yields NaN rather than a partial/misleading sum. Because
        this is a rolling *sum* of already-realized daily relative strength values, it
        never looks ahead of the current trade_date.
        """
        if df_sector_history.empty or "relative_strength_1d" not in df_sector_history.columns:
            return df_sector_history

        df = df_sector_history.sort_values(["sector_name", "trade_date"]).copy()
        g = df.groupby("sector_name")["relative_strength_1d"]
        df["relative_strength_3d"] = g.transform(lambda x: x.rolling(3, min_periods=3).sum())
        df["relative_strength_5d"] = g.transform(lambda x: x.rolling(5, min_periods=5).sum())
        return df
