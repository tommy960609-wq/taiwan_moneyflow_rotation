import json
import os
import shutil

import pytest
import yaml
from unittest.mock import patch

from scripts.run_daily import run_pipeline
from src.config_manager import ConfigManager


TRADE_DATE = "2026-07-16"
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
RAW_SAMPLES_DIR = os.path.join(PROJECT_ROOT, "loop", "evidence", "raw_samples")
REAL_MAPPING = os.path.join(PROJECT_ROOT, "data", "reference", "stock_industry_mapping.xlsx")
DEFAULT_CONFIG = os.path.join(PROJECT_ROOT, "config", "default.yaml")


def _load_payload(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return data.get("payload") if isinstance(data, dict) and "payload" in data else data


def _write_real_snapshot(data_dir):
    for relative_dir in ("reference", "raw/ohlcv", "raw/institutional", "raw/margin", "processed"):
        os.makedirs(os.path.join(data_dir, relative_dir), exist_ok=True)
    shutil.copy(REAL_MAPPING, os.path.join(data_dir, "reference", "stock_industry_mapping.xlsx"))

    for sample_name, output_name in (
        ("twse_ohlcv_sample.json", f"raw/ohlcv/twse_prices_{TRADE_DATE}.json"),
        ("tpex_ohlcv_sample.json", f"raw/ohlcv/tpex_prices_{TRADE_DATE}.json"),
        ("twse_inst_sample.json", f"raw/institutional/inst_{TRADE_DATE}.json"),
        ("tpex_inst_sample.json", f"raw/institutional/tpex_inst_{TRADE_DATE}.json"),
        ("twse_margin_sample.json", f"raw/margin/margin_{TRADE_DATE}.json"),
        ("tpex_margin_sample.json", f"raw/margin/tpex_margin_{TRADE_DATE}.json"),
    ):
        with open(os.path.join(data_dir, output_name), "w", encoding="utf-8") as handle:
            json.dump({"payload": _load_payload(os.path.join(RAW_SAMPLES_DIR, sample_name))}, handle, ensure_ascii=False)


@pytest.mark.parametrize(
    ("observe_settings", "expected_depth", "expected_sector_top_n"),
    [
        ({"ranking_depth": 50, "sector_top_n": 3}, 50, 3),
        (None, 300, 5),
    ],
    ids=("configured_depth", "missing_yaml_section_uses_static_fallback"),
)
def test_real_pipeline_observe_rankings_use_yaml_settings_or_static_fallback(
    tmp_path, observe_settings, expected_depth, expected_sector_top_n
):
    """Run the unmocked ranking calculation over real snapshots and inspect its JSON output."""
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "outputs"
    _write_real_snapshot(str(data_dir))

    with open(DEFAULT_CONFIG, encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    config["system"]["data_dir"] = str(data_dir)
    config["system"]["output_dir"] = str(output_dir)
    config["reconciliation"]["leaderboard_dir"] = str(tmp_path / "no_leaderboard")
    if observe_settings is None:
        config.pop("observe_rankings")
    else:
        config["observe_rankings"] = observe_settings
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, allow_unicode=True, sort_keys=False)

    with patch("scripts.run_daily.ConfigManager", side_effect=lambda: ConfigManager(str(config_path))):
        audit = run_pipeline(TRADE_DATE)

    assert audit["status"] == "SUCCESS"
    rankings_path = output_dir / "observe" / f"rankings_{TRADE_DATE}.json"
    with open(rankings_path, encoding="utf-8") as handle:
        rankings = json.load(handle)

    assert rankings["metadata"]["ranking_depth"] == expected_depth
    assert rankings["metadata"]["sector_top_n"] == expected_sector_top_n
    assert len(rankings["rankings"]["top_gainers"]["stocks"]) == expected_depth
    assert len(rankings["rankings"]["top_losers"]["stocks"]) == expected_depth
    assert len(rankings["rankings"]["top_turnover"]["stocks"]) == expected_depth
    assert all(
        len(rankings["rankings"][section]["top5_sectors"]) <= expected_sector_top_n
        for section in ("top_gainers", "top_losers", "top_turnover")
    )
