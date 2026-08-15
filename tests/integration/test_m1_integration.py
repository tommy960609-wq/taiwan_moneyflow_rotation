import sys
import os
import pytest
import json
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.data_cleaner import DataCleaner

def test_m1_dual_market_integration_and_reconciliation():
    base_dir = "C:/Workspace_CN/taiwan_moneyflow_rotation"
    sample_dir = f"{base_dir}/loop/evidence/raw_samples"
    
    twse_path = f"{sample_dir}/twse_ohlcv_sample.json"
    tpex_path = f"{sample_dir}/tpex_ohlcv_sample.json"
    twse_inst_path = f"{sample_dir}/twse_inst_sample.json"
    tpex_inst_path = f"{sample_dir}/tpex_inst_sample.json"
    twse_margin_path = f"{sample_dir}/twse_margin_sample.json"
    tpex_margin_path = f"{sample_dir}/tpex_margin_sample.json"
    
    assert os.path.exists(twse_path), "TWSE sample missing"
    assert os.path.exists(tpex_path), "TPEx sample missing"
    assert os.path.exists(twse_inst_path), "TWSE inst sample missing"
    assert os.path.exists(tpex_inst_path), "TPEx inst sample missing"
    assert os.path.exists(twse_margin_path), "TWSE margin sample missing"
    assert os.path.exists(tpex_margin_path), "TPEx margin sample missing"
    
    cleaner = DataCleaner()
    
    # Load raw JSONs (Natural same-day payloads cached)
    with open(twse_path, "r", encoding="utf-8") as f:
        twse_data = json.load(f)["payload"]
    with open(tpex_path, "r", encoding="utf-8") as f:
        tpex_data = json.load(f)["payload"]
        
    # Same-Day Alignment (B3/B4 compliance): Clean using their natural dates to avoid manual overriding in fixtures
    df_twse = cleaner.clean_ohlcv_data(twse_data, trade_date="2026-07-16", market_type="TWSE")
    df_tpex = cleaner.clean_ohlcv_data(tpex_data, trade_date="2026-07-16", market_type="TPEx")
    
    assert not df_twse.empty, "TWSE price empty"
    assert not df_tpex.empty, "TPEx price empty"
    
    # Assert row scale (B2 compliance: full market counts)
    assert len(df_twse) > 800, f"Expected full market TWSE stocks, got {len(df_twse)}"
    assert len(df_tpex) > 800, f"Expected full market TPEx stocks, got {len(df_tpex)}"
    
    df_full = pd.concat([df_twse, df_tpex], ignore_index=True)
    assert len(df_full) == len(df_twse) + len(df_tpex)
    
    # 2. Clean Institutional statistics (B1/B-02 compliance)
    with open(twse_inst_path, "r", encoding="utf-8") as f:
        twse_inst_raw = json.load(f)["payload"]
    with open(tpex_inst_path, "r", encoding="utf-8") as f:
        tpex_inst_raw = json.load(f)["payload"]
        
    df_twse_inst = cleaner.clean_institutional_data(twse_inst_raw, None, trade_date="2026-07-16")
    df_tpex_inst = cleaner.clean_institutional_data(None, tpex_inst_raw, trade_date="2026-07-16")
    df_inst = pd.concat([df_twse_inst, df_tpex_inst], ignore_index=True)
    
    assert not df_inst.empty, "Institutional cleaned data is empty"
    
    # Assert TPEx institutional mappings are successful and contain valid non-zero values (B1 value-level assertions)
    df_tpex_inst_cleaned = df_inst[df_inst["market_type"] == "TPEx"]
    assert not df_tpex_inst_cleaned.empty, "TPEx institutional flow is empty"
    
    tpex_foreign_series = df_tpex_inst_cleaned["foreign_net_buy"].dropna()
    assert not tpex_foreign_series.empty, "TPEx foreign_net_buy normalized to None"
    assert (tpex_foreign_series != 0).any(), "TPEx foreign_net_buy contains only zeros"
    
    # 3. Clean Margin statistics (B3/B-02 compliance)
    with open(twse_margin_path, "r", encoding="utf-8") as f:
        twse_margin_raw = json.load(f)["payload"]
    with open(tpex_margin_path, "r", encoding="utf-8") as f:
        tpex_margin_raw = json.load(f)["payload"]
        
    df_twse_margin = cleaner.clean_margin_data(twse_margin_raw, None, trade_date="2026-07-16")
    df_tpex_margin = cleaner.clean_margin_data(None, tpex_margin_raw, trade_date="2026-07-16")
    df_margin = pd.concat([df_twse_margin, df_tpex_margin], ignore_index=True)
    
    assert not df_margin.empty, "Margin cleaned data is empty"
    assert "margin_balance" in df_margin.columns
    assert len(df_margin[df_margin["market_type"] == "TWSE"]) > 0
    assert len(df_margin[df_margin["market_type"] == "TPEx"]) > 0
    
    # 4. Reconciliation checks (C07 compliance)
    ticker = df_twse.iloc[0]["stock_id"]
    our_close = df_twse.iloc[0]["close"]
    prev_close = our_close / 1.02
    df_prev = pd.DataFrame([{
        "stock_id": ticker, "trade_date": "2026-07-15", "open": prev_close,
        "high": prev_close, "low": prev_close, "close": prev_close,
        "volume": 1000.0, "market_type": "TWSE",
    }])

    df_board_match = pd.DataFrame([{"stock_id": ticker, "漲跌幅": 2.0}])
    log_match = cleaner.reconcile_with_leaderboard(df_full, df_board_match, df_prev_prices=df_prev)
    assert log_match["status"] == "MATCH"
    
    df_board_deviate = pd.DataFrame([{"stock_id": ticker, "漲跌幅": 7.0}])
    log_warn = cleaner.reconcile_with_leaderboard(df_full, df_board_deviate, df_prev_prices=df_prev)
    assert log_warn["status"] == "WARNING_HIGH_DEVIATION"
    
    print("M1 Integration, institutional, margin, and same-day date reconciliation completed successfully.")
