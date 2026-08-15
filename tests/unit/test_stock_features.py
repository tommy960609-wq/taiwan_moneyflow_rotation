import sys
import os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.stock_features import StockFeatures


def _make_history(stock_id: str, closes: list, base_volume: float = 10000.0) -> pd.DataFrame:
    dates = pd.bdate_range("2026-06-01", periods=len(closes)).strftime("%Y-%m-%d").tolist()
    rows = []
    for i, (d, c) in enumerate(zip(dates, closes)):
        rows.append({
            "trade_date": d,
            "stock_id": stock_id,
            "open": c * 0.99,
            "high": c * 1.01,
            "low": c * 0.98,
            "close": c,
            "volume": base_volume + i * 100,
            "turnover": (base_volume + i * 100) * c,
        })
    return pd.DataFrame(rows)


def test_rolling_features_insufficient_history_returns_nan():
    """
    Fewer than min_periods days of history -> NaN, never a fabricated/backfilled value.
    vol_ma5/vol_ma20 require min_periods=3/10; high_20d requires min_periods=10.
    """
    closes = [100.0, 101.0]  # only 2 days of history
    df_hist = _make_history("2330", closes)

    sf = StockFeatures()
    out = sf.calculate_rolling_features(df_hist)

    assert out["vol_ma5"].isna().all(), "vol_ma5 should be NaN with only 2 days of history (min_periods=3)"
    assert out["high_20d"].isna().all(), "high_20d should be NaN with only 2 days of history (min_periods=10)"
    assert out["return_5d"].isna().all()


def test_rolling_features_sufficient_history_computes_values():
    closes = [100.0 + i for i in range(25)]  # 25 days, monotonically increasing
    df_hist = _make_history("2330", closes)

    sf = StockFeatures()
    out = sf.calculate_rolling_features(df_hist)

    last_row = out.iloc[-1]
    assert pd.notna(last_row["vol_ma5"])
    assert pd.notna(last_row["vol_ma20"])
    assert pd.notna(last_row["high_20d"])
    # Monotonically increasing closes -> 20d high should equal the current close
    assert last_row["high_20d"] == out["close"].iloc[-1]
    assert last_row["dist_from_20d_high"] == 0.0
    assert pd.notna(last_row["return_1d"])
    assert pd.notna(last_row["return_20d"])


def test_rolling_features_no_future_leakage():
    """
    Regression test (SPEC 26.6 style): computing rolling features on a dataset
    truncated at day T must produce IDENTICAL values (for all days <= T) as computing
    on the full dataset that includes T+1..T+20. This is the core anti-future-function
    guard for stock_features.
    """
    closes = [100.0 + np.sin(i / 3.0) * 5 + i * 0.5 for i in range(40)]
    df_full = _make_history("2330", closes)

    cutoff_idx = 25  # Dataset A: truncated at day T (index 24, 0-based -> 25 rows)
    df_truncated = df_full.iloc[:cutoff_idx].copy()

    sf = StockFeatures()
    out_full = sf.calculate_rolling_features(df_full.copy())
    out_truncated = sf.calculate_rolling_features(df_truncated)

    compare_cols = [
        "vol_ma5", "vol_ma20", "relative_volume_5d", "relative_volume_20d",
        "high_20d", "dist_from_20d_high",
        "return_1d", "return_3d", "return_5d", "return_10d", "return_20d",
    ]

    out_full_prefix = out_full.iloc[:cutoff_idx].reset_index(drop=True)
    out_truncated = out_truncated.reset_index(drop=True)

    for col in compare_cols:
        pd.testing.assert_series_equal(
            out_full_prefix[col], out_truncated[col], check_names=False,
            obj=f"Future leakage detected in column '{col}'"
        )


def test_rolling_features_multi_stock_independence():
    """
    Rolling windows must be computed per-stock (groupby stock_id), not across the
    whole market -- one stock's history must never leak into another's rolling stats.
    """
    df_a = _make_history("2330", [100.0 + i for i in range(10)], base_volume=10000.0)
    df_b = _make_history("2317", [50.0] * 10, base_volume=99999.0)  # flat price, different volume base
    df_hist = pd.concat([df_a, df_b], ignore_index=True)

    sf = StockFeatures()
    out = sf.calculate_rolling_features(df_hist)

    row_a = out[out["stock_id"] == "2330"].iloc[-1]
    row_b = out[out["stock_id"] == "2317"].iloc[-1]

    assert row_a["vol_ma5"] != row_b["vol_ma5"], "rolling volume mean must not mix across stocks"
    assert row_b["return_1d"] == 0.0  # flat series -> zero return
    assert row_a["return_1d"] > 0.0


def test_calculate_ranks_new_entry_flagging_preserved():
    """
    Backward-compat check: calculate_ranks (rank-improvement vs prior single day)
    still behaves as before -- stocks absent from yesterday's snapshot must be
    flagged is_new_entry=1, not assigned an arbitrary prior rank.
    """
    df_today = pd.DataFrame([
        {"stock_id": "2330", "open": 100.0, "close": 110.0},
        {"stock_id": "9999", "open": 50.0, "close": 60.0},  # new entrant today
    ])
    df_prev = pd.DataFrame([
        {"stock_id": "2330", "open": 95.0, "close": 100.0},
    ])

    sf = StockFeatures()
    out = sf.calculate_ranks(df_today, df_prev)

    new_row = out[out["stock_id"] == "9999"].iloc[0]
    assert new_row["is_new_entry"] == 1
