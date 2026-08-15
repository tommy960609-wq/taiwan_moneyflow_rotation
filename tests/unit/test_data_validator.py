import sys
import os
import pytest
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.data_validator import DataValidator

def test_data_validator_blocked():
    validator = DataValidator()
    score, status, issues = validator.calculate_quality_score(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), 0.0)
    assert status == "BLOCKED"
    assert score <= 70.0
    assert any("empty" in issue.lower() for issue in issues)

def test_data_validator_date_mismatch():
    validator = DataValidator()
    
    # Mock prices with mismatched dates
    df_mock = pd.DataFrame([
        {
            "stock_id": "2330",
            "open": 100.0,
            "high": 105.0,
            "low": 95.0,
            "close": 102.0,
            "volume": 1000.0,
            "trade_date": "2026-07-15",
            "market_type": "TWSE"
        }
    ])
    
    score, status, issues = validator.calculate_quality_score(
        df_ohlcv=df_mock, 
        df_inst=pd.DataFrame(), 
        df_margin=pd.DataFrame(), 
        mapping_coverage_pct=0.90,
        target_date="2026-07-16" # Target is 7/16, but data is 7/15
    )
    
    assert score < 100.0
    assert any("date" in issue.lower() for issue in issues)
