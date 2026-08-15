"""
M5a bridging utility: copies M4's `data_fetcher.py`-format raw snapshot filenames
(data/raw/<category>/{twse,tpex}_<date>.json) into the legacy filenames
`scripts/run_daily.py::run_pipeline` actually reads (a naming convention pre-dating
M4 that M4 never aligned to -- disclosed in docs/Milestone_4_Acceptance_Report.md
known-limitations as "run_pipeline was not re-run end-to-end against the new
2026-07-17 real data").

Legacy filenames expected by run_pipeline (unchanged, per "don't touch locked M1-M4
modules"):
  raw/ohlcv/twse_prices_<date>.json      <- raw/ohlcv/twse_<date>.json
  raw/ohlcv/tpex_prices_<date>.json      <- raw/ohlcv/tpex_<date>.json
  raw/institutional/inst_<date>.json     <- raw/institutional/twse_<date>.json
  raw/institutional/tpex_inst_<date>.json<- raw/institutional/tpex_<date>.json
  raw/margin/margin_<date>.json          <- raw/margin/twse_<date>.json
  raw/margin/tpex_margin_<date>.json     <- raw/margin/tpex_<date>.json

This is a pure copy (never a move, never mutates the M4-format source file) so both
naming conventions remain valid on disk. `run_pipeline` reads the `payload` key out of
whatever JSON it opens (`data.get("payload") if isinstance(data, dict) and "payload"
in data else data`), and M4's envelope already has that exact shape, so no payload
transformation is needed -- just placing a copy under the name it looks for.

Usage:
    python scripts/prepare_legacy_raw_snapshot.py --date 2026-07-17
"""

import os
import sys
import shutil
import argparse
from typing import Optional

from loguru import logger

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

# (category, m4_market_prefix) -> legacy_filename_template
_LEGACY_MAP = [
    ("ohlcv", "twse", "ohlcv/twse_prices_{date}.json"),
    ("ohlcv", "tpex", "ohlcv/tpex_prices_{date}.json"),
    ("institutional", "twse", "institutional/inst_{date}.json"),
    ("institutional", "tpex", "institutional/tpex_inst_{date}.json"),
    ("margin", "twse", "margin/margin_{date}.json"),
    ("margin", "tpex", "margin/tpex_margin_{date}.json"),
]


def prepare_legacy_snapshot(data_dir: str, trade_date: str) -> dict:
    """
    For `trade_date`, copies every M4-format raw file that exists into its legacy
    filename equivalent. Returns {legacy_relpath: "copied"|"source_missing"} so
    callers can see exactly what was and wasn't bridged -- a missing M4 source file is
    reported, never silently skipped without a trace.
    """
    report = {}
    for category, market, legacy_template in _LEGACY_MAP:
        src = os.path.join(data_dir, "raw", category, f"{market}_{trade_date}.json")
        legacy_relpath = legacy_template.format(date=trade_date)
        dst = os.path.join(data_dir, "raw", legacy_relpath)
        if not os.path.exists(src):
            report[legacy_relpath] = "source_missing"
            logger.warning(f"prepare_legacy_raw_snapshot: source not found, cannot bridge: {src}")
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        report[legacy_relpath] = "copied"
        logger.info(f"prepare_legacy_raw_snapshot: {src} -> {dst}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bridge M4 raw-snapshot filenames to legacy run_pipeline filenames.")
    parser.add_argument("--date", type=str, required=True, help="Trade date YYYY-MM-DD.")
    parser.add_argument("--data-dir", type=str,
                         default="C:/Workspace_CN/taiwan_moneyflow_rotation/data",
                         help="Project data directory.")
    args = parser.parse_args()

    result = prepare_legacy_snapshot(args.data_dir, args.date)
    for path, status in result.items():
        print(f"{status}: {path}")
