"""
M5a official industry classification auto-import (SPEC_ADDENDUM C-2).

Fetches TWSE + TPEx "company basic data" endpoints -- both verified against the
cached swagger definitions in loop/evidence/raw_samples/{twse,tpex}_swagger.json,
never recalled from memory:

  - TWSE `/opendata/t187ap03_L` (上市公司基本資料): fields `公司代號`/`公司名稱`/`產業別`.
    Verified live 2026-07-18: `產業別` is a **numeric code string** (e.g. "01"), not a
    Chinese label -- see loop/evidence/fetch_receipts/official_mapping_receipt_*.json
    for the actual sampled payload.
  - TPEx `/mopsfin_t187ap03_O` (上櫃股票基本資料): fields `SecuritiesCompanyCode`/
    `CompanyName`/`SecuritiesIndustryCode`. Same code-not-name shape per its OpenAPI
    3.0 component schema description ("產業別").

Neither TWSE's nor TPEx's swagger definitions expose a dedicated industry
code->Chinese-name lookup endpoint (searched all summaries/descriptions containing
"產業"/"類股"/"分類" in both cached swagger files -- only per-company code fields and
one unrelated aggregate table were found). Per the governing instruction ("code->name
table must come from an official endpoint or payload; if unavailable, keep the code and
record it -- never hand-author the table"), this script does NOT invent a code->name
dictionary. It keeps the raw numeric code as `primary_sector` and marks
`industry_code_lookup_status=UNAVAILABLE` in the run receipt so this limitation is
visible rather than silently papered over.

Rules enforced (per governing instructions):
  - Existing manually-reviewed rows (`reviewed`==True/1) in
    data/reference/stock_industry_mapping.xlsx are NEVER overwritten.
  - Stocks the official source doesn't cover remain "待分類" (unclassified) -- never
    guessed.
  - Fail-closed: any fetch failure leaves the existing mapping file untouched and
    records the failure in the receipt; never raises out to the caller.
  - A before/after coverage receipt is written to
    loop/evidence/fetch_receipts/official_mapping_receipt_<run_date>.json.

Usage:
    python scripts/build_official_mapping.py
"""

import os
import sys
import json
import datetime
from typing import Optional, Dict, List, Tuple

import pandas as pd
from loguru import logger

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from src.data_fetcher import fetch_with_retry, DEFAULT_HEADERS
from src.data_cleaner import DataCleaner

MAPPING_COLUMNS = [
    "stock_id", "stock_name", "primary_sector", "secondary_sector",
    "theme_1", "theme_2", "theme_3", "supply_chain_role",
    "valid_from", "valid_to", "source", "reviewed",
]

INDUSTRY_MAPPING_ENDPOINTS = {
    # Verified against loop/evidence/raw_samples/twse_swagger.json path
    # "/opendata/t187ap03_L" (上市公司基本資料).
    "twse": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
    # Verified against loop/evidence/raw_samples/tpex_swagger.json path
    # "/mopsfin_t187ap03_O" (上櫃股票基本資料), servers[0].url
    # "https://www.tpex.org.tw/openapi/v1".
    "tpex": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
}

INDUSTRY_LOOKUP_UNAVAILABLE = "UNAVAILABLE"


def _default_data_dir() -> str:
    return "C:/Workspace_CN/taiwan_moneyflow_rotation/data"


def _default_mapping_path() -> str:
    return os.path.join(_default_data_dir(), "reference", "stock_industry_mapping.xlsx")


def fetch_official_basic_data(market: str, fetch_fn=fetch_with_retry,
                               max_retries: int = 2, retry_delay_sec: float = 3.0):
    """
    Fetches the official company-basic-data endpoint for `market` ("twse" or "tpex").
    Returns (payload_list_or_None, FetchResult) -- fail-closed: caller must check for
    None before proceeding. Uses the same fetch_with_retry contract (HTTP!=200/empty/
    schema-mismatch -> failure, never raises) already established by src/data_fetcher.py.
    """
    url = INDUSTRY_MAPPING_ENDPOINTS[market]
    result = fetch_fn(url, category="industry_mapping", max_retries=max_retries,
                       retry_delay_sec=retry_delay_sec)
    if not result.success:
        logger.error(f"Official mapping fetch FAILED for {market}: {result.error}")
        return None, result
    payload = result.envelope["payload"]
    return payload, result


def normalize_twse_row(row: dict, cleaner: DataCleaner) -> Optional[dict]:
    ticker_raw = row.get("公司代號")
    name_raw = row.get("公司名稱") or row.get("公司簡稱") or ""
    industry_code = row.get("產業別")
    if not ticker_raw:
        return None
    ticker = cleaner.clean_ticker(ticker_raw)
    name = str(row.get("公司簡稱") or name_raw).strip()
    if not ticker or not name:
        return None
    return {"stock_id": ticker, "stock_name": name, "industry_code": (industry_code or "").strip()}


def normalize_tpex_row(row: dict, cleaner: DataCleaner) -> Optional[dict]:
    ticker_raw = row.get("SecuritiesCompanyCode")
    name_raw = row.get("CompanyAbbreviation") or row.get("CompanyName") or ""
    industry_code = row.get("SecuritiesIndustryCode")
    if not ticker_raw:
        return None
    ticker = cleaner.clean_ticker(ticker_raw)
    name = str(name_raw).strip()
    if not ticker or not name:
        return None
    return {"stock_id": ticker, "stock_name": name, "industry_code": (industry_code or "").strip()}


def build_official_rows(twse_payload: Optional[List[dict]], tpex_payload: Optional[List[dict]]) -> pd.DataFrame:
    """
    Normalizes both markets' official basic-data payloads into a single
    stock_id/stock_name/industry_code DataFrame (equities only -- ETFs/warrants
    filtered via the shared DataCleaner.is_valid_equity rule, same as
    scripts/build_mapping_template.py). Never guesses a sector: `industry_code` is
    carried through verbatim from the official payload (numeric code as-is).
    """
    cleaner = DataCleaner()
    rows = []
    for payload, normalizer in [(twse_payload, normalize_twse_row), (tpex_payload, normalize_tpex_row)]:
        if not payload:
            continue
        for raw_row in payload:
            norm = normalizer(raw_row, cleaner)
            if norm is None:
                continue
            if not cleaner.is_valid_equity(norm["stock_id"], norm["stock_name"]):
                continue
            rows.append(norm)

    if not rows:
        return pd.DataFrame(columns=["stock_id", "stock_name", "industry_code"])
    return pd.DataFrame(rows).drop_duplicates(subset=["stock_id"]).reset_index(drop=True)


def resolve_industry_names(df_official: pd.DataFrame,
                            code_to_name: Optional[Dict[str, str]] = None) -> Tuple[pd.DataFrame, str]:
    """
    Resolves `industry_code` -> a human-readable `primary_sector`.

    If `code_to_name` is supplied (a real mapping sourced from an official endpoint/
    payload, e.g. a future verified lookup table), codes are translated via it and any
    code missing from the table falls back to the raw code with a logged warning.

    If `code_to_name` is None (the current state -- no verified official code->name
    lookup endpoint was found in either swagger file, see module docstring), the raw
    numeric code is kept as-is in `primary_sector` and the second return value is
    INDUSTRY_LOOKUP_UNAVAILABLE, signalling callers/reports should treat primary_sector
    as a code, not a finished label, until a lookup source is found.
    """
    df = df_official.copy()
    if code_to_name:
        df["primary_sector"] = df["industry_code"].map(code_to_name).fillna(df["industry_code"])
        status = "RESOLVED"
    else:
        df["primary_sector"] = df["industry_code"]
        status = INDUSTRY_LOOKUP_UNAVAILABLE
    # An official row with a genuinely empty code (rare, e.g. holding companies not yet
    # classified) is left as "待分類" -- never fabricated.
    df.loc[df["primary_sector"].isin(["", None]) | df["primary_sector"].isna(), "primary_sector"] = "待分類"
    return df, status


def merge_into_mapping(df_existing: pd.DataFrame, df_official: pd.DataFrame,
                        source_label_twse: str = "TWSE官方", source_label_tpex: str = "TPEx官方",
                        run_date: Optional[str] = None) -> pd.DataFrame:
    """
    Merges official rows into the existing mapping table:
      - Rows already `reviewed` (True/1) in df_existing are NEVER overwritten -- kept
        verbatim regardless of what the official source says.
      - Rows not in df_existing (or present but not reviewed) are (re)written from the
        official source, with `reviewed=False`, `source`=<market>官方,
        `valid_from`=run_date.
      - Stocks with no official industry_code stay "待分類" (never guessed).
    """
    run_date = run_date or datetime.date.today().isoformat()

    if df_existing is None or df_existing.empty:
        df_existing = pd.DataFrame(columns=MAPPING_COLUMNS)
    else:
        df_existing = df_existing.copy()
        df_existing["stock_id"] = df_existing["stock_id"].astype(str).str.strip()
        df_existing["stock_id"] = df_existing["stock_id"].apply(lambda x: x[:-2] if x.endswith(".0") else x)

    reviewed_mask = df_existing.get("reviewed")
    if reviewed_mask is not None:
        reviewed_ids = set(
            df_existing.loc[df_existing["reviewed"].astype(str).isin(["1", "1.0", "True", "true"]), "stock_id"]
        )
    else:
        reviewed_ids = set()

    # Protected rows: anything already reviewed=True, kept verbatim regardless of what
    # the official source says. Also carry forward every OTHER pre-existing row
    # untouched by this run's official source (e.g. a previously-imported stock the
    # official payload didn't return this time, or a manually-added-but-not-yet-
    # reviewed row) -- the official rows below only ADD/REFRESH rows the source
    # actually covers; they must never cause an existing row to silently disappear.
    df_protected = df_existing.copy()

    official_ids_covered = set(df_official["stock_id"]) if not df_official.empty else set()

    official_rows = []
    for _, row in df_official.iterrows():
        if row["stock_id"] in reviewed_ids:
            continue  # never overwrite a manually reviewed row
        official_rows.append({
            "stock_id": row["stock_id"],
            "stock_name": row["stock_name"],
            "primary_sector": row["primary_sector"],
            "secondary_sector": "",
            "theme_1": "",
            "theme_2": "",
            "theme_3": "",
            "supply_chain_role": "",
            "valid_from": run_date,
            "valid_to": "",
            "source": row.get("_source_label", "官方"),
            "reviewed": 0,
        })
    df_official_new = pd.DataFrame(official_rows, columns=MAPPING_COLUMNS)

    # Official rows take precedence over an existing non-reviewed row for the SAME
    # stock_id (fresher classification), so drop those from df_protected before
    # concatenating; reviewed rows and rows the official source doesn't cover at all
    # are preserved as-is.
    ids_to_refresh = official_ids_covered - reviewed_ids
    df_protected = df_protected[~df_protected["stock_id"].isin(ids_to_refresh)]

    df_merged = pd.concat([df_protected, df_official_new], ignore_index=True)
    df_merged = df_merged.drop_duplicates(subset=["stock_id"], keep="first")
    return df_merged.reset_index(drop=True)


def compute_coverage(df_mapping: pd.DataFrame) -> float:
    """
    Fallback coverage: fraction of ROWS WITHIN THE MAPPING FILE ITSELF that are
    classified. This is NOT the real-world metric (a mapping file with only 8 rows,
    all classified, would show 100% here) -- it's only used when no real trading
    universe snapshot is available to compute compute_universe_coverage against
    (e.g. in isolated unit tests). Prefer compute_universe_coverage whenever an
    OHLCV universe snapshot exists.
    """
    if df_mapping is None or df_mapping.empty:
        return 0.0
    mapped = df_mapping[df_mapping["primary_sector"].notna() & (df_mapping["primary_sector"] != "待分類")]
    return len(mapped) / len(df_mapping)


def compute_universe_coverage(df_mapping: pd.DataFrame, df_universe_stock_ids: pd.Series) -> float:
    """
    Honest coverage metric: fraction of the REAL TRADING UNIVERSE (every stock_id
    observed in an actual OHLCV snapshot, e.g. today's fetch) that the mapping file
    classifies (primary_sector not empty/"待分類"). This is what the Dashboard/
    acceptance report should quote -- coverage against the mapping file's own row
    count is misleading (a tiny file can show 100% coverage of itself).
    """
    universe_ids = set(df_universe_stock_ids.astype(str).str.strip())
    if not universe_ids:
        return 0.0
    if df_mapping is None or df_mapping.empty:
        return 0.0
    classified_ids = set(
        df_mapping.loc[
            df_mapping["primary_sector"].notna() & (df_mapping["primary_sector"] != "待分類"),
            "stock_id",
        ].astype(str).str.strip()
    )
    covered = universe_ids & classified_ids
    return len(covered) / len(universe_ids)


def run(mapping_path: Optional[str] = None, receipts_dir: Optional[str] = None,
        fetch_fn=fetch_with_retry, universe_stock_ids: Optional[pd.Series] = None) -> dict:
    """
    End-to-end official mapping import. Fail-closed: any market fetch failure is
    recorded but does not block the other market or crash the run; if BOTH fail, the
    existing mapping file is left completely untouched.

    `universe_stock_ids`: optional Series of real stock_ids from an actual OHLCV
    snapshot. When supplied, coverage_before/after in the receipt are computed against
    this real trading universe (the honest metric) instead of the mapping file's own
    row count.
    """
    mapping_path = mapping_path or _default_mapping_path()
    receipts_dir = receipts_dir or "C:/Workspace_CN/taiwan_moneyflow_rotation/loop/evidence/fetch_receipts"
    run_date = datetime.date.today().isoformat()

    receipt = {
        "run_date": run_date,
        "mapping_path": mapping_path,
        "twse_fetch": None,
        "tpex_fetch": None,
        "industry_code_lookup_status": None,
        "coverage_before": None,
        "coverage_after": None,
        "rows_before": None,
        "rows_after": None,
        "official_rows_twse": 0,
        "official_rows_tpex": 0,
        "reviewed_rows_protected": 0,
        "status": "STARTED",
    }

    df_existing = pd.DataFrame(columns=MAPPING_COLUMNS)
    if os.path.exists(mapping_path):
        try:
            df_existing = pd.read_excel(mapping_path, dtype={"stock_id": str})
        except Exception as e:
            logger.error(f"Could not read existing mapping file {mapping_path}: {e}")
    receipt["rows_before"] = len(df_existing)
    coverage_metric = "universe" if universe_stock_ids is not None else "mapping_file_self"
    receipt["coverage_metric"] = coverage_metric
    receipt["coverage_before"] = (
        compute_universe_coverage(df_existing, universe_stock_ids)
        if universe_stock_ids is not None else compute_coverage(df_existing)
    )

    twse_payload, twse_result = fetch_official_basic_data("twse", fetch_fn=fetch_fn)
    receipt["twse_fetch"] = {
        "success": twse_result.success, "http_status": twse_result.http_status,
        "error": twse_result.error,
        "row_count": len(twse_payload) if twse_payload else 0,
    }

    tpex_payload, tpex_result = fetch_official_basic_data("tpex", fetch_fn=fetch_fn)
    receipt["tpex_fetch"] = {
        "success": tpex_result.success, "http_status": tpex_result.http_status,
        "error": tpex_result.error,
        "row_count": len(tpex_payload) if tpex_payload else 0,
    }

    if not twse_result.success and not tpex_result.success:
        logger.error("Both TWSE and TPEx official mapping fetches failed. "
                     "Existing mapping file left untouched (fail-closed).")
        receipt["status"] = "BLOCKED_BOTH_FETCH_FAILED"
        receipt["rows_after"] = receipt["rows_before"]
        receipt["coverage_after"] = receipt["coverage_before"]
        _write_receipt(receipts_dir, run_date, receipt)
        return receipt

    df_twse_official = build_official_rows(twse_payload, None)
    if not df_twse_official.empty:
        df_twse_official["_source_label"] = "TWSE官方"
    df_tpex_official = build_official_rows(None, tpex_payload)
    if not df_tpex_official.empty:
        df_tpex_official["_source_label"] = "TPEx官方"

    receipt["official_rows_twse"] = len(df_twse_official)
    receipt["official_rows_tpex"] = len(df_tpex_official)

    df_official_all = pd.concat([df_twse_official, df_tpex_official], ignore_index=True)
    if df_official_all.empty:
        logger.error("No usable rows parsed from official payloads. Mapping file left untouched.")
        receipt["status"] = "BLOCKED_NO_USABLE_ROWS"
        receipt["rows_after"] = receipt["rows_before"]
        receipt["coverage_after"] = receipt["coverage_before"]
        _write_receipt(receipts_dir, run_date, receipt)
        return receipt

    # No verified official code->Chinese-name lookup endpoint exists in either cached
    # swagger file (see module docstring) -- keep the raw code, mark UNAVAILABLE.
    df_resolved, lookup_status = resolve_industry_names(df_official_all, code_to_name=None)
    receipt["industry_code_lookup_status"] = lookup_status

    df_merged = merge_into_mapping(df_existing, df_resolved, run_date=run_date)

    reviewed_ids_before = set()
    if not df_existing.empty and "reviewed" in df_existing.columns:
        reviewed_ids_before = set(
            df_existing.loc[df_existing["reviewed"].astype(str).isin(["1", "1.0", "True", "true"]), "stock_id"]
        )
    receipt["reviewed_rows_protected"] = len(reviewed_ids_before)

    os.makedirs(os.path.dirname(mapping_path), exist_ok=True)
    df_merged.to_excel(mapping_path, index=False)
    # Also emit a CSV twin for consumers that prefer CSV (industry_mapper.py itself
    # only reads the xlsx via data_loader.load_industry_mapping, but keep both formats
    # in sync per the milestone brief's "csv+xlsx 雙格式" allowance).
    csv_path = mapping_path.replace(".xlsx", ".csv")
    df_merged.to_csv(csv_path, index=False, encoding="utf-8-sig")

    receipt["rows_after"] = len(df_merged)
    receipt["coverage_after"] = (
        compute_universe_coverage(df_merged, universe_stock_ids)
        if universe_stock_ids is not None else compute_coverage(df_merged)
    )
    receipt["status"] = "SUCCESS"
    receipt["output_xlsx"] = mapping_path
    receipt["output_csv"] = csv_path

    logger.info(
        f"Official mapping import complete: {receipt['rows_before']} -> {receipt['rows_after']} rows, "
        f"coverage {receipt['coverage_before']:.2%} -> {receipt['coverage_after']:.2%}, "
        f"industry_code_lookup_status={lookup_status}"
    )

    _write_receipt(receipts_dir, run_date, receipt)
    return receipt


def _write_receipt(receipts_dir: str, run_date: str, receipt: dict) -> str:
    os.makedirs(receipts_dir, exist_ok=True)
    path = os.path.join(receipts_dir, f"official_mapping_receipt_{run_date}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"Official mapping receipt written to {path}")
    return path


def load_universe_stock_ids_from_raw(data_dir: str, trade_date: str) -> Optional[pd.Series]:
    """
    Loads the real trading-universe stock_ids from an already-fetched
    data/raw/ohlcv/{twse,tpex}_<trade_date>.json snapshot pair, for computing the
    honest universe-coverage metric. Returns None (not an empty Series) if neither
    file exists, so callers can fall back to the file-only coverage metric rather than
    silently reporting 0% coverage against an empty "universe".
    """
    from src.data_cleaner import DataCleaner
    cleaner = DataCleaner()
    frames = []
    for market, prefix in [("TWSE", "twse"), ("TPEx", "tpex")]:
        path = os.path.join(data_dir, "raw", "ohlcv", f"{prefix}_{trade_date}.json")
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        payload = data.get("payload") if isinstance(data, dict) and "payload" in data else data
        df = cleaner.clean_ohlcv_data(payload, trade_date=trade_date, market_type=market)
        if not df.empty:
            frames.append(df)
    if not frames:
        return None
    df_all = pd.concat(frames, ignore_index=True)
    return df_all["stock_id"] if "stock_id" in df_all.columns else None


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Official industry classification importer (M5a).")
    parser.add_argument("--universe-date", type=str, default=None,
                         help="Trade date (YYYY-MM-DD) whose already-fetched raw OHLCV snapshot "
                              "should be used to compute the honest universe-coverage metric.")
    args = parser.parse_args()

    universe_ids = None
    if args.universe_date:
        universe_ids = load_universe_stock_ids_from_raw(_default_data_dir(), args.universe_date)
        if universe_ids is None:
            logger.warning(f"No raw OHLCV snapshot found for {args.universe_date}; "
                            f"falling back to mapping-file-self coverage metric.")

    result = run(universe_stock_ids=universe_ids)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
