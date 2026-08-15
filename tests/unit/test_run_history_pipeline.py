import os
import sys
import json
import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from scripts.run_history_pipeline import (
    discover_available_dates, discover_finmind_dates, bridge_finmind_dates,
    _extract_signal_events, _write_signals_jsonl, run_history_pipeline,
)


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{}")


def test_discover_available_dates_requires_both_markets(tmp_path):
    ohlcv_dir = tmp_path / "raw" / "ohlcv"
    _touch(str(ohlcv_dir / "twse_2026-04-20.json"))
    _touch(str(ohlcv_dir / "tpex_2026-04-20.json"))
    _touch(str(ohlcv_dir / "twse_2026-04-21.json"))  # tpex missing for this date

    dates = discover_available_dates(str(tmp_path))
    assert dates == ["2026-04-20"]


def test_discover_available_dates_sorted_ascending(tmp_path):
    ohlcv_dir = tmp_path / "raw" / "ohlcv"
    for d in ["2026-04-22", "2026-04-20", "2026-04-21"]:
        _touch(str(ohlcv_dir / f"twse_{d}.json"))
        _touch(str(ohlcv_dir / f"tpex_{d}.json"))

    dates = discover_available_dates(str(tmp_path))
    assert dates == ["2026-04-20", "2026-04-21", "2026-04-22"]


def test_discover_available_dates_filters_start_end(tmp_path):
    ohlcv_dir = tmp_path / "raw" / "ohlcv"
    for d in ["2026-04-20", "2026-05-01", "2026-06-01"]:
        _touch(str(ohlcv_dir / f"twse_{d}.json"))
        _touch(str(ohlcv_dir / f"tpex_{d}.json"))

    dates = discover_available_dates(str(tmp_path), start="2026-04-25", end="2026-05-15")
    assert dates == ["2026-05-01"]


def test_discover_available_dates_ignores_bak_files(tmp_path):
    ohlcv_dir = tmp_path / "raw" / "ohlcv"
    _touch(str(ohlcv_dir / "twse_2026-04-20.json"))
    _touch(str(ohlcv_dir / "tpex_2026-04-20.json"))
    _touch(str(ohlcv_dir / "twse_2026-04-20.json.bak"))

    dates = discover_available_dates(str(tmp_path))
    assert dates == ["2026-04-20"]


def test_extract_signal_events_empty_df_returns_empty_list():
    assert _extract_signal_events("2026-07-17", None) == []
    assert _extract_signal_events("2026-07-17", pd.DataFrame()) == []


def test_extract_signal_events_flattens_all_rows_not_just_hits():
    df = pd.DataFrame([
        {"sector_name": "半導體", "sector_type": "primary_sector", "signal_type": "A級新起漲",
         "score": 85.0, "signal_data_confidence": "FULL", "invalidation_condition": None,
         "up_stock_count": 5},
        {"sector_name": "紡織", "sector_type": "primary_sector", "signal_type": "無訊號",
         "score": 40.0, "signal_data_confidence": "FULL", "invalidation_condition": None,
         "up_stock_count": 1},
    ])
    events = _extract_signal_events("2026-07-17", df)
    assert len(events) == 2  # both hit and non-hit rows included
    assert events[0]["signal_type"] == "A級新起漲"
    assert events[1]["signal_type"] == "無訊號"
    assert all(e["trade_date"] == "2026-07-17" for e in events)


def test_write_signals_jsonl_one_json_object_per_line(tmp_path):
    events = [
        {"trade_date": "2026-07-17", "sector_name": "半導體", "signal_type": "A級新起漲"},
        {"trade_date": "2026-07-17", "sector_name": "紡織", "signal_type": "無訊號"},
    ]
    path = _write_signals_jsonl(str(tmp_path), "2026-07-17", events)
    assert os.path.exists(path)
    assert path.endswith("signals_2026-07-17.jsonl")

    with open(path, encoding="utf-8") as f:
        lines = [line for line in f.read().splitlines() if line.strip()]
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["sector_name"] == "半導體"
    assert parsed[1]["sector_name"] == "紡織"


def test_write_signals_jsonl_empty_events_writes_empty_file(tmp_path):
    path = _write_signals_jsonl(str(tmp_path), "2026-07-17", [])
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert content == ""


class _StubRunPipeline:
    """
    Scripted stand-in for scripts.run_daily.run_pipeline: returns a pre-scripted audit
    dict (with a "_df_final_sectors" sector-signal frame) per date, in call order, so
    the batch driver's sequencing/prev_date-threading/JSONL-writing logic can be tested
    without touching the real fetch/feature/scoring chain (already covered by M2/M3/M4
    tests).
    """
    def __init__(self, audits_by_date):
        self.audits_by_date = audits_by_date
        self.calls = []

    def __call__(self, trade_date, prev_date=None, use_calibrated_thresholds=False):
        self.calls.append((trade_date, prev_date))
        audit = self.audits_by_date.get(trade_date)
        if audit is None:
            return {"status": "BLOCKED_NO_MAPPING", "trade_date": trade_date}
        return dict(audit)  # shallow copy so .pop() in the driver doesn't mutate the fixture


def _success_audit(df_sectors):
    return {"status": "SUCCESS", "_df_final_sectors": df_sectors, "_df_scored_stocks": pd.DataFrame()}


def test_run_history_pipeline_processes_dates_in_order_and_threads_prev_date(tmp_path):
    dates = ["2026-07-14", "2026-07-15", "2026-07-16"]
    df_sig = pd.DataFrame([{"sector_name": "半導體", "sector_type": "primary_sector",
                             "signal_type": "無訊號", "score": 50.0}])
    stub = _StubRunPipeline({d: _success_audit(df_sig) for d in dates})

    result = run_history_pipeline(dates=dates, output_dir=str(tmp_path), run_pipeline_fn=stub)

    assert stub.calls == [
        ("2026-07-14", None),
        ("2026-07-15", "2026-07-14"),
        ("2026-07-16", "2026-07-15"),
    ]
    assert result["days_success"] == 3
    assert result["days_blocked"] == 0
    assert result["total_signal_events"] == 3  # 1 sector row per day x 3 days


def test_run_history_pipeline_writes_one_jsonl_per_successful_day(tmp_path):
    dates = ["2026-07-14", "2026-07-15"]
    df_sig = pd.DataFrame([
        {"sector_name": "半導體", "sector_type": "primary_sector", "signal_type": "A級新起漲", "score": 88.0},
        {"sector_name": "紡織", "sector_type": "primary_sector", "signal_type": "無訊號", "score": 30.0},
    ])
    stub = _StubRunPipeline({d: _success_audit(df_sig) for d in dates})

    run_history_pipeline(dates=dates, output_dir=str(tmp_path), run_pipeline_fn=stub)

    for d in dates:
        path = os.path.join(str(tmp_path), "signals", f"signals_{d}.jsonl")
        assert os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
        assert len(lines) == 2


def test_run_history_pipeline_blocked_day_does_not_write_jsonl_but_continues(tmp_path):
    dates = ["2026-07-14", "2026-07-15", "2026-07-16"]
    df_sig = pd.DataFrame([{"sector_name": "半導體", "sector_type": "primary_sector",
                             "signal_type": "無訊號", "score": 50.0}])
    # Day 2 is missing from the stub's audits_by_date -> returns BLOCKED_NO_MAPPING.
    stub = _StubRunPipeline({
        "2026-07-14": _success_audit(df_sig),
        "2026-07-16": _success_audit(df_sig),
    })

    result = run_history_pipeline(dates=dates, output_dir=str(tmp_path), run_pipeline_fn=stub)

    assert result["days_success"] == 2
    assert result["days_blocked"] == 1
    # All 3 dates still attempted -- one blocked day must not abort the batch.
    assert len(stub.calls) == 3
    assert not os.path.exists(os.path.join(str(tmp_path), "signals", "signals_2026-07-15.jsonl"))
    assert os.path.exists(os.path.join(str(tmp_path), "signals", "signals_2026-07-16.jsonl"))


def test_run_history_pipeline_records_per_day_signal_counts(tmp_path):
    dates = ["2026-07-14"]
    df_sig = pd.DataFrame([
        {"sector_name": "A", "sector_type": "primary_sector", "signal_type": "A級新起漲", "score": 90},
        {"sector_name": "B", "sector_type": "primary_sector", "signal_type": "B級早期點火", "score": 75},
        {"sector_name": "C", "sector_type": "primary_sector", "signal_type": "無訊號", "score": 20},
    ])
    stub = _StubRunPipeline({"2026-07-14": _success_audit(df_sig)})

    result = run_history_pipeline(dates=dates, output_dir=str(tmp_path), run_pipeline_fn=stub)

    assert result["signals_per_day"]["2026-07-14"] == 3


# ---------------------------------------------------------------------------
# M5b: FinMind date discovery + legacy bridging + use_finmind wiring.
# ---------------------------------------------------------------------------

def _write_finmind_ohlcv(data_dir, stock_id, dates):
    d = os.path.join(data_dir, "raw", "ohlcv")
    os.makedirs(d, exist_ok=True)
    payload = [{"date": d_, "stock_id": stock_id, "open": 10.0, "max": 10.5, "min": 9.5, "close": 10.2}
               for d_ in dates]
    with open(os.path.join(d, f"finmind_{stock_id}.json"), "w", encoding="utf-8") as f:
        json.dump({"metadata": {}, "payload": payload}, f, ensure_ascii=False)


def test_discover_finmind_dates_unions_across_stocks(tmp_path):
    _write_finmind_ohlcv(str(tmp_path), "1101", ["2026-04-20", "2026-04-21"])
    _write_finmind_ohlcv(str(tmp_path), "1102", ["2026-04-21", "2026-04-22"])

    dates = discover_finmind_dates(str(tmp_path))

    assert dates == ["2026-04-20", "2026-04-21", "2026-04-22"]


def test_discover_finmind_dates_filters_start_end(tmp_path):
    _write_finmind_ohlcv(str(tmp_path), "1101", ["2026-04-20", "2026-05-01", "2026-06-01"])

    dates = discover_finmind_dates(str(tmp_path), start="2026-04-25", end="2026-05-15")

    assert dates == ["2026-05-01"]


def test_discover_finmind_dates_no_files_returns_empty(tmp_path):
    assert discover_finmind_dates(str(tmp_path)) == []


def test_bridge_finmind_dates_calls_prepare_for_each_date(tmp_path, monkeypatch):
    calls = []

    def fake_prepare(data_dir, trade_date):
        calls.append((data_dir, trade_date))
        return {"ohlcv/twse_prices_" + trade_date + ".json": "written_from_finmind"}

    import scripts.run_history_pipeline as rhp
    monkeypatch.setattr(rhp, "prepare_finmind_legacy_snapshot", fake_prepare)

    results = bridge_finmind_dates(str(tmp_path), ["2026-04-20", "2026-04-21"])

    assert len(calls) == 2
    assert set(results.keys()) == {"2026-04-20", "2026-04-21"}


def test_run_history_pipeline_use_finmind_false_ignores_finmind_only_dates(tmp_path):
    """Default behavior (use_finmind=False) must be byte-for-byte the pre-M5b
    contract: FinMind-only dates are never discovered or processed."""
    _write_finmind_ohlcv(str(tmp_path), "1101", ["2026-04-20"])
    df_sig = pd.DataFrame([{"sector_name": "A", "sector_type": "primary_sector",
                             "signal_type": "無訊號", "score": 50.0}])
    stub = _StubRunPipeline({"2026-04-20": _success_audit(df_sig)})

    result = run_history_pipeline(data_dir=str(tmp_path), output_dir=str(tmp_path),
                                   run_pipeline_fn=stub, use_finmind=False)

    assert stub.calls == []  # no official dates exist, and finmind wasn't opted into
    assert result["days_success"] == 0


def test_run_history_pipeline_use_finmind_true_includes_finmind_only_dates(tmp_path, monkeypatch):
    _write_finmind_ohlcv(str(tmp_path), "1101", ["2026-04-20"])
    df_sig = pd.DataFrame([{"sector_name": "A", "sector_type": "primary_sector",
                             "signal_type": "無訊號", "score": 50.0}])
    stub = _StubRunPipeline({"2026-04-20": _success_audit(df_sig)})

    # Bridging itself is exercised separately (test_bridge_finmind_dates_*); stub it
    # out here so this test focuses purely on date-set wiring, not the bridge's own
    # file-writing logic.
    import scripts.run_history_pipeline as rhp
    monkeypatch.setattr(rhp, "bridge_finmind_dates", lambda data_dir, dates: {})

    result = run_history_pipeline(data_dir=str(tmp_path), output_dir=str(tmp_path),
                                   run_pipeline_fn=stub, use_finmind=True)

    assert stub.calls == [("2026-04-20", None)]
    assert result["days_success"] == 1


def test_run_history_pipeline_use_finmind_true_unions_with_official_dates(tmp_path, monkeypatch):
    ohlcv_dir = tmp_path / "raw" / "ohlcv"
    _touch(str(ohlcv_dir / "twse_2026-04-19.json"))
    _touch(str(ohlcv_dir / "tpex_2026-04-19.json"))
    _write_finmind_ohlcv(str(tmp_path), "1101", ["2026-04-20"])

    df_sig = pd.DataFrame([{"sector_name": "A", "sector_type": "primary_sector",
                             "signal_type": "無訊號", "score": 50.0}])
    stub = _StubRunPipeline({
        "2026-04-19": _success_audit(df_sig), "2026-04-20": _success_audit(df_sig),
    })

    import scripts.run_history_pipeline as rhp
    monkeypatch.setattr(rhp, "bridge_finmind_dates", lambda data_dir, dates: {})

    result = run_history_pipeline(data_dir=str(tmp_path), output_dir=str(tmp_path),
                                   run_pipeline_fn=stub, use_finmind=True)

    assert stub.calls == [("2026-04-19", None), ("2026-04-20", "2026-04-19")]
    assert result["days_success"] == 2
