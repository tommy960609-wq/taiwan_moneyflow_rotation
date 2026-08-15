import sys
import os
import json
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.data_cleaner import DataCleaner
from src.industry_mapper import IndustryMapper
from src.stock_features import StockFeatures
from src.sector_features import SectorFeatures
from src.sector_scoring import SectorScoring
from src.stock_scoring import StockScoring

RAW_SAMPLES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../loop/evidence/raw_samples"))
MAPPING_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../data/reference/stock_industry_mapping.xlsx"))


def _load_payload(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("payload") if isinstance(data, dict) and "payload" in data else data


def test_real_snapshot_full_chain_clean_feature_score():
    """
    Integration test (SPEC 26.2/26.3 style) using the REAL cached TWSE+TPEx OHLCV
    snapshots from loop/evidence/raw_samples (871+ cleaned equities per the M1 gate
    evidence), running the full M2 chain: clean -> industry map -> stock features ->
    sector features -> sector scoring -> stock scoring, and asserting non-empty,
    schema-correct output at every stage. No network calls are made (files are read
    from disk only).
    """
    twse_path = os.path.join(RAW_SAMPLES_DIR, "twse_ohlcv_sample.json")
    tpex_path = os.path.join(RAW_SAMPLES_DIR, "tpex_ohlcv_sample.json")
    assert os.path.exists(twse_path), f"Real TWSE snapshot missing at {twse_path}"
    assert os.path.exists(tpex_path), f"Real TPEx snapshot missing at {tpex_path}"

    twse_meta = json.load(open(twse_path, encoding="utf-8"))["metadata"]
    trade_date = "2026-07-16"  # ROC 1150716 per metadata fetch date used across M1 evidence

    raw_twse = _load_payload(twse_path)
    raw_tpex = _load_payload(tpex_path)

    cleaner = DataCleaner()
    df_twse = cleaner.clean_ohlcv_data(raw_twse, trade_date=trade_date, market_type="TWSE")
    df_tpex = cleaner.clean_ohlcv_data(raw_tpex, trade_date=trade_date, market_type="TPEx")
    df_prices = pd.concat([df_twse, df_tpex], ignore_index=True)

    assert not df_prices.empty
    # Sanity floor consistent with M1 gate evidence (TPEx alone cleaned to ~871 equities)
    assert len(df_prices) > 500, f"Expected substantial full-market universe, got {len(df_prices)} rows"

    df_mapping = pd.read_excel(MAPPING_PATH, dtype={"stock_id": str})
    mapper = IndustryMapper(df_mapping)
    df_mapped = mapper.map_dataframe(df_prices)
    assert not df_mapped.empty
    assert "primary_sector" in df_mapped.columns

    # Most of the real universe is expected to be "待分類" since the mapping file only
    # covers a curated handful of stocks -- this is expected/correct behavior (SPEC 8.2
    # rule 5: never guess), not a bug.
    coverage = mapper.calculate_coverage(df_mapped)
    assert 0.0 <= coverage <= 1.0

    stock_feat = StockFeatures()
    df_stock_features = stock_feat.calculate_ranks(df_mapped)
    assert "current_rank" in df_stock_features.columns
    assert not df_stock_features.empty

    sector_feat = SectorFeatures()
    df_sector_features = sector_feat.calculate_sector_metrics(df_stock_features)
    assert not df_sector_features.empty, "Sector features must be non-empty for a real multi-sector universe"
    assert ((df_sector_features["breadth"] >= 0.0) & (df_sector_features["breadth"] <= 1.0)).all()

    sector_scoring = SectorScoring()
    df_scored_sectors, sector_confidence = sector_scoring.score_sectors(df_sector_features, has_institutional=False)
    assert not df_scored_sectors.empty
    assert ((df_scored_sectors["score"] >= 0.0) & (df_scored_sectors["score"] <= 100.0)).all()
    assert sector_confidence in ("FULL", "DEGRADED", "LOW")

    stock_scoring = StockScoring()
    df_scored_stocks, stock_confidence = stock_scoring.score_stocks(df_stock_features, df_scored_sectors, has_institutional=False)
    assert not df_scored_stocks.empty
    assert ((df_scored_stocks["stock_score"] >= 0.0) & (df_scored_stocks["stock_score"] <= 100.0)).all()

    print(
        f"Real-snapshot M2 chain OK: {len(df_prices)} priced equities, "
        f"{len(df_sector_features)} sector/theme groups, sector_confidence={sector_confidence}, "
        f"stock_confidence={stock_confidence}"
    )
