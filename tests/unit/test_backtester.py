import sys
import os

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.backtester import (
    extract_events,
    resolve_sector_member_stock_ids,
    compute_entry_price,
    compute_stock_forward_returns,
    compute_sector_forward_returns,
    compute_market_forward_returns,
    apply_trading_cost,
    Backtester,
    EVENT_STATUS_TRADABLE,
    EVENT_STATUS_UNTRADABLE,
    EVENT_STATUS_PENDING,
)


# ---------------------------------------------------------------------------
# extract_events (SPEC 19.6 / SPEC_ADDENDUM B-3.1)
# ---------------------------------------------------------------------------

def _signal_row(date, sector, signal_type, sector_type="primary"):
    return {"trade_date": date, "sector_name": sector, "sector_type": sector_type,
            "signal_type": signal_type}


def test_first_signal_day_is_event_start():
    df = pd.DataFrame([
        _signal_row("2026-01-01", "半導體", "無訊號"),
        _signal_row("2026-01-02", "半導體", "B級早期點火"),
        _signal_row("2026-01-03", "半導體", "B級早期點火"),
    ])
    out = extract_events(df)
    starts = out.set_index("trade_date")["is_event_start"]
    assert starts["2026-01-01"] == False
    assert starts["2026-01-02"] == True
    assert starts["2026-01-03"] == False  # persistence, not a new event


def test_gap_day_resets_event():
    df = pd.DataFrame([
        _signal_row("2026-01-01", "半導體", "B級早期點火"),
        _signal_row("2026-01-02", "半導體", "無訊號"),
        _signal_row("2026-01-03", "半導體", "B級早期點火"),
    ])
    out = extract_events(df).set_index("trade_date")
    assert out.loc["2026-01-01", "is_event_start"] == True
    assert out.loc["2026-01-03", "is_event_start"] == True  # new event after the gap


def test_grade_change_within_family_is_persistence_not_new_event():
    df = pd.DataFrame([
        _signal_row("2026-01-01", "半導體", "B級早期點火"),
        _signal_row("2026-01-02", "半導體", "A級新起漲"),  # still NEW_GAINER family
    ])
    out = extract_events(df).set_index("trade_date")
    assert out.loc["2026-01-01", "is_event_start"] == True
    assert out.loc["2026-01-02", "is_event_start"] == False


def test_family_switch_starts_new_event():
    df = pd.DataFrame([
        _signal_row("2026-01-01", "半導體", "B級早期點火"),      # NEW_GAINER
        _signal_row("2026-01-02", "半導體", "續漲訊號"),          # CONTINUED_MOMENTUM
    ])
    out = extract_events(df).set_index("trade_date")
    assert out.loc["2026-01-01", "is_event_start"] == True
    assert out.loc["2026-01-02", "is_event_start"] == True


def test_different_sectors_independent():
    df = pd.DataFrame([
        _signal_row("2026-01-01", "半導體", "B級早期點火"),
        _signal_row("2026-01-01", "航運", "B級早期點火"),
    ])
    out = extract_events(df)
    assert out["is_event_start"].all()


def test_same_sector_name_different_sector_type_independent():
    # A theme sector and a primary sector sharing a name must not interfere with
    # each other's run-length tracking (may_double_count territory).
    df = pd.DataFrame([
        _signal_row("2026-01-01", "AI", "B級早期點火", sector_type="theme"),
        _signal_row("2026-01-01", "AI", "無訊號", sector_type="primary"),
        _signal_row("2026-01-02", "AI", "B級早期點火", sector_type="primary"),
    ])
    out = extract_events(df)
    theme_row = out[(out["sector_type"] == "theme") & (out["trade_date"] == "2026-01-01")]
    primary_row = out[(out["sector_type"] == "primary") & (out["trade_date"] == "2026-01-02")]
    assert theme_row["is_event_start"].iloc[0] == True
    assert primary_row["is_event_start"].iloc[0] == True


def test_empty_signals_returns_empty_with_columns():
    out = extract_events(pd.DataFrame())
    assert out.empty
    assert "is_event_start" in out.columns
    assert "event_family" in out.columns


# ---------------------------------------------------------------------------
# resolve_sector_member_stock_ids
# ---------------------------------------------------------------------------

def test_primary_sector_membership_exact_match():
    df_stock = pd.DataFrame([
        {"stock_id": "1101", "primary_sector": "水泥工業", "theme_1": None, "theme_2": None, "theme_3": None},
        {"stock_id": "2330", "primary_sector": "半導體", "theme_1": None, "theme_2": None, "theme_3": None},
    ])
    ids = resolve_sector_member_stock_ids("半導體", "primary", df_stock)
    assert ids == ["2330"]


def test_theme_sector_membership_any_of_three_columns():
    df_stock = pd.DataFrame([
        {"stock_id": "2330", "primary_sector": "半導體", "theme_1": "AI", "theme_2": None, "theme_3": None},
        {"stock_id": "3661", "primary_sector": "半導體", "theme_1": None, "theme_2": "AI", "theme_3": None},
        {"stock_id": "1101", "primary_sector": "水泥工業", "theme_1": None, "theme_2": None, "theme_3": "AI"},
        {"stock_id": "9999", "primary_sector": "水泥工業", "theme_1": None, "theme_2": None, "theme_3": None},
    ])
    ids = resolve_sector_member_stock_ids("AI", "theme", df_stock)
    assert set(ids) == {"2330", "3661", "1101"}


def test_empty_stock_scored_returns_empty_list():
    assert resolve_sector_member_stock_ids("半導體", "primary", pd.DataFrame()) == []


# ---------------------------------------------------------------------------
# compute_entry_price / limit-up lockout (SPEC_ADDENDUM B-2.1, P0-06)
# ---------------------------------------------------------------------------

def _ohlcv_rows(stock_id, rows):
    """rows: list of (trade_date, open, high, low, close, volume)"""
    return pd.DataFrame([
        {"stock_id": stock_id, "trade_date": d, "open": o, "high": h, "low": l, "close": c, "volume": v}
        for d, o, h, l, c, v in rows
    ])


def test_normal_entry_not_limit_locked():
    hist = _ohlcv_rows("2330", [
        ("2026-01-01", 100, 102, 99, 100, 5_000_000),
        ("2026-01-02", 101, 103, 100, 102, 5_000_000),
    ])
    info = compute_entry_price("2330", "2026-01-01", hist, "exclude")
    assert info["status"] == EVENT_STATUS_TRADABLE
    assert info["entry_price"] == 101
    assert info["entry_date"] == "2026-01-02"


def test_limit_up_locked_excluded():
    hist = _ohlcv_rows("2330", [
        ("2026-01-01", 100, 100, 100, 100, 5_000_000),
        ("2026-01-02", 110, 110, 110, 110, 500),  # +10% open, thin volume -> locked
    ])
    info = compute_entry_price("2330", "2026-01-01", hist, "exclude")
    assert info["status"] == EVENT_STATUS_UNTRADABLE
    assert info["reason"] == "LIMIT_UP_LOCKED_T1"
    assert info["entry_price"] is None


def test_limit_up_locked_postponed_to_t2_when_t2_unlocked():
    hist = _ohlcv_rows("2330", [
        ("2026-01-01", 100, 100, 100, 100, 5_000_000),
        ("2026-01-02", 110, 110, 110, 110, 500),   # T+1 locked
        ("2026-01-03", 108, 111, 107, 109, 5_000_000),  # T+2 open, not locked vs T+1 close
    ])
    info = compute_entry_price("2330", "2026-01-01", hist, "postpone")
    assert info["status"] == EVENT_STATUS_TRADABLE
    assert info["entry_date"] == "2026-01-03"
    assert info["entry_price"] == 108
    assert info["entry_idx_offset"] == 2


def test_limit_up_locked_both_days_postpone_still_untradable():
    hist = _ohlcv_rows("2330", [
        ("2026-01-01", 100, 100, 100, 100, 5_000_000),
        ("2026-01-02", 110, 110, 110, 110, 500),
        ("2026-01-03", 121, 121, 121, 121, 500),  # T+2 also locked vs T+1 close (110*1.1=121)
    ])
    info = compute_entry_price("2330", "2026-01-01", hist, "postpone")
    assert info["status"] == EVENT_STATUS_UNTRADABLE
    assert info["reason"] == "LIMIT_UP_LOCKED_T1_AND_T2"


def test_limit_up_price_but_high_volume_is_not_locked():
    # Price moved +10% but volume was heavy -- real liquidity existed, should NOT be
    # treated as a locked/untradable bar.
    hist = _ohlcv_rows("2330", [
        ("2026-01-01", 100, 100, 100, 100, 5_000_000),
        ("2026-01-02", 110, 112, 109, 111, 20_000_000),
    ])
    info = compute_entry_price("2330", "2026-01-01", hist, "exclude")
    assert info["status"] == EVENT_STATUS_TRADABLE


def test_missing_volume_does_not_assume_locked():
    hist = _ohlcv_rows("2330", [
        ("2026-01-01", 100, 100, 100, 100, 5_000_000),
        ("2026-01-02", 110, 110, 110, 110, np.nan),
    ])
    info = compute_entry_price("2330", "2026-01-01", hist, "exclude")
    assert info["status"] == EVENT_STATUS_TRADABLE  # fail-closed toward NOT excluding


def test_no_t_plus_1_bar_is_pending_not_untradable():
    hist = _ohlcv_rows("2330", [("2026-01-01", 100, 100, 100, 100, 5_000_000)])
    info = compute_entry_price("2330", "2026-01-01", hist, "exclude")
    assert info["status"] == EVENT_STATUS_PENDING


def test_signal_date_missing_from_history_is_untradable_not_crash():
    hist = _ohlcv_rows("2330", [("2026-01-01", 100, 100, 100, 100, 5_000_000)])
    info = compute_entry_price("2330", "2099-01-01", hist, "exclude")
    assert info["status"] == EVENT_STATUS_UNTRADABLE


# ---------------------------------------------------------------------------
# compute_stock_forward_returns / compute_sector_forward_returns
# ---------------------------------------------------------------------------

def test_forward_returns_basic_1_3_5d():
    hist = _ohlcv_rows("2330", [
        ("2026-01-02", 100, 100, 100, 100, 1_000_000),  # entry date, close=100 is day K=1
        ("2026-01-03", 100, 100, 100, 105, 1_000_000),  # K=2
        ("2026-01-04", 100, 100, 100, 110, 1_000_000),  # K=3
    ])
    rets = compute_stock_forward_returns("2330", "2026-01-02", 100.0, hist, horizons=(1, 3))
    assert rets[1] == pytest.approx(0.0)
    assert rets[3] == pytest.approx(0.10)


def test_forward_returns_missing_horizon_is_none_not_zero():
    hist = _ohlcv_rows("2330", [("2026-01-02", 100, 100, 100, 100, 1_000_000)])
    rets = compute_stock_forward_returns("2330", "2026-01-02", 100.0, hist, horizons=(1, 20))
    assert rets[1] == pytest.approx(0.0)
    assert rets[20] is None


def test_sector_forward_return_is_median_of_members():
    hist = pd.concat([
        _ohlcv_rows("A", [("2026-01-02", 100, 100, 100, 100, 1e6), ("2026-01-03", 100, 100, 100, 110, 1e6)]),
        _ohlcv_rows("B", [("2026-01-02", 100, 100, 100, 100, 1e6), ("2026-01-03", 100, 100, 100, 120, 1e6)]),
        _ohlcv_rows("C", [("2026-01-02", 100, 100, 100, 100, 1e6), ("2026-01-03", 100, 100, 100, 90, 1e6)]),
    ], ignore_index=True)
    entry_prices = {"A": 100.0, "B": 100.0, "C": 100.0}
    rets = compute_sector_forward_returns(["A", "B", "C"], "2026-01-02", entry_prices, hist, horizons=(2,))
    # returns: A=+10%, B=+20%, C=-10% -> median = +10%
    assert rets[2] == pytest.approx(0.10)


def test_sector_forward_return_below_min_constituents_is_none():
    hist = _ohlcv_rows("A", [("2026-01-02", 100, 100, 100, 100, 1e6), ("2026-01-03", 100, 100, 100, 110, 1e6)])
    rets = compute_sector_forward_returns(["A"], "2026-01-02", {"A": 100.0}, hist, horizons=(2,),
                                           min_constituents=2)
    assert rets[2] is None


# ---------------------------------------------------------------------------
# compute_market_forward_returns
# ---------------------------------------------------------------------------

def test_market_forward_returns():
    taiex = pd.DataFrame([
        {"trade_date": "2026-01-01", "close": 20000},
        {"trade_date": "2026-01-02", "close": 20200},
        {"trade_date": "2026-01-03", "close": 19800},
        {"trade_date": "2026-01-04", "close": 20400},
    ])
    rets = compute_market_forward_returns("2026-01-02", taiex, horizons=(1, 2, 3))
    assert rets[1] == pytest.approx(0.01)
    assert rets[2] == pytest.approx(-0.01)
    assert rets[3] == pytest.approx(0.02)


def test_market_forward_returns_first_trade_date_is_none():
    taiex = pd.DataFrame([
        {"trade_date": "2026-01-02", "close": 20000},
        {"trade_date": "2026-01-03", "close": 20200},
    ])
    rets = compute_market_forward_returns("2026-01-02", taiex, horizons=(1, 2))
    assert rets == {1: None, 2: None}


def test_market_forward_returns_deduplicates_trade_date_keep_last():
    taiex = pd.DataFrame([
        {"trade_date": "2026-01-01", "close": 19000},
        {"trade_date": "2026-01-01", "close": 20000},
        {"trade_date": "2026-01-02", "close": 20200},
        {"trade_date": "2026-01-03", "close": 20600},
    ])
    rets = compute_market_forward_returns("2026-01-02", taiex, horizons=(1, 2))
    assert rets[1] == pytest.approx(0.01)
    assert rets[2] == pytest.approx(0.03)


def test_market_forward_returns_invalid_prior_close_is_none():
    for prior_close in (np.nan, 0.0, -1.0):
        taiex = pd.DataFrame([
            {"trade_date": "2026-01-01", "close": prior_close},
            {"trade_date": "2026-01-02", "close": 20200},
            {"trade_date": "2026-01-03", "close": 20400},
        ])
        rets = compute_market_forward_returns("2026-01-02", taiex, horizons=(1, 2))
        assert rets == {1: None, 2: None}


def test_market_forward_returns_missing_entry_date_is_none():
    taiex = pd.DataFrame([
        {"trade_date": "2026-01-01", "close": 20000},
        {"trade_date": "2026-01-02", "close": 20200},
    ])
    rets = compute_market_forward_returns("2026-01-09", taiex, horizons=(1, 2))
    assert rets == {1: None, 2: None}


# ---------------------------------------------------------------------------
# apply_trading_cost
# ---------------------------------------------------------------------------

def test_apply_trading_cost_subtracts_fee_twice_tax_once():
    net = apply_trading_cost(0.05, fee_pct=0.001425, tax_pct=0.003, slippage_pct=0.001)
    expected = 0.05 - (0.001425 * 2 + 0.003 + 0.001)
    assert net == pytest.approx(expected)


def test_apply_trading_cost_none_passthrough():
    assert apply_trading_cost(None, 0.001425, 0.003) is None


# ---------------------------------------------------------------------------
# Backtester.run_event_study integration-style unit test (small synthetic universe)
# ---------------------------------------------------------------------------

def test_run_event_study_end_to_end_small_universe():
    df_signals = pd.DataFrame([
        _signal_row("2026-01-01", "半導體", "無訊號"),
        _signal_row("2026-01-02", "半導體", "B級早期點火"),
        _signal_row("2026-01-03", "半導體", "B級早期點火"),  # persistence, not counted as 2nd event
    ])
    stock_scored = pd.DataFrame([
        {"stock_id": "A", "primary_sector": "半導體", "theme_1": None, "theme_2": None, "theme_3": None},
        {"stock_id": "B", "primary_sector": "半導體", "theme_1": None, "theme_2": None, "theme_3": None},
    ])
    df_stock_scored_by_date = {"2026-01-01": stock_scored, "2026-01-02": stock_scored, "2026-01-03": stock_scored}

    ohlcv = pd.concat([
        _ohlcv_rows("A", [
            ("2026-01-02", 100, 100, 100, 100, 1e6),
            ("2026-01-03", 100, 100, 100, 100, 1e6),  # T+1 entry bar (open=100)
            ("2026-01-04", 100, 100, 100, 105, 1e6),
            ("2026-01-05", 100, 100, 100, 110, 1e6),
        ]),
        _ohlcv_rows("B", [
            ("2026-01-02", 100, 100, 100, 100, 1e6),
            ("2026-01-03", 100, 100, 100, 100, 1e6),
            ("2026-01-04", 100, 100, 100, 103, 1e6),
            ("2026-01-05", 100, 100, 100, 108, 1e6),
        ]),
    ], ignore_index=True)
    taiex = pd.DataFrame([
        {"trade_date": "2026-01-02", "close": 20000},
        {"trade_date": "2026-01-03", "close": 20000},
        {"trade_date": "2026-01-04", "close": 20100},
        {"trade_date": "2026-01-05", "close": 20200},
    ])

    bt = Backtester(fee_pct=0.001425, tax_pct=0.003, slippage_pct=0.0)
    result = bt.run_event_study(df_signals, df_stock_scored_by_date, ohlcv, taiex, horizons=(1, 3))

    assert len(result) == 1  # only one independent event (day 2 is the start; day 3 is persistence)
    row = result.iloc[0]
    assert row["trade_date"] == "2026-01-02"
    assert row["entry_date"] == "2026-01-03"
    assert row["status"] == EVENT_STATUS_TRADABLE
    assert row["gross_return_1d"] == pytest.approx(0.0)
    # median of (A:+10%, B:+8%) at day 3 (K=3 from entry 01-03: 01-03,01-04,01-05) = +9%
    assert row["gross_return_3d"] == pytest.approx(0.09)
    assert row["net_return_3d"] == pytest.approx(0.09 - (0.001425 * 2 + 0.003))


def test_run_event_study_untradable_event_all_returns_none():
    df_signals = pd.DataFrame([_signal_row("2026-01-01", "航運", "B級早期點火")])
    stock_scored = pd.DataFrame([
        {"stock_id": "X", "primary_sector": "航運", "theme_1": None, "theme_2": None, "theme_3": None},
    ])
    df_stock_scored_by_date = {"2026-01-01": stock_scored}
    ohlcv = _ohlcv_rows("X", [
        ("2026-01-01", 100, 100, 100, 100, 1e6),
        ("2026-01-02", 110, 110, 110, 110, 500),  # locked
    ])
    taiex = pd.DataFrame([{"trade_date": "2026-01-01", "close": 20000},
                           {"trade_date": "2026-01-02", "close": 20100}])
    bt = Backtester()
    result = bt.run_event_study(df_signals, df_stock_scored_by_date, ohlcv, taiex, horizons=(1,))
    row = result.iloc[0]
    assert row["status"] == EVENT_STATUS_UNTRADABLE
    assert row["gross_return_1d"] is None
    # No realized excess return -> label module correctly reports INSUFFICIENT_DATA
    # (SPEC_ADDENDUM A-2), never a fabricated SUCCESS/FAILURE guess.
    assert row["outcome_label"] == "INSUFFICIENT_DATA"


# ---------------------------------------------------------------------------
# Disposition/caution stock weight penalty wiring (SPEC_ADDENDUM B-2.2)
# ---------------------------------------------------------------------------

def test_disposition_member_flagged_and_penalized():
    df_signals = pd.DataFrame([_signal_row("2026-01-01", "半導體", "B級早期點火")])
    stock_scored = pd.DataFrame([
        {"stock_id": "A", "primary_sector": "半導體", "theme_1": None, "theme_2": None, "theme_3": None},
        {"stock_id": "B", "primary_sector": "半導體", "theme_1": None, "theme_2": None, "theme_3": None},
    ])
    df_stock_scored_by_date = {"2026-01-01": stock_scored}
    ohlcv = pd.concat([
        _ohlcv_rows("A", [("2026-01-01", 100, 100, 100, 100, 1e6), ("2026-01-02", 100, 100, 100, 105, 1e6)]),
        _ohlcv_rows("B", [("2026-01-01", 100, 100, 100, 100, 1e6), ("2026-01-02", 100, 100, 100, 105, 1e6)]),
    ], ignore_index=True)
    taiex = pd.DataFrame([{"trade_date": "2026-01-01", "close": 20000}, {"trade_date": "2026-01-02", "close": 20000}])

    bt = Backtester()
    result = bt.run_event_study(df_signals, df_stock_scored_by_date, ohlcv, taiex, horizons=(1,),
                                 disposition_stock_ids={"A"})
    row = result.iloc[0]
    assert row["has_disposition_member"] == True
    assert row["weight_penalty"] == pytest.approx(0.5)


def test_no_disposition_list_means_no_penalty_never_assumed():
    df_signals = pd.DataFrame([_signal_row("2026-01-01", "半導體", "B級早期點火")])
    stock_scored = pd.DataFrame([
        {"stock_id": "A", "primary_sector": "半導體", "theme_1": None, "theme_2": None, "theme_3": None},
    ])
    df_stock_scored_by_date = {"2026-01-01": stock_scored}
    ohlcv = _ohlcv_rows("A", [("2026-01-01", 100, 100, 100, 100, 1e6), ("2026-01-02", 100, 100, 100, 105, 1e6)])
    taiex = pd.DataFrame([{"trade_date": "2026-01-01", "close": 20000}, {"trade_date": "2026-01-02", "close": 20000}])
    bt = Backtester()
    result = bt.run_event_study(df_signals, df_stock_scored_by_date, ohlcv, taiex, horizons=(1,))
    row = result.iloc[0]
    assert row["has_disposition_member"] == False
    assert row["weight_penalty"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Cost model config wiring (SPEC 19.5 / config/default.yaml backtest.*)
# ---------------------------------------------------------------------------

def test_backtester_cost_config_is_wired_not_hardcoded():
    hist = _ohlcv_rows("A", [
        ("2026-01-01", 100, 100, 100, 100, 1e6),
        ("2026-01-02", 100, 100, 100, 100, 1e6),
        ("2026-01-03", 100, 100, 100, 110, 1e6),
    ])
    bt_cheap = Backtester(fee_pct=0.0001, tax_pct=0.0001, slippage_pct=0.0)
    bt_expensive = Backtester(fee_pct=0.01, tax_pct=0.01, slippage_pct=0.01)
    df_signals = pd.DataFrame([_signal_row("2026-01-01", "半導體", "B級早期點火")])
    stock_scored = pd.DataFrame([
        {"stock_id": "A", "primary_sector": "半導體", "theme_1": None, "theme_2": None, "theme_3": None},
    ])
    df_stock_scored_by_date = {"2026-01-01": stock_scored}
    taiex = pd.DataFrame([{"trade_date": "2026-01-01", "close": 20000},
                           {"trade_date": "2026-01-02", "close": 20000},
                           {"trade_date": "2026-01-03", "close": 20000}])
    r_cheap = bt_cheap.run_event_study(df_signals, df_stock_scored_by_date, hist, taiex, horizons=(2,))
    r_expensive = bt_expensive.run_event_study(df_signals, df_stock_scored_by_date, hist, taiex, horizons=(2,))
    assert r_cheap.iloc[0]["net_return_2d"] > r_expensive.iloc[0]["net_return_2d"]
    # gross return must be identical regardless of cost config (cost only affects net)
    assert r_cheap.iloc[0]["gross_return_2d"] == pytest.approx(r_expensive.iloc[0]["gross_return_2d"])
