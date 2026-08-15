"""
Benchmark models for Research Ready gating (SPEC_ADDENDUM A-3, docs/signal_definitions.md
section 3). Two baselines, both computed purely from the same on-disk artifacts the
event-study backtester uses (per-day sector_scored frames + FinMind OHLCV + TAIEX):

1. Momentum Extension Baseline (動能延續基準): every trading day, "buy" the single
   sector with the highest `score` on the PRIOR day (T-1), hold K days from T's T+1
   open (same entry convention as the real signals, so the comparison is apples-to-
   apples on execution timing). This is a daily-rebalanced heuristic, not an event
   study -- it produces one observation per trading day in the range, not one per
   signal event.

2. Random Sector Bootstrap Baseline (隨機族群基準): for each of N bootstrap draws, pick
   a uniformly random (sector_name, sector_type, trade_date) triple from the full
   available universe and compute its forward K-day return the same way. Repeated N
   times per horizon to build an empirical return distribution (SPEC_ADDENDUM 3.2 says
   N=10,000; this module defaults to a smaller number for fast unit tests and exposes N
   as a parameter so the real report run can use the full 10,000 -- always disclosed in
   the report, never silently substituted).

Both are used purely as a comparison base -- SPEC_ADDENDUM A-3.3: "新起漲/續漲訊號的超
額報酬必須顯著優於動能延續基準,否則判定「無增量價值」,不得標 Research Ready." This
module does NOT decide Research Ready status itself (that's a report-level judgment,
made explicitly in the acceptance report text, not silently encoded as a boolean here).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from src.backtester import (
    HORIZONS_DAYS,
    compute_entry_price,
    compute_market_forward_returns,
    compute_sector_forward_returns,
    resolve_sector_member_stock_ids,
    index_ohlcv_by_stock,
    EVENT_STATUS_TRADABLE,
)


def momentum_extension_baseline(df_sector_scored_by_date: Dict[str, pd.DataFrame],
                                 df_stock_scored_by_date: Dict[str, pd.DataFrame],
                                 df_ohlcv_history: pd.DataFrame,
                                 df_taiex: pd.DataFrame,
                                 horizons: Sequence[int] = HORIZONS_DAYS) -> pd.DataFrame:
    """
    One row per trading day T (for every T in df_sector_scored_by_date that has a T-1
    scored day immediately before it in the sorted date list): identifies the
    highest-`score` sector as of T-1, "buys" it at T's T+1 open (mirrors the real
    signal's entry-timing convention -- T-1's already-known score used to pick a T-day
    action, filled the next day), holds `horizons` days, records gross sector/market
    returns and excess. Ties on score are broken by (sector_type, sector_name)
    lexicographic order for determinism (documented, not hidden).

    Sectors with all-NaN score (score column entirely missing/NaN that day) are
    excluded from the "strongest sector" selection -- never treated as score=0, which
    would bias toward selecting genuinely-unscored/degraded rows.
    """
    ohlcv_idx = index_ohlcv_by_stock(df_ohlcv_history) if isinstance(df_ohlcv_history, pd.DataFrame) else df_ohlcv_history
    dates = sorted(df_sector_scored_by_date.keys())
    rows = []
    for i in range(1, len(dates)):
        prior_date = dates[i - 1]
        action_date = dates[i]
        df_prior = df_sector_scored_by_date.get(prior_date, pd.DataFrame())
        if df_prior.empty or "score" not in df_prior.columns:
            continue
        scored = df_prior.dropna(subset=["score"])
        if scored.empty:
            continue
        scored = scored.sort_values(
            ["score", "sector_type", "sector_name"], ascending=[False, True, True]
        )
        top = scored.iloc[0]
        sector_name, sector_type = top["sector_name"], top.get("sector_type", "primary")

        df_stock_scored = df_stock_scored_by_date.get(action_date, pd.DataFrame())
        member_ids = resolve_sector_member_stock_ids(sector_name, sector_type, df_stock_scored)
        if not member_ids:
            continue

        entry_infos = {sid: compute_entry_price(sid, action_date, ohlcv_idx, "exclude")
                        for sid in member_ids}
        tradable_ids = [sid for sid, info in entry_infos.items() if info["status"] == EVENT_STATUS_TRADABLE]
        if not tradable_ids:
            continue
        entry_dates = [entry_infos[sid]["entry_date"] for sid in tradable_ids]
        entry_date_for_market = max(set(entry_dates), key=entry_dates.count)
        entry_prices = {sid: entry_infos[sid]["entry_price"] for sid in tradable_ids}

        sector_rets = compute_sector_forward_returns(tradable_ids, entry_date_for_market,
                                                       entry_prices, ohlcv_idx, horizons)
        market_rets = compute_market_forward_returns(entry_date_for_market, df_taiex, horizons)

        row = {
            "decision_date": prior_date, "action_date": action_date,
            "sector_name": sector_name, "sector_type": sector_type,
            "prior_score": float(top["score"]),
        }
        for k in horizons:
            row[f"return_{k}d"] = sector_rets[k]
            row[f"market_return_{k}d"] = market_rets[k]
            row[f"excess_return_{k}d"] = (
                sector_rets[k] - market_rets[k]
                if sector_rets[k] is not None and market_rets[k] is not None else None
            )
        rows.append(row)
    return pd.DataFrame(rows)


def random_sector_bootstrap_baseline(df_sector_scored_by_date: Dict[str, pd.DataFrame],
                                      df_stock_scored_by_date: Dict[str, pd.DataFrame],
                                      df_ohlcv_history: pd.DataFrame,
                                      df_taiex: pd.DataFrame,
                                      n_draws: int = 1000,
                                      horizons: Sequence[int] = HORIZONS_DAYS,
                                      random_seed: int = 42) -> pd.DataFrame:
    """
    Draws `n_draws` uniformly-random (sector_name, sector_type, trade_date) triples from
    the full (date -> available sectors) universe, computes each draw's forward K-day
    sector/market return the same way the momentum baseline does. `random_seed` is fixed
    (default 42, matching this project's existing reproducibility convention in
    scripts/create_demo_data.py) so a report is exactly reproducible; the seed used is
    always recorded in the returned frame's attrs and disclosed in the report text.

    SPEC_ADDENDUM 3.2 specifies N=10,000 for the real report; this defaults to 1,000 to
    keep unit tests fast -- callers building the real report must pass n_draws=10000
    explicitly (scripts/run_backtest.py does), never silently relying on this default.
    """
    ohlcv_idx = index_ohlcv_by_stock(df_ohlcv_history) if isinstance(df_ohlcv_history, pd.DataFrame) else df_ohlcv_history
    rng = np.random.default_rng(random_seed)
    universe: List[tuple] = []
    for date, df in df_sector_scored_by_date.items():
        if df.empty:
            continue
        for _, r in df[["sector_name", "sector_type"]].drop_duplicates().iterrows():
            universe.append((date, r["sector_name"], r.get("sector_type", "primary")))

    if not universe:
        out = pd.DataFrame()
        out.attrs["random_seed"] = random_seed
        out.attrs["n_draws_requested"] = n_draws
        out.attrs["universe_size"] = 0
        return out

    draw_indices = rng.integers(0, len(universe), size=n_draws)
    rows = []
    for di in draw_indices:
        date, sector_name, sector_type = universe[int(di)]
        df_stock_scored = df_stock_scored_by_date.get(date, pd.DataFrame())
        member_ids = resolve_sector_member_stock_ids(sector_name, sector_type, df_stock_scored)
        if not member_ids:
            continue
        entry_infos = {sid: compute_entry_price(sid, date, ohlcv_idx, "exclude")
                        for sid in member_ids}
        tradable_ids = [sid for sid, info in entry_infos.items() if info["status"] == EVENT_STATUS_TRADABLE]
        if not tradable_ids:
            continue
        entry_dates = [entry_infos[sid]["entry_date"] for sid in tradable_ids]
        entry_date_for_market = max(set(entry_dates), key=entry_dates.count)
        entry_prices = {sid: entry_infos[sid]["entry_price"] for sid in tradable_ids}

        sector_rets = compute_sector_forward_returns(tradable_ids, entry_date_for_market,
                                                       entry_prices, ohlcv_idx, horizons)
        market_rets = compute_market_forward_returns(entry_date_for_market, df_taiex, horizons)
        row = {"draw_date": date, "sector_name": sector_name, "sector_type": sector_type}
        for k in horizons:
            row[f"return_{k}d"] = sector_rets[k]
            row[f"market_return_{k}d"] = market_rets[k]
            row[f"excess_return_{k}d"] = (
                sector_rets[k] - market_rets[k]
                if sector_rets[k] is not None and market_rets[k] is not None else None
            )
        rows.append(row)

    out = pd.DataFrame(rows)
    out.attrs["random_seed"] = random_seed
    out.attrs["n_draws_requested"] = n_draws
    out.attrs["n_draws_resolved"] = len(rows)
    out.attrs["universe_size"] = len(universe)
    return out


def bootstrap_confidence_interval(values: Sequence[float], n_resamples: int = 1000,
                                   ci: float = 0.90, random_seed: int = 42) -> Dict[str, Optional[float]]:
    """
    Simple percentile bootstrap CI of the mean of `values` (SPEC 19.4's "Bootstrap信賴區間").
    Returns {"mean": ..., "ci_low": ..., "ci_high": ..., "n": ...}; all None if `values`
    is empty (never fabricates a CI from zero data).
    """
    vals = np.array([v for v in values if v is not None and not (isinstance(v, float) and np.isnan(v))])
    if len(vals) == 0:
        return {"mean": None, "ci_low": None, "ci_high": None, "n": 0}
    rng = np.random.default_rng(random_seed)
    means = np.array([rng.choice(vals, size=len(vals), replace=True).mean() for _ in range(n_resamples)])
    alpha = (1 - ci) / 2
    return {
        "mean": float(vals.mean()),
        "ci_low": float(np.quantile(means, alpha)),
        "ci_high": float(np.quantile(means, 1 - alpha)),
        "n": int(len(vals)),
    }
