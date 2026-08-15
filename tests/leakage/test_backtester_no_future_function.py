"""
M5c no-future-function regression test (SPEC 19.1, §26.6 spirit: "把資料截斷到 T 日重算
事件與 T 日前特徵，與全量結果比對一致").

Strategy: build a synthetic multi-day universe (signals + stock_scored + OHLCV + TAIEX),
run the full event study against (a) the complete dataset and (b) a version whose OHLCV
history is truncated to end exactly at the last day needed to realize the FIRST event's
10-day horizon. Every return/label already computed as of the truncation point must be
byte-identical between the two runs -- if truncating data that lies strictly AFTER an
event's already-realized horizon changes that event's own computed returns, the engine
is reaching into the future to compute a "past" result, which is exactly the P0-03/19.1
violation this test exists to catch.

A second check directly exercises compute_entry_price/compute_stock_forward_returns:
appending additional REAL trading days after an event's horizon has already fully
matured must never change that event's own recorded returns (only whether *later*
events, which need dates that don't exist yet, are PENDING vs TRADABLE).
"""

import sys
import os

import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.backtester import Backtester, compute_stock_forward_returns, EVENT_STATUS_PENDING


def _ohlcv_rows(stock_id, rows):
    return pd.DataFrame([
        {"stock_id": stock_id, "trade_date": d, "open": o, "high": h, "low": l, "close": c, "volume": v}
        for d, o, h, l, c, v in rows
    ])


def _build_universe(n_days: int):
    """Builds n_days of a single-sector, single-stock synthetic universe starting
    2026-01-01 (weekday-agnostic; this is a pure calendar-index synthetic test, not a
    real trading-calendar one)."""
    dates = [f"2026-01-{d:02d}" for d in range(1, n_days + 1)]
    signal_rows = []
    for i, d in enumerate(dates):
        signal_rows.append({
            "trade_date": d, "sector_name": "半導體", "sector_type": "primary",
            "signal_type": "B級早期點火" if i == 0 else "無訊號",
        })
    df_signals = pd.DataFrame(signal_rows)

    stock_scored = pd.DataFrame([
        {"stock_id": "A", "primary_sector": "半導體", "theme_1": None, "theme_2": None, "theme_3": None},
    ])
    df_stock_scored_by_date = {d: stock_scored for d in dates}

    # Deterministic upward-drifting close series so returns are non-trivial and easy to
    # hand-verify (close_t = 100 + t).
    ohlcv_rows = [(d, 100 + i, 100 + i + 1, 100 + i - 1, 100 + i, 1_000_000) for i, d in enumerate(dates)]
    ohlcv = _ohlcv_rows("A", ohlcv_rows)
    taiex = pd.DataFrame([{"trade_date": d, "close": 20000 + i * 5} for i, d in enumerate(dates)])
    return df_signals, df_stock_scored_by_date, ohlcv, taiex, dates


def test_truncated_dataset_matches_full_dataset_for_already_realized_event():
    # Need the signal day (index 0) + T+1 entry + 20 more trading days for the 20d
    # horizon to fully realize -> at least 22 days total.
    df_signals, df_stock_scored_by_date, ohlcv_full, taiex_full, dates = _build_universe(30)

    bt = Backtester(fee_pct=0.001425, tax_pct=0.003, slippage_pct=0.0)
    result_full = bt.run_event_study(df_signals, df_stock_scored_by_date, ohlcv_full, taiex_full,
                                      horizons=(1, 3, 5, 10, 20))

    # Truncate to exactly the 22 days needed for the first event's 20d horizon to
    # mature (signal day + T+1 entry + 20 more bars = index 0..21).
    truncate_at = 22
    truncated_dates = set(dates[:truncate_at])
    ohlcv_trunc = ohlcv_full[ohlcv_full["trade_date"].isin(truncated_dates)].copy()
    taiex_trunc = taiex_full[taiex_full["trade_date"].isin(truncated_dates)].copy()
    df_signals_trunc = df_signals[df_signals["trade_date"].isin(truncated_dates)].copy()
    stock_scored_by_date_trunc = {d: v for d, v in df_stock_scored_by_date.items() if d in truncated_dates}

    result_trunc = bt.run_event_study(df_signals_trunc, stock_scored_by_date_trunc, ohlcv_trunc, taiex_trunc,
                                       horizons=(1, 3, 5, 10, 20))

    assert len(result_full) == 1
    assert len(result_trunc) == 1
    row_full = result_full.iloc[0]
    row_trunc = result_trunc.iloc[0]

    for k in (1, 3, 5, 10, 20):
        col_gross = f"gross_return_{k}d"
        col_net = f"net_return_{k}d"
        col_excess = f"excess_return_gross_{k}d"
        assert row_full[col_gross] == pytest.approx(row_trunc[col_gross]), f"mismatch at {col_gross}"
        assert row_full[col_net] == pytest.approx(row_trunc[col_net]), f"mismatch at {col_net}"
        assert row_full[col_excess] == pytest.approx(row_trunc[col_excess]), f"mismatch at {col_excess}"
    assert row_full["outcome_label"] == row_trunc["outcome_label"]


def test_appending_future_days_does_not_change_already_realized_return():
    """Direct unit-level check: compute a stock's forward returns against a short
    history, then again against the SAME history plus extra future bars appended --
    the already-realized horizons must be byte-identical."""
    short_hist = _ohlcv_rows("A", [
        ("2026-01-01", 100, 100, 100, 100, 1e6),
        ("2026-01-02", 100, 100, 100, 105, 1e6),
        ("2026-01-03", 100, 100, 100, 110, 1e6),
    ])
    extended_hist = pd.concat([short_hist, _ohlcv_rows("A", [
        ("2026-01-04", 100, 100, 100, 999, 1e6),  # a wild future value
        ("2026-01-05", 100, 100, 100, 1, 1e6),
    ])], ignore_index=True)

    rets_short = compute_stock_forward_returns("A", "2026-01-01", 100.0, short_hist, horizons=(1, 2, 3))
    rets_extended = compute_stock_forward_returns("A", "2026-01-01", 100.0, extended_hist, horizons=(1, 2, 3))

    assert rets_short[1] == rets_extended[1]
    assert rets_short[2] == rets_extended[2]
    assert rets_short[3] == rets_extended[3]


def test_event_not_yet_matured_is_pending_never_guessed():
    """An event whose forward horizon data simply doesn't exist yet (the real 60-day
    dataset's tail dates) must be reported PENDING, never silently computed from data
    that doesn't exist / never defaults to a fabricated 0% return."""
    df_signals, df_stock_scored_by_date, ohlcv_full, taiex_full, dates = _build_universe(30)
    # Signal on the SECOND-TO-LAST day -- its T+1 exists but its 20d horizon does not.
    df_signals_late = df_signals.copy()
    df_signals_late["signal_type"] = "無訊號"
    df_signals_late.loc[df_signals_late["trade_date"] == dates[-2], "signal_type"] = "B級早期點火"

    bt = Backtester()
    result = bt.run_event_study(df_signals_late, df_stock_scored_by_date, ohlcv_full, taiex_full,
                                 horizons=(1, 20))
    row = result.iloc[0]
    assert row["gross_return_1d"] is not None
    assert row["gross_return_20d"] is None
    assert row["status"] == EVENT_STATUS_PENDING
