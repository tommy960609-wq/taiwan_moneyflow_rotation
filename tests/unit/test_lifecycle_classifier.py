import sys
import os
import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.lifecycle_classifier import LifecycleClassifier, INSUFFICIENT_DATA_LABEL


def _history_rows(sector_name, scores, breadths, hhis=None, rel_strengths=None):
    dates = pd.bdate_range("2026-06-01", periods=len(scores)).strftime("%Y-%m-%d").tolist()
    hhis = hhis or [0.3] * len(scores)
    rel_strengths = rel_strengths or [0.01] * len(scores)
    return [
        {"trade_date": d, "sector_name": sector_name, "score": s, "breadth": b, "hhi": h, "relative_strength": r}
        for d, s, b, h, r in zip(dates, scores, breadths, hhis, rel_strengths)
    ]


def test_insufficient_data_when_fewer_than_3_days_history():
    """
    SPEC 13.6: classification must use 3/5/10-day joint evidence, not a single day.
    Fewer than 3 days of accumulated history -> explicit "資料不足", never a guessed stage.
    """
    rows = _history_rows("半導體", scores=[60.0, 65.0], breadths=[0.5, 0.55])
    df_hist = pd.DataFrame(rows)

    classifier = LifecycleClassifier()
    out = classifier.classify_lifecycle(df_hist)

    assert out.iloc[0]["lifecycle"] == INSUFFICIENT_DATA_LABEL
    assert out.iloc[0]["lifecycle_confidence"] == "INSUFFICIENT_DATA"


def test_exactly_3_days_gives_partial_confidence_real_stage():
    rows = _history_rows("半導體", scores=[55.0, 65.0, 75.0], breadths=[0.4, 0.6, 0.75])
    df_hist = pd.DataFrame(rows)

    classifier = LifecycleClassifier()
    out = classifier.classify_lifecycle(df_hist)

    assert out.iloc[0]["lifecycle"] != INSUFFICIENT_DATA_LABEL
    assert out.iloc[0]["lifecycle_confidence"] == "PARTIAL"


def test_10_or_more_days_gives_full_confidence():
    rows = _history_rows("半導體", scores=[50.0 + i for i in range(10)], breadths=[0.3 + i * 0.02 for i in range(10)])
    df_hist = pd.DataFrame(rows)

    classifier = LifecycleClassifier()
    out = classifier.classify_lifecycle(df_hist)

    assert out.iloc[0]["lifecycle_confidence"] == "FULL"


def test_accelerate_stage_high_score_high_breadth():
    rows = _history_rows("半導體", scores=[70.0, 75.0, 80.0], breadths=[0.6, 0.65, 0.75])
    df_hist = pd.DataFrame(rows)
    classifier = LifecycleClassifier()
    out = classifier.classify_lifecycle(df_hist)
    assert out.iloc[0]["lifecycle"] == "加速期"


def test_diverge_stage_weak_score_high_concentration():
    rows = _history_rows("半導體", scores=[60.0, 55.0, 50.0], breadths=[0.5, 0.45, 0.4], hhis=[0.6, 0.6, 0.6])
    df_hist = pd.DataFrame(rows)
    classifier = LifecycleClassifier()
    out = classifier.classify_lifecycle(df_hist)
    assert out.iloc[0]["lifecycle"] == "分化期"


def test_multiple_sectors_classified_independently():
    rows = _history_rows("半導體", scores=[70.0, 75.0, 80.0], breadths=[0.6, 0.65, 0.75])
    rows += _history_rows("電子零組件", scores=[30.0, 28.0, 26.0], breadths=[0.2, 0.18, 0.15], hhis=[0.7, 0.7, 0.7])
    df_hist = pd.DataFrame(rows)

    classifier = LifecycleClassifier()
    out = classifier.classify_lifecycle(df_hist)

    assert len(out) == 2
    assert set(out["sector_name"]) == {"半導體", "電子零組件"}


def test_missing_required_columns_raises():
    classifier = LifecycleClassifier()
    with pytest.raises(ValueError):
        classifier.classify_lifecycle(pd.DataFrame([{"sector_name": "x"}]))


def test_empty_dataframe_returns_empty():
    classifier = LifecycleClassifier()
    out = classifier.classify_lifecycle(pd.DataFrame())
    assert out.empty
