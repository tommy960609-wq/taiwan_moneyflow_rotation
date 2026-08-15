"""Hermetic acceptance tests for the late-official-data auto-backfill loop."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from scripts import daily_orchestrator as orch


def _write_json(root, relative, payload):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _mark_prior_success(output_dir):
    _write_json(
        output_dir,
        "logs/orchestrator_summary_2026-07-20.json",
        {"final_status": "SUCCESS"},
    )


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def test_find_backfill_gaps_uses_calendar_window_and_skips_success(tmp_path):
    _write_json(
        tmp_path,
        "logs/orchestrator_summary_2026-07-20.json",
        {"final_status": "SUCCESS"},
    )
    gaps = orch._find_backfill_gaps(
        str(tmp_path), lookback_days=5, today="2026-07-22"
    )
    assert gaps == ["2026-07-21", "2026-07-22"]


def test_readiness_probe_parses_mi_index_chinese_date_and_stock_day_all_once():
    calls = []

    def request(url):
        calls.append(url)
        if url.endswith("MI_INDEX"):
            return _Response([{"日期": "1150721", "指數": "發行量加權股價指數"}])
        return _Response([{"Date": "1150721", "Code": "2330"}])

    assert orch._twse_official_latest_date(request) == "2026-07-21"
    assert len(calls) == 2
    assert calls[0].endswith("MI_INDEX")
    assert calls[1].endswith("STOCK_DAY_ALL")


def test_readiness_probe_uses_older_feed_date_when_official_feeds_disagree():
    def request(url):
        if url.endswith("MI_INDEX"):
            return _Response([{"日期": "1150722"}])
        return _Response([{"Date": "1150721"}])

    assert orch._twse_official_latest_date(request) == "2026-07-21"


def test_readiness_probe_is_fail_closed_on_http_or_parse_failure():
    calls = []

    def request(url):
        calls.append(url)
        return _Response({"unexpected": "shape"}, status_code=200)

    assert orch._twse_official_latest_date(request) is None
    # Both official endpoints are probed once; one malformed result still fails closed.
    assert len(calls) == 2


def test_gap_classification_distinguishes_delayed_and_holiday():
    assert orch._classify_gap("2026-07-22", "2026-07-21") == "DEFERRED_NOT_READY"
    assert (
        orch._classify_gap("2026-07-21", "2026-07-22", holiday_evidence=True)
        == "HOLIDAY_SKIP"
    )
    assert orch._classify_gap("2026-07-21", "2026-07-22") == "READY"


def test_auto_backfill_ready_days_call_existing_atom_oldest_first(tmp_path):
    calls = []
    _mark_prior_success(tmp_path / "outputs")

    def orchestration(**kwargs):
        calls.append(kwargs["trade_date"])
        return {"final_status": "SUCCESS", "summary_path": f"{kwargs['trade_date']}.json"}

    summary = orch.run_auto_backfill(
        today="2026-07-22",
        lookback_days=5,
        output_dir=str(tmp_path / "outputs"),
        data_dir=str(tmp_path / "data"),
        receipts_dir=str(tmp_path / "receipts"),
        readiness_fn=lambda: "2026-07-22",
        orchestration_fn=orchestration,
    )
    assert calls == ["2026-07-21", "2026-07-22"]
    assert summary["final_status"] == "SUCCESS"
    assert summary["exit_code"] == 0


def test_auto_backfill_not_ready_never_calls_fetch_pipeline_or_writes_blocked_audit(tmp_path):
    calls = []

    def orchestration(**kwargs):
        calls.append(kwargs["trade_date"])
        raise AssertionError("DEFERRED dates must not invoke the one-day atom")

    output_dir = tmp_path / "outputs"
    _mark_prior_success(output_dir)
    summary = orch.run_auto_backfill(
        today="2026-07-22",
        lookback_days=5,
        output_dir=str(output_dir),
        data_dir=str(tmp_path / "data"),
        receipts_dir=str(tmp_path / "receipts"),
        readiness_fn=lambda: "2026-07-20",
        orchestration_fn=orchestration,
    )
    assert calls == []
    assert summary["final_status"] == "DEFERRED"
    assert summary["exit_code"] == 0
    assert not (output_dir / "logs" / "audit_2026-07-21.json").exists()
    assert not (output_dir / "logs" / "audit_2026-07-22.json").exists()
    assert all(day["status"] == "DEFERRED_NOT_READY" for day in summary["days"])


def test_auto_backfill_holiday_skip_does_not_retry_holiday(tmp_path):
    receipts = tmp_path / "receipts"
    _mark_prior_success(tmp_path / "outputs")
    _write_json(
        receipts,
        "fetch_receipt_2026-07-21.json",
        {
            "results": {
                "ohlcv": {"twse": {"row_count": 0}, "tpex": {"row_count": 0}},
                "market_index": {"twse": {"row_count": 0}, "tpex": {"row_count": 0}},
            }
        },
    )
    calls = []

    def orchestration(**kwargs):
        calls.append(kwargs["trade_date"])
        return {"final_status": "SUCCESS"}

    summary = orch.run_auto_backfill(
        today="2026-07-22",
        lookback_days=5,
        output_dir=str(tmp_path / "outputs"),
        data_dir=str(tmp_path / "data"),
        receipts_dir=str(receipts),
        readiness_fn=lambda: "2026-07-22",
        orchestration_fn=orchestration,
    )
    assert calls == ["2026-07-22"]
    assert summary["days"][0]["status"] == "HOLIDAY_SKIP"
    assert summary["final_status"] == "SUCCESS"


def test_auto_backfill_successful_days_are_idempotently_skipped(tmp_path):
    output_dir = tmp_path / "outputs"
    _mark_prior_success(output_dir)
    _write_json(
        output_dir,
        "logs/orchestrator_summary_2026-07-21.json",
        {"final_status": "SUCCESS"},
    )
    _write_json(
        output_dir,
        "logs/orchestrator_summary_2026-07-22.json",
        {"final_status": "SUCCESS"},
    )

    def readiness_should_not_run():
        raise AssertionError("no readiness probe is needed when there are no gaps")

    summary = orch.run_auto_backfill(
        today="2026-07-22",
        lookback_days=5,
        output_dir=str(output_dir),
        readiness_fn=readiness_should_not_run,
        orchestration_fn=lambda **_: (_ for _ in ()).throw(AssertionError("not called")),
    )
    assert summary["gap_dates"] == []
    assert summary["final_status"] == "NO_GAPS"
    assert summary["exit_code"] == 0


def test_auto_backfill_continues_after_one_exception_and_reports_nonzero(tmp_path):
    calls = []
    _mark_prior_success(tmp_path / "outputs")

    def orchestration(**kwargs):
        date = kwargs["trade_date"]
        calls.append(date)
        if date == "2026-07-21":
            raise RuntimeError("simulated late-day failure")
        return {"final_status": "SUCCESS"}

    summary = orch.run_auto_backfill(
        today="2026-07-22",
        lookback_days=5,
        output_dir=str(tmp_path / "outputs"),
        readiness_fn=lambda: "2026-07-22",
        orchestration_fn=orchestration,
    )
    assert calls == ["2026-07-21", "2026-07-22"]
    assert summary["final_status"] == "EXCEPTION"
    assert summary["exit_code"] == 3


def test_cli_explicit_date_keeps_single_day_path(monkeypatch):
    calls = []

    def one_day(**kwargs):
        calls.append(kwargs)
        return {"final_status": "SUCCESS", "exit_code": 0}

    monkeypatch.setattr(orch, "run_daily_orchestration", one_day)
    monkeypatch.setattr(
        orch,
        "run_auto_backfill",
        lambda **_: (_ for _ in ()).throw(AssertionError("explicit --date must bypass backfill")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["daily_orchestrator.py", "--date", "2026-07-21", "--prev-date", "2026-07-20"],
    )
    with pytest.raises(SystemExit) as exc:
        orch.main()
    assert exc.value.code == 0
    assert calls[0]["trade_date"] == "2026-07-21"
    assert calls[0]["prev_date"] == "2026-07-20"


def test_cli_no_backfill_keeps_single_day_path(monkeypatch):
    calls = []

    def one_day(**kwargs):
        calls.append(kwargs)
        return {"final_status": "SUCCESS", "exit_code": 0}

    monkeypatch.setattr(orch, "run_daily_orchestration", one_day)
    monkeypatch.setattr(sys, "argv", ["daily_orchestrator.py", "--no-backfill"])
    with pytest.raises(SystemExit) as exc:
        orch.main()
    assert exc.value.code == 0
    assert calls[0]["trade_date"] is None
