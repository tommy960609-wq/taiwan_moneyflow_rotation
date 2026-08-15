import sys
import os
import pytest
import tempfile
import shutil
import json
import pandas as pd
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from scripts.run_daily import run_pipeline
from src.config_manager import ConfigManager

def test_future_data_leakage_prevention():
    """
    Acceptance Test: Asserts that run_pipeline strictly ignores any future daily files
    and does not leak future price data during file discovery (P0-03 compliance).
    Uses hermetic local mock files to avoid any live network calls (B5 compliance).
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_data_dir = os.path.join(temp_dir, "data")
        temp_output_dir = os.path.join(temp_dir, "outputs")
        
        os.makedirs(os.path.join(temp_data_dir, "reference"), exist_ok=True)
        os.makedirs(os.path.join(temp_data_dir, "raw/ohlcv"), exist_ok=True)
        os.makedirs(os.path.join(temp_data_dir, "raw/institutional"), exist_ok=True)
        os.makedirs(os.path.join(temp_data_dir, "raw/margin"), exist_ok=True)
        os.makedirs(temp_output_dir, exist_ok=True)
        
        # 1. Copy the real stock industry mapping
        real_mapping = "C:/Workspace_CN/taiwan_moneyflow_rotation/data/reference/stock_industry_mapping.xlsx"
        temp_mapping = os.path.join(temp_data_dir, "reference/stock_industry_mapping.xlsx")
        shutil.copy(real_mapping, temp_mapping)
        
        # 2. Write price file for target date 2026-07-17 (Use separate twse/tpex names)
        price_target = {
            "payload": [{
                "Date": "1150717", "Code": "2330", "Name": "台積電",
                "OpeningPrice": 1000.0, "HighestPrice": 1010.0, "LowestPrice": 995.0, "ClosingPrice": 1005.0,
                "TradeVolume": 10000, "TradeValue": 10050000
            }]
        }
        with open(os.path.join(temp_data_dir, "raw/ohlcv/twse_prices_2026-07-17.json"), "w", encoding="utf-8") as f:
            json.dump(price_target, f)
            
        tpex_target = {
            "payload": [{
                "Date": "1150717", "SecuritiesCompanyCode": "3017", "CompanyName": "奇鋐",
                "Open": 600.0, "High": 620.0, "Low": 595.0, "Close": 615.0,
                "TradingShares": 5000, "TransactionAmount": 3075000
            }]
        }
        with open(os.path.join(temp_data_dir, "raw/ohlcv/tpex_prices_2026-07-17.json"), "w", encoding="utf-8") as f:
            json.dump(tpex_target, f)
            
        # Write mock inst and margin local snapshots to avoid network calls (hermetic test guard)
        with open(os.path.join(temp_data_dir, "raw/institutional/inst_2026-07-17.json"), "w", encoding="utf-8") as f:
            json.dump({"payload": []}, f)
        with open(os.path.join(temp_data_dir, "raw/institutional/tpex_inst_2026-07-17.json"), "w", encoding="utf-8") as f:
            json.dump({"payload": []}, f)
        with open(os.path.join(temp_data_dir, "raw/margin/margin_2026-07-17.json"), "w", encoding="utf-8") as f:
            json.dump({"payload": []}, f)
        with open(os.path.join(temp_data_dir, "raw/margin/tpex_margin_2026-07-17.json"), "w", encoding="utf-8") as f:
            json.dump({"payload": []}, f)
            
        # 3. Write a FUTURE price file for date 2026-07-18
        price_future = {
            "payload": [{
                "Date": "1150718", "Code": "9999", "Name": "未來科技",
                "OpeningPrice": 500.0, "HighestPrice": 550.0, "LowestPrice": 480.0, "ClosingPrice": 520.0,
                "TradeVolume": 20000, "TradeValue": 10400000
            }]
        }
        with open(os.path.join(temp_data_dir, "raw/ohlcv/twse_prices_2026-07-18.json"), "w", encoding="utf-8") as f:
            json.dump(price_future, f)
            
        # 4. Patch ConfigManager to point to the temporary directory path
        def mock_config_get(self, key: str, default=None):
            if key == "system.data_dir":
                return temp_data_dir
            elif key == "system.output_dir":
                return temp_output_dir
            elif key == "system.run_mode":
                return "production"
            defaults = ConfigManager().get_defaults()
            keys = key.split(".")
            val = defaults
            for k in keys:
                if isinstance(val, dict) and k in val:
                    val = val[k]
                else:
                    return default
            return val
            
        # 5. Run the daily pipeline for 2026-07-17
        with patch('src.config_manager.ConfigManager.get', mock_config_get):
            run_pipeline("2026-07-17")
            
        # 6. Verify that the generated Excel report contains 2330/3017, but absolutely does NOT contain "9999"
        expected_excel = os.path.join(temp_output_dir, "daily/MoneyFlow_Rotation_2026-07-17.xlsx")
        assert os.path.exists(expected_excel), "Excel report not generated"
        
        # Read sheet to verify (M3/SPEC_ADDENDUM B-4 renamed this sheet to the Chinese
        # "個股優先排序" as part of the 4-sheet-only V1 Excel slim-down; row 1 is a
        # title banner and row 3 (header=2, 0-indexed) holds the actual column headers)
        df_stocks = pd.read_excel(expected_excel, sheet_name="個股優先排序", header=2)
        assert "2330" in df_stocks["股票代號"].astype(str).values
        assert "9999" not in df_stocks["股票代號"].astype(str).values, "Future data leakage detected! Stock 9999 processed."
        
        print("Hermetic future data leakage prevention test completed successfully!")
