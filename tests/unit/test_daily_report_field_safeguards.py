import json

from scripts.run_daily import evaluate_market_coverage


def _write_audit(path, date, twse, tpex, status="SUCCESS"):
    path.write_text(json.dumps({"trade_date": date, "status": status, "row_counts": {
        "prices_twse": twse, "prices_tpex": tpex,
    }}), encoding="utf-8")


def test_low_coverage_blocks_against_recent_success_median(tmp_path):
    for day in range(1, 6):
        _write_audit(tmp_path / f"audit_2026-07-0{day}.json", f"2026-07-0{day}", 1100, 860)

    decision = evaluate_market_coverage(
        str(tmp_path), "2026-07-20", twse_count=130, tpex_count=860,
        lookback_success_days=5, min_coverage_ratio=0.8,
    )

    assert decision["status"] == "BLOCKED_LOW_COVERAGE"
    assert decision["markets"]["TWSE"]["baseline"] == 1100


def test_cold_start_keeps_existing_nonempty_market_behavior(tmp_path):
    decision = evaluate_market_coverage(
        str(tmp_path), "2026-07-20", twse_count=1, tpex_count=1,
        lookback_success_days=5, min_coverage_ratio=0.8,
    )
    assert decision["status"] == "OK_COLD_START"
