"""
Milestone 7 (Pitfall Pack): 處置股/注意股 (disposition / attention stock) fetcher.

Background: `src/backtester.py`'s module docstring (M5c) explicitly disclosed this as a
missing input -- "no processed disposition/caution list exists on disk this milestone
(no fetcher wired). `disposition_stock_ids` is an optional input so a future milestone
can wire it in without changing this module's contract." This module is that future
milestone's fetcher; `Backtester.run_event_study`'s `disposition_stock_ids` parameter
and its `has_disposition_member`/`weight_penalty` logic are UNCHANGED (already-accepted
M5c code, per governance rule #9 / the task's "backtester 之 disposition_stock_ids 參數
接上真實名單" instruction -- only the caller now passes a real set instead of an
implicit empty one).

Endpoints (discovered from the cached swagger definitions, never recalled from memory --
see loop/evidence/raw_samples/{twse,tpex}_swagger.json, grep for
punish/attention/disposition/notice/warning found these 5 candidates, all confirmed live
on 2026-07-18):

  - TWSE `/announcement/punish`  (處置股 -- 每日排定處置有價證券). Fields include Code
    (stock id), Name, ReasonsOfDisposition, DispositionPeriod, DispositionMeasures.
    This is the TWSE DISPOSITION list.
  - TWSE `/announcement/notice`  (公布注意股票). Fields include Code, TradingInfoForAttention.
    NOTE (verified live): on a day with zero attention stocks, this endpoint returns a
    single SENTINEL row with Number="0" and all other fields empty/"" -- NOT a real
    stock. This is filtered out (Code=="" treated as "no rows", not a stock named "").
  - TPEx `/tpex_trading_warning_information` (上櫃股票注意資訊, real-time 注意股 list).
  - TPEx `/tpex_trading_warning_note` (上櫃股票注意累計次數異常資訊, escalation tracking).
  - TPEx `/tpex_esb_warning_information` (興櫃注意資訊, emerging-board attention list).

Both TWSE endpoints' JSON responses were observed (live, 2026-07-18) to contain
mojibake/replacement-character Chinese text in free-text fields (ReasonsOfDisposition,
DispositionMeasures, Detail, LinkInformation, TradingInfoForAttention) -- this is a
genuine TWSE-server-side encoding defect in the raw HTTP response body itself (confirmed:
the numeric/ASCII fields like Code/Date/NumberOfAnnouncement are intact; only the
Chinese-text fields are corrupted), NOT an artifact of this fetcher's own decoding. Those
fields are stored as-is (disclosed, not silently dropped or re-guessed) -- only the
`Code` (stock_id) field, which is unaffected, is used for the disposition/attention flag
this milestone actually wires into the report and backtester.

Fail-closed contract identical to src/data_fetcher.py: HTTP != 200 / malformed JSON ->
None, logged, never raises.
"""

from __future__ import annotations

import os
import json
import hashlib
import datetime
from typing import Optional, Dict, List, Callable, Any

import requests
import urllib3
from loguru import logger

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

MAX_RETRIES = 2
RETRY_DELAY_SEC = 3

# category -> (market, url, stock_id_field). Verified live 2026-07-18 against the real
# endpoints; see module docstring for swagger provenance.
DISPOSITION_ENDPOINTS: Dict[str, Dict[str, str]] = {
    "twse_punish": {
        "market": "twse", "kind": "disposition",
        "url": "https://openapi.twse.com.tw/v1/announcement/punish",
        "id_field": "Code",
    },
    "twse_notice": {
        "market": "twse", "kind": "attention",
        "url": "https://openapi.twse.com.tw/v1/announcement/notice",
        "id_field": "Code",
    },
    "tpex_warning_info": {
        "market": "tpex", "kind": "attention",
        "url": "https://www.tpex.org.tw/openapi/v1/tpex_trading_warning_information",
        "id_field": "SecuritiesCompanyCode",
    },
    "tpex_warning_note": {
        "market": "tpex", "kind": "attention",
        "url": "https://www.tpex.org.tw/openapi/v1/tpex_trading_warning_note",
        "id_field": "SecuritiesCompanyCode",
    },
    "tpex_esb_warning": {
        "market": "tpex", "kind": "attention",
        # This endpoint's own JSON keys are themselves the (mojibake) Chinese field
        # names (verified live) rather than English aliases like the other 4 -- the
        # stock-code key is positionally the 2nd column; resolved defensively in
        # fetch_one() by falling back to positional lookup if "Code"/id_field isn't a
        # literal key, rather than trusting a hardcoded mojibake byte string.
        "url": "https://www.tpex.org.tw/openapi/v1/tpex_esb_warning_information",
        "id_field": None,
    },
}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class DispositionFetchResult:
    def __init__(self, success: bool, payload: Optional[List[dict]] = None,
                 error: Optional[str] = None, http_status: Optional[int] = None):
        self.success = success
        self.payload = payload
        self.error = error
        self.http_status = http_status


def _default_get(url: str, max_retries: int = MAX_RETRIES,
                  retry_delay_sec: float = RETRY_DELAY_SEC,
                  timeout_sec: int = 25) -> DispositionFetchResult:
    import time
    last_error = None
    last_status = None
    for attempt in range(max_retries + 1):
        try:
            res = requests.get(url, headers=DEFAULT_HEADERS, verify=False, timeout=timeout_sec)
            last_status = res.status_code
            if res.status_code != 200:
                last_error = f"HTTP {res.status_code}"
                logger.error(f"[disposition attempt {attempt + 1}/{max_retries + 1}] {url} -> {last_error}")
            else:
                try:
                    data = res.json()
                except Exception as e:
                    last_error = f"JSON decode error: {e}"
                    data = None
                if data is not None:
                    if not isinstance(data, list):
                        last_error = f"Unexpected response shape (expected list): {type(data)}"
                        logger.error(f"[disposition attempt {attempt + 1}] {url} -> {last_error}")
                    else:
                        return DispositionFetchResult(success=True, payload=data, http_status=200)
        except requests.exceptions.RequestException as e:
            last_error = f"Request exception: {e}"
            logger.error(f"[disposition attempt {attempt + 1}/{max_retries + 1}] {url} -> {last_error}")
        if attempt < max_retries:
            time.sleep(retry_delay_sec)
    logger.error(f"Disposition fetch failed after {max_retries + 1} attempts for {url}: {last_error}")
    return DispositionFetchResult(success=False, error=last_error, http_status=last_status)


class DispositionFetcher:
    """
    Fetches all 5 registered endpoints, normalizes each into a common
    (stock_id, kind, market, source, raw_row) shape, and writes both raw envelopes and a
    consolidated today-list to disk. `fetch_fn` injectable for offline tests.
    """

    def __init__(self, data_dir: str = "C:/Workspace_CN/taiwan_moneyflow_rotation/data",
                 fetch_fn: Optional[Callable[..., DispositionFetchResult]] = None):
        self.data_dir = data_dir
        self._fetch_fn = fetch_fn or _default_get
        self.failure_log: List[dict] = []

    def _raw_dir(self) -> str:
        path = os.path.join(self.data_dir, "raw", "disposition")
        os.makedirs(path, exist_ok=True)
        return path

    def fetch_one(self, endpoint_key: str) -> Optional[dict]:
        """Fetches and saves one endpoint's raw envelope. Returns the envelope dict, or
        None on failure (fail-closed, logged to self.failure_log)."""
        spec = DISPOSITION_ENDPOINTS[endpoint_key]
        result = self._fetch_fn(spec["url"])
        if not result.success:
            self.failure_log.append({"endpoint": endpoint_key, "url": spec["url"],
                                      "error": result.error, "http_status": result.http_status})
            logger.error(f"DispositionFetcher.fetch_one FAILED (fail-closed): "
                         f"{endpoint_key} -> {result.error}")
            return None

        raw_text = json.dumps(result.payload, ensure_ascii=False)
        envelope = {
            "metadata": {
                "endpoint": endpoint_key, "url": spec["url"], "market": spec["market"],
                "kind": spec["kind"], "fetch_time": _now_str(),
                "row_count": len(result.payload), "sha256": _sha256(raw_text),
            },
            "payload": result.payload,
        }
        path = os.path.join(self._raw_dir(), f"{endpoint_key}_{datetime.date.today().isoformat()}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(envelope, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved disposition/{endpoint_key} -> {path} ({len(result.payload)} rows)")
        return envelope

    def fetch_today_list(self) -> dict:
        """
        Fetches all 5 endpoints and returns a consolidated dict:
          {stock_id: {"kind": "disposition"|"attention", "sources": [endpoint_key, ...]}}
        A stock appearing on the TWSE punish list is "disposition" (a hard trading
        restriction); everything else (TWSE notice, all 3 TPEx endpoints) is "attention"
        (a softer watch-list flag). A stock on BOTH is reported as "disposition" (the
        more severe classification wins).

        Never fabricates a stock: the empty-sentinel row TWSE's /announcement/notice
        returns on a zero-attention-stock day (Code=="") is filtered out here, not
        treated as a real stock.
        """
        consolidated: Dict[str, dict] = {}
        per_endpoint_counts = {}
        for key, spec in DISPOSITION_ENDPOINTS.items():
            envelope = self.fetch_one(key)
            if envelope is None:
                per_endpoint_counts[key] = None
                continue
            rows = envelope["payload"]
            n_real = 0
            for row in rows:
                stock_id = self._extract_stock_id(row, spec)
                if not stock_id:
                    continue
                n_real += 1
                kind = spec["kind"]
                if stock_id not in consolidated:
                    consolidated[stock_id] = {"kind": kind, "sources": [key]}
                else:
                    consolidated[stock_id]["sources"].append(key)
                    if kind == "disposition":
                        consolidated[stock_id]["kind"] = "disposition"
            per_endpoint_counts[key] = n_real

        return {
            "date": datetime.date.today().isoformat(),
            "stocks": consolidated,
            "per_endpoint_real_row_counts": per_endpoint_counts,
            "failures": list(self.failure_log),
        }

    @staticmethod
    def _extract_stock_id(row: dict, spec: dict) -> Optional[str]:
        id_field = spec.get("id_field")
        if id_field is not None:
            val = row.get(id_field)
            return str(val).strip() if val not in (None, "") else None
        # tpex_esb_warning: keys are mojibake Chinese field names, not stable across
        # encodings -- fall back to positional lookup (2nd column is documented in
        # the swagger schema as 股票代號/stock code) rather than trusting a hardcoded
        # mojibake byte string that could differ run-to-run.
        values = list(row.values())
        if len(values) >= 2:
            val = values[1]
            return str(val).strip() if val not in (None, "") else None
        return None
