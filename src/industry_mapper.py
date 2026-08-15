import pandas as pd
from typing import Optional, Dict
from loguru import logger

class IndustryMapper:
    def __init__(self, mapping_df: Optional[pd.DataFrame] = None):
        self.mapping_df = mapping_df
        self.mapping_dict: Dict[str, dict] = {}
        if mapping_df is not None:
            self.build_mapping_cache()

    def build_mapping_cache(self):
        if self.mapping_df is None or self.mapping_df.empty:
            return
            
        self.mapping_dict = {}
        df = self.mapping_df.copy()
        df["stock_id"] = df["stock_id"].astype(str).str.strip()
        df["stock_id"] = df["stock_id"].apply(lambda x: x[:-2] if x.endswith(".0") else x)
        
        for _, row in df.iterrows():
            ticker = row["stock_id"]
            self.mapping_dict[ticker] = {
                "stock_name": row.get("stock_name", ""),
                "primary_sector": row.get("primary_sector", "待分類"),
                "secondary_sector": row.get("secondary_sector", "待分類"),
                "theme_1": row.get("theme_1", None),
                "theme_2": row.get("theme_2", None),
                "theme_3": row.get("theme_3", None),
                "supply_chain_role": row.get("supply_chain_role", None)
            }

    def map_stock(self, ticker: str) -> dict:
        ticker = str(ticker).strip()
        if ticker.endswith(".0"):
            ticker = ticker[:-2]
            
        if ticker in self.mapping_dict:
            return self.mapping_dict[ticker]
            
        return {
            "stock_name": "未知",
            "primary_sector": "待分類",
            "secondary_sector": "待分類",
            "theme_1": None,
            "theme_2": None,
            "theme_3": None,
            "supply_chain_role": None
        }

    def map_dataframe(self, df_prices: pd.DataFrame) -> pd.DataFrame:
        if df_prices.empty:
            return df_prices
            
        mapped_rows = []
        for _, row in df_prices.iterrows():
            ticker = row["stock_id"]
            info = self.map_stock(ticker)
            merged = {**row.to_dict(), **info}
            mapped_rows.append(merged)
            
        return pd.DataFrame(mapped_rows)

    def calculate_coverage(self, df_mapped: pd.DataFrame) -> float:
        if df_mapped.empty:
            return 0.0
        total_stocks = len(df_mapped)
        mapped_stocks = df_mapped[df_mapped["primary_sector"] != "待分類"]
        coverage = len(mapped_stocks) / total_stocks
        logger.info(f"Industry mapping coverage: {coverage:.2%} ({len(mapped_stocks)}/{total_stocks} stocks mapped)")
        return coverage
