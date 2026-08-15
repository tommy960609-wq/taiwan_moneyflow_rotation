import os
import glob
import requests
import json
import urllib3
from loguru import logger
import pandas as pd
from typing import Optional, Dict, List

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class DataLoader:
    def __init__(self, timeout_sec: int = 20):
        self.timeout = timeout_sec
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def _get_api_response(self, url: str) -> Optional[List[Dict]]:
        try:
            logger.info(f"Fetching OpenAPI URL: {url}")
            response = requests.get(url, headers=self.headers, verify=False, timeout=self.timeout)
            if response.status_code == 200:
                data = response.json()
                # If wrapped in metadata/payload structure, return payload
                if isinstance(data, dict) and "payload" in data:
                    return data["payload"]
                return data
            else:
                logger.error(f"Failed to fetch {url}. Status code: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Exception fetching {url}: {e}")
            return None

    def fetch_twse_ohlcv_all(self) -> Optional[List[Dict]]:
        url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
        return self._get_api_response(url)

    def fetch_twse_pe_pb_all(self) -> Optional[List[Dict]]:
        url = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
        return self._get_api_response(url)

    def fetch_twse_institutional_all(self, date_str: str = "20260716") -> Optional[List[Dict]]:
        # Correct RWD T86 URL mapping
        url = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={date_str}&selectType=ALLBUT0999"
        try:
            logger.info(f"Fetching T86 RWD URL: {url}")
            res = requests.get(url, headers=self.headers, verify=False, timeout=self.timeout)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict):
                    if "payload" in data:
                        return data["payload"]
                    # Standard TWSE T86 RWD returns dict with fields and data
                    if "data" in data and isinstance(data["data"], list):
                        fields = data.get("fields", [])
                        report_date = data.get("date")
                        rows = []
                        for row in data["data"]:
                            d = dict(zip(fields, row))
                            if report_date:
                                d["_report_date_"] = report_date
                            rows.append(d)
                        return rows
                return None
            else:
                logger.error(f"T86 returned HTTP {res.status_code}")
                return None
        except Exception as e:
            logger.error(f"Exception in fetch_twse_institutional_all: {e}")
            return None

    def fetch_twse_margin_all(self) -> Optional[List[Dict]]:
        url = "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"
        return self._get_api_response(url)

    def fetch_tpex_ohlcv_all(self) -> Optional[List[Dict]]:
        url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
        return self._get_api_response(url)

    def fetch_tpex_institutional_all(self) -> Optional[List[Dict]]:
        url = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"
        return self._get_api_response(url)

    def fetch_tpex_margin_all(self) -> Optional[List[Dict]]:
        url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance"
        return self._get_api_response(url)

    def load_industry_mapping(self, path: str = "C:/Workspace_CN/taiwan_moneyflow_rotation/data/reference/stock_industry_mapping.xlsx") -> Optional[pd.DataFrame]:
        try:
            if not os.path.exists(path):
                logger.warning(f"Industry mapping Excel not found at {path}")
                return None
            df = pd.read_excel(path, dtype={"stock_id": str})
            return df
        except Exception as e:
            logger.error(f"Error loading industry mapping: {e}")
            return None

    # -------------------------------------------------------------------
    # M5b: FinMind historical data integration (SPEC_ADDENDUM M5b brief item 3).
    #
    # The official TWSE/TPEx endpoints cannot serve historical dates (see
    # src/data_fetcher.py's DATE_MISMATCH guard and its module docstring) -- FinMind
    # is used as the historical source instead (src/finmind_fetcher.py). FinMind's
    # per-stock files (data/raw/<category>/finmind_<stock_id>.json, one file per
    # stock covering a whole date range) are a structurally different on-disk shape
    # from the official whole-market-per-day files
    # (data/raw/<category>/{twse,tpex}_<date>.json / legacy twse_prices_<date>.json
    # etc) -- these loaders never mix the two INSIDE one file; they read FinMind's
    # per-stock files, filter to one trade_date, and hand back a DataFrame in the
    # same target schema src/data_cleaner.py's clean_* methods already produce, with
    # an explicit `source` column ("FinMind" vs "official") so a caller can always
    # tell them apart. Official-source-wins-on-conflict is implemented in
    # merge_ohlcv_sources / merge_institutional_sources / merge_margin_sources below.
    # -------------------------------------------------------------------

    def load_finmind_ohlcv_for_date(self, data_dir: str, trade_date: str,
                                     stock_market_lookup: Optional[Dict[str, str]] = None) -> pd.DataFrame:
        """
        Scans data/raw/ohlcv/finmind_<stock_id>.json for every stock's series, extracts
        the row matching `trade_date` (if present), and returns a DataFrame with the
        same columns as DataCleaner.clean_ohlcv_data's output (trade_date, stock_id,
        stock_name, open, high, low, close, volume, turnover, market_type) plus a
        `source`="FinMind" column. `stock_market_lookup` (stock_id -> "TWSE"/"TPEx",
        typically derived from FinMind's own TaiwanStockInfo `type` field) fills
        market_type; a stock_id not in the lookup gets market_type=None rather than a
        guessed value. stock_name is likewise left None here (FinMind's per-stock OHLCV
        rows don't carry it) -- callers needing a name should join against the industry
        mapping table, which already carries FinMind-sourced stock_name.
        """
        pattern = os.path.join(data_dir, "raw", "ohlcv", "finmind_*.json")
        stock_market_lookup = stock_market_lookup or {}
        rows = []
        for path in sorted(glob.glob(pattern)):
            fname = os.path.basename(path)
            if fname == "_smoke_twse_sample.json" or not fname.startswith("finmind_"):
                continue
            stock_id = fname.replace("finmind_", "").replace(".json", "")
            try:
                with open(path, "r", encoding="utf-8") as f:
                    env = json.load(f)
            except Exception as e:
                logger.warning(f"load_finmind_ohlcv_for_date: unreadable file {path}: {e}")
                continue
            for row in env.get("payload", []) or []:
                if row.get("date") != trade_date:
                    continue
                try:
                    op, hi, lo, cl = float(row["open"]), float(row["max"]), float(row["min"]), float(row["close"])
                except (KeyError, TypeError, ValueError):
                    continue
                if op <= 0 or hi <= 0 or lo <= 0 or cl <= 0:
                    continue
                rows.append({
                    "trade_date": trade_date,
                    "stock_id": stock_id,
                    "stock_name": None,
                    "open": op, "high": hi, "low": lo, "close": cl,
                    "volume": float(row.get("Trading_Volume") or 0.0),
                    "turnover": float(row.get("Trading_money") or 0.0),
                    "market_type": stock_market_lookup.get(stock_id),
                    "source": "FinMind",
                })
                break  # one row per (stock_id, trade_date) expected; first match wins
        return pd.DataFrame(rows)

    def load_finmind_institutional_for_date(self, data_dir: str, trade_date: str) -> pd.DataFrame:
        """
        Scans data/raw/institutional/finmind_<stock_id>.json. FinMind's
        TaiwanStockInstitutionalInvestorsBuySell returns 5 rows per stock per day (one
        per institutional sub-category: Foreign_Investor, Foreign_Dealer_Self,
        Investment_Trust, Dealer_self, Dealer_Hedging) -- these are summed into the
        same foreign_net_buy/investment_trust_net_buy/dealer_net_buy columns
        DataCleaner.clean_institutional_data produces (Foreign_Investor +
        Foreign_Dealer_Self both count as "foreign"; Dealer_self + Dealer_Hedging both
        count as "dealer" -- matches TWSE's own T86 'ALLBUT0999' grouping convention).
        """
        pattern = os.path.join(data_dir, "raw", "institutional", "finmind_*.json")
        FOREIGN_NAMES = {"Foreign_Investor", "Foreign_Dealer_Self"}
        TRUST_NAMES = {"Investment_Trust"}
        DEALER_NAMES = {"Dealer_self", "Dealer_Hedging"}

        by_stock: Dict[str, Dict[str, float]] = {}
        for path in sorted(glob.glob(pattern)):
            fname = os.path.basename(path)
            if not fname.startswith("finmind_"):
                continue
            stock_id = fname.replace("finmind_", "").replace(".json", "")
            try:
                with open(path, "r", encoding="utf-8") as f:
                    env = json.load(f)
            except Exception as e:
                logger.warning(f"load_finmind_institutional_for_date: unreadable file {path}: {e}")
                continue
            for row in env.get("payload", []) or []:
                if row.get("date") != trade_date:
                    continue
                name = row.get("name")
                net = float(row.get("buy") or 0.0) - float(row.get("sell") or 0.0)
                acc = by_stock.setdefault(stock_id, {"foreign": 0.0, "trust": 0.0, "dealer": 0.0, "seen": False})
                acc["seen"] = True
                if name in FOREIGN_NAMES:
                    acc["foreign"] += net
                elif name in TRUST_NAMES:
                    acc["trust"] += net
                elif name in DEALER_NAMES:
                    acc["dealer"] += net

        rows = []
        for stock_id, acc in by_stock.items():
            if not acc["seen"]:
                continue
            rows.append({
                "trade_date": trade_date,
                "stock_id": stock_id,
                "foreign_net_buy": acc["foreign"],
                "investment_trust_net_buy": acc["trust"],
                "dealer_net_buy": acc["dealer"],
                "market_type": None,
                "source": "FinMind",
            })
        return pd.DataFrame(rows)

    def load_finmind_margin_for_date(self, data_dir: str, trade_date: str) -> pd.DataFrame:
        """
        Scans data/raw/margin/finmind_<stock_id>.json
        (TaiwanStockMarginPurchaseShortSale), mapping FinMind's field names onto the
        same schema DataCleaner.clean_margin_data produces.
        """
        pattern = os.path.join(data_dir, "raw", "margin", "finmind_*.json")
        rows = []
        for path in sorted(glob.glob(pattern)):
            fname = os.path.basename(path)
            if not fname.startswith("finmind_"):
                continue
            stock_id = fname.replace("finmind_", "").replace(".json", "")
            try:
                with open(path, "r", encoding="utf-8") as f:
                    env = json.load(f)
            except Exception as e:
                logger.warning(f"load_finmind_margin_for_date: unreadable file {path}: {e}")
                continue
            for row in env.get("payload", []) or []:
                if row.get("date") != trade_date:
                    continue
                rows.append({
                    "trade_date": trade_date,
                    "stock_id": stock_id,
                    "margin_buy": row.get("MarginPurchaseBuy"),
                    "margin_sell": row.get("MarginPurchaseSell"),
                    "margin_balance": row.get("MarginPurchaseTodayBalance"),
                    "short_buy": row.get("ShortSaleBuy"),
                    "short_sell": row.get("ShortSaleSell"),
                    "short_balance": row.get("ShortSaleTodayBalance"),
                    "market_type": None,
                    "source": "FinMind",
                })
                break
        return pd.DataFrame(rows)

    @staticmethod
    def _merge_official_priority(df_official: pd.DataFrame, df_finmind: pd.DataFrame,
                                  key: str = "stock_id") -> pd.DataFrame:
        """
        Shared merge rule for all three FinMind/official merges below: rows keyed by
        `key` present in df_official win outright (official data is never overridden by
        FinMind for the same stock/date); FinMind rows fill in any stock_id df_official
        doesn't cover. The returned frame always carries a `source` column so a
        downstream reader can tell which rows came from which source, even after
        concatenation -- never silently blending values from both sources for the same
        row.
        """
        if df_official is None:
            df_official = pd.DataFrame()
        if df_finmind is None:
            df_finmind = pd.DataFrame()

        if not df_official.empty and "source" not in df_official.columns:
            df_official = df_official.copy()
            df_official["source"] = "official"

        if df_official.empty:
            return df_finmind.copy()
        if df_finmind.empty:
            return df_official.copy()

        official_ids = set(df_official[key].astype(str))
        df_finmind_gap_fill = df_finmind[~df_finmind[key].astype(str).isin(official_ids)]
        return pd.concat([df_official, df_finmind_gap_fill], ignore_index=True)

    def merge_ohlcv_sources(self, df_official: pd.DataFrame, df_finmind: pd.DataFrame) -> pd.DataFrame:
        """Official OHLCV wins on any stock_id conflict; FinMind only fills gaps."""
        return self._merge_official_priority(df_official, df_finmind)

    def merge_institutional_sources(self, df_official: pd.DataFrame, df_finmind: pd.DataFrame) -> pd.DataFrame:
        """Official institutional-flow wins on any stock_id conflict; FinMind fills gaps."""
        return self._merge_official_priority(df_official, df_finmind)

    def merge_margin_sources(self, df_official: pd.DataFrame, df_finmind: pd.DataFrame) -> pd.DataFrame:
        """Official margin data wins on any stock_id conflict; FinMind fills gaps."""
        return self._merge_official_priority(df_official, df_finmind)
