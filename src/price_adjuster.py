"""
Milestone 7 (Pitfall Pack): ex-dividend price adjustment (SPEC_ADDENDUM B-2.3, disclosed
as NOT implemented by M5c/backtester.py's module docstring -- this closes that gap).

Background: M5c's backtester computes forward returns straight off FinMind's raw daily
OHLCV `close`. On a real ex-dividend day, `close` drops by (roughly) the dividend amount
even though no value was lost -- an investor who held through the ex-div date received
the dividend in cash. Not adjusting for this means every event whose forward-return
window straddles an ex-dividend date is understated (2026-04-20..2026-07-17, this
project's whole backtest window, is peak Taiwan cash-dividend season -- see the M7
report for the empirical before/after headline comparison).

Direct adjusted-price dataset check (M7 dry-run, live probe against the real FinMind API,
never recalled from memory -- see
loop/evidence/fetch_receipts/finmind_adjusted_price_probe_2026-07-18.json): NONE of
TaiwanStockPriceAdj / TaiwanStockPriceAdjusted / TaiwanStockAdjPrice /
TaiwanStockPriceAdjustment / TaiwanStockPriceAdjustmentFactor / TaiwanStockAdjustment
exist on this token (all HTTP 400/422). CONFIRMED WORKING instead:
`TaiwanStockDividendResult` -- a per-stock list of real ex-dividend EVENTS, each row
carrying `date` (the ex-dividend trading date), `before_price` (reference close the prior
trading day) and `after_price` (the exchange's official ex-rights/ex-dividend reference
price, i.e. before_price minus the cash+stock dividend value). This module uses that
event list to compute a classic backward (multiplicative) adjustment factor series --
the same convention `tests/unit/test_dividend_adjustment.py`'s pre-existing scaffold test
demonstrates arithmetically (adjust the PRE-event price down, not the post-event price
up, so the most recent price always equals its own raw close).

Adjustment factor definition, per ex-dividend event on trade_date D:
    factor_D = after_price / before_price   (<=1.0 for a cash/stock dividend; can be
                                              exactly 1.0 for a data quirk with no real
                                              price effect, never fabricated otherwise)
For any bar dated STRICTLY BEFORE D, the cumulative adjustment multiplier is the product
of factor_D for every ex-dividend event on or after that bar's date (i.e. all raw prices
before an ex-div event are scaled down by that event's factor; bars on/after D are
untouched by that event). With multiple ex-div events in a stock's history, factors
compound multiplicatively (earliest-affected bars carry the product of every later
event's factor).

Fail-closed contract: a stock with zero dividend events in FinMind's response is not an
error -- it genuinely never paid a dividend in the queried range, so its adjustment
factor is 1.0 for its entire history (no data missing, nothing to adjust). A stock whose
dividend-event fetch itself fails (network/rate-limit) gets NO factor entry at all
(distinguished from "confirmed zero dividends") so callers can tell "verified clean" from
"unknown" and the backtester can tag the latter UNADJUSTED rather than silently treating
missing-fetch the same as confirmed-no-dividend.
"""

from __future__ import annotations

import os
import json
import time
from typing import Dict, List, Optional

import pandas as pd
from loguru import logger

from src.finmind_fetcher import finmind_get, get_finmind_token, build_envelope, FinMindResult

DIVIDEND_DATASET = "TaiwanStockDividendResult"


def fetch_dividend_events(stock_id: str, start_date: str, end_date: str,
                           token: Optional[str] = None,
                           fetch_fn=None) -> Optional[List[dict]]:
    """
    Fetches one stock's ex-dividend event list from FinMind (TaiwanStockDividendResult)
    for [start_date, end_date]. Returns a list (possibly empty -- a genuinely
    dividend-free stock in this window) on success, or None on a real fetch failure
    (fail-closed; caller must not treat None as "no dividends").
    """
    fetch_fn = fetch_fn or finmind_get
    result: FinMindResult = fetch_fn(DIVIDEND_DATASET, token=token, data_id=stock_id,
                                      start_date=start_date, end_date=end_date)
    if not result.success:
        logger.error(f"fetch_dividend_events FAILED for {stock_id}: {result.error}")
        return None
    return result.payload


def compute_adjustment_factor_table(stock_id: str, dividend_events: List[dict],
                                     trade_dates: List[str]) -> pd.DataFrame:
    """
    Given `dividend_events` (raw TaiwanStockDividendResult rows for one stock) and the
    sorted list of `trade_dates` present in that stock's OHLCV history, returns a
    DataFrame with columns [stock_id, trade_date, adj_factor] where adj_factor is the
    cumulative backward-adjustment multiplier to apply to that bar's raw
    open/high/low/close (multiply raw price * adj_factor -> adjusted price).

    Bars on/after the LATEST ex-dividend event's date always carry adj_factor=1.0 (the
    convention anchors adjustment to today's actual price, matching
    `test_dividend_adjustment.py`'s scaffold). Bars before an event are scaled down by
    that event's (and every later event's) factor, compounding multiplicatively for
    stocks with more than one ex-dividend date in range.

    A dividend event whose before_price is zero/missing/non-numeric is skipped (factor
    contribution of that single event treated as neutral 1.0) rather than raising or
    producing inf/NaN contamination of the whole series -- logged, not silently dropped.
    """
    dates_sorted = sorted(trade_dates)
    if not dates_sorted:
        return pd.DataFrame(columns=["stock_id", "trade_date", "adj_factor"])

    # Build sorted list of (event_date, event_factor).
    events: List[tuple] = []
    for ev in dividend_events or []:
        ev_date = ev.get("date")
        before = ev.get("before_price")
        after = ev.get("after_price")
        if not ev_date or before in (None, 0) or after is None:
            logger.warning(f"compute_adjustment_factor_table: skipping malformed dividend "
                            f"event for {stock_id}: {ev}")
            continue
        try:
            before_f = float(before)
            after_f = float(after)
        except (TypeError, ValueError):
            logger.warning(f"compute_adjustment_factor_table: non-numeric before/after "
                            f"for {stock_id} event {ev}")
            continue
        if before_f <= 0:
            continue
        factor = after_f / before_f
        events.append((ev_date, factor))
    events.sort(key=lambda x: x[0])

    # Cumulative multiplier for a bar dated `d`: product of factor for every event whose
    # date > d... actually events apply to bars strictly BEFORE the event's ex-div date
    # (the event's own date already reflects the post-adjustment reference price).
    rows = []
    for d in dates_sorted:
        mult = 1.0
        for ev_date, factor in events:
            if d < ev_date:
                mult *= factor
        rows.append({"stock_id": stock_id, "trade_date": d, "adj_factor": mult})
    return pd.DataFrame(rows)


def build_adjustment_factor_table_for_universe(
        stock_ids: List[str],
        ohlcv_dir: str,
        start_date: str,
        end_date: str,
        token: Optional[str] = None,
        fetch_fn=None,
        polite_delay_sec: float = 1.0,
        skip_existing: bool = True,
        dividend_events_dir: Optional[str] = None,
) -> pd.DataFrame:
    """
    Orchestrates the whole-universe adjustment factor build: for each stock_id, fetches
    (or reuses an on-disk cached) dividend-event list, then computes its factor series
    against that stock's own on-disk OHLCV trade_date list (read from
    `<ohlcv_dir>/finmind_<stock_id>.json`, the same file M5b/M5c's OHLCV loader uses).

    Returns a single stacked DataFrame [stock_id, trade_date, adj_factor] covering every
    stock that had a successful dividend-event fetch (fresh or cached). Stocks whose
    fetch failed are simply absent from the result (never given a fabricated factor of
    1.0) -- the caller (this module's CLI / scripts/fetch_price_adjustments.py) is
    responsible for reporting the failed/absent set honestly, and downstream consumers
    (the backtester) must tag any stock absent from this table as UNADJUSTED.
    """
    dividend_events_dir = dividend_events_dir or os.path.join(
        os.path.dirname(ohlcv_dir.rstrip("/\\")), "fundamentals", "dividends"
    )
    os.makedirs(dividend_events_dir, exist_ok=True)
    token = token if token is not None else get_finmind_token()

    all_rows = []
    failures = []
    n_success = 0
    n_reused = 0

    for stock_id in stock_ids:
        cache_path = os.path.join(dividend_events_dir, f"finmind_div_{stock_id}.json")
        events = None
        if skip_existing and os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                if cached.get("metadata", {}).get("start_date") == start_date and \
                   cached.get("metadata", {}).get("end_date") == end_date:
                    events = cached.get("payload", [])
                    n_reused += 1
            except Exception as e:
                logger.warning(f"build_adjustment_factor_table_for_universe: cache unreadable "
                                f"for {stock_id}: {e}")

        if events is None:
            events = fetch_dividend_events(stock_id, start_date, end_date, token=token, fetch_fn=fetch_fn)
            if events is None:
                failures.append(stock_id)
                continue
            envelope = build_envelope(DIVIDEND_DATASET, stock_id, events, start_date, end_date)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(envelope, f, ensure_ascii=False, indent=2)
            n_success += 1
            if polite_delay_sec:
                time.sleep(polite_delay_sec)

        ohlcv_path = os.path.join(ohlcv_dir, f"finmind_{stock_id}.json")
        if not os.path.exists(ohlcv_path):
            logger.warning(f"build_adjustment_factor_table_for_universe: no OHLCV file for "
                            f"{stock_id} at {ohlcv_path}, cannot build factor table (no trade_dates).")
            continue
        with open(ohlcv_path, "r", encoding="utf-8") as f:
            ohlcv_env = json.load(f)
        trade_dates = [r["date"] for r in ohlcv_env.get("payload", []) if r.get("date")]

        factor_df = compute_adjustment_factor_table(stock_id, events, trade_dates)
        if not factor_df.empty:
            all_rows.append(factor_df)

    logger.info(f"build_adjustment_factor_table_for_universe: {n_success} freshly fetched, "
                f"{n_reused} reused from cache, {len(failures)} failed (see failures list).")

    result = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame(
        columns=["stock_id", "trade_date", "adj_factor"])
    result.attrs["failures"] = failures
    result.attrs["n_success"] = n_success
    result.attrs["n_reused"] = n_reused
    return result


def apply_adjustment(df_ohlcv: pd.DataFrame, df_factors: pd.DataFrame) -> pd.DataFrame:
    """
    Left-joins `df_factors` (stock_id, trade_date, adj_factor) onto `df_ohlcv`
    (must have stock_id, trade_date, open/high/low/close) and multiplies
    open/high/low/close by adj_factor to produce adjusted prices in new columns
    (adj_open/adj_high/adj_low/adj_close). Rows with no matching factor entry (stock not
    in df_factors at all, e.g. its dividend fetch failed) get adj_factor=NaN and a new
    boolean column `price_unadjusted=True` -- the caller (backtester) must read
    adjusted prices only when `price_unadjusted` is False, and fall back to the raw
    column (tagged UNADJUSTED) otherwise. Never silently assumes adj_factor=1.0 for a
    stock this function has no evidence about.
    """
    if df_ohlcv.empty:
        out = df_ohlcv.copy()
        for c in ("adj_open", "adj_high", "adj_low", "adj_close"):
            out[c] = pd.Series(dtype=float)
        out["price_unadjusted"] = pd.Series(dtype=bool)
        return out

    merged = df_ohlcv.merge(
        df_factors[["stock_id", "trade_date", "adj_factor"]] if not df_factors.empty
        else pd.DataFrame(columns=["stock_id", "trade_date", "adj_factor"]),
        on=["stock_id", "trade_date"], how="left",
    )
    merged["price_unadjusted"] = merged["adj_factor"].isna()
    for raw_col, adj_col in (("open", "adj_open"), ("high", "adj_high"),
                              ("low", "adj_low"), ("close", "adj_close")):
        if raw_col in merged.columns:
            merged[adj_col] = merged.apply(
                lambda r: r[raw_col] if pd.isna(r["adj_factor"]) or pd.isna(r[raw_col])
                else r[raw_col] * r["adj_factor"], axis=1
            )
        else:
            merged[adj_col] = pd.Series(dtype=float)
    return merged
