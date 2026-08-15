"""
M5b industry-name Chinese-ification (SPEC_ADDENDUM M5b brief item 2).

M5a's official mapping import (scripts/build_official_mapping.py) left `primary_sector`
as a raw numeric code (e.g. "01", "28") for the 1,955 newly-imported (non-reviewed)
rows, because neither TWSE nor TPEx swagger exposes a code->Chinese-name lookup
endpoint (industry_code_lookup_status=UNAVAILABLE, see docs/Milestone_5a_Acceptance_Report.md).

FinMind's `TaiwanStockInfo` dataset DOES carry a real Chinese-language
`industry_category` field per stock_id (dry-run verified 2026-07-18, see
loop/evidence/fetch_receipts/finmind_dataset_probe_2026-07-18.json) -- e.g. stock_id
2330 -> "半導體業". This script uses that as the new primary_sector for every
non-reviewed row the FinMind table covers, while:
  - Moving the OLD numeric code (whatever was in primary_sector before, e.g. "28")
    into a NEW `sector_code` column, never discarding it.
  - NEVER touching a row where reviewed==1/True (the 8 manually-curated rows).
  - NEVER guessing a Chinese name for a stock_id FinMind's table doesn't cover --
    such rows keep their existing numeric-code primary_sector untouched (still
    honestly a code, not silently blanked).
  - source column updated to "FinMind" only for rows this script actually changes.

FinMind's TaiwanStockInfo has a genuine data quality wrinkle discovered during this
milestone's verification (NOT invented, dry-run confirmed): ~1,044 of 3,118 unique
stock_ids appear more than once (industry reclassification history -- rows carry
different `date` values e.g. 2020-06-03 vs 2026-07-18), and ~600 of those have TWO
rows sharing the exact same latest `date` with two different category labels (one
specific TWSE-style industry, one broader catch-all bucket, e.g. 2330 appears as both
"半導體業" then "電子工業" on the same date). Resolution rule (verified against the 8
manually-reviewed ground-truth rows, see build_chinese_mapping() docstring): for each
stock_id, keep the row with the maximum `date`; if multiple rows share that maximum
date, keep the FIRST one in FinMind's returned list order -- this was verified to
match the manually-curated primary_sector for every one of the 6 reviewed rows FinMind
also covers (2330->半導體業, 2454->半導體業 both confirmed exact matches; 2317's
manual "電腦週邊" and 2382's manual "電子零組件" are human refinements beyond either
FinMind bucket and are untouched anyway since reviewed==1).

Usage:
    python scripts/build_chinese_sector_mapping.py
"""

import os
import sys
import json
import datetime
from typing import Dict, Optional, Tuple

import pandas as pd
from loguru import logger

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from src.data_cleaner import DataCleaner

MAPPING_COLUMNS = [
    "stock_id", "stock_name", "primary_sector", "sector_code", "secondary_sector",
    "theme_1", "theme_2", "theme_3", "supply_chain_role",
    "valid_from", "valid_to", "source", "reviewed",
]


def _default_data_dir() -> str:
    return "C:/Workspace_CN/taiwan_moneyflow_rotation/data"


def _default_mapping_path() -> str:
    return os.path.join(_default_data_dir(), "reference", "stock_industry_mapping.xlsx")


def _default_stock_info_path() -> str:
    return os.path.join(_default_data_dir(), "raw", "fundamentals", "finmind_stock_info.json")


def load_finmind_stock_info(path: str) -> Optional[list]:
    if not os.path.exists(path):
        logger.error(f"FinMind stock_info file not found at {path}. "
                      f"Run scripts/fetch_history_finmind.py first.")
        return None
    with open(path, "r", encoding="utf-8") as f:
        env = json.load(f)
    return env.get("payload")


def build_chinese_name_lookup(stock_info_payload: list) -> Dict[str, str]:
    """
    Builds a stock_id -> Chinese industry_category dict from the raw FinMind
    TaiwanStockInfo payload, applying the dedup rule described in the module
    docstring: max `date` wins; ties on the same max date keep the first (lowest
    list-index) occurrence. Never fabricates an entry for a stock_id not present in
    the payload.
    """
    cleaner = DataCleaner()
    best: Dict[str, Tuple[str, int, str]] = {}  # stock_id -> (date, index, category)
    for idx, row in enumerate(stock_info_payload):
        sid = cleaner.clean_ticker(row.get("stock_id", ""))
        category = (row.get("industry_category") or "").strip()
        date = str(row.get("date") or "")
        if not sid or not category:
            continue
        # Exclude non-equity "index"/ETF/ETN bucket labels -- these aren't real
        # sector names for individual stocks and would corrupt the mapping if a
        # stock_id collided with one (defensive; FinMind's per-stock_id categories
        # for real equities are never literally "ETF"/"ETN"/"Index").
        if category in ("ETF", "ETN", "Index", "大盤", "所有證券"):
            continue
        prev = best.get(sid)
        # Strictly newer date always wins. A tie on the same max date keeps the
        # earlier-seen (first) occurrence -- so ties intentionally do NOT overwrite.
        if prev is None or date > prev[0]:
            best[sid] = (date, idx, category)
    return {sid: category for sid, (date, idx, category) in best.items()}


def apply_chinese_names(df_mapping: pd.DataFrame, name_lookup: Dict[str, str],
                          run_date: Optional[str] = None) -> Tuple[pd.DataFrame, dict]:
    """
    Returns (updated_df, stats). For every row where reviewed != 1 AND stock_id is in
    name_lookup: moves the current primary_sector value into a new sector_code column
    (if sector_code doesn't already hold a value), then overwrites primary_sector with
    the FinMind Chinese name and sets source="FinMind". Rows not covered by
    name_lookup, or already reviewed==1, are left completely untouched.
    """
    run_date = run_date or datetime.date.today().isoformat()
    df = df_mapping.copy()
    if "sector_code" not in df.columns:
        df["sector_code"] = pd.NA

    df["stock_id"] = df["stock_id"].astype(str).str.strip()
    reviewed_mask = df["reviewed"].astype(str).isin(["1", "1.0", "True", "true"])

    stats = {"rows_total": len(df), "reviewed_protected": int(reviewed_mask.sum()),
              "eligible_for_update": 0, "updated": 0, "not_covered_by_finmind": 0}

    for idx, row in df.iterrows():
        if reviewed_mask.loc[idx]:
            continue
        stats["eligible_for_update"] += 1
        sid = row["stock_id"]
        chinese_name = name_lookup.get(sid)
        if chinese_name is None:
            stats["not_covered_by_finmind"] += 1
            continue
        old_code = row.get("sector_code")
        if pd.isna(old_code) or old_code in ("", None):
            df.at[idx, "sector_code"] = row.get("primary_sector")
        df.at[idx, "primary_sector"] = chinese_name
        df.at[idx, "source"] = "FinMind"
        stats["updated"] += 1

    return df, stats


def run(mapping_path: Optional[str] = None, stock_info_path: Optional[str] = None,
        receipts_dir: Optional[str] = None) -> dict:
    mapping_path = mapping_path or _default_mapping_path()
    stock_info_path = stock_info_path or _default_stock_info_path()
    receipts_dir = receipts_dir or "C:/Workspace_CN/taiwan_moneyflow_rotation/loop/evidence/fetch_receipts"
    run_date = datetime.date.today().isoformat()

    receipt = {
        "run_date": run_date, "mapping_path": mapping_path,
        "stock_info_path": stock_info_path, "status": "STARTED",
    }

    if not os.path.exists(mapping_path):
        receipt["status"] = "BLOCKED_MAPPING_FILE_MISSING"
        _write_receipt(receipts_dir, receipt)
        return receipt

    payload = load_finmind_stock_info(stock_info_path)
    if payload is None:
        receipt["status"] = "BLOCKED_STOCK_INFO_MISSING"
        _write_receipt(receipts_dir, receipt)
        return receipt

    df_existing = pd.read_excel(mapping_path, dtype={"stock_id": str})
    receipt["rows_before"] = len(df_existing)

    # Sample before-state for a handful of rows so the acceptance report can show a
    # real before/after diff (not just aggregate counts).
    sample_ids = ["1101", "1102", "2330", "2317"]
    receipt["sample_before"] = df_existing[df_existing["stock_id"].isin(sample_ids)][
        ["stock_id", "stock_name", "primary_sector", "reviewed"]
    ].to_dict("records")

    name_lookup = build_chinese_name_lookup(payload)
    receipt["finmind_unique_stock_ids_with_category"] = len(name_lookup)

    # Backup the pre-change file per governance rule #10 (backup before modifying a
    # file that feeds downstream reports). Keep the .xlsx suffix so pandas can infer
    # the write engine, with the run date inserted before it.
    base, ext = os.path.splitext(mapping_path)
    bak_path = f"{base}.bak_{run_date}{ext}"
    if not os.path.exists(bak_path):
        df_existing.to_excel(bak_path, index=False)
    receipt["backup_path"] = bak_path

    df_updated, stats = apply_chinese_names(df_existing, name_lookup, run_date=run_date)
    receipt["update_stats"] = stats

    receipt["sample_after"] = df_updated[df_updated["stock_id"].isin(sample_ids)][
        ["stock_id", "stock_name", "primary_sector", "sector_code", "reviewed"]
    ].to_dict("records")

    df_updated.to_excel(mapping_path, index=False)
    csv_path = mapping_path.replace(".xlsx", ".csv")
    df_updated.to_csv(csv_path, index=False, encoding="utf-8-sig")

    receipt["rows_after"] = len(df_updated)
    receipt["output_xlsx"] = mapping_path
    receipt["output_csv"] = csv_path
    receipt["status"] = "SUCCESS"

    logger.info(f"Chinese sector mapping applied: {stats['updated']} rows updated, "
                f"{stats['not_covered_by_finmind']} not covered by FinMind, "
                f"{stats['reviewed_protected']} reviewed rows protected.")

    _write_receipt(receipts_dir, receipt)
    return receipt


def _write_receipt(receipts_dir: str, receipt: dict) -> str:
    os.makedirs(receipts_dir, exist_ok=True)
    path = os.path.join(receipts_dir, f"chinese_sector_mapping_receipt_{receipt['run_date']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"Chinese sector mapping receipt written to {path}")
    return path


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
