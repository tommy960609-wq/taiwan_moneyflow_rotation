import sys
import os
import pytest
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.data_cleaner import DataCleaner

def test_ticker_standardization():
    cleaner = DataCleaner()
    assert cleaner.clean_ticker("2330") == "2330"
    assert cleaner.clean_ticker(2330) == "2330"
    assert cleaner.clean_ticker("2330.0") == "2330"
    assert cleaner.clean_ticker("50") == "0050"
    assert cleaner.clean_ticker(50) == "0050"

def test_equity_exclusions():
    cleaner = DataCleaner()
    assert cleaner.is_valid_equity("2330", "台積電") is True
    assert cleaner.is_valid_equity("2317", "鴻海") is True
    assert cleaner.is_valid_equity("3017", "奇鋐") is True
    
    # Exclude ETFs
    assert cleaner.is_valid_equity("0050", "元大台灣50") is False
    assert cleaner.is_valid_equity("0056", "元大高股息") is False
    assert cleaner.is_valid_equity("00878", "國泰永續高股息") is False
    
    # Exclude Warrants
    assert cleaner.is_valid_equity("2330P", "台積電麥格理5B售01") is False
    assert cleaner.is_valid_equity("07001P", "元大普惠") is False
    assert cleaner.is_valid_equity("2330A", "台積電甲特") is True

def test_parse_roc_date():
    cleaner = DataCleaner()
    assert cleaner.parse_roc_date("1150716") == "2026-07-16"
    assert cleaner.parse_roc_date("1150717") == "2026-07-17"
    assert cleaner.parse_roc_date("115/07/16") == "2026-07-16"
    assert cleaner.parse_roc_date("20260716") == "2026-07-16"
    assert cleaner.parse_roc_date("") is None

def test_ohlcv_normalization():
    cleaner = DataCleaner()
    
    # TWSE format
    twse_raw = [{
        "Date": "1150716",
        "Code": "2330",
        "Name": "台積電",
        "OpeningPrice": "1,000.0",
        "HighestPrice": "1,010.0",
        "LowestPrice": "995.0",
        "ClosingPrice": "1,005.0",
        "TradeVolume": "10,000,000",
        "TradeValue": "10,050,000,000"
    }]
    
    # TPEx format using TradingShares and TransactionAmount (B1 compliance)
    tpex_raw = [{
        "Date": "1150716",
        "SecuritiesCompanyCode": "3017",
        "CompanyName": "奇鋐",
        "Open": "600.0",
        "High": "620.0",
        "Low": "595.0",
        "Close": "615.0",
        "TradingShares": "5,000,000",
        "TransactionAmount": "3,075,000,000"
    }]
    
    df_twse = cleaner.clean_ohlcv_data(twse_raw, trade_date="2026-07-16", market_type="TWSE")
    df_tpex = cleaner.clean_ohlcv_data(tpex_raw, trade_date="2026-07-16", market_type="TPEx")
    
    assert len(df_twse) == 1
    assert df_twse.iloc[0]["open"] == 1000.0
    assert df_twse.iloc[0]["volume"] == 10000000.0
    assert df_twse.iloc[0]["trade_date"] == "2026-07-16"
    
    assert len(df_tpex) == 1
    assert df_tpex.iloc[0]["open"] == 600.0
    assert df_tpex.iloc[0]["volume"] == 5000000.0
    assert df_tpex.iloc[0]["turnover"] == 3075000000.0
    assert df_tpex.iloc[0]["trade_date"] == "2026-07-16"

def test_date_mismatch_dropped():
    cleaner = DataCleaner()
    twse_raw = [{
        "Date": "1150715", # Day 15
        "Code": "2330",
        "Name": "台積電",
        "OpeningPrice": 100, "HighestPrice": 105, "LowestPrice": 95, "ClosingPrice": 102,
        "TradeVolume": 1000, "TradeValue": 100000
    }]
    # target is Day 16, should drop (B3 compliance)
    df = cleaner.clean_ohlcv_data(twse_raw, trade_date="2026-07-16")
    assert df.empty

def test_reconciliation_any_deviation_warns():
    cleaner = DataCleaner()
    df_prev = pd.DataFrame([
        {"stock_id": "2330", "trade_date": "2026-07-15", "open": 100.0, "high": 100.0,
         "low": 100.0, "close": 100.0, "volume": 1000.0, "market_type": "TWSE"}
    ])
    df_prices = pd.DataFrame([
        {"stock_id": "2330", "trade_date": "2026-07-16", "open": 90.0, "high": 111.0,
         "low": 89.0, "close": 110.0, "volume": 1000.0, "market_type": "TWSE"}
    ])

    # 1. Matches previous-close return exactly: (110 - 100) / 100 = 10%.
    # The open-to-close return is 22.22%, intentionally different, because that basis
    # mismatch is the regression this reconciliation must no longer penalize.
    df_board_match = pd.DataFrame([{"stock_id": "2330", "return_pct": 10.0}])
    log_match = cleaner.reconcile_with_leaderboard(df_prices, df_board_match, df_prev_prices=df_prev)
    assert log_match["status"] == "MATCH"
    assert log_match["deviation_count"] == 0

    # 2. Deviates by 5 percentage points on the same previous-close basis.
    df_board_deviate = pd.DataFrame([{"stock_id": "2330", "return_pct": 5.0}])
    log_warn = cleaner.reconcile_with_leaderboard(df_prices, df_board_deviate, df_prev_prices=df_prev)
    assert log_warn["status"] == "WARNING_HIGH_DEVIATION"
    assert log_warn["deviation_count"] == 1


def test_reconciliation_without_previous_close_is_incomplete_not_warning():
    cleaner = DataCleaner()
    df_prices = pd.DataFrame([
        {"stock_id": "2330", "trade_date": "2026-07-16", "open": 90.0, "high": 111.0,
         "low": 89.0, "close": 110.0, "volume": 1000.0, "market_type": "TWSE"}
    ])
    df_board = pd.DataFrame([{"stock_id": "2330", "return_pct": 10.0}])

    log = cleaner.reconcile_with_leaderboard(df_prices, df_board)

    assert log["status"] == "INCOMPLETE"
    assert log["deviation_count"] == 0
