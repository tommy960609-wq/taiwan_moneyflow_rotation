import sys
import os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.sector_scoring import SectorScoring


def _mock_sectors(n=5):
    rows = []
    for i in range(n):
        rows.append({
            "sector_name": f"sector_{i}",
            "breadth": 0.3 + i * 0.1,
            "volume_share": 0.1 + i * 0.02,
            "relative_strength": -0.01 + i * 0.005,
            "inst_flow_ratio": 0.01 * i,
            "hhi": 0.2 + i * 0.05,
            "total_turnover": 1_000_000.0 * (i + 1),
            "stock_count": 5,
        })
    return pd.DataFrame(rows)


def test_scores_are_bounded_0_to_100():
    scoring = SectorScoring()
    df, _ = scoring.score_sectors(_mock_sectors())
    assert ((df["score"] >= 0.0) & (df["score"] <= 100.0)).all()
    assert ((df["overheat_risk"] >= 0.0) & (df["overheat_risk"] <= 100.0)).all()


def test_full_confidence_when_all_factors_present():
    scoring = SectorScoring()
    df, confidence = scoring.score_sectors(_mock_sectors(), has_institutional=True, has_momentum=True)
    assert confidence == "FULL"
    assert (df["score_confidence"] == "FULL").all()


def test_degraded_confidence_when_institutional_missing():
    scoring = SectorScoring()
    df, confidence = scoring.score_sectors(_mock_sectors(), has_institutional=False)
    assert confidence == "DEGRADED"


def test_weight_renormalization_sums_to_one_when_factor_missing():
    """
    P1-01 compliance: when a scoring factor is disabled (e.g. institutional missing),
    the remaining active weights must be rescaled so they still sum to 1.0 -- the
    missing factor is never scored as zero.
    """
    scoring = SectorScoring()
    df_sectors = _mock_sectors()

    scoring.score_sectors(df_sectors, has_institutional=False, has_momentum=True)
    active = scoring.default_weights.copy()
    active["institution"] = 0.0
    weight_sum = sum(active.values())
    normalized = {k: v / weight_sum for k, v in active.items()}
    assert abs(sum(normalized.values()) - 1.0) < 1e-9


def test_all_factors_missing_returns_low_confidence_and_nan_score():
    scoring = SectorScoring()
    df_sectors = _mock_sectors()
    for col in ["breadth", "volume_share", "relative_strength", "hhi"]:
        df_sectors[col] = np.nan

    df, confidence = scoring.score_sectors(df_sectors, has_institutional=False, has_momentum=False)
    assert confidence == "LOW"


def test_empty_dataframe_returns_low_confidence():
    scoring = SectorScoring()
    df, confidence = scoring.score_sectors(pd.DataFrame())
    assert confidence == "LOW"


def test_placeholder_weights_sum_to_one():
    from src.sector_scoring import DEFAULT_SECTOR_WEIGHTS
    assert abs(sum(DEFAULT_SECTOR_WEIGHTS.values()) - 1.0) < 1e-9
