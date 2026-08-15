"""
M5b FinMind historical backfill CLI (SPEC_ADDENDUM M5b brief item 1).

Backfills 2026-04-20..2026-07-17 OHLCV / institutional / margin / TAIEX index history
via FinMind (src/finmind_fetcher.py), since the official TWSE/TPEx endpoints cannot
serve historical dates (see src/finmind_fetcher.py module docstring and the M5a
DATE_MISMATCH finding). Fail-closed, rate-limit-aware, resumable.

The stock universe to backfill is discovered from the real trading universe on disk
(data/reference/stock_industry_mapping.csv's stock_id column, which M5a populated
from a real 2026-07-17 OHLCV snapshot at 98.58% coverage) rather than guessed --
falls back to a live FinMind TaiwanStockInfo call if the mapping file is absent.

Usage:
  python scripts/fetch_history_finmind.py --start 2026-04-20 --end 2026-07-17
  python scripts/fetch_history_finmind.py --start 2026-04-20 --end 2026-07-17 --limit-stocks 20   # smoke/dev run
  python scripts/fetch_history_finmind.py --stock-info-only   # just refresh the Chinese sector table
"""

import os
import sys
import json
import argparse
import datetime
from typing import List, Optional

import pandas as pd
from loguru import logger

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from src.finmind_fetcher import FinMindFetcher, get_finmind_token


def _default_data_dir() -> str:
    return "C:/Workspace_CN/taiwan_moneyflow_rotation/data"


def _default_receipts_dir() -> str:
    return "C:/Workspace_CN/taiwan_moneyflow_rotation/loop/evidence/fetch_receipts"


def discover_stock_universe(data_dir: str, fetcher: Optional[FinMindFetcher] = None) -> List[str]:
    """
    Returns the list of stock_ids to backfill. Prefers the real trading universe
    already recorded in data/reference/stock_industry_mapping.csv (populated by M5a
    from a live 2026-07-17 OHLCV snapshot -- 1,963 real tickers, not guessed). Falls
    back to a live FinMind TaiwanStockInfo call (equities only, via
    src.data_cleaner.DataCleaner.is_valid_equity) if that file is missing.
    """
    mapping_path = os.path.join(data_dir, "reference", "stock_industry_mapping.csv")
    if os.path.exists(mapping_path):
        df = pd.read_csv(mapping_path, dtype={"stock_id": str})
        ids = sorted(df["stock_id"].dropna().astype(str).str.strip().unique().tolist())
        logger.info(f"discover_stock_universe: {len(ids)} stock_ids from existing mapping file.")
        return ids

    logger.warning("stock_industry_mapping.csv not found; falling back to a live FinMind "
                    "TaiwanStockInfo call to discover the universe.")
    from src.data_cleaner import DataCleaner
    cleaner = DataCleaner()
    fetcher = fetcher or FinMindFetcher(data_dir=data_dir)
    envelope = fetcher.fetch_stock_info()
    if envelope is None:
        logger.error("discover_stock_universe: FinMind stock_info fetch also failed; returning empty universe.")
        return []
    ids = []
    seen = set()
    for row in envelope["payload"]:
        sid = str(row.get("stock_id", "")).strip()
        name = str(row.get("stock_name", "")).strip()
        if sid and sid not in seen and cleaner.is_valid_equity(sid, name):
            seen.add(sid)
            ids.append(sid)
    return sorted(ids)


def run_backfill(start_date: str, end_date: str, data_dir: Optional[str] = None,
                  receipts_dir: Optional[str] = None, limit_stocks: Optional[int] = None,
                  categories: Optional[List[str]] = None, skip_existing: bool = True,
                  sleep_between_sec: Optional[float] = None) -> dict:
    """
    `sleep_between_sec`: optional override for FinMindFetcher's per-request polite delay
    (default None preserves FinMindFetcher's own POLITE_DELAY_SEC=1.0s -- exact pre-M5c
    behavior, unchanged unless the caller explicitly passes a value). Added for a slow
    "drip" background backfill (M5c brief: 45-60s between requests) without touching any
    other default; the CLI's own --sleep-between flag below defaults to None for the
    same reason.
    """
    data_dir = data_dir or _default_data_dir()
    receipts_dir = receipts_dir or _default_receipts_dir()
    categories = categories or ["ohlcv", "institutional", "margin"]

    fetcher_kwargs = {"data_dir": data_dir}
    if sleep_between_sec is not None:
        fetcher_kwargs["polite_delay_sec"] = sleep_between_sec
    fetcher = FinMindFetcher(**fetcher_kwargs)
    token_present = fetcher.token_present

    stock_ids = discover_stock_universe(data_dir, fetcher=fetcher)
    if limit_stocks:
        stock_ids = stock_ids[:limit_stocks]

    summary = {
        "run_started_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "start_date": start_date, "end_date": end_date,
        "token_present": token_present,
        "universe_size": len(stock_ids),
        "categories": categories,
        "per_category": None,
        "requests_made": 0,
        "rate_limited": False,
        "stopped_early": False,
        "market_index": {},
        "stock_info": None,
        "elapsed_sec": None,
        "failure_sample": [],
    }

    # Market index (TAIEX via FinMind; TPEx/OTC honestly UNAVAILABLE -- see
    # src/finmind_fetcher.py module docstring).
    for market in ("twse", "tpex"):
        env = fetcher.fetch_market_index(market, start_date, end_date, skip_existing=skip_existing)
        summary["market_index"][market] = (
            {"row_count": env["metadata"]["row_count"]} if env else "UNAVAILABLE_OR_FAILED"
        )

    if fetcher.rate_limit_hit:
        summary["rate_limited"] = True
        summary["stopped_early"] = True
        summary["failure_sample"] = fetcher.failure_log[:20]
        _finish(summary, fetcher, receipts_dir)
        return summary

    # Stock info (Chinese sector names) -- one call, cheap, do it while quota is fresh.
    info_env = fetcher.fetch_stock_info(skip_existing=skip_existing)
    summary["stock_info"] = {"row_count": info_env["metadata"]["row_count"]} if info_env else "FAILED"

    if fetcher.rate_limit_hit:
        summary["rate_limited"] = True
        summary["stopped_early"] = True
        summary["failure_sample"] = fetcher.failure_log[:20]
        _finish(summary, fetcher, receipts_dir)
        return summary

    batch_summary = fetcher.backfill_universe(stock_ids, categories, start_date, end_date,
                                               skip_existing=skip_existing)
    summary["per_category"] = batch_summary["per_category"]
    summary["requests_made"] = batch_summary["requests_made"]
    summary["rate_limited"] = summary["rate_limited"] or batch_summary["rate_limited"]
    summary["stopped_early"] = summary["stopped_early"] or batch_summary["stopped_early"]
    summary["failure_sample"] = fetcher.failure_log[:20]

    _finish(summary, fetcher, receipts_dir)
    return summary


def _finish(summary: dict, fetcher: FinMindFetcher, receipts_dir: str) -> None:
    summary["total_failures_logged"] = len(fetcher.failure_log)
    finished_at = datetime.datetime.now()
    summary["run_finished_at"] = finished_at.strftime("%Y-%m-%d %H:%M:%S")
    started_at = datetime.datetime.strptime(summary["run_started_at"], "%Y-%m-%d %H:%M:%S")
    summary["elapsed_sec"] = round((finished_at - started_at).total_seconds(), 2)


def write_receipt(receipts_dir: str, summary: dict) -> str:
    os.makedirs(receipts_dir, exist_ok=True)
    path = os.path.join(receipts_dir, "finmind_backfill_summary.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"FinMind backfill summary written to {path}")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="M5b FinMind historical backfill.")
    parser.add_argument("--start", type=str, default="2026-04-20")
    parser.add_argument("--end", type=str, default="2026-07-17")
    parser.add_argument("--limit-stocks", type=int, default=None,
                         help="Cap the number of stocks fetched (dev/smoke runs).")
    parser.add_argument("--no-resume", action="store_true",
                         help="Force re-fetch even if a matching-range file already exists on disk.")
    parser.add_argument("--receipts-dir", type=str, default=_default_receipts_dir())
    parser.add_argument("--sleep-between", type=float, default=None,
                         help="Seconds to sleep between per-stock requests (default: unchanged "
                              "FinMindFetcher.POLITE_DELAY_SEC=1.0s). For a slow unattended "
                              "background drip backfill, pass e.g. --sleep-between 50.")
    args = parser.parse_args()

    result = run_backfill(args.start, args.end, limit_stocks=args.limit_stocks,
                           skip_existing=not args.no_resume, receipts_dir=args.receipts_dir,
                           sleep_between_sec=args.sleep_between)
    write_receipt(args.receipts_dir, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
