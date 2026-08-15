import os
import sys
import json
import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from scripts.build_official_mapping import (
    normalize_twse_row, normalize_tpex_row, build_official_rows,
    resolve_industry_names, merge_into_mapping, compute_coverage,
    compute_universe_coverage, run, MAPPING_COLUMNS, INDUSTRY_LOOKUP_UNAVAILABLE,
)
from src.data_cleaner import DataCleaner
from src.data_fetcher import FetchResult


SAMPLE_TWSE_ROW = {
    "出表日期": "1150717", "公司代號": "1101", "公司名稱": "臺灣水泥股份有限公司",
    "公司簡稱": "台泥", "產業別": "01",
}
SAMPLE_TPEX_ROW = {
    "Date": "1150717", "SecuritiesCompanyCode": "3260", "CompanyName": "威剛科技股份有限公司",
    "CompanyAbbreviation": "威剛", "SecuritiesIndustryCode": "24",
}


def test_normalize_twse_row_extracts_code_and_name():
    cleaner = DataCleaner()
    row = normalize_twse_row(SAMPLE_TWSE_ROW, cleaner)
    assert row == {"stock_id": "1101", "stock_name": "台泥", "industry_code": "01"}


def test_normalize_tpex_row_extracts_code_and_name():
    cleaner = DataCleaner()
    row = normalize_tpex_row(SAMPLE_TPEX_ROW, cleaner)
    assert row == {"stock_id": "3260", "stock_name": "威剛", "industry_code": "24"}


def test_normalize_row_missing_ticker_returns_none():
    cleaner = DataCleaner()
    assert normalize_twse_row({"公司名稱": "no ticker"}, cleaner) is None
    assert normalize_tpex_row({"CompanyName": "no ticker"}, cleaner) is None


def test_build_official_rows_filters_etf_and_warrants():
    twse_payload = [
        SAMPLE_TWSE_ROW,
        {"公司代號": "0050", "公司名稱": "元大台灣50", "公司簡稱": "元大台灣50", "產業別": "99"},
    ]
    df = build_official_rows(twse_payload, None)
    assert list(df["stock_id"]) == ["1101"]  # 0050 (ETF-range ticker) excluded


def test_build_official_rows_dedupes_on_stock_id():
    twse_payload = [SAMPLE_TWSE_ROW, SAMPLE_TWSE_ROW]
    df = build_official_rows(twse_payload, None)
    assert len(df) == 1


def test_resolve_industry_names_no_lookup_table_keeps_raw_code():
    df = pd.DataFrame([{"stock_id": "1101", "stock_name": "台泥", "industry_code": "01"}])
    df_resolved, status = resolve_industry_names(df, code_to_name=None)
    assert status == INDUSTRY_LOOKUP_UNAVAILABLE
    assert df_resolved.loc[0, "primary_sector"] == "01"


def test_resolve_industry_names_with_lookup_table_translates_code():
    df = pd.DataFrame([{"stock_id": "1101", "stock_name": "台泥", "industry_code": "01"}])
    df_resolved, status = resolve_industry_names(df, code_to_name={"01": "水泥工業"})
    assert status == "RESOLVED"
    assert df_resolved.loc[0, "primary_sector"] == "水泥工業"


def test_resolve_industry_names_missing_code_falls_back_to_unclassified():
    df = pd.DataFrame([{"stock_id": "9999", "stock_name": "空白", "industry_code": ""}])
    df_resolved, _ = resolve_industry_names(df, code_to_name=None)
    assert df_resolved.loc[0, "primary_sector"] == "待分類"


def test_merge_never_overwrites_reviewed_row():
    df_existing = pd.DataFrame([{
        "stock_id": "2330", "stock_name": "台積電", "primary_sector": "半導體",
        "secondary_sector": "晶圓代工", "theme_1": "CoWoS", "theme_2": None, "theme_3": None,
        "supply_chain_role": "Upstream", "valid_from": "2026-01-01", "valid_to": None,
        "source": None, "reviewed": 1,
    }])
    df_official = pd.DataFrame([{
        "stock_id": "2330", "stock_name": "台積電", "primary_sector": "24",
        "_source_label": "TWSE官方",
    }])
    df_merged = merge_into_mapping(df_existing, df_official, run_date="2026-07-18")
    row = df_merged[df_merged["stock_id"] == "2330"].iloc[0]
    assert row["primary_sector"] == "半導體"  # untouched, NOT overwritten with official code
    assert row["reviewed"] == 1


def test_merge_adds_new_unreviewed_official_row():
    df_existing = pd.DataFrame(columns=MAPPING_COLUMNS)
    df_official = pd.DataFrame([{
        "stock_id": "1101", "stock_name": "台泥", "primary_sector": "01",
        "_source_label": "TWSE官方",
    }])
    df_merged = merge_into_mapping(df_existing, df_official, run_date="2026-07-18")
    row = df_merged[df_merged["stock_id"] == "1101"].iloc[0]
    assert row["primary_sector"] == "01"
    assert row["reviewed"] == 0
    assert row["source"] == "TWSE官方"
    assert row["valid_from"] == "2026-07-18"


def test_merge_unclassified_stocks_stay_unclassified_when_absent_from_official_source():
    # A stock in the existing mapping that the official source doesn't mention at all
    # (e.g. delisted, or a market segment not covered) must not be invented a sector --
    # it simply isn't touched by the merge (stays whatever it already was).
    df_existing = pd.DataFrame([{
        "stock_id": "9999", "stock_name": "某股", "primary_sector": "待分類",
        "secondary_sector": "待分類", "theme_1": None, "theme_2": None, "theme_3": None,
        "supply_chain_role": None, "valid_from": "2026-01-01", "valid_to": None,
        "source": "manual", "reviewed": 0,
    }])
    df_official = pd.DataFrame(columns=["stock_id", "stock_name", "primary_sector", "_source_label"])
    df_merged = merge_into_mapping(df_existing, df_official, run_date="2026-07-18")
    row = df_merged[df_merged["stock_id"] == "9999"].iloc[0]
    assert row["primary_sector"] == "待分類"


def test_compute_coverage_against_mapping_file_itself():
    df = pd.DataFrame([
        {"stock_id": "1", "primary_sector": "半導體"},
        {"stock_id": "2", "primary_sector": "待分類"},
    ])
    assert compute_coverage(df) == 0.5


def test_compute_universe_coverage_against_real_trading_universe():
    df_mapping = pd.DataFrame([
        {"stock_id": "1101", "primary_sector": "01"},
        {"stock_id": "9999", "primary_sector": "待分類"},
    ])
    universe = pd.Series(["1101", "2330", "9999"])  # 2330 not even in mapping file
    coverage = compute_universe_coverage(df_mapping, universe)
    assert coverage == pytest.approx(1 / 3)  # only 1101 is both in-universe and classified


def test_compute_universe_coverage_empty_universe_is_zero():
    df_mapping = pd.DataFrame([{"stock_id": "1101", "primary_sector": "01"}])
    assert compute_universe_coverage(df_mapping, pd.Series([], dtype=str)) == 0.0


class _StubFetchFn:
    """Scripted fetch_fn stand-in matching src/data_fetcher.py's fetch_with_retry signature."""
    def __init__(self, results_by_url):
        self.results_by_url = results_by_url
        self.calls = []

    def __call__(self, url, category, max_retries=2, retry_delay_sec=3, **kwargs):
        self.calls.append(url)
        return self.results_by_url.get(url, FetchResult(success=False, error="no stub for url"))


def _ok(payload):
    return FetchResult(success=True, envelope={
        "metadata": {"url": "stub", "http_status": 200, "fetch_time": "t", "row_count": len(payload), "sha256": "x"},
        "payload": payload,
    }, http_status=200)


def test_run_end_to_end_both_markets_succeed(tmp_path):
    mapping_path = str(tmp_path / "mapping.xlsx")
    stub = _StubFetchFn({
        "https://openapi.twse.com.tw/v1/opendata/t187ap03_L": _ok([SAMPLE_TWSE_ROW]),
        "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O": _ok([SAMPLE_TPEX_ROW]),
    })
    receipt = run(mapping_path=mapping_path, receipts_dir=str(tmp_path / "receipts"), fetch_fn=stub)

    assert receipt["status"] == "SUCCESS"
    assert receipt["rows_after"] == 2
    assert os.path.exists(mapping_path)
    df_out = pd.read_excel(mapping_path, dtype={"stock_id": str})
    assert set(df_out["stock_id"]) == {"1101", "3260"}
    assert receipt["industry_code_lookup_status"] == INDUSTRY_LOOKUP_UNAVAILABLE


def test_run_both_fetches_fail_leaves_existing_file_untouched(tmp_path):
    mapping_path = tmp_path / "mapping.xlsx"
    df_seed = pd.DataFrame([{
        "stock_id": "2330", "stock_name": "台積電", "primary_sector": "半導體",
        "secondary_sector": "晶圓代工", "theme_1": None, "theme_2": None, "theme_3": None,
        "supply_chain_role": None, "valid_from": "2026-01-01", "valid_to": None,
        "source": None, "reviewed": 1,
    }])
    df_seed.to_excel(mapping_path, index=False)

    stub = _StubFetchFn({})  # both URLs miss -> fail
    receipt = run(mapping_path=str(mapping_path), receipts_dir=str(tmp_path / "receipts"), fetch_fn=stub)

    assert receipt["status"] == "BLOCKED_BOTH_FETCH_FAILED"
    df_after = pd.read_excel(mapping_path, dtype={"stock_id": str})
    assert len(df_after) == 1
    assert df_after.iloc[0]["primary_sector"] == "半導體"


def test_run_one_market_fails_other_succeeds_still_writes(tmp_path):
    mapping_path = str(tmp_path / "mapping.xlsx")
    stub = _StubFetchFn({
        "https://openapi.twse.com.tw/v1/opendata/t187ap03_L": _ok([SAMPLE_TWSE_ROW]),
        # TPEx URL missing from stub -> fails
    })
    receipt = run(mapping_path=mapping_path, receipts_dir=str(tmp_path / "receipts"), fetch_fn=stub)

    assert receipt["status"] == "SUCCESS"
    assert receipt["tpex_fetch"]["success"] is False
    assert receipt["official_rows_twse"] == 1
    assert receipt["official_rows_tpex"] == 0


def test_run_receipt_written_to_disk(tmp_path):
    mapping_path = str(tmp_path / "mapping.xlsx")
    receipts_dir = str(tmp_path / "receipts")
    stub = _StubFetchFn({
        "https://openapi.twse.com.tw/v1/opendata/t187ap03_L": _ok([SAMPLE_TWSE_ROW]),
        "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O": _ok([SAMPLE_TPEX_ROW]),
    })
    receipt = run(mapping_path=mapping_path, receipts_dir=receipts_dir, fetch_fn=stub)
    receipt_files = os.listdir(receipts_dir)
    assert len(receipt_files) == 1
    with open(os.path.join(receipts_dir, receipt_files[0]), encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["status"] == "SUCCESS"
