"""
Official free-endpoint margin history backfill CLI.

Backfills TWSE + TPEx margin/short-sale history for a date range using the legacy
TWSE MI_MARGN / TPEx margin_bal_result.php endpoints (src/twse_tpex_margin_history.py)
instead of FinMind -- FinMind's free-tier quota is exhausted, but these two official
endpoints are free and unlimited, and (unlike the current-day-only OpenAPI endpoints
already wired into src/data_loader.py's fetch_twse_margin_all/fetch_tpex_margin_all,
which this script does NOT touch) they genuinely honor a historical date parameter.

Output files use a distinct filename prefix (twse_official_<date>.json /
tpex_official_<date>.json) so nothing here ever overwrites an existing FinMind file
(margin_<date>.json / finmind_<stock_id>.json) or any other existing data/raw/margin/
file.

Iterates every CALENDAR date in [start, end] (inclusive) -- there is no trading-day
calendar file in this project (confirmed: grep for trading_calendar/is_trading_day
across src/ and scripts/ found nothing; scripts/fetch_history_finmind.py uses the same
"try every date, treat an empty/no-data response as a non-trading day" approach) -- a
weekend/holiday is expected to return zero rows (TWSE: `stat` != "OK" with no
per-stock table; TPEx: likely a similar empty/short response) and is recorded as
`skipped_non_trading_day`, not a failure.

Resumable: if data/raw/margin/twse_official_<date>.json (or the tpex_official_
counterpart) already exists on disk, that date/market is skipped without a network
call, so re-running after an interruption is cheap and safe.

Usage:
    python scripts/backfill_margin_history.py
    python scripts/backfill_margin_history.py --start 2026-04-20 --end 2026-07-20
    python scripts/backfill_margin_history.py --no-resume   # re-fetch even if present
"""

import os
import sys
import json
import time
import argparse
import datetime
from typing import List, Optional, Dict

from loguru import logger

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from src.twse_tpex_margin_history import (
    fetch_twse_margin_history,
    fetch_tpex_margin_history,
    transform_twse_margin_rows,
    transform_tpex_margin_rows,
    build_history_envelope,
    TWSE_MARGIN_HISTORY_URL,
    TPEX_MARGIN_HISTORY_URL,
    iso_to_roc_slash,
    POLITE_DELAY_SEC,
)

DEFAULT_START = "2026-04-20"
DEFAULT_END = "2026-07-20"


def _default_data_dir() -> str:
    return "C:/Workspace_CN/taiwan_moneyflow_rotation/data"


def _default_receipts_dir() -> str:
    return "C:/Workspace_CN/taiwan_moneyflow_rotation/loop/evidence/fetch_receipts"


def _margin_dir(data_dir: str) -> str:
    path = os.path.join(data_dir, "raw", "margin")
    os.makedirs(path, exist_ok=True)
    return path


def _output_path(data_dir: str, market: str, trade_date: str) -> str:
    return os.path.join(_margin_dir(data_dir), f"{market}_official_{trade_date}.json")


def _date_range(start: str, end: str) -> List[str]:
    start_dt = datetime.datetime.strptime(start, "%Y-%m-%d").date()
    end_dt = datetime.datetime.strptime(end, "%Y-%m-%d").date()
    if end_dt < start_dt:
        return []
    out = []
    d = start_dt
    one_day = datetime.timedelta(days=1)
    while d <= end_dt:
        out.append(d.strftime("%Y-%m-%d"))
        d += one_day
    return out


def _file_exists_and_valid(path: str) -> bool:
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            env = json.load(f)
        return "payload" in env
    except Exception:
        return False


def backfill_one_date(data_dir: str, trade_date: str, skip_existing: bool = True) -> Dict[str, str]:
    """
    Backfills both TWSE and TPEx margin history for one `trade_date`. Returns a dict
    {"twse": <status>, "tpex": <status>} where status is one of:
    "saved", "skipped_existing", "skipped_non_trading_day", "failed".
    Never raises -- every fetch call is already fail-closed (returns None on error).
    """
    result = {"twse": None, "tpex": None}

    # --- TWSE ---
    twse_path = _output_path(data_dir, "twse", trade_date)
    if skip_existing and _file_exists_and_valid(twse_path):
        result["twse"] = "skipped_existing"
    else:
        rows = fetch_twse_margin_history(trade_date)
        if rows is None:
            result["twse"] = "failed"
        elif len(rows) == 0:
            result["twse"] = "skipped_non_trading_day"
        else:
            transformed = transform_twse_margin_rows(rows)
            url = (f"{TWSE_MARGIN_HISTORY_URL}?response=json&date="
                   f"{trade_date.replace('-', '')}&selectType=ALL")
            envelope = build_history_envelope("TWSE_MI_MARGN_history", url, transformed, 200)
            with open(twse_path, "w", encoding="utf-8") as f:
                json.dump(envelope, f, ensure_ascii=False, indent=2)
            result["twse"] = "saved"
            logger.info(f"Saved TWSE official margin history {trade_date} -> {twse_path} "
                        f"({len(transformed)} rows)")
        time.sleep(POLITE_DELAY_SEC)

    # --- TPEx ---
    tpex_path = _output_path(data_dir, "tpex", trade_date)
    if skip_existing and _file_exists_and_valid(tpex_path):
        result["tpex"] = "skipped_existing"
    else:
        rows = fetch_tpex_margin_history(trade_date)
        if rows is None:
            result["tpex"] = "failed"
        elif len(rows) == 0:
            result["tpex"] = "skipped_non_trading_day"
        else:
            transformed = transform_tpex_margin_rows(rows, trade_date)
            roc_date = iso_to_roc_slash(trade_date)
            url = f"{TPEX_MARGIN_HISTORY_URL}?l=zh-tw&d={roc_date}&o=json"
            envelope = build_history_envelope("TPEx_margin_bal_result_history", url, transformed, 200)
            with open(tpex_path, "w", encoding="utf-8") as f:
                json.dump(envelope, f, ensure_ascii=False, indent=2)
            result["tpex"] = "saved"
            logger.info(f"Saved TPEx official margin history {trade_date} -> {tpex_path} "
                        f"({len(transformed)} rows)")
        time.sleep(POLITE_DELAY_SEC)

    return result


def run_backfill(start: str, end: str, data_dir: Optional[str] = None,
                  skip_existing: bool = True) -> dict:
    data_dir = data_dir or _default_data_dir()
    dates = _date_range(start, end)

    summary = {
        "run_started_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "start_date": start,
        "end_date": end,
        "total_dates": len(dates),
        "twse": {"saved": 0, "skipped_existing": 0, "skipped_non_trading_day": 0, "failed": 0},
        "tpex": {"saved": 0, "skipped_existing": 0, "skipped_non_trading_day": 0, "failed": 0},
        "failed_dates": {"twse": [], "tpex": []},
    }

    for trade_date in dates:
        per_date = backfill_one_date(data_dir, trade_date, skip_existing=skip_existing)
        for market in ("twse", "tpex"):
            status = per_date[market]
            summary[market][status] += 1
            if status == "failed":
                summary["failed_dates"][market].append(trade_date)

    summary["run_finished_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return summary


def write_receipt(receipts_dir: str, summary: dict) -> str:
    os.makedirs(receipts_dir, exist_ok=True)
    path = os.path.join(receipts_dir, "margin_history_backfill_summary.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"Margin history backfill summary written to {path}")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=str, default=DEFAULT_START)
    parser.add_argument("--end", type=str, default=DEFAULT_END)
    parser.add_argument("--data-dir", type=str, default=_default_data_dir())
    parser.add_argument("--receipts-dir", type=str, default=_default_receipts_dir())
    parser.add_argument("--no-resume", action="store_true",
                         help="Force re-fetch even if a file already exists on disk.")
    args = parser.parse_args()

    result = run_backfill(args.start, args.end, data_dir=args.data_dir,
                           skip_existing=not args.no_resume)
    write_receipt(args.receipts_dir, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
