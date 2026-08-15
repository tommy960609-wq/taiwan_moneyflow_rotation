"""
Milestone 9 threshold calibration (SPEC_ADDENDUM B-1.3): converts the fixed absolute
numbers in `src/sector_scoring.py` / `src/signal_detector.py` (e.g. `min_score: 70`)
into rolling, self-relative QUANTILE thresholds computed from each sector's own
historical score/metric distribution, per the addendum's explicit instruction:
"M5 校準後，門檻改以「分位數」形式定義（如「族群分數進入自身滾動歷史 85 分位」），
不用絕對數字。"

**Honest scope disclosure (read before using this module)**:
1. This is a PRELIMINARY calibration based on a real but SMALL sample: the real
   historical batch this milestone actually processed successfully covers only 28
   trading days (2026-04-20..2026-07-17, NON-contiguous -- 34 of the original 62
   candidate days hit BLOCKED_LOW_DQ this run, a real regression from a pre-existing,
   already-disclosed leaderboard-reconciliation basis mismatch that only became this
   severe once FinMind OHLCV coverage reached ~100%; see
   docs/Milestone_9_Calibration_Backtest_Report.md for the full disclosure). A rolling
   quantile computed from 10-28 same-sector observations is NOT a statistically robust
   estimate -- it is a directionally-reasonable first cut that MUST be re-run as more
   history accumulates. This is stated in every calibrated threshold's inline comment
   and must never be read as "calibration complete."
2. **No-lookahead guarantee**: `rolling_quantile_threshold` only ever consumes rows
   whose `trade_date` is < the date being evaluated (strictly PRIOR history) -- the
   quantile used to judge day T is never computed using day T's own value or any later
   day, by construction (see the function's own no-future-leakage unit tests in
   tests/leakage/test_threshold_calibration_no_future_function.py).
3. **Fallback discipline**: when a sector/metric has fewer than `min_periods` prior
   observations (`MIN_CALIBRATION_PERIODS`, currently 10 -- itself a judgment call
   given how little history exists, not a validated statistical minimum), the ORIGINAL
   uncalibrated absolute placeholder value is used instead of a quantile computed on
   too few points -- never silently extrapolated from a near-empty sample.
"""

import pandas as pd

# Below this many strictly-prior same-sector observations, a quantile estimate is
# considered too unreliable to use; the caller's original absolute placeholder value
# is used instead. This number is itself a judgment call (not derived from any formal
# power calculation) given this milestone's small overall sample -- documented, not
# hidden.
MIN_CALIBRATION_PERIODS = 10

# Quantile choices (SPEC_ADDENDUM B-1.3's own literal example uses the 85th percentile
# for the new-gainer "today's score" bar; the other two below are this session's
# judgment calls, disclosed as such -- not independently re-derived from a separate
# backtest sweep, since sweeping quantile choices against the same 28-day sample used
# to report the resulting backtest would itself be an undisclosed multiple-comparison
# problem (SPEC_ADDENDUM B-3.3)). All three are PRELIMINARY per this module's docstring.
NEW_GAINER_MIN_SCORE_QUANTILE = 0.85            # PRELIMINARY (n=28 trading days)
NEW_GAINER_PREV_SCORE_MAX_QUANTILE = 0.50        # PRELIMINARY (n=28 trading days)
CONTINUED_MOMENTUM_MIN_SCORE_QUANTILE = 0.70     # PRELIMINARY (n=28 trading days)


def rolling_quantile_threshold(df_history: pd.DataFrame,
                                sector_name: str,
                                metric_col: str,
                                trade_date: str,
                                quantile: float,
                                fallback_value: float,
                                min_periods: int = MIN_CALIBRATION_PERIODS) -> float:
    """
    Returns the `quantile`-th percentile of `metric_col` for `sector_name`, computed
    ONLY from rows in `df_history` whose trade_date is strictly earlier than
    `trade_date` (never today's own value, never a future date) -- an expanding
    (all-available-prior-history) window, not a fixed-width one, since daily data is
    scarce and gapped (BLOCKED days leave holes) in this project's real history so far.

    Returns `fallback_value` (the original absolute PLACEHOLDER threshold) when fewer
    than `min_periods` qualifying prior observations exist, or when `df_history`/
    `sector_name`/`metric_col` don't yield any usable rows -- never fabricates a
    quantile from an unreliably small sample.
    """
    if df_history is None or df_history.empty:
        return fallback_value
    if "trade_date" not in df_history.columns or "sector_name" not in df_history.columns:
        return fallback_value
    if metric_col not in df_history.columns:
        return fallback_value

    prior = df_history[
        (df_history["sector_name"] == sector_name) &
        (df_history["trade_date"] < trade_date)
    ][metric_col]
    prior = prior.dropna()

    if len(prior) < min_periods:
        return fallback_value

    return float(prior.quantile(quantile))


def rolling_quantile_threshold_pooled(df_history: pd.DataFrame,
                                      metric_col: str,
                                      trade_date: str,
                                      quantile: float,
                                      fallback_value: float,
                                      min_periods: int = MIN_CALIBRATION_PERIODS) -> float:
    """
    Market-wide (all-sectors-pooled) counterpart to `rolling_quantile_threshold`, for
    metrics where a genuinely sector-specific quantile would have too few observations
    even with this project's full available history (e.g. a newly-created theme sector
    with only a handful of trading days on record). Uses every sector's observations
    of `metric_col` on trade dates strictly before `trade_date`, still with the same
    no-lookahead guarantee and the same `min_periods` fallback discipline.
    """
    if df_history is None or df_history.empty:
        return fallback_value
    if "trade_date" not in df_history.columns:
        return fallback_value
    if metric_col not in df_history.columns:
        return fallback_value

    prior = df_history[df_history["trade_date"] < trade_date][metric_col].dropna()

    if len(prior) < min_periods:
        return fallback_value

    return float(prior.quantile(quantile))


def build_calibrated_new_gainer_config(df_history: pd.DataFrame,
                                        sector_name: str,
                                        trade_date: str,
                                        base_cfg: dict,
                                        min_periods: int = MIN_CALIBRATION_PERIODS) -> dict:
    """
    Returns a per-sector, per-day copy of `base_cfg` (the DEFAULT_NEW_GAINER_CONFIG
    shape from src/signal_detector.py) with `min_score` and `prev_score_max` replaced
    by rolling quantile thresholds computed from `sector_name`'s own score history
    strictly before `trade_date` (SPEC_ADDENDUM B-1.3's literal example: "族群分數進入
    自身滾動歷史 85 分位"). Only these two conditions are calibrated this milestone --
    they are the ones most directly implicated in the M5c/M9 finding that the fixed
    `min_score=70` bar interacts with the C-grade fallback ("if any of 10 conditions
    passed, grade C") to produce a signal on effectively every sector-day (see
    docs/Milestone_9_Calibration_Backtest_Report.md §3). Every other new_gainer
    threshold (rule 3-10) is left at its original PLACEHOLDER value this milestone --
    calibrating all 10 at once with only ~28 days of history would produce quantile
    estimates far less reliable than even the already-disclosed-as-preliminary two
    calibrated here; SPEC_ADDENDUM B-1 point 4 also gates full threshold acceptance on
    50 independent events per grade, which this dataset does not have.

    `min_score` is calibrated to the `NEW_GAINER_MIN_SCORE_QUANTILE` (0.85) percentile
    of the sector's own strictly-prior score history; `prev_score_max` to the
    `NEW_GAINER_PREV_SCORE_MAX_QUANTILE` (0.50, median) percentile -- both fall back to
    the original absolute PLACEHOLDER (70 / 55) when fewer than `min_periods` prior
    observations exist for that sector.
    """
    cfg = dict(base_cfg)
    cfg["min_score"] = rolling_quantile_threshold(
        df_history, sector_name, "score", trade_date,
        quantile=NEW_GAINER_MIN_SCORE_QUANTILE,
        fallback_value=base_cfg["min_score"],
        min_periods=min_periods,
    )
    cfg["prev_score_max"] = rolling_quantile_threshold(
        df_history, sector_name, "score", trade_date,
        quantile=NEW_GAINER_PREV_SCORE_MAX_QUANTILE,
        fallback_value=base_cfg["prev_score_max"],
        min_periods=min_periods,
    )
    return cfg


def build_calibrated_continued_momentum_config(df_history: pd.DataFrame,
                                                sector_name: str,
                                                trade_date: str,
                                                base_cfg: dict,
                                                min_periods: int = MIN_CALIBRATION_PERIODS) -> dict:
    """
    Same pattern as `build_calibrated_new_gainer_config` for
    DEFAULT_CONTINUED_MOMENTUM_CONFIG's `min_score` (rule 1): calibrated to the
    `CONTINUED_MOMENTUM_MIN_SCORE_QUANTILE` (0.70) percentile of the sector's own
    strictly-prior score history, falling back to the original absolute PLACEHOLDER
    (65) below `min_periods`.
    """
    cfg = dict(base_cfg)
    cfg["min_score"] = rolling_quantile_threshold(
        df_history, sector_name, "score", trade_date,
        quantile=CONTINUED_MOMENTUM_MIN_SCORE_QUANTILE,
        fallback_value=base_cfg["min_score"],
        min_periods=min_periods,
    )
    return cfg
