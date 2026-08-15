import sys
import os
import pytest
import tempfile
import shutil
import pandas as pd
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from scripts.run_daily import run_pipeline
from src.config_manager import ConfigManager

@patch('src.data_loader.DataLoader.fetch_twse_ohlcv_all')
@patch('src.data_loader.DataLoader.fetch_tpex_ohlcv_all')
@patch('src.data_loader.DataLoader.fetch_twse_institutional_all')
@patch('src.data_loader.DataLoader.fetch_tpex_institutional_all')
@patch('src.data_loader.DataLoader.fetch_twse_margin_all')
@patch('src.data_loader.DataLoader.fetch_tpex_margin_all')
def test_run_pipeline_entrypoint(mock_tpex_margin,
                                 mock_twse_margin,
                                 mock_tpex_inst,
                                 mock_twse_inst,
                                 mock_tpex_price,
                                 mock_twse_price):
    """
    Integration Test: Asserts that run_pipeline executes hermetically without network warnings
    and successfully generates the Excel report in a temporary directory (B5 compliance).
    """
    # 1. Create temporary directory for hermetic execution
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_data_dir = os.path.join(temp_dir, "data")
        temp_output_dir = os.path.join(temp_dir, "outputs")
        
        os.makedirs(os.path.join(temp_data_dir, "reference"), exist_ok=True)
        os.makedirs(os.path.join(temp_data_dir, "raw/ohlcv"), exist_ok=True)
        os.makedirs(os.path.join(temp_data_dir, "raw/institutional"), exist_ok=True)
        os.makedirs(os.path.join(temp_data_dir, "raw/margin"), exist_ok=True)
        os.makedirs(temp_output_dir, exist_ok=True)
        
        # 2. Copy the real industry mapping excel to temp data dir
        real_mapping = "C:/Workspace_CN/taiwan_moneyflow_rotation/data/reference/stock_industry_mapping.xlsx"
        temp_mapping = os.path.join(temp_data_dir, "reference/stock_industry_mapping.xlsx")
        shutil.copy(real_mapping, temp_mapping)
        
        # 3. Setup mock data loaders returns (TWSE 2330 & TPEx 3017)
        mock_twse_price.return_value = [{
            "Date": "1150717", "Code": "2330", "Name": "台積電",
            "OpeningPrice": 1000.0, "HighestPrice": 1010.0, "LowestPrice": 995.0, "ClosingPrice": 1005.0,
            "TradeVolume": 10000, "TradeValue": 10050000
        }]
        mock_tpex_price.return_value = [{
            "Date": "1150717", "SecuritiesCompanyCode": "3017", "CompanyName": "奇鋐",
            "Open": 600.0, "High": 620.0, "Low": 595.0, "Close": 615.0,
            "TradingShares": 5000, "TransactionAmount": 3075000
        }]
        
        # Mock TWSE T86 inst format {fields, data}
        mock_twse_inst.return_value = {
            "fields": ["Code", "Name", "Buy", "Sell", "Net", "", "", "", "TrustBuy", "TrustSell", "TrustNet", "DealerNet"],
            "data": [
                ["2330", "台積電", "100", "50", "50", "", "", "", "20", "10", "10", "5", "", "", "", "", "", "", "65"]
            ]
        }
        # Mock TPEx inst list format
        mock_tpex_inst.return_value = [{
            "Date": "1150717", "SecuritiesCompanyCode": "3017", "CompanyName": "奇鋐",
            "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference": "50",
            "SecuritiesInvestmentTrustCompanies-Difference": "10",
            "Dealers-Difference": "5"
        }]
        
        # Mock margin loaders
        mock_twse_margin.return_value = [{
            "Code": "2330", "Name": "台積電",
            "MarginBuy": "100", "MarginSell": "50", "MarginCash": "0", "PrevMargin": "1000", "MarginBalance": "1050",
            "MarginLimit": "5000", "ShortBuy": "10", "ShortSell": "20", "ShortCash": "0", "PrevShort": "100", "ShortBalance": "110"
        }]
        mock_tpex_margin.return_value = [{
            "Date": "1150717", "SecuritiesCompanyCode": "3017", "CompanyName": "奇鋐",
            "MarginPurchase": "50", "MarginSales": "10", "MarginPurchaseBalance": "500",
            "ShortConvering": "5", "ShortSale": "15", "ShortSaleBalance": "80"
        }]
        
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
            
        orig_exists = os.path.exists
        def side_effect_exists(path):
            if "raw" in path:
                return False
            return orig_exists(path)

        for observe_target, expected_log_message in (
            ("scripts.run_daily.build_observe_rankings", "Observe rankings unavailable (non-fatal)"),
            ("scripts.run_daily.write_observe_rankings", "Observe rankings write failed (non-fatal)"),
        ):
            with patch('src.config_manager.ConfigManager.get', mock_config_get), \
                 patch('os.path.exists', side_effect_exists), \
                 patch(observe_target, side_effect=RuntimeError("observe regression failure")):
                audit = run_pipeline("2026-07-17")

            assert audit["status"] == "SUCCESS"
            assert not any(
                os.path.basename(path) == "rankings_2026-07-17.json"
                for path in audit["output_files"]
            )
            with open(os.path.join(temp_output_dir, "logs", "run_2026-07-17.log"), encoding="utf-8") as handle:
                assert expected_log_message in handle.read()
                
        # 5. Assert loaders were successfully called
        assert mock_twse_price.called, "TWSE price loader not called"
        assert mock_tpex_price.called, "TPEx price loader not called"
        assert mock_twse_inst.called, "TWSE institutional loader not called"
        assert mock_tpex_inst.called, "TPEx institutional loader not called"
        assert mock_twse_margin.called, "TWSE margin loader not called"
        assert mock_tpex_margin.called, "TPEx margin loader not called"
        
        # 6. Verify Excel generation inside the temporary directory
        expected_excel = os.path.join(temp_output_dir, "daily/MoneyFlow_Rotation_2026-07-17.xlsx")
        assert os.path.exists(expected_excel), f"Expected Excel report at {expected_excel} was not generated"

        print("Hermetic daily runner integration test completed successfully!")
