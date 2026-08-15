import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.disposition_fetcher import (
    DispositionFetcher, DispositionFetchResult, DISPOSITION_ENDPOINTS,
)

SAMPLE_TWSE_PUNISH = [
    {"Number": "1", "Date": "1150714", "Code": "2330", "Name": "X",
     "ReasonsOfDisposition": "R", "DispositionPeriod": "P",
     "DispositionMeasures": "M", "Detail": "D", "LinkInformation": "L"},
]

# The real live-observed "no attention stocks today" sentinel row.
SAMPLE_TWSE_NOTICE_EMPTY_SENTINEL = [
    {"Number": "0", "Code": "", "Name": "", "NumberOfAnnouncement": "0",
     "TradingInfoForAttention": "", "Date": "", "ClosingPrice": "0", "PE": "0"},
]

SAMPLE_TWSE_NOTICE_REAL = [
    {"Number": "1", "Code": "1101", "Name": "X", "NumberOfAnnouncement": "1",
     "TradingInfoForAttention": "T", "Date": "1150714", "ClosingPrice": "10", "PE": "5"},
]

SAMPLE_TPEX_WARNING_INFO = [
    {"Date": "1150717", "SecuritiesCompanyCode": "2061", "CompanyName": "X",
     "TradingInformation": "T", "ClosePrice": "56.7", "PriceEarningRatio": "N/A"},
]

# tpex_esb_warning: keys are non-English (mojibake-prone) field names; id is positional.
SAMPLE_TPEX_ESB_WARNING = [
    {"日期": "1150717", "代號": "6878", "名稱": "X", "資訊": "info", "收盤價": "16.69"},
]


class _StubFetch:
    """Maps endpoint URL -> DispositionFetchResult, mimicking _default_get's signature."""

    def __init__(self, url_to_result):
        self.url_to_result = url_to_result
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append(url)
        return self.url_to_result.get(url, DispositionFetchResult(success=False, error="unmapped url"))


def _all_endpoints_empty_ok():
    return {spec["url"]: DispositionFetchResult(success=True, payload=[], http_status=200)
            for spec in DISPOSITION_ENDPOINTS.values()}


def test_fetch_one_saves_envelope_and_returns_it(tmp_path):
    url = DISPOSITION_ENDPOINTS["twse_punish"]["url"]
    stub = _StubFetch({url: DispositionFetchResult(success=True, payload=SAMPLE_TWSE_PUNISH, http_status=200)})
    fetcher = DispositionFetcher(data_dir=str(tmp_path), fetch_fn=stub)

    envelope = fetcher.fetch_one("twse_punish")
    assert envelope is not None
    assert envelope["metadata"]["row_count"] == 1
    assert envelope["payload"] == SAMPLE_TWSE_PUNISH
    saved_files = os.listdir(os.path.join(str(tmp_path), "raw", "disposition"))
    assert len(saved_files) == 1


def test_fetch_one_failure_is_fail_closed(tmp_path):
    url = DISPOSITION_ENDPOINTS["twse_punish"]["url"]
    stub = _StubFetch({url: DispositionFetchResult(success=False, error="HTTP 500", http_status=500)})
    fetcher = DispositionFetcher(data_dir=str(tmp_path), fetch_fn=stub)

    envelope = fetcher.fetch_one("twse_punish")
    assert envelope is None
    assert len(fetcher.failure_log) == 1
    assert fetcher.failure_log[0]["endpoint"] == "twse_punish"


def test_fetch_today_list_filters_empty_sentinel_row(tmp_path):
    results = _all_endpoints_empty_ok()
    results[DISPOSITION_ENDPOINTS["twse_notice"]["url"]] = DispositionFetchResult(
        success=True, payload=SAMPLE_TWSE_NOTICE_EMPTY_SENTINEL, http_status=200)
    stub = _StubFetch(results)
    fetcher = DispositionFetcher(data_dir=str(tmp_path), fetch_fn=stub)

    result = fetcher.fetch_today_list()
    assert result["stocks"] == {}  # sentinel row (Code="") must not become a fake stock
    assert result["per_endpoint_real_row_counts"]["twse_notice"] == 0


def test_fetch_today_list_real_row_included(tmp_path):
    results = _all_endpoints_empty_ok()
    results[DISPOSITION_ENDPOINTS["twse_notice"]["url"]] = DispositionFetchResult(
        success=True, payload=SAMPLE_TWSE_NOTICE_REAL, http_status=200)
    stub = _StubFetch(results)
    fetcher = DispositionFetcher(data_dir=str(tmp_path), fetch_fn=stub)

    result = fetcher.fetch_today_list()
    assert "1101" in result["stocks"]
    assert result["stocks"]["1101"]["kind"] == "attention"


def test_disposition_kind_wins_over_attention_when_both(tmp_path):
    results = _all_endpoints_empty_ok()
    results[DISPOSITION_ENDPOINTS["twse_punish"]["url"]] = DispositionFetchResult(
        success=True, payload=SAMPLE_TWSE_PUNISH, http_status=200)  # 2330, disposition
    results[DISPOSITION_ENDPOINTS["tpex_warning_info"]["url"]] = DispositionFetchResult(
        success=True, payload=[{"Date": "x", "SecuritiesCompanyCode": "2330",
                                 "CompanyName": "X", "TradingInformation": "T",
                                 "ClosePrice": "1", "PriceEarningRatio": "1"}], http_status=200)
    stub = _StubFetch(results)
    fetcher = DispositionFetcher(data_dir=str(tmp_path), fetch_fn=stub)

    result = fetcher.fetch_today_list()
    assert result["stocks"]["2330"]["kind"] == "disposition"
    assert set(result["stocks"]["2330"]["sources"]) == {"twse_punish", "tpex_warning_info"}


def test_fetch_today_list_one_endpoint_failing_does_not_abort_others(tmp_path):
    results = _all_endpoints_empty_ok()
    results[DISPOSITION_ENDPOINTS["twse_punish"]["url"]] = DispositionFetchResult(
        success=False, error="HTTP 500", http_status=500)
    results[DISPOSITION_ENDPOINTS["tpex_warning_info"]["url"]] = DispositionFetchResult(
        success=True, payload=SAMPLE_TPEX_WARNING_INFO, http_status=200)
    stub = _StubFetch(results)
    fetcher = DispositionFetcher(data_dir=str(tmp_path), fetch_fn=stub)

    result = fetcher.fetch_today_list()
    assert "2061" in result["stocks"]
    assert result["per_endpoint_real_row_counts"]["twse_punish"] is None
    assert len(result["failures"]) == 1


def test_esb_warning_positional_id_extraction(tmp_path):
    results = _all_endpoints_empty_ok()
    results[DISPOSITION_ENDPOINTS["tpex_esb_warning"]["url"]] = DispositionFetchResult(
        success=True, payload=SAMPLE_TPEX_ESB_WARNING, http_status=200)
    stub = _StubFetch(results)
    fetcher = DispositionFetcher(data_dir=str(tmp_path), fetch_fn=stub)

    result = fetcher.fetch_today_list()
    assert "6878" in result["stocks"]
    assert result["stocks"]["6878"]["kind"] == "attention"
