import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

import scripts.backfill_margin_history as backfill_module
from scripts.backfill_margin_history import (
    backfill_one_date,
    run_backfill,
    _date_range,
    _output_path,
)


def _write_existing_envelope(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"metadata": {"source": "test"}, "payload": [{"a": 1}]}, f)


# ---------------------------------------------------------------------------
# _date_range
# ---------------------------------------------------------------------------

def test_date_range_inclusive():
    dates = _date_range("2026-07-01", "2026-07-03")
    assert dates == ["2026-07-01", "2026-07-02", "2026-07-03"]


def test_date_range_single_day():
    assert _date_range("2026-07-01", "2026-07-01") == ["2026-07-01"]


def test_date_range_end_before_start_returns_empty():
    assert _date_range("2026-07-05", "2026-07-01") == []


# ---------------------------------------------------------------------------
# backfill_one_date: resume / skip-existing logic
# ---------------------------------------------------------------------------

def test_backfill_one_date_skips_existing_files(tmp_path, monkeypatch):
    data_dir = str(tmp_path)
    twse_path = _output_path(data_dir, "twse", "2026-07-14")
    tpex_path = _output_path(data_dir, "tpex", "2026-07-14")
    _write_existing_envelope(twse_path)
    _write_existing_envelope(tpex_path)

    def _boom_twse(date):
        raise AssertionError("should not fetch when file already exists")

    def _boom_tpex(date):
        raise AssertionError("should not fetch when file already exists")

    monkeypatch.setattr(backfill_module, "fetch_twse_margin_history", _boom_twse)
    monkeypatch.setattr(backfill_module, "fetch_tpex_margin_history", _boom_tpex)

    result = backfill_one_date(data_dir, "2026-07-14", skip_existing=True)

    assert result == {"twse": "skipped_existing", "tpex": "skipped_existing"}


def test_backfill_one_date_fetches_when_no_resume(tmp_path, monkeypatch):
    data_dir = str(tmp_path)
    twse_path = _output_path(data_dir, "twse", "2026-07-14")
    _write_existing_envelope(twse_path)

    calls = []

    def _fake_twse(date):
        calls.append(date)
        return [["2330", "TSMC", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14"]]

    def _fake_tpex(date):
        return []

    monkeypatch.setattr(backfill_module, "fetch_twse_margin_history", _fake_twse)
    monkeypatch.setattr(backfill_module, "fetch_tpex_margin_history", _fake_tpex)
    monkeypatch.setattr(backfill_module.time, "sleep", lambda s: None)

    result = backfill_one_date(data_dir, "2026-07-14", skip_existing=False)

    assert calls == ["2026-07-14"]
    assert result["twse"] == "saved"
    assert result["tpex"] == "skipped_non_trading_day"


def test_backfill_one_date_saves_new_files(tmp_path, monkeypatch):
    data_dir = str(tmp_path)

    twse_row = ["2330", "TSMC", "1,099", "760", "27", "32,875", "33,187", "6,483,092",
                "2", "14", "0", "48", "60", "6,483,092", "1", " "]
    tpex_row = ["6488", "Env", "9,277", "2,256", "1,368", "11", "10,154", "88", "8.49",
                "119,528", "48", "0", "3", "45", "0", "0", "0.0", "119,528", "0", ""]

    monkeypatch.setattr(backfill_module, "fetch_twse_margin_history", lambda date: [twse_row])
    monkeypatch.setattr(backfill_module, "fetch_tpex_margin_history", lambda date: [tpex_row])
    monkeypatch.setattr(backfill_module.time, "sleep", lambda s: None)

    result = backfill_one_date(data_dir, "2026-07-14", skip_existing=True)

    assert result == {"twse": "saved", "tpex": "saved"}
    twse_path = _output_path(data_dir, "twse", "2026-07-14")
    tpex_path = _output_path(data_dir, "tpex", "2026-07-14")
    assert os.path.exists(twse_path)
    assert os.path.exists(tpex_path)

    with open(twse_path, encoding="utf-8") as f:
        twse_env = json.load(f)
    assert twse_env["payload"] == [twse_row]

    with open(tpex_path, encoding="utf-8") as f:
        tpex_env = json.load(f)
    assert tpex_env["payload"][0]["SecuritiesCompanyCode"] == "6488"


def test_backfill_one_date_records_failed_fetch(tmp_path, monkeypatch):
    data_dir = str(tmp_path)

    monkeypatch.setattr(backfill_module, "fetch_twse_margin_history", lambda date: None)
    monkeypatch.setattr(backfill_module, "fetch_tpex_margin_history", lambda date: None)
    monkeypatch.setattr(backfill_module.time, "sleep", lambda s: None)

    result = backfill_one_date(data_dir, "2026-07-14", skip_existing=True)

    assert result == {"twse": "failed", "tpex": "failed"}
    assert not os.path.exists(_output_path(data_dir, "twse", "2026-07-14"))
    assert not os.path.exists(_output_path(data_dir, "tpex", "2026-07-14"))


# ---------------------------------------------------------------------------
# run_backfill: aggregates across a date range
# ---------------------------------------------------------------------------

def test_run_backfill_aggregates_summary(tmp_path, monkeypatch):
    data_dir = str(tmp_path)

    def fake_twse(date):
        if date == "2026-07-15":
            return None  # simulate a failure on one day
        return []  # non-trading day for the rest

    monkeypatch.setattr(backfill_module, "fetch_twse_margin_history", fake_twse)
    monkeypatch.setattr(backfill_module, "fetch_tpex_margin_history", lambda date: [])
    monkeypatch.setattr(backfill_module.time, "sleep", lambda s: None)

    summary = run_backfill("2026-07-14", "2026-07-16", data_dir=data_dir, skip_existing=True)

    assert summary["total_dates"] == 3
    assert summary["twse"]["failed"] == 1
    assert summary["twse"]["skipped_non_trading_day"] == 2
    assert summary["tpex"]["skipped_non_trading_day"] == 3
    assert summary["failed_dates"]["twse"] == ["2026-07-15"]
