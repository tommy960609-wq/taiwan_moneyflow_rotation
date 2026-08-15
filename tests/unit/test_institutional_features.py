import sys
import os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.institutional_features import InstitutionalFeatures


def _make_inst_history(stock_id: str, foreign: list, trust: list, dealer=None) -> pd.DataFrame:
    n = len(foreign)
    dates = pd.bdate_range("2026-06-01", periods=n).strftime("%Y-%m-%d").tolist()
    dealer = dealer or [0.0] * n
    return pd.DataFrame({
        "trade_date": dates,
        "stock_id": [stock_id] * n,
        "foreign_net_buy": foreign,
        "investment_trust_net_buy": trust,
        "dealer_net_buy": dealer,
    })


def test_cumulative_sums_hand_calculated():
    # 5 constant days of foreign=100, trust=50 -> cum_3d=300/150, cum_5d=500/250
    df_hist = _make_inst_history("2330", foreign=[100.0] * 5, trust=[50.0] * 5)

    feat = InstitutionalFeatures()
    out = feat.calculate_cumulative_features(df_hist)

    last = out.iloc[-1]
    assert last["foreign_cum_3d"] == 300.0
    assert last["trust_cum_3d"] == 150.0
    assert last["foreign_cum_5d"] == 500.0
    assert last["trust_cum_5d"] == 250.0
    assert pd.isna(out.iloc[0]["foreign_cum_3d"])  # only 1 day so far
    assert pd.isna(out.iloc[1]["foreign_cum_5d"])  # only 2 days so far


def test_cumulative_min_periods_enforced_10_20d():
    closes_len = 25
    df_hist = _make_inst_history("2330", foreign=[10.0] * closes_len, trust=[5.0] * closes_len)

    feat = InstitutionalFeatures()
    out = feat.calculate_cumulative_features(df_hist)

    assert pd.isna(out.iloc[8]["foreign_cum_10d"])  # 9 days -> insufficient for 10d window
    assert pd.notna(out.iloc[9]["foreign_cum_10d"])  # 10th day -> window complete
    assert pd.isna(out.iloc[18]["foreign_cum_20d"])
    assert pd.notna(out.iloc[19]["foreign_cum_20d"])


def test_consecutive_buy_days_streak_hand_calculated():
    # Days: buy, buy, sell, buy, buy, buy -> streak should be 1,2,0,1,2,3
    foreign = [10.0, 10.0, -5.0, 10.0, 10.0, 10.0]
    trust = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    df_hist = _make_inst_history("2330", foreign=foreign, trust=trust)

    feat = InstitutionalFeatures()
    out = feat.calculate_cumulative_features(df_hist)

    assert list(out["consecutive_buy_days"]) == [1, 2, 0, 1, 2, 3]


def test_consecutive_buy_days_nan_on_missing_data_resets_streak():
    foreign = [10.0, np.nan, 10.0]
    trust = [0.0, np.nan, 0.0]
    df_hist = _make_inst_history("2330", foreign=foreign, trust=trust)

    feat = InstitutionalFeatures()
    out = feat.calculate_cumulative_features(df_hist)

    assert out.iloc[0]["consecutive_buy_days"] == 1
    assert pd.isna(out.iloc[1]["consecutive_buy_days"])
    assert out.iloc[2]["consecutive_buy_days"] == 1  # streak resets after missing day


def test_foreign_trust_same_direction_flag():
    foreign = [10.0, -5.0, 10.0, np.nan]
    trust = [5.0, -3.0, -2.0, 5.0]
    df_hist = _make_inst_history("2330", foreign=foreign, trust=trust)

    feat = InstitutionalFeatures()
    out = feat.calculate_cumulative_features(df_hist)

    assert out.iloc[0]["foreign_trust_same_direction"] == True   # both buy
    assert out.iloc[1]["foreign_trust_same_direction"] == False  # both sell (not "buy" direction)
    assert out.iloc[2]["foreign_trust_same_direction"] == False  # opposite signs
    assert pd.isna(out.iloc[3]["foreign_trust_same_direction"])  # missing foreign


def test_no_data_stock_never_zero_filled():
    """
    B-02 null discipline: a stock entirely absent from institutional data must
    surface as NaN throughout, never as a fabricated 0.
    """
    df_hist = _make_inst_history("2330", foreign=[np.nan] * 5, trust=[np.nan] * 5)

    feat = InstitutionalFeatures()
    out = feat.calculate_cumulative_features(df_hist)

    assert out["foreign_cum_3d"].isna().all()
    assert out["foreign_cum_5d"].isna().all()
    assert out["consecutive_buy_days"].isna().all()
    assert out["foreign_trust_same_direction"].isna().all()


def test_buy_pct_of_volume_hand_calculated():
    df_inst_day = pd.DataFrame([
        {"stock_id": "2330", "foreign_net_buy": 1000.0, "investment_trust_net_buy": 500.0},
        {"stock_id": "2317", "foreign_net_buy": np.nan, "investment_trust_net_buy": np.nan},
    ])
    df_price_day = pd.DataFrame([
        {"stock_id": "2330", "volume": 10000.0},
        {"stock_id": "2317", "volume": 5000.0},
    ])

    feat = InstitutionalFeatures()
    out = feat.calculate_buy_pct_of_volume(df_inst_day, df_price_day)

    row_2330 = out[out["stock_id"] == "2330"].iloc[0]
    assert row_2330["inst_buy_pct_of_volume"] == 0.15  # (1000+500)/10000

    row_2317 = out[out["stock_id"] == "2317"].iloc[0]
    assert pd.isna(row_2317["inst_buy_pct_of_volume"])  # both inputs missing -> NaN, not 0


def test_buy_pct_of_volume_zero_volume_is_nan_not_divide_error():
    df_inst_day = pd.DataFrame([{"stock_id": "2330", "foreign_net_buy": 100.0, "investment_trust_net_buy": 0.0}])
    df_price_day = pd.DataFrame([{"stock_id": "2330", "volume": 0.0}])

    feat = InstitutionalFeatures()
    out = feat.calculate_buy_pct_of_volume(df_inst_day, df_price_day)

    assert pd.isna(out.iloc[0]["inst_buy_pct_of_volume"])


def test_quarter_end_window_flag_last_5_trading_days_of_quarter_month():
    # March 2026 trading days (weekdays only)
    dates = pd.bdate_range("2026-03-01", "2026-03-31")
    series = pd.Series(dates)

    feat = InstitutionalFeatures()
    flags = feat.flag_quarter_end_window(series)

    last_5 = flags.iloc[-5:]
    assert last_5.all()
    before_last_5 = flags.iloc[:-5]
    assert not before_last_5.any()


def test_quarter_end_window_flag_non_quarter_month_all_false():
    # April is not a quarter-end month (3/6/9/12)
    dates = pd.bdate_range("2026-04-01", "2026-04-30")
    series = pd.Series(dates)

    feat = InstitutionalFeatures()
    flags = feat.flag_quarter_end_window(series)

    assert not flags.any()


def test_quarter_end_window_boundary_exact_5th_last_day_true_6th_false():
    dates = pd.bdate_range("2026-06-01", "2026-06-30")
    series = pd.Series(dates)

    feat = InstitutionalFeatures()
    flags = feat.flag_quarter_end_window(series)

    # 6th-from-last must be False, 5th-from-last (boundary) must be True
    assert flags.iloc[-6] == False
    assert flags.iloc[-5] == True


def test_sector_aggregation_net_buying_count_and_total():
    df_stock_inst = pd.DataFrame([
        {"stock_id": "2330", "foreign_net_buy": 1000.0, "investment_trust_net_buy": 200.0},
        {"stock_id": "2454", "foreign_net_buy": -500.0, "investment_trust_net_buy": 100.0},  # net -400
        {"stock_id": "3017", "foreign_net_buy": np.nan, "investment_trust_net_buy": np.nan},  # no data
    ])
    df_mapped_prices = pd.DataFrame([
        {"stock_id": "2330", "primary_sector": "半導體", "turnover": 100000.0},
        {"stock_id": "2454", "primary_sector": "半導體", "turnover": 50000.0},
        {"stock_id": "3017", "primary_sector": "半導體", "turnover": 30000.0},
    ])

    feat = InstitutionalFeatures()
    out = feat.aggregate_sector_institutional(df_stock_inst, df_mapped_prices)

    semi = out[out["sector_name"] == "半導體"].iloc[0]
    assert semi["net_buying_stock_count"] == 1  # only 2330 net > 0
    assert semi["sector_net_buy_total"] == 1000.0 + 200.0 - 500.0 + 100.0  # 800.0
    expected_pct = 800.0 / (100000.0 + 50000.0 + 30000.0)
    assert abs(semi["sector_net_buy_pct_of_turnover"] - expected_pct) < 1e-9


def test_sector_aggregation_no_institutional_data_returns_nan_not_zero():
    df_stock_inst = pd.DataFrame([
        {"stock_id": "2330", "foreign_net_buy": np.nan, "investment_trust_net_buy": np.nan},
    ])
    df_mapped_prices = pd.DataFrame([
        {"stock_id": "2330", "primary_sector": "半導體", "turnover": 100000.0},
    ])

    feat = InstitutionalFeatures()
    out = feat.aggregate_sector_institutional(df_stock_inst, df_mapped_prices)

    semi = out[out["sector_name"] == "半導體"].iloc[0]
    assert pd.isna(semi["sector_net_buy_total"])
    assert pd.isna(semi["net_buying_stock_count"])
