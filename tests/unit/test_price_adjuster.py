import sys
import os
import json

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.price_adjuster import (
    compute_adjustment_factor_table,
    apply_adjustment,
    fetch_dividend_events,
    build_adjustment_factor_table_for_universe,
)
from src.finmind_fetcher import FinMindResult


# ---------------------------------------------------------------------------
# compute_adjustment_factor_table: the core backward-adjustment math.
# ---------------------------------------------------------------------------

def test_no_dividend_events_gives_factor_1_everywhere():
    trade_dates = ["2026-04-20", "2026-04-21", "2026-04-22"]
    df = compute_adjustment_factor_table("2330", [], trade_dates)
    assert len(df) == 3
    assert (df["adj_factor"] == 1.0).all()


def test_single_event_scales_only_bars_strictly_before_it():
    # Mirrors tests/unit/test_dividend_adjustment.py's scaffold: before_price=100,
    # after_price=95 -> factor = 0.95, applied to all bars before the ex-div date.
    events = [{"date": "2026-04-22", "before_price": 100.0, "after_price": 95.0}]
    trade_dates = ["2026-04-20", "2026-04-21", "2026-04-22", "2026-04-23"]
    df = compute_adjustment_factor_table("2330", events, trade_dates).set_index("trade_date")
    assert df.loc["2026-04-20", "adj_factor"] == 0.95
    assert df.loc["2026-04-21", "adj_factor"] == 0.95
    assert df.loc["2026-04-22", "adj_factor"] == 1.0
    assert df.loc["2026-04-23", "adj_factor"] == 1.0


def test_multiple_events_compound_multiplicatively():
    events = [
        {"date": "2026-05-01", "before_price": 100.0, "after_price": 90.0},  # factor 0.9
        {"date": "2026-06-01", "before_price": 200.0, "after_price": 180.0},  # factor 0.9
    ]
    trade_dates = ["2026-04-01", "2026-05-15", "2026-06-15"]
    df = compute_adjustment_factor_table("2330", events, trade_dates).set_index("trade_date")
    # Before BOTH events: compounds 0.9 * 0.9 = 0.81
    assert abs(df.loc["2026-04-01", "adj_factor"] - 0.81) < 1e-9
    # Between the two events (after May event, before June event): only June's factor applies
    assert abs(df.loc["2026-05-15", "adj_factor"] - 0.9) < 1e-9
    # After both events
    assert df.loc["2026-06-15", "adj_factor"] == 1.0


def test_malformed_event_skipped_not_raised():
    events = [
        {"date": "2026-05-01", "before_price": 0, "after_price": 90.0},  # before_price=0, skip
        {"date": None, "before_price": 100.0, "after_price": 90.0},  # no date, skip
        {"date": "2026-05-01", "before_price": "not-a-number", "after_price": 90.0},  # non-numeric
    ]
    trade_dates = ["2026-04-01"]
    df = compute_adjustment_factor_table("2330", events, trade_dates)
    # All 3 events malformed -> no real adjustment, factor stays 1.0
    assert (df["adj_factor"] == 1.0).all()


def test_empty_trade_dates_returns_empty_frame():
    df = compute_adjustment_factor_table("2330", [{"date": "2026-05-01", "before_price": 100.0, "after_price": 90.0}], [])
    assert df.empty
    assert list(df.columns) == ["stock_id", "trade_date", "adj_factor"]


# ---------------------------------------------------------------------------
# apply_adjustment: merge onto OHLCV, tag UNADJUSTED where no factor exists.
# ---------------------------------------------------------------------------

def test_apply_adjustment_scales_ohlc_and_flags_unadjusted():
    df_ohlcv = pd.DataFrame([
        {"stock_id": "2330", "trade_date": "2026-04-20", "open": 100.0, "high": 105.0, "low": 95.0, "close": 100.0},
        {"stock_id": "9999", "trade_date": "2026-04-20", "open": 50.0, "high": 55.0, "low": 45.0, "close": 50.0},
    ])
    df_factors = pd.DataFrame([
        {"stock_id": "2330", "trade_date": "2026-04-20", "adj_factor": 0.9},
        # 9999 has NO factor entry at all -> must be tagged price_unadjusted=True
    ])
    out = apply_adjustment(df_ohlcv, df_factors)
    row_2330 = out[out.stock_id == "2330"].iloc[0]
    row_9999 = out[out.stock_id == "9999"].iloc[0]

    assert row_2330["price_unadjusted"] == False
    assert abs(row_2330["adj_close"] - 90.0) < 1e-9
    assert abs(row_2330["adj_open"] - 90.0) < 1e-9

    assert row_9999["price_unadjusted"] == True
    assert row_9999["adj_close"] == row_9999["close"]  # falls back to raw


def test_apply_adjustment_empty_ohlcv_returns_empty_with_columns():
    out = apply_adjustment(pd.DataFrame(), pd.DataFrame())
    assert out.empty
    for c in ("adj_open", "adj_high", "adj_low", "adj_close", "price_unadjusted"):
        assert c in out.columns


# ---------------------------------------------------------------------------
# fetch_dividend_events: fail-closed on a real fetch failure vs. a genuine
# zero-dividend stock (empty list is NOT a failure).
# ---------------------------------------------------------------------------

def test_fetch_dividend_events_empty_payload_is_not_a_failure():
    def stub_fn(dataset, token=None, data_id=None, start_date=None, end_date=None, **kwargs):
        return FinMindResult(success=True, payload=[], http_status=200)

    result = fetch_dividend_events("3008", "2026-01-01", "2026-07-17", fetch_fn=stub_fn)
    assert result == []  # genuinely zero dividends, not None


def test_fetch_dividend_events_real_failure_returns_none():
    def stub_fn(dataset, token=None, data_id=None, start_date=None, end_date=None, **kwargs):
        return FinMindResult(success=False, error="HTTP 500", http_status=500)

    result = fetch_dividend_events("2330", "2026-01-01", "2026-07-17", fetch_fn=stub_fn)
    assert result is None


# ---------------------------------------------------------------------------
# build_adjustment_factor_table_for_universe: end-to-end with injected fetch_fn,
# tmp_path-based OHLCV/dividend cache dirs (fully hermetic, no network).
# ---------------------------------------------------------------------------

def test_build_adjustment_factor_table_for_universe_end_to_end(tmp_path):
    ohlcv_dir = tmp_path / "ohlcv"
    ohlcv_dir.mkdir()
    # Two stocks: 2330 has a dividend event, 9999 has zero events (still succeeds).
    (ohlcv_dir / "finmind_2330.json").write_text(json.dumps({
        "payload": [
            {"date": "2026-04-20", "close": 100.0},
            {"date": "2026-05-01", "close": 95.0},
        ]
    }), encoding="utf-8")
    (ohlcv_dir / "finmind_9999.json").write_text(json.dumps({
        "payload": [{"date": "2026-04-20", "close": 50.0}]
    }), encoding="utf-8")

    def stub_fn(dataset, token=None, data_id=None, start_date=None, end_date=None, **kwargs):
        if data_id == "2330":
            return FinMindResult(success=True, payload=[
                {"date": "2026-05-01", "before_price": 100.0, "after_price": 95.0}
            ], http_status=200)
        return FinMindResult(success=True, payload=[], http_status=200)

    df = build_adjustment_factor_table_for_universe(
        ["2330", "9999"], str(ohlcv_dir), "2026-04-20", "2026-07-17",
        fetch_fn=stub_fn, polite_delay_sec=0, skip_existing=False,
    )
    assert set(df["stock_id"].unique()) == {"2330", "9999"}
    assert df.attrs["n_success"] == 2
    assert df.attrs["failures"] == []

    row_2330_before = df[(df.stock_id == "2330") & (df.trade_date == "2026-04-20")].iloc[0]
    assert abs(row_2330_before["adj_factor"] - 0.95) < 1e-9


def test_build_adjustment_factor_table_for_universe_records_failures(tmp_path):
    ohlcv_dir = tmp_path / "ohlcv"
    ohlcv_dir.mkdir()
    (ohlcv_dir / "finmind_1111.json").write_text(json.dumps({
        "payload": [{"date": "2026-04-20", "close": 10.0}]
    }), encoding="utf-8")

    def stub_fn(dataset, token=None, data_id=None, start_date=None, end_date=None, **kwargs):
        return FinMindResult(success=False, error="HTTP 500", http_status=500)

    df = build_adjustment_factor_table_for_universe(
        ["1111"], str(ohlcv_dir), "2026-04-20", "2026-07-17",
        fetch_fn=stub_fn, polite_delay_sec=0, skip_existing=False,
    )
    assert df.empty
    assert df.attrs["failures"] == ["1111"]
