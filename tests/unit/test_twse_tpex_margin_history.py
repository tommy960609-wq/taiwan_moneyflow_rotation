import sys
import os
import json

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

import src.twse_tpex_margin_history as margin_history_module
from src.twse_tpex_margin_history import (
    fetch_twse_margin_history,
    fetch_tpex_margin_history,
    iso_to_roc_slash,
    transform_twse_margin_rows,
    transform_tpex_margin_rows,
    build_history_envelope,
    DATE_MISMATCH,
)


# ---------------------------------------------------------------------------
# Fake requests.Response / requests.get stand-ins (no real network calls).
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, raise_json_error=False):
        self.status_code = status_code
        self._json_data = json_data
        self._raise_json_error = raise_json_error

    def json(self):
        if self._raise_json_error:
            raise json.JSONDecodeError("bad json", "doc", 0)
        return self._json_data


class _FakeTimeout(Exception):
    pass


TWSE_SAMPLE_ROW = ["2330", "台積電", "1,099", "760", "27", "32,875", "33,187",
                   "6,483,092", "2", "14", "0", "48", "60", "6,483,092", "1", " "]

TWSE_OK_PAYLOAD = {
    "stat": "OK",
    "date": "20260714",
    "tables": [
        {"title": "market total", "fields": ["a", "b"], "data": [["x", "y"]]},
        {"title": "per stock", "fields": ["代號", "名稱"], "data": [TWSE_SAMPLE_ROW]},
    ],
}

TPEX_SAMPLE_ROW = ["6488", "環球晶", "9,277", "2,256", "1,368", "11", "10,154", "88",
                   "8.49", "119,528", "48", "0", "3", "45", "0", "0", "0.0",
                   "119,528", "0", "11 X A"]

TPEX_OK_PAYLOAD = {
    "date": "20260714",
    "tables": [
        {"fields": ["代號", "名稱"], "data": [TPEX_SAMPLE_ROW], "totalCount": 1},
    ],
}


# ---------------------------------------------------------------------------
# fetch_twse_margin_history
# ---------------------------------------------------------------------------

def test_fetch_twse_margin_history_success(monkeypatch):
    def fake_get(url, headers=None, verify=None, timeout=None):
        assert "date=20260714" in url
        return _FakeResponse(200, TWSE_OK_PAYLOAD)

    monkeypatch.setattr(margin_history_module.requests, "get", fake_get)

    rows = fetch_twse_margin_history("2026-07-14")

    assert rows == [TWSE_SAMPLE_ROW]


def test_fetch_twse_margin_history_date_mismatch_returns_none(monkeypatch):
    mismatched = dict(TWSE_OK_PAYLOAD)
    mismatched["date"] = "20260715"  # server reports a different date than requested

    def fake_get(url, headers=None, verify=None, timeout=None):
        return _FakeResponse(200, mismatched)

    monkeypatch.setattr(margin_history_module.requests, "get", fake_get)

    result = fetch_twse_margin_history("2026-07-14")

    assert result is None


def test_fetch_twse_margin_history_http_404_returns_none(monkeypatch):
    def fake_get(url, headers=None, verify=None, timeout=None):
        return _FakeResponse(404, None)

    monkeypatch.setattr(margin_history_module.requests, "get", fake_get)

    result = fetch_twse_margin_history("2026-07-14")

    assert result is None


def test_fetch_twse_margin_history_timeout_returns_none(monkeypatch):
    def fake_get(url, headers=None, verify=None, timeout=None):
        raise margin_history_module.requests.exceptions.Timeout("timed out")

    monkeypatch.setattr(margin_history_module.requests, "get", fake_get)

    result = fetch_twse_margin_history("2026-07-14")

    assert result is None


def test_fetch_twse_margin_history_bad_json_returns_none(monkeypatch):
    def fake_get(url, headers=None, verify=None, timeout=None):
        return _FakeResponse(200, None, raise_json_error=True)

    monkeypatch.setattr(margin_history_module.requests, "get", fake_get)

    result = fetch_twse_margin_history("2026-07-14")

    assert result is None


def test_fetch_twse_margin_history_holiday_no_table_returns_empty_list(monkeypatch):
    holiday_payload = {"stat": "查詢日期資料不存在", "date": "20260718", "tables": []}

    def fake_get(url, headers=None, verify=None, timeout=None):
        return _FakeResponse(200, holiday_payload)

    monkeypatch.setattr(margin_history_module.requests, "get", fake_get)

    result = fetch_twse_margin_history("2026-07-18")

    assert result == []


def test_fetch_twse_margin_history_weekend_no_date_or_tables_returns_empty_list(monkeypatch):
    """
    Real observed shape on a non-trading day (e.g. Saturday 2026-04-25): ONLY a
    "stat" message, no "date" field and no "tables" field at all. This must be
    treated as a non-trading day (empty list), NOT a DATE_MISMATCH failure (None) --
    regression test for a bug found during the real backfill run where every
    weekend/holiday was being misclassified as "failed".
    """
    weekend_payload = {"stat": "很抱歉，沒有符合條件的資料"}

    def fake_get(url, headers=None, verify=None, timeout=None):
        return _FakeResponse(200, weekend_payload)

    monkeypatch.setattr(margin_history_module.requests, "get", fake_get)

    result = fetch_twse_margin_history("2026-04-25")

    assert result == []


def test_fetch_twse_margin_history_unparseable_date_returns_none():
    result = fetch_twse_margin_history("not-a-date")
    assert result is None


# ---------------------------------------------------------------------------
# fetch_tpex_margin_history
# ---------------------------------------------------------------------------

def test_fetch_tpex_margin_history_success(monkeypatch):
    def fake_get(url, headers=None, verify=None, timeout=None):
        assert "d=115/07/14" in url
        return _FakeResponse(200, TPEX_OK_PAYLOAD)

    monkeypatch.setattr(margin_history_module.requests, "get", fake_get)

    rows = fetch_tpex_margin_history("2026-07-14")

    assert rows == [TPEX_SAMPLE_ROW]


def test_fetch_tpex_margin_history_date_mismatch_returns_none(monkeypatch):
    mismatched = dict(TPEX_OK_PAYLOAD)
    mismatched["date"] = "20260715"

    def fake_get(url, headers=None, verify=None, timeout=None):
        return _FakeResponse(200, mismatched)

    monkeypatch.setattr(margin_history_module.requests, "get", fake_get)

    result = fetch_tpex_margin_history("2026-07-14")

    assert result is None


def test_fetch_tpex_margin_history_http_404_returns_none(monkeypatch):
    def fake_get(url, headers=None, verify=None, timeout=None):
        return _FakeResponse(404, None)

    monkeypatch.setattr(margin_history_module.requests, "get", fake_get)

    result = fetch_tpex_margin_history("2026-07-14")

    assert result is None


def test_fetch_tpex_margin_history_timeout_returns_none(monkeypatch):
    def fake_get(url, headers=None, verify=None, timeout=None):
        raise margin_history_module.requests.exceptions.Timeout("timed out")

    monkeypatch.setattr(margin_history_module.requests, "get", fake_get)

    result = fetch_tpex_margin_history("2026-07-14")

    assert result is None


def test_fetch_tpex_margin_history_bad_json_returns_none(monkeypatch):
    def fake_get(url, headers=None, verify=None, timeout=None):
        return _FakeResponse(200, None, raise_json_error=True)

    monkeypatch.setattr(margin_history_module.requests, "get", fake_get)

    result = fetch_tpex_margin_history("2026-07-14")

    assert result is None


def test_fetch_tpex_margin_history_unconvertible_date_returns_none():
    result = fetch_tpex_margin_history("1899-01-01")  # ROC year would be negative
    assert result is None


# ---------------------------------------------------------------------------
# iso_to_roc_slash: date format conversion
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("iso, expected", [
    ("2026-07-14", "115/07/14"),
    ("2011-01-01", "100/01/01"),  # ROC 100 lower boundary
    ("2031-12-31", "120/12/31"),  # ROC 120 upper boundary
    ("2026-01-05", "115/01/05"),  # zero-padded month/day
])
def test_iso_to_roc_slash_valid(iso, expected):
    assert iso_to_roc_slash(iso) == expected


@pytest.mark.parametrize("iso", [
    "2010-01-01",   # ROC 99, below the 100-120 sanity band
    "2032-01-01",   # ROC 121, above the 100-120 sanity band
    "not-a-date",
    "",
    None,
    "2026-13-01",   # invalid month
])
def test_iso_to_roc_slash_invalid_returns_none(iso):
    assert iso_to_roc_slash(iso) is None


# ---------------------------------------------------------------------------
# transform_* : raw rows -> clean_margin_data-compatible shapes
# ---------------------------------------------------------------------------

def test_transform_twse_margin_rows_passthrough():
    result = transform_twse_margin_rows([TWSE_SAMPLE_ROW])
    assert result == [TWSE_SAMPLE_ROW]


def test_transform_twse_margin_rows_empty():
    assert transform_twse_margin_rows([]) == []
    assert transform_twse_margin_rows(None) == []


def test_transform_tpex_margin_rows_builds_expected_dict_keys():
    result = transform_tpex_margin_rows([TPEX_SAMPLE_ROW], "2026-07-14")

    assert len(result) == 1
    row = result[0]
    assert row["SecuritiesCompanyCode"] == "6488"
    assert row["MarginPurchase"] == "2,256"       # index 3
    assert row["MarginSales"] == "1,368"          # index 4
    assert row["MarginPurchaseBalance"] == "10,154"  # index 6
    assert row["ShortSale"] == "0"                # index 11
    assert row["ShortConvering"] == "3"           # index 12
    assert row["ShortSaleBalance"] == "0"         # index 14
    assert row["Date"] == "2026-07-14"


def test_transform_tpex_margin_rows_skips_short_rows():
    result = transform_tpex_margin_rows([["1234", "too short"]], "2026-07-14")
    assert result == []


def test_transform_tpex_margin_rows_compatible_with_clean_margin_data():
    """
    End-to-end check: the dicts produced by transform_tpex_margin_rows must be
    something src.data_cleaner.DataCleaner.clean_margin_data's TPEx branch actually
    parses into the expected margin_buy/margin_sell/margin_balance/short_* columns.
    """
    from src.data_cleaner import DataCleaner

    tpex_dicts = transform_tpex_margin_rows([TPEX_SAMPLE_ROW], "2026-07-14")
    cleaner = DataCleaner()

    df = cleaner.clean_margin_data(raw_twse=None, raw_tpex=tpex_dicts, trade_date="2026-07-14")

    assert len(df) == 1
    row = df.iloc[0]
    assert row["stock_id"] == "6488"
    assert row["margin_buy"] == 2256.0     # row[3] 資買
    assert row["margin_sell"] == 1368.0    # row[4] 資賣
    assert row["margin_balance"] == 10154.0  # row[6] 資餘額
    assert row["short_buy"] == 3.0          # row[12] 券買 -> ShortConvering -> short_buy
    assert row["short_sell"] == 0.0         # row[11] 券賣 -> ShortSale -> short_sell
    assert row["short_balance"] == 0.0      # row[14] 券餘額
    assert row["market_type"] == "TPEx"


def test_transform_twse_margin_rows_compatible_with_clean_margin_data():
    from src.data_cleaner import DataCleaner

    cleaner = DataCleaner()
    df = cleaner.clean_margin_data(raw_twse=[TWSE_SAMPLE_ROW], raw_tpex=None, trade_date="2026-07-14")

    assert len(df) == 1
    row = df.iloc[0]
    assert row["stock_id"] == "2330"
    assert row["margin_buy"] == 1099.0     # row[2]
    assert row["margin_sell"] == 760.0     # row[3]
    assert row["margin_balance"] == 33187.0  # row[6]
    assert row["short_buy"] == 2.0          # row[8]
    assert row["short_sell"] == 14.0        # row[9]
    assert row["short_balance"] == 60.0     # row[12]
    assert row["market_type"] == "TWSE"


# ---------------------------------------------------------------------------
# build_history_envelope
# ---------------------------------------------------------------------------

def test_build_history_envelope_shape():
    env = build_history_envelope("TWSE_MI_MARGN_history", "https://example.test", [{"a": 1}], 200)

    assert env["metadata"]["source"] == "TWSE_MI_MARGN_history"
    assert env["metadata"]["url"] == "https://example.test"
    assert env["metadata"]["http_status"] == 200
    assert env["metadata"]["row_count"] == 1
    assert "sha256" in env["metadata"]
    assert env["payload"] == [{"a": 1}]
