"""
Milestone 6: tests for scripts/daily_orchestrator.py's fail-closed contract.

Uses dependency injection (the orchestrator's fetch_fn/bridge_fn/pipeline_fn
parameters) rather than monkeypatching module-level names, so these tests exercise
exactly the same call sequence production code takes without needing network access,
a real industry mapping file, or real TWSE/TPEx data on disk -- fully hermetic, no
network calls, matches this project's existing mocking pattern
(tests/integration/test_run_daily.py).

Covers the three scenarios named in the M6 brief:
  1. Network failure at fetch -> FETCH_FAILED, pipeline never invoked, exit code 1.
  2. API returned empty/schema-mismatched for one market -> fetch reports partial
     success, pipeline is invoked (it owns the BLOCKED_MISSING_MARKET fail-closed
     check), and the orchestrator surfaces that status honestly.
  3. DQ black-out (BLOCKED_LOW_DQ) -> pipeline invoked, no signals JSONL written,
     exit code 2, no Excel report claimed.
Plus the full-success happy path and the "unexpected exception is never a bare
traceback" contract for each step.
"""

import os
import sys
import json
import tempfile
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from scripts.daily_orchestrator import run_daily_orchestration


# Keep injected-fetch tests on a future date so they exercise the fetch atom.
# Historical dates are intentionally skipped by the production orchestrator.
TEST_TRADE_DATE = (date.today() + timedelta(days=1)).isoformat()
TEST_PREV_DATE = date.today().isoformat()


def _fake_fetch_all_ok(trade_date, receipts_dir=None):
    return {
        "trade_date": trade_date,
        "results": {
            "ohlcv": {
                "twse": {"row_count": 1000, "http_status": 200},
                "tpex": {"row_count": 800, "http_status": 200},
            },
            "institutional": {
                "twse": {"row_count": 500, "http_status": 200},
                "tpex": {"row_count": 400, "http_status": 200},
            },
        },
        "failures": [],
    }


def _fake_fetch_all_failed(trade_date, receipts_dir=None):
    return {
        "trade_date": trade_date,
        "results": {
            "ohlcv": {"twse": None, "tpex": None},
            "institutional": {"twse": None, "tpex": None},
        },
        "failures": [
            {"category": "ohlcv", "market": "twse", "error": "ConnectionError: network unreachable"},
            {"category": "ohlcv", "market": "tpex", "error": "ConnectionError: network unreachable"},
        ],
    }


def _fake_fetch_partial(trade_date, receipts_dir=None):
    """TWSE OHLCV succeeded, TPEx OHLCV returned empty/schema-mismatched (saved nothing)."""
    return {
        "trade_date": trade_date,
        "results": {
            "ohlcv": {
                "twse": {"row_count": 1000, "http_status": 200},
                "tpex": None,
            },
        },
        "failures": [
            {"category": "ohlcv", "market": "tpex", "error": "empty payload after schema check"},
        ],
    }


def _fake_bridge_ok(data_dir, trade_date):
    return {"ohlcv/twse_prices_{}.json".format(trade_date): "copied"}


def _fake_pipeline_success(trade_date, prev_date=None):
    return {
        "trade_date": trade_date, "prev_date": prev_date,
        "status": "SUCCESS",
        "row_counts": {"dq_score": 91.0},
        "output_files": ["outputs/daily/MoneyFlow_Rotation_{}.xlsx".format(trade_date)],
        "_df_final_sectors": None,
        "_df_scored_stocks": None,
    }


def _fake_pipeline_blocked_low_dq(trade_date, prev_date=None):
    return {
        "trade_date": trade_date, "prev_date": prev_date,
        "status": "BLOCKED_LOW_DQ",
        "row_counts": {"dq_score": 55.0},
        "output_files": [],
    }


def _fake_pipeline_blocked_missing_market(trade_date, prev_date=None):
    return {
        "trade_date": trade_date, "prev_date": prev_date,
        "status": "BLOCKED_MISSING_MARKET",
        "row_counts": {},
        "output_files": [],
    }


def _fake_pipeline_raises(trade_date, prev_date=None):
    raise RuntimeError("simulated unexpected pipeline crash")


class TestFetchFailure:
    def test_network_failure_stops_before_pipeline(self):
        pipeline_calls = []

        def _tracking_pipeline(trade_date, prev_date=None):
            pipeline_calls.append(trade_date)
            return _fake_pipeline_success(trade_date, prev_date)

        with tempfile.TemporaryDirectory() as tmp:
            summary = run_daily_orchestration(
                trade_date=TEST_TRADE_DATE, prev_date=None,
                output_dir=tmp,
                fetch_fn=_fake_fetch_all_failed,
                bridge_fn=_fake_bridge_ok,
                pipeline_fn=_tracking_pipeline,
            )

        assert summary["final_status"] == "FETCH_FAILED"
        assert summary["exit_code"] == 1
        assert summary["fetch"]["status"] == "FETCH_FAILED"
        # Pipeline must never be invoked -- no partial/bad data should touch anything.
        assert pipeline_calls == []
        assert summary["pipeline"] is None

    def test_summary_written_to_disk_on_fetch_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_daily_orchestration(
                trade_date=TEST_TRADE_DATE, output_dir=tmp,
                fetch_fn=_fake_fetch_all_failed, bridge_fn=_fake_bridge_ok,
                pipeline_fn=_fake_pipeline_success,
            )
            summary_path = os.path.join(tmp, "logs", f"orchestrator_summary_{TEST_TRADE_DATE}.json")
            assert os.path.exists(summary_path)
            with open(summary_path, "r", encoding="utf-8") as f:
                on_disk = json.load(f)
            assert on_disk["final_status"] == "FETCH_FAILED"


class TestHistoricalFetchSafeguard:
    """The safeguard moved (2026-08-03); it was not dropped.

    Past dates used to skip the fetch atom outright, because every endpoint but
    T86 served only its own latest snapshot and a backfill would have filed
    today's data under a historical name. The cost was that any day the nightly
    run missed could never be recovered -- that is how 2026-07-28..07-31 were
    lost. The fetcher now has dated endpoints plus envelope- and row-level date
    verification, so the orchestrator fetches past dates; the "never clobber a
    verified historical file" half of the safeguard lives in run_single_day's
    skip_existing flag instead.
    """

    def test_past_date_now_fetches_so_missed_days_are_recoverable(self):
        historical_date = (date.today() - timedelta(days=7)).isoformat()
        fetch_calls = []

        def _recording_fetch(trade_date, receipts_dir=None):
            fetch_calls.append(trade_date)
            return _fake_fetch_all_ok(trade_date, receipts_dir)

        with tempfile.TemporaryDirectory() as tmp:
            summary = run_daily_orchestration(
                trade_date=historical_date, output_dir=tmp,
                fetch_fn=_recording_fetch, bridge_fn=_fake_bridge_ok,
                pipeline_fn=_fake_pipeline_success,
            )

        assert fetch_calls == [historical_date]
        assert summary["fetch"]["status"] == "OK"
        assert summary["pipeline"]["status"] == "SUCCESS"
        assert summary["final_status"] == "SUCCESS"

    def test_backfill_does_not_overwrite_an_already_verified_snapshot(self, tmp_path):
        """The half of the old safeguard that still has to hold."""
        import scripts.fetch_daily_data as fetch_daily_data

        historical_date = (date.today() - timedelta(days=7)).isoformat()
        seen = {}

        class _SpyFetcher:
            def __init__(self, data_dir=None):
                pass

            def fetch_all_categories(self, trade_date, skip_existing=False, **kwargs):
                seen["skip_existing"] = skip_existing
                return {}

            failure_log = []

        original_fetcher = fetch_daily_data.DataFetcher
        original_recovery = fetch_daily_data._fetch_tpex_historical_ohlcv
        fetch_daily_data.DataFetcher = _SpyFetcher
        fetch_daily_data._fetch_tpex_historical_ohlcv = lambda *a, **k: None
        try:
            fetch_daily_data.run_single_day(historical_date)
            assert seen["skip_existing"] is True, "a past date must not clobber existing raw files"
            seen.clear()
            fetch_daily_data.run_single_day(date.today().isoformat())
            assert seen["skip_existing"] is False, "today's run must behave exactly as before"
        finally:
            fetch_daily_data.DataFetcher = original_fetcher
            fetch_daily_data._fetch_tpex_historical_ohlcv = original_recovery


class TestPartialFetchStillReachesPipeline:
    def test_partial_fetch_proceeds_to_pipeline_which_owns_the_block(self):
        """
        API returned but one market's category was empty/schema-mismatched: the
        orchestrator does not duplicate run_pipeline's own BLOCKED_MISSING_MARKET
        check -- it proceeds, and surfaces whatever status run_pipeline reaches.
        """
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_daily_orchestration(
                trade_date=TEST_TRADE_DATE, output_dir=tmp,
                fetch_fn=_fake_fetch_partial, bridge_fn=_fake_bridge_ok,
                pipeline_fn=_fake_pipeline_blocked_missing_market,
            )
        assert summary["fetch"]["status"] == "OK"
        assert "ohlcv/tpex" in summary["fetch"]["categories_failed"]
        assert summary["pipeline"]["status"] == "BLOCKED_MISSING_MARKET"
        assert summary["final_status"] == "PIPELINE_BLOCKED"
        assert summary["exit_code"] == 2


class TestDQBlackout:
    def test_blocked_low_dq_produces_no_signals_and_exit_code_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_daily_orchestration(
                trade_date=TEST_TRADE_DATE, output_dir=tmp,
                fetch_fn=_fake_fetch_all_ok, bridge_fn=_fake_bridge_ok,
                pipeline_fn=_fake_pipeline_blocked_low_dq,
            )
        assert summary["pipeline"]["status"] == "BLOCKED_LOW_DQ"
        assert summary["final_status"] == "PIPELINE_BLOCKED"
        assert summary["exit_code"] == 2
        # Black-out day: no formal report, no signals JSONL written this run.
        assert summary["signals"]["status"] == "SKIPPED_NOT_SUCCESS"
        assert summary["signals"]["event_count"] == 0

    def test_blocked_status_does_not_write_signals_jsonl_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_daily_orchestration(
                trade_date=TEST_TRADE_DATE, output_dir=tmp,
                fetch_fn=_fake_fetch_all_ok, bridge_fn=_fake_bridge_ok,
                pipeline_fn=_fake_pipeline_blocked_low_dq,
            )
            signals_path = os.path.join(tmp, "signals", f"signals_{TEST_TRADE_DATE}.jsonl")
            assert not os.path.exists(signals_path)


class TestHappyPath:
    def test_full_success_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_daily_orchestration(
                trade_date=TEST_TRADE_DATE, prev_date=TEST_PREV_DATE, output_dir=tmp,
                fetch_fn=_fake_fetch_all_ok, bridge_fn=_fake_bridge_ok,
                pipeline_fn=_fake_pipeline_success,
            )
        assert summary["fetch"]["status"] == "OK"
        assert summary["bridge"]["status"] == "OK"
        assert summary["pipeline"]["status"] == "SUCCESS"
        assert summary["signals"]["status"] == "OK"
        assert summary["final_status"] == "SUCCESS"
        assert summary["exit_code"] == 0

    def test_prev_date_auto_detected_from_prior_success_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs_dir = os.path.join(tmp, "logs")
            os.makedirs(logs_dir, exist_ok=True)
            with open(os.path.join(logs_dir, "audit_2026-07-17.json"), "w", encoding="utf-8") as f:
                json.dump({"status": "SUCCESS", "trade_date": "2026-07-17"}, f)

            captured = {}

            def _capturing_pipeline(trade_date, prev_date=None):
                captured["prev_date"] = prev_date
                return _fake_pipeline_success(trade_date, prev_date)

            run_daily_orchestration(
                trade_date=TEST_TRADE_DATE, prev_date=None, output_dir=tmp,
                fetch_fn=_fake_fetch_all_ok, bridge_fn=_fake_bridge_ok,
                pipeline_fn=_capturing_pipeline,
            )
        assert captured["prev_date"] == "2026-07-17"

    def test_prev_date_auto_detect_ignores_blocked_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs_dir = os.path.join(tmp, "logs")
            os.makedirs(logs_dir, exist_ok=True)
            with open(os.path.join(logs_dir, "audit_2026-07-16.json"), "w", encoding="utf-8") as f:
                json.dump({"status": "SUCCESS", "trade_date": "2026-07-16"}, f)
            with open(os.path.join(logs_dir, "audit_2026-07-17.json"), "w", encoding="utf-8") as f:
                json.dump({"status": "BLOCKED_LOW_DQ", "trade_date": "2026-07-17"}, f)

            captured = {}

            def _capturing_pipeline(trade_date, prev_date=None):
                captured["prev_date"] = prev_date
                return _fake_pipeline_success(trade_date, prev_date)

            run_daily_orchestration(
                trade_date=TEST_TRADE_DATE, prev_date=None, output_dir=tmp,
                fetch_fn=_fake_fetch_all_ok, bridge_fn=_fake_bridge_ok,
                pipeline_fn=_capturing_pipeline,
            )
        # 2026-07-17 was BLOCKED, so the most recent real SUCCESS is 07-16.
        assert captured["prev_date"] == "2026-07-16"


class TestUnexpectedExceptions:
    def test_fetch_step_exception_is_caught_not_raised(self):
        def _raising_fetch(trade_date, receipts_dir=None):
            raise ConnectionError("DNS resolution failed")

        with tempfile.TemporaryDirectory() as tmp:
            summary = run_daily_orchestration(
                trade_date=TEST_TRADE_DATE, output_dir=tmp,
                fetch_fn=_raising_fetch, bridge_fn=_fake_bridge_ok,
                pipeline_fn=_fake_pipeline_success,
            )
        assert summary["final_status"] == "EXCEPTION"
        assert summary["exit_code"] == 3
        assert summary["fetch"]["status"] == "EXCEPTION"

    def test_pipeline_step_exception_is_caught_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_daily_orchestration(
                trade_date=TEST_TRADE_DATE, output_dir=tmp,
                fetch_fn=_fake_fetch_all_ok, bridge_fn=_fake_bridge_ok,
                pipeline_fn=_fake_pipeline_raises,
            )
        assert summary["final_status"] == "EXCEPTION"
        assert summary["exit_code"] == 3
        assert summary["pipeline"]["status"] == "EXCEPTION"

    def test_bridge_step_exception_is_caught_not_raised(self):
        def _raising_bridge(data_dir, trade_date):
            raise OSError("disk full")

        with tempfile.TemporaryDirectory() as tmp:
            summary = run_daily_orchestration(
                trade_date=TEST_TRADE_DATE, output_dir=tmp,
                fetch_fn=_fake_fetch_all_ok, bridge_fn=_raising_bridge,
                pipeline_fn=_fake_pipeline_success,
            )
        assert summary["final_status"] == "EXCEPTION"
        assert summary["exit_code"] == 3
        assert summary["bridge"]["status"] == "EXCEPTION"


class TestSignalsAppendIsNonFatal:
    def test_signals_write_failure_does_not_downgrade_success(self):
        """
        The Excel report already succeeded by the time signals JSONL is written --
        a failure appending signals must not retroactively report the whole run as
        failed (that would misrepresent a real successful report as a bad day).
        """
        import scripts.daily_orchestrator as orch_mod

        original = orch_mod._extract_signal_events

        def _raising_extract(*args, **kwargs):
            raise ValueError("simulated malformed sector frame")

        orch_mod._extract_signal_events = _raising_extract
        try:
            with tempfile.TemporaryDirectory() as tmp:
                summary = run_daily_orchestration(
                    trade_date=TEST_TRADE_DATE, output_dir=tmp,
                    fetch_fn=_fake_fetch_all_ok, bridge_fn=_fake_bridge_ok,
                    pipeline_fn=_fake_pipeline_success,
                )
        finally:
            orch_mod._extract_signal_events = original

        assert summary["pipeline"]["status"] == "SUCCESS"
        assert summary["signals"]["status"] == "EXCEPTION"
        # Final status still SUCCESS -- the report itself is real and good.
        assert summary["final_status"] == "SUCCESS"
        assert summary["exit_code"] == 0
