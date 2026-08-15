"""
Event-study backtest engine for Milestone 5c (SPEC Ch.19/20, SPEC_ADDENDUM A-2/A-3/B-2/B-3).

This module is intentionally a pure-function / pure-class library: it takes already
-persisted, on-disk artifacts (signal event rows, per-day scored sector/stock frames,
per-stock OHLCV history, TAIEX index history) and computes forward-looking event-study
statistics. It does not fetch data and does not decide *whether* to run -- orchestration
(loading all 60 days, writing the Excel/CSV report) lives in scripts/run_backtest.py so
this module stays unit-testable without touching disk.

Core design decisions (see docs/backtest_methodology.md for the full narrative):

1. **Event definition (SPEC 19.6 / SPEC_ADDENDUM B-3.1)**: an "event" is the FIRST day a
   given (sector_name, sector_type) pair carries a graded signal (A/B/C for new-gainer,
   續漲訊號 for continued-momentum) after a day where it did NOT carry that same signal
   family at grade-or-better. Consecutive days of the same signal on the same sector are
   a single event's "persistence", counted separately (see `extract_events`) and never
   blended into the independent-event denominator, per SPEC_ADDENDUM B-3.1's explicit
   instruction ("兩者禁止混算").

2. **No future function (SPEC 19.1)**: entry is always T+1 OPEN (T = signal day close).
   Forward returns are computed strictly from OHLCV rows dated > the signal date. The
   caller is responsible for only ever passing this module data already on disk as of
   the signal date or later -- this module itself never reads a `trade_date` column and
   reasons "as of" anything; it just walks forward chronologically through whatever
   `df_ohlcv_history` it's given. `tests/leakage/test_backtester_no_future_function.py`
   verifies truncating the OHLCV file to date T does not change any T-dated event's
   already-realized returns.

3. **Taiwan-specific rules (SPEC_ADDENDUM B-2)**:
   - Limit-up lockout: if T+1 open >= prev_close * (1 + LIMIT_UP_THRESHOLD_PCT) (a
     tolerance-padded proxy for the real +10% daily limit -- no official "was this the
     locked limit price with zero sell-side liquidity" flag exists in the FinMind feed
     this milestone has, so the proxy is disclosed, not asserted as ground truth), the
     bar is treated as UNTRADABLE. Both "exclude" and "postpone to T+2" accounting are
     computed and reported per event (not just one), per the addendum's explicit
     instruction.
   - Ex-dividend / adjusted close: NOT implemented. No `adjusted_close` field exists
     anywhere in this project's OHLCV pipeline (FinMind's `TaiwanStockPrice` payload has
     no split/dividend-adjusted variant wired in `src/finmind_fetcher.py`/
     `src/data_loader.py`); this is a disclosed, real limitation (see the Milestone 5c
     Acceptance Report), not silently patched over with a fabricated adjustment.
   - Disposition/caution stocks: no processed disposition/caution list exists on disk
     this milestone (no fetcher wired). `disposition_stock_ids` is an optional input so
     a future milestone can wire it in without changing this module's contract; when
     omitted, no event is penalized (disclosed, not silently assumed clean).

4. **Trading cost**: config-driven (`fee_pct` charged twice -- buy + sell -- `tax_pct`
   once on the sell leg only, matching real Taiwan brokerage/exchange conventions; the
   pre-M5c stub double-counted `fee_pct` in a way that also implicitly doubled slippage
   with no configurable off switch. `compute_forward_returns` returns BOTH gross (no
   cost) and net (cost-adjusted) columns so the report can show "before and after cost"
   side by side, per the milestone brief's explicit requirement).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from loguru import logger

# Forward return horizons required by SPEC 19.4.
HORIZONS_DAYS: Tuple[int, ...] = (1, 3, 5, 10, 20)

# SPEC_ADDENDUM B-2.1: proxy for Taiwan's +10% daily price limit. FinMind's OHLCV feed
# carries no explicit "this bar was limit-locked with no sell-side liquidity" flag, so a
# price-based proxy is used, with a small tolerance band for float/rounding noise in the
# upstream feed (prices are stored to 1-2 decimal places, so a strict >= 1.10 boundary
# check can miss a true limit-up bar by a fraction of a cent).
LIMIT_UP_THRESHOLD_PCT = 0.095  # a bar whose T+1 open is >= prevClose * 1.095 is treated
                                  # as "likely limit-up" (real limit is +10%; the 0.5pp
                                  # tolerance absorbs rounding, matches the pre-M5c stub's
                                  # convention so results are comparable).
LOW_VOLUME_LOCK_THRESHOLD = 1000  # shares; a limit-up bar with <= this much volume is
                                    # treated as having had essentially no sell-side
                                    # liquidity (UNTRADABLE), not just a strong-up day.

# Grades that count as a "new gainer" family event for event-extraction purposes.
NEW_GAINER_GRADES = ("A級新起漲", "B級早期點火", "C級個股事件")
CONTINUED_MOMENTUM_GRADES = ("續漲訊號",)
NO_SIGNAL_LABELS = ("無訊號", "無效")

EVENT_STATUS_TRADABLE = "TRADABLE"
EVENT_STATUS_UNTRADABLE = "UNTRADABLE"
EVENT_STATUS_PENDING = "PENDING"  # forward horizon not yet mature as of the data endpoint


def extract_events(df_signals: pd.DataFrame,
                    signal_col: str = "signal_type",
                    date_col: str = "trade_date",
                    sector_col: str = "sector_name",
                    sector_type_col: str = "sector_type") -> pd.DataFrame:
    """
    SPEC 19.6 / SPEC_ADDENDUM B-3.1: splits a stacked multi-day signal frame (one row
    per sector per trade_date, as written by scripts/run_history_pipeline.py to
    outputs/signals/signals_<date>.jsonl) into:

      - independent EVENTS: the first day in a run of consecutive graded-signal days for
        a given (sector_name, sector_type). `is_event_start=True`.
      - PERSISTENCE rows: every subsequent consecutive day of the same signal family
        (new-gainer grades A/B/C are one family; 續漲訊號 is a second, separate family).
        `is_event_start=False`.

    A gap day (無訊號/無效, or the sector simply absent that day because it wasn't
    scored) resets the run -- the next graded day for that sector starts a brand new
    event, per SPEC 19.6 ("同一族群連續多天出現訊號時...持續狀態").

    Grade changes within the SAME family while consecutive (e.g. B on day1, A on day2)
    are treated as persistence of the same event (still a "new gainer" episode), not a
    fresh event -- only crossing a signal-day gap (or switching families) starts a new
    event. This matches "同一族群連續多日出現訊號=持續狀態" read at the family level,
    not the exact-grade level (SPEC's own new-gainer 10-condition checklist can flip a
    sector between A/B/C day-to-day purely from noise in one borderline condition; that
    is not a fresh ignition).

    Returns the input frame with two new columns: `event_family` (NEW_GAINER /
    CONTINUED_MOMENTUM / None) and `is_event_start` (bool). Rows with no signal
    (無訊號/無效) get `event_family=None`, `is_event_start=False` and are kept (needed
    as the "reset" markers for the run-length logic, and as the universe for the
    momentum/random benchmarks) rather than dropped.
    """
    if df_signals.empty:
        out = df_signals.copy()
        out["event_family"] = pd.Series(dtype=object)
        out["is_event_start"] = pd.Series(dtype=bool)
        return out

    df = df_signals.copy()
    df["_family"] = df[signal_col].apply(_signal_family)
    df = df.sort_values([sector_col, sector_type_col, date_col]).reset_index(drop=True)

    flags: List[bool] = []
    for _, group in df.groupby([sector_col, sector_type_col], sort=False):
        prev_family = None
        group_flags = []
        for fam in group["_family"]:
            # pandas may store a Python None inserted via .apply() as float NaN once the
            # column is touched by groupby/reindexing -- normalize both to None so the
            # "no signal" sentinel is never mistaken for a real (falsy-but-distinct)
            # family value.
            fam_norm = None if (fam is None or (isinstance(fam, float) and pd.isna(fam))) else fam
            group_flags.append(fam_norm is not None and fam_norm != prev_family)
            prev_family = fam_norm
        flags.extend(group_flags)
    df["is_event_start"] = flags
    df["event_family"] = df["_family"]
    df = df.drop(columns=["_family"])
    return df


def _signal_family(signal_type: Optional[str]) -> Optional[str]:
    if signal_type in NEW_GAINER_GRADES:
        return "NEW_GAINER"
    if signal_type in CONTINUED_MOMENTUM_GRADES:
        return "CONTINUED_MOMENTUM"
    return None


def resolve_sector_member_stock_ids(sector_name: str, sector_type: str,
                                     df_stock_scored: pd.DataFrame) -> List[str]:
    """
    Same membership rule src/sector_features.py already uses (see its module
    docstring): `primary` sectors match `stock.primary_sector == sector_name` (each
    stock belongs to exactly one primary sector -- no double counting); `theme` sectors
    match a stock having `sector_name` in ANY of theme_1/theme_2/theme_3 (a stock may
    belong to multiple themes -- may_double_count territory, which is why event
    statistics are always reported separately per sector_type, never pooled).
    """
    if df_stock_scored.empty:
        return []
    if sector_type == "theme":
        mask = (
            (df_stock_scored.get("theme_1") == sector_name)
            | (df_stock_scored.get("theme_2") == sector_name)
            | (df_stock_scored.get("theme_3") == sector_name)
        )
    else:
        mask = df_stock_scored.get("primary_sector") == sector_name
    return sorted(df_stock_scored.loc[mask, "stock_id"].astype(str).unique().tolist())


def index_ohlcv_by_stock(df_ohlcv_history: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """
    Pre-groups `df_ohlcv_history` into {stock_id: sorted-by-trade_date DataFrame} ONCE.
    Purely a performance helper for callers that will look up the same large OHLCV
    frame many thousands of times in one run (the real event study touches every
    signal's member stocks; the random bootstrap baseline touches a random member
    subset per draw, potentially 10,000 draws) -- grouping once up front turns each
    lookup from an O(n_total_rows) full-frame boolean-mask scan into an O(1) dict get.
    Every function in this module that takes `df_ohlcv_history` accepts EITHER a raw
    DataFrame (re-filtered internally every call -- simplest for tests/small inputs) OR
    the dict this function returns (fast path -- `scripts/run_backtest.py` and
    `src/benchmarks.py`'s bootstrap loop build this once up front and reuse it).

    Explicitly NOT implemented as an identity-keyed cache inside `_stock_close_series`
    itself: an earlier version of this module tried exactly that (memoizing by
    `id(df_ohlcv_history)`) and it was a real, caught bug in this session's own testing
    -- CPython reuses freed objects' memory addresses, so two DIFFERENT DataFrames built
    in unrelated calls (e.g. two separate unit tests' small per-test frames) can share
    the same `id()` once the first one is garbage-collected, silently returning a stale
    cached OTHER stock's history. An explicit, caller-owned index built once and passed
    down by the caller has no such hazard.
    """
    out: Dict[str, pd.DataFrame] = {}
    if df_ohlcv_history.empty:
        return out
    for stock_id, group in df_ohlcv_history.groupby(df_ohlcv_history["stock_id"].astype(str)):
        out[stock_id] = group.sort_values("trade_date").reset_index(drop=True)
    return out


def _stock_close_series(stock_id: str, df_ohlcv_history) -> pd.DataFrame:
    """Accepts either a raw OHLCV DataFrame (filtered fresh every call) or a pre-built
    `index_ohlcv_by_stock` dict (O(1) lookup) -- see that function's docstring."""
    if isinstance(df_ohlcv_history, dict):
        return df_ohlcv_history.get(str(stock_id), pd.DataFrame(columns=["stock_id", "trade_date",
                                                                            "open", "high", "low", "close", "volume"]))
    sub = df_ohlcv_history[df_ohlcv_history["stock_id"].astype(str) == str(stock_id)]
    return sub.sort_values("trade_date").reset_index(drop=True)


def compute_entry_price(stock_id: str, signal_date: str, df_ohlcv_history: pd.DataFrame,
                         limit_up_handling: str = "exclude") -> dict:
    """
    Resolves the T+1-open entry price for one stock given a T-dated signal, applying the
    SPEC_ADDENDUM B-2.1 limit-up lockout rule. Returns a dict:
      {status: TRADABLE|UNTRADABLE, entry_date, entry_price, entry_idx_offset}
    `entry_idx_offset` is 1 for a normal T+1 fill, 2 for a postponed T+2 fill (only when
    limit_up_handling="postpone" and T+1 was locked but T+2 was not).

    Never raises on missing history -- returns status=UNTRADABLE with entry_price=None
    (fail-closed; the caller must not silently treat a None entry price as a 0% return).
    """
    hist = _stock_close_series(stock_id, df_ohlcv_history)
    idx_list = hist.index[hist["trade_date"] == signal_date].tolist()
    if not idx_list or hist.empty:
        return {"status": EVENT_STATUS_UNTRADABLE, "entry_date": None, "entry_price": None,
                "entry_idx_offset": None, "reason": "NO_SIGNAL_DATE_IN_HISTORY"}
    sig_idx = idx_list[0]
    if sig_idx + 1 >= len(hist):
        return {"status": EVENT_STATUS_PENDING, "entry_date": None, "entry_price": None,
                "entry_idx_offset": None, "reason": "NO_T_PLUS_1_BAR_YET"}

    t1 = hist.iloc[sig_idx + 1]
    prev_close = hist.iloc[sig_idx]["close"]
    t1_locked = _is_limit_locked(t1["open"], prev_close, t1.get("volume"))

    if not t1_locked:
        return {"status": EVENT_STATUS_TRADABLE, "entry_date": t1["trade_date"],
                "entry_price": float(t1["open"]), "entry_idx_offset": 1, "reason": None}

    if limit_up_handling == "exclude":
        return {"status": EVENT_STATUS_UNTRADABLE, "entry_date": t1["trade_date"],
                "entry_price": None, "entry_idx_offset": None, "reason": "LIMIT_UP_LOCKED_T1"}

    # postpone to T+2
    if sig_idx + 2 >= len(hist):
        return {"status": EVENT_STATUS_PENDING, "entry_date": None, "entry_price": None,
                "entry_idx_offset": None, "reason": "NO_T_PLUS_2_BAR_YET"}
    t2 = hist.iloc[sig_idx + 2]
    t2_locked = _is_limit_locked(t2["open"], t1["close"], t2.get("volume"))
    if t2_locked:
        return {"status": EVENT_STATUS_UNTRADABLE, "entry_date": t2["trade_date"],
                "entry_price": None, "entry_idx_offset": None, "reason": "LIMIT_UP_LOCKED_T1_AND_T2"}
    return {"status": EVENT_STATUS_TRADABLE, "entry_date": t2["trade_date"],
            "entry_price": float(t2["open"]), "entry_idx_offset": 2, "reason": "POSTPONED_T2"}


def _is_limit_locked(open_price: float, prev_close: float, volume: Optional[float]) -> bool:
    if prev_close is None or prev_close <= 0 or open_price is None:
        return False
    is_limit_up_price = open_price >= prev_close * (1 + LIMIT_UP_THRESHOLD_PCT)
    if not is_limit_up_price:
        return False
    if volume is None or (isinstance(volume, float) and np.isnan(volume)):
        # No volume signal available -- cannot confirm zero sell-side liquidity, so do
        # NOT assume locked (fail-closed toward NOT flagging UNTRADABLE on missing data,
        # since falsely excluding a real tradable event would bias the sample).
        return False
    return volume <= LOW_VOLUME_LOCK_THRESHOLD


def compute_stock_forward_returns(stock_id: str, entry_date: str, entry_price: float,
                                   df_ohlcv_history: pd.DataFrame,
                                   horizons: Sequence[int] = HORIZONS_DAYS) -> Dict[int, Optional[float]]:
    """
    Cumulative simple returns (as decimals, e.g. 0.05 = +5%) from `entry_price` to the
    close K trading days after `entry_date` (K counted from entry_date itself: K=1 is
    entry_date's own close). Returns None (not 0.0) for a horizon whose bar does not yet
    exist in `df_ohlcv_history` (PENDING per SPEC's data-endpoint-maturity rule), never
    silently substitutes a shorter-horizon actual value.
    """
    hist = _stock_close_series(stock_id, df_ohlcv_history)
    idx_list = hist.index[hist["trade_date"] == entry_date].tolist()
    out: Dict[int, Optional[float]] = {k: None for k in horizons}
    if not idx_list:
        return out
    entry_idx = idx_list[0]
    for k in horizons:
        exit_idx = entry_idx + (k - 1)
        if exit_idx < len(hist):
            exit_price = hist.iloc[exit_idx]["close"]
            if pd.notna(exit_price) and entry_price:
                out[k] = float((exit_price - entry_price) / entry_price)
    return out


def compute_sector_forward_returns(stock_ids: Sequence[str], entry_date: str,
                                    entry_prices: Dict[str, float],
                                    df_ohlcv_history: pd.DataFrame,
                                    horizons: Sequence[int] = HORIZONS_DAYS,
                                    min_constituents: int = 1) -> Dict[int, Optional[float]]:
    """
    Sector-level forward return = cross-sectional MEDIAN of tradable member stocks'
    individual forward returns (SPEC 19.4 + docs/signal_definitions.md's R_sector,K
    definition; median chosen over turnover-weighted mean because a turnover-weighted
    number would let one giant-cap stock dominate the "sector" read, defeating the
    system's own breadth-based philosophy -- documented explicitly in
    docs/backtest_methodology.md rather than silently picking one without justification
    per the M5c brief's "擇一說明" instruction).
    Returns None for a horizon where fewer than `min_constituents` member stocks have a
    realized (non-None) return at that horizon (keeps the median from being computed off
    a single thin/unrepresentative stock when most of the sector's history is missing --
    a real, disclosed limitation given only 571/1963 stocks have FinMind OHLCV this
    milestone).
    """
    per_horizon: Dict[int, List[float]] = {k: [] for k in horizons}
    for sid in stock_ids:
        entry_price = entry_prices.get(sid)
        if entry_price is None:
            continue
        rets = compute_stock_forward_returns(sid, entry_date, entry_price, df_ohlcv_history, horizons)
        for k in horizons:
            if rets[k] is not None:
                per_horizon[k].append(rets[k])
    out: Dict[int, Optional[float]] = {}
    for k in horizons:
        vals = per_horizon[k]
        out[k] = float(np.median(vals)) if len(vals) >= min_constituents else None
    return out


def compute_market_forward_returns(entry_date: str, df_taiex: pd.DataFrame,
                                   horizons: Sequence[int] = HORIZONS_DAYS) -> Dict[int, Optional[float]]:
    """Compute market returns from the prior close through each exit close.

    The market leg starts at the previous trading day's close so that the 1-day
    return captures the entry day's actual index move.  The exit side deliberately
    remains ``entry_idx + (k - 1)``, matching the stock leg's horizon convention.
    TAIEX data has no open index, so this is still previous-close -> exit-close while
    the stock leg is T+1 open -> exit-close; the market leg therefore includes an
    overnight gap that cannot be removed with the available data.  That residual is
    common to events on the same day and is the best available cross-sectional
    alignment, but it can bias absolute ``excess_return > 0`` thresholds.

    The frame is deduplicated by trade date after sorting; keeping the last row
    prevents a duplicate date from making the prior-close lookup fall back to the
    entry date itself.  Missing or non-positive prior closes fail closed to None.
    """
    df = (df_taiex.sort_values("trade_date", kind="stable")
          .drop_duplicates("trade_date", keep="last")
          .reset_index(drop=True))
    idx_list = df.index[df["trade_date"] == entry_date].tolist()
    out: Dict[int, Optional[float]] = {k: None for k in horizons}
    if not idx_list:
        return out
    entry_idx = idx_list[0]
    if entry_idx == 0:
        return out
    entry_price = df.iloc[entry_idx - 1]["close"]
    if pd.isna(entry_price) or entry_price <= 0:
        return out
    for k in horizons:
        exit_idx = entry_idx + (k - 1)
        if exit_idx < len(df):
            exit_price = df.iloc[exit_idx]["close"]
            if pd.notna(exit_price):
                out[k] = float((exit_price - entry_price) / entry_price)
    return out


def apply_trading_cost(gross_return: Optional[float], fee_pct: float, tax_pct: float,
                        slippage_pct: float = 0.0) -> Optional[float]:
    """
    Net return = gross - (fee charged on buy leg + fee charged on sell leg + tax charged
    on sell leg only + slippage, all as simple percentage-point deductions from the
    return). Taiwan brokerage/exchange convention: 手續費(fee) on BOTH legs,
    證交稅(tax) on the SELL leg ONLY -- this differs from the pre-M5c stub, which charged
    `fee_pct * 2 + tax_pct` without documenting the tax-is-sell-only convention; the
    formula is unchanged numerically (fee*2 + tax is still fee*2 + tax regardless of
    which leg each piece is conceptually attached to) but is now named/tested explicitly
    so the convention is verifiable, not just implied.
    """
    if gross_return is None:
        return None
    total_cost = (fee_pct * 2) + tax_pct + slippage_pct
    return gross_return - total_cost


class Backtester:
    """
    Orchestrates one full event-study pass: event extraction -> per-event forward
    returns (sector + market) -> cost-adjusted net returns -> label attachment.
    Kept side-effect-free (no disk I/O) so it's directly unit-testable;
    scripts/run_backtest.py is the disk-touching caller.
    """

    def __init__(self, fee_pct: float = 0.001425, tax_pct: float = 0.003,
                 slippage_pct: float = 0.001, limit_up_handling: str = "exclude"):
        self.fee_pct = fee_pct
        self.tax_pct = tax_pct
        self.slippage_pct = slippage_pct
        self.limit_up_handling = limit_up_handling

    def run_event_study(self,
                         df_signals_all_days: pd.DataFrame,
                         df_stock_scored_by_date: Dict[str, pd.DataFrame],
                         df_ohlcv_history: pd.DataFrame,
                         df_taiex: pd.DataFrame,
                         horizons: Sequence[int] = HORIZONS_DAYS,
                         disposition_stock_ids: Optional[set] = None) -> pd.DataFrame:
        """
        `df_stock_scored_by_date`: {trade_date: stock_scored dataframe for that date}
        (sector membership, i.e. primary_sector/theme_1-3, is read fresh per-date since
        the industry mapping can in principle change over the 60-day window -- using the
        signal date's own membership snapshot, never a later date's, keeps this
        no-future-leakage).

        Returns one row per EVENT (is_event_start=True rows only) with gross/net
        1/3/5/10/20-day sector and market returns, excess return, UNTRADABLE/PENDING
        status for both exclude and postpone accounting, and (for new-gainer's 10-day /
        continued-momentum's 5-day horizon) the SPEC_ADDENDUM A-2 label.
        """
        disposition_stock_ids = disposition_stock_ids or set()
        ohlcv_idx = index_ohlcv_by_stock(df_ohlcv_history) if isinstance(df_ohlcv_history, pd.DataFrame) else df_ohlcv_history
        events_df = extract_events(df_signals_all_days)
        events_df = events_df[events_df["is_event_start"]].copy()

        rows = []
        for _, ev in events_df.iterrows():
            sector_name = ev["sector_name"]
            sector_type = ev.get("sector_type", "primary")
            signal_date = ev["trade_date"]
            df_stock_scored = df_stock_scored_by_date.get(signal_date, pd.DataFrame())
            member_ids = resolve_sector_member_stock_ids(sector_name, sector_type, df_stock_scored)

            has_disposition = bool(set(member_ids) & disposition_stock_ids)
            weight_penalty = 0.5 if has_disposition else 1.0

            row_base = {
                "trade_date": signal_date,
                "sector_name": sector_name,
                "sector_type": sector_type,
                "signal_type": ev.get("signal_type"),
                "event_family": ev.get("event_family"),
                "member_stock_count": len(member_ids),
                "has_disposition_member": has_disposition,
                "weight_penalty": weight_penalty,
            }

            for handling in ("exclude", "postpone"):
                entry_infos = {sid: compute_entry_price(sid, signal_date, ohlcv_idx, handling)
                                for sid in member_ids}
                tradable_ids = [sid for sid, info in entry_infos.items() if info["status"] == EVENT_STATUS_TRADABLE]
                pending_ids = [sid for sid, info in entry_infos.items() if info["status"] == EVENT_STATUS_PENDING]

                suffix = "" if handling == "exclude" else "_postpone"
                if not member_ids:
                    row_base[f"status{suffix}"] = "NO_MEMBERS"
                elif tradable_ids:
                    entry_dates = [entry_infos[sid]["entry_date"] for sid in tradable_ids]
                    # sector-level entry_date = the modal (most common) entry date among
                    # tradable members; almost always unanimous (all T+1) except under
                    # "postpone" with a mix of locked/unlocked members.
                    entry_date_for_market = max(set(entry_dates), key=entry_dates.count)
                    entry_prices = {sid: entry_infos[sid]["entry_price"] for sid in tradable_ids}
                    sector_rets = compute_sector_forward_returns(
                        tradable_ids, entry_date_for_market, entry_prices, ohlcv_idx, horizons
                    )
                    market_rets = compute_market_forward_returns(entry_date_for_market, df_taiex, horizons)

                    any_pending_horizon = False
                    for k in horizons:
                        gross = sector_rets[k]
                        mkt = market_rets[k]
                        net = apply_trading_cost(gross, self.fee_pct, self.tax_pct, self.slippage_pct) \
                            if gross is not None else None
                        excess_gross = (gross - mkt) if (gross is not None and mkt is not None) else None
                        excess_net = (net - mkt) if (net is not None and mkt is not None) else None
                        row_base[f"gross_return_{k}d{suffix}"] = gross
                        row_base[f"net_return_{k}d{suffix}"] = net
                        row_base[f"market_return_{k}d{suffix}"] = mkt
                        row_base[f"excess_return_gross_{k}d{suffix}"] = excess_gross
                        row_base[f"excess_return_net_{k}d{suffix}"] = excess_net
                        if gross is None:
                            any_pending_horizon = True
                    row_base[f"status{suffix}"] = (
                        EVENT_STATUS_PENDING if any_pending_horizon and not sector_rets.get(horizons[0])
                        else EVENT_STATUS_TRADABLE
                    )
                    row_base[f"entry_date{suffix}"] = entry_date_for_market
                    row_base[f"tradable_member_count{suffix}"] = len(tradable_ids)
                elif pending_ids and not tradable_ids:
                    row_base[f"status{suffix}"] = EVENT_STATUS_PENDING
                    for k in horizons:
                        row_base[f"gross_return_{k}d{suffix}"] = None
                        row_base[f"net_return_{k}d{suffix}"] = None
                        row_base[f"market_return_{k}d{suffix}"] = None
                        row_base[f"excess_return_gross_{k}d{suffix}"] = None
                        row_base[f"excess_return_net_{k}d{suffix}"] = None
                else:
                    row_base[f"status{suffix}"] = EVENT_STATUS_UNTRADABLE
                    for k in horizons:
                        row_base[f"gross_return_{k}d{suffix}"] = None
                        row_base[f"net_return_{k}d{suffix}"] = None
                        row_base[f"market_return_{k}d{suffix}"] = None
                        row_base[f"excess_return_gross_{k}d{suffix}"] = None
                        row_base[f"excess_return_net_{k}d{suffix}"] = None

            rows.append(row_base)

        result = pd.DataFrame(rows)
        if result.empty:
            return result

        # Attach SPEC_ADDENDUM A-2 outcome labels using the "exclude" accounting's net
        # excess return (the conservative, directly-tradable-capital view) at each
        # family's defined horizon.
        from src.labels import label_new_gainer_outcome, label_continued_momentum_outcome

        def _label_row(r):
            if r["event_family"] == "NEW_GAINER":
                return label_new_gainer_outcome(
                    r.get("excess_return_net_10d") * 100.0 if r.get("excess_return_net_10d") is not None else None
                )
            if r["event_family"] == "CONTINUED_MOMENTUM":
                return label_continued_momentum_outcome(
                    r.get("excess_return_net_5d") * 100.0 if r.get("excess_return_net_5d") is not None else None
                )
            return None

        result["outcome_label"] = result.apply(_label_row, axis=1)
        return result

    # ------------------------------------------------------------------
    # Legacy per-stock-signal simulate_trades kept for backward compatibility with any
    # caller expecting the pre-M5c per-row stock-level trade simulation contract (this
    # milestone's real signals are sector-level rows, not stock-level, so the new
    # run_event_study path above is what scripts/run_backtest.py actually uses -- this
    # method is retained, not deleted, since removing a previously-public method without
    # a stated reason would violate the "don't touch already-accepted behavior" rule,
    # and no test/caller in this codebase depended on it being removed).
    # ------------------------------------------------------------------
    def simulate_trades(self,
                         df_signals: pd.DataFrame,
                         df_ohlcv_history: pd.DataFrame,
                         disposition_tickers: Optional[List[str]] = None,
                         limit_up_handling: str = "exclude") -> Tuple[pd.DataFrame, dict]:
        disposition_tickers = disposition_tickers or []
        results = []
        summary = {"total_trades": 0, "successful_trades": 0, "win_rate": 0.0, "avg_return": 0.0}

        if df_signals.empty or df_ohlcv_history.empty:
            return pd.DataFrame(), summary

        for _, row in df_signals.iterrows():
            if row.get("signal_type", "無訊號") in NO_SIGNAL_LABELS:
                continue
            ticker = row.get("stock_id")
            sig_date = row.get("trade_date")
            if not ticker or not sig_date:
                continue

            info = compute_entry_price(ticker, sig_date, df_ohlcv_history, limit_up_handling)
            if info["status"] != EVENT_STATUS_TRADABLE:
                continue

            entry_price = info["entry_price"]
            size_penalty = 0.5 if ticker in disposition_tickers else 1.0
            rets = compute_stock_forward_returns(ticker, info["entry_date"], entry_price,
                                                  df_ohlcv_history, horizons=(1, 3, 5, 10))
            trade_returns = {}
            for k in (1, 3, 5, 10):
                gross = rets[k]
                trade_returns[f"return_{k}d"] = (
                    apply_trading_cost(gross, self.fee_pct, self.tax_pct, self.slippage_pct)
                    if gross is not None else np.nan
                )

            results.append({
                "trade_date": sig_date,
                "stock_id": ticker,
                "sector_name": row.get("sector_name", ""),
                "signal_type": row["signal_type"],
                "entry_price": entry_price,
                "size_penalty": size_penalty,
                **trade_returns,
            })

        df_results = pd.DataFrame(results)
        if not df_results.empty:
            summary["total_trades"] = len(df_results)
            valid_5d = df_results["return_5d"].dropna()
            if len(valid_5d) > 0:
                summary["successful_trades"] = int((valid_5d > 0).sum())
                summary["win_rate"] = float(summary["successful_trades"] / len(valid_5d))
                summary["avg_return"] = float(valid_5d.mean())

        return df_results, summary
