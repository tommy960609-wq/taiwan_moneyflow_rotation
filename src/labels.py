"""
Success/Failure outcome label definitions for signal event studies (P0-02,
SPEC_ADDENDUM A-2). See docs/signal_definitions.md for the full narrative
specification these constants and functions implement.

All numeric thresholds below are explicit initial placeholder values -- they may be
recalibrated after Milestone 5 backtesting, but a concrete, testable label definition
must exist at all times (SPEC_ADDENDUM A-2: "任何時點都必須存在一組明確標籤定義").

This module intentionally only defines the label *computation* functions (pure
functions over an excess-return series/scalar). It does not run any backtest --
Milestone 2 scope is limited to defining and unit-testing the labeling logic itself.
"""

from typing import Optional
import numpy as np
import pandas as pd

# New Gainer (新起漲) label thresholds -- evaluated on AR_sector_10 (10-trading-day
# forward cumulative sector excess return vs the market benchmark).
NEW_GAINER_SUCCESS_THRESHOLD_PCT = 3.0    # PLACEHOLDER - UNCALIBRATED (AR_10 > +3.0%)
NEW_GAINER_HORIZON_DAYS = 10

# Continued Momentum (續漲) label thresholds -- evaluated on AR_sector_5 (5-trading-day
# forward cumulative sector excess return).
CONTINUED_MOMENTUM_SUCCESS_THRESHOLD_PCT = 0.0  # PLACEHOLDER - UNCALIBRATED (AR_5 > 0%)
CONTINUED_MOMENTUM_HORIZON_DAYS = 5

# Failure sub-classification boundary shared by both signal families: excess returns
# between 0% and this (negative) threshold are "minor failure"; below it is "reversal".
FAILURE_REVERSAL_THRESHOLD_PCT = -3.0  # PLACEHOLDER - UNCALIBRATED

LABEL_SUCCESS = "SUCCESS"
LABEL_FAILURE_MINOR = "FAILURE_MINOR"       # 小幅失效: 0% >= AR >= -3%
LABEL_FAILURE_REVERSAL = "FAILURE_REVERSAL"  # 反轉: AR < -3%
LABEL_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


def label_new_gainer_outcome(excess_return_10d_pct: Optional[float]) -> str:
    """
    Classifies a New Gainer (新起漲) signal's outcome from its realized 10-trading-day
    forward sector excess return (percentage points, e.g. 3.5 means +3.5%).

    Rules (SPEC_ADDENDUM A-2):
      - Success:        AR_10 > +3.0%
      - Failure/Minor:  0.0% >= AR_10 >= -3.0%
      - Failure/Reversal: AR_10 < -3.0%
    A None/NaN input (insufficient forward data, e.g. too close to the data horizon)
    returns INSUFFICIENT_DATA rather than guessing/defaulting to a real label.
    """
    return _label_from_excess_return(excess_return_10d_pct, NEW_GAINER_SUCCESS_THRESHOLD_PCT)


def label_continued_momentum_outcome(excess_return_5d_pct: Optional[float],
                                      faded_within_window: Optional[bool] = None) -> str:
    """
    Classifies a Continued Momentum (續漲) signal's outcome from its realized
    5-trading-day forward sector excess return (percentage points).

    Rules (SPEC_ADDENDUM A-2 / docs/signal_definitions.md 2.2):
      - Success: AR_5 > 0.0% AND no "Fading (退潮)" lifecycle triggered within the window.
      - Failure: AR_5 <= 0.0% OR fading triggered in the window.
        - Minor failure: 0.0% >= AR_5 >= -3.0% (and not fading)
        - Reversal:      AR_5 < -3.0% (or fading triggered, treated as reversal-grade failure)

    `faded_within_window`: pass True if lifecycle classification recorded a fade
    (退潮期) at any point in T+1..T+5; None if that information is unavailable (in which
    case only the excess-return threshold is used).
    """
    label = _label_from_excess_return(excess_return_5d_pct, CONTINUED_MOMENTUM_SUCCESS_THRESHOLD_PCT)
    if label == LABEL_SUCCESS and faded_within_window is True:
        # Success requires both a positive excess return AND no fade signal.
        return LABEL_FAILURE_REVERSAL
    return label


def _label_from_excess_return(excess_return_pct: Optional[float], success_threshold_pct: float) -> str:
    if excess_return_pct is None or (isinstance(excess_return_pct, float) and np.isnan(excess_return_pct)):
        return LABEL_INSUFFICIENT_DATA

    if excess_return_pct > success_threshold_pct:
        return LABEL_SUCCESS
    if excess_return_pct >= FAILURE_REVERSAL_THRESHOLD_PCT:
        return LABEL_FAILURE_MINOR
    return LABEL_FAILURE_REVERSAL


def compute_sector_excess_return(sector_median_return_pct: pd.Series,
                                  market_return_pct: pd.Series) -> pd.Series:
    """
    Computes AR_sector_K = R_sector_K - R_market_K element-wise for aligned series
    (e.g. cumulative percentage returns over the same forward K-day window for each
    signal event). Returns NaN for any index where either input is NaN/missing rather
    than dropping or zero-filling, so downstream labeling correctly reports
    INSUFFICIENT_DATA for those events.
    """
    return sector_median_return_pct - market_return_pct
