import json

import pandas as pd

from src.observe_rankings import (
    build_observe_rankings,
)


def _stocks():
    return pd.DataFrame([
        {"stock_id": "2330", "stock_name": "A", "primary_sector": "半導體", "daily_return": 0.10,
         "turnover": 1000, "foreign_net_buy": 10, "investment_trust_net_buy": 2, "dealer_net_buy": 1},
        {"stock_id": "2317", "stock_name": "B", "primary_sector": "半導體", "daily_return": 0.10,
         "turnover": 2000, "foreign_net_buy": -5, "investment_trust_net_buy": 0, "dealer_net_buy": 0},
        {"stock_id": "1101", "stock_name": "C", "primary_sector": "水泥", "daily_return": -0.05,
         "turnover": 3000, "foreign_net_buy": -20, "investment_trust_net_buy": 1, "dealer_net_buy": 2},
    ])


def test_observe_rankings_has_all_four_sections_and_fixed_ties():
    result = build_observe_rankings(_stocks(), "2026-07-20", ranking_depth=2, sector_top_n=2)

    assert result["trade_date"] == "2026-07-20"
    assert set(result["rankings"]) == {"top_gainers", "top_losers", "top_turnover"}
    assert "institutional_by_sector" in result
    # Same return: turnover descending, then stock_id ascending.
    assert [row["stock_id"] for row in result["rankings"]["top_gainers"]["stocks"]] == ["2317", "2330"]
    assert result["institutional_by_sector"]["net_buy_top5"][0]["sector_name"] == "半導體"


def test_observe_rankings_is_repeatable_and_uses_only_input_rows():
    first = build_observe_rankings(_stocks(), "2026-07-20", ranking_depth=2, sector_top_n=2)
    second = build_observe_rankings(_stocks(), "2026-07-20", ranking_depth=2, sector_top_n=2)

    assert first == second
    assert first["metadata"]["network_calls"] == 0


def test_explicit_observe_defaults_preserve_existing_output():
    implicit_defaults = build_observe_rankings(_stocks(), "2026-07-20")
    explicit_defaults = build_observe_rankings(
        _stocks(), "2026-07-20", ranking_depth=300, sector_top_n=5
    )

    assert json.dumps(explicit_defaults, ensure_ascii=False, indent=2, sort_keys=True) == json.dumps(
        implicit_defaults, ensure_ascii=False, indent=2, sort_keys=True
    )
