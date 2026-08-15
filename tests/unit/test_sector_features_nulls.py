import sys
import os
import pytest
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.sector_features import SectorFeatures

def test_sector_features_nan_preservation():
    """
    Unit Test: Asserts that SectorFeatures.calculate_sector_metrics preserves
    NaN (Null) values for missing institutional flows (B-02 compliance downstream behavior).
    """
    # 1. Mock mapped prices
    df_prices = pd.DataFrame([
        {
            "stock_id": "2330",
            "stock_name": "台積電",
            "open": 100.0,
            "high": 105.0,
            "low": 95.0,
            "close": 102.0,
            "volume": 1000.0,
            "turnover": 102000.0,
            "primary_sector": "半導體",
            "theme_1": "GB200",
            "theme_2": None,
            "theme_3": None
        }
    ])
    
    # 2. Mock institutional flows with missing (NaN) values for 2330
    # e.g., We have a flow table but 2330 is NOT inside it
    df_inst = pd.DataFrame([
        {
            "stock_id": "2317", # Different stock
            "foreign_net_buy": 500.0,
            "investment_trust_net_buy": 100.0,
            "dealer_net_buy": 50.0
        }
    ])
    
    sf = SectorFeatures()
    df_metrics = sf.calculate_sector_metrics(df_prices, df_inst)
    
    assert not df_metrics.empty
    
    # Assert that inst_flow_ratio for the "半導體" sector is NaN
    # because the only stock in "半導體" (2330) has no institutional statistics (retains NaN, B-02 compliance)
    row_semi = df_metrics[df_metrics["sector_name"] == "半導體"]
    assert not row_semi.empty
    
    # Check that inst_flow_ratio is indeed NaN
    ratio_val = row_semi.iloc[0]["inst_flow_ratio"]
    assert np.isnan(ratio_val), f"Expected NaN, but got {ratio_val}"
    
    print("Downstream sector features NaN preservation verified successfully!")
