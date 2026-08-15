import sys
import os

import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.benchmarks import (
    momentum_extension_baseline,
    random_sector_bootstrap_baseline,
    bootstrap_confidence_interval,
)


def _ohlcv_rows(stock_id, rows):
    return pd.DataFrame([
        {"stock_id": stock_id, "trade_date": d, "open": o, "high": h, "low": l, "close": c, "volume": v}
        for d, o, h, l, c, v in rows
    ])


def _small_universe():
    sector_scored_day1 = pd.DataFrame([
        {"trade_date": "2026-01-01", "sector_name": "半導體", "sector_type": "primary", "score": 80.0},
        {"trade_date": "2026-01-01", "sector_name": "航運", "sector_type": "primary", "score": 40.0},
    ])
    sector_scored_day2 = pd.DataFrame([
        {"trade_date": "2026-01-02", "sector_name": "半導體", "sector_type": "primary", "score": 70.0},
        {"trade_date": "2026-01-02", "sector_name": "航運", "sector_type": "primary", "score": 90.0},
    ])
    df_sector_scored_by_date = {"2026-01-01": sector_scored_day1, "2026-01-02": sector_scored_day2}

    stock_scored = pd.DataFrame([
        {"stock_id": "A", "primary_sector": "半導體", "theme_1": None, "theme_2": None, "theme_3": None},
        {"stock_id": "B", "primary_sector": "航運", "theme_1": None, "theme_2": None, "theme_3": None},
    ])
    df_stock_scored_by_date = {"2026-01-01": stock_scored, "2026-01-02": stock_scored}

    ohlcv = pd.concat([
        _ohlcv_rows("A", [
            ("2026-01-01", 100, 100, 100, 100, 1e6),
            ("2026-01-02", 100, 100, 100, 100, 1e6),
            ("2026-01-03", 100, 100, 100, 105, 1e6),
        ]),
        _ohlcv_rows("B", [
            ("2026-01-01", 50, 50, 50, 50, 1e6),
            ("2026-01-02", 50, 50, 50, 50, 1e6),
            ("2026-01-03", 50, 50, 50, 52, 1e6),
        ]),
    ], ignore_index=True)
    taiex = pd.DataFrame([
        {"trade_date": "2026-01-01", "close": 20000},
        {"trade_date": "2026-01-02", "close": 20000},
        {"trade_date": "2026-01-03", "close": 20100},
    ])
    return df_sector_scored_by_date, df_stock_scored_by_date, ohlcv, taiex


def test_momentum_baseline_selects_prior_day_strongest_sector():
    df_sector, df_stock, ohlcv, taiex = _small_universe()
    out = momentum_extension_baseline(df_sector, df_stock, ohlcv, taiex, horizons=(1,))
    assert len(out) == 1
    row = out.iloc[0]
    # day2's action should pick day1's strongest sector (半導體, score=80), NOT day2's own
    # score (航運=90) -- using only information known as of the decision day.
    assert row["sector_name"] == "半導體"
    assert row["decision_date"] == "2026-01-01"
    assert row["action_date"] == "2026-01-02"


def test_momentum_baseline_empty_when_no_prior_day():
    df_sector, df_stock, ohlcv, taiex = _small_universe()
    single_day = {"2026-01-01": df_sector["2026-01-01"]}
    out = momentum_extension_baseline(single_day, df_stock, ohlcv, taiex, horizons=(1,))
    assert out.empty


def test_momentum_baseline_ignores_nan_scores():
    df_sector, df_stock, ohlcv, taiex = _small_universe()
    df_sector["2026-01-01"] = df_sector["2026-01-01"].copy()
    df_sector["2026-01-01"]["score"] = float("nan")
    out = momentum_extension_baseline(df_sector, df_stock, ohlcv, taiex, horizons=(1,))
    assert out.empty  # no scoreable sector on the decision day -> no action


def test_random_bootstrap_baseline_reproducible_with_fixed_seed():
    df_sector, df_stock, ohlcv, taiex = _small_universe()
    out1 = random_sector_bootstrap_baseline(df_sector, df_stock, ohlcv, taiex, n_draws=20,
                                             horizons=(1,), random_seed=42)
    out2 = random_sector_bootstrap_baseline(df_sector, df_stock, ohlcv, taiex, n_draws=20,
                                             horizons=(1,), random_seed=42)
    pd.testing.assert_frame_equal(out1, out2)


def test_random_bootstrap_baseline_records_seed_and_n_draws_in_attrs():
    df_sector, df_stock, ohlcv, taiex = _small_universe()
    out = random_sector_bootstrap_baseline(df_sector, df_stock, ohlcv, taiex, n_draws=15, random_seed=7)
    assert out.attrs["random_seed"] == 7
    assert out.attrs["n_draws_requested"] == 15


def test_random_bootstrap_baseline_empty_universe():
    out = random_sector_bootstrap_baseline({}, {}, pd.DataFrame(), pd.DataFrame(), n_draws=10)
    assert out.empty
    assert out.attrs["universe_size"] == 0


def test_bootstrap_confidence_interval_basic():
    result = bootstrap_confidence_interval([0.01, 0.02, 0.03, -0.01, 0.05], n_resamples=200, ci=0.90)
    assert result["n"] == 5
    assert result["ci_low"] <= result["mean"] <= result["ci_high"]


def test_bootstrap_confidence_interval_empty_input_returns_none_not_fabricated():
    result = bootstrap_confidence_interval([], n_resamples=200)
    assert result["mean"] is None
    assert result["ci_low"] is None
    assert result["ci_high"] is None
    assert result["n"] == 0


def test_bootstrap_confidence_interval_filters_nan():
    import numpy as np
    result = bootstrap_confidence_interval([0.01, np.nan, 0.03, None], n_resamples=100)
    assert result["n"] == 2
