import sys
import os
import pytest
import tempfile
import shutil
import pandas as pd
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from scripts.run_daily import run_pipeline
from src.config_manager import ConfigManager


def _mock_ohlcv_for(date_roc: str, twse_close: float, tpex_close: float):
    twse = [{
        "Date": date_roc, "Code": "2330", "Name": "台積電",
        "OpeningPrice": twse_close - 5, "HighestPrice": twse_close + 5,
        "LowestPrice": twse_close - 10, "ClosingPrice": twse_close,
        "TradeVolume": 10000, "TradeValue": 10050000
    }]
    tpex = [{
        "Date": date_roc, "SecuritiesCompanyCode": "3017", "CompanyName": "奇鋐",
        "Open": tpex_close - 5, "High": tpex_close + 5, "Low": tpex_close - 10,
        "Close": tpex_close, "TradingShares": 5000, "TransactionAmount": 3075000
    }]
    return twse, tpex


def _mock_inst_for(date_roc: str):
    twse_inst = {
        "fields": ["Code", "Name", "Buy", "Sell", "Net", "", "", "", "TrustBuy", "TrustSell", "TrustNet", "DealerNet"],
        "data": [
            ["2330", "台積電", "100", "50", "50", "", "", "", "20", "10", "10", "5", "", "", "", "", "", "", "65"]
        ]
    }
    tpex_inst = [{
        "Date": date_roc, "SecuritiesCompanyCode": "3017", "CompanyName": "奇鋐",
        "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference": "50",
        "SecuritiesInvestmentTrustCompanies-Difference": "10",
        "Dealers-Difference": "5"
    }]
    return twse_inst, tpex_inst


def _mock_margin_for(date_roc: str):
    twse_margin = [{
        "Code": "2330", "Name": "台積電",
        "MarginBuy": "100", "MarginSell": "50", "MarginCash": "0", "PrevMargin": "1000", "MarginBalance": "1050",
        "MarginLimit": "5000", "ShortBuy": "10", "ShortSell": "20", "ShortCash": "0", "PrevShort": "100", "ShortBalance": "110"
    }]
    tpex_margin = [{
        "Date": date_roc, "SecuritiesCompanyCode": "3017", "CompanyName": "奇鋐",
        "MarginPurchase": "50", "MarginSales": "10", "MarginPurchaseBalance": "500",
        "ShortConvering": "5", "ShortSale": "15", "ShortSaleBalance": "80"
    }]
    return twse_margin, tpex_margin


@patch('src.data_loader.DataLoader.fetch_twse_ohlcv_all')
@patch('src.data_loader.DataLoader.fetch_tpex_ohlcv_all')
@patch('src.data_loader.DataLoader.fetch_twse_institutional_all')
@patch('src.data_loader.DataLoader.fetch_tpex_institutional_all')
@patch('src.data_loader.DataLoader.fetch_twse_margin_all')
@patch('src.data_loader.DataLoader.fetch_tpex_margin_all')
def test_run_pipeline_two_consecutive_real_days_with_institutional_merge(
        mock_tpex_margin, mock_twse_margin, mock_tpex_inst, mock_twse_inst,
        mock_tpex_price, mock_twse_price):
    """
    Regression test for the M4 latent merge bug (M5b Acceptance Report §6 finding a):
    scripts/run_daily.py's institutional-column merge onto df_stock_features_today had
    no `suffixes=` argument. Day 1's run persists stock_features_<date1>.csv WITH
    foreign_net_buy/investment_trust_net_buy/dealer_net_buy columns already merged in
    (M4 behavior). Day 2's _load_stock_history() concatenates that CSV into
    df_stock_history_full, so df_stock_features_today already carries those columns
    BEFORE the second merge is attempted -- pandas raises
    "Passing 'suffixes' which cause duplicate columns ... is not allowed" (or, pre-fix,
    a plain MergeError for the un-suffixed merge) on day 2's df_inst merge.

    Before the fix: this test must FAIL (crash) on day 2.
    After the fix: this test must PASS for both days, with day 2's institutional
    columns correctly reflecting day 2's fresh institutional data (not stale/duplicated
    day 1 values).
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_data_dir = os.path.join(temp_dir, "data")
        temp_output_dir = os.path.join(temp_dir, "outputs")

        os.makedirs(os.path.join(temp_data_dir, "reference"), exist_ok=True)
        os.makedirs(os.path.join(temp_data_dir, "raw/ohlcv"), exist_ok=True)
        os.makedirs(os.path.join(temp_data_dir, "raw/institutional"), exist_ok=True)
        os.makedirs(os.path.join(temp_data_dir, "raw/margin"), exist_ok=True)
        os.makedirs(temp_output_dir, exist_ok=True)

        real_mapping = "C:/Workspace_CN/taiwan_moneyflow_rotation/data/reference/stock_industry_mapping.xlsx"
        temp_mapping = os.path.join(temp_data_dir, "reference/stock_industry_mapping.xlsx")
        shutil.copy(real_mapping, temp_mapping)

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
            # Force every category to go through the live-loader mock path (never
            # read a local raw JSON snapshot), matching the existing hermetic
            # single-day test's convention -- except processed/reference files,
            # which DO need to be read for real (that's the whole point: day 2 must
            # see day 1's real persisted stock_features_<date1>.csv on disk).
            if "raw" in path:
                return False
            return orig_exists(path)

        with patch('src.config_manager.ConfigManager.get', mock_config_get):
            with patch('os.path.exists', side_effect_exists):
                # Day 1: 2026-07-16
                twse1, tpex1 = _mock_ohlcv_for("1150716", 1005.0, 615.0)
                mock_twse_price.return_value = twse1
                mock_tpex_price.return_value = tpex1
                mock_twse_inst.return_value, mock_tpex_inst.return_value = _mock_inst_for("1150716")
                mock_twse_margin.return_value, mock_tpex_margin.return_value = _mock_margin_for("1150716")

                audit_day1 = run_pipeline("2026-07-16")
                assert audit_day1["status"] == "SUCCESS", f"Day 1 unexpectedly not SUCCESS: {audit_day1}"

                # Confirm day 1's persisted CSV really does carry the institutional
                # columns (the precondition that triggers the bug on day 2).
                day1_csv = os.path.join(temp_data_dir, "processed", "stock_features_2026-07-16.csv")
                assert os.path.exists(day1_csv)
                df_day1 = pd.read_csv(day1_csv)
                for col in ["foreign_net_buy", "investment_trust_net_buy", "dealer_net_buy"]:
                    assert col in df_day1.columns, f"Day 1 CSV missing precondition column {col}"

                # Day 2: 2026-07-17, with DIFFERENT institutional net-buy values so we
                # can assert day 2's merge actually reflects fresh data, not a stale
                # duplicate from day 1.
                twse2, tpex2 = _mock_ohlcv_for("1150717", 1020.0, 630.0)
                mock_twse_price.return_value = twse2
                mock_tpex_price.return_value = tpex2
                twse_inst2 = {
                    "fields": ["Code", "Name", "Buy", "Sell", "Net", "", "", "", "TrustBuy", "TrustSell", "TrustNet", "DealerNet"],
                    "data": [
                        ["2330", "台積電", "300", "50", "250", "", "", "", "40", "10", "30", "15", "", "", "", "", "", "", "65"]
                    ]
                }
                tpex_inst2 = [{
                    "Date": "1150717", "SecuritiesCompanyCode": "3017", "CompanyName": "奇鋐",
                    "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference": "250",
                    "SecuritiesInvestmentTrustCompanies-Difference": "30",
                    "Dealers-Difference": "15"
                }]
                mock_twse_inst.return_value = twse_inst2
                mock_tpex_inst.return_value = tpex_inst2
                mock_twse_margin.return_value, mock_tpex_margin.return_value = _mock_margin_for("1150717")

                # This is the line that crashed pre-fix.
                audit_day2 = run_pipeline("2026-07-17", prev_date="2026-07-16")

        assert audit_day2["status"] == "SUCCESS", f"Day 2 unexpectedly not SUCCESS: {audit_day2}"

        day2_csv = os.path.join(temp_data_dir, "processed", "stock_features_2026-07-17.csv")
        assert os.path.exists(day2_csv)
        df_day2 = pd.read_csv(day2_csv, dtype={"stock_id": str})
        for col in ["foreign_net_buy", "investment_trust_net_buy", "dealer_net_buy"]:
            assert col in df_day2.columns, f"Day 2 CSV missing column {col}"
            # No pandas-suffixed duplicate columns (e.g. foreign_net_buy_x/_y) leaked
            # into the persisted output.
            assert f"{col}_x" not in df_day2.columns
            assert f"{col}_y" not in df_day2.columns

        row_2330 = df_day2[df_day2["stock_id"] == "2330"].iloc[0]
        # Day 2's foreign_net_buy for 2330 must reflect day 2's fresh 250 net buy
        # (TWSE T86 "Net" column), not day 1's 50 or a stale/duplicated value.
        assert row_2330["foreign_net_buy"] == 250, (
            f"Expected day 2's fresh foreign_net_buy=250 for 2330, got {row_2330['foreign_net_buy']}"
        )
