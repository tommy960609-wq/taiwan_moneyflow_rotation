import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.threshold_calibration import (
    rolling_quantile_threshold,
    rolling_quantile_threshold_pooled,
    build_calibrated_new_gainer_config,
    build_calibrated_continued_momentum_config,
    MIN_CALIBRATION_PERIODS,
)


def _history(sector_scores, sector_name="半導體", start="2026-01-01"):
    """Builds a df_history frame with one row per day for `sector_name`, scores in
    the given order, trade_date starting at `start` and incrementing by simple integer
    day suffixes (calendar-agnostic, matches this test's own known-value expectations)."""
    dates = pd.date_range(start, periods=len(sector_scores), freq="D").strftime("%Y-%m-%d")
    return pd.DataFrame({
        "sector_name": [sector_name] * len(sector_scores),
        "trade_date": list(dates),
        "score": sector_scores,
    })


class TestRollingQuantileThreshold:
    def test_known_small_sample_quantile_value(self):
        """10 prior observations [1..10]; median (0.5 quantile) of a strictly-prior
        window ending the day before should be pandas' own quantile() on [1..10]."""
        scores = list(range(1, 11))  # 1..10, 10 observations
        df = _history(scores)
        # evaluate on the 11th day (one day after the last historical row)
        eval_date = pd.date_range("2026-01-01", periods=11, freq="D")[-1].strftime("%Y-%m-%d")
        result = rolling_quantile_threshold(df, "半導體", "score", eval_date,
                                             quantile=0.5, fallback_value=999.0, min_periods=10)
        expected = pd.Series(scores).quantile(0.5)
        assert result == pytest.approx(expected)

    def test_falls_back_below_min_periods(self):
        scores = list(range(1, 6))  # only 5 observations
        df = _history(scores)
        eval_date = pd.date_range("2026-01-01", periods=6, freq="D")[-1].strftime("%Y-%m-%d")
        result = rolling_quantile_threshold(df, "半導體", "score", eval_date,
                                             quantile=0.85, fallback_value=70.0, min_periods=10)
        assert result == 70.0

    def test_exactly_min_periods_uses_quantile_not_fallback(self):
        scores = list(range(1, 11))  # exactly 10 observations
        df = _history(scores)
        eval_date = pd.date_range("2026-01-01", periods=11, freq="D")[-1].strftime("%Y-%m-%d")
        result = rolling_quantile_threshold(df, "半導體", "score", eval_date,
                                             quantile=0.85, fallback_value=70.0, min_periods=10)
        assert result != 70.0
        assert result == pytest.approx(pd.Series(scores).quantile(0.85))

    def test_empty_history_falls_back(self):
        df = pd.DataFrame(columns=["sector_name", "trade_date", "score"])
        result = rolling_quantile_threshold(df, "半導體", "score", "2026-01-05",
                                             quantile=0.85, fallback_value=42.0)
        assert result == 42.0

    def test_none_history_falls_back(self):
        result = rolling_quantile_threshold(None, "半導體", "score", "2026-01-05",
                                             quantile=0.85, fallback_value=42.0)
        assert result == 42.0

    def test_missing_metric_column_falls_back(self):
        df = pd.DataFrame({"sector_name": ["半導體"] * 12, "trade_date": [f"2026-01-{i:02d}" for i in range(1, 13)]})
        result = rolling_quantile_threshold(df, "半導體", "score", "2026-01-13",
                                             quantile=0.85, fallback_value=42.0)
        assert result == 42.0

    def test_missing_required_columns_falls_back(self):
        df = pd.DataFrame({"score": list(range(1, 13))})  # no sector_name/trade_date
        result = rolling_quantile_threshold(df, "半導體", "score", "2026-01-13",
                                             quantile=0.85, fallback_value=42.0)
        assert result == 42.0

    def test_other_sectors_do_not_contaminate_this_sectors_quantile(self):
        df_a = _history(list(range(1, 15)), sector_name="A")
        df_b = _history([1000.0] * 14, sector_name="B")
        df = pd.concat([df_a, df_b], ignore_index=True)
        eval_date = pd.date_range("2026-01-01", periods=15, freq="D")[-1].strftime("%Y-%m-%d")
        result = rolling_quantile_threshold(df, "A", "score", eval_date,
                                             quantile=0.5, fallback_value=999.0, min_periods=10)
        # must reflect only sector A's 1..14 distribution, not sector B's 1000s
        assert result < 100

    def test_nan_scores_excluded_from_quantile_and_from_min_periods_count(self):
        scores = [1, 2, 3, None, None, 6, 7, 8, 9, 10, 11, 12]  # 10 real values, 2 NaN
        df = _history(scores)
        eval_date = pd.date_range("2026-01-01", periods=13, freq="D")[-1].strftime("%Y-%m-%d")
        result = rolling_quantile_threshold(df, "半導體", "score", eval_date,
                                             quantile=0.5, fallback_value=999.0, min_periods=10)
        assert result != 999.0  # 10 non-NaN values meets min_periods=10

    def test_default_min_calibration_periods_constant_used_when_unspecified(self):
        scores = list(range(1, MIN_CALIBRATION_PERIODS))  # one short of the default floor
        df = _history(scores)
        eval_date = pd.date_range("2026-01-01", periods=len(scores) + 1, freq="D")[-1].strftime("%Y-%m-%d")
        result = rolling_quantile_threshold(df, "半導體", "score", eval_date,
                                             quantile=0.85, fallback_value=55.5)
        assert result == 55.5


class TestRollingQuantileThresholdPooled:
    def test_pools_across_all_sectors(self):
        df_a = _history(list(range(1, 8)), sector_name="A")
        df_b = _history(list(range(8, 15)), sector_name="B")
        df = pd.concat([df_a, df_b], ignore_index=True)
        eval_date = pd.date_range("2026-01-01", periods=8, freq="D")[-1].strftime("%Y-%m-%d")
        result = rolling_quantile_threshold_pooled(df, "score", eval_date,
                                                    quantile=0.5, fallback_value=999.0, min_periods=10)
        # pooled prior history across both sectors before the 8th day should have 12
        # values (A's first 7 days + B's first... depends on exact date alignment);
        # regardless, it must not equal the fallback since pooling clears min_periods.
        assert result != 999.0

    def test_falls_back_below_min_periods_when_pooled_still_too_thin(self):
        df = _history(list(range(1, 4)), sector_name="A")  # only 3 rows total
        eval_date = pd.date_range("2026-01-01", periods=4, freq="D")[-1].strftime("%Y-%m-%d")
        result = rolling_quantile_threshold_pooled(df, "score", eval_date,
                                                    quantile=0.5, fallback_value=42.0, min_periods=10)
        assert result == 42.0


class TestBuildCalibratedNewGainerConfig:
    def test_calibrates_min_score_and_prev_score_max_with_enough_history(self):
        scores = list(range(30, 30 + 15))  # 15 prior obs
        df = _history(scores)
        eval_date = pd.date_range("2026-01-01", periods=16, freq="D")[-1].strftime("%Y-%m-%d")
        base_cfg = {"min_score": 70, "prev_score_max": 55, "score_breakout_days": 5}
        cfg = build_calibrated_new_gainer_config(df, "半導體", eval_date, base_cfg)
        assert cfg["min_score"] != 70
        assert cfg["prev_score_max"] != 55
        # other keys untouched
        assert cfg["score_breakout_days"] == 5

    def test_falls_back_to_base_cfg_values_with_insufficient_history(self):
        scores = list(range(30, 35))  # only 5 obs
        df = _history(scores)
        eval_date = pd.date_range("2026-01-01", periods=6, freq="D")[-1].strftime("%Y-%m-%d")
        base_cfg = {"min_score": 70, "prev_score_max": 55}
        cfg = build_calibrated_new_gainer_config(df, "半導體", eval_date, base_cfg)
        assert cfg["min_score"] == 70
        assert cfg["prev_score_max"] == 55

    def test_does_not_mutate_base_cfg(self):
        scores = list(range(30, 45))
        df = _history(scores)
        eval_date = pd.date_range("2026-01-01", periods=16, freq="D")[-1].strftime("%Y-%m-%d")
        base_cfg = {"min_score": 70, "prev_score_max": 55}
        build_calibrated_new_gainer_config(df, "半導體", eval_date, base_cfg)
        assert base_cfg["min_score"] == 70
        assert base_cfg["prev_score_max"] == 55


class TestBuildCalibratedContinuedMomentumConfig:
    def test_calibrates_min_score_with_enough_history(self):
        scores = list(range(30, 30 + 15))
        df = _history(scores)
        eval_date = pd.date_range("2026-01-01", periods=16, freq="D")[-1].strftime("%Y-%m-%d")
        base_cfg = {"min_score": 65, "min_score_days": 2}
        cfg = build_calibrated_continued_momentum_config(df, "半導體", eval_date, base_cfg)
        assert cfg["min_score"] != 65
        assert cfg["min_score_days"] == 2

    def test_falls_back_with_insufficient_history(self):
        scores = list(range(30, 35))
        df = _history(scores)
        eval_date = pd.date_range("2026-01-01", periods=6, freq="D")[-1].strftime("%Y-%m-%d")
        base_cfg = {"min_score": 65}
        cfg = build_calibrated_continued_momentum_config(df, "半導體", eval_date, base_cfg)
        assert cfg["min_score"] == 65
