"""
Milestone 7 (Pitfall Pack), use A: 漲停家數/連續漲停 (limit-up-count / consecutive-
limit-up) historical series built from the user-collected 36-day leaderboard
(src/leaderboard_loader.py), feeding the OVERHEAT RISK sub-factor `src/sector_scoring.py`
has explicitly disclosed as unimplemented since M2 ("Factors requiring data not yet
wired into the pipeline (consecutive-limit-up counts, upper-shadow candle ratios,
institutional-selling reversal) are intentionally NOT approximated here").

IMPORTANT scope decision (per this project's own "先 observe 後 active" data-driven
iteration rule and governance rule #9 "不碰確定性護城河...未經拍板一行不改"): this
module is OBSERVE-ONLY. It computes and persists the limit-up-count series as a new,
additive, disclosed dataset -- it does NOT modify `src/sector_scoring.py`'s
`_compute_overheat_risk` formula or `OVERHEAT_SUBWEIGHTS` (an already-accepted M2 scoring
weight contract this task's own instruction says not to change: "禁改已驗收模組既有
行為...其餘加參數預設不變"). Wiring this into the LIVE overheat_risk score is a future
milestone's decision after this observe-only series has been reviewed, exactly like
every other new signal in this project's history (SPEC's own "新機制一律先 observe 後
active").

Two aggregation levels (task brief):
  - Market-wide: daily count of leaderboard rows with limit_up_proxy=True (out of the
    top-300 by return -- NOT the full market universe; the leaderboard only ever lists
    the top 300 gainers, so a day with fewer than N limit-up stocks captures all of them
    exactly, but this is disclosed as `leaderboard_universe_note` since it CANNOT prove
    "zero limit-up stocks outside the top 300" logically, only observationally always-true
    in practice since a real limit-up stock (+10%) will essentially always rank inside
    a 300-deep same-day gainer leaderboard).
  - Sector-level: joins leaderboard stock_ids against this project's own
    `data/reference/stock_industry_mapping` (primary_sector) to aggregate limit-up counts
    per (trade_date, primary_sector). Stocks not yet mapped are counted separately under
    "未分類" (never silently dropped or misattributed to a sector).

Consecutive-limit-up: for each stock, the run-length of consecutive TRADE DATES (not
calendar days) on which it appeared in the leaderboard with limit_up_proxy=True,
resetting to 0 the moment the stock either drops out of the leaderboard for a date (rank
> 300 that day, or the day isn't limit-up) or the top-300 report for a date wasn't
collected at all (a GAP in the 36-day sample, e.g. 2026-06-17..06-26 is entirely absent
from the 36 files) -- a gap must not be silently bridged as if the streak continued
uninterrupted through days we have no evidence for.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
from loguru import logger

from src.leaderboard_loader import flag_limit_up_proxy


def build_market_wide_limit_up_series(df_leaderboard: pd.DataFrame) -> pd.DataFrame:
    """Returns [trade_date, limit_up_count, sample_size] -- one row per trade_date
    present in `df_leaderboard`. sample_size is always 300 for this dataset (top-300
    leaderboard), included so a reader never mistakes this for "300 = full market"."""
    if df_leaderboard.empty:
        return pd.DataFrame(columns=["trade_date", "limit_up_count", "sample_size"])
    df = flag_limit_up_proxy(df_leaderboard)
    out = df.groupby("trade_date").agg(
        limit_up_count=("limit_up_proxy", "sum"),
        sample_size=("stock_id", "count"),
    ).reset_index()
    out["limit_up_count"] = out["limit_up_count"].astype(int)
    return out.sort_values("trade_date").reset_index(drop=True)


def build_sector_limit_up_series(df_leaderboard: pd.DataFrame,
                                   df_mapping: pd.DataFrame,
                                   sector_col: str = "primary_sector") -> pd.DataFrame:
    """
    Returns [trade_date, sector_name, limit_up_count, total_in_leaderboard] aggregated
    by joining the leaderboard's stock_id against `df_mapping` (this project's own
    stock_industry_mapping reference; expects a `stock_id` and `sector_col` column).
    Unmapped stocks (no match in df_mapping, or mapping value is null) are grouped under
    the literal sector_name "未分類" rather than dropped -- so the sum of per-sector
    counts always reconciles exactly to the market-wide total for that date.
    """
    if df_leaderboard.empty:
        return pd.DataFrame(columns=["trade_date", "sector_name", "limit_up_count", "total_in_leaderboard"])
    df = flag_limit_up_proxy(df_leaderboard).copy()
    df["stock_id"] = df["stock_id"].astype(str).str.strip()

    if df_mapping is None or df_mapping.empty or "stock_id" not in df_mapping.columns:
        df["sector_name"] = "未分類"
    else:
        map_slim = df_mapping[["stock_id", sector_col]].copy()
        map_slim["stock_id"] = map_slim["stock_id"].astype(str).str.strip()
        map_slim = map_slim.rename(columns={sector_col: "sector_name"})
        df = df.merge(map_slim, on="stock_id", how="left")
        df["sector_name"] = df["sector_name"].fillna("未分類")

    out = df.groupby(["trade_date", "sector_name"]).agg(
        limit_up_count=("limit_up_proxy", "sum"),
        total_in_leaderboard=("stock_id", "count"),
    ).reset_index()
    out["limit_up_count"] = out["limit_up_count"].astype(int)
    return out.sort_values(["trade_date", "sector_name"]).reset_index(drop=True)


def compute_consecutive_limit_up_streaks(df_leaderboard: pd.DataFrame,
                                           threshold_pct: float = None) -> pd.DataFrame:
    """
    Returns [stock_id, trade_date, consecutive_limit_up_days] -- for each stock, on each
    trade_date it appears in the leaderboard as limit_up_proxy=True, the run-length of
    consecutive TRADE DATES (as observed in this 36-day sample, not calendar dates) it
    has been limit-up including today. Resets to 0 (i.e. the stock is simply absent from
    the output for that date, since a non-limit-up day contributes nothing to a streak)
    whenever the stock is not limit-up on some intervening leaderboard date, OR whenever
    there is a GAP between two consecutive leaderboard dates in the sample itself (a date
    with no collected report at all) -- gaps never silently bridge a streak.
    """
    from src.leaderboard_loader import LIMIT_UP_PROXY_THRESHOLD_PCT
    threshold_pct = threshold_pct if threshold_pct is not None else LIMIT_UP_PROXY_THRESHOLD_PCT

    if df_leaderboard.empty:
        return pd.DataFrame(columns=["stock_id", "trade_date", "consecutive_limit_up_days"])

    df = flag_limit_up_proxy(df_leaderboard, threshold_pct).copy()
    df["stock_id"] = df["stock_id"].astype(str).str.strip()

    all_dates_sorted = sorted(df["trade_date"].unique().tolist())
    date_order = {d: i for i, d in enumerate(all_dates_sorted)}

    rows = []
    for stock_id, group in df.groupby("stock_id"):
        g = group.sort_values("trade_date")
        streak = 0
        prev_date_idx = None
        for _, r in g.iterrows():
            cur_idx = date_order[r["trade_date"]]
            is_up = bool(r["limit_up_proxy"])
            # A gap in the LEADERBOARD SAMPLE ITSELF (not just this stock's absence)
            # between the previous observed date and this one breaks the streak --
            # we have no evidence about the missing dates.
            contiguous_sample = (prev_date_idx is not None and cur_idx == prev_date_idx + 1)
            if is_up:
                streak = streak + 1 if contiguous_sample and streak > 0 else 1
                rows.append({"stock_id": stock_id, "trade_date": r["trade_date"],
                             "consecutive_limit_up_days": streak})
            else:
                streak = 0
            prev_date_idx = cur_idx

    return pd.DataFrame(rows, columns=["stock_id", "trade_date", "consecutive_limit_up_days"])
