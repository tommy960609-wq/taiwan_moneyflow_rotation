"""
Milestone 9 bridging utility: converts the newly-backfilled official TWSE/TPEx
margin-history snapshots (data/raw/margin/twse_official_<date>.json /
tpex_official_<date>.json -- see src/twse_tpex_margin_history.py and
docs/Margin_History_Backfill_Report.md, 63 trading days 2026-04-20..2026-07-20,
near-full-market coverage: 1283 TWSE rows / 913 TPEx rows per day) into the legacy
whole-market-per-day filenames `scripts/run_daily.py::run_pipeline` actually reads
via `src/data_cleaner.py::clean_margin_data`:

  raw/margin/margin_<date>.json       <- raw/margin/twse_official_<date>.json
  raw/margin/tpex_margin_<date>.json  <- raw/margin/tpex_official_<date>.json

Why this bridge is needed (the actual gap found this session): before this script,
`run_pipeline`/`run_history_pipeline.py` had NO path that ever reads
`twse_official_*`/`tpex_official_*` -- those files were written by
`scripts/backfill_margin_history.py` but nothing downstream consumed them. The
existing `margin_<date>.json` legacy files were populated only by the FinMind
per-stock bridge (`scripts/prepare_finmind_legacy_snapshot.py`, near-zero margin
coverage: 2/1963 stocks) or the real-time official same-day fetch
(`scripts/prepare_legacy_raw_snapshot.py`, only ever available for "today"). This
script is the missing third bridge, and per the same "official priority" contract
already used by `prepare_finmind_legacy_snapshot.py`, this history-report source
DOES win over the near-empty FinMind-derived legacy file for a given date -- it is
correct here (unlike the FinMind bridge) to REPLACE an existing legacy margin file
if it currently holds vastly less data (see `--force` behavior below), because the
existing file for these historical dates is not a genuine same-day official fetch,
it's either FinMind's near-empty 2-stock fallback or entirely absent. Default
behavior is still non-destructive (skip if already present) unless `--force` is
passed, matching this project's "never silently overwrite" convention; the M9
calibration run explicitly passes `--force` (see Milestone_9 report) with the reason
disclosed there.

The payloads on disk in `twse_official_<date>.json`/`tpex_official_<date>.json` are
ALREADY fully transformed (`scripts/backfill_margin_history.py` calls
`transform_twse_margin_rows`/`transform_tpex_margin_rows` before writing via
`build_history_envelope` -- confirmed by direct inspection, not assumed): the TWSE
payload is already the list-of-lists shape `clean_margin_data`'s TWSE branch expects,
and the TPEx payload is already the list-of-dicts shape (`SecuritiesCompanyCode`/
`MarginPurchase`/... keys) its TPEx branch expects. This script is therefore a pure
copy of the `payload` key into the legacy filename -- no re-transformation, since
that already happened once at fetch time and doing it twice would be wrong (the
transform functions expect RAW rows, not already-transformed ones).

Usage:
    python scripts/prepare_official_margin_history_snapshot.py --date 2026-07-14
    python scripts/prepare_official_margin_history_snapshot.py --start 2026-04-20 --end 2026-07-20 --force
"""

import os
import sys
import json
import glob
import argparse
import datetime
from typing import Optional, List

from loguru import logger

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))


def _default_data_dir() -> str:
    return "C:/Workspace_CN/taiwan_moneyflow_rotation/data"


def discover_official_margin_dates(data_dir: str, start: Optional[str] = None,
                                    end: Optional[str] = None) -> List[str]:
    """
    Returns sorted trade_dates that have BOTH a twse_official_<date>.json and a
    tpex_official_<date>.json snapshot on disk (data/raw/margin/), optionally
    filtered to [start, end] inclusive. A date with only one side's file is excluded
    (never half-bridged silently).
    """
    margin_dir = os.path.join(data_dir, "raw", "margin")
    twse_files = glob.glob(os.path.join(margin_dir, "twse_official_*.json"))
    tpex_files = glob.glob(os.path.join(margin_dir, "tpex_official_*.json"))

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

    twse_dates = _dates_from(twse_files, "twse_official")
    tpex_dates = _dates_from(tpex_files, "tpex_official")
    both = twse_dates & tpex_dates

    if start:
        both = {d for d in both if d >= start}
    if end:
        both = {d for d in both if d <= end}
    return sorted(both)


def prepare_official_margin_history_snapshot(data_dir: str, trade_date: str,
                                              force: bool = False) -> dict:
    """
    Bridges one trade_date's official history snapshots into the legacy filenames.
    Returns {legacy_relpath: "written"|"skipped_already_present"|"source_missing"}.
    """
    margin_dir = os.path.join(data_dir, "raw", "margin")
    report = {}

    twse_src = os.path.join(margin_dir, f"twse_official_{trade_date}.json")
    tpex_src = os.path.join(margin_dir, f"tpex_official_{trade_date}.json")
    twse_dst = os.path.join(margin_dir, f"margin_{trade_date}.json")
    tpex_dst = os.path.join(margin_dir, f"tpex_margin_{trade_date}.json")

    # TWSE side
    if not os.path.exists(twse_src):
        report[f"margin/margin_{trade_date}.json"] = "source_missing"
    elif os.path.exists(twse_dst) and not force:
        report[f"margin/margin_{trade_date}.json"] = "skipped_already_present"
    else:
        with open(twse_src, "r", encoding="utf-8") as f:
            env = json.load(f)
        rows = env.get("payload") or []
        with open(twse_dst, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        report[f"margin/margin_{trade_date}.json"] = "written"

    # TPEx side
    if not os.path.exists(tpex_src):
        report[f"margin/tpex_margin_{trade_date}.json"] = "source_missing"
    elif os.path.exists(tpex_dst) and not force:
        report[f"margin/tpex_margin_{trade_date}.json"] = "skipped_already_present"
    else:
        with open(tpex_src, "r", encoding="utf-8") as f:
            env = json.load(f)
        rows = env.get("payload") or []
        with open(tpex_dst, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        report[f"margin/tpex_margin_{trade_date}.json"] = "written"

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Bridge official TWSE/TPEx margin-history snapshots to legacy run_pipeline filenames.")
    parser.add_argument("--date", type=str, default=None, help="Single trade date YYYY-MM-DD.")
    parser.add_argument("--start", type=str, default=None, help="Start date YYYY-MM-DD (inclusive).")
    parser.add_argument("--end", type=str, default=None, help="End date YYYY-MM-DD (inclusive).")
    parser.add_argument("--data-dir", type=str, default=_default_data_dir())
    parser.add_argument("--force", action="store_true",
                         help="Overwrite an existing legacy margin_<date>.json/tpex_margin_<date>.json "
                              "with this official history source (needed because the pre-existing "
                              "legacy files for these historical dates are FinMind's near-empty "
                              "2/1963-stock fallback, not a genuine full-market snapshot).")
    args = parser.parse_args()

    if args.date:
        dates = [args.date]
    else:
        dates = discover_official_margin_dates(args.data_dir, start=args.start, end=args.end)

    total_report = {}
    for d in dates:
        r = prepare_official_margin_history_snapshot(args.data_dir, d, force=args.force)
        total_report[d] = r
        for path, status in r.items():
            print(f"{status}: {path}")
    logger.info(f"prepare_official_margin_history_snapshot: bridged {len(dates)} date(s).")
