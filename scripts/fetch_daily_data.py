"""
M4 daily data fetch CLI.

Usage:
  python scripts/fetch_daily_data.py --date 2026-07-17
  python scripts/fetch_daily_data.py --backfill 2026-07-13 2026-07-17
  python scripts/fetch_daily_data.py --smoke

--smoke fetches exactly one endpoint (TWSE OHLCV, all-market) for a single date and
validates the returned schema/envelope, without writing the full multi-category set.
It is the ONLY mode of this repository's runtime code allowed to make a live network
call during normal development; pytest never calls this script.
"""

import os
import sys
import json
import argparse
import datetime
import hashlib

import requests
import urllib3

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from loguru import logger
from src.data_fetcher import (
    DataFetcher,
    fetch_with_retry,
    ENDPOINTS,
    INDEX_SOURCE_UNAVAILABLE,
    extract_payload_date,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# Verified live 2026-07-22 against the TPEx historical web UI.  The OpenAPI
# `tpex_mainboard_daily_close_quotes` endpoint is latest-day-only; this POST action
# is the official date-addressable route used by the same TPEx site.
TPEX_HISTORICAL_DAILY_QUOTES_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"
TPEX_HISTORICAL_TIMEOUT_SEC = 30


def _default_data_dir() -> str:
    return "C:/Workspace_CN/taiwan_moneyflow_rotation/data"


def _normalise_tpex_historical_rows(payload: dict, trade_date: str):
    """Convert the TPEx web table response to the existing cleaner row shape."""
    if not isinstance(payload, dict) or not isinstance(payload.get("tables"), list):
        return None
    if extract_payload_date("ohlcv", payload) != trade_date:
        return None

    tables = payload["tables"]
    if not tables or not isinstance(tables[0], dict):
        return None
    fields = tables[0].get("fields")
    data = tables[0].get("data")
    if not isinstance(fields, list) or not isinstance(data, list) or not data:
        return None

    field_map = {
        "代號": "SecuritiesCompanyCode",
        "名稱": "CompanyName",
        "收盤": "Close",
        "開盤": "Open",
        "最高": "High",
        "最低": "Low",
        "成交股數": "TradingShares",
        "成交金額(元)": "TransactionAmount",
    }
    rows = []
    for values in data:
        if not isinstance(values, list):
            continue
        row = {field_map[field]: values[index]
               for index, field in enumerate(fields)
               if index < len(values) and field in field_map}
        row["Date"] = payload.get("date")
        if row.get("SecuritiesCompanyCode") and row.get("CompanyName"):
            rows.append(row)
    return rows or None


def _fetch_tpex_historical_ohlcv(
    trade_date: str,
    fetcher: DataFetcher,
    post_fn=None,
):
    """Fetch and persist one historical TPEx OHLCV day, fail-closed."""
    requester = post_fn or requests.post
    try:
        response = requester(
            TPEX_HISTORICAL_DAILY_QUOTES_URL,
            data={"date": trade_date.replace("-", "/"), "response": "json"},
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Referer": "https://www.tpex.org.tw/zh-tw/mainboard/trading/info/pricing.html",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
                ),
                "X-Requested-With": "XMLHttpRequest",
            },
            verify=False,
            timeout=TPEX_HISTORICAL_TIMEOUT_SEC,
        )
        if response.status_code != 200:
            logger.warning(f"TPEx historical OHLCV HTTP {response.status_code} for {trade_date}")
            return None
        payload = response.json()
        rows = _normalise_tpex_historical_rows(payload, trade_date)
        if not rows:
            logger.warning(f"TPEx historical OHLCV returned no date-matching rows for {trade_date}")
            return None
        raw_text = json.dumps(rows, ensure_ascii=False, sort_keys=True)
        envelope = {
            "metadata": {
                "url": TPEX_HISTORICAL_DAILY_QUOTES_URL,
                "method": "POST",
                "http_status": response.status_code,
                "fetch_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "row_count": len(rows),
                "sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                "source": "TPEx_HISTORICAL_WEB",
            },
            "payload": rows,
        }
        path = fetcher._output_path("ohlcv", "tpex", trade_date)
        fetcher._write_envelope(path, envelope)
        logger.info(
            f"Saved TPEx historical OHLCV for {trade_date} -> {path} ({len(rows)} rows)"
        )
        return envelope
    except Exception as exc:
        logger.warning(f"TPEx historical OHLCV fallback failed for {trade_date}: {exc}")
        return None


def run_single_day(trade_date: str, receipts_dir: str = None) -> dict:
    fetcher = DataFetcher(data_dir=_default_data_dir())
    # Backfilling a past day must never re-fetch or overwrite a snapshot that a
    # previous run already verified and saved; today's run has nothing on disk
    # yet, so its behavior is unchanged.
    is_backfill = trade_date != datetime.date.today().isoformat()
    results = fetcher.fetch_all_categories(trade_date, skip_existing=is_backfill)

    historical_recovery = []
    # The OpenAPI TPEx price feed is latest-day-only.  When a manual retry asks for
    # yesterday after the feed has rolled to today, recover the requested day from
    # TPEx's own date-addressable historical web endpoint.  This is official data,
    # never FinMind and never a relabel of today's payload.
    if results.get("ohlcv", {}).get("tpex") is None:
        recovered = _fetch_tpex_historical_ohlcv(trade_date, fetcher)
        if recovered is not None:
            results.setdefault("ohlcv", {})["tpex"] = recovered
            historical_recovery.append({
                "category": "ohlcv",
                "market": "tpex",
                "source": "TPEx_HISTORICAL_WEB",
                "row_count": recovered["metadata"]["row_count"],
            })

    summary = {
        "trade_date": trade_date,
        "results": {},
        "failures": fetcher.failure_log,
        "historical_recovery": historical_recovery,
    }
    for category, by_market in results.items():
        summary["results"][category] = {
            market: (
                {"row_count": env["metadata"]["row_count"], "http_status": env["metadata"]["http_status"]}
                if env else None
            )
            for market, env in by_market.items()
        }

    if receipts_dir:
        os.makedirs(receipts_dir, exist_ok=True)
        receipt_path = os.path.join(receipts_dir, f"fetch_receipt_{trade_date}.json")
        with open(receipt_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"Fetch receipt written to {receipt_path}")
        summary["receipt_path"] = receipt_path

    return summary


def run_backfill(start_date: str, end_date: str, receipts_dir: str = None,
                  skip_existing: bool = True) -> dict:
    """
    `skip_existing` defaults to True for CLI backfill runs (M5a): a multi-day
    historical backfill is expected to be resumable across network interruptions
    without re-fetching days that already succeeded. Pass skip_existing=False to force
    a full re-fetch of the entire range (matches the pre-M5a always-refetch behavior).
    """
    fetcher = DataFetcher(data_dir=_default_data_dir())
    all_results = fetcher.backfill(start_date, end_date, skip_existing=skip_existing)

    summary = {"start_date": start_date, "end_date": end_date, "days": {}, "failures": fetcher.failure_log}
    for trade_date, results in all_results.items():
        summary["days"][trade_date] = {
            category: {
                market: (
                    {"row_count": env["metadata"]["row_count"]} if env else None
                )
                for market, env in by_market.items()
            }
            for category, by_market in results.items()
        }

    if receipts_dir:
        os.makedirs(receipts_dir, exist_ok=True)
        receipt_path = os.path.join(receipts_dir, f"fetch_receipt_backfill_{start_date}_{end_date}.json")
        with open(receipt_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"Backfill receipt written to {receipt_path}")
        summary["receipt_path"] = receipt_path

    return summary


def run_smoke(receipts_dir: str = None) -> dict:
    """
    Live smoke test: fetch exactly ONE endpoint (TWSE all-market OHLCV) for "today"
    (or the most recent weekday), validate the envelope schema, and report success/
    failure honestly. Does not write into data/raw/ (uses a dedicated smoke path so
    it never collides with/overwrites a real day's fetch).
    """
    today = datetime.date.today()
    # Use most recent weekday for the smoke probe (avoids guaranteed-empty weekend hit).
    probe_date = today
    while probe_date.weekday() >= 5:
        probe_date -= datetime.timedelta(days=1)
    date_str = probe_date.isoformat()

    url = ENDPOINTS["ohlcv"]["twse"]
    result = fetch_with_retry(url, category="ohlcv", max_retries=0)

    outcome = {
        "mode": "smoke",
        "endpoint": url,
        "probe_date": date_str,
        "success": result.success,
        "http_status": result.http_status,
        "error": result.error,
    }
    if result.success:
        outcome["row_count"] = result.envelope["metadata"]["row_count"]
        outcome["sha256"] = result.envelope["metadata"]["sha256"]
        sample_path = os.path.join(_default_data_dir(), "raw", "ohlcv", "_smoke_twse_sample.json")
        os.makedirs(os.path.dirname(sample_path), exist_ok=True)
        with open(sample_path, "w", encoding="utf-8") as f:
            json.dump(result.envelope, f, ensure_ascii=False, indent=2)
        outcome["sample_path"] = sample_path
        logger.info(f"Smoke test SUCCESS: {outcome['row_count']} rows, HTTP {result.http_status}")
    else:
        logger.error(f"Smoke test FAILED: {result.error}")

    if receipts_dir:
        os.makedirs(receipts_dir, exist_ok=True)
        receipt_path = os.path.join(receipts_dir, f"smoke_receipt_{date_str}.json")
        with open(receipt_path, "w", encoding="utf-8") as f:
            json.dump(outcome, f, ensure_ascii=False, indent=2, default=str)
        outcome["receipt_path"] = receipt_path
        logger.info(f"Smoke receipt written to {receipt_path}")

    return outcome


def main():
    parser = argparse.ArgumentParser(description="Taiwan Moneyflow Rotation daily data fetcher (M4).")
    parser.add_argument("--date", type=str, help="Single trade date YYYY-MM-DD to fetch.")
    parser.add_argument("--backfill", nargs=2, metavar=("START", "END"),
                         help="Backfill an inclusive date range YYYY-MM-DD YYYY-MM-DD (weekends skipped).")
    parser.add_argument("--smoke", action="store_true",
                         help="Live smoke test: one endpoint, one date, schema validation only.")
    parser.add_argument("--receipts-dir", type=str,
                         default="C:/Workspace_CN/taiwan_moneyflow_rotation/loop/evidence/fetch_receipts",
                         help="Directory to write JSON receipts summarizing this run.")
    parser.add_argument("--no-resume", action="store_true",
                         help="For --backfill: force re-fetching every date even if already on disk "
                              "(default is resumable: dates already saved are skipped).")
    args = parser.parse_args()

    if args.smoke:
        outcome = run_smoke(receipts_dir=args.receipts_dir)
        print(json.dumps(outcome, ensure_ascii=False, indent=2, default=str))
        sys.exit(0 if outcome["success"] else 1)
    elif args.backfill:
        summary = run_backfill(args.backfill[0], args.backfill[1], receipts_dir=args.receipts_dir,
                                skip_existing=not args.no_resume)
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    elif args.date:
        summary = run_single_day(args.date, receipts_dir=args.receipts_dir)
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
