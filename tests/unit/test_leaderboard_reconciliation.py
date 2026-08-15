import sys
import os
import math

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.leaderboard_reconciliation import (
    compute_finmind_prevclose_returns,
    reconcile_leaderboard_vs_finmind,
    summarize_reconciliation,
    DEVIATION_THRESHOLD_PCT,
)


def test_compute_finmind_prevclose_returns_basic():
    df_ohlcv = pd.DataFrame([
        {"stock_id": "2330", "trade_date": "2026-04-20", "close": 100.0},
        {"stock_id": "2330", "trade_date": "2026-04-21", "close": 105.0},
        {"stock_id": "2330", "trade_date": "2026-04-22", "close": 100.0},
    ])
    out = compute_finmind_prevclose_returns(df_ohlcv).set_index("trade_date")
    assert pd.isna(out.loc["2026-04-20", "finmind_prevclose_return_pct"])  # no prior close
    assert abs(out.loc["2026-04-21", "finmind_prevclose_return_pct"] - 5.0) < 1e-9
    assert abs(out.loc["2026-04-22", "finmind_prevclose_return_pct"] - (-4.761904)) < 1e-4


def test_compute_finmind_prevclose_returns_guards_zero_prev_close():
    # Real observed FinMind data anomaly: a zero-close row followed by a real close.
    # Must produce NaN (excluded from comparison), never +/-inf.
    df_ohlcv = pd.DataFrame([
        {"stock_id": "2321", "trade_date": "2026-06-08", "close": 0.0},
        {"stock_id": "2321", "trade_date": "2026-06-09", "close": 15.0},
    ])
    out = compute_finmind_prevclose_returns(df_ohlcv).set_index("trade_date")
    val = out.loc["2026-06-09", "finmind_prevclose_return_pct"]
    assert pd.isna(val) or math.isfinite(val)
    assert not (isinstance(val, float) and math.isinf(val))


def test_compute_finmind_prevclose_returns_independent_per_stock():
    df_ohlcv = pd.DataFrame([
        {"stock_id": "A", "trade_date": "2026-04-20", "close": 10.0},
        {"stock_id": "B", "trade_date": "2026-04-20", "close": 999.0},
        {"stock_id": "A", "trade_date": "2026-04-21", "close": 11.0},
    ])
    out = compute_finmind_prevclose_returns(df_ohlcv)
    row_a = out[(out.stock_id == "A") & (out.trade_date == "2026-04-21")].iloc[0]
    assert abs(row_a["finmind_prevclose_return_pct"] - 10.0) < 1e-9


def test_reconcile_matches_within_threshold():
    df_lb = pd.DataFrame([
        {"trade_date": "2026-04-21", "stock_id": "2330", "return_pct": 5.0},
    ])
    df_ohlcv = pd.DataFrame([
        {"stock_id": "2330", "trade_date": "2026-04-20", "close": 100.0},
        {"stock_id": "2330", "trade_date": "2026-04-21", "close": 105.0},
    ])
    out = reconcile_leaderboard_vs_finmind(df_lb, df_ohlcv)
    row = out.iloc[0]
    assert row["has_finmind_comparison"] == True
    assert abs(row["abs_deviation_pct"]) < 1e-9
    assert row["deviation_exceeds_threshold"] == False


def test_reconcile_flags_deviation_beyond_threshold():
    df_lb = pd.DataFrame([
        {"trade_date": "2026-04-21", "stock_id": "2330", "return_pct": 5.0},
    ])
    df_ohlcv = pd.DataFrame([
        {"stock_id": "2330", "trade_date": "2026-04-20", "close": 100.0},
        {"stock_id": "2330", "trade_date": "2026-04-21", "close": 110.0},  # 10% actual
    ])
    out = reconcile_leaderboard_vs_finmind(df_lb, df_ohlcv)
    row = out.iloc[0]
    assert row["abs_deviation_pct"] > DEVIATION_THRESHOLD_PCT
    assert row["deviation_exceeds_threshold"] == True


def test_reconcile_no_finmind_comparison_excluded_from_deviation_but_counted():
    df_lb = pd.DataFrame([
        {"trade_date": "2026-04-20", "stock_id": "9999", "return_pct": 5.0},  # no FinMind data at all
    ])
    df_ohlcv = pd.DataFrame(columns=["stock_id", "trade_date", "close"])
    out = reconcile_leaderboard_vs_finmind(df_lb, df_ohlcv)
    row = out.iloc[0]
    assert row["has_finmind_comparison"] == False
    assert row["deviation_exceeds_threshold"] == False  # never flagged when uncomparable


def test_reconcile_empty_leaderboard_returns_empty():
    out = reconcile_leaderboard_vs_finmind(pd.DataFrame(), pd.DataFrame())
    assert out.empty


def test_summarize_reconciliation_headline_numbers():
    df_lb = pd.DataFrame([
        {"trade_date": "2026-04-21", "stock_id": "A", "return_pct": 5.0},
        {"trade_date": "2026-04-21", "stock_id": "B", "return_pct": 5.0},
        {"trade_date": "2026-04-21", "stock_id": "C", "return_pct": 5.0},  # no finmind data
    ])
    df_ohlcv = pd.DataFrame([
        {"stock_id": "A", "trade_date": "2026-04-20", "close": 100.0},
        {"stock_id": "A", "trade_date": "2026-04-21", "close": 105.0},  # exact match
        {"stock_id": "B", "trade_date": "2026-04-20", "close": 100.0},
        {"stock_id": "B", "trade_date": "2026-04-21", "close": 120.0},  # 20% actual, big deviation
    ])
    reconciled = reconcile_leaderboard_vs_finmind(df_lb, df_ohlcv)
    summary = summarize_reconciliation(reconciled)
    assert summary["total_leaderboard_rows"] == 3
    assert summary["rows_with_finmind_comparison"] == 2
    assert summary["coverage_pct"] == round(2 / 3, 4)
    assert summary["rows_exceeding_threshold"] == 1
    assert summary["pct_exceeding_threshold"] == 0.5


def test_summarize_reconciliation_empty_input():
    summary = summarize_reconciliation(pd.DataFrame())
    assert summary["total_leaderboard_rows"] == 0
    assert summary["coverage_pct"] is None
