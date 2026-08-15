import os
import sys

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from scripts.run_daily import _attach_top5_stocks


def _stocks():
    return pd.DataFrame([
        {
            "stock_id": "2330", "stock_name": "半導體龍頭", "primary_sector": "半導體",
            "theme_1": "AI", "theme_2": None, "theme_3": None, "stock_score": 80.0,
        },
        {
            "stock_id": "2454", "stock_name": "AI龍頭", "primary_sector": "半導體",
            "theme_1": "Edge AI", "theme_2": None, "theme_3": None, "stock_score": 90.0,
        },
    ])


def test_theme_membership_uses_authoritative_resolver():
    sectors = pd.DataFrame([
        {"sector_name": "Edge AI", "sector_type": "theme"},
        {"sector_name": "半導體", "sector_type": "primary"},
    ])
    result = _attach_top5_stocks(sectors, _stocks())
    assert result.loc[0, "top5_stocks"] == "AI龍頭(2454)"
    assert result.loc[1, "top5_stocks"] == "AI龍頭(2454)、半導體龍頭(2330)"


def test_missing_sector_type_falls_back_to_primary_behavior():
    sectors = pd.DataFrame([{"sector_name": "半導體"}])
    result = _attach_top5_stocks(sectors, _stocks())
    assert result.loc[0, "top5_stocks"] == "AI龍頭(2454)、半導體龍頭(2330)"
