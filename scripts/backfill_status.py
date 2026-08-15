"""
Milestone 8: FinMind per-stock backfill progress truth tool.

Why this exists: `docs/open_issues_audit_2026-07-19.md` #22 / `loop/KNOWN_ISSUES.md` #7
found that `loop/evidence/fetch_receipts/finmind_backfill_summary.json` is a stale
snapshot of a single past execution, NOT the cumulative on-disk state -- the background
drip process (PID 9836) keeps adding files after any receipt is written, so anyone
trusting the receipt file underestimates real progress. This script has zero opinion
about history; it counts what is actually on disk, right now, every time it's run.

What it counts: for each category (ohlcv / institutional / margin), the per-stock
backfill files matching `finmind_<stock_id>.json` directly under
`data/raw/<category>/` (NOT the separate same-day snapshot files like
`twse_prices_<date>.json` / `margin_<date>.json`, which are a different, unrelated
artifact family). The denominator is the trading universe size: the row count of
`data/reference/stock_industry_mapping.xlsx` (1,963 as of 2026-07-19; read live, not
hardcoded, so this stays correct if the universe changes).

Additionally (added for the free-official-endpoint margin history backfill --
src/twse_tpex_margin_history.py / scripts/backfill_margin_history.py -- which replaced
FinMind for margin/short-sale HISTORY once the FinMind free-tier quota was exhausted):
reports `margin_date_sources`, a PER-DATE (not per-stock) file count for margin data,
broken out by source prefix -- `finmind` (legacy same-day `margin_<date>.json`
snapshots), `twse_official`/`tpex_official` (the new `twse_official_<date>.json` /
`tpex_official_<date>.json` files from the official free endpoints). This is a
DIFFERENT denominator (distinct trade_dates found on disk across ALL three prefixes,
not the stock universe) from the per-stock `categories.margin` section above --
the two measure genuinely different things and are both reported, never conflated.

Usage:
  python scripts/backfill_status.py                  # human-readable table to stdout
  python scripts/backfill_status.py --json            # strict JSON to stdout
  python scripts/backfill_status.py --data-dir <dir> --mapping-path <xlsx>  # override

Output (both modes) reports, per category: file count, universe size, coverage_pct,
oldest mtime, newest mtime (ISO 8601, local time); plus the margin_date_sources
breakdown described above. This script is read-only -- it never writes into data/raw,
never touches the running drip process (PID 9836 at time of writing), and never
modifies data/reference.
"""

import os
import sys
import glob
import json
import argparse
import datetime
import re
from typing import Dict, List, Optional

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

DEFAULT_DATA_DIR = "C:/Workspace_CN/taiwan_moneyflow_rotation/data"
DEFAULT_MAPPING_PATH = (
    "C:/Workspace_CN/taiwan_moneyflow_rotation/data/reference/stock_industry_mapping.xlsx"
)

CATEGORIES = ["ohlcv", "institutional", "margin"]

# Per-stock backfill files look like finmind_<stock_id>.json where stock_id is the
# TWSE/TPEx numeric-ish ticker (e.g. 2330, 00631L, 6488). Same-day snapshot files
# (twse_prices_2026-07-17.json, margin_2026-04-20.json, etc.) must NOT be counted here
# -- they're a different artifact family entirely (see module docstring).
_FINMIND_STOCK_FILE_RE = re.compile(r"^finmind_(?P<stock_id>[A-Za-z0-9]+)\.json$")

# Per-DATE margin file prefixes (data/raw/margin/ only) -- three distinct sources that
# can each legitimately hold a given trade_date's margin snapshot:
#   finmind_<date>.json               -- legacy same-day snapshot naming (pre-M5b)
#   margin_<date>.json                -- legacy same-day snapshot naming (older still)
#   twse_official_<date>.json         -- src/twse_tpex_margin_history.py (this task)
#   tpex_official_<date>.json         -- src/twse_tpex_margin_history.py (this task)
# NOTE: this is unrelated to _FINMIND_STOCK_FILE_RE above -- these are DATE-keyed
# files, not per-stock files, and only ever live under data/raw/margin/.
_MARGIN_DATE_FILE_RE = re.compile(
    r"^(?P<prefix>finmind|margin|twse_official|tpex_official)_(?P<date>\d{4}-\d{2}-\d{2})\.json$"
)
MARGIN_DATE_PREFIXES = ["finmind", "margin", "twse_official", "tpex_official"]


def _get_universe_size(mapping_path: str) -> Optional[int]:
    """
    Returns the trading-universe row count from stock_industry_mapping.xlsx, or None
    if the file doesn't exist (fail-closed: caller must not fabricate a denominator).
    """
    if not os.path.exists(mapping_path):
        return None
    try:
        df = pd.read_excel(mapping_path)
        return len(df)
    except Exception:
        return None


def _scan_category(data_dir: str, category: str) -> Dict:
    """
    Scans data/raw/<category>/ for finmind_<stock_id>.json files and returns a dict of
    raw facts (file count, stock ids, mtimes). Does no interpretation/percentage math
    here -- that's the caller's job once the universe size is known.
    """
    category_dir = os.path.join(data_dir, "raw", category)
    if not os.path.isdir(category_dir):
        return {"dir_exists": False, "file_count": 0, "stock_ids": [], "mtimes": []}

    stock_ids: List[str] = []
    mtimes: List[float] = []
    for name in os.listdir(category_dir):
        m = _FINMIND_STOCK_FILE_RE.match(name)
        if not m:
            continue
        full_path = os.path.join(category_dir, name)
        if not os.path.isfile(full_path):
            continue
        stock_ids.append(m.group("stock_id"))
        mtimes.append(os.path.getmtime(full_path))

    return {
        "dir_exists": True,
        "file_count": len(stock_ids),
        "stock_ids": sorted(stock_ids),
        "mtimes": mtimes,
    }


def _scan_margin_date_sources(data_dir: str) -> Dict:
    """
    Scans data/raw/margin/ for PER-DATE margin files across all three known source
    prefixes (finmind_<date>.json / margin_<date>.json / twse_official_<date>.json /
    tpex_official_<date>.json -- see _MARGIN_DATE_FILE_RE). Returns raw facts: per-
    prefix date sets, the union of all dates seen (any source), and dates covered by
    BOTH twse_official and tpex_official (the two new official-endpoint sources added
    by this task, useful to see paired-market coverage at a glance). Does no
    percentage math here (mirrors _scan_category's split of scan vs. interpret).
    """
    margin_dir = os.path.join(data_dir, "raw", "margin")
    if not os.path.isdir(margin_dir):
        return {"dir_exists": False, "dates_by_prefix": {p: [] for p in MARGIN_DATE_PREFIXES},
                "all_dates": [], "twse_and_tpex_official_dates": []}

    dates_by_prefix: Dict[str, set] = {p: set() for p in MARGIN_DATE_PREFIXES}
    for name in os.listdir(margin_dir):
        m = _MARGIN_DATE_FILE_RE.match(name)
        if not m:
            continue
        full_path = os.path.join(margin_dir, name)
        if not os.path.isfile(full_path):
            continue
        dates_by_prefix[m.group("prefix")].add(m.group("date"))

    all_dates = set()
    for dates in dates_by_prefix.values():
        all_dates |= dates
    twse_and_tpex_official_dates = dates_by_prefix["twse_official"] & dates_by_prefix["tpex_official"]

    return {
        "dir_exists": True,
        "dates_by_prefix": {p: sorted(d) for p, d in dates_by_prefix.items()},
        "all_dates": sorted(all_dates),
        "twse_and_tpex_official_dates": sorted(twse_and_tpex_official_dates),
    }


def _fmt_mtime(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def compute_backfill_status(
    data_dir: str = DEFAULT_DATA_DIR, mapping_path: str = DEFAULT_MAPPING_PATH
) -> Dict:
    """
    Core, side-effect-free computation. Returns a JSON-serializable dict:
    {
      "generated_at": <ISO8601>,
      "universe_size": <int or None>,
      "universe_source": <mapping_path>,
      "categories": {
        "ohlcv": {"file_count": int, "universe_size": int|None,
                   "coverage_pct": float|None, "oldest_mtime": str|None,
                   "newest_mtime": str|None, "dir_exists": bool},
        ...
      }
    }
    `coverage_pct` is None (not 0) when the universe size can't be determined --
    per governance rule "缺數據就留空...絕禁捏造數字", never fabricate a fraction
    against an unknown denominator.
    """
    universe_size = _get_universe_size(mapping_path)

    categories_out = {}
    for category in CATEGORIES:
        scan = _scan_category(data_dir, category)
        file_count = scan["file_count"]
        mtimes = scan["mtimes"]

        if universe_size and universe_size > 0:
            coverage_pct = round(100.0 * file_count / universe_size, 2)
        else:
            coverage_pct = None

        categories_out[category] = {
            "dir_exists": scan["dir_exists"],
            "file_count": file_count,
            "universe_size": universe_size,
            "coverage_pct": coverage_pct,
            "oldest_mtime": _fmt_mtime(min(mtimes)) if mtimes else None,
            "newest_mtime": _fmt_mtime(max(mtimes)) if mtimes else None,
        }

    margin_date_scan = _scan_margin_date_sources(data_dir)
    margin_date_sources = {
        "dir_exists": margin_date_scan["dir_exists"],
        "counts_by_prefix": {p: len(d) for p, d in margin_date_scan["dates_by_prefix"].items()},
        "total_distinct_dates": len(margin_date_scan["all_dates"]),
        "twse_and_tpex_official_paired_dates": len(margin_date_scan["twse_and_tpex_official_dates"]),
        "earliest_date": margin_date_scan["all_dates"][0] if margin_date_scan["all_dates"] else None,
        "latest_date": margin_date_scan["all_dates"][-1] if margin_date_scan["all_dates"] else None,
    }

    return {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "universe_size": universe_size,
        "universe_source": mapping_path,
        "categories": categories_out,
        "margin_date_sources": margin_date_sources,
    }


def _render_human(status: Dict) -> str:
    lines = []
    lines.append(f"Backfill status as of {status['generated_at']}")
    universe_size = status["universe_size"]
    if universe_size is None:
        lines.append(
            f"WARNING: universe size unavailable (mapping file not found/unreadable at "
            f"{status['universe_source']}) -- coverage_pct will show N/A for all categories."
        )
    else:
        lines.append(f"Universe size (from {status['universe_source']}): {universe_size}")
    lines.append("")
    lines.append(f"{'Category':<15}{'Files':>14}{'Coverage':>12}{'Oldest':>22}{'Newest':>22}")
    for category, c in status["categories"].items():
        coverage_str = f"{c['coverage_pct']}%" if c["coverage_pct"] is not None else "N/A"
        universe_str = f"/{c['universe_size']}" if c["universe_size"] is not None else ""
        files_str = f"{c['file_count']}{universe_str}"
        oldest = c["oldest_mtime"] or "-"
        newest = c["newest_mtime"] or "-"
        lines.append(
            f"{category:<15}{files_str:>14}{coverage_str:>12}{oldest:>22}{newest:>22}"
        )
    lines.append("")
    lines.append(
        "Note: this counts finmind_<stock_id>.json files on disk right now, not any "
        "past receipt/log file -- see loop/KNOWN_ISSUES.md for why receipt files are "
        "not trustworthy for cumulative progress."
    )

    mds = status.get("margin_date_sources")
    if mds:
        lines.append("")
        lines.append("Margin PER-DATE source coverage (data/raw/margin/, distinct trade_dates):")
        if not mds["dir_exists"]:
            lines.append("  data/raw/margin/ does not exist.")
        else:
            for prefix, count in mds["counts_by_prefix"].items():
                lines.append(f"  {prefix + '_<date>.json':<28}{count:>6} dates")
            lines.append(f"  {'total distinct dates (any source)':<28}{mds['total_distinct_dates']:>6}")
            lines.append(f"  {'twse+tpex official paired dates':<28}{mds['twse_and_tpex_official_paired_dates']:>6}")
            lines.append(f"  date range: {mds['earliest_date']} .. {mds['latest_date']}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR, help="Root data directory (contains raw/)")
    parser.add_argument(
        "--mapping-path", default=DEFAULT_MAPPING_PATH, help="Path to stock_industry_mapping.xlsx"
    )
    parser.add_argument("--json", action="store_true", help="Emit strict JSON instead of a human-readable table")
    args = parser.parse_args()

    status = compute_backfill_status(data_dir=args.data_dir, mapping_path=args.mapping_path)

    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
    else:
        print(_render_human(status))


if __name__ == "__main__":
    main()
