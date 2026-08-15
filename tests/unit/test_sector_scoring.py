import sys
import os
import pytest
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.sector_scoring import SectorScoring

def test_dynamic_weight_renormalization():
    scoring = SectorScoring()
    df_mock = pd.DataFrame([{
        "sector_name": "半導體",
        "breadth": 0.8,
        "volume_share": 0.15,
        "relative_strength": 0.02,
        "inst_flow_ratio": 0.05,
        "hhi": 0.2,
        "total_turnover": 1000000.0,
        "stock_count": 5
    }])
    
    # has institutional
    df_full, conf_full = scoring.score_sectors(df_mock, has_institutional=True)
    assert conf_full == "FULL"
    assert "score" in df_full.columns
    
    # missing institutional
    df_degraded, conf_degraded = scoring.score_sectors(df_mock, has_institutional=False)
    assert conf_degraded == "DEGRADED"
    assert "score" in df_degraded.columns
    
    score_val = df_degraded.iloc[0]["score"]
    assert 0.0 <= score_val <= 100.0
