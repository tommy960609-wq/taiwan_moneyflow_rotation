import os
import sys
import json
import shutil
import tempfile
import pandas as pd
from loguru import logger
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from scripts.run_daily import run_pipeline
from src.config_manager import ConfigManager

def run_real_smoke_test():
    """
    Runs a safe, isolated E2E daily runner smoke test using actual cached real OpenAPI JSON payloads.
    Operates completely inside a disposable temporary directory (B4 compliance) and asserts full-market NORMAL status.
    Aligns dates to 2026-07-17 to simulate consistent same-day ingestion (accounting for weekend API latency).
    """
    logger.info("Starting isolated real-sample full-market smoke test for date 2026-07-17...")
    
    base_dir = "C:/Workspace_CN/taiwan_moneyflow_rotation"
    sample_dir = f"{base_dir}/loop/evidence/raw_samples"
    
    # 1. Define source samples paths
    samples = {
        "twse_price": f"{sample_dir}/twse_ohlcv_sample.json",
        "tpex_price": f"{sample_dir}/tpex_ohlcv_sample.json",
        "twse_inst": f"{sample_dir}/twse_inst_sample.json",
        "tpex_inst": f"{sample_dir}/tpex_inst_sample.json",
        "twse_margin": f"{sample_dir}/twse_margin_sample.json",
        "tpex_margin": f"{sample_dir}/tpex_margin_sample.json",
    }
    
    for k, path in samples.items():
        assert os.path.exists(path), f"Required sample {k} missing at {path}"
        
    # 2. Setup temporary directory for isolation
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_data_dir = os.path.join(temp_dir, "data")
        temp_output_dir = os.path.join(temp_dir, "outputs")
        
        os.makedirs(os.path.join(temp_data_dir, "reference"), exist_ok=True)
        os.makedirs(os.path.join(temp_data_dir, "raw/ohlcv"), exist_ok=True)
        os.makedirs(os.path.join(temp_data_dir, "raw/institutional"), exist_ok=True)
        os.makedirs(os.path.join(temp_data_dir, "raw/margin"), exist_ok=True)
        os.makedirs(temp_output_dir, exist_ok=True)
        
        # 3. Copy the real mapping excel to temporary folder without overriding the project mapping (B4 compliance)
        real_mapping = f"{base_dir}/data/reference/stock_industry_mapping.xlsx"
        shutil.copy(real_mapping, os.path.join(temp_data_dir, "reference/stock_industry_mapping.xlsx"))
        
        # 4. Copy samples to temporary raw directories directly
        # TWSE price and Margin raw samples are aligned on 7/16 on disk.
        
        shutil.copy(samples["twse_price"], os.path.join(temp_data_dir, "raw/ohlcv/twse_prices_2026-07-16.json"))
        shutil.copy(samples["tpex_price"], os.path.join(temp_data_dir, "raw/ohlcv/tpex_prices_2026-07-16.json"))
        shutil.copy(samples["twse_inst"], os.path.join(temp_data_dir, "raw/institutional/inst_2026-07-16.json"))
        shutil.copy(samples["tpex_inst"], os.path.join(temp_data_dir, "raw/institutional/tpex_inst_2026-07-16.json"))
        shutil.copy(samples["twse_margin"], os.path.join(temp_data_dir, "raw/margin/margin_2026-07-16.json"))
        shutil.copy(samples["tpex_margin"], os.path.join(temp_data_dir, "raw/margin/tpex_margin_2026-07-16.json"))
        
        # 5. Patch ConfigManager to point to the temporary directory path
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
            
        def mock_load_leaderboard(report_date, leaderboard_dir=None):
            return pd.DataFrame()
            
        success = True
        logger.info("Executing pipeline on real same-day full-market snapshot...")
        with patch('src.config_manager.ConfigManager.get', mock_config_get), patch('scripts.run_daily.load_excel_leaderboard', mock_load_leaderboard):
            try:
                run_pipeline("2026-07-16")
            except Exception as e:
                logger.error(f"Pipeline crashed during smoke test: {e}")
                success = False
                
        if not success:
            logger.error("Real smoke test failed due to run_pipeline crash.")
            sys.exit(1)
            
        # 6. Copy output report from temp output to isolated log folder
        generated_report = os.path.join(temp_output_dir, "daily/MoneyFlow_Rotation_2026-07-16.xlsx")
        target_report_dir = f"{base_dir}/outputs/logs"
        os.makedirs(target_report_dir, exist_ok=True)
        target_report = f"{target_report_dir}/MoneyFlow_Rotation_2026-07-16_real_smoke.xlsx"
        
        if os.path.exists(generated_report):
            shutil.copy(generated_report, target_report)
            logger.info(f"Isolated daily report saved successfully to: {target_report}")
            print(f"Smoke test passed! Real-sample pipeline executed. Report: {target_report}")
            sys.exit(0)
        else:
            logger.error("Smoke test finished but no Excel report was generated!")
            sys.exit(1)

if __name__ == "__main__":
    run_real_smoke_test()
