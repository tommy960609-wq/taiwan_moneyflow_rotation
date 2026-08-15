"""
Milestone 7 (Pitfall Pack), use B: 36-day cross-reconciliation between the user-collected
leaderboard's 漲跌幅 (return_pct) and this project's own FinMind-derived daily return.

BASIS MISMATCH (the task brief's explicit warning, confirmed real by inspecting both
sources' actual formulas):
  - Leaderboard 漲跌幅 (TWSE/TPEx standard convention): (close - prev_close) / prev_close
    -- i.e. PREVIOUS-CLOSE-to-CLOSE.
  - This project's own `daily_return` (src/stock_features.py line 32,
    src/sector_features.py line 35): (close - open) / open -- i.e. OPEN-to-CLOSE, a
    DIFFERENT, already-disclosed convention (see M3's acceptance report notes on
    `load_excel_leaderboard`'s pre-existing return-basis mismatch).

Comparing these two numbers directly would produce a meaningless "mismatch rate" driven
entirely by the basis difference, not genuine data-quality problems. This module instead
computes an INDEPENDENT prev-close-basis return straight from FinMind OHLCV
(close[t]/close[t-1] - 1, requiring the stock's own previous trading day's close to be
present in the same OHLCV history) and reconciles THAT against the leaderboard's
漲跌幅 -- an apples-to-apples comparison. The existing open-to-close `daily_return` is
reported alongside purely for transparency (so a reader can see how large the basis
effect itself would have been), never used as the primary reconciliation figure.

A deviation is flagged when |leaderboard_return_pct - finmind_prevclose_return_pct| >
DEVIATION_THRESHOLD_PCT (0.5 percentage points, per the task brief's explicit "超過 0.5%
偏差的比例是關鍵讀數" instruction).
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
from loguru import logger

DEVIATION_THRESHOLD_PCT = 0.5  # percentage points, per task brief.


def compute_finmind_prevclose_returns(df_ohlcv: pd.DataFrame) -> pd.DataFrame:
    """
    Given a stacked FinMind OHLCV history (stock_id, trade_date, close, ... one row per
    stock per trading day), returns [stock_id, trade_date, finmind_prevclose_return_pct]
    -- close-to-close % return computed strictly from each stock's own OWN prior row in
    the SAME frame (sorted by trade_date), never assuming calendar-adjacency. The first
    trading date on file for any stock has no prior close and gets NaN (not 0%,
    genuinely unknown/unavailable -- fail-closed).
    """
    if df_ohlcv.empty:
        return pd.DataFrame(columns=["stock_id", "trade_date", "finmind_prevclose_return_pct"])
    df = df_ohlcv.copy()
    df["stock_id"] = df["stock_id"].astype(str).str.strip()
    df = df.sort_values(["stock_id", "trade_date"])
    df["prev_close"] = df.groupby("stock_id")["close"].shift(1)
    # A zero/negative prev_close is a genuine upstream FinMind data anomaly (observed
    # live in this backfill), not a legitimate "no prior close" case -- computing a %
    # return against it would divide by zero (producing +/-inf, which would silently
    # poison any downstream mean/median). Treated the same as "no comparison available"
    # (NaN), never as a real return value.
    safe_prev_close = df["prev_close"].where(df["prev_close"] > 0)
    df["finmind_prevclose_return_pct"] = (
        (df["close"] - safe_prev_close) / safe_prev_close * 100.0
    )
    return df[["stock_id", "trade_date", "finmind_prevclose_return_pct"]]


def reconcile_leaderboard_vs_finmind(df_leaderboard: pd.DataFrame,
                                       df_ohlcv: pd.DataFrame,
                                       deviation_threshold_pct: float = DEVIATION_THRESHOLD_PCT) -> pd.DataFrame:
    """
    Inner-joins the leaderboard's (trade_date, stock_id, return_pct) against
    FinMind-derived prev-close-basis returns for the same (trade_date, stock_id), and
    computes the absolute deviation. Rows where FinMind has no prev_close (first date on
    file for that stock, or the stock isn't FinMind-backfilled at all) are excluded from
    the deviation statistics but counted separately as `no_finmind_comparison` so
    coverage is honestly reported, not silently treated as "0 deviation".
    """
    if df_leaderboard.empty:
        return pd.DataFrame()

    df_lb = df_leaderboard.copy()
    df_lb["stock_id"] = df_lb["stock_id"].astype(str).str.strip()

    df_fm = compute_finmind_prevclose_returns(df_ohlcv)

    merged = df_lb.merge(df_fm, on=["trade_date", "stock_id"], how="left")
    merged["has_finmind_comparison"] = merged["finmind_prevclose_return_pct"].notna()
    merged["abs_deviation_pct"] = (
        (merged["return_pct"] - merged["finmind_prevclose_return_pct"]).abs()
    )
    merged["deviation_exceeds_threshold"] = (
        merged["has_finmind_comparison"] & (merged["abs_deviation_pct"] > deviation_threshold_pct)
    )
    return merged


def summarize_reconciliation(df_reconciled: pd.DataFrame,
                              deviation_threshold_pct: float = DEVIATION_THRESHOLD_PCT) -> dict:
    """
    Headline reconciliation stats: total rows compared, coverage (rows with a FinMind
    prev-close comparison available), and the KEY READING per the task brief -- the
    fraction of compared rows whose |deviation| exceeds `deviation_threshold_pct`.
    """
    if df_reconciled.empty:
        return {
            "total_leaderboard_rows": 0, "rows_with_finmind_comparison": 0,
            "coverage_pct": None, "rows_exceeding_threshold": 0,
            "pct_exceeding_threshold": None, "deviation_threshold_pct": deviation_threshold_pct,
            "abs_deviation_median_pct": None, "abs_deviation_mean_pct": None,
        }
    total = len(df_reconciled)
    compared = df_reconciled[df_reconciled["has_finmind_comparison"]]
    n_compared = len(compared)
    n_exceed = int(compared["deviation_exceeds_threshold"].sum()) if n_compared else 0
    return {
        "total_leaderboard_rows": total,
        "rows_with_finmind_comparison": n_compared,
        "coverage_pct": round(n_compared / total, 4) if total else None,
        "rows_exceeding_threshold": n_exceed,
        "pct_exceeding_threshold": round(n_exceed / n_compared, 4) if n_compared else None,
        "deviation_threshold_pct": deviation_threshold_pct,
        "abs_deviation_median_pct": float(compared["abs_deviation_pct"].median()) if n_compared else None,
        "abs_deviation_mean_pct": float(compared["abs_deviation_pct"].mean()) if n_compared else None,
        "abs_deviation_max_pct": float(compared["abs_deviation_pct"].max()) if n_compared else None,
    }
