"""
M4 daily data fetcher (V2 data source, SPEC Chapter 8/18, SPEC_ADDENDUM A-1).

Responsibilities:
  1. Fetch TWSE + TPEx daily OHLCV / institutional flow / margin trading from the
     verified real endpoints in loop/evidence/raw_samples/*.json (same URLs used by
     scripts/inspect_endpoints.py and src/data_loader.py -- never invented/recalled
     from memory).
  2. Fetch market index (TAIEX + OTC/櫃買指數) daily close, using the verified
     endpoints discovered in loop/evidence/raw_samples/{twse,tpex}_swagger.json:
       - TWSE MI_INDEX  (https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX)
       - TPEx tpex_index (https://www.tpex.org.tw/openapi/v1/tpex_index)
     If a real index endpoint cannot be found/verified, callers must get back an
     explicit INDEX_SOURCE_UNAVAILABLE marker -- never a fabricated URL or value.
  3. Persist each raw response to data/raw/<category>/<market>_<YYYY-MM-DD>.json in
     the same {metadata: {url, fetch_time, http_status, row_count, sha256}, payload}
     envelope already used by loop/evidence/raw_samples (format continuity).
  4. Fail-closed on HTTP != 200 / empty payload / schema mismatch: log + record a
     failure entry, return None. Never raise out of a fetch call, and never invent
     data to fill a gap (constitution 3.3 / BEHAVIOR_RULES #1).
  5. Retry up to 2 times (3 attempts total) with a 3-second pause between attempts,
     and a >=1.5s polite delay is left to the caller between distinct requests
     (see scripts/fetch_daily_data.py which sleeps between endpoints).
  6. Idempotent writes: re-fetching the same category/market/date backs up any
     existing file to `<path>.bak` (overwriting a previous .bak) before writing the
     new one, so re-running a day's fetch never silently loses the prior evidence.
"""

import os
import json
import shutil
import time
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

MAX_RETRIES = 2          # 2 retries -> 3 attempts total
RETRY_DELAY_SEC = 3
POLITE_DELAY_SEC = 1.5

# Endpoint registry. Every URL here is one already verified real/live in
# loop/evidence/raw_samples/*.json (OHLCV/inst/margin) or discovered from the cached
# swagger definitions (index). category -> market -> url (or None if unavailable).
ENDPOINTS: Dict[str, Dict[str, Optional[str]]] = {
    "ohlcv": {
        "twse": "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
        "tpex": "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
    },
    "institutional": {
        "twse": "https://www.twse.com.tw/rwd/zh/fund/T86",  # date param appended at call time
        "tpex": "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading",
    },
    "margin": {
        "twse": "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN",
        "tpex": "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance",
    },
    "market_index": {
        # Verified against loop/evidence/raw_samples/twse_swagger.json path
        # "/exchangeReport/MI_INDEX" (大盤統計資訊, includes TAIEX 發行量加權股價指數 row).
        "twse": "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX",
        # Verified against loop/evidence/raw_samples/tpex_swagger.json path
        # "/tpex_index" (櫃買指數歷史資料).
        "tpex": "https://www.tpex.org.tw/openapi/v1/tpex_index",
    },
}

INDEX_SOURCE_UNAVAILABLE = "INDEX_SOURCE_UNAVAILABLE"

# ---------------------------------------------------------------------------
# Dated endpoints (2026-08-03).
#
# Every URL in ENDPOINTS above (except TWSE T86) serves ONLY its own latest
# trading day and ignores any date parameter, so a missed day could never be
# recovered: re-running it re-fetched "today" and the DATE_MISMATCH guard
# (correctly) dropped it, leaving the pipeline permanently BLOCKED for that
# date. The URLs below DO honor a date parameter and are used strictly as a
# fallback after the undated attempt fails, so the same-day happy path is
# untouched.
#
# All eight were probed live against 2026-07-30 before being written here (not
# recalled from memory, per CLAUDE.md rule 11). Placeholders: {date_compact} =
# YYYYMMDD (TWSE), {date_slash} = YYYY/MM/DD (TPEx) -- the two sites disagree
# on format.
#
# Deliberately NOT registered:
#   - institutional/twse: _build_url already appends `date=` to T86, which is
#     the one original endpoint that honors it. Nothing to fall back to.
#   - market_index/tpex: no dated OTC-index endpoint could be found (four
#     candidates all returned the site's 404 HTML page). Stays unavailable
#     rather than being faked.
#   - TPEx's legacy web/stock/aftertrading/daily_close_quotes/stk_quote_result.php
#     ACCEPTS a date parameter but SILENTLY IGNORES IT (probed with d=115/07/30,
#     responded date=20260803). It must never be used.
DATED_ENDPOINTS: Dict[str, Dict[str, Optional[str]]] = {
    "ohlcv": {
        "twse": "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
                "?date={date_compact}&type=ALLBUT0999&response=json",
        "tpex": "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc"
                "?date={date_slash}&type=EW&id=&response=json",
    },
    "institutional": {
        "twse": None,
        "tpex": "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"
                "?type=Daily&sect=EW&date={date_slash}&id=&response=json",
    },
    "margin": {
        "twse": "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
                "?date={date_compact}&selectType=ALL&response=json",
        "tpex": "https://www.tpex.org.tw/www/zh-tw/margin/balance"
                "?type=Daily&date={date_slash}&id=&response=json",
    },
    "market_index": {
        "twse": "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
                "?date={date_compact}&type=ALLBUT0999&response=json",
        "tpex": None,
    },
}

# Field-name signatures used to LOCATE the wanted table inside a dated response.
# Never index into `tables` positionally: TWSE's MI_INDEX reply carries ten
# tables and TPEx's replies two, and their order is not contractual. A response
# whose tables match no signature yields None (fail-closed) rather than a guess.
# Field labels are compared after .strip() because TPEx pads several of its own
# ("收盤 ", "成交股數  ").
_DATED_TABLE_SIGNATURES: Dict[tuple, tuple] = {
    ("ohlcv", "twse"): ("證券代號", "證券名稱", "收盤價"),
    ("ohlcv", "tpex"): ("代號", "名稱", "收盤"),
    ("institutional", "tpex"): ("代號", "名稱", "三大法人買賣超股數合計"),
    ("margin", "twse"): ("代號", "名稱", "資券互抵", "註記"),
    ("margin", "tpex"): ("代號", "名稱", "資餘額", "券餘額"),
}

# Positional column -> OpenAPI key. The normalizer's whole job is to hand the
# cleaners a record list that is shape-identical to what the undated OpenAPI
# endpoint would have returned, so src/data_cleaner.py needs no changes at all.
# Each list is index-aligned with the dated table's `fields`; None skips a
# column that has no OpenAPI counterpart.
_DATED_COLUMN_MAPS: Dict[tuple, List[Optional[str]]] = {
    # dated: 證券代號 證券名稱 成交股數 成交筆數 成交金額 開盤價 最高價 最低價
    #        收盤價 漲跌(+/-) 漲跌價差 最後揭示買價 最後揭示買量 最後揭示賣價
    #        最後揭示賣量 本益比
    ("ohlcv", "twse"): [
        "Code", "Name", "TradeVolume", "Transaction", "TradeValue",
        "OpeningPrice", "HighestPrice", "LowestPrice", "ClosingPrice",
        None, "Change", None, None, None, None, None,
    ],
    # dated: 代號 名稱 收盤 漲跌 開盤 最高 最低 成交股數 成交金額(元) 成交筆數
    #        最後買價 最後買量 最後賣價 最後賣量 發行股數 次日漲停價 次日跌停價
    ("ohlcv", "tpex"): [
        "SecuritiesCompanyCode", "CompanyName", "Close", "Change", "Open",
        "High", "Low", "TradingShares", "TransactionAmount",
        "TransactionNumber", "LatestBidPrice", None, "LatesAskPrice", None,
        "Capitals", "NextLimitUp", "NextLimitDown",
    ],
    # dated: 代號 名稱 then SEVEN buy/sell/net triplets, then the grand total:
    #   1 外資及陸資(不含外資自營商)  2 外資自營商  3 外資及陸資合計
    #   4 投信  5 自營商(自行買賣)  6 自營商(避險)  7 自營商合計
    # The OpenAPI feed exposes only five of the seven, so four columns drop out.
    # Verified on 2026-07-30 row 006201: 0 (外資合計) + 115000 (投信)
    # + -355249 (自營合計) = -240249 = the reported grand total.
    ("institutional", "tpex"): [
        "SecuritiesCompanyCode", "CompanyName",
        "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Buy",
        " Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Sell",
        "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference",
        "Foreign Dealers-Total Buy", "Foreign Dealers-TotalSell", "ForeignDealers-Difference",
        "ForeignInvestorsIncludeMainlandAreaInvestors-TotalBuy",
        "ForeignInvestorsIncludeMainlandAreaInvestors-TotalSell",
        "ForeignInvestorsInclude MainlandAreaInvestors-Difference",
        "SecuritiesInvestmentTrustCompanies-TotalBuy",
        "SecuritiesInvestmentTrustCompanies-TotalSell",
        "SecuritiesInvestmentTrustCompanies-Difference",
        None, None, None,
        None, None, None,
        "Dealers-TotalBuy", "Dealers-TotalSell", "Dealers-Difference",
        "TotalDifference",
    ],
    # dated table "融資融券彙總 (全部)" is column-for-column the same order as the
    # OpenAPI MI_MARGN dict, which clean_margin_data reads POSITIONALLY
    # (vals[2]/[3]/[6]/[8]/[9]/[12]) -- so the key names must stay in this order.
    ("margin", "twse"): [
        "股票代號", "股票名稱", "融資買進", "融資賣出", "融資現金償還",
        "融資前日餘額", "融資今日餘額", "融資限額", "融券買進", "融券賣出",
        "融券現券償還", "融券前日餘額", "融券今日餘額", "融券限額",
        "資券互抵", "註記",
    ],
    ("margin", "tpex"): [
        "SecuritiesCompanyCode", "CompanyName",
        "MarginPurchaseBalancePreviousDay", "MarginPurchase", "MarginSales",
        "CashRedemption", "MarginPurchaseBalance",
        "MarginPurchaseBalanceBelongSecuritiesFinanceEnterprise",
        "MarginPurchaseUtilizationRate", "MarginPurchaseQuota",
        "ShortSaleBalancePreviousDay", "ShortSale", "ShortConvering",
        "StockRedemption", "ShortSaleBalance",
        "ShortSaleBalanceBelongSecuritiesFinanceEnterprise",
        "ShortSaleUtilizationRate", "ShortSaleQuota", "Offsetting", "Note",
    ],
}

# Categories whose normalized records carry a ROC "Date"/"日期" field, so the
# existing DATE_MISMATCH guard can still validate them after normalization.
_DATED_DATE_KEY: Dict[tuple, Optional[str]] = {
    ("ohlcv", "twse"): "Date",
    ("ohlcv", "tpex"): "Date",
    ("institutional", "tpex"): "Date",
    ("margin", "twse"): None,      # OpenAPI MI_MARGN rows carry no date either
    ("margin", "tpex"): "Date",
    ("market_index", "twse"): "日期",
}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _estimate_row_count(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        if "data" in payload and isinstance(payload["data"], list):
            return len(payload["data"])
        return len(payload)
    return 1 if payload is not None else 0


class FetchResult:
    """Outcome of a single fetch attempt, always constructed -- never an exception."""

    def __init__(self, success: bool, envelope: Optional[dict] = None,
                 error: Optional[str] = None, http_status: Optional[int] = None):
        self.success = success
        self.envelope = envelope
        self.error = error
        self.http_status = http_status

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "error": self.error,
            "http_status": self.http_status,
        }


def _validate_payload(category: str, payload: Any) -> Optional[str]:
    """
    Returns None if payload passes a minimal schema sanity check for `category`,
    otherwise a short human-readable reason string. Fail-closed: unknown/empty/
    malformed shapes are rejected here rather than downstream silently producing
    empty features.
    """
    if payload is None:
        return "payload is None"
    if isinstance(payload, list) and len(payload) == 0:
        return "payload is an empty list"
    if isinstance(payload, dict):
        if "data" in payload and isinstance(payload["data"], list) and len(payload["data"]) == 0:
            # A genuinely empty market-holiday response is legitimate for some
            # endpoints (see is_holiday_response below) -- callers decide whether an
            # empty `data` list should be treated as a normal non-trading-day record.
            return None
        if not payload:
            return "payload is an empty dict"
    if category == "ohlcv" and isinstance(payload, list):
        sample = payload[0]
        required_any = ["Code", "SecuritiesCompanyCode", "stock_id"]
        if not any(k in sample for k in required_any):
            return f"OHLCV row missing an identifiable ticker key: {list(sample.keys())[:5]}"
    return None


def _parse_roc_or_iso_date(raw: Any) -> Optional[str]:
    """
    Parses a date string that may be ROC-format (e.g. "1150716" = 115 民國年 07 月 16
    日) or plain 8-digit Gregorian (e.g. "20260716") into ISO "YYYY-MM-DD". Returns
    None if `raw` isn't a recognizable date string -- callers must treat None as "no
    date signal available", not as a mismatch.
    """
    if raw is None:
        return None
    s = str(raw).replace("/", "").replace("-", "").strip()
    if not s.isdigit():
        return None
    if len(s) == 7:  # ROC: YYYMMDD, e.g. 1150716
        roc_year = int(s[:3])
        month, day = s[3:5], s[5:7]
        return f"{roc_year + 1911}-{month}-{day}"
    if len(s) == 8:  # Could be Gregorian YYYYMMDD or ROC YYYYMMDD-style zero-padded
        year_part = int(s[:4])
        if year_part > 1911:  # plain Gregorian, e.g. 20260716
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        # zero-padded ROC year, e.g. 01150716 would be 9 digits so this branch is for
        # oddities like "0990716" already handled by len==7; fall through to None.
    return None


def extract_payload_date(category: str, payload: Any) -> Optional[str]:
    """
    Extracts the date the payload SELF-REPORTS it covers, in ISO "YYYY-MM-DD" form.
    Returns None when the payload carries no per-response date signal at all (e.g.
    TWSE MI_MARGN rows have no date field whatsoever -- confirmed against a real
    sampled response, see loop/evidence/raw_samples/twse_margin_sample.json) rather
    than fabricating a date or assuming a match. Checked shapes (verified against real
    cached/live samples, not guessed):
      - dict with a top-level "date" field (TWSE T86 institutional: "date": "20260717").
      - list of row-dicts with a "Date" or "日期" field (TWSE STOCK_DAY_ALL and
        MI_INDEX respectively; ROC format e.g. "1150716").
    """
    if isinstance(payload, dict):
        top_date = payload.get("date") or payload.get("日期")
        if top_date:
            return _parse_roc_or_iso_date(top_date)
        return None
    if isinstance(payload, list) and payload:
        sample = payload[0]
        if isinstance(sample, dict):
            row_date = sample.get("Date") or sample.get("日期")
            if row_date:
                return _parse_roc_or_iso_date(row_date)
    return None


def is_holiday_response(category: str, payload: Any) -> bool:
    """
    Some endpoints legitimately return an empty payload on non-trading days
    (weekends/holidays). Treat an empty list, or a dict with an empty `data` list,
    as a normal "market closed" record rather than a failure -- per the M4 spec's
    "--backfill 跳過週末;休市日 API 回空視為正常記錄" requirement.
    """
    if isinstance(payload, list) and len(payload) == 0:
        return True
    if isinstance(payload, dict) and isinstance(payload.get("data"), list) and len(payload["data"]) == 0:
        return True
    return False


def _iso_to_roc(trade_date: str) -> str:
    """"2026-07-30" -> "1150730" (the ROC form every OpenAPI feed reports)."""
    year, month, day = trade_date.split("-")
    return f"{int(year) - 1911}{month}{day}"


def _build_dated_url(category: str, market: str, trade_date: str) -> Optional[str]:
    """Fill a DATED_ENDPOINTS template, or None when no dated source exists."""
    template = DATED_ENDPOINTS.get(category, {}).get(market)
    if not template:
        return None
    compact = trade_date.replace("-", "")
    return template.format(date_compact=compact, date_slash=trade_date.replace("-", "/"))


def _strip_html(value: Any) -> str:
    """TWSE wraps its 漲跌 sign in markup ("<p style ='color:green'>-</p>")."""
    text = str(value if value is not None else "")
    out, depth = [], 0
    for char in text:
        if char == "<":
            depth += 1
        elif char == ">":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(char)
    return "".join(out).strip()


def _clean_cell(value: Any) -> Any:
    """Drop thousands separators so the value matches the OpenAPI feed's form.

    Placeholders ("--", "", "X") are passed through untouched: the cleaners
    already know how to reject them, and rewriting them here would turn "no
    trade" into a fabricated zero.
    """
    if not isinstance(value, str):
        return value
    text = _strip_html(value)
    if text in ("", "--", "---"):
        return text
    compact = text.replace(",", "")
    return compact


def _find_dated_table(payload: Any, signature: tuple) -> Optional[dict]:
    """Return the one table whose stripped `fields` contain every signature label.

    Fail-closed: no match, or more than one match, returns None. Falling back to
    "the first table that looks close enough" is exactly how a report ends up
    silently built from 報酬指數 instead of 價格指數.
    """
    if not isinstance(payload, dict):
        return None
    tables = payload.get("tables")
    if not isinstance(tables, list):
        return None
    matches = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        fields = table.get("fields")
        if not isinstance(fields, list) or not table.get("data"):
            continue
        stripped = {str(f).strip() for f in fields if f is not None}
        if all(label in stripped for label in signature):
            matches.append(table)
    if len(matches) != 1:
        return None
    return matches[0]


def _normalize_index_tables(payload: dict, trade_date: str) -> Optional[List[dict]]:
    """Flatten MI_INDEX's six index tables into OpenAPI MI_INDEX row-dicts.

    Both 價格指數 and 報酬指數 tables are emitted, exactly as the OpenAPI feed
    does, so downstream code keeps applying its own 發行/加權/not-報酬 filter
    rather than trusting this function to have picked the right row.
    """
    tables = payload.get("tables")
    if not isinstance(tables, list):
        return None
    roc_date = _iso_to_roc(trade_date)
    rows: List[dict] = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        fields = table.get("fields")
        data = table.get("data")
        if not isinstance(fields, list) or not isinstance(data, list) or not data:
            continue
        stripped = [str(f).strip() for f in fields]
        if not stripped or stripped[0] not in ("指數", "報酬指數"):
            continue
        if "收盤指數" not in stripped:
            continue
        for row in data:
            if not isinstance(row, list) or len(row) < 2:
                continue
            rows.append({
                "日期": roc_date,
                "指數": _strip_html(row[0]),
                "收盤指數": _clean_cell(row[1]),
                "漲跌": _strip_html(row[2]) if len(row) > 2 else "",
                "漲跌點數": _clean_cell(row[3]) if len(row) > 3 else "",
                "漲跌百分比": _clean_cell(row[4]) if len(row) > 4 else "",
                "特殊處理註記": _strip_html(row[5]) if len(row) > 5 else "",
            })
    return rows or None


def normalize_dated_payload(category: str, market: str, payload: Any,
                             trade_date: str) -> Optional[List[dict]]:
    """Convert a dated TWSE/TPEx response into OpenAPI-shaped records.

    Returns None -- never a partial or empty list dressed up as success -- when
    the envelope reports a status other than OK, self-reports a date other than
    the one requested, or contains no table matching the expected signature.
    """
    if not isinstance(payload, dict):
        return None
    stat = str(payload.get("stat", "")).strip().lower()
    if stat and stat not in ("ok", "succeeded"):
        logger.warning(f"dated {category}/{market}: envelope stat={payload.get('stat')!r}, rejected")
        return None

    # Envelope-level date check. This is stronger than the post-normalization
    # DATE_MISMATCH guard because it also covers margin/twse, whose rows carry
    # no date field of their own.
    envelope_date = _parse_roc_or_iso_date(payload.get("date"))
    if envelope_date is not None and envelope_date != trade_date:
        logger.warning(
            f"dated {category}/{market}: envelope self-reports {envelope_date}, "
            f"requested {trade_date}; rejected"
        )
        return None

    if category == "market_index" and market == "twse":
        return _normalize_index_tables(payload, trade_date)

    key = (category, market)
    signature = _DATED_TABLE_SIGNATURES.get(key)
    column_map = _DATED_COLUMN_MAPS.get(key)
    if signature is None or column_map is None:
        return None

    table = _find_dated_table(payload, signature)
    if table is None:
        logger.warning(f"dated {category}/{market}: no table matched signature {signature}")
        return None

    fields = table.get("fields") or []
    if len(fields) != len(column_map):
        logger.warning(
            f"dated {category}/{market}: table has {len(fields)} columns but the "
            f"column map expects {len(column_map)}; layout changed, rejected"
        )
        return None

    date_key = _DATED_DATE_KEY.get(key)
    roc_date = _iso_to_roc(trade_date)
    records: List[dict] = []
    for row in table.get("data") or []:
        if not isinstance(row, list) or len(row) != len(column_map):
            continue
        record: Dict[str, Any] = {}
        if date_key:
            record[date_key] = roc_date
        for value, name in zip(row, column_map):
            if name is None:
                continue
            record[name] = _clean_cell(value)
        if key == ("ohlcv", "twse"):
            # TWSE splits 漲跌 into an unsigned magnitude plus a separate sign
            # cell; STOCK_DAY_ALL publishes them already combined.
            sign = _strip_html(row[9]) if len(row) > 9 else ""
            magnitude = record.get("Change", "")
            if sign == "-" and magnitude not in ("", "--", "0.0000"):
                record["Change"] = f"-{magnitude}"
        records.append(record)
    return records or None


def fetch_with_retry(url: str, category: str,
                      max_retries: int = MAX_RETRIES,
                      retry_delay_sec: float = RETRY_DELAY_SEC,
                      timeout_sec: int = 30,
                      session: Optional[requests.Session] = None) -> FetchResult:
    """
    GETs `url`, retrying up to `max_retries` additional times (spaced
    `retry_delay_sec` apart) on HTTP != 200, network exception, or payload schema
    failure. Never raises -- always returns a FetchResult. On final failure returns
    success=False with a descriptive `error` (fail-closed contract).
    """
    requester = session.get if session is not None else requests.get
    last_error = None
    last_status = None

    for attempt in range(max_retries + 1):
        try:
            res = requester(url, headers=DEFAULT_HEADERS, verify=False, timeout=timeout_sec)
            last_status = res.status_code
            if res.status_code != 200:
                last_error = f"HTTP {res.status_code}"
                logger.error(f"[fetch attempt {attempt + 1}/{max_retries + 1}] {url} -> {last_error}")
            else:
                try:
                    data = res.json()
                except Exception as e:
                    last_error = f"JSON decode error: {e}"
                    logger.error(f"[fetch attempt {attempt + 1}/{max_retries + 1}] {url} -> {last_error}")
                    data = None

                if data is not None:
                    payload = data["payload"] if isinstance(data, dict) and "payload" in data else data
                    schema_issue = _validate_payload(category, payload)
                    if schema_issue is not None:
                        last_error = f"Schema validation failed: {schema_issue}"
                        logger.error(f"[fetch attempt {attempt + 1}/{max_retries + 1}] {url} -> {last_error}")
                    else:
                        raw_text = json.dumps(payload, ensure_ascii=False)
                        envelope = {
                            "metadata": {
                                "url": url,
                                "http_status": res.status_code,
                                "fetch_time": _now_str(),
                                "row_count": _estimate_row_count(payload),
                                "sha256": _sha256(raw_text),
                            },
                            "payload": payload,
                        }
                        return FetchResult(success=True, envelope=envelope, http_status=res.status_code)
        except requests.exceptions.RequestException as e:
            last_error = f"Request exception: {e}"
            logger.error(f"[fetch attempt {attempt + 1}/{max_retries + 1}] {url} -> {last_error}")

        if attempt < max_retries:
            time.sleep(retry_delay_sec)

    logger.error(f"Fetch failed after {max_retries + 1} attempts for {url}: {last_error}")
    return FetchResult(success=False, error=last_error, http_status=last_status)


class DataFetcher:
    """
    High-level fetcher: knows the endpoint registry, output path convention, and
    idempotent-backup/write logic. Network calls go through `fetch_with_retry`
    (or an injected `fetch_fn` for offline testing).
    """

    def __init__(self, data_dir: str = "C:/Workspace_CN/taiwan_moneyflow_rotation/data",
                 fetch_fn: Optional[Callable[..., FetchResult]] = None,
                 max_retries: int = MAX_RETRIES,
                 retry_delay_sec: float = RETRY_DELAY_SEC):
        self.data_dir = data_dir
        self._fetch_fn = fetch_fn or fetch_with_retry
        self.max_retries = max_retries
        self.retry_delay_sec = retry_delay_sec
        self.failure_log: List[dict] = []

    def _output_path(self, category: str, market: str, trade_date: str) -> str:
        category_dir = os.path.join(self.data_dir, "raw", category)
        os.makedirs(category_dir, exist_ok=True)
        return os.path.join(category_dir, f"{market}_{trade_date}.json")

    def _write_envelope(self, path: str, envelope: dict) -> None:
        """Idempotent write: backs up an existing file to <path>.bak first."""
        if os.path.exists(path):
            bak_path = f"{path}.bak"
            shutil.copyfile(path, bak_path)
            logger.info(f"Existing file backed up to {bak_path} before overwrite.")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(envelope, f, ensure_ascii=False, indent=2)

    def _build_url(self, category: str, market: str, trade_date: str) -> Optional[str]:
        url = ENDPOINTS.get(category, {}).get(market)
        if url is None:
            return None
        if category == "institutional" and market == "twse":
            date_str = trade_date.replace("-", "")
            return f"{url}?response=json&date={date_str}&selectType=ALLBUT0999"
        return url

    def fetch_and_save(self, category: str, market: str, trade_date: str,
                        skip_existing: bool = False) -> Optional[dict]:
        """
        Fetches one (category, market) endpoint for `trade_date`, writes it to
        data/raw/<category>/<market>_<trade_date>.json, and returns the envelope
        dict. Returns None on any failure (HTTP error, empty/invalid payload after
        retries exhausted) -- fail-closed, logged to self.failure_log, never raises.

        `skip_existing` (default False, preserving pre-M5a always-refetch behavior):
        when True and a valid (non-empty, parseable JSON) file already exists at the
        target path, the fetch is skipped entirely and the on-disk envelope is
        returned as-is -- used by resumable backfills (M5a) so a re-run after a
        network interruption doesn't needlessly re-fetch/re-request days that already
        succeeded. A corrupt/unreadable existing file is treated as "not present" (the
        fetch proceeds normally) rather than silently trusted.
        """
        if skip_existing:
            existing_path = self._output_path(category, market, trade_date)
            if os.path.exists(existing_path):
                try:
                    with open(existing_path, "r", encoding="utf-8") as f:
                        existing_envelope = json.load(f)
                    if existing_envelope.get("payload") is not None:
                        logger.info(f"skip_existing: {category}/{market}/{trade_date} already on disk, skipping fetch.")
                        return existing_envelope
                except Exception as e:
                    logger.warning(f"skip_existing: existing file at {existing_path} unreadable ({e}); will re-fetch.")

        if category == "market_index" and ENDPOINTS["market_index"].get(market) is None:
            msg = f"{INDEX_SOURCE_UNAVAILABLE}: no verified index endpoint for market={market}"
            logger.warning(msg)
            self.failure_log.append({
                "category": category, "market": market, "trade_date": trade_date,
                "error": INDEX_SOURCE_UNAVAILABLE,
            })
            return None

        url = self._build_url(category, market, trade_date)
        if url is None:
            msg = f"No endpoint registered for category={category}, market={market}"
            logger.error(msg)
            self.failure_log.append({
                "category": category, "market": market, "trade_date": trade_date, "error": msg,
            })
            return None

        result = self._fetch_fn(url, category, max_retries=self.max_retries,
                                 retry_delay_sec=self.retry_delay_sec)

        envelope = None
        failure_entry = None

        if not result.success:
            failure_entry = {
                "category": category, "market": market, "trade_date": trade_date,
                "url": url, "error": result.error, "http_status": result.http_status,
            }
            logger.error(f"fetch_and_save undated attempt FAILED: "
                         f"category={category} market={market} date={trade_date} error={result.error}")
        else:
            # Date-consistency guard (M5a): if the payload itself reports a date (see
            # extract_payload_date), it MUST match the requested trade_date. Most of these
            # endpoints (TWSE STOCK_DAY_ALL/MI_MARGN/MI_INDEX, all TPEx endpoints) have no
            # date query parameter at all -- they always return "today's" data regardless
            # of what trade_date the caller asked for. Backfilling a past date against
            # such an endpoint would silently mislabel today's data as historical if this
            # check didn't exist. Only TWSE T86 (institutional) genuinely honors a date=
            # parameter; every other endpoint's payload date is expected to equal
            # trade_date only when trade_date IS the endpoint's actual latest trading day.
            payload_date = extract_payload_date(category, result.envelope["payload"])
            if payload_date is not None and payload_date != trade_date:
                msg = (f"DATE_MISMATCH: requested trade_date={trade_date} but payload "
                       f"self-reports date={payload_date} for category={category} market={market}. "
                       f"Dropped, not saved (this endpoint only serves its latest trading day).")
                logger.warning(msg)
                failure_entry = {
                    "category": category, "market": market, "trade_date": trade_date,
                    "url": url, "error": "DATE_MISMATCH", "payload_date": payload_date,
                }
            else:
                envelope = result.envelope
                envelope["metadata"]["source"] = "undated"

        # Dated fallback. Only reached once the undated attempt has already
        # failed, so a normal same-day run never touches this path.
        if envelope is None:
            envelope = self._fetch_dated_envelope(category, market, trade_date)
            if envelope is None:
                if failure_entry is not None:
                    self.failure_log.append(failure_entry)
                logger.error(f"fetch_and_save FAILED (fail-closed, returning None): "
                             f"category={category} market={market} date={trade_date}")
                return None
            logger.info(f"fetch_and_save recovered {category}/{market}/{trade_date} "
                        f"via the dated endpoint after the undated attempt failed "
                        f"({(failure_entry or {}).get('error')}).")

        path = self._output_path(category, market, trade_date)
        self._write_envelope(path, envelope)
        logger.info(f"Saved {category}/{market} for {trade_date} -> {path} "
                    f"({envelope['metadata']['row_count']} rows, "
                    f"source={envelope['metadata'].get('source')})")
        return envelope

    def _fetch_dated_envelope(self, category: str, market: str,
                               trade_date: str) -> Optional[dict]:
        """Fetch `trade_date` from the dated endpoint and normalize it.

        Returns an envelope whose `payload` is shape-identical to the undated
        OpenAPI feed's, or None if no dated endpoint exists for this pair, the
        request fails, the response can't be normalized, or the normalized rows
        still fail the DATE_MISMATCH guard. Never raises.
        """
        dated_url = _build_dated_url(category, market, trade_date)
        if dated_url is None:
            return None

        result = self._fetch_fn(dated_url, category, max_retries=self.max_retries,
                                 retry_delay_sec=self.retry_delay_sec)
        if not result.success:
            logger.warning(f"dated {category}/{market}/{trade_date}: fetch failed ({result.error})")
            return None

        records = normalize_dated_payload(category, market, result.envelope["payload"], trade_date)
        if not records:
            return None

        payload_date = extract_payload_date(category, records)
        if payload_date is not None and payload_date != trade_date:
            logger.warning(
                f"dated {category}/{market}/{trade_date}: normalized rows self-report "
                f"{payload_date}; rejected"
            )
            return None

        raw_text = json.dumps(records, ensure_ascii=False)
        return {
            "metadata": {
                "url": dated_url,
                "fetch_time": _now_str(),
                "http_status": result.http_status,
                "row_count": len(records),
                "sha256": _sha256(raw_text),
                "source": "dated",
            },
            "payload": records,
        }

    def fetch_market_index(self, trade_date: str) -> Dict[str, Optional[dict]]:
        """
        Fetches both TAIEX (TWSE MI_INDEX) and OTC/櫃買指數 (TPEx tpex_index) for
        `trade_date`. Returns {"twse": envelope_or_None, "tpex": envelope_or_None}.
        Any market whose endpoint is unavailable or fails returns None for that key
        with an INDEX_SOURCE_UNAVAILABLE / failure entry recorded in self.failure_log
        -- never a fabricated index value.
        """
        return {
            "twse": self.fetch_and_save("market_index", "twse", trade_date),
            "tpex": self.fetch_and_save("market_index", "tpex", trade_date),
        }

    def fetch_all_categories(self, trade_date: str,
                              categories: Optional[List[str]] = None,
                              polite_delay_sec: float = POLITE_DELAY_SEC,
                              skip_existing: bool = False) -> Dict[str, Dict[str, Optional[dict]]]:
        """
        Fetches OHLCV + institutional + margin (+ market_index) for both markets on
        `trade_date`, sleeping `polite_delay_sec` between each distinct HTTP request
        (rate-limit courtesy to TWSE/TPEx). Returns a nested dict:
        {category: {market: envelope_or_None}}.

        `skip_existing` (default False): forwarded to fetch_and_save -- when True,
        (category, market, trade_date) combinations already saved on disk are not
        re-fetched (resumable backfill, M5a).
        """
        categories = categories or ["ohlcv", "institutional", "margin", "market_index"]
        results: Dict[str, Dict[str, Optional[dict]]] = {}
        first_request = True
        for category in categories:
            results[category] = {}
            for market in ("twse", "tpex"):
                already_on_disk = skip_existing and os.path.exists(
                    self._output_path(category, market, trade_date)
                )
                if not first_request and not already_on_disk:
                    time.sleep(polite_delay_sec)
                first_request = False
                results[category][market] = self.fetch_and_save(
                    category, market, trade_date, skip_existing=skip_existing
                )
        return results

    def backfill(self, start_date: str, end_date: str,
                 categories: Optional[List[str]] = None,
                 polite_delay_sec: float = POLITE_DELAY_SEC,
                 skip_existing: bool = False) -> Dict[str, Dict[str, Dict[str, Optional[dict]]]]:
        """
        Runs fetch_all_categories for each weekday between start_date and end_date
        (inclusive, both YYYY-MM-DD). Weekends are skipped entirely (not even
        attempted). A holiday weekday that returns an empty payload is recorded
        normally (see is_holiday_response) rather than treated as an error.
        Returns {trade_date: {category: {market: envelope_or_None}}}.

        `skip_existing` (default False, preserving pre-M5a always-refetch behavior):
        when True, any (category, market, trade_date) file already on disk is not
        re-fetched -- makes a multi-day backfill resumable after a network
        interruption without re-requesting days that already succeeded.
        """
        start = datetime.date.fromisoformat(start_date)
        end = datetime.date.fromisoformat(end_date)
        if start > end:
            raise ValueError(f"start_date {start_date} is after end_date {end_date}")

        all_results: Dict[str, Dict[str, Dict[str, Optional[dict]]]] = {}
        current = start
        while current <= end:
            if current.weekday() >= 5:  # Saturday=5, Sunday=6
                logger.info(f"Skipping weekend date {current.isoformat()}")
                current += datetime.timedelta(days=1)
                continue
            date_str = current.isoformat()
            logger.info(f"Backfilling {date_str}...")
            all_results[date_str] = self.fetch_all_categories(
                date_str, categories=categories, polite_delay_sec=polite_delay_sec,
                skip_existing=skip_existing,
            )
            current += datetime.timedelta(days=1)
        return all_results
