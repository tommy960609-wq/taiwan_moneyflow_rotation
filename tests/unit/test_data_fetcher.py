import sys
import os
import json
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.data_fetcher import (
    DataFetcher, FetchResult, fetch_with_retry, is_holiday_response,
    INDEX_SOURCE_UNAVAILABLE, ENDPOINTS, extract_payload_date,
)


def _ok_result(payload, http_status=200):
    raw_text = json.dumps(payload, ensure_ascii=False)
    import hashlib
    envelope = {
        "metadata": {
            "url": "https://example.test/endpoint",
            "http_status": http_status,
            "fetch_time": "2026-07-17 09:00:00",
            "row_count": len(payload) if isinstance(payload, list) else 1,
            "sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        },
        "payload": payload,
    }
    return FetchResult(success=True, envelope=envelope, http_status=http_status)


def _fail_result(error="HTTP 404", http_status=404):
    return FetchResult(success=False, error=error, http_status=http_status)


SAMPLE_OHLCV_PAYLOAD = [
    {"Date": "1150716", "Code": "2330", "Name": "台積電", "OpeningPrice": "600", "ClosingPrice": "610",
     "HighestPrice": "615", "LowestPrice": "598", "TradeVolume": "1000", "TradeValue": "610000"}
]


class _StubFetchFn:
    """Callable fetch_fn stand-in that returns a scripted sequence of FetchResults."""
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, url, category, max_retries=2, retry_delay_sec=3, **kwargs):
        self.calls.append((url, category))
        if not self.results:
            return _fail_result("stub exhausted")
        return self.results.pop(0)


def test_fetch_and_save_success_writes_envelope(tmp_path):
    stub = _StubFetchFn([_ok_result(SAMPLE_OHLCV_PAYLOAD)])
    fetcher = DataFetcher(data_dir=str(tmp_path), fetch_fn=stub)

    envelope = fetcher.fetch_and_save("ohlcv", "twse", "2026-07-16")

    assert envelope is not None
    expected_path = tmp_path / "raw" / "ohlcv" / "twse_2026-07-16.json"
    assert expected_path.exists()
    with open(expected_path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["metadata"]["row_count"] == 1
    assert saved["payload"] == SAMPLE_OHLCV_PAYLOAD
    assert fetcher.failure_log == []


def test_fetch_and_save_http_404_returns_none_fail_closed(tmp_path):
    stub = _StubFetchFn([_fail_result("HTTP 404", 404)])
    fetcher = DataFetcher(data_dir=str(tmp_path), fetch_fn=stub)

    result = fetcher.fetch_and_save("ohlcv", "twse", "2026-07-16")

    assert result is None
    expected_path = tmp_path / "raw" / "ohlcv" / "twse_2026-07-16.json"
    assert not expected_path.exists()
    assert len(fetcher.failure_log) == 1
    assert fetcher.failure_log[0]["error"] == "HTTP 404"


def test_fetch_and_save_empty_payload_schema_failure_returns_none(tmp_path):
    stub = _StubFetchFn([_fail_result("Schema validation failed: payload is an empty list")])
    fetcher = DataFetcher(data_dir=str(tmp_path), fetch_fn=stub)

    result = fetcher.fetch_and_save("ohlcv", "twse", "2026-07-16")

    assert result is None
    assert not (tmp_path / "raw" / "ohlcv" / "twse_2026-07-16.json").exists()


def test_fetch_and_save_retry_exhausted_returns_none(tmp_path):
    # Simulate: all attempts fail (the retry loop itself lives inside fetch_with_retry;
    # here we verify DataFetcher correctly propagates a final failure to None/fail-closed
    # regardless of how many attempts fetch_fn made internally).
    stub = _StubFetchFn([_fail_result("Request exception: timeout")])
    fetcher = DataFetcher(data_dir=str(tmp_path), fetch_fn=stub, max_retries=2, retry_delay_sec=0)

    result = fetcher.fetch_and_save("ohlcv", "twse", "2026-07-16")

    assert result is None
    assert fetcher.failure_log[0]["error"] == "Request exception: timeout"


def test_fetch_with_retry_retries_then_succeeds(monkeypatch):
    """
    fetch_with_retry itself must retry up to max_retries times on failure before
    giving up, and succeed immediately once a good response arrives.
    """
    calls = {"n": 0}

    class FakeResponse:
        def __init__(self, status_code, json_data=None):
            self.status_code = status_code
            self._json_data = json_data

        def json(self):
            return self._json_data

    def fake_get(url, headers=None, verify=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            return FakeResponse(500)
        return FakeResponse(200, SAMPLE_OHLCV_PAYLOAD)

    import src.data_fetcher as data_fetcher_module
    monkeypatch.setattr(data_fetcher_module.requests, "get", fake_get)

    result = fetch_with_retry("https://example.test/ohlcv", category="ohlcv",
                               max_retries=2, retry_delay_sec=0)

    assert result.success is True
    assert calls["n"] == 3  # 2 failures + 1 success


def test_fetch_with_retry_exhausts_and_fails(monkeypatch):
    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code
        def json(self):
            return None

    def fake_get(url, headers=None, verify=None, timeout=None):
        return FakeResponse(500)

    import src.data_fetcher as data_fetcher_module
    monkeypatch.setattr(data_fetcher_module.requests, "get", fake_get)

    result = fetch_with_retry("https://example.test/ohlcv", category="ohlcv",
                               max_retries=2, retry_delay_sec=0)

    assert result.success is False
    assert "HTTP 500" in result.error


def test_idempotent_backup_before_overwrite(tmp_path):
    stub = _StubFetchFn([_ok_result(SAMPLE_OHLCV_PAYLOAD), _ok_result(SAMPLE_OHLCV_PAYLOAD + SAMPLE_OHLCV_PAYLOAD)])
    fetcher = DataFetcher(data_dir=str(tmp_path), fetch_fn=stub)

    fetcher.fetch_and_save("ohlcv", "twse", "2026-07-16")
    path = tmp_path / "raw" / "ohlcv" / "twse_2026-07-16.json"
    bak_path = tmp_path / "raw" / "ohlcv" / "twse_2026-07-16.json.bak"
    assert path.exists()
    assert not bak_path.exists()

    fetcher.fetch_and_save("ohlcv", "twse", "2026-07-16")
    assert bak_path.exists()
    with open(bak_path, encoding="utf-8") as f:
        bak_content = json.load(f)
    assert bak_content["metadata"]["row_count"] == 1  # backup holds the FIRST version

    with open(path, encoding="utf-8") as f:
        new_content = json.load(f)
    assert new_content["metadata"]["row_count"] == 2  # new file holds the SECOND version


def test_filename_format(tmp_path):
    stub = _StubFetchFn([_ok_result(SAMPLE_OHLCV_PAYLOAD)])
    fetcher = DataFetcher(data_dir=str(tmp_path), fetch_fn=stub)
    fetcher.fetch_and_save("margin", "tpex", "2026-07-16")
    assert (tmp_path / "raw" / "margin" / "tpex_2026-07-16.json").exists()


def test_market_index_unavailable_marker_when_no_endpoint(tmp_path, monkeypatch):
    import src.data_fetcher as data_fetcher_module
    monkeypatch.setitem(data_fetcher_module.ENDPOINTS["market_index"], "tpex", None)

    stub = _StubFetchFn([])
    fetcher = DataFetcher(data_dir=str(tmp_path), fetch_fn=stub)

    result = fetcher.fetch_and_save("market_index", "tpex", "2026-07-16")

    assert result is None
    assert fetcher.failure_log[-1]["error"] == INDEX_SOURCE_UNAVAILABLE


def test_market_index_endpoints_registered_by_default():
    """
    Sanity check that the endpoint registry has real, verified (non-None) URLs for
    both markets' index endpoints as of this milestone (found via swagger inspection,
    see docstring in src/data_fetcher.py) -- not accidentally left unavailable.
    """
    assert ENDPOINTS["market_index"]["twse"] == "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX"
    assert ENDPOINTS["market_index"]["tpex"] == "https://www.tpex.org.tw/openapi/v1/tpex_index"


def test_is_holiday_response_empty_list_is_holiday():
    assert is_holiday_response("ohlcv", []) is True


def test_is_holiday_response_empty_data_dict_is_holiday():
    assert is_holiday_response("institutional", {"stat": "OK", "data": []}) is True


def test_is_holiday_response_nonempty_is_not_holiday():
    assert is_holiday_response("ohlcv", SAMPLE_OHLCV_PAYLOAD) is False


def test_backfill_skips_weekends(tmp_path):
    stub = _StubFetchFn([_ok_result(SAMPLE_OHLCV_PAYLOAD) for _ in range(40)])
    fetcher = DataFetcher(data_dir=str(tmp_path), fetch_fn=stub)

    # 2026-07-16 is Thursday, 2026-07-20 is Monday -> weekend 07-18/07-19 must be skipped
    results = fetcher.backfill("2026-07-16", "2026-07-20", polite_delay_sec=0)

    assert "2026-07-16" in results
    assert "2026-07-17" in results
    assert "2026-07-18" not in results  # Saturday
    assert "2026-07-19" not in results  # Sunday
    assert "2026-07-20" in results


def test_no_endpoint_registered_returns_none(tmp_path):
    stub = _StubFetchFn([])
    fetcher = DataFetcher(data_dir=str(tmp_path), fetch_fn=stub)
    result = fetcher.fetch_and_save("nonexistent_category", "twse", "2026-07-16")
    assert result is None
    assert fetcher.failure_log[-1]["error"].startswith("No endpoint registered")


# ---------------------------------------------------------------------------
# M5a: payload date-consistency guard. Most TWSE/TPEx endpoints have NO date query
# parameter and always return their latest trading day regardless of what date the
# caller requested (confirmed against the real cached swagger definitions -- see
# scripts/build_official_mapping.py module docstring and Milestone_5a acceptance
# report). Backfilling a past date against such an endpoint must never silently
# mislabel today's data as historical.
# ---------------------------------------------------------------------------

def test_extract_payload_date_roc_row_date():
    payload = [{"Date": "1150716", "Code": "2330"}]
    assert extract_payload_date("ohlcv", payload) == "2026-07-16"


def test_extract_payload_date_top_level_date_field():
    payload = {"stat": "OK", "date": "20260717", "data": []}
    assert extract_payload_date("institutional", payload) == "2026-07-17"


def test_extract_payload_date_chinese_mi_index_field_from_real_sample():
    # Shape copied from loop/evidence/raw_samples/mi_index_20260722T203706.json.
    payload = [{"日期": "1150721", "指數": "發行量加權股價指數"}]
    assert extract_payload_date("market_index", payload) == "2026-07-21"


def test_extract_payload_date_no_date_signal_returns_none():
    # Real TWSE MI_MARGN rows carry no date field at all.
    payload = [{"股票代號": "2330", "融資買進": "100"}]
    assert extract_payload_date("margin", payload) is None


def test_extract_payload_date_empty_payload_returns_none():
    assert extract_payload_date("ohlcv", []) is None
    assert extract_payload_date("institutional", {}) is None


def test_fetch_and_save_drops_payload_when_date_mismatches_request(tmp_path):
    # Requested trade_date is 2026-06-01, but the (stubbed) response is actually for
    # 2026-07-16 -- e.g. hitting a latest-day-only endpoint during a backfill attempt.
    mismatched_payload = [{"Date": "1150716", "Code": "2330", "Name": "台積電"}]
    stub = _StubFetchFn([_ok_result(mismatched_payload)])
    fetcher = DataFetcher(data_dir=str(tmp_path), fetch_fn=stub)

    result = fetcher.fetch_and_save("ohlcv", "twse", "2026-06-01")

    assert result is None
    expected_path = tmp_path / "raw" / "ohlcv" / "twse_2026-06-01.json"
    assert not expected_path.exists(), "Mismatched-date payload must never be written to disk"
    assert fetcher.failure_log[-1]["error"] == "DATE_MISMATCH"
    assert fetcher.failure_log[-1]["payload_date"] == "2026-07-16"


def test_fetch_and_save_accepts_payload_when_date_matches_request(tmp_path):
    matching_payload = [{"Date": "1150716", "Code": "2330", "Name": "台積電"}]
    stub = _StubFetchFn([_ok_result(matching_payload)])
    fetcher = DataFetcher(data_dir=str(tmp_path), fetch_fn=stub)

    result = fetcher.fetch_and_save("ohlcv", "twse", "2026-07-16")

    assert result is not None
    assert (tmp_path / "raw" / "ohlcv" / "twse_2026-07-16.json").exists()


def test_fetch_and_save_accepts_payload_with_no_date_signal(tmp_path):
    # An endpoint whose rows carry no date at all (e.g. MI_MARGN) must not be blocked
    # by the date-consistency guard -- there's nothing to compare against.
    no_date_payload = [{"股票代號": "2330", "融資買進": "100"}]
    stub = _StubFetchFn([_ok_result(no_date_payload)])
    fetcher = DataFetcher(data_dir=str(tmp_path), fetch_fn=stub)

    result = fetcher.fetch_and_save("margin", "twse", "2026-06-01")

    assert result is not None
    assert (tmp_path / "raw" / "margin" / "twse_2026-06-01.json").exists()


# ---------------------------------------------------------------------------
# M5a: resumable backfill (skip_existing). Default behavior (skip_existing=False)
# must remain exactly what M4 shipped -- always re-fetch, always back up.
# ---------------------------------------------------------------------------

def test_fetch_and_save_default_still_refetches_existing_file(tmp_path):
    stub = _StubFetchFn([_ok_result(SAMPLE_OHLCV_PAYLOAD), _ok_result(SAMPLE_OHLCV_PAYLOAD)])
    fetcher = DataFetcher(data_dir=str(tmp_path), fetch_fn=stub)
    fetcher.fetch_and_save("ohlcv", "twse", "2026-07-16")
    fetcher.fetch_and_save("ohlcv", "twse", "2026-07-16")  # no skip_existing -> refetches
    assert len(stub.calls) == 2


def test_fetch_and_save_skip_existing_does_not_refetch(tmp_path):
    stub = _StubFetchFn([_ok_result(SAMPLE_OHLCV_PAYLOAD)])
    fetcher = DataFetcher(data_dir=str(tmp_path), fetch_fn=stub)
    fetcher.fetch_and_save("ohlcv", "twse", "2026-07-16")

    result = fetcher.fetch_and_save("ohlcv", "twse", "2026-07-16", skip_existing=True)

    assert len(stub.calls) == 1  # second call never hit the network
    assert result is not None
    assert result["payload"] == SAMPLE_OHLCV_PAYLOAD


def test_fetch_and_save_skip_existing_still_fetches_when_file_absent(tmp_path):
    stub = _StubFetchFn([_ok_result(SAMPLE_OHLCV_PAYLOAD)])
    fetcher = DataFetcher(data_dir=str(tmp_path), fetch_fn=stub)

    result = fetcher.fetch_and_save("ohlcv", "twse", "2026-07-16", skip_existing=True)

    assert len(stub.calls) == 1
    assert result is not None


def test_fetch_and_save_skip_existing_refetches_when_existing_file_corrupt(tmp_path):
    bad_path = tmp_path / "raw" / "ohlcv"
    bad_path.mkdir(parents=True)
    (bad_path / "twse_2026-07-16.json").write_text("{not valid json", encoding="utf-8")

    stub = _StubFetchFn([_ok_result(SAMPLE_OHLCV_PAYLOAD)])
    fetcher = DataFetcher(data_dir=str(tmp_path), fetch_fn=stub)

    result = fetcher.fetch_and_save("ohlcv", "twse", "2026-07-16", skip_existing=True)

    assert len(stub.calls) == 1  # corrupt file did not block a real fetch
    assert result is not None


def test_backfill_skip_existing_resumes_partial_run(tmp_path):
    stub = _StubFetchFn([_ok_result(SAMPLE_OHLCV_PAYLOAD) for _ in range(40)])
    fetcher = DataFetcher(data_dir=str(tmp_path), fetch_fn=stub)

    # Pre-seed 2026-07-16's ohlcv/twse file as if a prior run already succeeded there.
    seed_dir = tmp_path / "raw" / "ohlcv"
    seed_dir.mkdir(parents=True)
    seed_envelope = _ok_result(SAMPLE_OHLCV_PAYLOAD).envelope
    with open(seed_dir / "twse_2026-07-16.json", "w", encoding="utf-8") as f:
        json.dump(seed_envelope, f, ensure_ascii=False)

    fetcher.backfill("2026-07-16", "2026-07-17", categories=["ohlcv"],
                      polite_delay_sec=0, skip_existing=True)

    # twse/2026-07-16 must NOT have been re-fetched (already existed); everything else
    # in this 2-weekday range (tpex/2026-07-16, twse+tpex/2026-07-17) must have been.
    # Count only the primary (undated) attempts: the stub replays a payload dated
    # 1150716 for every call, so the 2026-07-17 requests legitimately trip
    # DATE_MISMATCH and each earns one extra dated-endpoint retry. Those retries
    # say nothing about skip_existing, which is what this test is about.
    undated_urls = {url for markets in ENDPOINTS.values() for url in markets.values() if url}
    undated_calls = [(url, cat) for url, cat in stub.calls if url.split("?")[0] in undated_urls]
    assert len(undated_calls) == 3  # 4 total (category,market) x 2 days - 1 skipped
