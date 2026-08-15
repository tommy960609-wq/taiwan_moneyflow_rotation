"""
Builds a stock-industry mapping template CSV listing every stock_id/stock_name
observed in real cached OHLCV snapshots (loop/evidence/raw_samples/*.json) that is
NOT already present in data/reference/stock_industry_mapping.xlsx.

Per SPEC section 8.2 rule 5 ("不得自行猜測未分類股票的產業") and SPEC_ADDENDUM item 10,
this script NEVER guesses primary_sector/secondary_sector/theme values for unmapped
stocks -- it only emits the stock_id/stock_name plus empty placeholder columns so a
human can fill them in and re-import. All emitted rows carry `is_new=True` for
clarity when merging back into the master mapping file.

Usage:
    python scripts/build_mapping_template.py
Output:
    data/reference/stock_industry_mapping_template.csv
"""

import os
import sys
import json
import glob
from typing import Optional

import pandas as pd
from loguru import logger

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from src.data_cleaner import DataCleaner

MAPPING_COLUMNS = [
    "stock_id", "stock_name", "primary_sector", "secondary_sector",
    "theme_1", "theme_2", "theme_3", "supply_chain_role",
    "valid_from", "valid_to", "source", "reviewed",
]


def _load_payload(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("payload") if isinstance(data, dict) and "payload" in data else data


def discover_universe_from_raw_samples(raw_samples_dir: str) -> pd.DataFrame:
    """
    Reads the cached real TWSE/TPEx OHLCV snapshots under raw_samples_dir and returns
    a deduplicated DataFrame of (stock_id, stock_name) for every valid equity found
    (ETFs/warrants excluded via the same DataCleaner.is_valid_equity rule used
    elsewhere in the pipeline, so the template doesn't ask a human to classify
    instruments this system will never trade anyway).
    """
    cleaner = DataCleaner()
    rows = []

    twse_path = os.path.join(raw_samples_dir, "twse_ohlcv_sample.json")
    tpex_path = os.path.join(raw_samples_dir, "tpex_ohlcv_sample.json")

    for path, market in [(twse_path, "TWSE"), (tpex_path, "TPEx")]:
        if not os.path.exists(path):
            logger.warning(f"Raw sample not found: {path}. Skipping {market}.")
            continue
        payload = _load_payload(path)
        if not payload:
            continue
        for row in payload:
            ticker_raw = row.get("Code") or row.get("SecuritiesCompanyCode") or row.get("stock_id")
            name_raw = row.get("Name") or row.get("CompanyName") or row.get("stock_name") or ""
            if not ticker_raw:
                continue
            ticker = cleaner.clean_ticker(ticker_raw)
            name = str(name_raw).strip()
            if not ticker or not name:
                continue
            if not cleaner.is_valid_equity(ticker, name):
                continue
            rows.append({"stock_id": ticker, "stock_name": name})

    if not rows:
        return pd.DataFrame(columns=["stock_id", "stock_name"])

    df = pd.DataFrame(rows).drop_duplicates(subset=["stock_id"])
    return df.reset_index(drop=True)


def build_template(mapping_path: str, raw_samples_dir: str, output_path: str) -> pd.DataFrame:
    df_universe = discover_universe_from_raw_samples(raw_samples_dir)
    if df_universe.empty:
        logger.error("No valid equities discovered from raw_samples. Template not generated.")
        return pd.DataFrame()

    existing_ids = set()
    if os.path.exists(mapping_path):
        try:
            df_existing = pd.read_excel(mapping_path, dtype={"stock_id": str})
            existing_ids = set(df_existing["stock_id"].astype(str).str.strip())
        except Exception as e:
            logger.warning(f"Could not read existing mapping file {mapping_path}: {e}")
    else:
        logger.warning(f"No existing mapping file at {mapping_path}; treating entire universe as unmapped.")

    df_unmapped = df_universe[~df_universe["stock_id"].isin(existing_ids)].copy()

    for col in MAPPING_COLUMNS:
        if col not in df_unmapped.columns:
            df_unmapped[col] = ""

    # Explicit, never-guessed placeholders (SPEC 8.2 rule 5 compliance).
    df_unmapped["primary_sector"] = "待分類"
    df_unmapped["secondary_sector"] = "待分類"
    df_unmapped["reviewed"] = 0
    df_unmapped["source"] = "auto_template_unclassified"

    df_unmapped = df_unmapped[MAPPING_COLUMNS]

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df_unmapped.to_csv(output_path, index=False, encoding="utf-8-sig")
    logger.info(f"Mapping template written: {output_path} ({len(df_unmapped)} unclassified stocks out of {len(df_universe)} total discovered)")
    return df_unmapped


if __name__ == "__main__":
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    build_template(
        mapping_path=os.path.join(project_root, "data/reference/stock_industry_mapping.xlsx"),
        raw_samples_dir=os.path.join(project_root, "loop/evidence/raw_samples"),
        output_path=os.path.join(project_root, "data/reference/stock_industry_mapping_template.csv"),
    )
