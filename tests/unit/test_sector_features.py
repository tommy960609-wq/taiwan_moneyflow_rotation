import sys
import os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.sector_features import SectorFeatures


def _mock_prices():
    return pd.DataFrame([
        {"stock_id": "2330", "stock_name": "台積電", "open": 100.0, "high": 105.0, "low": 95.0, "close": 110.0,
         "volume": 1000.0, "turnover": 110000.0, "primary_sector": "半導體", "theme_1": "CoWoS", "theme_2": None, "theme_3": None},
        {"stock_id": "2454", "stock_name": "聯發科", "open": 500.0, "high": 510.0, "low": 490.0, "close": 495.0,
         "volume": 200.0, "turnover": 99000.0, "primary_sector": "半導體", "theme_1": "CoWoS", "theme_2": "ASIC", "theme_3": None},
        {"stock_id": "3017", "stock_name": "奇鋐", "open": 600.0, "high": 620.0, "low": 590.0, "close": 615.0,
         "volume": 300.0, "turnover": 184500.0, "primary_sector": "電子零組件", "theme_1": "GB200", "theme_2": None, "theme_3": None},
    ])


def test_breadth_uses_full_market_membership_not_leaderboard_proxy():
    """
    A-1 compliance: breadth = up-count / full sector membership count, computed from
    full-market OHLCV rows -- not a leaderboard-entry proxy.
    """
    df = _mock_prices()
    sf = SectorFeatures()
    out = sf.calculate_sector_metrics(df)

    semi = out[(out["sector_name"] == "半導體") & (out["sector_type"] == "primary")].iloc[0]
    # 2330 up (+10%), 2454 down (-1%) -> 1 of 2 stocks up
    assert semi["stock_count"] == 2
    assert semi["up_stock_count"] == 1
    assert semi["breadth"] == 0.5


def test_breadth_range_0_to_1():
    df = _mock_prices()
    sf = SectorFeatures()
    out = sf.calculate_sector_metrics(df)
    assert ((out["breadth"] >= 0.0) & (out["breadth"] <= 1.0)).all()


def test_hhi_range_and_concentration_metrics():
    df = _mock_prices()
    sf = SectorFeatures()
    out = sf.calculate_sector_metrics(df)

    semi = out[(out["sector_name"] == "半導體") & (out["sector_type"] == "primary")].iloc[0]
    # HHI must be in [1/n, 1]
    assert 0.5 <= semi["hhi"] <= 1.0
    assert semi["top1_concentration"] >= semi["top3_concentration"] * 0.0 + 0  # sanity: non-negative
    assert 0.0 <= semi["top1_concentration"] <= 1.0
    assert semi["top1_concentration"] <= semi["top3_concentration"]
    assert semi["top3_concentration"] <= semi["top5_concentration"] or semi["stock_count"] < 5


def test_primary_sector_volume_no_double_counting_p0_05():
    """
    P0-05: summing primary_sector turnover across all primary-sector rows must equal
    total market turnover exactly once (each stock belongs to exactly one
    primary_sector), and these rows must be flagged may_double_count=False.
    """
    df = _mock_prices()
    sf = SectorFeatures()
    out = sf.calculate_sector_metrics(df)

    primary_rows = out[out["sector_type"] == "primary"]
    assert (primary_rows["may_double_count"] == False).all()

    total_primary_turnover = primary_rows["total_turnover"].sum()
    total_market_turnover = df["turnover"].sum()
    assert abs(total_primary_turnover - total_market_turnover) < 1e-6


def test_theme_aggregation_flags_may_double_count_true():
    """
    P0-05: theme aggregates allow a stock to belong to multiple themes (theme_1/2/3),
    so theme turnover totals may legitimately exceed market turnover. These rows must
    be explicitly flagged may_double_count=True so downstream consumers cannot
    mistake theme totals for a non-overlapping partition of the market.
    """
    df = _mock_prices()
    sf = SectorFeatures()
    out = sf.calculate_sector_metrics(df)

    theme_rows = out[out["sector_type"] == "theme"]
    assert not theme_rows.empty
    assert (theme_rows["may_double_count"] == True).all()

    # 2330 and 2454 both belong to theme "CoWoS" -> their turnover is counted once in
    # the primary_sector total, but the theme aggregate double-counts them relative to
    # the primary/market partition. Verify CoWoS turnover reflects both contributing stocks.
    cowos_row = theme_rows[theme_rows["sector_name"] == "CoWoS"].iloc[0]
    assert abs(cowos_row["total_turnover"] - (110000.0 + 99000.0)) < 1e-6


def test_volume_share_sums_to_approximately_100_pct_for_primary_sectors():
    df = _mock_prices()
    sf = SectorFeatures()
    out = sf.calculate_sector_metrics(df)

    primary_rows = out[out["sector_type"] == "primary"]
    total_share = primary_rows["volume_share"].sum()
    assert abs(total_share - 1.0) < 1e-6


def test_missing_institutional_flow_preserves_nan_not_zero():
    df = _mock_prices()
    df_inst = pd.DataFrame([{"stock_id": "9999", "foreign_net_buy": 500.0, "investment_trust_net_buy": 100.0, "dealer_net_buy": 0.0}])

    sf = SectorFeatures()
    out = sf.calculate_sector_metrics(df, df_inst)

    semi = out[(out["sector_name"] == "半導體") & (out["sector_type"] == "primary")].iloc[0]
    assert np.isnan(semi["inst_flow_ratio"]), "inst_flow_ratio must stay NaN, never zero-filled, when no institutional data matches"


def test_relative_strength_rolling_history_min_periods():
    """
    relative_strength_3d/5d must be NaN until the sector has accumulated at least
    3/5 days of history respectively (min_periods enforced, no partial-window sums).
    """
    dates = pd.bdate_range("2026-06-01", periods=6).strftime("%Y-%m-%d").tolist()
    df_hist = pd.DataFrame([
        {"trade_date": d, "sector_name": "半導體", "relative_strength_1d": 0.01 * (i + 1)}
        for i, d in enumerate(dates)
    ])

    sf = SectorFeatures()
    out = sf.calculate_relative_strength_history(df_hist)

    assert out.iloc[0]["relative_strength_3d"] != out.iloc[0]["relative_strength_3d"] or pd.isna(out.iloc[0]["relative_strength_3d"])
    assert pd.isna(out.iloc[1]["relative_strength_3d"])  # only 2 days so far
    assert pd.notna(out.iloc[2]["relative_strength_3d"])  # 3rd day: window complete
    assert pd.isna(out.iloc[3]["relative_strength_5d"])  # only 4 days so far
    assert pd.notna(out.iloc[4]["relative_strength_5d"])  # 5th day: window complete
