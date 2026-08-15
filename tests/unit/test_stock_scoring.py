import sys
import os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.stock_scoring import StockScoring, DEFAULT_STOCK_WEIGHTS


def _mock_stocks():
    return pd.DataFrame([
        {"stock_id": "2330", "primary_sector": "半導體", "daily_return": 0.05, "volume": 5000.0, "rank_improvement": 10},
        {"stock_id": "2454", "primary_sector": "半導體", "daily_return": -0.01, "volume": 2000.0, "rank_improvement": -5},
        {"stock_id": "3017", "primary_sector": "電子零組件", "daily_return": 0.03, "volume": 3000.0, "rank_improvement": 2},
    ])


def _mock_scored_sectors():
    return pd.DataFrame([
        {"sector_name": "半導體", "score": 80.0},
        {"sector_name": "電子零組件", "score": 60.0},
    ])


def test_stock_score_bounded_0_to_100():
    scoring = StockScoring()
    df, _ = scoring.score_stocks(_mock_stocks(), _mock_scored_sectors())
    assert ((df["stock_score"] >= 0.0) & (df["stock_score"] <= 100.0)).all()


def test_full_confidence_with_all_factors():
    scoring = StockScoring()
    df, confidence = scoring.score_stocks(
        _mock_stocks(), _mock_scored_sectors(),
        has_institutional=False, has_rank_improvement=True, has_breakout_quality=False
    )
    # institutional and breakout_quality unavailable in this fixture -> degraded, not full
    assert confidence in ("DEGRADED", "FULL")


def test_missing_sector_score_renormalizes_and_flags_low():
    scoring = StockScoring()
    df_stocks = _mock_stocks()
    df, confidence = scoring.score_stocks(df_stocks, pd.DataFrame())  # no scored sectors at all
    assert confidence == "LOW"
    assert df["sector_score"].isna().all()
    # stock_score must still be computed via the renormalized remaining weights, not NaN
    assert df["stock_score"].notna().all()


def test_weights_sum_to_one():
    assert abs(sum(DEFAULT_STOCK_WEIGHTS.values()) - 1.0) < 1e-9


def test_role_assignment_uses_score_thresholds():
    scoring = StockScoring()
    df, _ = scoring.score_stocks(_mock_stocks(), _mock_scored_sectors())
    assert set(df["stock_role"].unique()).issubset({"領先龍頭", "高流動性次龍頭", "基本面受惠股", "低位階補漲股", "資料不足"})


def test_empty_input_returns_low_confidence():
    scoring = StockScoring()
    df, confidence = scoring.score_stocks(pd.DataFrame(), pd.DataFrame())
    assert confidence == "LOW"
    assert df.empty
