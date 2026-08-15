import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.finmind_fetcher import (
    FinMindFetcher, FinMindResult, finmind_get, build_envelope, get_finmind_token,
    RATE_LIMITED, OTC_INDEX_UNAVAILABLE, DATASETS,
)

SAMPLE_OHLCV_PAYLOAD = [
    {"date": "2026-07-01", "stock_id": "2330", "Trading_Volume": 37544470,
     "Trading_money": 93600076825, "open": 2495.0, "max": 2505.0, "min": 2475.0,
     "close": 2505.0, "spread": 95.0, "Trading_turnover": 111091},
]

SAMPLE_STOCK_INFO_PAYLOAD = [
    {"industry_category": "半導體業", "stock_id": "2330", "stock_name": "台積電", "type": "twse", "date": "2020-01-01"},
    {"industry_category": "電腦及週邊設備業", "stock_id": "5450", "stock_name": "寶聯通", "type": "tpex", "date": "2020-06-03"},
]


def _ok(payload, http_status=200):
    return FinMindResult(success=True, payload=payload, http_status=http_status)


def _fail(error="HTTP 404", http_status=404):
    return FinMindResult(success=False, error=error, http_status=http_status)


def _rate_limited(http_status=402):
    return FinMindResult(success=False, error=RATE_LIMITED, http_status=http_status, rate_limited=True)


class _StubFetchFn:
    """Scripted sequence of FinMindResult, mimicking finmind_get's call signature."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, dataset, token=None, data_id=None, start_date=None, end_date=None,
                 max_retries=2, retry_delay_sec=3, **kwargs):
        self.calls.append({"dataset": dataset, "data_id": data_id,
                            "start_date": start_date, "end_date": end_date})
        if not self.results:
            return _fail("stub exhausted")
        return self.results.pop(0)


# ---------------------------------------------------------------------------
# get_finmind_token: never prints/logs the token, reads from env file, fails
# closed (returns None) when absent.
# ---------------------------------------------------------------------------

def test_get_finmind_token_reads_from_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("SOME_OTHER_KEY=abc\nFINMIND_API_KEY=test-token-123\n", encoding="utf-8")

    token = get_finmind_token(env_paths=[str(env_file)])

    assert token == "test-token-123"


def test_get_finmind_token_accepts_alternate_key_name(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("FINMIND_API_TOKEN=alt-token\n", encoding="utf-8")

    token = get_finmind_token(env_paths=[str(env_file)])

    assert token == "alt-token"


def test_get_finmind_token_returns_none_when_absent(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("UNRELATED=1\n", encoding="utf-8")

    token = get_finmind_token(env_paths=[str(env_file)])

    assert token is None


def test_get_finmind_token_returns_none_when_no_files_exist(tmp_path):
    missing_path = str(tmp_path / "does_not_exist.env")

    token = get_finmind_token(env_paths=[missing_path])

    assert token is None


# ---------------------------------------------------------------------------
# build_envelope: project-standard shape, source/dataset always recorded.
# ---------------------------------------------------------------------------

def test_build_envelope_shape():
    env = build_envelope("TaiwanStockPrice", "2330", SAMPLE_OHLCV_PAYLOAD, "2026-07-01", "2026-07-10")

    assert env["metadata"]["source"] == "FinMind"
    assert env["metadata"]["dataset"] == "TaiwanStockPrice"
    assert env["metadata"]["data_id"] == "2330"
    assert env["metadata"]["row_count"] == 1
    assert "sha256" in env["metadata"]
    assert env["payload"] == SAMPLE_OHLCV_PAYLOAD


# ---------------------------------------------------------------------------
# FinMindFetcher.fetch_stock_series: success/failure/rate-limit/resume paths.
# ---------------------------------------------------------------------------

def test_fetch_stock_series_success_writes_file(tmp_path):
    stub = _StubFetchFn([_ok(SAMPLE_OHLCV_PAYLOAD)])
    fetcher = FinMindFetcher(data_dir=str(tmp_path), token="tok", fetch_fn=stub)

    env = fetcher.fetch_stock_series("ohlcv", "2330", "2026-07-01", "2026-07-10")

    assert env is not None
    expected_path = tmp_path / "raw" / "ohlcv" / "finmind_2330.json"
    assert expected_path.exists()
    with open(expected_path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["metadata"]["source"] == "FinMind"
    assert saved["payload"] == SAMPLE_OHLCV_PAYLOAD
    assert fetcher.failure_log == []


def test_fetch_stock_series_failure_returns_none_fail_closed(tmp_path):
    stub = _StubFetchFn([_fail("HTTP 500", 500)])
    fetcher = FinMindFetcher(data_dir=str(tmp_path), token="tok", fetch_fn=stub)

    result = fetcher.fetch_stock_series("ohlcv", "2330", "2026-07-01", "2026-07-10")

    assert result is None
    assert not (tmp_path / "raw" / "ohlcv" / "finmind_2330.json").exists()
    assert fetcher.failure_log[0]["error"] == "HTTP 500"


def test_fetch_stock_series_empty_data_is_success_not_failure(tmp_path):
    """An empty 'data' list is a legitimate response (e.g. no trades in range), not a
    schema failure -- must still be written to disk with row_count=0."""
    stub = _StubFetchFn([_ok([])])
    fetcher = FinMindFetcher(data_dir=str(tmp_path), token="tok", fetch_fn=stub)

    env = fetcher.fetch_stock_series("ohlcv", "9999", "2026-07-01", "2026-07-10")

    assert env is not None
    assert env["metadata"]["row_count"] == 0
    assert fetcher.failure_log == []


def test_fetch_stock_series_rate_limited_sets_flag_and_returns_none(tmp_path):
    stub = _StubFetchFn([_rate_limited(402)])
    fetcher = FinMindFetcher(data_dir=str(tmp_path), token="tok", fetch_fn=stub)

    result = fetcher.fetch_stock_series("ohlcv", "2330", "2026-07-01", "2026-07-10")

    assert result is None
    assert fetcher.rate_limit_hit is True
    assert fetcher.failure_log[0]["error"] == RATE_LIMITED
    assert not (tmp_path / "raw" / "ohlcv" / "finmind_2330.json").exists()


def test_fetch_stock_series_429_also_treated_as_rate_limited(tmp_path):
    stub = _StubFetchFn([_rate_limited(429)])
    fetcher = FinMindFetcher(data_dir=str(tmp_path), token="tok", fetch_fn=stub)

    result = fetcher.fetch_stock_series("ohlcv", "2330", "2026-07-01", "2026-07-10")

    assert result is None
    assert fetcher.rate_limit_hit is True


def test_fetch_stock_series_skip_existing_same_range_no_network_call(tmp_path):
    stub = _StubFetchFn([_ok(SAMPLE_OHLCV_PAYLOAD)])
    fetcher = FinMindFetcher(data_dir=str(tmp_path), token="tok", fetch_fn=stub)
    fetcher.fetch_stock_series("ohlcv", "2330", "2026-07-01", "2026-07-10")

    result = fetcher.fetch_stock_series("ohlcv", "2330", "2026-07-01", "2026-07-10", skip_existing=True)

    assert len(stub.calls) == 1  # second call never hit the network
    assert result is not None


def test_fetch_stock_series_skip_existing_different_range_refetches(tmp_path):
    """A different date range on disk must NOT be silently treated as covering a new
    request -- re-fetch rather than return a stale partial range."""
    stub = _StubFetchFn([_ok(SAMPLE_OHLCV_PAYLOAD), _ok(SAMPLE_OHLCV_PAYLOAD)])
    fetcher = FinMindFetcher(data_dir=str(tmp_path), token="tok", fetch_fn=stub)
    fetcher.fetch_stock_series("ohlcv", "2330", "2026-04-20", "2026-05-20")

    result = fetcher.fetch_stock_series("ohlcv", "2330", "2026-04-20", "2026-07-17", skip_existing=True)

    assert len(stub.calls) == 2
    assert result is not None


def test_fetch_stock_series_skip_existing_corrupt_file_refetches(tmp_path):
    bad_dir = tmp_path / "raw" / "ohlcv"
    bad_dir.mkdir(parents=True)
    (bad_dir / "finmind_2330.json").write_text("{not valid json", encoding="utf-8")

    stub = _StubFetchFn([_ok(SAMPLE_OHLCV_PAYLOAD)])
    fetcher = FinMindFetcher(data_dir=str(tmp_path), token="tok", fetch_fn=stub)

    result = fetcher.fetch_stock_series("ohlcv", "2330", "2026-07-01", "2026-07-10", skip_existing=True)

    assert len(stub.calls) == 1
    assert result is not None


# ---------------------------------------------------------------------------
# fetch_market_index: TAIEX works, TPEx/OTC honestly unavailable, never fabricated.
# ---------------------------------------------------------------------------

def test_fetch_market_index_twse_success(tmp_path):
    index_payload = [{"date": "2026-07-01", "stock_id": "TAIEX", "open": 46234.7,
                       "max": 47293.1, "min": 46234.7, "close": 47018.99}]
    stub = _StubFetchFn([_ok(index_payload)])
    fetcher = FinMindFetcher(data_dir=str(tmp_path), token="tok", fetch_fn=stub)

    env = fetcher.fetch_market_index("twse", "2026-07-01", "2026-07-10")

    assert env is not None
    assert env["metadata"]["data_id"] == "TAIEX"
    expected_path = tmp_path / "raw" / "market_index" / "finmind_index_twse.json"
    assert expected_path.exists()


def test_fetch_market_index_tpex_returns_none_unavailable_not_fabricated(tmp_path):
    stub = _StubFetchFn([])  # must never even be called for tpex
    fetcher = FinMindFetcher(data_dir=str(tmp_path), token="tok", fetch_fn=stub)

    result = fetcher.fetch_market_index("tpex", "2026-07-01", "2026-07-10")

    assert result is None
    assert len(stub.calls) == 0  # no network call attempted for a known-unavailable series
    assert fetcher.failure_log[-1]["error"] == OTC_INDEX_UNAVAILABLE
    assert not (tmp_path / "raw" / "market_index" / "finmind_index_tpex.json").exists()


# ---------------------------------------------------------------------------
# fetch_stock_info: whole-market Chinese sector table, single call.
# ---------------------------------------------------------------------------

def test_fetch_stock_info_success(tmp_path):
    stub = _StubFetchFn([_ok(SAMPLE_STOCK_INFO_PAYLOAD)])
    fetcher = FinMindFetcher(data_dir=str(tmp_path), token="tok", fetch_fn=stub)

    env = fetcher.fetch_stock_info()

    assert env is not None
    assert env["metadata"]["row_count"] == 2
    expected_path = tmp_path / "raw" / "fundamentals" / "finmind_stock_info.json"
    assert expected_path.exists()


def test_fetch_stock_info_failure_fail_closed(tmp_path):
    stub = _StubFetchFn([_fail("HTTP 500", 500)])
    fetcher = FinMindFetcher(data_dir=str(tmp_path), token="tok", fetch_fn=stub)

    result = fetcher.fetch_stock_info()

    assert result is None
    assert not (tmp_path / "raw" / "fundamentals" / "finmind_stock_info.json").exists()


# ---------------------------------------------------------------------------
# backfill_universe: iterates stock x category, stops cleanly on rate limit,
# resumable, one stock's failure doesn't abort the batch.
# ---------------------------------------------------------------------------

def test_backfill_universe_success_all(tmp_path):
    stub = _StubFetchFn([_ok(SAMPLE_OHLCV_PAYLOAD) for _ in range(6)])
    fetcher = FinMindFetcher(data_dir=str(tmp_path), token="tok", fetch_fn=stub, polite_delay_sec=0)

    summary = fetcher.backfill_universe(["2330", "2317", "2454"], ["ohlcv", "margin"],
                                         "2026-07-01", "2026-07-10", skip_existing=True)

    assert summary["per_category"]["ohlcv"]["success"] == 3
    assert summary["per_category"]["margin"]["success"] == 3
    assert summary["requests_made"] == 6
    assert summary["rate_limited"] is False
    assert summary["stopped_early"] is False


def test_backfill_universe_one_stock_failure_does_not_abort_batch(tmp_path):
    stub = _StubFetchFn([
        _ok(SAMPLE_OHLCV_PAYLOAD),      # 2330 ok
        _fail("HTTP 500", 500),          # 2317 fails
        _ok(SAMPLE_OHLCV_PAYLOAD),      # 2454 ok
    ])
    fetcher = FinMindFetcher(data_dir=str(tmp_path), token="tok", fetch_fn=stub, polite_delay_sec=0)

    summary = fetcher.backfill_universe(["2330", "2317", "2454"], ["ohlcv"],
                                         "2026-07-01", "2026-07-10", skip_existing=True)

    assert summary["per_category"]["ohlcv"]["success"] == 2
    assert summary["per_category"]["ohlcv"]["failed"] == 1
    assert summary["requests_made"] == 3


def test_backfill_universe_stops_immediately_on_rate_limit(tmp_path):
    stub = _StubFetchFn([
        _ok(SAMPLE_OHLCV_PAYLOAD),      # 2330 ok
        _rate_limited(402),              # 2317 rate limited -> stop
        _ok(SAMPLE_OHLCV_PAYLOAD),      # would be 2454, must NEVER be called
    ])
    fetcher = FinMindFetcher(data_dir=str(tmp_path), token="tok", fetch_fn=stub, polite_delay_sec=0)

    summary = fetcher.backfill_universe(["2330", "2317", "2454"], ["ohlcv"],
                                         "2026-07-01", "2026-07-10", skip_existing=True)

    assert summary["rate_limited"] is True
    assert summary["stopped_early"] is True
    assert len(stub.calls) == 2  # third stock never attempted
    assert summary["per_category"]["ohlcv"]["success"] == 1


def test_backfill_universe_resumable_skips_already_fetched(tmp_path):
    stub = _StubFetchFn([_ok(SAMPLE_OHLCV_PAYLOAD)])
    fetcher = FinMindFetcher(data_dir=str(tmp_path), token="tok", fetch_fn=stub, polite_delay_sec=0)
    fetcher.fetch_stock_series("ohlcv", "2330", "2026-07-01", "2026-07-10")  # pre-seed

    stub2 = _StubFetchFn([_ok(SAMPLE_OHLCV_PAYLOAD)])
    fetcher2 = FinMindFetcher(data_dir=str(tmp_path), token="tok", fetch_fn=stub2, polite_delay_sec=0)
    summary = fetcher2.backfill_universe(["2330", "2317"], ["ohlcv"],
                                          "2026-07-01", "2026-07-10", skip_existing=True)

    assert summary["per_category"]["ohlcv"]["skipped_existing"] == 1
    assert summary["per_category"]["ohlcv"]["success"] == 1
    assert len(stub2.calls) == 1  # only 2317 actually hit the network


def test_backfill_universe_max_requests_caps_run(tmp_path):
    stub = _StubFetchFn([_ok(SAMPLE_OHLCV_PAYLOAD) for _ in range(10)])
    fetcher = FinMindFetcher(data_dir=str(tmp_path), token="tok", fetch_fn=stub, polite_delay_sec=0)

    summary = fetcher.backfill_universe(["2330", "2317", "2454", "2382"], ["ohlcv"],
                                         "2026-07-01", "2026-07-10", skip_existing=True,
                                         max_requests=2)

    assert summary["requests_made"] == 2
    assert summary["stopped_early"] is True


# ---------------------------------------------------------------------------
# finmind_get: HTTP-level behavior (retry, rate-limit short-circuit, malformed body).
# ---------------------------------------------------------------------------

def test_finmind_get_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    class FakeResponse:
        def __init__(self, status_code, json_data=None):
            self.status_code = status_code
            self._json_data = json_data

        def json(self):
            return self._json_data

    def fake_get(url, params=None, headers=None, verify=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 2:
            return FakeResponse(500)
        return FakeResponse(200, {"msg": "success", "data": SAMPLE_OHLCV_PAYLOAD})

    import src.finmind_fetcher as fm
    monkeypatch.setattr(fm.requests, "get", fake_get)

    result = finmind_get("TaiwanStockPrice", token="tok", data_id="2330",
                          start_date="2026-07-01", end_date="2026-07-10",
                          max_retries=2, retry_delay_sec=0)

    assert result.success is True
    assert result.payload == SAMPLE_OHLCV_PAYLOAD
    assert calls["n"] == 2


def test_finmind_get_402_short_circuits_without_retry(monkeypatch):
    calls = {"n": 0}

    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code

        def json(self):
            return {"msg": "payment required"}

    def fake_get(url, params=None, headers=None, verify=None, timeout=None):
        calls["n"] += 1
        return FakeResponse(402)

    import src.finmind_fetcher as fm
    monkeypatch.setattr(fm.requests, "get", fake_get)

    result = finmind_get("TaiwanStockPrice", token="tok", data_id="2330",
                          max_retries=2, retry_delay_sec=0)

    assert result.success is False
    assert result.rate_limited is True
    assert calls["n"] == 1  # no retry burned against an exhausted quota


def test_finmind_get_malformed_body_missing_data_key_is_failure(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"msg": "success"}  # no "data" key

    def fake_get(url, params=None, headers=None, verify=None, timeout=None):
        return FakeResponse()

    import src.finmind_fetcher as fm
    monkeypatch.setattr(fm.requests, "get", fake_get)

    result = finmind_get("TaiwanStockPrice", token="tok", data_id="2330",
                          max_retries=0, retry_delay_sec=0)

    assert result.success is False


def test_finmind_get_empty_data_list_is_success():
    """Confirms the module-level contract used throughout FinMindFetcher: an empty
    'data' list is a legitimate response, not an error."""
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"msg": "success", "data": []}

    import src.finmind_fetcher as fm

    def fake_get(url, params=None, headers=None, verify=None, timeout=None):
        return FakeResponse()

    orig = fm.requests.get
    fm.requests.get = fake_get
    try:
        result = finmind_get("TaiwanStockPrice", token="tok", data_id="9999",
                              max_retries=0, retry_delay_sec=0)
    finally:
        fm.requests.get = orig

    assert result.success is True
    assert result.payload == []


# ---------------------------------------------------------------------------
# DATASETS registry sanity -- documents the dry-run-verified names so a future
# accidental edit to a wrong/guessed name fails a test rather than shipping silently.
# ---------------------------------------------------------------------------

def test_dataset_registry_matches_dry_run_verified_names():
    assert DATASETS["ohlcv"] == "TaiwanStockPrice"
    assert DATASETS["institutional"] == "TaiwanStockInstitutionalInvestorsBuySell"
    assert DATASETS["margin"] == "TaiwanStockMarginPurchaseShortSale"
    assert DATASETS["market_index"] == "TaiwanStockPrice"
    assert DATASETS["stock_info"] == "TaiwanStockInfo"
