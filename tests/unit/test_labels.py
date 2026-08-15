import sys
import os
import math
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.labels import (
    label_new_gainer_outcome,
    label_continued_momentum_outcome,
    compute_sector_excess_return,
    LABEL_SUCCESS,
    LABEL_FAILURE_MINOR,
    LABEL_FAILURE_REVERSAL,
    LABEL_INSUFFICIENT_DATA,
    NEW_GAINER_SUCCESS_THRESHOLD_PCT,
    FAILURE_REVERSAL_THRESHOLD_PCT,
)


def test_new_gainer_success_above_threshold():
    assert label_new_gainer_outcome(3.01) == LABEL_SUCCESS
    assert label_new_gainer_outcome(10.0) == LABEL_SUCCESS


def test_new_gainer_exactly_at_threshold_is_not_success():
    # Spec: Success requires STRICTLY > +3.0%, so exactly 3.0% is failure/minor.
    assert label_new_gainer_outcome(NEW_GAINER_SUCCESS_THRESHOLD_PCT) == LABEL_FAILURE_MINOR


def test_new_gainer_minor_failure_band():
    assert label_new_gainer_outcome(0.0) == LABEL_FAILURE_MINOR
    assert label_new_gainer_outcome(-1.5) == LABEL_FAILURE_MINOR
    assert label_new_gainer_outcome(FAILURE_REVERSAL_THRESHOLD_PCT) == LABEL_FAILURE_MINOR


def test_new_gainer_reversal_band():
    assert label_new_gainer_outcome(-3.01) == LABEL_FAILURE_REVERSAL
    assert label_new_gainer_outcome(-20.0) == LABEL_FAILURE_REVERSAL


def test_new_gainer_insufficient_data_on_none_or_nan():
    assert label_new_gainer_outcome(None) == LABEL_INSUFFICIENT_DATA
    assert label_new_gainer_outcome(float("nan")) == LABEL_INSUFFICIENT_DATA


def test_continued_momentum_success():
    assert label_continued_momentum_outcome(0.01) == LABEL_SUCCESS


def test_continued_momentum_success_overridden_by_fade():
    """
    Success requires BOTH positive excess return AND no fade triggered in the window.
    A positive return with fading triggered must NOT be labeled success.
    """
    assert label_continued_momentum_outcome(1.5, faded_within_window=True) == LABEL_FAILURE_REVERSAL


def test_continued_momentum_failure_non_positive():
    assert label_continued_momentum_outcome(0.0) == LABEL_FAILURE_MINOR
    assert label_continued_momentum_outcome(-5.0) == LABEL_FAILURE_REVERSAL


def test_compute_sector_excess_return_preserves_nan():
    sector = pd.Series([5.0, np.nan, 2.0])
    market = pd.Series([2.0, 1.0, np.nan])
    excess = compute_sector_excess_return(sector, market)
    assert excess.iloc[0] == 3.0
    assert math.isnan(excess.iloc[1])
    assert math.isnan(excess.iloc[2])
