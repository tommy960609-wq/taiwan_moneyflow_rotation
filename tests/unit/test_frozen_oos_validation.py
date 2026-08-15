"""Unit tests for frozen-parameter OOS availability checks."""

from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from pathlib import Path


TOOL_PATH = (
    Path(__file__).parents[2]
    / ".."
    / "Quant-Agent"
    / "_workbench"
    / "tools"
    / "run_frozen_oos_validation.py"
).resolve()
SPEC = importlib.util.spec_from_file_location("frozen_oos_validation", TOOL_PATH)
assert SPEC and SPEC.loader
OOS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OOS)


def _dates(start: date, count: int):
    return [start + timedelta(days=index) for index in range(count)]


def test_oos_requires_dates_after_training_window():
    result = OOS.assess_oos_availability(
        [date(2026, 7, 17)], [date(2026, 7, 17)], min_oos_days=1
    )

    assert result["status"] == "INSUFFICIENT_OOS_DATA"
    assert result["candidate_date_count"] == 0
    assert result["future_data_reused"] is False


def test_one_new_date_cannot_be_called_mature():
    new_date = date(2026, 7, 20)
    result = OOS.assess_oos_availability(
        [date(2026, 7, 17), new_date], [date(2026, 7, 17), new_date], min_oos_days=1
    )

    assert result["candidate_date_count"] == 1
    assert result["mature_date_count"] == 0
    assert result["status"] == "INSUFFICIENT_OOS_DATA"


def test_mature_window_is_ready_only_after_required_follow_up_dates():
    candidate = date(2026, 7, 20)
    follow_up = _dates(date(2026, 7, 21), 10)
    result = OOS.assess_oos_availability(
        [date(2026, 7, 17), candidate, *follow_up],
        [date(2026, 7, 17), candidate, *follow_up],
        min_oos_days=1,
    )

    assert result["status"] == "READY"
    assert result["mature_date_count"] == 1


def test_dates_before_or_at_training_end_are_excluded_even_if_signal_exists():
    dates = [date(2026, 7, 16), date(2026, 7, 17), date(2026, 7, 20)]
    result = OOS.assess_oos_availability(dates, dates, min_oos_days=1)

    assert result["available_scored_dates_after_training"] == ["2026-07-20"]
