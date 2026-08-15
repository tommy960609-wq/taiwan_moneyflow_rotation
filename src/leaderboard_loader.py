"""
Milestone 7 (Pitfall Pack): loader for the user-collected 36-day 台股漲幅排行 (top-300
daily gainer leaderboard) Excel reports.

Source: `Quant-Agent/台股漲幅排行/Report_YYYYMMDD.xlsx` (read-only per task instruction --
this project reads a COPY under `data/raw/reports/` instead, populated once by the M7
maker via a plain file copy, never written back to the source folder). 36 files,
2026-05-15..2026-07-16, each 300 rows x 5 columns: 排名(rank) / 代號(stock_id) /
名稱(stock_name) / 漲跌幅(return_pct, percent already, e.g. 10.0 = +10%) /
成交額(百萬)(turnover_million_twd).

Column header note: the xlsx cells decode to correct Unicode when read via
openpyxl/pandas (verified: `ord()` on the header string gives real CJK codepoints, e.g.
0x6392 0x540d = 排名) -- there is NO real mojibake in the underlying file, only in some
terminals' display of it. `scripts/run_daily.py::load_excel_leaderboard`'s existing
`try_decode_cp950` fallback is defensive and a no-op on this data; this module does not
need it and reads columns positionally (排名/代號/名稱/漲跌幅/成交額, always in that
exact order across all 36 files -- verified) to avoid any encoding-guessing entirely.

Two uses (M7 task brief):
  A. 漲停家數/連續漲停 (limit-up count / consecutive-limit-up) proxy history --
     return_pct >= LIMIT_UP_PROXY_THRESHOLD_PCT (9.5) is treated as "this stock hit the
     daily +10% limit" (a PROXY: the leaderboard only reports the CLOSING return, not
     whether the stock was locked at the limit with zero sell-side liquidity all day --
     same caveat class as backtester.py's own limit-up proxy). Aggregated per
     trade_date at both market-wide and sector level (sector join needs the project's
     own stock_industry_mapping, done by src/limit_up_history.py, not here).
  B. Cross-reconciliation vs FinMind-computed daily_return, to sanity-check this
     project's own OHLCV pipeline against an independent source the user collected by
     hand. Basis mismatch warning: the leaderboard's 漲跌幅 is PREVIOUS-CLOSE-to-CLOSE
     (standard TWSE/TPEx convention for 漲跌幅), while this project's own
     `daily_return` (src/stock_features.py / src/sector_features.py) is
     OPEN-to-CLOSE ((close-open)/open) -- a real, pre-existing, previously-disclosed
     basis mismatch (see scripts/run_daily.py M3 acceptance report notes on
     load_excel_leaderboard). Reconciliation must compute an independent prev-close
     basis return from FinMind OHLCV before comparing -- never compare the two
     mismatched bases directly (see src/leaderboard_reconciliation.py).
"""

from __future__ import annotations

import os
import glob
import re
from typing import Optional, List

import pandas as pd
from loguru import logger

LIMIT_UP_PROXY_THRESHOLD_PCT = 9.5  # disclosed proxy, not a true "was locked" flag.

# Fixed positional column order, verified identical across all 36 source files.
EXPECTED_COLUMN_COUNT = 5
COLUMN_NAMES = ["rank", "stock_id", "stock_name", "return_pct", "turnover_million_twd"]


def discover_leaderboard_files(reports_dir: str) -> List[str]:
    """Returns sorted (by date) list of Report_YYYYMMDD.xlsx paths under `reports_dir`."""
    pattern = os.path.join(reports_dir, "Report_*.xlsx")
    files = glob.glob(pattern)

    def _date_key(path: str) -> str:
        m = re.search(r"Report_(\d{8})\.xlsx$", os.path.basename(path))
        return m.group(1) if m else os.path.basename(path)

    return sorted(files, key=_date_key)


def _filename_to_iso_date(path: str) -> Optional[str]:
    m = re.search(r"Report_(\d{8})\.xlsx$", os.path.basename(path))
    if not m:
        return None
    s = m.group(1)
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"


def load_one_leaderboard(path: str) -> pd.DataFrame:
    """
    Loads one Report_YYYYMMDD.xlsx into a normalized DataFrame with columns
    [trade_date, rank, stock_id, stock_name, return_pct, turnover_million_twd].
    Returns an empty DataFrame (logged, not raised) if the file is unreadable or its
    shape doesn't match the expected 5-column layout (fail-closed: a malformed source
    file must not silently contribute wrong data to the limit-up history or
    reconciliation).
    """
    trade_date = _filename_to_iso_date(path)
    if trade_date is None:
        logger.error(f"load_one_leaderboard: cannot parse trade_date from filename {path}")
        return pd.DataFrame()

    try:
        df = pd.read_excel(path, engine="openpyxl")
    except Exception as e:
        logger.error(f"load_one_leaderboard: failed to read {path}: {e}")
        return pd.DataFrame()

    if df.shape[1] != EXPECTED_COLUMN_COUNT:
        logger.error(f"load_one_leaderboard: {path} has {df.shape[1]} columns, "
                     f"expected {EXPECTED_COLUMN_COUNT}. Skipping (fail-closed).")
        return pd.DataFrame()

    df = df.copy()
    df.columns = COLUMN_NAMES
    df["trade_date"] = trade_date
    df["stock_id"] = df["stock_id"].astype(str).str.strip()
    df["return_pct"] = pd.to_numeric(df["return_pct"], errors="coerce")
    df["turnover_million_twd"] = pd.to_numeric(df["turnover_million_twd"], errors="coerce")
    df["rank"] = pd.to_numeric(df["rank"], errors="coerce")
    return df[["trade_date", "rank", "stock_id", "stock_name", "return_pct", "turnover_million_twd"]]


def load_all_leaderboards(reports_dir: str) -> pd.DataFrame:
    """Loads and stacks every Report_YYYYMMDD.xlsx found under `reports_dir`. Files that
    fail to parse are skipped (logged), not fatal to the whole load."""
    files = discover_leaderboard_files(reports_dir)
    frames = []
    failed = []
    for path in files:
        df = load_one_leaderboard(path)
        if df.empty:
            failed.append(path)
            continue
        frames.append(df)
    logger.info(f"load_all_leaderboards: loaded {len(frames)}/{len(files)} files "
                f"({len(failed)} failed/skipped).")
    if not frames:
        return pd.DataFrame(columns=["trade_date", "rank", "stock_id", "stock_name",
                                      "return_pct", "turnover_million_twd"])
    return pd.concat(frames, ignore_index=True)


def flag_limit_up_proxy(df_leaderboard: pd.DataFrame,
                          threshold_pct: float = LIMIT_UP_PROXY_THRESHOLD_PCT) -> pd.DataFrame:
    """Adds a boolean `limit_up_proxy` column: True where return_pct >= threshold_pct.
    Purely additive -- does not filter/drop any row."""
    out = df_leaderboard.copy()
    out["limit_up_proxy"] = out["return_pct"] >= threshold_pct
    return out
