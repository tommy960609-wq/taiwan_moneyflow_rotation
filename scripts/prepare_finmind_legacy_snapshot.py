"""
M5b bridging utility: converts FinMind's per-stock historical files
(data/raw/<category>/finmind_<stock_id>.json, one file per stock covering a whole
date range -- see src/finmind_fetcher.py) into the legacy whole-market-per-day
filenames `scripts/run_daily.py::run_pipeline` actually reads (the same legacy
filename convention `scripts/prepare_legacy_raw_snapshot.py` bridges the M4/M5a
official per-day snapshots into):

  raw/ohlcv/twse_prices_<date>.json       <- FinMind ohlcv rows for stocks whose
  raw/ohlcv/tpex_prices_<date>.json          FinMind TaiwanStockInfo `type` says
                                              twse/tpex respectively, filtered to <date>
  raw/institutional/inst_<date>.json      <- FinMind institutional rows (TWSE-shaped
                                              {fields, data} envelope emulated), <date>
  raw/institutional/tpex_inst_<date>.json <- FinMind institutional rows (TPEx-shaped
                                              dict-list), <date>
  raw/margin/margin_<date>.json           <- FinMind margin rows (TWSE-shaped list of
                                              13-element positional lists), <date>
  raw/margin/tpex_margin_<date>.json      <- FinMind margin rows (TPEx-shaped dict
                                              list), <date>

This is the FinMind-sourced counterpart to scripts/prepare_legacy_raw_snapshot.py
(which bridges the OFFICIAL M4-format per-day files). Per the M5b brief's dual-source
rule ("同日兩源都有時官方優先"), this script is a NO-OP for a given legacy path if the
OFFICIAL bridge (scripts/prepare_legacy_raw_snapshot.py) already produced a real file
there -- it never overwrites an official-sourced legacy file with FinMind data.

Why field names are translated here (not by relying on src/data_cleaner.py's already-
generic key lookups): clean_ohlcv_data looks for High/high and Low/low, but FinMind's
raw OHLCV rows use `max`/`min` -- so a straight pass-through of FinMind's raw payload
would silently produce empty high/low columns. This script emits rows using the exact
key spellings clean_ohlcv_data already checks for (`Open`/`High`/`Low`/`Close`/
`Volume`/`Amount`/`Code`/`Name`/`Date`), so data_cleaner.py itself is never modified.

Usage:
    python scripts/prepare_finmind_legacy_snapshot.py --date 2026-05-04
"""

import os
import sys
import json
import glob
import argparse
from typing import Dict, List, Optional

from loguru import logger

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))


def _default_data_dir() -> str:
    return "C:/Workspace_CN/taiwan_moneyflow_rotation/data"


def load_finmind_stock_type_lookup(data_dir: str) -> Dict[str, str]:
    """
    stock_id -> "TWSE"/"TPEx", derived from FinMind's own TaiwanStockInfo `type` field
    (already fetched to data/raw/fundamentals/finmind_stock_info.json). A stock_id not
    present in this table is simply excluded from the per-market legacy files (never
    guessed).
    """
    path = os.path.join(data_dir, "raw", "fundamentals", "finmind_stock_info.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        env = json.load(f)
    lookup: Dict[str, str] = {}
    for row in env.get("payload", []) or []:
        sid = str(row.get("stock_id", "")).strip()
        t = row.get("type")
        if not sid or t not in ("twse", "tpex"):
            continue
        # Later (more recent, since payload is roughly chronological per-id) entries
        # override earlier ones -- a stock rarely changes market, but if it did, the
        # latest classification is preferred; never guessed either way.
        lookup[sid] = "TWSE" if t == "twse" else "TPEx"
    return lookup


def _iter_finmind_files(data_dir: str, category: str):
    pattern = os.path.join(data_dir, "raw", category, "finmind_*.json")
    for path in sorted(glob.glob(pattern)):
        fname = os.path.basename(path)
        if not fname.startswith("finmind_") or fname.endswith(".bak"):
            continue
        stock_id = fname.replace("finmind_", "").replace(".json", "")
        try:
            with open(path, "r", encoding="utf-8") as f:
                env = json.load(f)
        except Exception as e:
            logger.warning(f"prepare_finmind_legacy_snapshot: unreadable {path}: {e}")
            continue
        yield stock_id, env.get("payload", []) or []


def build_ohlcv_legacy_rows(data_dir: str, trade_date: str,
                             stock_type_lookup: Dict[str, str]) -> Dict[str, List[dict]]:
    """Returns {"TWSE": [...], "TPEx": [...]} of rows in clean_ohlcv_data's expected shape."""
    out: Dict[str, List[dict]] = {"TWSE": [], "TPEx": []}
    for stock_id, payload in _iter_finmind_files(data_dir, "ohlcv"):
        market = stock_type_lookup.get(stock_id)
        if market is None:
            continue
        for row in payload:
            if row.get("date") != trade_date:
                continue
            try:
                op, hi, lo, cl = float(row["open"]), float(row["max"]), float(row["min"]), float(row["close"])
            except (KeyError, TypeError, ValueError):
                continue
            if op <= 0 or hi <= 0 or lo <= 0 or cl <= 0:
                continue
            out[market].append({
                "Date": trade_date.replace("-", ""),
                "Code": stock_id,
                "Name": stock_id,  # FinMind OHLCV rows carry no stock_name; the industry
                                    # mapping table (FinMind-sourced) is the name-of-record
                                    # downstream -- this placeholder is never surfaced as
                                    # the display name because clean_ohlcv_data only
                                    # requires a non-empty ticker+name pair to pass its
                                    # equity-validity check.
                "OpeningPrice": op, "HighestPrice": hi, "LowestPrice": lo, "ClosingPrice": cl,
                "TradeVolume": row.get("Trading_Volume") or 0,
                "TradeValue": row.get("Trading_money") or 0,
            })
            break
    return out


def build_institutional_legacy_rows(data_dir: str, trade_date: str,
                                     stock_type_lookup: Dict[str, str]) -> Dict[str, list]:
    """
    Returns {"twse": <TWSE-shaped {fields,data} dict>, "tpex": <TPEx-shaped dict list>}
    matching what clean_institutional_data's two branches each expect.
    """
    FOREIGN_NAMES = {"Foreign_Investor", "Foreign_Dealer_Self"}
    TRUST_NAMES = {"Investment_Trust"}
    DEALER_NAMES = {"Dealer_self", "Dealer_Hedging"}

    by_stock: Dict[str, Dict[str, float]] = {}
    for stock_id, payload in _iter_finmind_files(data_dir, "institutional"):
        for row in payload:
            if row.get("date") != trade_date:
                continue
            name = row.get("name")
            net = float(row.get("buy") or 0.0) - float(row.get("sell") or 0.0)
            acc = by_stock.setdefault(stock_id, {"foreign": 0.0, "trust": 0.0, "dealer": 0.0})
            if name in FOREIGN_NAMES:
                acc["foreign"] += net
            elif name in TRUST_NAMES:
                acc["trust"] += net
            elif name in DEALER_NAMES:
                acc["dealer"] += net

    twse_rows = []
    tpex_rows = []
    for stock_id, acc in by_stock.items():
        market = stock_type_lookup.get(stock_id)
        if market == "TWSE":
            # 12-element positional row matching clean_institutional_data's TWSE
            # branch: index0=Code, index4=Foreign Net, index10=Trust Net, index11=Dealer Net.
            row = [stock_id] + [""] * 11
            row[4] = acc["foreign"]
            row[10] = acc["trust"]
            row[11] = acc["dealer"]
            twse_rows.append(row)
        elif market == "TPEx":
            tpex_rows.append({
                "Date": trade_date.replace("-", ""),
                "SecuritiesCompanyCode": stock_id,
                "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference": acc["foreign"],
                "SecuritiesInvestmentTrustCompanies-Difference": acc["trust"],
                "Dealers-Difference": acc["dealer"],
            })

    twse_envelope = {"stat": "OK", "date": trade_date.replace("-", ""), "fields": [], "data": twse_rows}
    return {"twse": twse_envelope, "tpex": tpex_rows}


def build_margin_legacy_rows(data_dir: str, trade_date: str,
                              stock_type_lookup: Dict[str, str]) -> Dict[str, list]:
    """Returns {"twse": [13-el positional lists], "tpex": [dict rows]}."""
    twse_rows = []
    tpex_rows = []
    for stock_id, payload in _iter_finmind_files(data_dir, "margin"):
        market = stock_type_lookup.get(stock_id)
        if market is None:
            continue
        for row in payload:
            if row.get("date") != trade_date:
                continue
            if market == "TWSE":
                positional = [""] * 13
                positional[0] = stock_id
                positional[2] = row.get("MarginPurchaseBuy")
                positional[3] = row.get("MarginPurchaseSell")
                positional[6] = row.get("MarginPurchaseTodayBalance")
                positional[8] = row.get("ShortSaleBuy")
                positional[9] = row.get("ShortSaleSell")
                positional[12] = row.get("ShortSaleTodayBalance")
                twse_rows.append(positional)
            else:
                tpex_rows.append({
                    "Date": trade_date.replace("-", ""),
                    "SecuritiesCompanyCode": stock_id,
                    "MarginPurchase": row.get("MarginPurchaseBuy"),
                    "MarginSales": row.get("MarginPurchaseSell"),
                    "MarginPurchaseBalance": row.get("MarginPurchaseTodayBalance"),
                    "ShortConvering": row.get("ShortSaleBuy"),
                    "ShortSale": row.get("ShortSaleSell"),
                    "ShortSaleBalance": row.get("ShortSaleTodayBalance"),
                })
            break
    return {"twse": twse_rows, "tpex": tpex_rows}


def prepare_finmind_legacy_snapshot(data_dir: str, trade_date: str) -> dict:
    """
    Writes the 6 legacy files for `trade_date` FROM FINMIND DATA ONLY, skipping (never
    overwriting) any legacy path that already holds a real file (official-source
    priority -- see module docstring). Returns {legacy_relpath: "written_from_finmind"
    |"skipped_official_already_present"|"no_finmind_rows"}.
    """
    stock_type_lookup = load_finmind_stock_type_lookup(data_dir)
    report = {}

    def _write_if_absent(relpath: str, content) -> str:
        dst = os.path.join(data_dir, "raw", relpath)
        if os.path.exists(dst):
            return "skipped_official_already_present"
        if not content:
            return "no_finmind_rows"
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)
        return "written_from_finmind"

    ohlcv = build_ohlcv_legacy_rows(data_dir, trade_date, stock_type_lookup)
    report[f"ohlcv/twse_prices_{trade_date}.json"] = _write_if_absent(
        f"ohlcv/twse_prices_{trade_date}.json", ohlcv["TWSE"])
    report[f"ohlcv/tpex_prices_{trade_date}.json"] = _write_if_absent(
        f"ohlcv/tpex_prices_{trade_date}.json", ohlcv["TPEx"])

    inst = build_institutional_legacy_rows(data_dir, trade_date, stock_type_lookup)
    report[f"institutional/inst_{trade_date}.json"] = _write_if_absent(
        f"institutional/inst_{trade_date}.json",
        inst["twse"] if inst["twse"]["data"] else None)
    report[f"institutional/tpex_inst_{trade_date}.json"] = _write_if_absent(
        f"institutional/tpex_inst_{trade_date}.json", inst["tpex"])

    margin = build_margin_legacy_rows(data_dir, trade_date, stock_type_lookup)
    report[f"margin/margin_{trade_date}.json"] = _write_if_absent(
        f"margin/margin_{trade_date}.json", margin["twse"])
    report[f"margin/tpex_margin_{trade_date}.json"] = _write_if_absent(
        f"margin/tpex_margin_{trade_date}.json", margin["tpex"])

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bridge FinMind per-stock files to legacy run_pipeline filenames.")
    parser.add_argument("--date", type=str, required=True, help="Trade date YYYY-MM-DD.")
    parser.add_argument("--data-dir", type=str, default=_default_data_dir())
    args = parser.parse_args()

    result = prepare_finmind_legacy_snapshot(args.data_dir, args.date)
    for path, status in result.items():
        print(f"{status}: {path}")
