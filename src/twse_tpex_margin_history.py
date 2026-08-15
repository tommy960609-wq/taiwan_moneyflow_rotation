"""
Official free-endpoint margin/short-sale HISTORY backfill (TWSE + TPEx legacy JSON
endpoints), added to replace FinMind for this dataset because the FinMind free-tier
quota was exhausted (see the governing brief for this task -- read-only-verified
across two rounds, both endpoints live-checked before this file was written).

Why a NEW module instead of extending `src/data_loader.py`'s existing
`fetch_twse_margin_all` / `fetch_tpex_margin_all`: those two hit the OpenAPI
"whole-market, TODAY-only" endpoints (no date parameter honored) and MUST NOT be
touched -- they're relied on for the current-day pipeline. The endpoints here are a
different, older TWSE/TPEx "history report" family that DOES honor an explicit date
query parameter, confirmed live:

  TWSE (上市):
    https://www.twse.com.tw/exchangeReport/MI_MARGN?response=json&date=YYYYMMDD&selectType=ALL
    Takes a plain Gregorian YYYYMMDD date. Response shape (live-verified 2026-07-2x,
    NOT the flat {fields,data} shape written in the original task brief -- the brief's
    shape guess was wrong, this is what the endpoint actually returns):
      {"stat": "OK", "date": "20260714", "tables": [
          {"title": ..., "fields": [...6 cols...], "data": [...market-total row...]},
          {"title": ..., "fields": [...16 cols...], "data": [[stock_id, name, buy,
              sell, cash_repay, prev_balance, today_balance, next_limit,
              short_buy, short_sell, short_repay, short_prev_balance,
              short_today_balance, short_next_limit, offset, note], ...]}
      ]}
    tables[1] is the per-stock margin table. Column order is EXACTLY the order
    src/data_cleaner.py::clean_margin_data's TWSE list-branch already expects
    (row[0]=code, row[2]=margin_buy, row[3]=margin_sell, row[6]=margin_balance,
    row[8]=short_buy, row[9]=short_sell, row[12]=short_balance) -- confirmed by
    decoding the real field labels byte-for-byte, not assumed.

  TPEx (上櫃):
    https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php?l=zh-tw&d=115/07/14&o=json
    Takes an ROC-year SLASH date "115/07/14" (NOT Gregorian, NOT dashes) -- this is
    the single most important gotcha of this endpoint and is exactly what the task
    brief called out. Response shape (live-verified):
      {"date": "20260714", "tables": [
          {"fields": [...20 cols...], "data": [[stock_id, name,
              prev_short... wait -- see field order below], ...], "totalCount": 913}
      ]}
    Field order (byte-verified against the real field-name strings): 代號(0) 名稱(1)
    前資餘額(2) 資買(3) 資賣(4) 現償(5) 資餘額(6) 資屬證金(7) 資使用率(8) 資限額(9)
    前券餘額(10) 券賣(11) 券買(12) 券償(13) 券餘額(14) 券屬證金(15) 券使用率(16)
    券限額(17) 資券相抵(18) 備註(19).
    Note TPEx's column 11/12 order is SELL-then-BUY for the short side (mirrors the
    TWSE table's own 買/賣 vs short 賣/買 ordering) -- verified positionally against
    the real payload, not assumed from the TWSE layout.

Both endpoints' top-level `date` field is the response's own self-reported date
(Gregorian YYYYMMDD in both cases, even though TPEx's *request* param is ROC-slash).
Every fetch function in this module cross-checks that self-reported date against the
requested date before returning anything -- a mismatch is treated exactly like a
failure (returns None), never silently accepted. This is the same "date consistency"
fail-closed contract already used by src/data_fetcher.py's DATE_MISMATCH guard; it is
re-implemented here rather than imported because `extract_payload_date` in that module
doesn't know this endpoint family's `{"date": ..., "tables": [...]}` shape.

Fail-closed contract (matches src/data_fetcher.py and src/finmind_fetcher.py):
  - HTTP != 200, timeout, connection error, or unparseable JSON -> None, logged.
  - Response's self-reported date != requested date -> None, logged (DATE_MISMATCH).
  - Missing/malformed `tables` -> None, logged.
  - Never raises out of a fetch call.

Output envelope matches the project-standard shape used throughout data/raw/
({metadata: {source, url, fetch_time, http_status, row_count, sha256}, payload}) via
`build_history_envelope` below, so existing tooling that reads that envelope shape
works unchanged.
"""

import json
import hashlib
import datetime
from typing import Optional, List, Dict, Any

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

TIMEOUT_SEC = 20

# Polite delay between requests to these free official endpoints -- not FinMind, no
# quota to protect, but still don't hammer a government server. Matches the
# conservative per-request delay convention used elsewhere in this project
# (src/finmind_fetcher.py POLITE_DELAY_SEC / src/data_fetcher.py POLITE_DELAY_SEC).
POLITE_DELAY_SEC = 1.5

TWSE_MARGIN_HISTORY_URL = "https://www.twse.com.tw/exchangeReport/MI_MARGN"
TPEX_MARGIN_HISTORY_URL = (
    "https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php"
)

DATE_MISMATCH = "DATE_MISMATCH"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def iso_to_roc_slash(date_str: str) -> Optional[str]:
    """
    Converts a Gregorian ISO date "YYYY-MM-DD" to the ROC-year slash format the TPEx
    history endpoint requires, e.g. "2026-07-14" -> "115/07/14". Returns None (does
    NOT raise / does NOT fabricate) for anything that doesn't parse as a plausible
    Gregorian date, or whose ROC year would fall outside the 100-120 sanity band this
    project's date range (2026-04-20..2026-07-20, ROC 115) actually needs -- guards
    against a silently-wrong conversion being fed into a live HTTP request.
    """
    if not date_str:
        return None
    s = str(date_str).strip()
    try:
        parts = s.split("-")
        if len(parts) != 3:
            return None
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return None
        roc_year = year - 1911
        if not (100 <= roc_year <= 120):
            logger.warning(f"iso_to_roc_slash: ROC year {roc_year} (from {date_str}) "
                            f"outside expected 100-120 sanity band; refusing to convert.")
            return None
        return f"{roc_year}/{month:02d}/{day:02d}"
    except (ValueError, TypeError):
        return None


def _iso_to_gregorian_compact(date_str: str) -> Optional[str]:
    """"2026-07-14" -> "20260714" for the TWSE request param. None if unparseable."""
    if not date_str:
        return None
    s = str(date_str).strip().replace("-", "")
    if len(s) == 8 and s.isdigit():
        return s
    return None


def _response_date_to_iso(date_field: Any) -> Optional[str]:
    """
    Both endpoints self-report their covered date as a Gregorian YYYYMMDD string in
    the top-level "date" field (e.g. "20260714"). Returns ISO "YYYY-MM-DD", or None if
    the field is missing/malformed.
    """
    if not date_field:
        return None
    s = str(date_field).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return None


def fetch_twse_margin_history(date: str, timeout_sec: int = TIMEOUT_SEC) -> Optional[List[Dict]]:
    """
    Fetches TWSE's per-stock margin/short-sale table for `date` (ISO "YYYY-MM-DD")
    from the legacy MI_MARGN history endpoint. Returns the raw per-stock table as a
    list of dicts with keys: fields (list[str], the 16 raw column labels) and rows
    (list[list]) -- see `_table_to_rows` for the flattened {stock_id, name, ...} form
    consumed by the transform step. Returns None (fail-closed, logged) on any HTTP
    failure, timeout, JSON parse failure, missing tables, or a self-reported date that
    doesn't match the requested date -- never raises, never fabricates.
    """
    compact_date = _iso_to_gregorian_compact(date)
    if compact_date is None:
        logger.error(f"fetch_twse_margin_history: unparseable date {date!r}")
        return None

    url = f"{TWSE_MARGIN_HISTORY_URL}?response=json&date={compact_date}&selectType=ALL"
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, verify=False, timeout=timeout_sec)
    except requests.exceptions.Timeout:
        logger.error(f"fetch_twse_margin_history: timeout fetching {url}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"fetch_twse_margin_history: request exception fetching {url}: {e}")
        return None

    if resp.status_code != 200:
        logger.error(f"fetch_twse_margin_history: HTTP {resp.status_code} for {url}")
        return None

    try:
        payload = resp.json()
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"fetch_twse_margin_history: JSON parse failure for {url}: {e}")
        return None

    if not isinstance(payload, dict):
        logger.error(f"fetch_twse_margin_history: unexpected top-level type for {url}")
        return None

    # A trading holiday / weekend / non-trading day for TWSE MI_MARGN returns ONLY
    # {"stat": "很抱歉，沒有符合條件的資料"} -- no "date" field and no "tables" field at
    # all (live-verified against 2026-04-25, a Saturday). This must be checked BEFORE
    # the date-consistency guard below: with no self-reported date to compare against,
    # the date guard would otherwise misclassify every single non-trading day as a
    # DATE_MISMATCH failure instead of the normal "no data this day" outcome. Only once
    # `tables` is confirmed absent do we treat this as a benign no-data day; a
    # genuinely malformed/unexpected response (tables absent AND date present) still
    # falls through to the date-mismatch/malformed-table checks below.
    if "date" not in payload and "tables" not in payload:
        logger.info(f"fetch_twse_margin_history: no data for date={date} "
                     f"(stat={payload.get('stat')!r}); treating as no-data/non-trading day.")
        return []

    resp_date_iso = _response_date_to_iso(payload.get("date"))
    if resp_date_iso is None or resp_date_iso != date:
        logger.error(f"{DATE_MISMATCH}: fetch_twse_margin_history requested date={date} "
                     f"but response date={payload.get('date')!r} ({url})")
        return None

    tables = payload.get("tables")
    if not isinstance(tables, list) or len(tables) < 2:
        # Defensive fallback: date matched but the per-stock table is still missing/
        # short for some other reason -- treat as no-data day rather than a failure,
        # same as the "date"-absent case above.
        logger.info(f"fetch_twse_margin_history: no per-stock table for date={date} "
                     f"(stat={payload.get('stat')!r}); treating as no-data day.")
        return []

    per_stock_table = tables[1]
    rows = per_stock_table.get("data")
    if not isinstance(rows, list):
        logger.error(f"fetch_twse_margin_history: malformed per-stock table for date={date}")
        return None

    return rows


def fetch_tpex_margin_history(date: str, timeout_sec: int = TIMEOUT_SEC) -> Optional[List[Dict]]:
    """
    Fetches TPEx's per-stock margin/short-sale table for `date` (ISO "YYYY-MM-DD")
    from the legacy margin_bal_result.php history endpoint. Converts `date` to the
    ROC-year slash format the endpoint requires (iso_to_roc_slash) before the request.
    Returns the raw per-stock rows (list of lists, 20 columns each -- see module
    docstring for field order), or None (fail-closed, logged) on any HTTP failure,
    timeout, JSON parse failure, unconvertible date, missing tables, or a
    self-reported date mismatch.
    """
    roc_date = iso_to_roc_slash(date)
    if roc_date is None:
        logger.error(f"fetch_tpex_margin_history: could not convert date {date!r} to ROC format")
        return None

    url = f"{TPEX_MARGIN_HISTORY_URL}?l=zh-tw&d={roc_date}&o=json"
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, verify=False, timeout=timeout_sec)
    except requests.exceptions.Timeout:
        logger.error(f"fetch_tpex_margin_history: timeout fetching {url}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"fetch_tpex_margin_history: request exception fetching {url}: {e}")
        return None

    if resp.status_code != 200:
        logger.error(f"fetch_tpex_margin_history: HTTP {resp.status_code} for {url}")
        return None

    try:
        payload = resp.json()
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"fetch_tpex_margin_history: JSON parse failure for {url}: {e}")
        return None

    if not isinstance(payload, dict):
        logger.error(f"fetch_tpex_margin_history: unexpected top-level type for {url}")
        return None

    resp_date_iso = _response_date_to_iso(payload.get("date"))
    if resp_date_iso is None or resp_date_iso != date:
        logger.error(f"{DATE_MISMATCH}: fetch_tpex_margin_history requested date={date} "
                     f"(roc={roc_date}) but response date={payload.get('date')!r} ({url})")
        return None

    tables = payload.get("tables")
    if not isinstance(tables, list) or len(tables) < 1:
        logger.info(f"fetch_tpex_margin_history: no per-stock table for date={date}; "
                     f"treating as no-data day.")
        return []

    rows = tables[0].get("data")
    if not isinstance(rows, list):
        logger.error(f"fetch_tpex_margin_history: malformed per-stock table for date={date}")
        return None

    return rows


# ---------------------------------------------------------------------------
# Transform: raw rows -> the exact shapes src/data_cleaner.py::clean_margin_data
# already knows how to parse, so no changes to the cleaner are needed.
# ---------------------------------------------------------------------------

def transform_twse_margin_rows(rows: List[list]) -> List[list]:
    """
    TWSE's raw per-stock rows are ALREADY in the exact list-of-lists column order
    src/data_cleaner.py::clean_margin_data's TWSE branch expects (row[0]=code,
    row[2]=margin_buy, row[3]=margin_sell, row[6]=margin_balance, row[8]=short_buy,
    row[9]=short_sell, row[12]=short_balance) -- verified field-by-field against the
    real response (see module docstring). This function exists as an explicit,
    named identity/pass-through step (rather than feeding raw rows straight to the
    cleaner) so the on-disk envelope always records what was actually persisted, and
    so a future TWSE column-order change only needs a change here, not a
    clean_margin_data edit. Rows are returned unchanged (list of lists).
    """
    return list(rows) if rows else []


def transform_tpex_margin_rows(rows: List[list], trade_date: str) -> List[Dict]:
    """
    TPEx's raw per-stock rows are 20-column lists (see module docstring for exact
    field order); src/data_cleaner.py::clean_margin_data's TPEx branch expects a list
    of DICTS with keys SecuritiesCompanyCode/MarginPurchase/MarginSales/
    MarginPurchaseBalance/ShortConvering/ShortSale/ShortSaleBalance/Date (matching its
    existing FinMind/openapi-shaped TPEx dict convention) -- this builds exactly that,
    positionally, from the verified column order:
      0=code, 3=資買(MarginPurchase), 4=資賣(MarginSales), 6=資餘額(MarginPurchaseBalance),
      11=券賣(ShortSale), 12=券買(ShortConvering), 14=券餘額(ShortSaleBalance).
    `Date` is stamped as the Gregorian ISO trade_date (clean_margin_data's
    parse_roc_date also accepts an 8-digit Gregorian string; ISO with dashes round-trips
    through it too since parse_roc_date strips both "/" and "-").
    """
    out = []
    for row in rows or []:
        if not isinstance(row, list) or len(row) < 15:
            continue
        out.append({
            "SecuritiesCompanyCode": row[0],
            "MarginPurchase": row[3],
            "MarginSales": row[4],
            "MarginPurchaseBalance": row[6],
            "ShortSale": row[11],
            "ShortConvering": row[12],
            "ShortSaleBalance": row[14],
            "Date": trade_date,
        })
    return out


def build_history_envelope(source: str, url: str, payload: Any, http_status: int) -> dict:
    """
    Wraps a fetched/transformed payload in the project-standard
    {metadata: {source, url, fetch_time, http_status, row_count, sha256}, payload}
    envelope (same shape as data/raw/*.json elsewhere in this project).
    """
    raw_text = json.dumps(payload, ensure_ascii=False)
    return {
        "metadata": {
            "source": source,
            "url": url,
            "fetch_time": _now_str(),
            "http_status": http_status,
            "row_count": len(payload) if isinstance(payload, list) else None,
            "sha256": _sha256(raw_text),
        },
        "payload": payload,
    }
