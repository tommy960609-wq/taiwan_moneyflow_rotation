import sys
import os
import json

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.data_loader import DataLoader


def _write_finmind_file(data_dir, category, stock_id, payload):
    d = os.path.join(data_dir, "raw", category)
    os.makedirs(d, exist_ok=True)
    envelope = {
        "metadata": {"source": "FinMind", "dataset": "test", "data_id": stock_id,
                      "row_count": len(payload)},
        "payload": payload,
    }
    with open(os.path.join(d, f"finmind_{stock_id}.json"), "w", encoding="utf-8") as f:
        json.dump(envelope, f, ensure_ascii=False)


# ---------------------------------------------------------------------------
# load_finmind_ohlcv_for_date
# ---------------------------------------------------------------------------

def test_load_finmind_ohlcv_for_date_basic(tmp_path):
    _write_finmind_file(str(tmp_path), "ohlcv", "1101", [
        {"date": "2026-04-20", "stock_id": "1101", "open": 25.05, "max": 25.1, "min": 24.7,
         "close": 24.8, "Trading_Volume": 15979332, "Trading_money": 396915981},
        {"date": "2026-04-21", "stock_id": "1101", "open": 25.0, "max": 25.0, "min": 24.7,
         "close": 24.75, "Trading_Volume": 13083599, "Trading_money": 324682895},
    ])
    loader = DataLoader()

    df = loader.load_finmind_ohlcv_for_date(str(tmp_path), "2026-04-20")

    assert len(df) == 1
    row = df.iloc[0]
    assert row["stock_id"] == "1101"
    assert row["open"] == 25.05
    assert row["high"] == 25.1
    assert row["low"] == 24.7
    assert row["close"] == 24.8
    assert row["volume"] == 15979332
    assert row["turnover"] == 396915981
    assert row["source"] == "FinMind"


def test_load_finmind_ohlcv_for_date_no_match_returns_empty(tmp_path):
    _write_finmind_file(str(tmp_path), "ohlcv", "1101", [
        {"date": "2026-04-20", "stock_id": "1101", "open": 25.05, "max": 25.1, "min": 24.7, "close": 24.8},
    ])
    loader = DataLoader()

    df = loader.load_finmind_ohlcv_for_date(str(tmp_path), "2026-05-01")

    assert df.empty


def test_load_finmind_ohlcv_for_date_uses_market_lookup(tmp_path):
    _write_finmind_file(str(tmp_path), "ohlcv", "1101", [
        {"date": "2026-04-20", "stock_id": "1101", "open": 25.05, "max": 25.1, "min": 24.7, "close": 24.8},
    ])
    loader = DataLoader()

    df = loader.load_finmind_ohlcv_for_date(str(tmp_path), "2026-04-20",
                                             stock_market_lookup={"1101": "TWSE"})

    assert df.iloc[0]["market_type"] == "TWSE"


def test_load_finmind_ohlcv_for_date_missing_market_lookup_is_none_not_guessed(tmp_path):
    _write_finmind_file(str(tmp_path), "ohlcv", "1101", [
        {"date": "2026-04-20", "stock_id": "1101", "open": 25.05, "max": 25.1, "min": 24.7, "close": 24.8},
    ])
    loader = DataLoader()

    df = loader.load_finmind_ohlcv_for_date(str(tmp_path), "2026-04-20")

    assert df.iloc[0]["market_type"] is None


def test_load_finmind_ohlcv_for_date_invalid_prices_dropped(tmp_path):
    _write_finmind_file(str(tmp_path), "ohlcv", "9999", [
        {"date": "2026-04-20", "stock_id": "9999", "open": 0, "max": 0, "min": 0, "close": 0},
    ])
    loader = DataLoader()

    df = loader.load_finmind_ohlcv_for_date(str(tmp_path), "2026-04-20")

    assert df.empty


def test_load_finmind_ohlcv_for_date_no_files_returns_empty(tmp_path):
    loader = DataLoader()
    df = loader.load_finmind_ohlcv_for_date(str(tmp_path), "2026-04-20")
    assert df.empty


# ---------------------------------------------------------------------------
# load_finmind_institutional_for_date
# ---------------------------------------------------------------------------

def test_load_finmind_institutional_for_date_aggregates_by_group(tmp_path):
    _write_finmind_file(str(tmp_path), "institutional", "2330", [
        {"date": "2026-07-01", "stock_id": "2330", "name": "Foreign_Investor", "buy": 1000, "sell": 200},
        {"date": "2026-07-01", "stock_id": "2330", "name": "Foreign_Dealer_Self", "buy": 50, "sell": 10},
        {"date": "2026-07-01", "stock_id": "2330", "name": "Investment_Trust", "buy": 300, "sell": 100},
        {"date": "2026-07-01", "stock_id": "2330", "name": "Dealer_self", "buy": 20, "sell": 5},
        {"date": "2026-07-01", "stock_id": "2330", "name": "Dealer_Hedging", "buy": 15, "sell": 5},
    ])
    loader = DataLoader()

    df = loader.load_finmind_institutional_for_date(str(tmp_path), "2026-07-01")

    assert len(df) == 1
    row = df.iloc[0]
    # foreign = (1000-200) + (50-10) = 800 + 40 = 840
    assert row["foreign_net_buy"] == 840
    # trust = 300-100 = 200
    assert row["investment_trust_net_buy"] == 200
    # dealer = (20-5) + (15-5) = 15 + 10 = 25
    assert row["dealer_net_buy"] == 25
    assert row["source"] == "FinMind"


def test_load_finmind_institutional_for_date_no_match_excluded(tmp_path):
    _write_finmind_file(str(tmp_path), "institutional", "2330", [
        {"date": "2026-06-01", "stock_id": "2330", "name": "Foreign_Investor", "buy": 1000, "sell": 200},
    ])
    loader = DataLoader()

    df = loader.load_finmind_institutional_for_date(str(tmp_path), "2026-07-01")

    assert df.empty


# ---------------------------------------------------------------------------
# load_finmind_margin_for_date
# ---------------------------------------------------------------------------

def test_load_finmind_margin_for_date_basic(tmp_path):
    _write_finmind_file(str(tmp_path), "margin", "2330", [
        {"date": "2026-07-01", "stock_id": "2330", "MarginPurchaseBuy": 1483,
         "MarginPurchaseSell": 2192, "MarginPurchaseTodayBalance": 32433,
         "ShortSaleBuy": 0, "ShortSaleSell": 45, "ShortSaleTodayBalance": 67},
    ])
    loader = DataLoader()

    df = loader.load_finmind_margin_for_date(str(tmp_path), "2026-07-01")

    assert len(df) == 1
    row = df.iloc[0]
    assert row["margin_buy"] == 1483
    assert row["margin_balance"] == 32433
    assert row["short_balance"] == 67
    assert row["source"] == "FinMind"


# ---------------------------------------------------------------------------
# merge_*_sources: official always wins on conflict, FinMind fills gaps, source
# column always present and never blended.
# ---------------------------------------------------------------------------

def test_merge_ohlcv_sources_official_wins_on_conflict():
    loader = DataLoader()
    df_official = pd.DataFrame([
        {"stock_id": "1101", "close": 100.0, "trade_date": "2026-04-20"},
    ])
    df_finmind = pd.DataFrame([
        {"stock_id": "1101", "close": 999.0, "trade_date": "2026-04-20", "source": "FinMind"},  # would-be conflict
        {"stock_id": "1102", "close": 50.0, "trade_date": "2026-04-20", "source": "FinMind"},    # gap fill
    ])

    merged = loader.merge_ohlcv_sources(df_official, df_finmind)

    row_1101 = merged[merged["stock_id"] == "1101"].iloc[0]
    assert row_1101["close"] == 100.0  # official value, not FinMind's 999.0
    assert row_1101["source"] == "official"

    row_1102 = merged[merged["stock_id"] == "1102"].iloc[0]
    assert row_1102["close"] == 50.0
    assert row_1102["source"] == "FinMind"


def test_merge_ohlcv_sources_official_empty_uses_all_finmind():
    loader = DataLoader()
    df_official = pd.DataFrame()
    df_finmind = pd.DataFrame([{"stock_id": "1101", "close": 50.0, "source": "FinMind"}])

    merged = loader.merge_ohlcv_sources(df_official, df_finmind)

    assert len(merged) == 1
    assert merged.iloc[0]["source"] == "FinMind"


def test_merge_ohlcv_sources_finmind_empty_returns_official_only():
    loader = DataLoader()
    df_official = pd.DataFrame([{"stock_id": "1101", "close": 100.0}])
    df_finmind = pd.DataFrame()

    merged = loader.merge_ohlcv_sources(df_official, df_finmind)

    assert len(merged) == 1
    assert merged.iloc[0]["source"] == "official"


def test_merge_institutional_sources_official_priority():
    loader = DataLoader()
    df_official = pd.DataFrame([{"stock_id": "2330", "foreign_net_buy": 500.0}])
    df_finmind = pd.DataFrame([
        {"stock_id": "2330", "foreign_net_buy": -999.0, "source": "FinMind"},
        {"stock_id": "2317", "foreign_net_buy": 10.0, "source": "FinMind"},
    ])

    merged = loader.merge_institutional_sources(df_official, df_finmind)

    assert merged[merged["stock_id"] == "2330"].iloc[0]["foreign_net_buy"] == 500.0
    assert merged[merged["stock_id"] == "2317"].iloc[0]["foreign_net_buy"] == 10.0


def test_merge_margin_sources_official_priority():
    loader = DataLoader()
    df_official = pd.DataFrame([{"stock_id": "2330", "margin_balance": 100.0}])
    df_finmind = pd.DataFrame([{"stock_id": "2330", "margin_balance": -1.0, "source": "FinMind"}])

    merged = loader.merge_margin_sources(df_official, df_finmind)

    assert merged.iloc[0]["margin_balance"] == 100.0
    assert merged.iloc[0]["source"] == "official"


def test_merge_sources_both_empty_returns_empty():
    loader = DataLoader()
    merged = loader.merge_ohlcv_sources(pd.DataFrame(), pd.DataFrame())
    assert merged.empty
