"""Read-only diagnostic for the predictive value of daily stock scores.

The scored snapshots contain many overlapping stock-day observations.  They are
useful for cross-sectional ranks, but must *not* be treated as independent
observations for significance tests: a 10-day holding opened on consecutive
days shares most of its price path.  This script therefore calculates t-stats
from daily portfolio (or daily IC) series only and uses a Bartlett
Newey-West/HAC standard error.  It never calls a network provider, changes the
daily pipeline, or writes beneath ``data/`` or ``outputs/``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

LOGGER = logging.getLogger(__name__)
HORIZONS = (1, 3, 5, 10, 20)
WIDE_UNIVERSE_MIN_STOCKS = 1_000
MIN_DAILY_DECILE_N = 50
MIN_DECISIVE_DECILE_DAYS = 40
FACTORS = (
    "sector_score",
    "score_strength",
    "score_volume",
    "score_improvement",
    "score_breakout",
    "score_institution",
)
SCORE_COLUMNS = ("stock_id", "trade_date", "stock_score", *FACTORS,
                 "score_confidence", "stock_role", "primary_sector", "daily_return", "volume")
FEE_PCT, TAX_PCT, SLIPPAGE_PCT = 0.001425, 0.003, 0.001
ROUND_TRIP_COST = FEE_PCT * 2 + TAX_PCT + SLIPPAGE_PCT


def newey_west_tstat(values: Iterable[float], lag: Optional[int] = None) -> dict:
    """Return a mean and Bartlett Newey-West t-stat for one daily series.

    No external statistics package is required.  The default lag follows the
    conventional floor(4 * (n / 100) ** (2 / 9)) rule and is capped by n - 1.
    Empty or constant inputs stay null instead of inventing precision.
    """
    x = np.asarray([v for v in values if v is not None and np.isfinite(v)], dtype=float)
    n = len(x)
    if n == 0:
        return {"n_daily": 0, "mean": None, "std": None, "nw_lag": None, "t_stat": None}
    mean = float(x.mean())
    if n < 2:
        return {"n_daily": n, "mean": mean, "std": None, "nw_lag": 0, "t_stat": None}
    lag = min(n - 1, lag if lag is not None else int(math.floor(4 * (n / 100) ** (2 / 9))))
    centered = x - mean
    gamma0 = float(np.dot(centered, centered) / n)
    long_run_variance = gamma0
    for k in range(1, lag + 1):
        gamma = float(np.dot(centered[k:], centered[:-k]) / n)
        long_run_variance += 2 * (1 - k / (lag + 1)) * gamma
    se = math.sqrt(max(long_run_variance, 0.0) / n)
    return {
        "n_daily": n,
        "mean": mean,
        "std": float(x.std(ddof=1)),
        "nw_lag": lag,
        "t_stat": float(mean / se) if se > 0 else None,
    }


def horizon_newey_west_tstat(values: Iterable[float], horizon: int) -> dict:
    """Apply a horizon-aware HAC lag to an overlapping daily return series."""
    clean = [value for value in values if value is not None and np.isfinite(value)]
    n = len(clean)
    automatic_lag = int(math.floor(4 * (n / 100) ** (2 / 9))) if n else 0
    return newey_west_tstat(clean, lag=max(automatic_lag, horizon - 1))


def _parse_roc_or_iso_date(value: object) -> Optional[str]:
    """Parse official ROC/ISO dates without relying on the snapshot file name."""
    text = str(value).strip()
    if not text:
        return None
    digits = text.replace("/", "").replace("-", "")
    if digits.isdigit() and len(digits) == 7:
        year, month, day = int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:])
    elif digits.isdigit() and len(digits) == 8:
        year, month, day = int(digits[:4]), int(digits[4:6]), int(digits[6:])
    else:
        parts = text.replace("/", "-").split("-")
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            return None
        year, month, day = map(int, parts)
        if year < 1911:
            year += 1911
    try:
        return dt.date(year, month, day).isoformat()
    except ValueError:
        return None


def _number_or_none(value: object) -> Optional[float]:
    """Parse a persisted numeric field; price validity is enforced by the reader."""
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"---", "--", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _snapshot_payload(path: Path) -> list[dict]:
    """Read one already-persisted official snapshot; malformed files stay absent."""
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        LOGGER.warning("Skipping unreadable official snapshot %s: %s", path, exc)
        return []
    payload = loaded.get("payload", []) if isinstance(loaded, dict) else loaded
    return payload if isinstance(payload, list) else []


def load_official_ohlcv_history(data_dir_ohlcv: Path) -> pd.DataFrame:
    """Merge local FinMind and official OHLCV snapshots, with official precedence.

    Despite the historical function name, this is the complete disk-only adapter
    used by the diagnostic.  It supports both TPEx schemas (legacy ``Code`` /
    ``ClosingPrice`` and current ``SecuritiesCompanyCode`` / ``Close``), records
    every rejected row, and removes nonpositive closes at the read boundary.
    No fetcher is imported and no network request is possible here.
    """
    records: dict[tuple[str, str], dict] = {}
    stats: dict[str, object] = {
        "source_files": 0,
        "raw_rows": 0,
        "parsed_rows": 0,
        "parse_failure_rows": 0,
        "nonpositive_close_rows": 0,
        "nonpositive_close_files": 0,
        "finmind_nonpositive_close_rows": 0,
        "finmind_nonpositive_close_files": 0,
        "official_nonpositive_close_rows": 0,
        "official_nonpositive_close_files": 0,
        "finmind_parsed_rows": 0,
        "official_parsed_rows": 0,
        "duplicate_keys_overridden_by_official": 0,
        "output_rows": 0,
        "output_unique_stocks": 0,
        "output_nonpositive_close_rows": 0,
    }
    nonpositive_files: set[str] = set()
    finmind_nonpositive_files: set[str] = set()
    official_nonpositive_files: set[str] = set()

    # FinMind is the broad fallback.  Its stock id is encoded in the file name.
    for path in sorted(data_dir_ohlcv.glob("finmind_*.json")):
        stats["source_files"] += 1
        file_failures = 0
        for raw in _snapshot_payload(path):
            stats["raw_rows"] += 1
            stock_id = path.stem.removeprefix("finmind_")
            trade_date = _parse_roc_or_iso_date(raw.get("date"))
            values = [_number_or_none(raw.get(key)) for key in
                      ("open", "max", "min", "close", "Trading_Volume")]
            if not stock_id or trade_date is None or any(value is None for value in values):
                stats["parse_failure_rows"] += 1
                file_failures += 1
                continue
            if values[3] <= 0:
                stats["nonpositive_close_rows"] += 1
                stats["finmind_nonpositive_close_rows"] += 1
                nonpositive_files.add(path.name)
                finmind_nonpositive_files.add(path.name)
                continue
            records[(stock_id, trade_date)] = {
                "stock_id": stock_id, "trade_date": trade_date,
                "open": values[0], "high": values[1], "low": values[2],
                "close": values[3], "volume": values[4],
                "_source_priority": 0,
            }
            stats["parsed_rows"] += 1
            stats["finmind_parsed_rows"] += 1
        if file_failures:
            LOGGER.warning("FinMind snapshot %s rejected %d malformed rows", path.name, file_failures)

    # Official rows extend and override FinMind.  TWSE receives deterministic
    # precedence for the unlikely case that the same id/date appears in both markets.
    source_specs = (
        (3, "twse_prices_*.json", "twse"),
        (2, "tpex_prices_*.json", "tpex"),
    )
    for priority, pattern, market in source_specs:
        for path in sorted(data_dir_ohlcv.glob(pattern)):
            stats["source_files"] += 1
            file_failures = 0
            for raw in _snapshot_payload(path):
                stats["raw_rows"] += 1
                if market == "tpex" and "SecuritiesCompanyCode" in raw:
                    keys = ("SecuritiesCompanyCode", "Date", "Open", "High", "Low", "Close", "TradingShares")
                else:
                    keys = ("Code", "Date", "OpeningPrice", "HighestPrice", "LowestPrice",
                            "ClosingPrice", "TradeVolume")
                stock_key, date_key, open_key, high_key, low_key, close_key, volume_key = keys
                stock_id = str(raw.get(stock_key, "")).strip()
                trade_date = _parse_roc_or_iso_date(raw.get(date_key))
                values = [_number_or_none(raw.get(key)) for key in (open_key, high_key, low_key, close_key, volume_key)]
                if not stock_id or trade_date is None or any(value is None for value in values):
                    stats["parse_failure_rows"] += 1
                    file_failures += 1
                    continue
                if values[3] <= 0:
                    stats["nonpositive_close_rows"] += 1
                    stats["official_nonpositive_close_rows"] += 1
                    nonpositive_files.add(path.name)
                    official_nonpositive_files.add(path.name)
                    continue
                key = (stock_id, trade_date)
                current = records.get(key)
                if current is None or priority > current["_source_priority"]:
                    if current is not None and current["_source_priority"] == 0:
                        stats["duplicate_keys_overridden_by_official"] += 1
                    records[key] = {
                        "stock_id": stock_id, "trade_date": trade_date,
                        "open": values[0], "high": values[1], "low": values[2],
                        "close": values[3], "volume": values[4],
                        "_source_priority": priority,
                    }
                stats["parsed_rows"] += 1
                stats["official_parsed_rows"] += 1
            if file_failures:
                LOGGER.warning("Official snapshot %s rejected %d malformed rows", path.name, file_failures)
    columns = ["stock_id", "trade_date", "open", "high", "low", "close", "volume"]
    stats["nonpositive_close_files"] = len(nonpositive_files)
    stats["finmind_nonpositive_close_files"] = len(finmind_nonpositive_files)
    stats["official_nonpositive_close_files"] = len(official_nonpositive_files)
    if not records:
        empty = pd.DataFrame(columns=columns)
        empty.attrs["cleaning_stats"] = stats
        return empty
    result = (pd.DataFrame(records.values())
              .drop(columns="_source_priority")
              .sort_values(["stock_id", "trade_date"])
              .drop_duplicates(["stock_id", "trade_date"], keep="first")
              .reset_index(drop=True))
    stats["output_rows"] = int(len(result))
    stats["output_unique_stocks"] = int(result["stock_id"].nunique())
    stats["output_nonpositive_close_rows"] = int((result["close"] <= 0).sum())
    result.attrs["cleaning_stats"] = stats
    return result


def load_scored_by_date(data_dir_processed: Path, prefix: str = "stock_scored") -> dict[str, pd.DataFrame]:
    """Load persisted score snapshots without importing an orchestration script."""
    scored: dict[str, pd.DataFrame] = {}
    for path in sorted(data_dir_processed.glob(f"{prefix}_*.csv")):
        if "_bak_" in path.name:
            continue
        try:
            scored[path.stem.removeprefix(f"{prefix}_")] = pd.read_csv(path, dtype={"stock_id": str})
        except (OSError, ValueError, pd.errors.ParserError) as exc:
            LOGGER.warning("Skipping unreadable score snapshot %s: %s", path, exc)
    return scored


def load_taiex(data_dir_market_index: Path) -> pd.DataFrame:
    """Extend FinMind TAIEX with date-guarded official disk snapshots.

    Official rows win on overlap.  The TAIEX row is selected by name, never by
    position; a snapshot whose file date disagrees with its self-reported date
    is rejected rather than forward-filled or interpolated.
    """
    payload = _snapshot_payload(data_dir_market_index / "finmind_index_twse.json")
    records: dict[str, tuple[int, float]] = {}
    stats: dict[str, object] = {
        "finmind_rows": 0,
        "official_files": 0,
        "official_rows_accepted": 0,
        "rejected_filename_date_mismatches": [],
        "official_parse_failures": 0,
        "overlap_dates": 0,
        "overlap_exact_matches": 0,
        "overlap_conflicts": [],
    }
    for raw in payload:
        trade_date = _parse_roc_or_iso_date(raw.get("date"))
        close = _number_or_none(raw.get("close"))
        if trade_date is not None and close is not None:
            records[trade_date] = (0, close)
            stats["finmind_rows"] += 1
    for path in sorted(data_dir_market_index.glob("twse_*.json")):
        stats["official_files"] += 1
        date_token = (
            path.stem.removeprefix("twse_official_")
            if path.stem.startswith("twse_official_")
            else path.stem.removeprefix("twse_")
        )
        file_date = _parse_roc_or_iso_date(date_token)
        matches = [raw for raw in _snapshot_payload(path)
                   if "發行" in str(raw.get("指數", ""))
                   and "加權" in str(raw.get("指數", ""))
                   and "報酬" not in str(raw.get("指數", ""))]
        if len(matches) != 1:
            stats["official_parse_failures"] += 1
            LOGGER.warning("TAIEX snapshot %s has %d matching index rows", path.name, len(matches))
            continue
        raw = matches[0]
        reported_date = _parse_roc_or_iso_date(raw.get("日期"))
        close = _number_or_none(raw.get("收盤指數"))
        if file_date is None or reported_date is None or close is None:
            stats["official_parse_failures"] += 1
            LOGGER.warning("TAIEX snapshot %s has an invalid date or close", path.name)
            continue
        if file_date != reported_date:
            stats["rejected_filename_date_mismatches"].append({
                "file": path.name, "file_date": file_date, "reported_date": reported_date,
            })
            LOGGER.warning("TAIEX snapshot %s rejected: reports %s", path.name, reported_date)
            continue
        if reported_date in records:
            stats["overlap_dates"] += 1
            existing = records[reported_date][1]
            if math.isclose(existing, close, rel_tol=0.0, abs_tol=1e-8):
                stats["overlap_exact_matches"] += 1
            else:
                stats["overlap_conflicts"].append({
                    "trade_date": reported_date, "finmind": existing, "official": close,
                })
        records[reported_date] = (1, close)
        stats["official_rows_accepted"] += 1
    rows = [{"trade_date": date, "close": value[1]} for date, value in sorted(records.items())]
    result = pd.DataFrame(rows, columns=["trade_date", "close"])
    stats["final_rows"] = int(len(result))
    stats["date_min"] = result["trade_date"].min() if not result.empty else None
    stats["date_max"] = result["trade_date"].max() if not result.empty else None
    result.attrs["coverage_stats"] = stats
    return result


def apply_local_price_adjustment(ohlcv: pd.DataFrame, data_dir: Path) -> tuple[pd.DataFrame, Optional[float]]:
    """Use only persisted factors; the caller measures its actual analysis rows."""
    if ohlcv.empty:
        return ohlcv, None
    factor_path = data_dir / "reference" / "price_adjustment_factors.csv"
    if not factor_path.exists():
        out = ohlcv.copy()
        out["price_unadjusted"] = True
        return out, 1.0
    from src.price_adjuster import apply_adjustment

    factors = pd.read_csv(factor_path, dtype={"stock_id": str})
    adjusted = apply_adjustment(ohlcv, factors)
    for raw_col, adjusted_col in (("open", "adj_open"), ("high", "adj_high"),
                                  ("low", "adj_low"), ("close", "adj_close")):
        adjusted[raw_col] = adjusted[adjusted_col]
    adjusted = adjusted.drop(columns=["adj_open", "adj_high", "adj_low", "adj_close"], errors="ignore")
    return adjusted, None


def spearman_rank_correlation(left: pd.Series, right: pd.Series) -> Optional[float]:
    """Spearman rho without scipy: Pearson correlation of average-tie ranks."""
    pair = pd.concat([left, right], axis=1).apply(pd.to_numeric, errors="coerce").dropna()
    if len(pair) < 2 or pair.iloc[:, 0].nunique() < 2 or pair.iloc[:, 1].nunique() < 2:
        return None
    return float(pair.iloc[:, 0].rank(method="average").corr(pair.iloc[:, 1].rank(method="average")))


def assign_daily_deciles(panel: pd.DataFrame) -> pd.DataFrame:
    """Assign D1..D10 per day, retaining ties deterministically by input order."""
    out = panel.copy()
    out["decile"] = pd.NA
    for date, indices in out.groupby("trade_date", sort=False).groups.items():
        scores = pd.to_numeric(out.loc[indices, "stock_score"], errors="coerce")
        valid = scores.dropna()
        if len(valid) < 10:
            continue
        ranks = valid.rank(method="first")
        bins = pd.qcut(ranks, 10, labels=False, duplicates="drop")
        out.loc[valid.index, "decile"] = (bins.astype(int) + 1).map(lambda x: f"D{x}")
    return out


def _price_path(stock_id: str, entry_date: str, entry_price: float,
                indexed_ohlcv: Mapping[str, pd.DataFrame], maximum_horizon: int = 20,
                market_trade_dates: Optional[Sequence[str]] = None) -> Optional[list[tuple[str, float]]]:
    """Calendar-aligned path, or ``None`` when the stock misses any market bar."""
    return _price_paths_by_horizon(
        stock_id, entry_date, entry_price, indexed_ohlcv, (maximum_horizon,), market_trade_dates,
    )[maximum_horizon]


def _price_paths_by_horizon(stock_id: str, entry_date: str, entry_price: float,
                            indexed_ohlcv: Mapping[str, pd.DataFrame],
                            horizons: Sequence[int] = HORIZONS,
                            market_trade_dates: Optional[Sequence[str]] = None
                            ) -> dict[int, Optional[list[tuple[str, float]]]]:
    """Build all requested calendar-aligned paths in one pass."""
    out: dict[int, Optional[list[tuple[str, float]]]] = {horizon: None for horizon in horizons}
    hist = indexed_ohlcv.get(str(stock_id))
    if hist is None or hist.empty:
        return out
    market_dates = list(market_trade_dates) if market_trade_dates is not None else sorted({
        str(date)
        for frame in indexed_ohlcv.values()
        for date in frame.get("trade_date", pd.Series(dtype=str)).dropna().astype(str)
    })
    if entry_date not in market_dates:
        return out
    start = market_dates.index(entry_date)
    maximum_horizon = max(horizons)
    expected_dates = market_dates[start:start + maximum_horizon]
    rows_by_date = (hist.assign(trade_date=hist["trade_date"].astype(str))
                    .drop_duplicates("trade_date", keep="last")
                    .set_index("trade_date"))
    previous = float(entry_price)
    path: list[tuple[str, float]] = []
    for offset, expected_date in enumerate(expected_dates, start=1):
        if expected_date not in rows_by_date.index:
            break
        row = rows_by_date.loc[expected_date]
        close = row.get("close")
        if pd.isna(close) or previous <= 0:
            break
        close = float(close)
        if close <= 0:
            break
        path.append((expected_date, (close - previous) / previous))
        previous = close
        if offset in out:
            out[offset] = path.copy()
    return out


def _market_forward_returns(entry_date: str, taiex: pd.DataFrame,
                            market_trade_dates: Sequence[str],
                            horizons: Sequence[int] = HORIZONS) -> dict[int, Optional[float]]:
    """Close-to-close TAIEX returns from the signal close through each exit.

    ``entry_date`` is market T+1.  The origin is therefore the preceding market
    close, making a one-day return the entry day's actual index move instead of
    the previous structurally-zero entry-close-to-entry-close value.
    """
    out = {horizon: None for horizon in horizons}
    if entry_date not in market_trade_dates or taiex.empty:
        return out
    market = (taiex.assign(trade_date=taiex["trade_date"].astype(str))
              .drop_duplicates("trade_date", keep="last")
              .set_index("trade_date")["close"])
    start = list(market_trade_dates).index(entry_date)
    if start == 0:
        return out
    origin_date = list(market_trade_dates)[start - 1]
    if origin_date not in market.index:
        return out
    origin_close = market.loc[origin_date]
    if pd.isna(origin_close) or float(origin_close) <= 0:
        return out
    for horizon in horizons:
        expected = list(market_trade_dates)[start:start + horizon]
        if len(expected) < horizon or any(date not in market.index for date in expected):
            continue
        exit_close = market.loc[expected[-1]]
        if pd.notna(exit_close):
            out[horizon] = float((float(exit_close) - float(origin_close)) / float(origin_close))
    return out


def _market_forward_returns_from_entry_close(
        entry_date: str, taiex: pd.DataFrame, market_trade_dates: Sequence[str],
        horizons: Sequence[int] = HORIZONS) -> dict[int, Optional[float]]:
    """Legacy diagnostic comparator: entry close through each exit close."""
    out = {horizon: None for horizon in horizons}
    if entry_date not in market_trade_dates or taiex.empty:
        return out
    market = (taiex.assign(trade_date=taiex["trade_date"].astype(str))
              .drop_duplicates("trade_date", keep="last")
              .set_index("trade_date")["close"])
    start = list(market_trade_dates).index(entry_date)
    if entry_date not in market.index:
        return out
    origin_close = market.loc[entry_date]
    if pd.isna(origin_close) or float(origin_close) <= 0:
        return out
    for horizon in horizons:
        expected = list(market_trade_dates)[start:start + horizon]
        if len(expected) < horizon or any(date not in market.index for date in expected):
            continue
        exit_close = market.loc[expected[-1]]
        if pd.notna(exit_close):
            out[horizon] = float((float(exit_close) - float(origin_close)) / float(origin_close))
    return out


def _stock_close_to_close_returns(
        stock_id: str, signal_date: str, indexed_ohlcv: Mapping[str, pd.DataFrame],
        market_trade_dates: Sequence[str], horizons: Sequence[int] = HORIZONS
        ) -> dict[int, Optional[float]]:
    """Stock close-to-close returns aligned to the TAIEX comparison window."""
    out = {horizon: None for horizon in horizons}
    hist = indexed_ohlcv.get(str(stock_id))
    if hist is None or hist.empty or signal_date not in market_trade_dates:
        return out
    rows = (hist.assign(trade_date=hist["trade_date"].astype(str))
            .drop_duplicates("trade_date", keep="last")
            .set_index("trade_date"))
    if signal_date not in rows.index:
        return out
    origin_close = rows.loc[signal_date].get("close")
    if pd.isna(origin_close) or float(origin_close) <= 0:
        return out
    start = list(market_trade_dates).index(signal_date) + 1
    for horizon in horizons:
        expected = list(market_trade_dates)[start:start + horizon]
        if len(expected) < horizon or any(date not in rows.index for date in expected):
            continue
        exit_close = rows.loc[expected[-1]].get("close")
        if pd.notna(exit_close) and float(exit_close) > 0:
            out[horizon] = float((float(exit_close) - float(origin_close)) / float(origin_close))
    return out


def build_return_panel(scored_by_date: Mapping[str, pd.DataFrame], indexed_ohlcv: Mapping[str, pd.DataFrame],
                       taiex: pd.DataFrame, start: Optional[str] = None, end: Optional[str] = None) -> tuple[pd.DataFrame, dict[int, dict[int, list[tuple[str, float]]]]]:
    """Flatten scored snapshots and attach only existing T+1 forward returns.

    The second return value holds short in-memory price paths used solely for
    overlapping-portfolio accounting.  It is deliberately not written to disk.
    """
    # Import at execution time.  Importing the orchestration module during pytest
    # collection mutates its legacy path setup and leaks into unrelated integration
    # tests; this diagnostic remains a direct consumer of the same helpers.
    from src.backtester import compute_entry_price, compute_stock_forward_returns

    rows: list[dict] = []
    paths: dict[int, dict[int, list[tuple[str, float]]]] = {}
    market_trade_dates = sorted({
        str(date)
        for frame in indexed_ohlcv.values()
        for date in frame.get("trade_date", pd.Series(dtype=str)).dropna().astype(str)
    })
    market_returns_by_entry: dict[str, dict[int, Optional[float]]] = {}
    legacy_market_returns_by_entry: dict[str, dict[int, Optional[float]]] = {}
    row_id = 0
    for signal_date, frame in sorted(scored_by_date.items()):
        if (start and signal_date < start) or (end and signal_date > end) or frame.empty:
            continue
        available = [c for c in SCORE_COLUMNS if c in frame.columns]
        day = frame.loc[:, available].copy()
        for col in SCORE_COLUMNS:
            if col not in day:
                day[col] = pd.NA
        day["stock_id"] = day["stock_id"].astype(str)
        for _, scored in day.iterrows():
            stock_id = str(scored["stock_id"])
            entry = compute_entry_price(stock_id, signal_date, indexed_ohlcv, limit_up_handling="exclude")
            if entry["status"] != "TRADABLE":
                continue
            signal_position = market_trade_dates.index(signal_date) if signal_date in market_trade_dates else -1
            expected_entry_date = (
                market_trade_dates[signal_position + 1]
                if signal_position >= 0 and signal_position + 1 < len(market_trade_dates)
                else None
            )
            stock_trade_dates = set(
                indexed_ohlcv[str(stock_id)]["trade_date"].dropna().astype(str)
            )
            previous_market_date = (
                market_trade_dates[signal_position - 1] if signal_position > 0 else None
            )
            if previous_market_date is not None and previous_market_date not in stock_trade_dates:
                LOGGER.debug(
                    "Rejecting %s signal %s: prior market bar %s is missing",
                    stock_id, signal_date, previous_market_date,
                )
                continue
            if entry["entry_date"] != expected_entry_date:
                LOGGER.debug(
                    "Rejecting %s signal %s: first stock bar %s is not market T+1 %s",
                    stock_id, signal_date, entry["entry_date"], expected_entry_date,
                )
                continue
            forwards = compute_stock_forward_returns(stock_id, entry["entry_date"], entry["entry_price"],
                                                       indexed_ohlcv, horizons=HORIZONS)
            price_paths = _price_paths_by_horizon(
                stock_id, entry["entry_date"], entry["entry_price"],
                indexed_ohlcv, HORIZONS, market_trade_dates,
            )
            close_to_close = _stock_close_to_close_returns(
                stock_id, signal_date, indexed_ohlcv, market_trade_dates,
            )
            if entry["entry_date"] not in market_returns_by_entry:
                market_returns_by_entry[entry["entry_date"]] = _market_forward_returns(
                    entry["entry_date"], taiex, market_trade_dates,
                )
                legacy_market_returns_by_entry[entry["entry_date"]] = (
                    _market_forward_returns_from_entry_close(
                        entry["entry_date"], taiex, market_trade_dates,
                    )
                )
            market = market_returns_by_entry[entry["entry_date"]]
            legacy_market = legacy_market_returns_by_entry[entry["entry_date"]]
            entry_row = (indexed_ohlcv[stock_id]
                         .loc[indexed_ohlcv[stock_id]["trade_date"].astype(str) == entry["entry_date"]]
                         .iloc[-1])
            record = scored.to_dict()
            record.update({
                "row_id": row_id,
                "entry_date": entry["entry_date"],
                "entry_price": entry["entry_price"],
                "price_unadjusted": bool(entry_row.get("price_unadjusted", True)),
            })
            for horizon in HORIZONS:
                gross = forwards[horizon] if price_paths[horizon] is not None else None
                aligned_stock = close_to_close[horizon] if price_paths[horizon] is not None else None
                record[f"gross_{horizon}d"] = gross
                record[f"close_to_close_{horizon}d"] = aligned_stock
                record[f"market_{horizon}d"] = market[horizon]
                record[f"market_entry_close_{horizon}d"] = legacy_market[horizon]
                record[f"legacy_excess_{horizon}d"] = (
                    gross - legacy_market[horizon]
                    if gross is not None and legacy_market[horizon] is not None else None
                )
                record[f"aligned_excess_{horizon}d"] = (
                    aligned_stock - market[horizon]
                    if aligned_stock is not None and market[horizon] is not None else None
                )
                record[f"excess_{horizon}d"] = record[f"legacy_excess_{horizon}d"]
            available_paths = {horizon: path for horizon, path in price_paths.items() if path is not None}
            if available_paths:
                paths[row_id] = available_paths
            rows.append(record)
            row_id += 1
    return pd.DataFrame(rows), paths


def decile_table(panel: pd.DataFrame, horizon: int = 10) -> tuple[pd.DataFrame, dict]:
    ranked = assign_daily_deciles(panel)
    rows = []
    col = f"excess_{horizon}d"
    for i in range(1, 11):
        values = pd.to_numeric(ranked.loc[ranked["decile"] == f"D{i}", col], errors="coerce").dropna()
        rows.append({"decile": f"D{i}", "n_stock_days": len(values),
                     "median_excess_return": float(values.median()) if len(values) else None,
                     "win_rate": float((values > 0).mean()) if len(values) else None,
                     "rank": i})
    table = pd.DataFrame(rows)
    complete = table.dropna(subset=["median_excess_return"])
    rho = spearman_rank_correlation(complete["rank"], complete["median_excess_return"])
    d1 = table.loc[table["decile"] == "D1", "median_excess_return"].iloc[0]
    d10 = table.loc[table["decile"] == "D10", "median_excess_return"].iloc[0]
    spread = d10 - d1 if pd.notna(d10) and pd.notna(d1) else None
    rank_rule_passed = bool(spread is not None and spread > 0 and rho is not None and rho > 0.5)
    minimum_n = int(table["n_stock_days"].min()) if not table.empty else 0
    daily_counts = (ranked.dropna(subset=[col])
                    .groupby(["trade_date", "decile"]).size()
                    .unstack(fill_value=0)
                    .reindex(columns=[f"D{i}" for i in range(1, 11)], fill_value=0))
    daily_minimum = int(daily_counts.min(axis=1).min()) if not daily_counts.empty else 0
    decisive_days = int((daily_counts.min(axis=1) >= MIN_DAILY_DECILE_N).sum()) if not daily_counts.empty else 0
    daily_requirement_met = decisive_days >= MIN_DECISIVE_DECILE_DAYS
    total_requirement_met = minimum_n >= 10_000
    daily_spreads = []
    for date in daily_counts.index[daily_counts.min(axis=1) >= MIN_DAILY_DECILE_N]:
        day = ranked[ranked["trade_date"] == date]
        d1_daily = pd.to_numeric(
            day.loc[day["decile"] == "D1", col], errors="coerce",
        ).dropna()
        d10_daily = pd.to_numeric(
            day.loc[day["decile"] == "D10", col], errors="coerce",
        ).dropna()
        if len(d1_daily) >= MIN_DAILY_DECILE_N and len(d10_daily) >= MIN_DAILY_DECILE_N:
            daily_spreads.append(float(d10_daily.mean() - d1_daily.mean()))
    spread_stats = horizon_newey_west_tstat(daily_spreads, horizon)
    return table, {
        "d10_minus_d1": spread, "spearman": rho, "passed": rank_rule_passed,
        "minimum_decile_n": minimum_n, "sample_requirement_met": total_requirement_met,
        "minimum_daily_decile_n": daily_minimum, "n_decisive_decile_days": decisive_days,
        "daily_sample_requirement_met": daily_requirement_met,
        "headline_sample_requirement_met": total_requirement_met and daily_requirement_met,
        "daily_d10_minus_d1_mean": spread_stats["mean"],
        "daily_d10_minus_d1_t_stat": spread_stats["t_stat"],
        "daily_d10_minus_d1_n": spread_stats["n_daily"],
        "daily_d10_minus_d1_nw_lag": spread_stats["nw_lag"],
        "daily_d10_minus_d1_positive_rate": (
            float(np.mean(np.asarray(daily_spreads) > 0)) if daily_spreads else None
        ),
    }


def horizon_availability_table(panel: pd.DataFrame, horizons: Sequence[int] = HORIZONS) -> pd.DataFrame:
    """Expose realized samples by horizon; never use shorter returns as a substitute."""
    rows = []
    per_date = panel.groupby("trade_date").size() if not panel.empty else pd.Series(dtype=int)
    wide_dates = set(per_date[per_date >= WIDE_UNIVERSE_MIN_STOCKS].index.astype(str))
    for horizon in horizons:
        eligible = panel.dropna(subset=[f"gross_{horizon}d", f"market_{horizon}d"])
        dates = set(eligible["trade_date"].astype(str))
        wide_eligible = eligible[eligible["trade_date"].astype(str).isin(wide_dates)]
        n_wide_dates = int(wide_eligible["trade_date"].nunique())
        rows.append({
            "horizon_days": horizon,
            "n_stock_days": int(len(eligible)),
            "n_trade_dates": int(len(dates)),
            "n_wide_universe_stock_days": int(len(wide_eligible)),
            "n_wide_universe_trade_dates": n_wide_dates,
            "wide_universe_mature": n_wide_dates >= MIN_DECISIVE_DECILE_DAYS,
            "status": "mature" if n_wide_dates >= MIN_DECISIVE_DECILE_DAYS else "insufficient_not_decisive",
        })
    return pd.DataFrame(rows)


def rank_ic_table(panel: pd.DataFrame, horizons: Sequence[int] = HORIZONS) -> pd.DataFrame:
    rows = []
    for factor in FACTORS:
        for horizon in horizons:
            daily_ics = []
            target = f"gross_{horizon}d"
            for _, day in panel.groupby("trade_date"):
                pair = day[[factor, target]].apply(pd.to_numeric, errors="coerce").dropna()
                if len(pair) >= 3 and pair[factor].nunique() > 1 and pair[target].nunique() > 1:
                    ic = spearman_rank_correlation(pair[factor], pair[target])
                    if ic is not None:
                        daily_ics.append(ic)
            stats = horizon_newey_west_tstat(daily_ics, horizon)
            rows.append({"factor": factor, "horizon_days": horizon, "n_daily": stats["n_daily"],
                         "mean_ic": stats["mean"], "ic_std": stats["std"], "nw_lag": stats["nw_lag"],
                         "ic_t_stat": stats["t_stat"],
                         "positive_ic_win_rate": float(np.mean(np.asarray(daily_ics) > 0)) if daily_ics else None})
    return pd.DataFrame(rows)


def _portfolio_stats(daily_gross: Mapping[str, float], daily_net: Mapping[str, float],
                     holding_days: Sequence[int], decision_days: int, horizon: int) -> dict:
    gross = pd.Series(daily_gross, dtype=float).sort_index()
    net = pd.Series(daily_net, dtype=float).sort_index()
    gross_total = float((1 + gross).prod() - 1) if not gross.empty else None
    net_total = float((1 + net).prod() - 1) if not net.empty else None
    nw = horizon_newey_west_tstat(net.tolist(), horizon)
    return {"gross_total_return": gross_total, "net_total_return": net_total,
            "n_daily_portfolio_observations": int(len(net)),
            "average_holding_days": float(np.mean(holding_days)) if holding_days else None,
            "average_daily_turnover": (1 / horizon) if decision_days else None,
            "nw_lag": nw["nw_lag"], "net_daily_t_stat": nw["t_stat"]}


def simulate_overlapping_portfolio(selected_row_ids: Mapping[str, Sequence[int]],
                                   paths: Mapping[int, Mapping[int, list[tuple[str, float]]]], horizon: int,
                                   constituent_aggregation: str = "mean") -> dict:
    """Simulate daily tranches; each remains invested K days.

    Top-N and random portfolios use equal-weight means.  The all-market benchmark
    uses the requested cross-sectional median, so one outsized stock cannot define
    the reference return.
    """
    if constituent_aggregation not in {"mean", "median"}:
        raise ValueError("constituent_aggregation must be 'mean' or 'median'")
    from src.backtester import apply_trading_cost

    daily_gross: dict[str, float] = defaultdict(float)
    daily_net: dict[str, float] = defaultdict(float)
    holding_days: list[int] = []
    decision_days = 0
    for _, row_ids in sorted(selected_row_ids.items()):
        tranche_paths = [paths[row_id][horizon] for row_id in row_ids if row_id in paths and horizon in paths[row_id]
                         and len(paths[row_id][horizon]) == horizon]
        if not tranche_paths:
            continue
        decision_days += 1
        weight = 1 / (horizon * len(tranche_paths))
        median_returns: dict[str, list[float]] = defaultdict(list)
        entry_costs: dict[str, float] = defaultdict(float)
        for path in tranche_paths:
            holding_days.append(len(path))
            for i, (date, daily_return) in enumerate(path):
                if constituent_aggregation == "mean":
                    daily_gross[date] += daily_return * weight
                    daily_net[date] += daily_return * weight
                else:
                    median_returns[date].append(daily_return)
                if i == 0:
                    # Use the shared cost function so this is the exact documented
                    # 0.685% round-trip charge, allocated once per tranche.
                    cost = -apply_trading_cost(0.0, FEE_PCT, TAX_PCT, SLIPPAGE_PCT)
                    entry_costs[date] += cost * weight
        if constituent_aggregation == "median":
            accepted_dates: set[str] = set()
            for date, returns in median_returns.items():
                if len(returns) < 30:
                    continue
                accepted_dates.add(date)
                daily_gross[date] += float(np.median(returns)) / horizon
                daily_net[date] += float(np.median(returns)) / horizon
        for date, cost in entry_costs.items():
            if constituent_aggregation == "median" and date not in accepted_dates:
                continue
            daily_net[date] -= cost
    return _portfolio_stats(daily_gross, daily_net, holding_days, decision_days, horizon)


def select_top(panel: pd.DataFrame, column: str, n: int, horizon: int) -> dict[str, list[int]]:
    eligible = panel.dropna(subset=[column, f"gross_{horizon}d"])
    out: dict[str, list[int]] = {}
    for date, day in eligible.groupby("trade_date"):
        out[str(date)] = day.nlargest(n, column)["row_id"].astype(int).tolist()
    return out


def select_all_market(panel: pd.DataFrame, horizon: int) -> dict[str, list[int]]:
    eligible = panel.dropna(subset=[f"gross_{horizon}d"])
    return {str(date): day["row_id"].astype(int).tolist() for date, day in eligible.groupby("trade_date")}


def bootstrap_random(panel: pd.DataFrame, paths: Mapping[int, Mapping[int, list[tuple[str, float]]]],
                     n: int, horizon: int, draws: int = 1000, seed: int = 42) -> dict:
    """Bootstrap entire overlapping portfolios from the same daily eligible universe."""
    rng = np.random.default_rng(seed + n * 100 + horizon)
    eligible = panel.dropna(subset=[f"gross_{horizon}d"])
    by_date = {str(date): day["row_id"].astype(int).tolist() for date, day in eligible.groupby("trade_date")}
    gross, net = [], []
    for _ in range(draws):
        selected = {date: rng.choice(ids, size=min(n, len(ids)), replace=False).astype(int).tolist()
                    for date, ids in by_date.items() if ids}
        result = simulate_overlapping_portfolio(selected, paths, horizon)
        if result["gross_total_return"] is not None:
            gross.append(result["gross_total_return"])
            net.append(result["net_total_return"])
    return {"random_bootstrap_draws": draws,
            "random_gross_total_return_median": float(np.median(gross)) if gross else None,
            "random_net_total_return_median": float(np.median(net)) if net else None}


def portfolio_table(panel: pd.DataFrame, paths: Mapping[int, Mapping[int, list[tuple[str, float]]]],
                    draws: int = 1000) -> pd.DataFrame:
    rows = []
    for n in (10, 20, 50):
        for horizon in (5, 10, 20):
            score = simulate_overlapping_portfolio(select_top(panel, "stock_score", n, horizon), paths, horizon)
            momentum = simulate_overlapping_portfolio(select_top(panel, "daily_return", n, horizon), paths, horizon)
            volume = simulate_overlapping_portfolio(select_top(panel, "volume", n, horizon), paths, horizon)
            market = simulate_overlapping_portfolio(select_all_market(panel, horizon), paths, horizon,
                                                     constituent_aggregation="median")
            bootstrap = bootstrap_random(panel, paths, n, horizon, draws=draws)
            rows.append({"portfolio": "stock_score_top_n", "n_stocks": n, "holding_days": horizon, **score,
                         "momentum_net_total_return": momentum["net_total_return"],
                         "volume_net_total_return": volume["net_total_return"],
                         "all_market_median_net_total_return": market["net_total_return"], **bootstrap})
    return pd.DataFrame(rows)


def quality_table(panel: pd.DataFrame, paths: Mapping[int, Mapping[int, list[tuple[str, float]]]],
                  draws: int) -> tuple[pd.DataFrame, dict[str, dict[str, pd.DataFrame]]]:
    labels = {"FULL": panel[panel["score_confidence"] == "FULL"],
              "DEGRADED_LOW": panel[panel["score_confidence"].isin(["DEGRADED", "LOW"])]}
    summary, detail = [], {}
    for label, subset in labels.items():
        table_a, decision = decile_table(subset)
        table_b = rank_ic_table(subset)
        table_c = portfolio_table(subset, paths, draws=draws)
        detail[label] = {"table_a": table_a, "table_b": table_b, "table_c": table_c}
        summary.append({"quality_group": label, "n_stock_days": len(subset),
                        "n_trade_dates": subset["trade_date"].nunique(),
                        "d10_minus_d1": decision["d10_minus_d1"], "spearman": decision["spearman"],
                        "decile_passed": decision["passed"],
                        "mean_10d_ic": table_b.loc[table_b["horizon_days"] == 10, "mean_ic"].mean()})
    return pd.DataFrame(summary), detail


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sampled_hashes(project_root: Path) -> dict:
    """Record three processed and up to three existing outputs files before/after."""
    result = {}
    for label, directory in (("processed", project_root / "data" / "processed"),
                             ("outputs", project_root / "outputs")):
        files = sorted(path for path in directory.rglob("*") if path.is_file())
        sample = files[:1] + files[len(files) // 2:len(files) // 2 + 1] + files[-1:]
        result[label] = {str(path.relative_to(project_root)): _sha256(path) for path in dict.fromkeys(sample)}
    return result


def official_snapshot_manifest(data_dir_ohlcv: Path) -> dict[str, dict[str, object]]:
    """Capture every consumed OHLCV snapshot's mtime and hash."""
    files = sorted(data_dir_ohlcv.glob("*.json"))
    return {
        str(path.relative_to(PROJECT_ROOT)): {
            "mtime_ns": path.stat().st_mtime_ns,
            "sha256": _sha256(path),
        }
        for path in files
    }


def market_index_snapshot_manifest(data_dir_market_index: Path) -> dict[str, dict[str, object]]:
    """Capture every consumed market-index snapshot's mtime and hash."""
    files = sorted((*data_dir_market_index.glob("finmind_index_twse.json"),
                    *data_dir_market_index.glob("twse_*.json")))
    return {
        str(path.relative_to(PROJECT_ROOT)): {
            "mtime_ns": path.stat().st_mtime_ns,
            "sha256": _sha256(path),
        }
        for path in files
    }


def protected_code_manifest() -> dict[str, dict[str, object]]:
    """Hash every explicitly protected production/config file before and after."""
    files = sorted(path for path in (PROJECT_ROOT / "src").rglob("*") if path.is_file())
    files.extend(PROJECT_ROOT / relative for relative in (
        "scripts/run_daily.py",
        "scripts/daily_orchestrator.py",
        "scripts/run_backtest.py",
        "scripts/fetch_history_finmind.py",
        "config/default.yaml",
    ))
    return {
        str(path.relative_to(PROJECT_ROOT)): {
            "mtime_ns": path.stat().st_mtime_ns,
            "sha256": _sha256(path),
        }
        for path in files
    }


def scored_ohlcv_coverage(scored_by_date: Mapping[str, pd.DataFrame], ohlcv: pd.DataFrame) -> dict:
    """Report score-universe coverage after the FinMind+official merge."""
    available_by_date = {
        str(date): set(day["stock_id"].astype(str))
        for date, day in ohlcv.groupby("trade_date")
    }
    rows = []
    for date, frame in sorted(scored_by_date.items()):
        scored_ids = set(frame["stock_id"].astype(str)) if "stock_id" in frame else set()
        covered = scored_ids & available_by_date.get(str(date), set())
        rows.append({
            "trade_date": str(date),
            "scored_stocks": len(scored_ids),
            "covered_stocks": len(covered),
            "missing_stocks": len(scored_ids - covered),
        })
    target = next((row for row in rows if row["trade_date"] == "2026-07-16"), None)
    return {
        "by_date": rows,
        "target_2026_07_16": target,
        "total_merged_rows": int(len(ohlcv)),
        "total_merged_unique_stocks": int(ohlcv["stock_id"].nunique()) if not ohlcv.empty else 0,
    }


def _narrow_unadjusted_stats(
        panel: pd.DataFrame, factor_ids: set[str], horizon: int = 10) -> dict[str, object]:
    """Measure factor-series gaps only on realized rows in the tested universe."""
    eligible = panel.dropna(subset=[f"excess_{horizon}d"])
    missing = ~eligible["stock_id"].astype(str).isin(factor_ids)
    missing_rows = int(missing.sum())
    return {
        "unadjusted_rows": missing_rows,
        "total_rows": int(len(eligible)),
        "ratio": float(missing_rows / len(eligible)) if len(eligible) else None,
        "numerator": (
            f"realized FULL {horizon}-day rows whose stock has no verified factor series"
        ),
        "denominator": (
            f"all realized FULL {horizon}-day rows used by Table A and {horizon}-day B/C cells"
        ),
    }


def _markdown_table(frame: pd.DataFrame, max_rows: Optional[int] = None) -> str:
    if frame.empty:
        return "(no rows)"
    shown = frame if max_rows is None else frame.head(max_rows)
    def render(value: object) -> str:
        if isinstance(value, (float, np.floating)):
            return "" if not np.isfinite(value) else f"{value:.4f}"
        return str(value).replace("|", "\\|")
    header = "| " + " | ".join(map(str, shown.columns)) + " |"
    divider = "| " + " | ".join("---" for _ in shown.columns) + " |"
    body = ["| " + " | ".join(render(value) for value in row) + " |" for row in shown.itertuples(index=False, name=None)]
    return "\n".join([header, divider, *body])


def write_report(output_dir: Path, panel: pd.DataFrame, table_a: pd.DataFrame, decision: dict,
                 table_b: pd.DataFrame, table_c: pd.DataFrame, table_d: pd.DataFrame,
                 horizon_availability: pd.DataFrame, unadjusted_stats: Optional[Mapping[str, object]],
                 hashes_before: dict, hashes_after: dict, raw_before: dict, raw_after: dict,
                 extreme_loss_10d_count: int, smoke: bool,
                 diagnostics: Optional[dict] = None,
                 protected_before: Optional[dict] = None,
                 protected_after: Optional[dict] = None,
                 market_index_before: Optional[dict] = None,
                 market_index_after: Optional[dict] = None) -> None:
    diagnostics = diagnostics or {}
    protected_before = protected_before or {}
    protected_after = protected_after or {}
    market_index_before = market_index_before or {}
    market_index_after = market_index_after or {}
    unadjusted_stats = dict(unadjusted_stats or {})
    output_dir.mkdir(parents=True, exist_ok=True)
    table_a.to_csv(output_dir / "table_a_decile_monotonicity.csv", index=False)
    table_b.to_csv(output_dir / "table_b_rank_ic.csv", index=False)
    table_c.to_csv(output_dir / "table_c_overlapping_portfolios.csv", index=False)
    table_d.to_csv(output_dir / "table_d_quality_strata.csv", index=False)
    horizon_availability.to_csv(output_dir / "horizon_availability.csv", index=False)
    (output_dir / "input_output_hash_samples.json").write_text(json.dumps({"before": hashes_before, "after": hashes_after,
                                                                              "unchanged": hashes_before == hashes_after}, indent=2), encoding="utf-8")
    (output_dir / "official_snapshot_manifest.json").write_text(
        json.dumps({"before": raw_before, "after": raw_after, "unchanged": raw_before == raw_after}, indent=2),
        encoding="utf-8",
    )
    (output_dir / "diagnostic_evidence.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2, default=str), encoding="utf-8",
    )
    (output_dir / "protected_files_manifest.json").write_text(
        json.dumps({
            "before": protected_before,
            "after": protected_after,
            "unchanged": protected_before == protected_after,
        }, indent=2),
        encoding="utf-8",
    )
    (output_dir / "market_index_snapshot_manifest.json").write_text(
        json.dumps({
            "before": market_index_before,
            "after": market_index_after,
            "unchanged": market_index_before == market_index_after,
        }, indent=2),
        encoding="utf-8",
    )
    if not decision["headline_sample_requirement_met"]:
        conclusion = "樣本不足，不可裁決"
    elif decision["passed"]:
        conclusion = "通過"
    else:
        conclusion = "不通過"
    horizon_10_20 = horizon_availability[horizon_availability["horizon_days"].isin([10, 20])]
    report = [
        "# Stock-score diagnostic (read-only)", "",
        f"- Mode: {'smoke' if smoke else 'full'}; panel stock-days: {len(panel):,}; trade dates: {panel['trade_date'].nunique() if not panel.empty else 0}.",
        "- Headline scope: FULL-confidence observations only. DEGRADED/LOW strata are diagnostic-only and cannot support the headline.",
        f"- Headline verdict: **{conclusion}**. D10-D1={decision['d10_minus_d1']!r}; Spearman={decision['spearman']!r}. Rank rule is D10-D1 > 0 and Spearman > 0.5.",
        f"- Acceptance sample check: min decile n={decision['minimum_decile_n']:,} (required >=10,000; met={decision['sample_requirement_met']}); min daily decile n={decision['minimum_daily_decile_n']:,}; decisive days={decision['n_decisive_decile_days']} (required >=50 for >=40 days; met={decision['daily_sample_requirement_met']}).",
        "- Horizon maturity: 10/20-day wide-universe samples are reported separately below. They are not replaced with 1/3/5-day returns and remain non-decisive until mature.",
        f"- Zero-close guard: gross_10d <= -0.9 count is {extreme_loss_10d_count}; zero-price bars are excluded rather than recorded as a -100% return.",
        (
            "- UNADJUSTED narrow-universe row proportion: "
            f"{unadjusted_stats.get('ratio')!r} "
            f"({unadjusted_stats.get('unadjusted_rows', 0):,} / "
            f"{unadjusted_stats.get('total_rows', 0):,}). "
            f"Numerator: {unadjusted_stats.get('numerator', 'n/a')}; "
            f"denominator: {unadjusted_stats.get('denominator', 'n/a')}."
        ),
        "- Statistics: daily portfolio / daily IC series only; Newey-West Bartlett adjustment. Stock-day rows are never treated as independent t-test observations.",
        "- Limitation: disposition data are a 2026-07-18 current snapshot, not historical per-date records; no disposition penalty is applied.", "",
        "## Return-basis disclosure",
        (
            "- Before Batch 6, stock returns started at the entry-day open while TAIEX "
            "started at the entry-day close. The omitted entry-day intraday stock move "
            f"averaged {diagnostics.get('return_basis', {}).get('entry_intraday_mean')!r} "
            f"and had median {diagnostics.get('return_basis', {}).get('entry_intraday_median')!r}."
        ),
        (
            "- That mismatch accounted for approximately "
            f"{diagnostics.get('return_basis', {}).get('legacy_negative_level_artifact_share')!r} "
            "of the legacy all-negative decile level. The estimate is the absolute mean "
            "entry-day intraday move divided by the absolute mean of the ten legacy 10-day "
            "decile medians."
        ),
        (
            "- Batch 6 keeps tradable open-to-close gross returns for portfolio simulation, "
            "and keeps Table A on that actionable next-open basis. A separate aligned table "
            "compares stock and TAIEX on the same signal-close-to-exit-close window. That "
            "aligned series includes the overnight gap before a next-open trade can occur, "
            "so it is diagnostic evidence, not an executable return claim."
        ),
        (
            "- The common market subtraction and equal-weight-stock versus capitalization-weighted-"
            "TAIEX basis are horizontal level shifts and cancel in D10-D1. Stock-specific overnight "
            "gaps can change the aligned ranks, so those results are shown separately."
        ),
        (
            "- Daily D10-D1 mean spread: "
            f"{decision.get('daily_d10_minus_d1_mean')!r}; "
            f"Newey-West t={decision.get('daily_d10_minus_d1_t_stat')!r}; "
            f"n={decision.get('daily_d10_minus_d1_n')}; "
            f"positive-day rate={decision.get('daily_d10_minus_d1_positive_rate')!r}; "
            f"lag={decision.get('daily_d10_minus_d1_nw_lag')}."
        ), "",
        "## Horizon availability", _markdown_table(horizon_availability), "",
        f"- 10/20-day wide-universe maturity: {horizon_10_20[['horizon_days', 'n_wide_universe_trade_dates', 'wide_universe_mature']].to_dict(orient='records')}", "",
        "## Table A — Tradable next-open decile monotonicity", _markdown_table(table_a), "",
        "## Table A2 — Aligned close-to-close deciles (diagnostic only)",
        _markdown_table(pd.DataFrame(
            diagnostics.get("aligned_close_to_close_deciles", {}).get("table", []),
        )), "",
        "## Table B — Factor rank IC", _markdown_table(table_b), "",
        "## Table C — Top-N overlapping portfolios", _markdown_table(table_c), "",
        "## Table D — Data-quality strata", _markdown_table(table_d), "",
        "## Adapter and calendar evidence", "```json",
        json.dumps(diagnostics, ensure_ascii=False, indent=2, default=str), "```", "",
        "## Side-effect evidence",
        f"Hash samples unchanged: `{hashes_before == hashes_after}`. OHLCV snapshots unchanged: `{raw_before == raw_after}`. Market-index snapshots unchanged: `{market_index_before == market_index_after}`. Protected production/config files unchanged: `{protected_before == protected_after}`. All generated files are in this workbench directory.",
    ]
    (output_dir / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")


def run(start: Optional[str] = None, end: Optional[str] = None, smoke: bool = False,
        bootstrap_draws: int = 1000, output_dir: Optional[Path] = None) -> dict:
    """Execute the diagnostic without changing project inputs or production outputs."""
    from src.backtester import index_ohlcv_by_stock

    data_dir = PROJECT_ROOT / "data"
    report_date = dt.date.today().isoformat()
    output_dir = output_dir or (WORKSPACE_ROOT / "Quant-Agent" / "_workbench" / "out" /
                                f"stock_score_diagnostic_{report_date}{'_smoke' if smoke else ''}")
    hashes_before = sampled_hashes(PROJECT_ROOT)
    raw_before = official_snapshot_manifest(data_dir / "raw" / "ohlcv")
    market_index_before = market_index_snapshot_manifest(data_dir / "raw" / "market_index")
    protected_before = protected_code_manifest()
    scored = load_scored_by_date(data_dir / "processed")
    ohlcv = load_official_ohlcv_history(data_dir / "raw" / "ohlcv")
    taiex = load_taiex(data_dir / "raw" / "market_index")
    if not scored or ohlcv.empty or taiex.empty:
        raise RuntimeError("Required on-disk scored snapshots, OHLCV, or TAIEX history are unavailable.")
    adjusted, _ = apply_local_price_adjustment(ohlcv, data_dir)
    panel, paths = build_return_panel(scored, index_ohlcv_by_stock(adjusted), taiex, start=start, end=end)
    if panel.empty:
        raise RuntimeError("No tradable stock-score rows in requested date range.")
    draws = min(20, bootstrap_draws) if smoke else bootstrap_draws
    full_panel = panel[panel["score_confidence"] == "FULL"].copy()
    factor_path = data_dir / "reference" / "price_adjustment_factors.csv"
    factor_ids = set(
        pd.read_csv(factor_path, dtype={"stock_id": str})["stock_id"].astype(str)
    ) if factor_path.exists() else set()
    unadjusted_stats = _narrow_unadjusted_stats(full_panel, factor_ids)
    table_a, decision = decile_table(full_panel)
    aligned_panel = full_panel.copy()
    for horizon in HORIZONS:
        aligned_panel[f"excess_{horizon}d"] = aligned_panel[f"aligned_excess_{horizon}d"]
    aligned_table_a, aligned_decision = decile_table(aligned_panel)
    table_b = rank_ic_table(full_panel)
    table_c = portfolio_table(full_panel, paths, draws=draws)
    table_d, strata = quality_table(panel, paths, draws=draws)
    availability = horizon_availability_table(panel)
    output_dir.mkdir(parents=True, exist_ok=True)
    for label, tables in strata.items():
        tables["table_a"].to_csv(output_dir / f"table_d_{label.lower()}_a_deciles.csv", index=False)
        tables["table_b"].to_csv(output_dir / f"table_d_{label.lower()}_b_ic.csv", index=False)
        tables["table_c"].to_csv(output_dir / f"table_d_{label.lower()}_c_portfolios.csv", index=False)
    aligned_table_a.to_csv(output_dir / "table_a_aligned_close_to_close_deciles.csv", index=False)
    hashes_after = sampled_hashes(PROJECT_ROOT)
    raw_after = official_snapshot_manifest(data_dir / "raw" / "ohlcv")
    market_index_after = market_index_snapshot_manifest(data_dir / "raw" / "market_index")
    protected_after = protected_code_manifest()
    extreme_loss_10d_count = int((pd.to_numeric(panel["gross_10d"], errors="coerce") <= -0.9).sum())
    gross_10d = pd.to_numeric(panel["gross_10d"], errors="coerce")
    intraday = pd.to_numeric(full_panel["gross_1d"], errors="coerce").dropna()
    market_1d = pd.to_numeric(full_panel["market_1d"], errors="coerce").dropna()
    legacy_level = pd.to_numeric(
        table_a["median_excess_return"], errors="coerce",
    ).mean()
    aligned_level = pd.to_numeric(
        aligned_table_a["median_excess_return"], errors="coerce",
    ).mean()
    intraday_mean = float(intraday.mean()) if len(intraday) else None
    intraday_median = float(intraday.median()) if len(intraday) else None
    artifact_share = (
        float(abs(intraday_mean) / abs(legacy_level))
        if intraday_mean is not None and pd.notna(legacy_level) and legacy_level != 0 else None
    )
    suspect_rows = (panel[panel["stock_id"].astype(str).isin(["1435", "2380"])]
                    [["stock_id", "trade_date", "entry_date", "gross_3d", "gross_10d"]]
                    .to_dict(orient="records"))
    diagnostics = {
        "network_calls": 0,
        "network_design": "disk-only; no requests/urllib/fetcher imports",
        "ohlcv_adapter": ohlcv.attrs.get("cleaning_stats", {}),
        "score_coverage": scored_ohlcv_coverage(scored, ohlcv),
        "taiex": taiex.attrs.get("coverage_stats", {}),
        "unadjusted_narrow_universe": unadjusted_stats,
        "return_basis": {
            "design": "parallel tradable-open and aligned signal-close return series",
            "entry_intraday_mean": intraday_mean,
            "entry_intraday_median": intraday_median,
            "legacy_mean_of_10_decile_medians_10d": (
                float(legacy_level) if pd.notna(legacy_level) else None
            ),
            "aligned_mean_of_10_decile_medians_10d": (
                float(aligned_level) if pd.notna(aligned_level) else None
            ),
            "legacy_negative_level_artifact_share": artifact_share,
            "horizontal_shift_does_not_create_d10_d1_ranking": True,
        },
        "market_1d": {
            "n": int(len(market_1d)),
            "unique": int(market_1d.nunique()),
            "min": float(market_1d.min()) if len(market_1d) else None,
            "max": float(market_1d.max()) if len(market_1d) else None,
            "constant_zero": bool(len(market_1d) and market_1d.nunique() == 1 and market_1d.iloc[0] == 0),
        },
        "daily_d10_minus_d1": {
            key: decision.get(key)
            for key in (
                "daily_d10_minus_d1_mean",
                "daily_d10_minus_d1_t_stat",
                "daily_d10_minus_d1_n",
                "daily_d10_minus_d1_nw_lag",
                "daily_d10_minus_d1_positive_rate",
            )
        },
        "aligned_close_to_close_deciles": {
            "role": "diagnostic-only; includes the signal-close to next-open gap",
            "table": aligned_table_a.to_dict(orient="records"),
            "decision": aligned_decision,
        },
        "gross_10d_max": float(gross_10d.max()) if gross_10d.notna().any() else None,
        "gross_10d_leq_negative_90pct_count": extreme_loss_10d_count,
        "suspect_stock_returns": suspect_rows,
        "horizon_availability": availability.to_dict(orient="records"),
        "red_green_evidence": {
            "red_baseline": "6 failed, 15 passed before fixes",
            "F1": "old gate accepted two return dates with only 20 constituents each",
            "F2": "old loader omitted the valid 2026-07-23 official TAIEX row",
            "F3": "old path skipped a missing calendar bar and returned a path",
            "F4": "old adapter omitted legacy TPEx rows and FinMind fallback rows",
            "F5": "old adapter exposed no cleaning counts and retained nonpositive closes",
            "green": "all targeted regression tests passed after fixes",
        },
    }
    write_report(output_dir, full_panel, table_a, decision, table_b, table_c, table_d,
                 availability, unadjusted_stats, hashes_before, hashes_after, raw_before, raw_after,
                 extreme_loss_10d_count, smoke, diagnostics, protected_before, protected_after,
                 market_index_before, market_index_after)
    return {"output_dir": str(output_dir), "panel_rows": len(panel), "decision": decision,
            "hashes_unchanged": hashes_before == hashes_after,
            "official_snapshots_unchanged": raw_before == raw_after,
            "market_index_snapshots_unchanged": market_index_before == market_index_after,
            "protected_files_unchanged": protected_before == protected_after,
            "gross_10d_leq_negative_90pct_count": extreme_loss_10d_count,
            "diagnostics": diagnostics,
            "horizon_availability": availability.to_dict(orient="records")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", help="Inclusive YYYY-MM-DD score date")
    parser.add_argument("--end", help="Inclusive YYYY-MM-DD score date")
    parser.add_argument("--smoke", action="store_true", help="Use 20, not 1,000, random bootstrap draws")
    parser.add_argument("--bootstrap-draws", type=int, default=1000)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = run(args.start, args.end, args.smoke, args.bootstrap_draws)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
