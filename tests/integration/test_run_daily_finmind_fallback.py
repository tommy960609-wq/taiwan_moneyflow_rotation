"""
FinMind same-day OHLCV fallback -- DISABLED as of 2026-07-20 (user request: FinMind
quota exhausted).

History: an earlier milestone (M9) wired a same-day FinMind fallback so that when the
official TWSE OpenAPI STOCK_DAY_ALL endpoint was badly delayed (observed 2026-07-20:
still serving 7/17 data at 22:45 on a real trading day), the pipeline would fill the
gap from FinMind instead of BLOCKing. In practice FinMind has no whole-market single
call and the free-tier quota exhausted after ~130 stocks (HTTP 402), giving only ~12%
coverage while burning the user's quota -- so the fallback was removed. The
`_fetch_finmind_ohlcv_fallback` helper remains in run_daily.py but is no longer called.

These tests now pin the DISABLED contract:
  1. Official empty + FinMind would have data -> pipeline still BLOCKs
     (fallback removed), and FinMind is NEVER called (no quota burned).
  2. Official data present -> succeeds normally, FinMind never called.
The date-consistency guard on the official path itself is unchanged and covered
elsewhere.
"""

import os
import sys
import json
import tempfile
import shutil
from unittest.mock import patch

import pandas as pd
from loguru import logger

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from scripts.run_daily import run_pipeline
from src.config_manager import ConfigManager
from src.finmind_fetcher import FinMindFetcher


def _mock_config_get_factory(temp_data_dir, temp_output_dir):
    def mock_config_get(self, key: str, default=None):
        if key == "system.data_dir":
            return temp_data_dir
        elif key == "system.output_dir":
            return temp_output_dir
        elif key == "system.run_mode":
            return "production"
        defaults = ConfigManager().get_defaults()
        val = defaults
        for k in key.split("."):
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val
    return mock_config_get


def _setup_temp_project(temp_dir: str, write_stock_info: bool = True):
    temp_data_dir = os.path.join(temp_dir, "data")
    temp_output_dir = os.path.join(temp_dir, "outputs")

    os.makedirs(os.path.join(temp_data_dir, "reference"), exist_ok=True)
    os.makedirs(os.path.join(temp_data_dir, "raw/ohlcv"), exist_ok=True)
    os.makedirs(os.path.join(temp_data_dir, "raw/institutional"), exist_ok=True)
    os.makedirs(os.path.join(temp_data_dir, "raw/margin"), exist_ok=True)
    os.makedirs(os.path.join(temp_data_dir, "raw/fundamentals"), exist_ok=True)
    os.makedirs(temp_output_dir, exist_ok=True)

    real_mapping = "C:/Workspace_CN/taiwan_moneyflow_rotation/data/reference/stock_industry_mapping.xlsx"
    shutil.copy(real_mapping, os.path.join(temp_data_dir, "reference/stock_industry_mapping.xlsx"))

    if write_stock_info:
        stock_info = {
            "metadata": {"source": "FinMind", "dataset": "TaiwanStockInfo"},
            "payload": [
                {"stock_id": "2330", "stock_name": "台積電", "type": "twse", "date": "2020-01-01"},
                {"stock_id": "3017", "stock_name": "奇鋐", "type": "tpex", "date": "2020-01-01"},
            ],
        }
        with open(os.path.join(temp_data_dir, "raw/fundamentals/finmind_stock_info.json"), "w", encoding="utf-8") as f:
            json.dump(stock_info, f, ensure_ascii=False)

    return temp_data_dir, temp_output_dir


def _mock_inst_margin(mock_twse_inst, mock_tpex_inst, mock_twse_margin, mock_tpex_margin):
    mock_twse_inst.return_value = {
        "fields": ["Code", "Name", "Buy", "Sell", "Net", "", "", "", "TrustBuy", "TrustSell", "TrustNet", "DealerNet"],
        "data": [["2330", "台積電", "100", "50", "50", "", "", "", "20", "10", "10", "5", "", "", "", "", "", "", "65"]],
    }
    mock_tpex_inst.return_value = [{
        "Date": "1150720", "SecuritiesCompanyCode": "3017", "CompanyName": "奇鋐",
        "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference": "50",
        "SecuritiesInvestmentTrustCompanies-Difference": "10",
        "Dealers-Difference": "5",
    }]
    mock_twse_margin.return_value = [{
        "Code": "2330", "Name": "台積電",
        "MarginBuy": "100", "MarginSell": "50", "MarginCash": "0", "PrevMargin": "1000", "MarginBalance": "1050",
        "MarginLimit": "5000", "ShortBuy": "10", "ShortSell": "20", "ShortCash": "0", "PrevShort": "100", "ShortBalance": "110",
    }]
    mock_tpex_margin.return_value = [{
        "Date": "1150720", "SecuritiesCompanyCode": "3017", "CompanyName": "奇鋐",
        "MarginPurchase": "50", "MarginSales": "10", "MarginPurchaseBalance": "500",
        "ShortConvering": "5", "ShortSale": "15", "ShortSaleBalance": "80",
    }]


def _side_effect_exists_factory():
    orig_exists = os.path.exists

    def side_effect_exists(path):
        if "raw" in path and "finmind_stock_info" not in path:
            return False
        return orig_exists(path)
    return side_effect_exists


@patch("src.data_loader.DataLoader.fetch_twse_ohlcv_all")
@patch("src.data_loader.DataLoader.fetch_tpex_ohlcv_all")
@patch("src.data_loader.DataLoader.fetch_twse_institutional_all")
@patch("src.data_loader.DataLoader.fetch_tpex_institutional_all")
@patch("src.data_loader.DataLoader.fetch_twse_margin_all")
@patch("src.data_loader.DataLoader.fetch_tpex_margin_all")
@patch("src.finmind_fetcher.FinMindFetcher.fetch_today_ohlcv_for_universe")
def test_official_empty_stays_blocked_finmind_not_called(
    mock_finmind_fetch, mock_tpex_margin, mock_twse_margin,
    mock_tpex_inst, mock_twse_inst, mock_tpex_price, mock_twse_price,
):
    """
    DISABLED-fallback contract: official TWSE OHLCV empty (stale-date rows already
    dropped upstream). Even though FinMind *could* serve today's data, the fallback is
    removed, so the pipeline stays BLOCKED_MISSING_MARKET and FinMind is never called
    (no quota burned). This is the whole point of the 2026-07-20 removal.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_data_dir, temp_output_dir = _setup_temp_project(temp_dir)

        mock_twse_price.return_value = []
        mock_tpex_price.return_value = [{
            "Date": "1150720", "SecuritiesCompanyCode": "3017", "CompanyName": "奇鋐",
            "Open": 610.0, "High": 625.0, "Low": 605.0, "Close": 620.0,
            "TradingShares": 5000, "TransactionAmount": 3075000,
        }]
        _mock_inst_margin(mock_twse_inst, mock_tpex_inst, mock_twse_margin, mock_tpex_margin)

        with patch("src.config_manager.ConfigManager.get", _mock_config_get_factory(temp_data_dir, temp_output_dir)):
            with patch("os.path.exists", _side_effect_exists_factory()):
                try:
                    audit = run_pipeline("2026-07-20")
                finally:
                    logger.remove()

        assert audit["status"] == "BLOCKED_MISSING_MARKET", (
            f"With fallback removed, official-empty TWSE must stay BLOCKED, got: {audit}"
        )
        assert audit["price_source_twse"] == "missing"
        assert not mock_finmind_fetch.called, (
            "FinMind fallback is disabled -- it must NOT be called even when official data is missing"
        )

        expected_excel = os.path.join(temp_output_dir, "daily", "MoneyFlow_Rotation_2026-07-20.xlsx")
        assert not os.path.exists(expected_excel), "No report should be produced from a blocked run"


@patch("src.data_loader.DataLoader.fetch_twse_ohlcv_all")
@patch("src.data_loader.DataLoader.fetch_tpex_ohlcv_all")
@patch("src.data_loader.DataLoader.fetch_twse_institutional_all")
@patch("src.data_loader.DataLoader.fetch_tpex_institutional_all")
@patch("src.data_loader.DataLoader.fetch_twse_margin_all")
@patch("src.data_loader.DataLoader.fetch_tpex_margin_all")
@patch("src.finmind_fetcher.FinMindFetcher.fetch_today_ohlcv_for_universe")
def test_official_data_present_finmind_never_called(
    mock_finmind_fetch, mock_tpex_margin, mock_twse_margin,
    mock_tpex_inst, mock_twse_inst, mock_tpex_price, mock_twse_price,
):
    """
    Both markets' official OHLCV present and correctly dated -> succeeds normally,
    FinMind never invoked (unchanged before and after the fallback removal).
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_data_dir, temp_output_dir = _setup_temp_project(temp_dir)

        mock_twse_price.return_value = [{
            "Date": "1150720", "Code": "2330", "Name": "台積電",
            "OpeningPrice": 2300.0, "HighestPrice": 2345.0, "LowestPrice": 2300.0, "ClosingPrice": 2320.0,
            "TradeVolume": 55790346, "TradeValue": 129815956839,
        }]
        mock_tpex_price.return_value = [{
            "Date": "1150720", "SecuritiesCompanyCode": "3017", "CompanyName": "奇鋐",
            "Open": 610.0, "High": 625.0, "Low": 605.0, "Close": 620.0,
            "TradingShares": 5000, "TransactionAmount": 3075000,
        }]
        _mock_inst_margin(mock_twse_inst, mock_tpex_inst, mock_twse_margin, mock_tpex_margin)

        with patch("src.config_manager.ConfigManager.get", _mock_config_get_factory(temp_data_dir, temp_output_dir)):
            with patch("os.path.exists", _side_effect_exists_factory()):
                try:
                    audit = run_pipeline("2026-07-20")
                finally:
                    logger.remove()

        assert audit["status"] == "SUCCESS"
        assert audit["price_source_twse"] == "official"
        assert audit["price_source_tpex"] == "official"
        assert not mock_finmind_fetch.called, "FinMind must not be called when official data is already present"
