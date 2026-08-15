"""Unit tests for the evidence-only paired calibration audit tool."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest


TOOL_PATH = (
    Path(__file__).parents[2]
    / ".."
    / "Quant-Agent"
    / "_workbench"
    / "tools"
    / "run_paired_calibration_audit.py"
).resolve()
SPEC = importlib.util.spec_from_file_location("paired_calibration_audit", TOOL_PATH)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


KEYS = ["trade_date", "sector_name", "sector_type"]


def _signals(types):
    return pd.DataFrame([
        {"trade_date": "2026-01-01", "sector_name": chr(65 + index), "sector_type": "primary_sector",
         "signal_type": signal}
        for index, signal in enumerate(types)
    ])


def test_signal_pairing_preserves_all_rows_and_transition_labels():
    pairs = AUDIT.build_signal_pairs(_signals(["無訊號", "C級個股事件"]),
                                     _signals(["C級個股事件", "無訊號"]))

    assert len(pairs) == 2
    assert pairs["population"].tolist() == ["both", "both"]
    assert int(pairs["signal_type_changed"].sum()) == 2


def test_signal_pairing_rejects_duplicate_sector_day_keys():
    duplicate = pd.concat([_signals(["無訊號"]), _signals(["C級個股事件"])], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate sector-day keys"):
        AUDIT.build_signal_pairs(duplicate, _signals(["無訊號"]))


def test_event_pairing_does_not_turn_missing_outcome_into_zero():
    uncal = pd.DataFrame([{
        "trade_date": "2026-01-01", "sector_name": "A", "sector_type": "theme",
        "signal_type": "C級個股事件", "excess_return_net_10d": None,
    }])
    cal = pd.DataFrame([{
        "trade_date": "2026-01-02", "sector_name": "A", "sector_type": "theme",
        "signal_type": "C級個股事件", "excess_return_net_10d": 0.02,
    }])

    pairs = AUDIT.build_event_pairs(uncal, cal)

    assert len(pairs) == 2
    assert pairs["uncalibrated_return_10d"].isna().all()
    assert pairs["calibrated_return_10d"].notna().sum() == 1


def test_cluster_bootstrap_is_deterministic_and_counts_dates():
    values = [("2026-01-01", 1.0), ("2026-01-01", 3.0), ("2026-01-02", -2.0)]

    first = AUDIT._cluster_bootstrap_ci(values, seed=9, n_resamples=100)
    second = AUDIT._cluster_bootstrap_ci(values, seed=9, n_resamples=100)

    assert first == second
    assert first["n_dates"] == 2
    assert first["n_values"] == 3
