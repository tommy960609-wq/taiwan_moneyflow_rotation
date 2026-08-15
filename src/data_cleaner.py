import re
import pandas as pd
from typing import Optional, List, Dict
from loguru import logger

from src.leaderboard_reconciliation import (
    reconcile_leaderboard_vs_finmind,
    summarize_reconciliation,
)

class DataCleaner:
    def __init__(self):
        self.equity_ticker_pattern = re.compile(r"^[0-9A-Z]{4,5}$")
        self.exclude_names = ["ETF", "權證", "購", "售", "牛", "熊", "展", "存託憑證", "TDR", "受益憑證", "債"]

    def clean_ticker(self, ticker: str) -> str:
        if pd.isna(ticker):
            return ""
        t = str(ticker).strip()
        if t.endswith(".0"):
            t = t[:-2]
        if t.isdigit() and len(t) < 4:
            t = t.zfill(4)
        return t

    def is_valid_equity(self, ticker: str, name: str) -> bool:
        ticker = self.clean_ticker(ticker)
        if not self.equity_ticker_pattern.match(ticker):
            return False
        
        for keyword in self.exclude_names:
            if keyword in name:
                return False
                
        if ticker.startswith(("005", "006", "007", "008", "009")) and len(ticker) in (4, 5, 6):
            return False
            
        return True

    def parse_roc_date(self, roc_date_str: str) -> Optional[str]:
        if not roc_date_str:
            return None
        try:
            s = str(roc_date_str).replace("/", "").replace("-", "").strip()
            if len(s) == 7: # e.g. '1150716'
                roc_year = int(s[:3])
                month = s[3:5]
                day = s[5:]
                greg_year = roc_year + 1911
                return f"{greg_year}-{month}-{day}"
            elif len(s) == 8: # e.g. '20260716'
                return f"{s[:4]}-{s[4:6]}-{s[6:]}"
            return None
        except Exception:
            return None

    def clean_ohlcv_data(self, raw_list: list, trade_date: str, market_type: Optional[str] = None) -> pd.DataFrame:
        if not raw_list:
            return pd.DataFrame()
            
        cleaned = []
        for row in raw_list:
            try:
                raw_date = row.get("Date") or row.get("trade_date")
                parsed_date = self.parse_roc_date(raw_date)
                if parsed_date and parsed_date != trade_date:
                    continue
                
                ticker = self.clean_ticker(
                    row.get("Code") or 
                    row.get("SecuritiesCompanyCode") or 
                    row.get("stock_id") or ""
                )
                name = (
                    row.get("Name") or 
                    row.get("CompanyName") or 
                    row.get("stock_name") or ""
                ).strip()
                
                if not ticker or not name:
                    continue
                    
                if not self.is_valid_equity(ticker, name):
                    continue
                
                op_val = row.get("OpeningPrice") or row.get("Open") or row.get("open")
                hp_val = row.get("HighestPrice") or row.get("High") or row.get("high")
                lp_val = row.get("LowestPrice") or row.get("Low") or row.get("low")
                cp_val = row.get("ClosingPrice") or row.get("Close") or row.get("close")
                
                vol_val = row.get("TradeVolume") or row.get("TradingShares") or row.get("Volume") or row.get("volume")
                turnover_val = row.get("TradeValue") or row.get("TransactionAmount") or row.get("Amount") or row.get("turnover")
                
                def to_float(val) -> float:
                    if val is None:
                        return 0.0
                    if isinstance(val, (int, float)):
                        return float(val)
                    s = str(val).replace(",", "").strip()
                    if s == "" or s == "--":
                        return 0.0
                    return float(s)

                op = to_float(op_val)
                hp = to_float(hp_val)
                lp = to_float(lp_val)
                cp = to_float(cp_val)
                vol = to_float(vol_val)
                turnover = to_float(turnover_val)
                
                if op <= 0 or hp <= 0 or lp <= 0 or cp <= 0:
                    continue
                
                mtype = market_type
                if not mtype:
                    if "SecuritiesCompanyCode" in row or "CompanyName" in row or "TradingShares" in row:
                        mtype = "TPEx"
                    else:
                        mtype = "TWSE"
                
                cleaned.append({
                    "trade_date": trade_date,
                    "stock_id": ticker,
                    "stock_name": name,
                    "open": op,
                    "high": hp,
                    "low": lp,
                    "close": cp,
                    "volume": vol,
                    "turnover": turnover,
                    "market_type": mtype
                })
            except Exception as e:
                continue
                
        df = pd.DataFrame(cleaned)
        if not df.empty:
            df = df.drop_duplicates(subset=["stock_id"])
        return df

    def _to_optional_float(self, val) -> Optional[float]:
        if val is None:
            return None
        s = str(val).replace(",", "").strip()
        if s == "" or s == "--":
            return None
        try:
            return float(s)
        except ValueError:
            return None

    def clean_institutional_data(self, raw_twse: Optional[dict], raw_tpex: Optional[List[dict]], trade_date: str) -> pd.DataFrame:
        """
        Cleans and normalizes institutional flow statistics for TWSE and TPEx markets (B1/B-02 compliance).
        """
        cleaned = []
        
        # 1. Parse TWSE ({fields, data} format)
        if raw_twse and isinstance(raw_twse, dict) and "data" in raw_twse:
            rows = raw_twse["data"]
            for row in rows:
                if len(row) < 12:
                    continue
                ticker = self.clean_ticker(row[0])
                if not ticker or not ticker.isdigit() or len(ticker) != 4:
                    continue
                # Position index mapping: Index 0=Code, Index 4=Foreign Net, Index 10=Trust Net, Index 11=Dealer Net
                cleaned.append({
                    "trade_date": trade_date,
                    "stock_id": ticker,
                    "foreign_net_buy": self._to_optional_float(row[4]),
                    "investment_trust_net_buy": self._to_optional_float(row[10]),
                    "dealer_net_buy": self._to_optional_float(row[11]),
                    "market_type": "TWSE"
                })
        elif raw_twse and isinstance(raw_twse, list):
            # Fallback if already converted to dict list
            for row in raw_twse:
                rep_date = row.get("_report_date_") or row.get("Date")
                if rep_date:
                    if rep_date != trade_date.replace("-", "") and rep_date != trade_date:
                        continue
                
                ticker = self.clean_ticker(row.get("Code") or row.get("stock_id") or row.get("證券代號"))
                if not ticker or not ticker.isdigit() or len(ticker) != 4:
                    continue
                cleaned.append({
                    "trade_date": trade_date,
                    "stock_id": ticker,
                    "foreign_net_buy": self._to_optional_float(row.get("ForeignInvestorsIncludeMainlandAreaInvestors-Difference") or row.get("foreign_net_buy") or row.get("外陸資買賣超股數(不含外資自營商)")),
                    "investment_trust_net_buy": self._to_optional_float(row.get("SecuritiesInvestmentTrustCompanies-Difference") or row.get("investment_trust_net_buy") or row.get("投信買賣超股數")),
                    "dealer_net_buy": self._to_optional_float(row.get("Dealers-Difference") or row.get("dealer_net_buy") or row.get("自營商買賣超股數")),
                    "market_type": "TWSE"
                })

        # 2. Parse TPEx (dict list format)
        if raw_tpex and isinstance(raw_tpex, list):
            for row in raw_tpex:
                raw_date = row.get("Date")
                if raw_date:
                    parsed = self.parse_roc_date(raw_date)
                    if parsed and parsed != trade_date:
                        continue
                ticker = self.clean_ticker(row.get("SecuritiesCompanyCode") or row.get("stock_id"))
                if not ticker or not ticker.isdigit() or len(ticker) != 4:
                    continue
                # B1 compliance: Map exact TPEx foreign flow difference key
                foreign_val = row.get("Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference") or row.get("ForeignInvestorsIncludeMainlandAreaInvestors-Difference")
                cleaned.append({
                    "trade_date": trade_date,
                    "stock_id": ticker,
                    "foreign_net_buy": self._to_optional_float(foreign_val),
                    "investment_trust_net_buy": self._to_optional_float(row.get("SecuritiesInvestmentTrustCompanies-Difference")),
                    "dealer_net_buy": self._to_optional_float(row.get("Dealers-Difference")),
                    "market_type": "TPEx"
                })
                
        df = pd.DataFrame(cleaned)
        if not df.empty:
            df = df.drop_duplicates(subset=["stock_id"])
        return df

    def clean_margin_data(self, raw_twse: Optional[List[dict]], raw_tpex: Optional[List[dict]], trade_date: str) -> pd.DataFrame:
        """
        Cleans and normalizes margin balances for TWSE and TPEx markets (B3/B-02 compliance).
        """
        cleaned = []
        
        # 1. Parse TWSE
        if raw_twse and isinstance(raw_twse, list):
            for row in raw_twse:
                # Can be a list or dict depending on wrapping
                if isinstance(row, list) and len(row) >= 13:
                    ticker = self.clean_ticker(row[0])
                    if not ticker or not ticker.isdigit() or len(ticker) != 4:
                        continue
                    cleaned.append({
                        "trade_date": trade_date,
                        "stock_id": ticker,
                        "margin_buy": self._to_optional_float(row[2]),
                        "margin_sell": self._to_optional_float(row[3]),
                        "margin_balance": self._to_optional_float(row[6]),
                        "short_buy": self._to_optional_float(row[8]),
                        "short_sell": self._to_optional_float(row[9]),
                        "short_balance": self._to_optional_float(row[12]),
                        "market_type": "TWSE"
                    })
                elif isinstance(row, dict):
                    # Direct dict keys map by order (first CP950 scrambled key is Code, index 2 is buy, etc)
                    vals = list(row.values())
                    if len(vals) >= 13:
                        ticker = self.clean_ticker(vals[0])
                        if not ticker or not ticker.isdigit() or len(ticker) != 4:
                            continue
                        cleaned.append({
                            "trade_date": trade_date,
                            "stock_id": ticker,
                            "margin_buy": self._to_optional_float(vals[2]),
                            "margin_sell": self._to_optional_float(vals[3]),
                            "margin_balance": self._to_optional_float(vals[6]),
                            "short_buy": self._to_optional_float(vals[8]),
                            "short_sell": self._to_optional_float(vals[9]),
                            "short_balance": self._to_optional_float(vals[12]),
                            "market_type": "TWSE"
                        })

        # 2. Parse TPEx
        if raw_tpex and isinstance(raw_tpex, list):
            for row in raw_tpex:
                raw_date = row.get("Date")
                if raw_date:
                    parsed = self.parse_roc_date(raw_date)
                    if parsed and parsed != trade_date:
                        continue
                ticker = self.clean_ticker(row.get("SecuritiesCompanyCode") or row.get("stock_id"))
                if not ticker or not ticker.isdigit() or len(ticker) != 4:
                    continue
                cleaned.append({
                    "trade_date": trade_date,
                    "stock_id": ticker,
                    "margin_buy": self._to_optional_float(row.get("MarginPurchase")),
                    "margin_sell": self._to_optional_float(row.get("MarginSales")),
                    "margin_balance": self._to_optional_float(row.get("MarginPurchaseBalance")),
                    "short_buy": self._to_optional_float(row.get("ShortConvering")),
                    "short_sell": self._to_optional_float(row.get("ShortSale")),
                    "short_balance": self._to_optional_float(row.get("ShortSaleBalance")),
                    "market_type": "TPEx"
                })
                
        df = pd.DataFrame(cleaned)
        if not df.empty:
            df = df.drop_duplicates(subset=["stock_id"])
        return df

    def reconcile_with_leaderboard(self, df_prices: pd.DataFrame, df_leaderboard: pd.DataFrame,
                                   df_prev_prices: Optional[pd.DataFrame] = None) -> dict:
        reconciliation_log = {
            "status": "MATCH",
            "deviation_count": 0,
            "details": [],
            "basis": "prev_close_to_close",
        }
        if df_prices.empty or df_leaderboard.empty:
            reconciliation_log["status"] = "INCOMPLETE"
            return reconciliation_log

        df_leaderboard = df_leaderboard.copy()
        if "stock_id" not in df_leaderboard.columns:
            reconciliation_log["status"] = "INCOMPLETE"
            reconciliation_log["details"].append("Leaderboard missing stock_id column.")
            return reconciliation_log
        if "return_pct" not in df_leaderboard.columns and "漲跌幅" in df_leaderboard.columns:
            df_leaderboard = df_leaderboard.rename(columns={"漲跌幅": "return_pct"})
        if "return_pct" not in df_leaderboard.columns:
            reconciliation_log["status"] = "INCOMPLETE"
            reconciliation_log["details"].append("Leaderboard missing return_pct/漲跌幅 column.")
            return reconciliation_log

        df_leaderboard["stock_id"] = df_leaderboard["stock_id"].apply(self.clean_ticker)
        df_leaderboard["return_pct"] = pd.to_numeric(df_leaderboard["return_pct"], errors="coerce")
        df_leaderboard = df_leaderboard.dropna(subset=["stock_id", "return_pct"])
        if df_leaderboard.empty:
            reconciliation_log["status"] = "INCOMPLETE"
            return reconciliation_log

        if "trade_date" not in df_leaderboard.columns:
            price_dates = df_prices.get("trade_date", pd.Series(dtype=object)).dropna().unique()
            if len(price_dates) == 1:
                df_leaderboard["trade_date"] = price_dates[0]
            else:
                reconciliation_log["status"] = "INCOMPLETE"
                reconciliation_log["details"].append("Leaderboard missing trade_date and price date is ambiguous.")
                return reconciliation_log

        frames = []
        if df_prev_prices is not None and not df_prev_prices.empty:
            frames.append(df_prev_prices.copy())
        frames.append(df_prices.copy())
        df_reconcile_prices = pd.concat(frames, ignore_index=True)

        reconciled = reconcile_leaderboard_vs_finmind(df_leaderboard, df_reconcile_prices)
        summary = summarize_reconciliation(reconciled)
        reconciliation_log["summary"] = summary
        if summary["rows_with_finmind_comparison"] == 0:
            reconciliation_log["status"] = "INCOMPLETE"
            reconciliation_log["details"].append("No previous-close comparison available.")
            return reconciliation_log

        reconciliation_log["deviation_count"] = summary["rows_exceeding_threshold"]
        if reconciliation_log["deviation_count"] > 0:
            reconciliation_log["status"] = "WARNING_HIGH_DEVIATION"
            deviated = reconciled[reconciled["deviation_exceeds_threshold"]].head(20)
            for _, row in deviated.iterrows():
                reconciliation_log["details"].append(
                    f"Ticker {row['stock_id']}: "
                    f"finmind_prevclose_return={row['finmind_prevclose_return_pct']:.2f}%, "
                    f"board_return={row['return_pct']:.2f}%, "
                    f"diff={row['abs_deviation_pct']:.2f}%"
                )
            logger.warning(f"Reconciliation deviation detected: {reconciliation_log['deviation_count']} stocks differ.")

        return reconciliation_log
