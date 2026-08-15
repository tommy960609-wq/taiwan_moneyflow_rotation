import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from scripts.run_daily import _reconciliation_requires_dq_penalty


def _warning(compared: int, rate: float) -> dict:
    return {
        "status": "WARNING_HIGH_DEVIATION",
        "deviation_count": round(compared * rate),
        "summary": {
            "rows_with_finmind_comparison": compared,
            "pct_exceeding_threshold": rate,
        },
    }


def test_isolated_reconciliation_outliers_do_not_reduce_dq_score():
    assert not _reconciliation_requires_dq_penalty(_warning(81, 6 / 81))


def test_material_reconciliation_rate_reduces_dq_score():
    assert _reconciliation_requires_dq_penalty(_warning(80, 0.125))


def test_small_comparison_sample_does_not_reduce_dq_score():
    assert not _reconciliation_requires_dq_penalty(_warning(10, 0.5))


def test_missing_summary_preserves_fail_closed_penalty():
    assert _reconciliation_requires_dq_penalty({"status": "WARNING_HIGH_DEVIATION"})
