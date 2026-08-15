"""
M5b FinMind historical data fetcher (SPEC_ADDENDUM M5b brief).

Background (why this file exists): the official TWSE/TPEx OpenAPI endpoints used by
`src/data_fetcher.py` (M4/M5a) do NOT accept a historical date query parameter for
OHLCV/margin/index -- confirmed by swagger grep AND by the live `DATE_MISMATCH`
fail-closed guard in `src/data_fetcher.py::extract_payload_date`. Only TWSE T86
(institutional) genuinely honors `date=`. This makes true historical backfill of
2026-04-20..2026-07-17 architecturally impossible from the official endpoints alone.
FinMind (https://api.finmindtrade.com/api/v4/data) is used instead as a genuine
historical data source for that date range.

Dataset names below were discovered by LIVE DRY-RUN against the real API on
2026-07-18 (never recalled from memory, per the governing instruction) -- see
`loop/evidence/fetch_receipts/finmind_dataset_probe_2026-07-18.json` for the raw
probe transcript. Confirmed working on this token:
  - "TaiwanStockInfo"                              -> stock_id/stock_name/industry_category/type
  - "TaiwanStockPrice"                              -> daily OHLCV, per stock_id; ALSO serves the
                                                        TAIEX index when data_id="TAIEX" (real
                                                        market-index row, verified: stock_id="TAIEX",
                                                        "price"-less OHLC row w/ open/max/min/close)
  - "TaiwanStockInstitutionalInvestorsBuySell"      -> per-stock 3-institutional-investor buy/sell
  - "TaiwanStockMarginPurchaseShortSale"            -> per-stock margin/short balance

Confirmed NOT usable / UNAVAILABLE on this token (dry-run, not guessed):
  - No OTC/TPEx (櫃買) index series was found under any plausible data_id
    ("OTC", "TPEX", "TWO", "OTC50", "Y9999", "IX0043", "IX0044", "TWOTCI") on either
    "TaiwanStockPrice" or "TaiwanStockTotalReturnIndex" -- all returned HTTP 200 with
    ZERO rows (a valid-but-empty response, not an error). `TaiwanStockInfo` itself only
    lists "TAIEX"/大盤 as an index entry, no OTC counterpart. Recorded as
    OTC_INDEX_UNAVAILABLE; callers must not fabricate a TPEx index value.
  - "TaiwanStockMarketValueWeight" -> HTTP 400 "Your level is register. Please update
    your user level" (a paid-tier-only dataset on this token).
  - "TaiwanVariousIndicators5Day" -> HTTP 422 (rejected; not investigated further, not
    needed for this milestone's scope).

Since FinMind's OHLCV/institutional/margin datasets are PER-STOCK (data_id=stock_id),
not whole-market-in-one-call like the TWSE/TPEx official endpoints, this fetcher
iterates over the stock universe (from data/reference/stock_industry_mapping or an
injected list) rather than making one bulk request per day. This is throttled and
resumable (see FinMindFetcher.backfill_range) to respect FinMind's free-tier rate
limit (documented product policy: several hundred requests/hour for a registered
token; this fetcher defaults conservative and treats HTTP 402/429 as an explicit
rate-limit signal to back off and stop the run rather than hammering the API).

Envelope format matches the existing project convention ({metadata:{...}, payload}),
with `metadata.source` = "FinMind" and `metadata.dataset` recording the exact FinMind
dataset name used, so a downstream reader can always tell official vs. FinMind data
apart even though both live under data/raw/.

Fail-closed contract (same as src/data_fetcher.py):
  - HTTP != 200, empty `data`, or a schema mismatch -> None, logged, never raises.
  - HTTP 402 (payment required / quota exhausted) or 429 (rate limited) -> a distinct
    RATE_LIMITED marker so callers can stop a batch run cleanly instead of retrying
    into a wall.
"""

import os
import json
import time
import hashlib
import datetime
from typing import Optional, Dict, List, Callable, Any

import requests
import urllib3
from loguru import logger

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

FINMIND_BASE_URL = "https://api.finmindtrade.com/api/v4/data"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

MAX_RETRIES = 2
RETRY_DELAY_SEC = 3
# Conservative polite delay between per-stock requests -- FinMind's free tier is
# request/hour limited (documented product policy, not per-second), but per-request
# throttling still avoids bursting.
POLITE_DELAY_SEC = 1.0

RATE_LIMITED = "RATE_LIMITED"
OTC_INDEX_UNAVAILABLE = "OTC_INDEX_UNAVAILABLE"

# Dataset name registry -- see module docstring for the dry-run verification behind
# each entry. category is the same vocabulary used by src/data_fetcher.py's ENDPOINTS
# (ohlcv/institutional/margin/market_index) so the two sources line up.
DATASETS: Dict[str, str] = {
    "ohlcv": "TaiwanStockPrice",
    "institutional": "TaiwanStockInstitutionalInvestorsBuySell",
    "margin": "TaiwanStockMarginPurchaseShortSale",
    "market_index": "TaiwanStockPrice",  # data_id="TAIEX" only; TPEx has no working series
    "stock_info": "TaiwanStockInfo",
}

# The only verified-working market-index data_id on this token. TPEx/OTC has no
# reachable series (see module docstring) -- never fabricate one.
MARKET_INDEX_DATA_IDS = {
    "twse": "TAIEX",
    "tpex": None,  # OTC_INDEX_UNAVAILABLE
}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_finmind_token(env_paths: Optional[List[str]] = None) -> Optional[str]:
    """
    Reads FINMIND_API_KEY / FINMIND_API_TOKEN from the first matching env file found
    among `env_paths` (defaults to the two project .env locations the milestone brief
    points at), WITHOUT ever printing/logging the token value itself. Returns None
    (never raises, never guesses a token) if not found -- callers fall back to
    anonymous-tier requests and must honestly record that in their receipt.
    """
    candidate_keys = ("FINMIND_API_KEY", "FINMIND_API_TOKEN")
    env_paths = env_paths or [
        "C:/Workspace_CN/.env",
        "C:/Workspace_CN/Quant-Agent/.env",
    ]
    for path in env_paths:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    if key.strip() in candidate_keys:
                        token = value.strip()
                        if token:
                            return token
        except Exception as e:
            logger.warning(f"Could not read env file {path} while looking for FinMind token: {e}")
    return None


class FinMindResult:
    """Outcome of a single FinMind API call, always constructed -- never an exception."""

    def __init__(self, success: bool, payload: Optional[List[dict]] = None,
                 error: Optional[str] = None, http_status: Optional[int] = None,
                 rate_limited: bool = False):
        self.success = success
        self.payload = payload
        self.error = error
        self.http_status = http_status
        self.rate_limited = rate_limited


def finmind_get(dataset: str, token: Optional[str] = None, data_id: Optional[str] = None,
                 start_date: Optional[str] = None, end_date: Optional[str] = None,
                 max_retries: int = MAX_RETRIES, retry_delay_sec: float = RETRY_DELAY_SEC,
                 timeout_sec: int = 25, session: Optional[requests.Session] = None) -> FinMindResult:
    """
    GETs one FinMind `dataset` call, retrying up to `max_retries` additional times on
    a transient network error or HTTP>=500. HTTP 402/429 are treated as a terminal
    rate-limit signal (not retried -- retrying into a rate limit just burns more of an
    hourly quota) and returned with `rate_limited=True`. Never raises.
    """
    params: Dict[str, Any] = {"dataset": dataset}
    if data_id:
        params["data_id"] = data_id
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    if token:
        params["token"] = token

    requester = session.get if session is not None else requests.get
    last_error = None
    last_status = None

    for attempt in range(max_retries + 1):
        try:
            res = requester(FINMIND_BASE_URL, params=params, headers=DEFAULT_HEADERS,
                             verify=False, timeout=timeout_sec)
            last_status = res.status_code

            if res.status_code in (402, 429):
                logger.warning(f"[finmind attempt {attempt + 1}] {dataset} data_id={data_id} "
                                f"-> HTTP {res.status_code} (rate limited / quota exhausted)")
                return FinMindResult(success=False, error=RATE_LIMITED,
                                      http_status=res.status_code, rate_limited=True)

            if res.status_code != 200:
                last_error = f"HTTP {res.status_code}"
                logger.error(f"[finmind attempt {attempt + 1}/{max_retries + 1}] "
                             f"{dataset} data_id={data_id} -> {last_error}")
            else:
                try:
                    body = res.json()
                except Exception as e:
                    last_error = f"JSON decode error: {e}"
                    body = None

                if body is not None:
                    if not isinstance(body, dict) or "data" not in body:
                        last_error = f"Unexpected response shape (no 'data' key): {list(body.keys()) if isinstance(body, dict) else type(body)}"
                        logger.error(f"[finmind attempt {attempt + 1}] {dataset} -> {last_error}")
                    else:
                        data = body.get("data")
                        if not isinstance(data, list):
                            last_error = f"'data' field is not a list: {type(data)}"
                            logger.error(f"[finmind attempt {attempt + 1}] {dataset} -> {last_error}")
                        else:
                            # An empty list is a legitimate "no data for this range"
                            # response (e.g. a non-trading day, or a genuinely
                            # unavailable series like the OTC index probe) -- success,
                            # not a failure, so callers can distinguish "no rows" from
                            # "broken call".
                            return FinMindResult(success=True, payload=data, http_status=200)
        except requests.exceptions.RequestException as e:
            last_error = f"Request exception: {e}"
            logger.error(f"[finmind attempt {attempt + 1}/{max_retries + 1}] "
                         f"{dataset} data_id={data_id} -> {last_error}")

        if attempt < max_retries:
            time.sleep(retry_delay_sec)

    logger.error(f"FinMind fetch failed after {max_retries + 1} attempts: "
                 f"dataset={dataset} data_id={data_id} error={last_error}")
    return FinMindResult(success=False, error=last_error, http_status=last_status)


def build_envelope(dataset: str, data_id: Optional[str], payload: List[dict],
                    start_date: Optional[str] = None, end_date: Optional[str] = None) -> dict:
    """Wraps a FinMind payload in the project-standard {metadata, payload} envelope."""
    raw_text = json.dumps(payload, ensure_ascii=False)
    return {
        "metadata": {
            "source": "FinMind",
            "dataset": dataset,
            "data_id": data_id,
            "start_date": start_date,
            "end_date": end_date,
            "fetch_time": _now_str(),
            "row_count": len(payload),
            "sha256": _sha256(raw_text),
        },
        "payload": payload,
    }


class FinMindFetcher:
    """
    High-level FinMind fetcher: knows the dataset registry, per-stock iteration,
    throttling, output path convention (data/raw/<category>/finmind_<...>.json), and
    resumable/skip-existing semantics. Network calls go through `finmind_get` (or an
    injected `fetch_fn` for offline testing).
    """

    def __init__(self, data_dir: str = "C:/Workspace_CN/taiwan_moneyflow_rotation/data",
                 token: Optional[str] = None, fetch_fn: Optional[Callable[..., FinMindResult]] = None,
                 max_retries: int = MAX_RETRIES, retry_delay_sec: float = RETRY_DELAY_SEC,
                 polite_delay_sec: float = POLITE_DELAY_SEC):
        self.data_dir = data_dir
        self.token = token if token is not None else get_finmind_token()
        self.token_present = self.token is not None
        self._fetch_fn = fetch_fn or finmind_get
        self.max_retries = max_retries
        self.retry_delay_sec = retry_delay_sec
        self.polite_delay_sec = polite_delay_sec
        self.failure_log: List[dict] = []
        self.rate_limit_hit = False

    def _category_dir(self, category: str) -> str:
        path = os.path.join(self.data_dir, "raw", category)
        os.makedirs(path, exist_ok=True)
        return path

    def _stock_series_path(self, category: str, stock_id: str) -> str:
        """
        One file per (category, stock_id) holding the full fetched date range so far
        -- FinMind's per-call date range means re-fetching one stock's whole history
        is one request, not one-per-day; this keeps the on-disk layout efficient while
        still being per-source (FinMind, distinct filename prefix) and easy for
        data_loader to merge alongside the official per-day snapshots.
        """
        return os.path.join(self._category_dir(category), f"finmind_{stock_id}.json")

    def _index_path(self, market: str) -> str:
        return os.path.join(self._category_dir("market_index"), f"finmind_index_{market}.json")

    def fetch_stock_series(self, category: str, stock_id: str, start_date: str, end_date: str,
                            skip_existing: bool = False) -> Optional[dict]:
        """
        Fetches one stock's full [start_date, end_date] history for `category`
        ("ohlcv"/"institutional"/"margin") and writes it to
        data/raw/<category>/finmind_<stock_id>.json. Returns the envelope, or None on
        failure (fail-closed, recorded in self.failure_log, never raises).

        `skip_existing`: if True and a valid envelope already covers this exact
        [start_date, end_date] on disk, skip the network call entirely (resumable
        backfill). A different date range on disk is NOT treated as already covering
        the request -- re-fetched to avoid silently returning a stale partial range.
        """
        path = self._stock_series_path(category, stock_id)
        if skip_existing and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                meta = existing.get("metadata", {})
                if meta.get("start_date") == start_date and meta.get("end_date") == end_date:
                    logger.info(f"skip_existing: finmind {category}/{stock_id} "
                                f"[{start_date}..{end_date}] already on disk, skipping fetch.")
                    return existing
            except Exception as e:
                logger.warning(f"skip_existing: existing file at {path} unreadable ({e}); will re-fetch.")

        dataset = DATASETS[category]
        result = self._fetch_fn(dataset, token=self.token, data_id=stock_id,
                                 start_date=start_date, end_date=end_date,
                                 max_retries=self.max_retries, retry_delay_sec=self.retry_delay_sec)

        if result.rate_limited:
            self.rate_limit_hit = True
            self.failure_log.append({
                "category": category, "stock_id": stock_id, "error": RATE_LIMITED,
                "http_status": result.http_status,
            })
            logger.error(f"FinMind RATE_LIMITED on {category}/{stock_id} -- stopping is the caller's "
                         f"responsibility (fetch_stock_series itself does not loop).")
            return None

        if not result.success:
            self.failure_log.append({
                "category": category, "stock_id": stock_id, "error": result.error,
                "http_status": result.http_status,
            })
            logger.error(f"FinMind fetch FAILED (fail-closed, returning None): "
                         f"category={category} stock_id={stock_id} error={result.error}")
            return None

        envelope = build_envelope(dataset, stock_id, result.payload, start_date, end_date)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(envelope, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved finmind {category}/{stock_id} [{start_date}..{end_date}] -> {path} "
                    f"({envelope['metadata']['row_count']} rows)")
        return envelope

    # Conservative default polite delay for the same-day universe fallback below.
    # Deliberately shorter than POLITE_DELAY_SEC (used by the multi-day historical
    # backfill in backfill_universe, which runs unattended overnight and can afford to
    # be slow): this path runs INSIDE a same-run daily pipeline fallback where the
    # caller (scripts/run_daily.py) is waiting on it, so it trades a bit of politeness
    # for finishing within a practical wall-clock budget. Still throttled (not 0) to
    # avoid bursting FinMind's undocumented rate limit.
    UNIVERSE_FALLBACK_DELAY_SEC = 0.3

    def fetch_today_ohlcv_for_universe(self, stock_ids: List[str], trade_date: str,
                                        max_requests: Optional[int] = None,
                                        polite_delay_sec: Optional[float] = None) -> dict:
        """
        Same-day OHLCV fallback fetch (distinct from `backfill_universe`, which is the
        multi-day/multi-category historical backfill): for each stock_id in
        `stock_ids`, fetches FinMind's TaiwanStockPrice for the single-day range
        [trade_date, trade_date] and keeps the row ONLY if its own `date` field equals
        `trade_date` exactly (same fail-closed date-match discipline as
        `src/data_fetcher.py::extract_payload_date`'s DATE_MISMATCH guard -- a
        wrong-date row is silently dropped, never smuggled in as if it were today's).

        Does NOT write the per-stock data/raw/ohlcv/finmind_<stock_id>.json files that
        `fetch_stock_series`/`backfill_universe` produce (those are for the historical
        multi-day backfill's resumable on-disk cache; this is a live same-run fallback
        whose result the caller consumes directly and persists via the normal
        `stock_features_<date>.csv` pipeline output instead).

        Stops early (like `backfill_universe`) the moment a RATE_LIMITED response is
        seen -- returns whatever rows were already collected rather than raising, so
        the caller can decide whether partial coverage is still usable.

        Returns {"rows": [{"date","stock_id","open","high","low","close","volume",
        "turnover"}, ...], "requested": N, "succeeded": N, "date_mismatch": N,
        "failed": N, "rate_limited": bool, "stopped_early": bool, "elapsed_sec": float}.
        """
        delay = self.polite_delay_sec if polite_delay_sec is None else polite_delay_sec
        if delay is None:
            delay = self.UNIVERSE_FALLBACK_DELAY_SEC

        summary = {
            "rows": [], "requested": len(stock_ids), "succeeded": 0,
            "date_mismatch": 0, "failed": 0, "rate_limited": False,
            "stopped_early": False, "elapsed_sec": None,
        }
        run_start = time.time()
        session = requests.Session()
        dataset = DATASETS["ohlcv"]

        for i, stock_id in enumerate(stock_ids):
            if max_requests is not None and i >= max_requests:
                summary["stopped_early"] = True
                logger.info(f"fetch_today_ohlcv_for_universe: reached max_requests={max_requests}, stopping.")
                break

            result = self._fetch_fn(dataset, token=self.token, data_id=stock_id,
                                     start_date=trade_date, end_date=trade_date,
                                     max_retries=self.max_retries, retry_delay_sec=self.retry_delay_sec,
                                     session=session)

            if result.rate_limited:
                self.rate_limit_hit = True
                summary["rate_limited"] = True
                summary["stopped_early"] = True
                logger.error(f"fetch_today_ohlcv_for_universe: RATE_LIMITED after {i} requests "
                              f"-- stopping early, returning {summary['succeeded']} rows collected so far.")
                break

            if not result.success:
                summary["failed"] += 1
                self.failure_log.append({"category": "ohlcv_today_fallback", "stock_id": stock_id,
                                          "error": result.error, "http_status": result.http_status})
            else:
                matched = False
                for row in result.payload or []:
                    if row.get("date") != trade_date:
                        continue
                    try:
                        op, hi, lo, cl = (float(row["open"]), float(row["max"]),
                                           float(row["min"]), float(row["close"]))
                    except (KeyError, TypeError, ValueError):
                        continue
                    if op <= 0 or hi <= 0 or lo <= 0 or cl <= 0:
                        continue
                    summary["rows"].append({
                        "date": trade_date, "stock_id": stock_id,
                        "open": op, "high": hi, "low": lo, "close": cl,
                        "volume": row.get("Trading_Volume") or 0,
                        "turnover": row.get("Trading_money") or 0,
                    })
                    summary["succeeded"] += 1
                    matched = True
                    break
                if not matched:
                    # Either the payload was empty (no trading data yet for this
                    # stock/date) or every row's date differed from trade_date --
                    # either way this is an honest "not available", not an error.
                    summary["date_mismatch"] += 1

            if delay:
                time.sleep(delay)

        summary["elapsed_sec"] = round(time.time() - run_start, 2)
        return summary

    def fetch_market_index(self, market: str, start_date: str, end_date: str,
                            skip_existing: bool = False) -> Optional[dict]:
        """
        Fetches TAIEX (twse) via FinMind's TaiwanStockPrice/data_id=TAIEX. Returns None
        immediately with an OTC_INDEX_UNAVAILABLE failure-log entry for market="tpex"
        -- no working OTC/TPEx index series was found on this token (dry-run
        verified, see module docstring); never fabricates one.
        """
        data_id = MARKET_INDEX_DATA_IDS.get(market)
        if data_id is None:
            self.failure_log.append({
                "category": "market_index", "market": market, "error": OTC_INDEX_UNAVAILABLE,
            })
            logger.warning(f"FinMind market_index for market={market}: {OTC_INDEX_UNAVAILABLE}")
            return None

        path = self._index_path(market)
        if skip_existing and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                meta = existing.get("metadata", {})
                if meta.get("start_date") == start_date and meta.get("end_date") == end_date:
                    logger.info(f"skip_existing: finmind market_index/{market} already on disk, skipping.")
                    return existing
            except Exception as e:
                logger.warning(f"skip_existing: existing index file unreadable ({e}); will re-fetch.")

        dataset = DATASETS["market_index"]
        result = self._fetch_fn(dataset, token=self.token, data_id=data_id,
                                 start_date=start_date, end_date=end_date,
                                 max_retries=self.max_retries, retry_delay_sec=self.retry_delay_sec)

        if result.rate_limited:
            self.rate_limit_hit = True
            self.failure_log.append({
                "category": "market_index", "market": market, "error": RATE_LIMITED,
                "http_status": result.http_status,
            })
            return None
        if not result.success:
            self.failure_log.append({
                "category": "market_index", "market": market, "error": result.error,
                "http_status": result.http_status,
            })
            return None

        envelope = build_envelope(dataset, data_id, result.payload, start_date, end_date)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(envelope, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved finmind market_index/{market} [{start_date}..{end_date}] -> {path} "
                    f"({envelope['metadata']['row_count']} rows)")
        return envelope

    def fetch_stock_info(self, skip_existing: bool = False) -> Optional[dict]:
        """
        Fetches the whole-market FinMind stock_id/stock_name/industry_category table
        (single call, not per-stock -- see module docstring). Written to
        data/raw/fundamentals/finmind_stock_info.json (reused by
        scripts/build_chinese_sector_mapping.py for M5b item 2).
        """
        path = os.path.join(self._category_dir("fundamentals"), "finmind_stock_info.json")
        if skip_existing and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                if existing.get("payload"):
                    logger.info("skip_existing: finmind stock_info already on disk, skipping fetch.")
                    return existing
            except Exception as e:
                logger.warning(f"skip_existing: existing stock_info file unreadable ({e}); will re-fetch.")

        result = self._fetch_fn(DATASETS["stock_info"], token=self.token,
                                 max_retries=self.max_retries, retry_delay_sec=self.retry_delay_sec)
        if result.rate_limited:
            self.rate_limit_hit = True
            self.failure_log.append({"category": "stock_info", "error": RATE_LIMITED,
                                      "http_status": result.http_status})
            return None
        if not result.success:
            self.failure_log.append({"category": "stock_info", "error": result.error,
                                      "http_status": result.http_status})
            return None

        envelope = build_envelope(DATASETS["stock_info"], None, result.payload)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(envelope, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved finmind stock_info -> {path} ({envelope['metadata']['row_count']} rows)")
        return envelope

    def backfill_universe(self, stock_ids: List[str], categories: List[str],
                           start_date: str, end_date: str,
                           skip_existing: bool = True,
                           max_requests: Optional[int] = None) -> dict:
        """
        Iterates `stock_ids` x `categories`, fetching each stock's full
        [start_date, end_date] history in one call per (category, stock_id) pair
        (FinMind's date-range API means this is NOT one-request-per-day). Stops
        immediately (does not keep burning quota) the moment a RATE_LIMITED response
        is seen, recording exactly how far the run got so a re-run with
        skip_existing=True resumes cleanly. `max_requests` optionally caps the number
        of live network calls this call makes (0/None = unlimited), useful for a
        deliberately partial/smoke run.

        Returns a summary dict: succeeded/failed/rate_limited counts per category,
        total requests made, and elapsed time. Never raises -- one stock's failure
        does not abort the batch (fail-closed per-item, not fail-closed for the whole
        run), except a RATE_LIMITED signal which deliberately DOES stop the run early
        (continuing would just accumulate more failures against an exhausted quota).
        """
        summary = {
            "start_date": start_date, "end_date": end_date,
            "requested_stock_count": len(stock_ids), "categories": categories,
            "per_category": {c: {"success": 0, "failed": 0, "skipped_existing": 0} for c in categories},
            "requests_made": 0, "rate_limited": False, "elapsed_sec": None,
            "stopped_early": False,
        }
        run_start = time.time()
        requests_made = 0

        for category in categories:
            for stock_id in stock_ids:
                if max_requests is not None and requests_made >= max_requests:
                    summary["stopped_early"] = True
                    logger.info(f"backfill_universe: reached max_requests={max_requests}, stopping.")
                    summary["elapsed_sec"] = round(time.time() - run_start, 2)
                    return summary

                path = self._stock_series_path(category, stock_id)
                already_covers_range = False
                if skip_existing and os.path.exists(path):
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            existing = json.load(f)
                        meta = existing.get("metadata", {})
                        already_covers_range = (meta.get("start_date") == start_date
                                                 and meta.get("end_date") == end_date)
                    except Exception:
                        already_covers_range = False

                if already_covers_range:
                    summary["per_category"][category]["skipped_existing"] += 1
                    continue

                envelope = self.fetch_stock_series(category, stock_id, start_date, end_date,
                                                    skip_existing=skip_existing)
                requests_made += 1
                summary["requests_made"] = requests_made

                if self.rate_limit_hit:
                    summary["rate_limited"] = True
                    summary["stopped_early"] = True
                    logger.error("backfill_universe: RATE_LIMITED encountered, stopping run early "
                                 "(resume later with skip_existing=True).")
                    summary["elapsed_sec"] = round(time.time() - run_start, 2)
                    return summary

                if envelope is not None:
                    summary["per_category"][category]["success"] += 1
                else:
                    summary["per_category"][category]["failed"] += 1

                if self.polite_delay_sec:
                    time.sleep(self.polite_delay_sec)

        summary["elapsed_sec"] = round(time.time() - run_start, 2)
        return summary
