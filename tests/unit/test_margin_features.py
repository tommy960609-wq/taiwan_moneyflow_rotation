import sys
import os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.margin_features import MarginFeatures


def _make_margin_history(stock_id: str, balances: list, short_balances=None, quotas=None) -> pd.DataFrame:
    n = len(balances)
    dates = pd.bdate_range("2026-06-01", periods=n).strftime("%Y-%m-%d").tolist()
    short_balances = short_balances or [0.0] * n
    df = pd.DataFrame({
        "trade_date": dates,
        "stock_id": [stock_id] * n,
        "margin_balance": balances,
        "short_balance": short_balances,
    })
    if quotas is not None:
        df["margin_quota"] = quotas
    return df


def test_margin_balance_chg_pct_hand_calculated():
    # balances: 100, 110, 121, 133.1, 146.41, 161.051 (10% growth each day, 6 days
    # so that a 5-trading-day-lookback pct_change has a valid base on the last row)
    balances = [100.0, 110.0, 121.0, 133.1, 146.41, 161.051]
    df_hist = _make_margin_history("2330", balances)

    feat = MarginFeatures()
    out = feat.calculate_margin_change_features(df_hist)

    last = out.iloc[-1]
    # 3d change: 161.051 vs balances[2]=121.0 -> (161.051-121.0)/121.0
    expected_3d = (161.051 - 121.0) / 121.0
    assert abs(last["margin_balance_chg_pct_3d"] - expected_3d) < 1e-6
    # 5d change: 161.051 vs balances[0]=100.0 -> (161.051-100.0)/100.0
    expected_5d = (161.051 - 100.0) / 100.0
    assert abs(last["margin_balance_chg_pct_5d"] - expected_5d) < 1e-6


def test_margin_balance_chg_pct_nan_when_insufficient_history():
    balances = [100.0, 110.0]  # only 2 days
    df_hist = _make_margin_history("2330", balances)

    feat = MarginFeatures()
    out = feat.calculate_margin_change_features(df_hist)

    assert out.iloc[0]["margin_balance_chg_pct_3d"] != out.iloc[0]["margin_balance_chg_pct_3d"] or pd.isna(out.iloc[0]["margin_balance_chg_pct_3d"])
    assert pd.isna(out.iloc[1]["margin_balance_chg_pct_3d"])
    assert pd.isna(out.iloc[1]["margin_balance_chg_pct_5d"])


def test_short_margin_ratio_hand_calculated():
    df_hist = _make_margin_history("2330", balances=[1000.0], short_balances=[50.0])

    feat = MarginFeatures()
    out = feat.calculate_margin_change_features(df_hist)

    assert out.iloc[0]["short_margin_ratio"] == 0.05


def test_short_margin_ratio_nan_when_margin_balance_zero():
    df_hist = _make_margin_history("2330", balances=[0.0], short_balances=[10.0])

    feat = MarginFeatures()
    out = feat.calculate_margin_change_features(df_hist)

    assert pd.isna(out.iloc[0]["short_margin_ratio"])


def test_short_margin_ratio_nan_when_missing_not_zero():
    df_hist = _make_margin_history("2330", balances=[np.nan], short_balances=[10.0])

    feat = MarginFeatures()
    out = feat.calculate_margin_change_features(df_hist)

    assert pd.isna(out.iloc[0]["short_margin_ratio"])


def test_usage_rate_with_real_quota_column():
    df_hist = _make_margin_history("2330", balances=[500.0], quotas=[1000.0])

    feat = MarginFeatures()
    out = feat.calculate_usage_rate_proxy(df_hist)

    assert out.iloc[0]["margin_usage_rate"] == 0.5
    assert "margin_usage_rate_proxy" not in out.columns


def test_usage_rate_proxy_fallback_when_no_quota_column():
    balances = [100.0 + i * 5 for i in range(25)]
    df_hist = _make_margin_history("2330", balances)

    feat = MarginFeatures()
    out = feat.calculate_usage_rate_proxy(df_hist)

    assert "margin_usage_rate_proxy" in out.columns
    assert "margin_usage_rate" not in out.columns
    # last row: balance is the rolling max so far (monotonic increasing) -> ratio == 1.0
    assert abs(out.iloc[-1]["margin_usage_rate_proxy"] - 1.0) < 1e-9
    # early rows (fewer than min_periods=20) should be NaN
    assert pd.isna(out.iloc[5]["margin_usage_rate_proxy"])


def test_usage_rate_quota_zero_or_missing_is_nan():
    df_hist = _make_margin_history("2330", balances=[500.0, 600.0], quotas=[1000.0, 0.0])

    feat = MarginFeatures()
    out = feat.calculate_usage_rate_proxy(df_hist)

    assert out.iloc[0]["margin_usage_rate"] == 0.5
    assert pd.isna(out.iloc[1]["margin_usage_rate"])
