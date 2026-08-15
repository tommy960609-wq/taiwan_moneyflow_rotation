import os
import sys
import json
import glob
import time
import statistics
import openpyxl
import pandas as pd
import numpy as np
from typing import Optional, Dict
from loguru import logger

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from src.config_manager import ConfigManager
from src.data_loader import DataLoader
from src.data_cleaner import DataCleaner
from src.data_validator import DataValidator
from src.industry_mapper import IndustryMapper
from src.stock_features import StockFeatures
from src.sector_features import SectorFeatures
from src.sector_scoring import SectorScoring
from src.stock_scoring import StockScoring
from src.lifecycle_classifier import LifecycleClassifier
from src.signal_detector import SignalDetector
from src.report_generator import ReportGenerator
from src.backtester import resolve_sector_member_stock_ids
from src.institutional_features import InstitutionalFeatures
from src.margin_features import MarginFeatures
from src.disposition_fetcher import DispositionFetcher
from src.finmind_fetcher import FinMindFetcher
from src.observe_rankings import (
    DEFAULT_RANKING_DEPTH,
    DEFAULT_SECTOR_TOP_N,
    build_observe_rankings,
    write_observe_rankings,
)


# A single stock-level reconciliation outlier is useful for audit visibility, but it
# should not make an otherwise usable market day untradeable. Apply the DQ deduction
# only when the discrepancy is broad enough to indicate a source/basis problem.
RECONCILIATION_DQ_PENALTY_MIN_COMPARABLE_ROWS = 30
RECONCILIATION_DQ_PENALTY_MIN_DEVIATION_RATE = 0.10
# PLACEHOLDER - UNCALIBRATED: recent successful-market sample size for the coverage guard.
DEFAULT_MARKET_COVERAGE_LOOKBACK_SUCCESS_DAYS = 10
# PLACEHOLDER - UNCALIBRATED: minimum fraction of a market's recent typical universe.
DEFAULT_MARKET_MIN_COVERAGE_RATIO = 0.80


def evaluate_market_coverage(log_dir: str, trade_date: str, twse_count: int, tpex_count: int,
                             lookback_success_days: int = DEFAULT_MARKET_COVERAGE_LOOKBACK_SUCCESS_DAYS,
                             min_coverage_ratio: float = DEFAULT_MARKET_MIN_COVERAGE_RATIO) -> dict:
    """Compare each market with its recent successful-day median without a cold-start block."""
    histories = {"TWSE": [], "TPEx": []}
    for path in sorted(glob.glob(os.path.join(log_dir, "audit_*.json"))):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                audit = json.load(handle)
            if audit.get("status") != "SUCCESS" or str(audit.get("trade_date", "")) >= trade_date:
                continue
            counts = audit.get("row_counts", {})
            for market, key in (("TWSE", "prices_twse"), ("TPEx", "prices_tpex")):
                value = counts.get(key)
                if isinstance(value, (int, float)) and value > 0:
                    histories[market].append(int(value))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    result = {"status": "OK", "markets": {}}
    for market, actual in (("TWSE", twse_count), ("TPEx", tpex_count)):
        recent = histories[market][-lookback_success_days:]
        if not recent:
            result["markets"][market] = {"actual": int(actual), "baseline": None, "minimum": None, "history_days": 0}
            continue
        baseline = float(statistics.median(recent))
        minimum = baseline * min_coverage_ratio
        result["markets"][market] = {"actual": int(actual), "baseline": baseline, "minimum": minimum, "history_days": len(recent)}
        if actual < minimum:
            result["status"] = "BLOCKED_LOW_COVERAGE"
    if all(not details["history_days"] for details in result["markets"].values()):
        result["status"] = "OK_COLD_START"
    return result


def _reconciliation_requires_dq_penalty(reconcile_log: dict) -> bool:
    """Return whether a leaderboard warning represents a material data problem.

    ``reconcile_with_leaderboard`` keeps every individual mismatch as a warning for
    audit purposes. The run-level DQ score is reduced only when at least 30 rows were
    comparable and >=10% exceeded the 0.5 percentage-point tolerance. If the summary
    is unavailable, fail closed and preserve the historical penalty behavior.
    """
    if not reconcile_log or reconcile_log.get("status") != "WARNING_HIGH_DEVIATION":
        return False
    summary = reconcile_log.get("summary")
    if not isinstance(summary, dict):
        return True
    compared = summary.get("rows_with_finmind_comparison")
    deviation_rate = summary.get("pct_exceeding_threshold")
    if compared is None or deviation_rate is None:
        return True
    try:
        return (
            int(compared) >= RECONCILIATION_DQ_PENALTY_MIN_COMPARABLE_ROWS
            and float(deviation_rate) >= RECONCILIATION_DQ_PENALTY_MIN_DEVIATION_RATE
        )
    except (TypeError, ValueError):
        return True


def _processed_dir(data_dir: str) -> str:
    path = f"{data_dir}/processed"
    os.makedirs(path, exist_ok=True)
    return path


def _load_stock_history(data_dir: str, up_to_date: str) -> pd.DataFrame:
    """
    Rebuilds a stacked multi-day stock-level price history strictly from previously
    persisted `data/processed/stock_features_*.csv` snapshots dated on or before
    `up_to_date`. This enforces the no-future-leakage contract structurally: a run for
    trade_date T can only ever see files named with dates <= T, since files for T+n
    are (by construction of this pipeline) written only after processing day T+n.
    """
    pattern = f"{data_dir}/processed/stock_features_*.csv"
    frames = []
    for path in sorted(glob.glob(pattern)):
        fname = os.path.basename(path)
        file_date = fname.replace("stock_features_", "").replace(".csv", "")
        if file_date > up_to_date:
            continue
        try:
            df = pd.read_csv(path, dtype={"stock_id": str})
            frames.append(df)
        except Exception as e:
            logger.warning(f"Could not read processed history file {path}: {e}")
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _load_disposition_ids_for_date(data_dir: str, trade_date: str) -> dict:
    """
    M7: reads whichever disposition/attention raw-endpoint files (written by
    `src.disposition_fetcher.DispositionFetcher.fetch_today_list`, filename pattern
    data/raw/disposition/<endpoint_key>_<date>.json) already exist on disk for
    `trade_date`, and reconstructs the same consolidated {stock_id: kind} shape
    `fetch_today_list` returns -- WITHOUT making a live network call from inside the
    pipeline (fetch is a separate, explicit step; run_pipeline stays read-only w.r.t.
    external data sources it doesn't already own, matching every other data source's
    "fetch is a distinct script" convention in this project).

    Fail-closed: if none of the 5 endpoint files exist for `trade_date` (e.g. this is a
    historical backfill day, or the fetch step was never run for today), returns an
    empty dict -- the pipeline proceeds with disposition_flag="N/A" for every stock
    rather than crashing or fabricating a clean list. This is NOT the same as "confirmed
    no disposition stocks today"; report_generator surfaces the distinction.
    """
    from src.disposition_fetcher import DISPOSITION_ENDPOINTS, DispositionFetcher

    disp_dir = os.path.join(data_dir, "raw", "disposition")
    consolidated: Dict[str, dict] = {}
    any_file_found = False
    for key, spec in DISPOSITION_ENDPOINTS.items():
        path = os.path.join(disp_dir, f"{key}_{trade_date}.json")
        if not os.path.exists(path):
            continue
        any_file_found = True
        try:
            with open(path, "r", encoding="utf-8") as f:
                envelope = json.load(f)
        except Exception as e:
            logger.warning(f"_load_disposition_ids_for_date: unreadable {path}: {e}")
            continue
        for row in envelope.get("payload", []) or []:
            stock_id = DispositionFetcher._extract_stock_id(row, spec)
            if not stock_id:
                continue
            kind = spec["kind"]
            if stock_id not in consolidated:
                consolidated[stock_id] = {"kind": kind, "sources": [key]}
            else:
                consolidated[stock_id]["sources"].append(key)
                if kind == "disposition":
                    consolidated[stock_id]["kind"] = "disposition"
    return {"stocks": consolidated, "data_available": any_file_found}


def _load_sector_history(data_dir: str, up_to_date: str) -> pd.DataFrame:
    pattern = f"{data_dir}/processed/sector_features_*.csv"
    frames = []
    for path in sorted(glob.glob(pattern)):
        fname = os.path.basename(path)
        file_date = fname.replace("sector_features_", "").replace(".csv", "")
        if file_date > up_to_date:
            continue
        try:
            df = pd.read_csv(path)
            frames.append(df)
        except Exception as e:
            logger.warning(f"Could not read processed sector history file {path}: {e}")
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _load_generic_history(data_dir: str, prefix: str, up_to_date: str, dtype: Optional[dict] = None) -> pd.DataFrame:
    """
    Generic version of _load_stock_history/_load_sector_history for any
    `data/processed/<prefix>_<date>.csv` snapshot family (used here for
    institutional_features_*.csv and margin_features_*.csv), same strictly-<=
    up_to_date no-future-leakage contract.
    """
    pattern = f"{data_dir}/processed/{prefix}_*.csv"
    frames = []
    for path in sorted(glob.glob(pattern)):
        fname = os.path.basename(path)
        file_date = fname.replace(f"{prefix}_", "").replace(".csv", "")
        if file_date > up_to_date:
            continue
        try:
            df = pd.read_csv(path, dtype=dtype)
            frames.append(df)
        except Exception as e:
            logger.warning(f"Could not read processed history file {path}: {e}")
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)

def _attach_top5_stocks(df_sectors: pd.DataFrame, df_scored_stocks: pd.DataFrame) -> pd.DataFrame:
    """
    Adds a `top5_stocks` column to the sector-level frame: a Chinese comma-joined
    "stock_name(stock_id)" string of the sector's top-5 stocks by stock_score, used by
    the New Gainer / Continued Momentum report sheets (SPEC Chapter 21 "前五名個股"
    requirement). Both primary and theme sectors use the authoritative backtester
    membership rule, so theme sectors can list stocks that belong to more than one
    theme. Sectors with no scored stocks or no resolved constituents get "N/A"
    rather than a fabricated list.
    """
    if df_sectors.empty:
        return df_sectors
    df = df_sectors.copy()
    if df_scored_stocks is None or df_scored_stocks.empty or "stock_score" not in df_scored_stocks.columns:
        df["top5_stocks"] = "N/A"
        return df

    if "stock_id" not in df_scored_stocks.columns or "sector_name" not in df.columns:
        df["top5_stocks"] = "N/A"
        return df

    if "sector_type" not in df.columns:
        logger.warning("_attach_top5_stocks: sector_type is missing; falling back to primary membership")

    top5_by_sector = {}
    for _, sector_row in df.iterrows():
        sector_name = sector_row.get("sector_name")
        if pd.isna(sector_name):
            continue
        sector_type = sector_row.get("sector_type", "primary") if "sector_type" in df.columns else "primary"
        if pd.isna(sector_type) or not str(sector_type).strip():
            sector_type = "primary"
        try:
            member_ids = resolve_sector_member_stock_ids(
                str(sector_name), str(sector_type), df_scored_stocks
            )
            member_id_set = set(member_ids)
            members = df_scored_stocks[
                df_scored_stocks["stock_id"].astype(str).isin(member_id_set)
            ]
            top5 = members.sort_values("stock_score", ascending=False, na_position="last").head(5)
            names = [
                f"{row.get('stock_name', '')}({row.get('stock_id', '')})"
                for _, row in top5.iterrows()
            ]
            top5_by_sector[(sector_name, str(sector_type))] = "、".join(names) if names else "N/A"
        except Exception as exc:
            logger.warning(f"_attach_top5_stocks: could not resolve {sector_name}: {exc}")
            top5_by_sector[(sector_name, str(sector_type))] = "N/A"

    def _lookup_top5(row):
        sector_type = row.get("sector_type", "primary") if "sector_type" in df.columns else "primary"
        if pd.isna(sector_type) or not str(sector_type).strip():
            sector_type = "primary"
        return top5_by_sector.get((row.get("sector_name"), str(sector_type)), "N/A")

    df["top5_stocks"] = df.apply(_lookup_top5, axis=1)
    return df


def load_excel_leaderboard(report_date: str, leaderboard_dir: Optional[str] = None) -> pd.DataFrame:
    """
    Loads the external Report_<YYYYMMDD>.xlsx leaderboard file (if any) used as a
    cross-check on daily scoring. `leaderboard_dir` is the directory to glob-search
    recursively; defaults to `reconciliation.leaderboard_dir` from config (M8: made
    configurable, was hardcoded pre-M8 -- default value preserves the exact pre-M8
    path, so behavior is unchanged for existing deployments/tests unless the config
    key is overridden). If the directory doesn't exist, reconciliation is silently
    skipped (logged) rather than blocking the pipeline.
    """
    if leaderboard_dir is None:
        leaderboard_dir = ConfigManager().get(
            "reconciliation.leaderboard_dir", "C:/Workspace_CN/Quant-Agent"
        )
    if not os.path.isdir(leaderboard_dir):
        logger.info(
            f"Leaderboard directory not found ({leaderboard_dir}); skipping reconciliation for {report_date}"
        )
        return pd.DataFrame()

    pattern = f"{leaderboard_dir}/**/Report_{report_date.replace('-', '')}.xlsx"
    files = glob.glob(pattern, recursive=True)
    if not files:
        logger.info(f"No historical leaderboard report found for date {report_date}")
        return pd.DataFrame()
        
    path = files[0]
    try:
        wb = openpyxl.load_workbook(path)
        ws = wb.active
        
        def try_decode_cp950(s):
            if not isinstance(s, str):
                return s
            try:
                candidate = s.encode('latin1').decode('cp950')
                if any(c in candidate for c in ["排名", "代號", "名稱", "漲跌幅", "成交額"]):
                    return candidate
            except:
                pass
            return s
            
        rows = list(ws.iter_rows(values_only=True))
        if len(rows) < 2:
            return pd.DataFrame()
            
        headers = [try_decode_cp950(h) for h in rows[0]]
        data = rows[1:]
        
        df = pd.DataFrame(data, columns=headers)
        df = df.rename(columns={
            "代號": "stock_id",
            "漲跌幅": "return_pct",
            "名稱": "stock_name"
        })
        return df
    except Exception as e:
        logger.error(f"Error loading leaderboard Excel: {e}")
        return pd.DataFrame()

def _setup_run_logger(output_dir: str, trade_date: str) -> int:
    """
    Adds a loguru file sink at outputs/logs/run_<trade_date>.log for this pipeline run
    (key steps, row counts, quality scores). Returns the sink id so callers could
    remove it later if needed; callers that don't care may ignore the return value.
    """
    log_dir = os.path.join(output_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"run_{trade_date}.log")
    return logger.add(log_path, level="INFO", encoding="utf-8", mode="w")


def _write_audit_summary(output_dir: str, trade_date: str, audit: dict) -> str:
    """
    Writes a structured JSON audit summary (input files, row counts, output files,
    elapsed time) for this run to outputs/logs/audit_<trade_date>.json.
    """
    log_dir = os.path.join(output_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    audit_path = os.path.join(log_dir, f"audit_{trade_date}.json")
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2, default=str)
    return audit_path


def _load_finmind_stock_type_lookup(data_dir: str) -> Dict[str, str]:
    """
    stock_id -> "TWSE"/"TPEx", read from the already-fetched
    data/raw/fundamentals/finmind_stock_info.json (FinMind's TaiwanStockInfo dataset,
    `type` field: "twse"/"tpex"/"emerging"). Same lookup shape/semantics as
    scripts/prepare_finmind_legacy_snapshot.py::load_finmind_stock_type_lookup (kept as
    a separate copy rather than importing that script, since it's a script entrypoint
    module, not a src/ library -- avoids depending on scripts/ internals from
    scripts/run_daily.py). A stock_id absent from this file, or the file itself being
    absent, simply yields an empty/partial lookup -- callers must treat "market
    unknown for this stock_id" as "excluded", never guessed.
    """
    path = os.path.join(data_dir, "raw", "fundamentals", "finmind_stock_info.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            env = json.load(f)
    except Exception as e:
        logger.warning(f"_load_finmind_stock_type_lookup: unreadable {path}: {e}")
        return {}
    lookup: Dict[str, str] = {}
    for row in env.get("payload", []) or []:
        sid = str(row.get("stock_id", "")).strip()
        t = row.get("type")
        if not sid or t not in ("twse", "tpex"):
            continue
        lookup[sid] = "TWSE" if t == "twse" else "TPEx"
    return lookup


def _fetch_finmind_ohlcv_fallback(data_dir: str, trade_date: str, market_type: str,
                                   cleaner: DataCleaner) -> pd.DataFrame:
    """
    Same-day OHLCV fallback (SPEC_ADDENDUM: "官方 STOCK_DAY_ALL 延遲時改用 FinMind
    補當日"). Only called when the official endpoint's data for `market_type` was
    empty or date-mismatched for `trade_date` (the caller already ran the official
    path and found it wanting -- this function never runs before that check, so
    official data always wins when it's actually available: "官方優先不變").

    Universe: the industry-mapping reference table's stock_ids (the pipeline's actual
    reporting universe), filtered down to whichever of those FinMind's own
    TaiwanStockInfo classifies as `market_type`. A stock_id with no known FinMind
    market classification is excluded (never guessed into either bucket).

    Fail-closed per the same DATE_MISMATCH discipline as src/data_fetcher.py: each
    fetched row's own `date` field must equal `trade_date` exactly (enforced inside
    FinMindFetcher.fetch_today_ohlcv_for_universe) -- a FinMind response carrying a
    stale date (e.g. FinMind also hasn't ingested today yet) is dropped, never used to
    silently satisfy the market-non-empty check with old prices under today's label.

    Returns an empty DataFrame (never raises) on: no FinMind token, no mapping stocks
    classified as `market_type`, or FinMind itself returning nothing usable -- in every
    case the caller's pre-existing BLOCKED_MISSING_MARKET fail-closed path is what
    ultimately fires, unchanged.
    """
    mapping_path = f"{data_dir}/reference/stock_industry_mapping.xlsx"
    if not os.path.exists(mapping_path):
        return pd.DataFrame()
    try:
        df_mapping_ids = pd.read_excel(mapping_path, dtype={"stock_id": str})
    except Exception as e:
        logger.warning(f"_fetch_finmind_ohlcv_fallback: could not read mapping table: {e}")
        return pd.DataFrame()

    type_lookup = _load_finmind_stock_type_lookup(data_dir)
    if not type_lookup:
        logger.warning("_fetch_finmind_ohlcv_fallback: no FinMind stock_info type lookup on disk "
                        "(data/raw/fundamentals/finmind_stock_info.json missing/empty); cannot "
                        "determine which stocks belong to this market, skipping fallback.")
        return pd.DataFrame()

    universe = [
        sid for sid in df_mapping_ids["stock_id"].astype(str).unique()
        if type_lookup.get(sid) == market_type
    ]
    if not universe:
        logger.warning(f"_fetch_finmind_ohlcv_fallback: no mapped stocks classified as "
                        f"{market_type} in FinMind stock_info; skipping fallback.")
        return pd.DataFrame()

    fetcher = FinMindFetcher(data_dir=data_dir)
    if not fetcher.token_present:
        logger.warning("_fetch_finmind_ohlcv_fallback: no FinMind API token found "
                        "(FINMIND_API_KEY/FINMIND_API_TOKEN); skipping fallback.")
        return pd.DataFrame()

    logger.info(f"FinMind OHLCV fallback triggered for {market_type}: official data empty/stale "
                f"for {trade_date}. Fetching {len(universe)} stocks live from FinMind.")
    result = fetcher.fetch_today_ohlcv_for_universe(universe, trade_date)
    logger.info(f"FinMind OHLCV fallback for {market_type}: requested={result['requested']} "
                f"succeeded={result['succeeded']} date_mismatch={result['date_mismatch']} "
                f"failed={result['failed']} rate_limited={result['rate_limited']} "
                f"stopped_early={result['stopped_early']} elapsed_sec={result['elapsed_sec']}")

    if not result["rows"]:
        return pd.DataFrame()

    # Translate FinMind's {date, stock_id, open, high, low, close, volume, turnover}
    # rows into the exact key spellings DataCleaner.clean_ohlcv_data already checks
    # for, so no changes to data_cleaner.py are needed (same technique as
    # scripts/prepare_finmind_legacy_snapshot.py::build_ohlcv_legacy_rows) -- and so
    # the row still passes back through the SAME date-consistency guard
    # (clean_ohlcv_data drops any row whose own Date != trade_date) as official data.
    legacy_rows = [
        {
            "Date": trade_date.replace("-", ""),
            "Code": row["stock_id"],
            "Name": row["stock_id"],  # FinMind OHLCV carries no stock_name; the
                                       # industry mapping table is the name-of-record
                                       # downstream (see IndustryMapper), so this
                                       # placeholder is never surfaced to the report.
            "OpeningPrice": row["open"], "HighestPrice": row["high"],
            "LowestPrice": row["low"], "ClosingPrice": row["close"],
            "TradeVolume": row["volume"], "TradeValue": row["turnover"],
        }
        for row in result["rows"]
    ]
    return cleaner.clean_ohlcv_data(legacy_rows, trade_date=trade_date, market_type=market_type)


def run_pipeline(trade_date: str, prev_date: Optional[str] = None,
                  use_calibrated_thresholds: bool = False):
    run_start_time = time.time()
    config = ConfigManager()
    data_dir = config.get("system.data_dir")
    output_dir = config.get("system.output_dir", "C:/Workspace_CN/taiwan_moneyflow_rotation/outputs")

    log_sink_id = _setup_run_logger(output_dir, trade_date)
    audit = {
        "trade_date": trade_date, "prev_date": prev_date,
        "input_files": [], "row_counts": {}, "output_files": [],
        "status": "STARTED", "elapsed_sec": None,
    }

    logger.info(f"Starting Taiwan Moneyflow Rotation Pipeline for: {trade_date}")

    loader = DataLoader()
    cleaner = DataCleaner()
    validator = DataValidator()

    mapping_path = f"{data_dir}/reference/stock_industry_mapping.xlsx"
    audit["input_files"].append(mapping_path)
    df_mapping = loader.load_industry_mapping(mapping_path)
    if df_mapping is None or df_mapping.empty:
        logger.error("Mapping reference stock_industry_mapping.xlsx not found. Pipeline blocked.")
        audit["status"] = "BLOCKED_NO_MAPPING"
        audit["elapsed_sec"] = round(time.time() - run_start_time, 2)
        _write_audit_summary(output_dir, trade_date, audit)
        logger.remove(log_sink_id)
        return audit

    mapper = IndustryMapper(df_mapping)
    
    # 1. Load Daily Prices
    local_price_path = f"{data_dir}/raw/ohlcv/prices_{trade_date}.json"
    local_twse_price_path = f"{data_dir}/raw/ohlcv/twse_prices_{trade_date}.json"
    local_tpex_price_path = f"{data_dir}/raw/ohlcv/tpex_prices_{trade_date}.json"
    
    raw_twse_prices = None
    raw_tpex_prices = None
    df_prices = pd.DataFrame()
    
    if os.path.exists(local_price_path):
        logger.info(f"Loading local combined price snapshot from {local_price_path}")
        with open(local_price_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            raw_prices = data.get("payload") if isinstance(data, dict) and "payload" in data else data
        df_prices = cleaner.clean_ohlcv_data(raw_prices, trade_date=trade_date)
    else:
        # Load from separate market paths
        if os.path.exists(local_twse_price_path):
            with open(local_twse_price_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                raw_twse_prices = data.get("payload") if isinstance(data, dict) and "payload" in data else data
        else:
            raw_twse_prices = loader.fetch_twse_ohlcv_all()
            
        if os.path.exists(local_tpex_price_path):
            with open(local_tpex_price_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                raw_tpex_prices = data.get("payload") if isinstance(data, dict) and "payload" in data else data
        else:
            raw_tpex_prices = loader.fetch_tpex_ohlcv_all()
            
        df_twse = cleaner.clean_ohlcv_data(raw_twse_prices, trade_date=trade_date, market_type="TWSE") if raw_twse_prices else pd.DataFrame()
        df_tpex = cleaner.clean_ohlcv_data(raw_tpex_prices, trade_date=trade_date, market_type="TPEx") if raw_tpex_prices else pd.DataFrame()
        df_prices = pd.concat([df_twse, df_tpex], ignore_index=True)
        
    # B4 compliance: Fail Closed if either market is empty or date mismatched.
    # `df_prices` can be a zero-column DataFrame here (e.g. pd.concat of two empty
    # frames when both the legacy bridge files and the live-fallback fetch return
    # nothing), in which case `market_type` doesn't exist yet -- guard the column
    # access itself rather than let a KeyError escape before the intended
    # fail-closed BLOCKED_MISSING_MARKET check below can run.
    if "market_type" not in df_prices.columns:
        df_twse_chk = pd.DataFrame()
        df_tpex_chk = pd.DataFrame()
    else:
        df_twse_chk = df_prices[df_prices["market_type"] == "TWSE"]
        df_tpex_chk = df_prices[df_prices["market_type"] == "TPEx"]

    audit["row_counts"]["prices_twse_official"] = len(df_twse_chk)
    audit["row_counts"]["prices_tpex_official"] = len(df_tpex_chk)
    price_source_twse = "official" if not df_twse_chk.empty else "missing"
    price_source_tpex = "official" if not df_tpex_chk.empty else "missing"

    # FinMind same-day fallback DISABLED (2026-07-20, user request: FinMind quota
    # exhausted). Per-stock same-day fetch consumed too much quota for too little
    # coverage (~130/1079 before HTTP 402). Official data only: if a market's
    # official same-day data is empty/date-mismatched, the pipeline now BLOCKs
    # (fail-closed) and the report is produced the next day once the official
    # endpoint catches up. The `_fetch_finmind_ohlcv_fallback` helper is retained
    # but no longer called, so it can be re-enabled later without re-implementing.

    audit["row_counts"]["prices_twse"] = len(df_twse_chk)
    audit["row_counts"]["prices_tpex"] = len(df_tpex_chk)
    audit["price_source_twse"] = price_source_twse
    audit["price_source_tpex"] = price_source_tpex
    if df_twse_chk.empty or df_tpex_chk.empty:
        logger.error(f"Fail-Closed: Missing price rows for a market. TWSE count={len(df_twse_chk)}, TPEx count={len(df_tpex_chk)}. Pipeline blocked.")
        audit["status"] = "BLOCKED_MISSING_MARKET"
        audit["price_source_twse"] = "missing" if df_twse_chk.empty else price_source_twse
        audit["price_source_tpex"] = "missing" if df_tpex_chk.empty else price_source_tpex
        audit["elapsed_sec"] = round(time.time() - run_start_time, 2)
        _write_audit_summary(output_dir, trade_date, audit)
        logger.remove(log_sink_id)
        return audit

    coverage_decision = evaluate_market_coverage(
        os.path.join(output_dir, "logs"), trade_date, len(df_twse_chk), len(df_tpex_chk),
        lookback_success_days=int(config.get(
            "market_coverage.recent_success_days", DEFAULT_MARKET_COVERAGE_LOOKBACK_SUCCESS_DAYS
        )),
        min_coverage_ratio=float(config.get(
            "market_coverage.min_coverage_ratio", DEFAULT_MARKET_MIN_COVERAGE_RATIO
        )),
    )
    audit["market_coverage"] = coverage_decision
    if coverage_decision["status"] == "OK_COLD_START":
        logger.warning("Market coverage guard has no successful-audit baseline; retaining existing non-empty-market behavior.")
    elif coverage_decision["status"] == "BLOCKED_LOW_COVERAGE":
        logger.error(f"Fail-Closed: market coverage below recent-success baseline: {coverage_decision['markets']}")
        audit["status"] = "BLOCKED_LOW_COVERAGE"
        audit["elapsed_sec"] = round(time.time() - run_start_time, 2)
        _write_audit_summary(output_dir, trade_date, audit)
        logger.remove(log_sink_id)
        return audit
        
    # 2. Load Institutional Flow
    local_twse_inst_path = f"{data_dir}/raw/institutional/inst_{trade_date}.json"
    local_tpex_inst_path = f"{data_dir}/raw/institutional/tpex_inst_{trade_date}.json"
    
    raw_twse_inst = None
    raw_tpex_inst = None
    
    if os.path.exists(local_twse_inst_path):
        with open(local_twse_inst_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            raw_twse_inst = data.get("payload") if isinstance(data, dict) and "payload" in data else data
    else:
        date_str = trade_date.replace("-", "")
        raw_twse_inst = loader.fetch_twse_institutional_all(date_str)
        
    if os.path.exists(local_tpex_inst_path):
        with open(local_tpex_inst_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            raw_tpex_inst = data.get("payload") if isinstance(data, dict) and "payload" in data else data
    else:
        raw_tpex_inst = loader.fetch_tpex_institutional_all()
        
    # Normalize institutional flow (B1 compliance)
    df_inst = cleaner.clean_institutional_data(raw_twse_inst, raw_tpex_inst, trade_date=trade_date)
    
    # 3. Load Margin Balance (B3 compliance)
    local_twse_margin_path = f"{data_dir}/raw/margin/margin_{trade_date}.json"
    local_tpex_margin_path = f"{data_dir}/raw/margin/tpex_margin_{trade_date}.json"
    
    raw_twse_margin = None
    raw_tpex_margin = None
    
    if os.path.exists(local_twse_margin_path):
        with open(local_twse_margin_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            raw_twse_margin = data.get("payload") if isinstance(data, dict) and "payload" in data else data
    else:
        raw_twse_margin = loader.fetch_twse_margin_all()
        
    if os.path.exists(local_tpex_margin_path):
        with open(local_tpex_margin_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            raw_tpex_margin = data.get("payload") if isinstance(data, dict) and "payload" in data else data
    else:
        raw_tpex_margin = loader.fetch_tpex_margin_all()
        
    # Normalize margin balances (B3 compliance)
    df_margin = cleaner.clean_margin_data(raw_twse_margin, raw_tpex_margin, trade_date=trade_date)
    audit["row_counts"]["institutional"] = len(df_inst)
    audit["row_counts"]["margin"] = len(df_margin)

    # 4. Industry Mapping & Coverage
    df_mapped = mapper.map_dataframe(df_prices)
    coverage = mapper.calculate_coverage(df_mapped)
    audit["row_counts"]["mapping_coverage_pct"] = coverage

    # 5. Load Previous Prices
    # Leaderboard return_pct is previous-close-to-close, so reconciliation must have
    # the previous trading day's close. The same df_prev is later reused for rank
    # improvement, keeping both consumers on one loaded snapshot.
    df_prev = pd.DataFrame()
    if prev_date:
        prev_combined = f"{data_dir}/raw/ohlcv/prices_{prev_date}.json"
        prev_twse_path = f"{data_dir}/raw/ohlcv/twse_prices_{prev_date}.json"
        prev_tpex_path = f"{data_dir}/raw/ohlcv/tpex_prices_{prev_date}.json"

        prev_raw = None
        if os.path.exists(prev_combined):
            with open(prev_combined, "r", encoding="utf-8") as f:
                data = json.load(f)
                prev_raw = data.get("payload") if isinstance(data, dict) and "payload" in data else data
            df_prev = cleaner.clean_ohlcv_data(prev_raw, trade_date=prev_date)
        else:
            prev_twse_raw = None
            prev_tpex_raw = None
            if os.path.exists(prev_twse_path):
                with open(prev_twse_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    prev_twse_raw = data.get("payload") if isinstance(data, dict) and "payload" in data else data
            if os.path.exists(prev_tpex_path):
                with open(prev_tpex_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    prev_tpex_raw = data.get("payload") if isinstance(data, dict) and "payload" in data else data

            df_prev_twse = cleaner.clean_ohlcv_data(prev_twse_raw, trade_date=prev_date, market_type="TWSE") if prev_twse_raw else pd.DataFrame()
            df_prev_tpex = cleaner.clean_ohlcv_data(prev_tpex_raw, trade_date=prev_date, market_type="TPEx") if prev_tpex_raw else pd.DataFrame()
            df_prev = pd.concat([df_prev_twse, df_prev_tpex], ignore_index=True)
    audit["row_counts"]["previous_prices"] = len(df_prev)

    # 6. Leaderboard Reconciliation
    leaderboard_dir = config.get("reconciliation.leaderboard_dir", "C:/Workspace_CN/Quant-Agent")
    df_leaderboard = load_excel_leaderboard(trade_date, leaderboard_dir=leaderboard_dir)
    reconcile_log = cleaner.reconcile_with_leaderboard(df_prices, df_leaderboard, df_prev_prices=df_prev)

    # 7. Data Quality Score calculation (carrying df_margin input)
    score, status, issues = validator.calculate_quality_score(
        df_prices, df_inst, df_margin, coverage, target_date=trade_date
    )

    if reconcile_log["status"] == "WARNING_HIGH_DEVIATION":
        summary = reconcile_log.get("summary") or {}
        compared = summary.get("rows_with_finmind_comparison")
        deviation_rate = summary.get("pct_exceeding_threshold")
        deviation_rate_text = (
            f"{float(deviation_rate):.2%}" if deviation_rate is not None else "unknown"
        )
        if _reconciliation_requires_dq_penalty(reconcile_log):
            score = max(0.0, score - 15.0)
            status = "WARNING" if score >= 85.0 else ("DEGRADED" if score >= 70.0 else "BLOCKED")
            issues.append(
                f"Material leaderboard discrepancy: {reconcile_log['deviation_count']} mismatches "
                f"out of {compared or 'unknown'} comparable rows."
            )
        else:
            issues.append(
                f"Isolated leaderboard discrepancy warning: {reconcile_log['deviation_count']} mismatches "
                f"out of {compared or 'unknown'} comparable rows "
                f"({deviation_rate_text}); DQ score unchanged."
            )

    logger.info(f"Data Quality Score: {score:.2f} | Status: {status} | Mapping coverage: {coverage:.2%}")

    if status == "BLOCKED":
        logger.error(f"Pipeline BLOCKED due to low Data Quality Score ({score:.2f}). Exiting.")
        audit["status"] = "BLOCKED_LOW_DQ"
        audit["row_counts"]["dq_score"] = score
        audit["elapsed_sec"] = round(time.time() - run_start_time, 2)
        _write_audit_summary(output_dir, trade_date, audit)
        logger.remove(log_sink_id)
        return audit

    stock_feat = StockFeatures()
    sector_feat = SectorFeatures()

    df_stock_features = stock_feat.calculate_ranks(df_mapped, df_prev)

    # 8. Rolling multi-day stock features (M2): rebuild history strictly from
    # previously-persisted processed snapshots dated <= trade_date, append today's
    # rows, then compute rolling windows (min_periods enforced, no future leakage --
    # see StockFeatures.calculate_rolling_features docstring).
    df_stock_history = _load_stock_history(data_dir, up_to_date=trade_date)
    df_stock_history = df_stock_history[df_stock_history["trade_date"] != trade_date] if not df_stock_history.empty else df_stock_history
    df_stock_history_full = pd.concat([df_stock_history, df_stock_features], ignore_index=True) if not df_stock_history.empty else df_stock_features.copy()
    df_stock_history_full = stock_feat.calculate_rolling_features(df_stock_history_full)
    df_stock_features_today = df_stock_history_full[df_stock_history_full["trade_date"] == trade_date].copy()

    # 8b. M4: institutional/margin feature expansion. Merge today's raw institutional
    # flow (foreign_net_buy/investment_trust_net_buy/dealer_net_buy) onto the stock
    # features frame so downstream scoring (stock_scoring.py's "institution" factor,
    # which reads foreign_net_buy) actually has real data to score instead of
    # silently falling back to a neutral 50.0 prior every day. Also rebuild the
    # institutional/margin rolling-history features (3/5/10/20d cumulative buy,
    # consecutive-buy streak, quarter-end window flag, margin balance change/usage)
    # from previously-persisted processed snapshots dated <= trade_date, same
    # no-future-leakage contract as stock/sector rolling features.
    inst_feat = InstitutionalFeatures()
    margin_feat = MarginFeatures()

    if not df_inst.empty:
        inst_cols_to_merge = [c for c in ["foreign_net_buy", "investment_trust_net_buy", "dealer_net_buy"]
                               if c in df_inst.columns]
        # Bug fix (M5c-prep, was M5b Acceptance Report §6 finding a): df_stock_features_today
        # is derived from df_stock_history_full, which concatenates every previously-persisted
        # stock_features_<date>.csv. Once a prior day's CSV already carried these same
        # institutional columns (because a prior day's run already merged them in), they leak
        # into df_stock_features_today too. Merging df_inst in again with no `suffixes=`
        # then either raises ("Passing 'suffixes' which cause duplicate columns ... is not
        # allowed") or, when pandas' default _x/_y suffixing applies, silently splits the
        # column into foreign_net_buy_x/_y instead of a single foreign_net_buy column,
        # corrupting the persisted CSV. Today's institutional flow always comes fresh from
        # df_inst (today's raw institutional fetch), so any of these columns already present
        # on df_stock_features_today are stale carry-over from history and must be dropped
        # before merging in the real values for today.
        df_stock_features_today = df_stock_features_today.drop(
            columns=[c for c in inst_cols_to_merge if c in df_stock_features_today.columns]
        )
        df_stock_features_today = df_stock_features_today.merge(
            df_inst[["stock_id"] + inst_cols_to_merge], on="stock_id", how="left"
        )
    else:
        for col in ["foreign_net_buy", "investment_trust_net_buy", "dealer_net_buy"]:
            df_stock_features_today[col] = np.nan

    df_inst_today = df_inst.copy()
    if not df_inst_today.empty:
        df_inst_today["trade_date"] = trade_date
    df_inst_history = _load_generic_history(data_dir, "institutional_features", up_to_date=trade_date,
                                             dtype={"stock_id": str})
    df_inst_history = df_inst_history[df_inst_history["trade_date"] != trade_date] if not df_inst_history.empty else df_inst_history
    df_inst_history_full = pd.concat([df_inst_history, df_inst_today], ignore_index=True) if not df_inst_history.empty else df_inst_today.copy()
    if not df_inst_history_full.empty:
        df_inst_history_full = inst_feat.calculate_cumulative_features(df_inst_history_full)
        df_inst_history_full["quarter_end_window"] = inst_feat.flag_quarter_end_window(
            pd.to_datetime(df_inst_history_full["trade_date"])
        )
    df_inst_features_today = (
        df_inst_history_full[df_inst_history_full["trade_date"] == trade_date].copy()
        if not df_inst_history_full.empty else pd.DataFrame()
    )

    df_margin_today = df_margin.copy()
    if not df_margin_today.empty:
        df_margin_today["trade_date"] = trade_date
    df_margin_history = _load_generic_history(data_dir, "margin_features", up_to_date=trade_date,
                                               dtype={"stock_id": str})
    df_margin_history = df_margin_history[df_margin_history["trade_date"] != trade_date] if not df_margin_history.empty else df_margin_history
    df_margin_history_full = pd.concat([df_margin_history, df_margin_today], ignore_index=True) if not df_margin_history.empty else df_margin_today.copy()
    if not df_margin_history_full.empty:
        df_margin_history_full = margin_feat.calculate_margin_change_features(df_margin_history_full)
        df_margin_history_full = margin_feat.calculate_usage_rate_proxy(df_margin_history_full)
    df_margin_features_today = (
        df_margin_history_full[df_margin_history_full["trade_date"] == trade_date].copy()
        if not df_margin_history_full.empty else pd.DataFrame()
    )

    audit["row_counts"]["institutional_features"] = len(df_inst_features_today)
    audit["row_counts"]["margin_features"] = len(df_margin_features_today)

    df_sector_features = sector_feat.calculate_sector_metrics(df_stock_features_today, df_inst)
    df_sector_features["trade_date"] = trade_date

    # Sector-level institutional aggregation (net-buying stock count, net buy total,
    # pct of sector turnover) -- attached as extra reference columns for reporting;
    # does not change the sector_score "institution" sub-factor formula (that remains
    # inst_flow_ratio computed inside SectorFeatures, unchanged per the "scoring
    # weight contract unchanged" M4 instruction).
    df_sector_inst_agg = inst_feat.aggregate_sector_institutional(df_inst, df_mapped) if not df_inst.empty else pd.DataFrame()
    if not df_sector_inst_agg.empty:
        df_sector_features = df_sector_features.merge(df_sector_inst_agg, on="sector_name", how="left")

    # 9. Rolling sector relative-strength history (3d/5d), same no-future-leakage
    # contract as stock rolling features.
    df_sector_history = _load_sector_history(data_dir, up_to_date=trade_date)
    df_sector_history = df_sector_history[df_sector_history["trade_date"] != trade_date] if not df_sector_history.empty else df_sector_history
    df_sector_history_full = pd.concat([df_sector_history, df_sector_features], ignore_index=True) if not df_sector_history.empty else df_sector_features.copy()
    df_sector_history_full = sector_feat.calculate_relative_strength_history(df_sector_history_full)

    sector_scoring = SectorScoring()
    stock_scoring = StockScoring()

    df_sector_features_today = df_sector_history_full[df_sector_history_full["trade_date"] == trade_date].copy()
    df_scored_sectors, sector_confidence = sector_scoring.score_sectors(df_sector_features_today, has_institutional=not df_inst.empty)
    has_breakout_quality = "dist_from_20d_high" in df_stock_features_today.columns and df_stock_features_today["dist_from_20d_high"].notna().any()
    df_scored_stocks, stock_confidence = stock_scoring.score_stocks(
        df_stock_features_today, df_scored_sectors,
        has_institutional=not df_inst.empty,
        has_rank_improvement="rank_improvement" in df_stock_features_today.columns,
        has_breakout_quality=has_breakout_quality,
    )

    # Persist this trade_date's scored sector snapshot into the accumulated sector
    # history so lifecycle classification (which requires 3/5/10-day history) can see it.
    df_scored_sector_history = df_sector_history_full.merge(
        df_scored_sectors[["sector_name", "score", "overheat_risk", "score_confidence"]],
        on="sector_name", how="left", suffixes=("", "_new")
    ) if not df_sector_history_full.empty else df_scored_sectors.copy()
    if "score_new" in df_scored_sector_history.columns:
        # Only the latest trade_date rows get the freshly computed score; historical
        # rows already carry their own persisted score column from prior runs.
        mask_today = df_scored_sector_history["trade_date"] == trade_date
        df_scored_sector_history.loc[mask_today, "score"] = df_scored_sector_history.loc[mask_today, "score_new"]
        df_scored_sector_history = df_scored_sector_history.drop(columns=["score_new", "overheat_risk_new", "score_confidence_new"], errors="ignore")

    classifier = LifecycleClassifier()
    df_classified = classifier.classify_lifecycle(df_scored_sector_history)

    # Previous trading day's sector row-per-name slice (for new-gainer/continued-
    # momentum day-over-day deltas) and previous trading day's stock features (for
    # the top-50/top-100 count deltas), read strictly from already-persisted
    # processed CSVs -- never recomputed from anything dated after `trade_date`.
    df_sectors_prev_day = pd.DataFrame()
    df_stock_features_prev_day = pd.DataFrame()
    if prev_date:
        prev_sector_path = os.path.join(_processed_dir(data_dir), f"sector_scored_{prev_date}.csv")
        if os.path.exists(prev_sector_path):
            try:
                df_sectors_prev_day = pd.read_csv(prev_sector_path)
            except Exception as e:
                logger.warning(f"Could not read previous-day sector snapshot {prev_sector_path}: {e}")
        prev_stock_path = os.path.join(_processed_dir(data_dir), f"stock_features_{prev_date}.csv")
        if os.path.exists(prev_stock_path):
            try:
                df_stock_features_prev_day = pd.read_csv(prev_stock_path, dtype={"stock_id": str})
            except Exception as e:
                logger.warning(f"Could not read previous-day stock features snapshot {prev_stock_path}: {e}")

    # Milestone 9 (SPEC_ADDENDUM B-1.3): when use_calibrated_thresholds=True, the
    # new-gainer/continued-momentum min_score/prev_score_max thresholds are computed
    # per-sector as rolling quantiles of that sector's own score history (strictly
    # prior trade_dates only, df_scored_sector_history already carries this) instead
    # of the fixed absolute placeholders -- see src/threshold_calibration.py for the
    # method and its explicit small-sample/PRELIMINARY disclosure. Default False
    # preserves exact pre-M9 behavior for every existing caller.
    detector = SignalDetector(
        df_sector_history=df_scored_sector_history if use_calibrated_thresholds else None,
        use_calibrated_thresholds=use_calibrated_thresholds,
    )
    df_final_sectors = detector.detect_signals(
        df_classified,
        df_sectors_prev=df_sectors_prev_day,
        df_stock_features=df_stock_features_today,
        df_stock_features_prev=df_stock_features_prev_day,
        dq_score=score,
        mapping_coverage_pct=coverage,
    )
    df_final_sectors = _attach_top5_stocks(df_final_sectors, df_scored_stocks)

    # 9b. M7: attach 處置/注意 (disposition/attention) flag, read from whatever
    # data/raw/disposition/<endpoint>_<trade_date>.json files already exist on disk
    # (a separate fetch step populates these -- see src/disposition_fetcher.py;
    # run_pipeline itself never makes a live network call here). Historical dates with
    # no such files on disk get disposition_flag="N/A" for every stock (honest "not
    # checked", never silently "clean").
    disposition_info = _load_disposition_ids_for_date(data_dir, trade_date)
    disposition_stocks = disposition_info["stocks"]
    if disposition_info["data_available"]:
        df_scored_stocks["disposition_flag"] = df_scored_stocks["stock_id"].astype(str).map(
            lambda sid: disposition_stocks.get(sid, {}).get("kind", "正常")
        ).replace({"disposition": "處置股", "attention": "注意股"})
    else:
        df_scored_stocks["disposition_flag"] = "N/A(未查核)"

    # 10. Persist processed feature/score snapshots for this trade_date (multi-day
    # accumulation lives on disk as one CSV per trade_date so subsequent daily runs --
    # even in a fresh process -- can rebuild rolling history without re-fetching data).
    processed_dir = _processed_dir(data_dir)
    df_stock_features_today.to_csv(os.path.join(processed_dir, f"stock_features_{trade_date}.csv"), index=False)
    df_sector_features.to_csv(os.path.join(processed_dir, f"sector_features_{trade_date}.csv"), index=False)
    df_final_sectors.to_csv(os.path.join(processed_dir, f"sector_scored_{trade_date}.csv"), index=False)
    df_scored_stocks.to_csv(os.path.join(processed_dir, f"stock_scored_{trade_date}.csv"), index=False)
    if not df_inst_today.empty:
        df_inst_today.to_csv(os.path.join(processed_dir, f"institutional_features_{trade_date}.csv"), index=False)
    if not df_margin_today.empty:
        df_margin_today.to_csv(os.path.join(processed_dir, f"margin_features_{trade_date}.csv"), index=False)

    audit["row_counts"]["sectors_scored"] = len(df_final_sectors)
    audit["row_counts"]["stocks_scored"] = len(df_scored_stocks)
    audit["row_counts"]["dq_score"] = score
    audit["row_counts"]["sector_confidence"] = sector_confidence
    audit["row_counts"]["stock_confidence"] = stock_confidence

    observe_result = None
    try:
        observe_result = build_observe_rankings(
            df_scored_stocks,
            trade_date,
            ranking_depth=int(config.get("observe_rankings.ranking_depth", DEFAULT_RANKING_DEPTH)),
            sector_top_n=int(config.get("observe_rankings.sector_top_n", DEFAULT_SECTOR_TOP_N)),
        )
    except Exception as exc:
        # Observe-only data must never turn an otherwise valid report into a failed run.
        logger.exception(f"Observe rankings unavailable (non-fatal): {exc}")

    generator = ReportGenerator(output_dir=os.path.join(output_dir, "daily"))
    out_path = generator.generate_excel_report(
        trade_date=trade_date,
        df_sectors=df_final_sectors,
        df_stocks=df_scored_stocks,
        dq_score=score,
        dq_status=status,
        dq_issues=issues,
        mapping_coverage_pct=coverage,
        sector_confidence=sector_confidence,
        stock_confidence=stock_confidence,
        observe_rankings=observe_result,
    )

    observe_path = None
    if observe_result is not None:
        try:
            observe_path = write_observe_rankings(output_dir, trade_date, observe_result)
        except Exception as exc:
            logger.exception(f"Observe rankings write failed (non-fatal): {exc}")

    audit["output_files"] = [
        os.path.join(processed_dir, f"stock_features_{trade_date}.csv"),
        os.path.join(processed_dir, f"sector_features_{trade_date}.csv"),
        os.path.join(processed_dir, f"sector_scored_{trade_date}.csv"),
        os.path.join(processed_dir, f"stock_scored_{trade_date}.csv"),
        out_path,
    ]
    if observe_path:
        audit["output_files"].append(observe_path)
    audit["status"] = "SUCCESS"
    audit["elapsed_sec"] = round(time.time() - run_start_time, 2)
    audit_path = _write_audit_summary(output_dir, trade_date, audit)

    logger.info(f"Pipeline executed successfully. Output generated: {out_path}")
    logger.info(f"Audit summary written to: {audit_path}")
    logger.remove(log_sink_id)

    # Returned (in addition to being written to disk) so callers like
    # scripts/run_history_pipeline.py can consume this run's sector-signal output
    # directly without re-reading the just-written CSV. No pre-M5a caller inspects
    # this return value (previously implicit None on every path), so this is additive.
    audit["_df_final_sectors"] = df_final_sectors
    audit["_df_scored_stocks"] = df_scored_stocks
    return audit

if __name__ == "__main__":
    run_pipeline("2026-07-14")
    run_pipeline("2026-07-15", prev_date="2026-07-14")
    run_pipeline("2026-07-16", prev_date="2026-07-15")
