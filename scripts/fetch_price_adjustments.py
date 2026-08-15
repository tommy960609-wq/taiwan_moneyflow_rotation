"""
Milestone 7: real fetch driver for ex-dividend adjustment factors (SPEC_ADDENDUM B-2.3
gap closure -- see src/price_adjuster.py module docstring for the full background and
the dry-run receipt that established TaiwanStockDividendResult as the only usable
FinMind dataset for this purpose).

Iterates every stock_id that already has a FinMind OHLCV file on disk
(data/raw/ohlcv/finmind_<id>.json, the M5b/M5c backfill this milestone's task explicitly
says not to race PID 2924 for), fetches its dividend-event history for the same
[start_date, end_date] window, and writes the resulting per-stock adjustment factor
rows into a single consolidated table:
  data/reference/price_adjustment_factors.csv  (stock_id, trade_date, adj_factor)

Also writes a summary receipt to
loop/evidence/fetch_receipts/price_adjustment_fetch_summary_<date>.json (success/reuse/
failure counts, coverage %, which stock_ids failed).

Per-stock dividend-event JSON files are cached under
data/raw/fundamentals/dividends/finmind_div_<id>.json -- a DIFFERENT filename prefix
(`finmind_div_`) than the drip-backfill process's own files
(data/raw/*/finmind_<id>.json), so this never collides with or overwrites PID 2924's
concurrent writes.

Usage:
  python scripts/fetch_price_adjustments.py
  python scripts/fetch_price_adjustments.py --start-date 2026-04-20 --end-date 2026-07-17
"""

import os
import sys
import glob
import json
import argparse
import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from loguru import logger
from src.price_adjuster import build_adjustment_factor_table_for_universe
from src.finmind_fetcher import get_finmind_token


def _default_data_dir() -> str:
    return "C:/Workspace_CN/taiwan_moneyflow_rotation/data"


def discover_backfilled_stock_ids(ohlcv_dir: str) -> list:
    """Finds every stock_id with a finmind_<id>.json OHLCV file on disk (excludes the
    unrelated `_smoke_twse_sample.json` fixture)."""
    ids = []
    for path in sorted(glob.glob(os.path.join(ohlcv_dir, "finmind_*.json"))):
        fname = os.path.basename(path)
        if fname == "_smoke_twse_sample.json" or not fname.startswith("finmind_"):
            continue
        sid = fname.replace("finmind_", "").replace(".json", "")
        if sid.isdigit() or (sid and sid[0].isdigit()):
            ids.append(sid)
    return ids


def run(data_dir: str = None, start_date: str = "2026-04-20", end_date: str = None,
        polite_delay_sec: float = 1.0, max_stocks: int = None) -> dict:
    data_dir = data_dir or _default_data_dir()
    end_date = end_date or datetime.date.today().isoformat()
    ohlcv_dir = os.path.join(data_dir, "raw", "ohlcv")

    stock_ids = discover_backfilled_stock_ids(ohlcv_dir)
    if max_stocks:
        stock_ids = stock_ids[:max_stocks]
    logger.info(f"Discovered {len(stock_ids)} FinMind-backfilled stocks with OHLCV on disk.")

    token = get_finmind_token()
    if token is None:
        logger.error("No FinMind token found -- aborting (fail-closed, will not attempt "
                      "anonymous-tier requests for a bulk per-stock fetch).")
        return {"status": "NO_TOKEN"}

    df_factors = build_adjustment_factor_table_for_universe(
        stock_ids, ohlcv_dir, start_date, end_date, token=token,
        polite_delay_sec=polite_delay_sec, skip_existing=True,
    )

    out_path = os.path.join(data_dir, "reference", "price_adjustment_factors.csv")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df_factors.drop(columns=[c for c in df_factors.columns if c not in
                              ("stock_id", "trade_date", "adj_factor")], errors="ignore") \
        .to_csv(out_path, index=False, encoding="utf-8-sig")

    failures = df_factors.attrs.get("failures", [])
    n_success = df_factors.attrs.get("n_success", 0)
    n_reused = df_factors.attrs.get("n_reused", 0)
    covered_stock_ids = sorted(df_factors["stock_id"].unique().tolist()) if not df_factors.empty else []

    summary = {
        "start_date": start_date, "end_date": end_date,
        "requested_stock_count": len(stock_ids),
        "covered_stock_count": len(covered_stock_ids),
        "coverage_pct": round(len(covered_stock_ids) / len(stock_ids), 4) if stock_ids else None,
        "n_freshly_fetched": n_success, "n_reused_from_cache": n_reused,
        "n_failed": len(failures), "failed_stock_ids": failures,
        "output_csv": out_path,
        "output_rows": len(df_factors),
        "stocks_with_at_least_one_real_adjustment": (
            int((df_factors.groupby("stock_id")["adj_factor"].apply(lambda s: (s != 1.0).any())).sum())
            if not df_factors.empty else 0
        ),
    }

    receipt_dir = "C:/Workspace_CN/taiwan_moneyflow_rotation/loop/evidence/fetch_receipts"
    os.makedirs(receipt_dir, exist_ok=True)
    receipt_path = os.path.join(receipt_dir, f"price_adjustment_fetch_summary_{datetime.date.today().isoformat()}.json")
    with open(receipt_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"Price adjustment fetch summary written to {receipt_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="M7: fetch FinMind ex-dividend events and build adjustment factors.")
    parser.add_argument("--start-date", type=str, default="2026-04-20")
    parser.add_argument("--end-date", type=str, default=None)
    parser.add_argument("--polite-delay", type=float, default=1.0)
    parser.add_argument("--max-stocks", type=int, default=None, help="Debug: cap number of stocks processed.")
    args = parser.parse_args()
    run(start_date=args.start_date, end_date=args.end_date,
        polite_delay_sec=args.polite_delay, max_stocks=args.max_stocks)
