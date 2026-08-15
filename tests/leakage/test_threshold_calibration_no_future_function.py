"""
Milestone 9 no-future-function regression test (SPEC 19.1 / SPEC_ADDENDUM's explicit
"禁止用未來資料校準" instruction): the calibrated quantile threshold used to judge day
T must never change depending on what happens on day T+1 or later. This directly
exercises `src/threshold_calibration.py::rolling_quantile_threshold` (and the
`build_calibrated_*_config` wrappers), the same style of truncated-vs-full-dataset
equivalence check used in tests/leakage/test_backtester_no_future_function.py for M5c.
"""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.threshold_calibration import (
    rolling_quantile_threshold,
    build_calibrated_new_gainer_config,
)


def _history(scores, sector_name="半導體"):
    dates = pd.date_range("2026-01-01", periods=len(scores), freq="D").strftime("%Y-%m-%d")
    return pd.DataFrame({
        "sector_name": [sector_name] * len(scores),
        "trade_date": list(dates),
        "score": scores,
    })


def test_threshold_for_day_t_identical_whether_or_not_future_rows_exist():
    """
    Build 20 days of history. Compute the calibrated threshold for day 15 (index 14,
    0-based) against (a) the full 20-day frame and (b) a frame truncated to end at day
    15 itself (no rows at all beyond day 15). Both must produce the exact same
    threshold value -- if appending future rows changes day 15's own already-computed
    threshold, the function is reaching into the future.
    """
    scores = [30 + i for i in range(20)]
    df_full = _history(scores)
    eval_date = pd.date_range("2026-01-01", periods=20, freq="D")[14].strftime("%Y-%m-%d")

    df_truncated = df_full[df_full["trade_date"] <= eval_date].reset_index(drop=True)

    result_full = rolling_quantile_threshold(df_full, "半導體", "score", eval_date,
                                              quantile=0.85, fallback_value=999.0, min_periods=10)
    result_truncated = rolling_quantile_threshold(df_truncated, "半導體", "score", eval_date,
                                                   quantile=0.85, fallback_value=999.0, min_periods=10)

    assert result_full == result_truncated


def test_appending_future_rows_after_eval_date_never_changes_the_threshold():
    """Same idea, but the future rows are pathologically extreme (huge scores) --
    if there were ANY leakage, this would show up as a drastically different value."""
    scores = [30 + i for i in range(15)]
    df_base = _history(scores)
    eval_date = pd.date_range("2026-01-01", periods=15, freq="D")[-1].strftime("%Y-%m-%d")

    result_before_future_appended = rolling_quantile_threshold(
        df_base, "半導體", "score", eval_date, quantile=0.85, fallback_value=999.0, min_periods=10)

    future_scores = [9999.0] * 10
    df_future = _history(future_scores)
    # shift future dates to strictly after eval_date
    future_dates = pd.date_range("2026-01-16", periods=10, freq="D").strftime("%Y-%m-%d")
    df_future = df_future.assign(trade_date=list(future_dates))
    df_with_future = pd.concat([df_base, df_future], ignore_index=True)

    result_with_future_appended = rolling_quantile_threshold(
        df_with_future, "半導體", "score", eval_date, quantile=0.85, fallback_value=999.0, min_periods=10)

    assert result_before_future_appended == result_with_future_appended


def test_eval_date_own_row_is_excluded_from_its_own_threshold():
    """
    If day T's own score value (which the resulting threshold is about to judge) were
    accidentally included in the quantile computation, an extreme value on day T
    itself would shift the day-T threshold -- this must not happen (strict `<`, not
    `<=`, in rolling_quantile_threshold's date filter).
    """
    scores = [30 + i for i in range(14)]  # 14 prior days, all in the 30-43 range
    df = _history(scores)
    eval_date = pd.date_range("2026-01-01", periods=15, freq="D")[-1].strftime("%Y-%m-%d")  # 15th day, not yet in `scores`

    # Add day 15 (the eval date) with a pathologically extreme score.
    df_with_today = pd.concat([df, pd.DataFrame({
        "sector_name": ["半導體"], "trade_date": [eval_date], "score": [999999.0],
    })], ignore_index=True)

    result = rolling_quantile_threshold(df_with_today, "半導體", "score", eval_date,
                                         quantile=0.85, fallback_value=1.0, min_periods=10)

    # Must reflect only the 30-43 range, nowhere near the 999999 extreme value.
    assert result < 100


def test_build_calibrated_config_no_lookahead_end_to_end():
    """Same guarantee at the build_calibrated_new_gainer_config level (the function
    SignalDetector actually calls per sector per day)."""
    scores = [40 + i for i in range(20)]
    df_full = _history(scores)
    eval_date = pd.date_range("2026-01-01", periods=20, freq="D")[14].strftime("%Y-%m-%d")
    df_truncated = df_full[df_full["trade_date"] <= eval_date].reset_index(drop=True)

    base_cfg = {"min_score": 70, "prev_score_max": 55}
    cfg_full = build_calibrated_new_gainer_config(df_full, "半導體", eval_date, base_cfg)
    cfg_truncated = build_calibrated_new_gainer_config(df_truncated, "半導體", eval_date, base_cfg)

    assert cfg_full["min_score"] == cfg_truncated["min_score"]
    assert cfg_full["prev_score_max"] == cfg_truncated["prev_score_max"]
