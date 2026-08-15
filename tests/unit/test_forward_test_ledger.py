"""Unit tests for scripts/run_forward_test_ledger.py (forward-test ledger, observe).

Fully offline: every fixture is synthesised into tmp_path. Nothing here reads the live
project's data, and nothing here touches the network -- the ledger itself never fetches,
and these tests would fail loudly (missing file) rather than silently reach out if it
ever started to.

The four guards these tests exist to hold down, in order of how much damage their
silent failure would do:

  1. the 2026-08-04 cutoff -- one pre-cutoff row in the ledger and the whole
     out-of-sample claim is void;
  2. fingerprint isolation -- pooling events graded by different code produces a
     statistic that describes no experiment that was ever run;
  3. PENDING is null, never 0.0 -- filling an immature horizon with zero silently
     drags every median toward zero and inflates the denominator;
  4. the TAIEX row guard -- 發行量加權股價指數 vs 發行量加權股價報酬指數 differ by ~2.3x,
     so the wrong pick corrupts every excess return without raising anything.

Each of those four is red-green self-proved: see
loop/evidence/test_logs/forward_test_ledger_redgreen.txt.
"""

import importlib.util
import json
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

_spec = importlib.util.spec_from_file_location(
    "run_forward_test_ledger",
    os.path.abspath(os.path.join(os.path.dirname(__file__),
                                 "../../scripts/run_forward_test_ledger.py")),
)
ledger_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ledger_mod)


# ---------------------------------------------------------------------------
# synthetic project tree
# ---------------------------------------------------------------------------

# Weekdays only; enough bars that a 2026-08-05 signal's T+10 matures at 2026-08-19.
TRADE_DATES = [
    "2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07",
    "2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14",
    "2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21",
]
SECTOR = "測試族群"
STOCKS = ["9001", "9002"]
OOS_FROM = "2026-08-04"


def _iso_to_roc(date_str: str) -> str:
    y, m, d = date_str.split("-")
    return f"{int(y) - 1911}{m}{d}"


def _write_market_index(market_dir: str, date_str: str, close: float,
                         reported_date: str = None) -> None:
    """One MI_INDEX snapshot carrying BOTH the price index and the total-return index,
    exactly as the real TWSE payload does -- so every test that reads TAIEX is
    implicitly exercising the 報酬 guard too."""
    payload = [
        {"日期": _iso_to_roc(reported_date or date_str), "指數": "寶島股價指數",
         "收盤指數": "48,002.53"},
        {"日期": _iso_to_roc(reported_date or date_str), "指數": "發行量加權股價指數",
         "收盤指數": f"{close:,.2f}"},
        {"日期": _iso_to_roc(reported_date or date_str), "指數": "發行量加權股價報酬指數",
         "收盤指數": f"{close * 2.3:,.2f}"},
    ]
    with open(os.path.join(market_dir, f"twse_{date_str}.json"), "w", encoding="utf-8") as f:
        json.dump({"metadata": {"row_count": len(payload)}, "payload": payload}, f,
                  ensure_ascii=False)


def build_project(root, signals_by_date, dates=None, fingerprint_marker="v1"):
    """Creates a minimal but structurally real project tree under `root`.

    `signals_by_date`: {trade_date: signal_type} for the single test sector. Dates absent
    from the map get 無訊號, which is what resets an episode."""
    dates = dates or TRADE_DATES
    root = str(root)
    for sub in ("src", "config", "data/processed", "data/raw/market_index",
                "outputs/signals", "loop/evidence/forward_test"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)

    # Fingerprint inputs. Real content is irrelevant -- only their SHA-256 matters here.
    for rel in ledger_mod.FINGERPRINT_FILES:
        with open(os.path.join(root, rel), "w", encoding="utf-8") as f:
            f.write(f"# fixture {rel} {fingerprint_marker}\n")

    for i, date_str in enumerate(dates):
        # OHLCV: a gentle, strictly non-zero drift. Never near +9.5%, so the limit-up
        # lockout in src/backtester.compute_entry_price is never triggered by accident.
        rows = []
        for j, sid in enumerate(STOCKS):
            base = 100.0 + j * 10 + i * 0.7
            rows.append({"trade_date": date_str, "stock_id": sid, "open": base,
                         "high": base * 1.01, "low": base * 0.99, "close": base * 1.005,
                         "volume": 5_000_000.0})
        pd.DataFrame(rows).to_csv(
            os.path.join(root, "data/processed", f"stock_features_{date_str}.csv"),
            index=False, encoding="utf-8")

        pd.DataFrame([{"trade_date": date_str, "stock_id": sid, "primary_sector": SECTOR,
                       "theme_1": None, "theme_2": None, "theme_3": None}
                      for sid in STOCKS]).to_csv(
            os.path.join(root, "data/processed", f"stock_scored_{date_str}.csv"),
            index=False, encoding="utf-8")

        # TAIEX drifts differently from the stocks so excess return is never trivially 0.
        _write_market_index(os.path.join(root, "data/raw/market_index"), date_str,
                            20000.0 + i * 30.0)

        sig = signals_by_date.get(date_str, "無訊號")
        with open(os.path.join(root, "outputs/signals", f"signals_{date_str}.jsonl"),
                  "w", encoding="utf-8") as f:
            f.write(json.dumps({"trade_date": date_str, "sector_name": SECTOR,
                                "sector_type": "primary", "signal_type": sig},
                               ensure_ascii=False) + "\n")

    write_registration(root)
    return root


def write_registration(root, oos_from=OOS_FROM):
    per_file, _ = ledger_mod.compute_code_fingerprint(str(root))
    reg = {
        "registered_at": "2026-08-04T00:00:00",
        "cutoff_date": "2026-08-03",
        "oos_starts_from": oos_from,
        "code_fingerprint": per_file,
        "in_sample_baseline": {"C級個股事件": {"n_realized": 507,
                                              "median_excess_pct": -2.48,
                                              "win_rate": 0.33},
                               "momentum_baseline_median_excess_pct": -0.39},
        "decision_rule": {"primary_horizon_days": 10,
                          "min_realized_events_per_tier": 30,
                          "success_criteria": "fixture rule"},
    }
    path = os.path.join(str(root), "loop/evidence/forward_test",
                        ledger_mod.REGISTRATION_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False)
    return path


def ledger_dir_of(root):
    return os.path.join(str(root), "loop/evidence/forward_test")


def run_ledger(root):
    return ledger_mod.run(project_root=str(root), ledger_dir=ledger_dir_of(root))


def read_rows(root):
    return ledger_mod.read_ledger(os.path.join(ledger_dir_of(root),
                                                ledger_mod.LEDGER_FILENAME))


# ---------------------------------------------------------------------------
# 1. cutoff filtering
# ---------------------------------------------------------------------------

def test_only_events_on_or_after_cutoff_enter_the_ledger(tmp_path):
    """A signal episode on 2026-08-03 (pre-cutoff) and a separate one on 2026-08-05
    (post-cutoff). Only the second may become a ledger row -- the first is in-sample and
    has already been used to tune thresholds."""
    root = build_project(tmp_path, {"2026-08-03": "C級個股事件",
                                    "2026-08-05": "C級個股事件"})
    summary = run_ledger(root)
    rows = read_rows(root)

    assert summary["oos_starts_from"] == OOS_FROM
    assert [r["trade_date"] for r in rows] == ["2026-08-05"]
    assert min(r["trade_date"] for r in rows) >= OOS_FROM
    assert not any(r["trade_date"] < OOS_FROM for r in rows)


def test_pre_cutoff_context_still_shapes_event_boundaries(tmp_path):
    """The pre-cutoff rows are read (they must be, or episode boundaries are wrong) but
    never recorded. 2026-08-03 and 2026-08-04 are one continuous episode, so 08-04 is
    persistence, not a fresh ignition -- and the ledger is therefore empty even though a
    graded signal exists on a post-cutoff date."""
    root = build_project(tmp_path, {"2026-08-03": "C級個股事件",
                                    "2026-08-04": "C級個股事件"})
    run_ledger(root)
    assert read_rows(root) == []


def test_hand_edited_pre_cutoff_row_is_dropped_on_next_run(tmp_path):
    """Second line of defence: even a row smuggled straight into ledger.jsonl by hand is
    removed on the next run rather than being merged forward."""
    root = build_project(tmp_path, {"2026-08-05": "C級個股事件"})
    run_ledger(root)
    path = os.path.join(ledger_dir_of(root), ledger_mod.LEDGER_FILENAME)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"trade_date": "2026-05-01", "sector_name": SECTOR,
                            "sector_type": "primary", "signal_type": "C級個股事件",
                            "code_fingerprint": "deadbeefdeadbeef",
                            "excess_return_net_10d": 0.5}, ensure_ascii=False) + "\n")
    run_ledger(root)
    rows = read_rows(root)
    assert all(r["trade_date"] >= OOS_FROM for r in rows)
    assert "2026-05-01" not in {r["trade_date"] for r in rows}


# ---------------------------------------------------------------------------
# 2. fingerprint isolation
# ---------------------------------------------------------------------------

def test_different_fingerprints_are_never_pooled_into_one_statistic():
    """Two events of the same tier, one graded by each of two code revisions. Changing
    the grading logic starts a NEW experiment: the two must be summarised separately,
    and neither may count toward the other's 30-event budget."""
    rows = [
        {"trade_date": "2026-08-05", "sector_name": "A", "sector_type": "primary",
         "signal_type": "C級個股事件", "status": "TRADABLE",
         "code_fingerprint": "aaaaaaaaaaaaaaaa", "excess_return_net_10d": 0.10},
        {"trade_date": "2026-08-06", "sector_name": "B", "sector_type": "primary",
         "signal_type": "C級個股事件", "status": "TRADABLE",
         "code_fingerprint": "bbbbbbbbbbbbbbbb", "excess_return_net_10d": -0.30},
    ]
    summary = ledger_mod.summarize_by_fingerprint(rows)

    assert set(summary) == {"aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb"}
    a = summary["aaaaaaaaaaaaaaaa"]["C級個股事件"]
    b = summary["bbbbbbbbbbbbbbbb"]["C級個股事件"]
    assert a["n_realized"] == 1 and b["n_realized"] == 1
    assert a["median_excess_pct"] == pytest.approx(10.0)
    assert b["median_excess_pct"] == pytest.approx(-30.0)
    # The pooled median would be -10.0 and the pooled win rate 0.5. Neither may appear.
    assert a["win_rate"] == pytest.approx(1.0)
    assert b["win_rate"] == pytest.approx(0.0)
    for bucket in summary.values():
        for stats in bucket.values():
            assert stats["n_events"] == 1


def test_changed_code_starts_a_new_fingerprint_without_erasing_the_old_sample(tmp_path):
    root = build_project(tmp_path, {"2026-08-05": "C級個股事件"}, fingerprint_marker="v1")
    first = run_ledger(root)
    assert first["fingerprint_matches_registration"] is True

    with open(os.path.join(str(root), "src/stock_scoring.py"), "w", encoding="utf-8") as f:
        f.write("# fixture src/stock_scoring.py v2 -- grading logic changed\n")
    second = run_ledger(root)
    assert second["fingerprint_matches_registration"] is False

    rows = read_rows(root)
    fps = {r["code_fingerprint"] for r in rows}
    assert len(fps) == 2, "the pre-change sample must survive the code change"
    summary = ledger_mod.summarize_by_fingerprint(rows)
    assert len(summary) == 2
    status = open(os.path.join(ledger_dir_of(root), ledger_mod.STATUS_FILENAME),
                  encoding="utf-8").read()
    assert "實驗已重置" in status


# ---------------------------------------------------------------------------
# 3. PENDING is null, never zero
# ---------------------------------------------------------------------------

def test_immature_horizon_is_null_not_zero(tmp_path):
    """A signal three bars from the end of the data: T+1/T+3 are realized, T+10 and T+20
    cannot be and must be null. A 0.0 here would read as a flat trade and quietly drag
    every median toward zero."""
    root = build_project(tmp_path, {"2026-08-19": "C級個股事件"})
    run_ledger(root)
    rows = read_rows(root)

    assert len(rows) == 1
    row = rows[0]
    assert row["net_return_1d"] is not None
    assert row["net_return_10d"] is None
    assert row["excess_return_net_10d"] is None
    assert row["net_return_20d"] is None
    assert row["excess_return_net_20d"] is None


def test_immature_event_is_excluded_from_the_win_rate_denominator():
    rows = [
        {"trade_date": "2026-08-05", "sector_name": "A", "sector_type": "primary",
         "signal_type": "C級個股事件", "status": "TRADABLE",
         "code_fingerprint": "aaaaaaaaaaaaaaaa", "excess_return_net_10d": 0.10},
        {"trade_date": "2026-08-06", "sector_name": "B", "sector_type": "primary",
         "signal_type": "C級個股事件", "status": "PENDING",
         "code_fingerprint": "aaaaaaaaaaaaaaaa", "excess_return_net_10d": None},
    ]
    stats = ledger_mod.summarize_by_fingerprint(rows)["aaaaaaaaaaaaaaaa"]["C級個股事件"]
    assert stats["n_events"] == 2
    assert stats["n_realized"] == 1, "PENDING must not enter the denominator"
    assert stats["win_rate"] == pytest.approx(1.0)
    assert stats["sample_sufficient"] is False


# ---------------------------------------------------------------------------
# 4. append-only merge + PENDING -> realized maturation
# ---------------------------------------------------------------------------

def test_rerun_does_not_duplicate_or_drop_existing_keys(tmp_path):
    root = build_project(tmp_path, {"2026-08-05": "C級個股事件"})
    run_ledger(root)
    before = read_rows(root)
    run_ledger(root)
    after = read_rows(root)

    keys_before = {ledger_mod.ledger_key(r) for r in before}
    keys_after = {ledger_mod.ledger_key(r) for r in after}
    assert keys_before <= keys_after
    assert len(after) == len(keys_after), "no duplicate keys after a re-run"


def test_pending_matures_into_a_realized_return_on_the_same_row(tmp_path):
    """The maturation path: run once with data that stops before T+10, then again once
    the later bars exist. Same key, same first_seen_at, now with a realized return."""
    short_dates = TRADE_DATES[:6]
    root = build_project(tmp_path, {"2026-08-05": "C級個股事件"}, dates=short_dates)
    run_ledger(root)
    early = read_rows(root)
    assert len(early) == 1
    assert early[0]["excess_return_net_10d"] is None

    build_project(root, {"2026-08-05": "C級個股事件"}, dates=TRADE_DATES)
    write_registration(root)
    run_ledger(root)
    late = read_rows(root)

    assert len(late) == 1, "maturation updates the existing row, it does not add one"
    assert ledger_mod.ledger_key(late[0]) == ledger_mod.ledger_key(early[0])
    assert late[0]["first_seen_at"] == early[0]["first_seen_at"]
    assert late[0]["excess_return_net_10d"] is not None


def test_merge_ledger_preserves_immutable_fields_and_unseen_keys():
    existing = [
        {"trade_date": "2026-08-05", "sector_name": "A", "sector_type": "primary",
         "signal_type": "C級個股事件", "code_fingerprint": "aaaaaaaaaaaaaaaa",
         "first_seen_at": "2026-08-05T09:00:00", "last_updated_at": "2026-08-05T09:00:00",
         "status": "PENDING", "excess_return_net_10d": None},
        {"trade_date": "2026-08-06", "sector_name": "Z", "sector_type": "primary",
         "signal_type": "續漲訊號", "code_fingerprint": "aaaaaaaaaaaaaaaa",
         "first_seen_at": "2026-08-06T09:00:00", "last_updated_at": "2026-08-06T09:00:00",
         "status": "TRADABLE", "excess_return_net_10d": 0.02},
    ]
    incoming = [
        {"trade_date": "2026-08-05", "sector_name": "A", "sector_type": "primary",
         "signal_type": "C級個股事件", "code_fingerprint": "aaaaaaaaaaaaaaaa",
         "first_seen_at": "2026-08-20T09:00:00", "last_updated_at": "2026-08-20T09:00:00",
         "status": "TRADABLE", "excess_return_net_10d": 0.05},
    ]
    merged = ledger_mod.merge_ledger(existing, incoming)
    by_key = {ledger_mod.ledger_key(r): r for r in merged}

    assert len(merged) == 2, "a key absent from this run must not be deleted"
    updated = by_key[("2026-08-05", "A", "primary", "C級個股事件", "aaaaaaaaaaaaaaaa")]
    assert updated["first_seen_at"] == "2026-08-05T09:00:00", "first_seen_at is immutable"
    assert updated["last_updated_at"] == "2026-08-20T09:00:00"
    assert updated["status"] == "TRADABLE"
    assert updated["excess_return_net_10d"] == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# 5. the TAIEX three guards
# ---------------------------------------------------------------------------

def _index_file(tmp_path, rows):
    path = os.path.join(str(tmp_path), "twse_2026-08-03.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"payload": rows}, f, ensure_ascii=False)
    return path


def test_price_index_is_chosen_over_the_total_return_index(tmp_path):
    """發行量加權股價指數 (43,386.41) and 發行量加權股價報酬指數 (100,027.02) both match
    發行 and 加權. They differ by ~2.3x. Only the exclusion of 報酬 separates them, and
    picking the total-return index would silently corrupt every relative return."""
    path = _index_file(tmp_path, [
        {"日期": "1150803", "指數": "發行量加權股價報酬指數", "收盤指數": "100,027.02"},
        {"日期": "1150803", "指數": "發行量加權股價指數", "收盤指數": "43,386.41"},
        {"日期": "1150803", "指數": "寶島股價指數", "收盤指數": "48,002.53"},
    ])
    value = ledger_mod.taiex_close_from_index_file(path, expected_date="2026-08-03")
    assert value == pytest.approx(43386.41)
    assert value != pytest.approx(100027.02)


def test_thousands_separator_is_stripped(tmp_path):
    path = _index_file(tmp_path, [
        {"日期": "1150803", "指數": "發行量加權股價指數", "收盤指數": "43,386.41"},
    ])
    assert ledger_mod.taiex_close_from_index_file(path, "2026-08-03") == pytest.approx(43386.41)


def test_self_reported_date_mismatch_is_rejected(tmp_path):
    """A real trap on this box: data/raw/market_index/twse_2026-07-18.json actually
    carries 2026-07-17's index. Trusting the filename would insert a phantom bar and
    desynchronise the market leg of every excess return spanning it."""
    path = _index_file(tmp_path, [
        {"日期": "1150717", "指數": "發行量加權股價指數", "收盤指數": "42,671.27"},
    ])
    assert ledger_mod.taiex_close_from_index_file(path, "2026-08-03") is None
    assert ledger_mod.taiex_close_from_index_file(path, "2026-07-17") == pytest.approx(42671.27)


def test_roc_date_conversion():
    assert ledger_mod.roc_date_to_iso("1150803") == "2026-08-03"
    assert ledger_mod.roc_date_to_iso("115/08/03") == "2026-08-03"
    assert ledger_mod.roc_date_to_iso("2026-08-03") == "2026-08-03"
    assert ledger_mod.roc_date_to_iso("nonsense") is None
    assert ledger_mod.roc_date_to_iso(None) is None


# ---------------------------------------------------------------------------
# 6. fail-closed
# ---------------------------------------------------------------------------

def test_missing_taiex_yields_null_excess_not_an_exception(tmp_path):
    root = build_project(tmp_path, {"2026-08-05": "C級個股事件"})
    market_dir = os.path.join(str(root), "data/raw/market_index")
    for name in os.listdir(market_dir):
        os.remove(os.path.join(market_dir, name))

    summary = run_ledger(root)
    assert summary is not None
    rows = read_rows(root)
    assert len(rows) == 1
    assert rows[0]["net_return_1d"] is not None, "the stock leg still computes"
    assert rows[0]["market_return_1d"] is None
    assert rows[0]["excess_return_net_1d"] is None, "no market leg -> no fabricated excess"


def test_missing_price_history_yields_null_returns_not_an_exception(tmp_path):
    root = build_project(tmp_path, {"2026-08-05": "C級個股事件"})
    processed = os.path.join(str(root), "data/processed")
    for name in os.listdir(processed):
        if name.startswith("stock_features_"):
            os.remove(os.path.join(processed, name))

    summary = run_ledger(root)
    assert summary is not None
    for row in read_rows(root):
        assert row["net_return_1d"] is None
        assert row["excess_return_net_10d"] is None


def test_unreadable_index_file_returns_none(tmp_path):
    path = os.path.join(str(tmp_path), "twse_2026-08-03.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{ not json")
    assert ledger_mod.taiex_close_from_index_file(path, "2026-08-03") is None
    assert ledger_mod.taiex_close_from_index_file(
        os.path.join(str(tmp_path), "does_not_exist.json"), "2026-08-03") is None


def test_missing_registration_refuses_to_run(tmp_path):
    """No pre-registration means no frozen cutoff and no frozen decision rule. Building
    a ledger anyway would be worse than building none."""
    root = build_project(tmp_path, {"2026-08-05": "C級個股事件"})
    os.remove(os.path.join(ledger_dir_of(root), ledger_mod.REGISTRATION_FILENAME))
    assert ledger_mod.run(project_root=str(root), ledger_dir=ledger_dir_of(root)) is None


def test_missing_fingerprint_file_is_reported_as_null_not_as_unchanged(tmp_path):
    root = build_project(tmp_path, {"2026-08-05": "C級個股事件"})
    os.remove(os.path.join(str(root), "src/signal_detector.py"))
    per_file, combined = ledger_mod.compute_code_fingerprint(str(root))
    assert per_file["src/signal_detector.py"] is None
    assert combined != ledger_mod.registered_fingerprint(
        json.load(open(os.path.join(ledger_dir_of(root),
                                    ledger_mod.REGISTRATION_FILENAME), encoding="utf-8")))


# ---------------------------------------------------------------------------
# status.md readout
# ---------------------------------------------------------------------------

def test_status_md_says_it_cannot_decide_while_the_sample_is_thin(tmp_path):
    root = build_project(tmp_path, {"2026-08-05": "C級個股事件"})
    run_ledger(root)
    status = open(os.path.join(ledger_dir_of(root), ledger_mod.STATUS_FILENAME),
                  encoding="utf-8").read()
    assert "還不能下結論" in status
    assert "不可以拿來調參數或下單" in status
    assert "等於**註冊時的指紋" in status
    for tier in ledger_mod.TRACKED_TIERS:
        assert tier in status
