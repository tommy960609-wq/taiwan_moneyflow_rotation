import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from scripts.prepare_finmind_legacy_snapshot import (
    load_finmind_stock_type_lookup, build_ohlcv_legacy_rows,
    build_institutional_legacy_rows, build_margin_legacy_rows,
    prepare_finmind_legacy_snapshot,
)


def _write_finmind_file(data_dir, category, stock_id, payload):
    d = os.path.join(data_dir, "raw", category)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"finmind_{stock_id}.json"), "w", encoding="utf-8") as f:
        json.dump({"metadata": {}, "payload": payload}, f, ensure_ascii=False)


def _write_stock_info(data_dir, rows):
    d = os.path.join(data_dir, "raw", "fundamentals")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "finmind_stock_info.json"), "w", encoding="utf-8") as f:
        json.dump({"metadata": {}, "payload": rows}, f, ensure_ascii=False)


def test_load_finmind_stock_type_lookup(tmp_path):
    _write_stock_info(str(tmp_path), [
        {"stock_id": "1101", "type": "twse"},
        {"stock_id": "5450", "type": "tpex"},
    ])

    lookup = load_finmind_stock_type_lookup(str(tmp_path))

    assert lookup["1101"] == "TWSE"
    assert lookup["5450"] == "TPEx"


def test_load_finmind_stock_type_lookup_missing_file_returns_empty(tmp_path):
    lookup = load_finmind_stock_type_lookup(str(tmp_path))
    assert lookup == {}


def test_build_ohlcv_legacy_rows_splits_by_market(tmp_path):
    _write_finmind_file(str(tmp_path), "ohlcv", "1101", [
        {"date": "2026-05-04", "stock_id": "1101", "open": 25.0, "max": 25.5, "min": 24.5, "close": 25.2,
         "Trading_Volume": 1000, "Trading_money": 25000},
    ])
    _write_finmind_file(str(tmp_path), "ohlcv", "5450", [
        {"date": "2026-05-04", "stock_id": "5450", "open": 10.0, "max": 10.5, "min": 9.5, "close": 10.1,
         "Trading_Volume": 500, "Trading_money": 5000},
    ])
    lookup = {"1101": "TWSE", "5450": "TPEx"}

    out = build_ohlcv_legacy_rows(str(tmp_path), "2026-05-04", lookup)

    assert len(out["TWSE"]) == 1
    assert out["TWSE"][0]["Code"] == "1101"
    assert out["TWSE"][0]["ClosingPrice"] == 25.2
    assert out["TWSE"][0]["HighestPrice"] == 25.5
    assert out["TWSE"][0]["LowestPrice"] == 24.5
    assert len(out["TPEx"]) == 1
    assert out["TPEx"][0]["Code"] == "5450"


def test_build_ohlcv_legacy_rows_unknown_market_excluded(tmp_path):
    _write_finmind_file(str(tmp_path), "ohlcv", "9999", [
        {"date": "2026-05-04", "stock_id": "9999", "open": 25.0, "max": 25.5, "min": 24.5, "close": 25.2},
    ])
    out = build_ohlcv_legacy_rows(str(tmp_path), "2026-05-04", {})  # no lookup entry for 9999

    assert out["TWSE"] == []
    assert out["TPEx"] == []


def test_build_institutional_legacy_rows_shapes(tmp_path):
    _write_finmind_file(str(tmp_path), "institutional", "2330", [
        {"date": "2026-05-04", "stock_id": "2330", "name": "Foreign_Investor", "buy": 1000, "sell": 200},
        {"date": "2026-05-04", "stock_id": "2330", "name": "Investment_Trust", "buy": 300, "sell": 100},
        {"date": "2026-05-04", "stock_id": "2330", "name": "Dealer_self", "buy": 20, "sell": 5},
    ])
    lookup = {"2330": "TWSE"}

    out = build_institutional_legacy_rows(str(tmp_path), "2026-05-04", lookup)

    assert out["twse"]["data"][0][0] == "2330"
    assert out["twse"]["data"][0][4] == 800.0    # foreign net
    assert out["twse"]["data"][0][10] == 200.0   # trust net
    assert out["twse"]["data"][0][11] == 15.0    # dealer net
    assert out["tpex"] == []


def test_build_margin_legacy_rows_positional_and_dict_shapes(tmp_path):
    _write_finmind_file(str(tmp_path), "margin", "1101", [
        {"date": "2026-05-04", "stock_id": "1101", "MarginPurchaseBuy": 100, "MarginPurchaseSell": 50,
         "MarginPurchaseTodayBalance": 500, "ShortSaleBuy": 5, "ShortSaleSell": 3, "ShortSaleTodayBalance": 20},
    ])
    lookup = {"1101": "TWSE"}

    out = build_margin_legacy_rows(str(tmp_path), "2026-05-04", lookup)

    assert out["twse"][0][0] == "1101"
    assert out["twse"][0][2] == 100
    assert out["twse"][0][6] == 500
    assert out["twse"][0][12] == 20


def test_prepare_finmind_legacy_snapshot_never_overwrites_official(tmp_path):
    """The core dual-source rule: an already-present legacy file (simulating an
    official-source bridge having run first) must never be overwritten by FinMind."""
    _write_stock_info(str(tmp_path), [{"stock_id": "1101", "type": "twse"}])
    _write_finmind_file(str(tmp_path), "ohlcv", "1101", [
        {"date": "2026-05-04", "stock_id": "1101", "open": 999.0, "max": 999.0, "min": 999.0, "close": 999.0},
    ])
    official_path = os.path.join(str(tmp_path), "raw", "ohlcv", "twse_prices_2026-05-04.json")
    os.makedirs(os.path.dirname(official_path), exist_ok=True)
    with open(official_path, "w", encoding="utf-8") as f:
        json.dump([{"Code": "1101", "ClosingPrice": "25.0"}], f)

    report = prepare_finmind_legacy_snapshot(str(tmp_path), "2026-05-04")

    assert report["ohlcv/twse_prices_2026-05-04.json"] == "skipped_official_already_present"
    with open(official_path, encoding="utf-8") as f:
        content = json.load(f)
    assert content[0]["ClosingPrice"] == "25.0"  # untouched


def test_prepare_finmind_legacy_snapshot_writes_when_absent(tmp_path):
    _write_stock_info(str(tmp_path), [{"stock_id": "1101", "type": "twse"}])
    _write_finmind_file(str(tmp_path), "ohlcv", "1101", [
        {"date": "2026-05-04", "stock_id": "1101", "open": 25.0, "max": 25.5, "min": 24.5, "close": 25.2},
    ])

    report = prepare_finmind_legacy_snapshot(str(tmp_path), "2026-05-04")

    assert report["ohlcv/twse_prices_2026-05-04.json"] == "written_from_finmind"
    written_path = os.path.join(str(tmp_path), "raw", "ohlcv", "twse_prices_2026-05-04.json")
    assert os.path.exists(written_path)


def test_prepare_finmind_legacy_snapshot_no_rows_reports_no_finmind_rows(tmp_path):
    report = prepare_finmind_legacy_snapshot(str(tmp_path), "2026-05-04")
    assert report["ohlcv/twse_prices_2026-05-04.json"] == "no_finmind_rows"
