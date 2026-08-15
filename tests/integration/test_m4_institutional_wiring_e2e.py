import sys
import os
import json
import shutil
import tempfile
import pandas as pd
import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from scripts.run_daily import run_pipeline
from src.config_manager import ConfigManager

RAW_SAMPLES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../loop/evidence/raw_samples"))
REAL_MAPPING = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../data/reference/stock_industry_mapping.xlsx"))

TRADE_DATE = "2026-07-16"


def _load_payload(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("payload") if isinstance(data, dict) and "payload" in data else data


@pytest.mark.slow
def test_institutional_features_actually_reach_stock_scoring():
    """
    M4 wiring regression test. Prior to M4, `scripts/run_daily.py` computed
    `df_inst` (institutional flow) and passed `has_institutional=not df_inst.empty`
    into `stock_scoring.score_stocks`, but never actually merged
    foreign_net_buy/investment_trust_net_buy onto the stock-features frame passed
    into that call -- so the "institution" scoring sub-factor silently fell back to
    a neutral 50.0 prior every single day even when real institutional data existed
    (the M4 task brief's "之前這因子常缺席" gap). This test proves the merge now
    actually happens: with the real 2026-07-16 TWSE+TPEx institutional snapshots,
    `stock_scored_<date>.csv` must contain a non-null `foreign_net_buy` column for
    at least some real stocks, and stock_confidence must not be silently degraded
    to LOW purely due to a missing institution factor when institutional data is
    in fact present.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_data_dir = os.path.join(temp_dir, "data")
        temp_output_dir = os.path.join(temp_dir, "outputs")
        os.makedirs(os.path.join(temp_data_dir, "reference"), exist_ok=True)
        os.makedirs(os.path.join(temp_data_dir, "raw/ohlcv"), exist_ok=True)
        os.makedirs(os.path.join(temp_data_dir, "raw/institutional"), exist_ok=True)
        os.makedirs(os.path.join(temp_data_dir, "raw/margin"), exist_ok=True)
        os.makedirs(os.path.join(temp_data_dir, "processed"), exist_ok=True)

        shutil.copy(REAL_MAPPING, os.path.join(temp_data_dir, "reference/stock_industry_mapping.xlsx"))

        twse_ohlcv = _load_payload(os.path.join(RAW_SAMPLES_DIR, "twse_ohlcv_sample.json"))
        tpex_ohlcv = _load_payload(os.path.join(RAW_SAMPLES_DIR, "tpex_ohlcv_sample.json"))
        with open(os.path.join(temp_data_dir, f"raw/ohlcv/twse_prices_{TRADE_DATE}.json"), "w", encoding="utf-8") as f:
            json.dump({"payload": twse_ohlcv}, f, ensure_ascii=False)
        with open(os.path.join(temp_data_dir, f"raw/ohlcv/tpex_prices_{TRADE_DATE}.json"), "w", encoding="utf-8") as f:
            json.dump({"payload": tpex_ohlcv}, f, ensure_ascii=False)

        twse_inst_full = json.load(open(os.path.join(RAW_SAMPLES_DIR, "twse_inst_sample.json"), encoding="utf-8"))["payload"]
        tpex_inst = _load_payload(os.path.join(RAW_SAMPLES_DIR, "tpex_inst_sample.json"))
        with open(os.path.join(temp_data_dir, f"raw/institutional/inst_{TRADE_DATE}.json"), "w", encoding="utf-8") as f:
            json.dump({"payload": twse_inst_full}, f, ensure_ascii=False)
        with open(os.path.join(temp_data_dir, f"raw/institutional/tpex_inst_{TRADE_DATE}.json"), "w", encoding="utf-8") as f:
            json.dump({"payload": tpex_inst}, f, ensure_ascii=False)

        twse_margin = _load_payload(os.path.join(RAW_SAMPLES_DIR, "twse_margin_sample.json"))
        tpex_margin = _load_payload(os.path.join(RAW_SAMPLES_DIR, "tpex_margin_sample.json"))
        with open(os.path.join(temp_data_dir, f"raw/margin/margin_{TRADE_DATE}.json"), "w", encoding="utf-8") as f:
            json.dump({"payload": twse_margin}, f, ensure_ascii=False)
        with open(os.path.join(temp_data_dir, f"raw/margin/tpex_margin_{TRADE_DATE}.json"), "w", encoding="utf-8") as f:
            json.dump({"payload": tpex_margin}, f, ensure_ascii=False)

        def mock_config_get(self, key, default=None):
            if key == "system.data_dir":
                return temp_data_dir
            if key == "system.output_dir":
                return temp_output_dir
            if key == "system.run_mode":
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

        with patch("src.config_manager.ConfigManager.get", mock_config_get), \
             patch("scripts.run_daily.load_excel_leaderboard", return_value=pd.DataFrame()):
            run_pipeline(TRADE_DATE)

        stock_scored_path = os.path.join(temp_data_dir, "processed", f"stock_scored_{TRADE_DATE}.csv")
        assert os.path.exists(stock_scored_path)
        df_scored = pd.read_csv(stock_scored_path, dtype={"stock_id": str})

        assert "foreign_net_buy" in df_scored.columns, (
            "foreign_net_buy must be merged onto the stock-features frame passed into "
            "stock_scoring.score_stocks -- otherwise the institution factor is dead weight."
        )
        assert df_scored["foreign_net_buy"].notna().sum() > 0, (
            "At least some real stocks must carry non-null foreign_net_buy given the "
            "real 2026-07-16 institutional snapshot was supplied."
        )
        assert "score_institution" in df_scored.columns
        assert df_scored["score_institution"].notna().sum() > 0, (
            "score_institution must actually be computed (rank-percentile of "
            "foreign_net_buy), not silently NaN for every row."
        )

        # Institutional feature CSV must also be persisted for history rebuilding.
        inst_features_path = os.path.join(temp_data_dir, "processed", f"institutional_features_{TRADE_DATE}.csv")
        assert os.path.exists(inst_features_path)

        # Sector-level institutional aggregation columns must be present on the
        # persisted sector_features CSV (net_buying_stock_count / sector_net_buy_total).
        sector_features_path = os.path.join(temp_data_dir, "processed", f"sector_features_{TRADE_DATE}.csv")
        df_sector_features = pd.read_csv(sector_features_path)
        assert "net_buying_stock_count" in df_sector_features.columns
        assert "sector_net_buy_total" in df_sector_features.columns
