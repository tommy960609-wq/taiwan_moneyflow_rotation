import sys
import os
import json
import shutil
import tempfile
from unittest.mock import patch

import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from scripts.run_daily import run_pipeline
from src.config_manager import ConfigManager

DATES = ["2026-07-14", "2026-07-15", "2026-07-16"]
ROC_DATES = {"2026-07-14": "1150714", "2026-07-15": "1150715", "2026-07-16": "1150716"}
# M5c-prep: these 3 dates' mock prices_<date>.json fixtures were moved out of
# data/raw/ohlcv/ (where they were shadowing the real official/FinMind-bridged
# per-market files for run_daily.py's live pipeline -- see
# docs/Milestone_5c_prep_Report.md item 2) into a dedicated test-fixtures
# directory. This test only ever READS these files (copies their content into its
# own temp dir), so updating the path here is a pure fixture-relocation, not a
# behavior change.
MOCK_OHLCV_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../data/test_fixtures/legacy_mock"))
MOCK_INST_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../data/raw/institutional"))
REAL_MAPPING = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../data/reference/stock_industry_mapping.xlsx"))


def _load_payload(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("payload") if isinstance(data, dict) and "payload" in data else data


def _mock_config_get_factory(temp_data_dir, temp_output_dir):
    def mock_config_get(self, key, default=None):
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
    return mock_config_get


@patch("scripts.run_daily.load_excel_leaderboard")
def test_e2e_3day_mock_pipeline_accumulates_rolling_history_and_writes_processed_output(mock_load_leaderboard):
    """
    Milestone 2 end-to-end requirement: run the full daily pipeline (clean -> map ->
    stock features -> sector features -> scoring -> lifecycle -> signals -> processed
    output) across 3 consecutive mock trading days and verify:
      1. All 3 days succeed and write processed feature/score CSVs under data/processed/.
      2. By day 3, rolling stock features (vol_ma5, return_1d) are populated because
         3 days of history have accumulated (min_periods=3 satisfied), while windows
         requiring more history (high_20d, return_20d; min_periods=10/20) correctly
         remain NaN rather than being fabricated.
      3. Sector lifecycle classification on day 3 has enough history (exactly 3 days)
         to produce a real stage label with PARTIAL confidence, not "資料不足".
      4. P0-05: primary-sector rows are flagged may_double_count=False and theme rows
         may_double_count=True in the persisted sector_scored snapshot.

    This test reuses the existing mock OHLCV fixture (data/test_fixtures/legacy_mock/
    prices_*.json, the same fixture backing the pre-existing M1 hermetic tests) but
    splits its 8 stocks into a TWSE half and a TPEx half in a temp dir, since the
    pipeline's B4 fail-closed rule requires both markets to be present for a given
    trade_date -- the original combined mock fixture only tags rows as TWSE.

    M5c-prep: load_excel_leaderboard is patched to always return empty. This test's
    mock fixture reuses real Taiwan stock IDs (2330/2317/etc) with fabricated prices,
    and scripts.run_daily.load_excel_leaderboard has a hardcoded external-project glob
    path (documented pre-existing M1 environment-coupling issue, see
    docs/Milestone_3_Acceptance_Report.md Sec.4) that picks up whatever REAL leaderboard
    file happens to exist on this dev machine for these dates. When that real file's
    real return_pct for a colliding stock_id differs from this test's fabricated mock
    price move by more than the reconciliation tolerance, the pipeline correctly (per
    its own fail-closed design) BLOCKs on low DQ -- which has nothing to do with what
    this test actually verifies (rolling-feature accumulation), so the leaderboard read
    is neutralized here for hermeticity, same pattern as tests/integration/
    test_run_daily.py's fully-mocked network layer.
    """
    mock_load_leaderboard.return_value = pd.DataFrame()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_data_dir = os.path.join(temp_dir, "data")
        temp_output_dir = os.path.join(temp_dir, "outputs")

        os.makedirs(os.path.join(temp_data_dir, "reference"), exist_ok=True)
        os.makedirs(os.path.join(temp_data_dir, "raw/ohlcv"), exist_ok=True)
        os.makedirs(os.path.join(temp_data_dir, "raw/institutional"), exist_ok=True)
        os.makedirs(os.path.join(temp_data_dir, "raw/margin"), exist_ok=True)
        os.makedirs(os.path.join(temp_data_dir, "processed"), exist_ok=True)
        os.makedirs(temp_output_dir, exist_ok=True)

        shutil.copy(REAL_MAPPING, os.path.join(temp_data_dir, "reference/stock_industry_mapping.xlsx"))

        for date in DATES:
            payload = _load_payload(os.path.join(MOCK_OHLCV_DIR, f"prices_{date}.json"))
            twse_rows = payload[:4]
            tpex_rows = []
            for row in payload[4:]:
                tpex_rows.append({
                    "Date": ROC_DATES[date],
                    "SecuritiesCompanyCode": row["Code"],
                    "CompanyName": row["Name"],
                    "Open": row["OpeningPrice"], "High": row["HighestPrice"],
                    "Low": row["LowestPrice"], "Close": row["ClosingPrice"],
                    "TradingShares": row["TradeVolume"], "TransactionAmount": row["TradeValue"],
                })
            with open(os.path.join(temp_data_dir, f"raw/ohlcv/twse_prices_{date}.json"), "w", encoding="utf-8") as f:
                json.dump({"payload": twse_rows}, f)
            with open(os.path.join(temp_data_dir, f"raw/ohlcv/tpex_prices_{date}.json"), "w", encoding="utf-8") as f:
                json.dump({"payload": tpex_rows}, f)

            inst_src = os.path.join(MOCK_INST_DIR, f"inst_{date}.json")
            if os.path.exists(inst_src):
                shutil.copy(inst_src, os.path.join(temp_data_dir, f"raw/institutional/inst_{date}.json"))
            else:
                with open(os.path.join(temp_data_dir, f"raw/institutional/inst_{date}.json"), "w", encoding="utf-8") as f:
                    json.dump([], f)
            with open(os.path.join(temp_data_dir, f"raw/institutional/tpex_inst_{date}.json"), "w", encoding="utf-8") as f:
                json.dump({"payload": []}, f)
            with open(os.path.join(temp_data_dir, f"raw/margin/margin_{date}.json"), "w", encoding="utf-8") as f:
                json.dump({"payload": []}, f)
            with open(os.path.join(temp_data_dir, f"raw/margin/tpex_margin_{date}.json"), "w", encoding="utf-8") as f:
                json.dump({"payload": []}, f)

        mock_config_get = _mock_config_get_factory(temp_data_dir, temp_output_dir)

        with patch("src.config_manager.ConfigManager.get", mock_config_get):
            prev = None
            for date in DATES:
                run_pipeline(date, prev_date=prev)
                prev = date

        processed_dir = os.path.join(temp_data_dir, "processed")
        for date in DATES:
            assert os.path.exists(os.path.join(processed_dir, f"stock_features_{date}.csv")), f"Missing stock_features for {date}"
            assert os.path.exists(os.path.join(processed_dir, f"sector_scored_{date}.csv")), f"Missing sector_scored for {date}"

        df_stock_day3 = pd.read_csv(os.path.join(processed_dir, "stock_features_2026-07-16.csv"))
        assert not df_stock_day3.empty
        # 3 days accumulated -> min_periods=3 windows populate
        assert df_stock_day3["vol_ma5"].notna().any(), "vol_ma5 should populate once 3 days of history exist"
        assert df_stock_day3["return_1d"].notna().any()
        # min_periods=10/20 windows must still be NaN (only 3 days available), not fabricated
        assert df_stock_day3["high_20d"].isna().all()
        assert df_stock_day3["return_20d"].isna().all()

        df_sector_day3 = pd.read_csv(os.path.join(processed_dir, "sector_scored_2026-07-16.csv"))
        assert not df_sector_day3.empty
        assert (df_sector_day3["lifecycle_confidence"] == "PARTIAL").any(), "3 accumulated days should yield PARTIAL lifecycle confidence, not insufficient data"
        assert (df_sector_day3["lifecycle"] != "資料不足").any()

        # P0-05 compliance check on persisted output
        primary_rows = df_sector_day3[df_sector_day3["sector_type"] == "primary"]
        theme_rows = df_sector_day3[df_sector_day3["sector_type"] == "theme"]
        if not primary_rows.empty:
            assert (primary_rows["may_double_count"] == False).all()
        if not theme_rows.empty:
            assert (theme_rows["may_double_count"] == True).all()

        expected_excel = os.path.join(temp_output_dir, "daily/MoneyFlow_Rotation_2026-07-16.xlsx")
        assert os.path.exists(expected_excel), "Excel report for final day not generated"

        print("M2 3-day E2E mock pipeline test completed successfully!")
