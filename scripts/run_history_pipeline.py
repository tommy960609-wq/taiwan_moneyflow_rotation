"""
M5a historical batch pipeline (SPEC_ADDENDUM item 3 of the M5a brief).

Runs the existing `scripts.run_daily.run_pipeline` (feature engineering -> scoring ->
signal detection -> Excel report) sequentially over every trade_date that has a
successfully-fetched raw OHLCV snapshot on disk (data/raw/ohlcv/{twse,tpex}_<date>.json),
in ascending date order, so rolling multi-day features (5/10/20-day windows,
lifecycle-classification history, sector relative strength) actually accumulate the
way they would in normal day-by-day production operation. This is NOT a separate
scoring/signal implementation -- it is a thin sequential driver over the same
`run_pipeline` used for a single real day (M3/M4), reusing 100% of its no-future-
leakage-by-construction contract (each day only ever reads processed CSVs dated <=
itself).

Per the M5a brief, this script does NOT produce a full Excel report for every
historical day (that would be wasteful and isn't needed for rolling-feature
accumulation) -- Excel generation inside run_pipeline is left as-is (it always runs;
disabling it would mean touching M3's locked report_generator wiring), but this
script's job is specifically to (a) let the processed CSVs and rolling history
accumulate and (b) extract a lightweight per-day signal event log to
outputs/signals/signals_<date>.jsonl, one JSON object per graded sector-signal row.

Usage:
    python scripts/run_history_pipeline.py                       # all discovered dates
    python scripts/run_history_pipeline.py --start 2026-04-20 --end 2026-07-17
"""

import os
import sys
import json
import glob
import time
import argparse
import datetime
from typing import List, Optional

import pandas as pd
from loguru import logger

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from scripts.run_daily import run_pipeline
from scripts.prepare_finmind_legacy_snapshot import prepare_finmind_legacy_snapshot


def _default_data_dir() -> str:
    return "C:/Workspace_CN/taiwan_moneyflow_rotation/data"


def _default_output_dir() -> str:
    return "C:/Workspace_CN/taiwan_moneyflow_rotation/outputs"


def discover_available_dates(data_dir: str, start: Optional[str] = None,
                              end: Optional[str] = None) -> List[str]:
    """
    Returns the sorted list of trade_dates that have BOTH a TWSE and a TPEx raw OHLCV
    snapshot successfully saved on disk (data/raw/ohlcv/{twse,tpex}_<date>.json) --
    i.e. the dates run_pipeline can actually process without hitting the
    BLOCKED_MISSING_MARKET fail-closed path. Optionally filtered to [start, end]
    inclusive (YYYY-MM-DD). A date with only one market's file (e.g. TPEx succeeded,
    TWSE hit a DATE_MISMATCH during backfill) is correctly excluded, not silently
    half-processed.
    """
    ohlcv_dir = os.path.join(data_dir, "raw", "ohlcv")
    twse_files = glob.glob(os.path.join(ohlcv_dir, "twse_*.json"))
    tpex_files = glob.glob(os.path.join(ohlcv_dir, "tpex_*.json"))

    def _dates_from(files, prefix):
        dates = set()
        for path in files:
            fname = os.path.basename(path)
            if fname.endswith(".bak"):
                continue
            date_str = fname.replace(f"{prefix}_", "").replace(".json", "")
            try:
                datetime.date.fromisoformat(date_str)
                dates.add(date_str)
            except ValueError:
                continue
        return dates

    twse_dates = _dates_from(twse_files, "twse")
    tpex_dates = _dates_from(tpex_files, "tpex")
    both = twse_dates & tpex_dates

    if start:
        both = {d for d in both if d >= start}
    if end:
        both = {d for d in both if d <= end}

    return sorted(both)


def discover_finmind_dates(data_dir: str, start: Optional[str] = None,
                            end: Optional[str] = None) -> List[str]:
    """
    M5b: unlike the official per-day snapshot files discover_available_dates() scans,
    FinMind's historical data lives in PER-STOCK files
    (data/raw/ohlcv/finmind_<stock_id>.json), each internally covering a whole date
    range. This scans every FinMind ohlcv file's payload for the set of all `date`
    values actually present anywhere in the fetched universe (a trading day is
    considered available if at least one stock has a row for it -- the per-day legacy
    bridge in scripts/prepare_finmind_legacy_snapshot.py then determines, per date, how
    many stocks actually ended up in that day's combined file). Optionally filtered to
    [start, end] inclusive. Returns a sorted list, never guessed -- a date with zero
    FinMind rows anywhere is correctly absent, not silently included.
    """
    ohlcv_dir = os.path.join(data_dir, "raw", "ohlcv")
    finmind_files = glob.glob(os.path.join(ohlcv_dir, "finmind_*.json"))

    dates = set()
    for path in finmind_files:
        fname = os.path.basename(path)
        if not fname.startswith("finmind_") or fname.endswith(".bak"):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                env = json.load(f)
        except Exception:
            continue
        for row in env.get("payload", []) or []:
            d = row.get("date")
            if d:
                dates.add(d)

    if start:
        dates = {d for d in dates if d >= start}
    if end:
        dates = {d for d in dates if d <= end}

    return sorted(dates)


def bridge_finmind_dates(data_dir: str, dates: List[str]) -> dict:
    """
    Runs prepare_finmind_legacy_snapshot for every date in `dates`, so run_pipeline can
    read them via the same legacy filenames the official-source bridge
    (scripts/prepare_legacy_raw_snapshot.py) uses. Official-sourced legacy files (if
    any already exist for a date) are never overwritten -- see
    prepare_finmind_legacy_snapshot's module docstring for the exact priority rule.
    Returns {date: per_file_status_dict}.
    """
    results = {}
    for trade_date in dates:
        results[trade_date] = prepare_finmind_legacy_snapshot(data_dir, trade_date)
    return results


def _extract_signal_events(trade_date: str, df_final_sectors: Optional[pd.DataFrame]) -> List[dict]:
    """
    Flattens one day's graded sector rows into JSONL-ready event dicts. Every row in
    df_final_sectors is included (not just "hit" signals) so a downstream consumer can
    see the full distribution of signal_type across a trading day, not just positives
    -- required for the eventual event-study denominator (SPEC_ADDENDUM B-3 "獨立事件
    數" discipline, though the actual statistics themselves are out of M5a scope).
    """
    if df_final_sectors is None or df_final_sectors.empty:
        return []
    events = []
    for _, row in df_final_sectors.iterrows():
        events.append({
            "trade_date": trade_date,
            "sector_name": row.get("sector_name"),
            "sector_type": row.get("sector_type"),
            "signal_type": row.get("signal_type"),
            "score": row.get("score"),
            "signal_data_confidence": row.get("signal_data_confidence", row.get("score_confidence")),
            "invalidation_condition": row.get("invalidation_condition"),
            "up_stock_count": row.get("up_stock_count"),
            "lifecycle": row.get("lifecycle") if "lifecycle" in row else row.get("lifecycle_stage"),
        })
    return events


def _write_signals_jsonl(output_dir: str, trade_date: str, events: List[dict]) -> str:
    signals_dir = os.path.join(output_dir, "signals")
    os.makedirs(signals_dir, exist_ok=True)
    path = os.path.join(signals_dir, f"signals_{trade_date}.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False, default=str))
            f.write("\n")
    return path


def run_history_pipeline(dates: Optional[List[str]] = None,
                          start: Optional[str] = None, end: Optional[str] = None,
                          data_dir: Optional[str] = None, output_dir: Optional[str] = None,
                          run_pipeline_fn=run_pipeline,
                          use_finmind: bool = False,
                          use_calibrated_thresholds: bool = False) -> dict:
    """
    Runs run_pipeline_fn sequentially over `dates` (or every discovered date in
    [start, end] if `dates` is not given), in ascending order, so day T+1's rolling
    features can see day T's already-persisted processed CSVs (same no-future-leakage
    contract as normal daily operation). For each date, writes
    outputs/signals/signals_<date>.jsonl and accumulates a summary.

    Never raises out on a single day's failure: a BLOCKED_* status for one date is
    recorded and the loop continues to the next date (one bad/missing day must not
    abort the entire historical run) -- fail-closed per-day, not fail-closed for the
    whole batch.

    `use_finmind` (default False, preserving exact M5a behavior): when True, dates are
    discovered from BOTH the official per-day snapshots (discover_available_dates) AND
    FinMind's per-stock historical files (discover_finmind_dates) -- the union, since a
    date may have official data, FinMind data, or (rarely, e.g. 2026-07-17) both. Before
    each FinMind-only date is processed, scripts/prepare_finmind_legacy_snapshot.py
    bridges that date's FinMind rows into the legacy filenames run_pipeline reads
    (never overwriting an official-sourced legacy file that already exists for that
    date -- official priority, per the M5b dual-source rule).

    `use_calibrated_thresholds` (default False, preserving exact pre-M9 behavior):
    forwarded to run_pipeline_fn -- when True, new-gainer/continued-momentum
    min_score/prev_score_max thresholds are the per-sector rolling-quantile calibrated
    values (src/threshold_calibration.py) instead of the fixed absolute placeholders.
    """
    data_dir = data_dir or _default_data_dir()
    output_dir = output_dir or _default_output_dir()

    if dates is None:
        official_dates = set(discover_available_dates(data_dir, start=start, end=end))
        if use_finmind:
            finmind_dates = set(discover_finmind_dates(data_dir, start=start, end=end))
            bridge_finmind_dates(data_dir, sorted(finmind_dates))
            dates = sorted(official_dates | finmind_dates)
        else:
            dates = sorted(official_dates)

    summary = {
        "requested_start": start, "requested_end": end,
        "dates_processed": [], "days_success": 0, "days_blocked": 0,
        "total_signal_events": 0, "signals_per_day": {}, "elapsed_sec": None,
        "signal_files": [],
    }

    run_start = time.time()
    prev_date = None
    for trade_date in dates:
        logger.info(f"[run_history_pipeline] Processing {trade_date} (prev_date={prev_date})...")
        day_start = time.time()
        try:
            audit = run_pipeline_fn(trade_date, prev_date=prev_date,
                                     use_calibrated_thresholds=use_calibrated_thresholds)
        except Exception as e:
            # run_pipeline itself is fail-closed internally (never raises on bad
            # upstream data), but guard the batch driver too so one genuinely
            # unexpected exception doesn't abort the remaining historical days.
            logger.error(f"[run_history_pipeline] Unhandled exception processing {trade_date}: {e}")
            summary["dates_processed"].append({
                "trade_date": trade_date, "status": "EXCEPTION", "error": str(e),
                "elapsed_sec": round(time.time() - day_start, 2),
            })
            summary["days_blocked"] += 1
            prev_date = trade_date
            continue

        status = audit.get("status", "UNKNOWN") if audit else "UNKNOWN"
        df_final_sectors = audit.pop("_df_final_sectors", None) if audit else None
        audit.pop("_df_scored_stocks", None) if audit else None

        day_record = {
            "trade_date": trade_date, "status": status,
            "elapsed_sec": round(time.time() - day_start, 2),
        }

        if status == "SUCCESS":
            events = _extract_signal_events(trade_date, df_final_sectors)
            signal_path = _write_signals_jsonl(output_dir, trade_date, events)
            day_record["signal_count"] = len(events)
            day_record["signal_file"] = signal_path
            summary["signals_per_day"][trade_date] = len(events)
            summary["total_signal_events"] += len(events)
            summary["signal_files"].append(signal_path)
            summary["days_success"] += 1
        else:
            day_record["signal_count"] = 0
            summary["days_blocked"] += 1
            logger.warning(f"[run_history_pipeline] {trade_date} did not succeed (status={status}); "
                            f"no signals JSONL written for this date.")

        summary["dates_processed"].append(day_record)
        prev_date = trade_date

    summary["elapsed_sec"] = round(time.time() - run_start, 2)
    logger.info(
        f"[run_history_pipeline] Done: {summary['days_success']} succeeded, "
        f"{summary['days_blocked']} blocked/failed, "
        f"{summary['total_signal_events']} total signal events, "
        f"{summary['elapsed_sec']}s elapsed."
    )
    return summary


def _write_run_receipt(receipts_dir: str, summary: dict) -> str:
    os.makedirs(receipts_dir, exist_ok=True)
    run_date = datetime.date.today().isoformat()
    path = os.path.join(receipts_dir, f"history_pipeline_summary_{run_date}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"History pipeline summary written to {path}")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="M5a/M5b historical batch feature/score/signal pipeline.")
    parser.add_argument("--start", type=str, default=None, help="Start date YYYY-MM-DD (inclusive).")
    parser.add_argument("--end", type=str, default=None, help="End date YYYY-MM-DD (inclusive).")
    parser.add_argument("--use-finmind", action="store_true",
                         help="M5b: also include dates only covered by FinMind's per-stock "
                              "historical files (bridged via prepare_finmind_legacy_snapshot.py), "
                              "in addition to the official per-day snapshots. Default off "
                              "(preserves exact M5a behavior).")
    parser.add_argument("--calibrated", action="store_true",
                         help="M9: use per-sector rolling-quantile calibrated new-gainer/"
                              "continued-momentum thresholds (src/threshold_calibration.py) "
                              "instead of the fixed absolute placeholders. Default off "
                              "(preserves exact pre-M9 behavior).")
    parser.add_argument("--receipts-dir", type=str,
                         default="C:/Workspace_CN/taiwan_moneyflow_rotation/loop/evidence/fetch_receipts",
                         help="Directory to write the JSON run summary.")
    args = parser.parse_args()

    result = run_history_pipeline(start=args.start, end=args.end, use_finmind=args.use_finmind,
                                   use_calibrated_thresholds=args.calibrated)
    _write_run_receipt(args.receipts_dir, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
