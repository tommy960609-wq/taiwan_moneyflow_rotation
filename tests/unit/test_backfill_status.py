"""
Milestone 8: tests for scripts/backfill_status.py, the direct-disk-scan progress truth
tool (see docs/open_issues_audit_2026-07-19.md #22 / loop/KNOWN_ISSUES.md #7 for why a
disk-scan tool was needed -- the pre-existing receipt file is a stale single-execution
snapshot, not cumulative progress). All tests build synthetic tmp_path fixtures; none
touch the real data/ directory or the live background drip process.
"""
import sys
import os
import json
import time

import openpyxl
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from scripts.backfill_status import (
    compute_backfill_status,
    _get_universe_size,
    _scan_category,
    _scan_margin_date_sources,
)


def _write_mapping_xlsx(path, n_rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["stock_id", "stock_name", "primary_sector"])
    for i in range(n_rows):
        ws.append([f"{1000+i}", f"Stock{i}", "Sector"])
    wb.save(path)


def _touch_finmind_file(category_dir, stock_id, content=None):
    os.makedirs(category_dir, exist_ok=True)
    path = os.path.join(category_dir, f"finmind_{stock_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(content or {"payload": []}, f)
    return path


def test_universe_size_missing_mapping_returns_none(tmp_path):
    missing = str(tmp_path / "nope.xlsx")
    assert _get_universe_size(missing) is None


def test_universe_size_reads_row_count(tmp_path):
    mapping_path = tmp_path / "mapping.xlsx"
    _write_mapping_xlsx(mapping_path, 10)
    assert _get_universe_size(str(mapping_path)) == 10


def test_scan_category_missing_dir(tmp_path):
    result = _scan_category(str(tmp_path), "ohlcv")
    assert result["dir_exists"] is False
    assert result["file_count"] == 0


def test_scan_category_counts_only_finmind_stock_files(tmp_path):
    data_dir = tmp_path
    cat_dir = os.path.join(str(data_dir), "raw", "ohlcv")
    _touch_finmind_file(cat_dir, "2330")
    _touch_finmind_file(cat_dir, "2317")
    # These must NOT be counted -- different artifact family (same-day snapshots).
    os.makedirs(cat_dir, exist_ok=True)
    with open(os.path.join(cat_dir, "twse_prices_2026-07-17.json"), "w", encoding="utf-8") as f:
        json.dump({}, f)
    with open(os.path.join(cat_dir, "_smoke_twse_sample.json"), "w", encoding="utf-8") as f:
        json.dump({}, f)

    result = _scan_category(str(data_dir), "ohlcv")
    assert result["file_count"] == 2
    assert sorted(result["stock_ids"]) == ["2317", "2330"]


def test_compute_backfill_status_full_coverage(tmp_path):
    data_dir = tmp_path / "data"
    mapping_path = tmp_path / "data" / "reference" / "stock_industry_mapping.xlsx"
    os.makedirs(os.path.dirname(mapping_path), exist_ok=True)
    _write_mapping_xlsx(mapping_path, 2)

    ohlcv_dir = os.path.join(str(data_dir), "raw", "ohlcv")
    _touch_finmind_file(ohlcv_dir, "1000")
    _touch_finmind_file(ohlcv_dir, "1001")

    status = compute_backfill_status(data_dir=str(data_dir), mapping_path=str(mapping_path))

    assert status["universe_size"] == 2
    assert status["categories"]["ohlcv"]["file_count"] == 2
    assert status["categories"]["ohlcv"]["coverage_pct"] == 100.0
    assert status["categories"]["institutional"]["file_count"] == 0
    assert status["categories"]["institutional"]["coverage_pct"] == 0.0
    assert status["categories"]["margin"]["dir_exists"] is False


def test_compute_backfill_status_missing_universe_never_fabricates_pct(tmp_path):
    data_dir = tmp_path / "data"
    missing_mapping = str(tmp_path / "data" / "reference" / "stock_industry_mapping.xlsx")
    ohlcv_dir = os.path.join(str(data_dir), "raw", "ohlcv")
    _touch_finmind_file(ohlcv_dir, "1000")

    status = compute_backfill_status(data_dir=str(data_dir), mapping_path=missing_mapping)

    assert status["universe_size"] is None
    # Must be None (unknown), never 0 or a fabricated percentage -- governance rule
    # "缺數據就留空給下游 fail-closed 處理".
    assert status["categories"]["ohlcv"]["coverage_pct"] is None
    assert status["categories"]["ohlcv"]["file_count"] == 1


def test_compute_backfill_status_mtimes_reflect_actual_file_times(tmp_path):
    data_dir = tmp_path / "data"
    mapping_path = tmp_path / "data" / "reference" / "stock_industry_mapping.xlsx"
    os.makedirs(os.path.dirname(mapping_path), exist_ok=True)
    _write_mapping_xlsx(mapping_path, 1)

    ohlcv_dir = os.path.join(str(data_dir), "raw", "ohlcv")
    path1 = _touch_finmind_file(ohlcv_dir, "1000")
    old_time = time.time() - 3600
    os.utime(path1, (old_time, old_time))
    path2 = _touch_finmind_file(ohlcv_dir, "1001")

    status = compute_backfill_status(data_dir=str(data_dir), mapping_path=str(mapping_path))
    ohlcv = status["categories"]["ohlcv"]
    assert ohlcv["oldest_mtime"] is not None
    assert ohlcv["newest_mtime"] is not None
    assert ohlcv["oldest_mtime"] <= ohlcv["newest_mtime"]


def test_compute_backfill_status_empty_dirs_report_none_mtimes(tmp_path):
    data_dir = tmp_path / "data"
    mapping_path = tmp_path / "data" / "reference" / "stock_industry_mapping.xlsx"
    os.makedirs(os.path.dirname(mapping_path), exist_ok=True)
    _write_mapping_xlsx(mapping_path, 5)
    os.makedirs(os.path.join(str(data_dir), "raw", "ohlcv"), exist_ok=True)

    status = compute_backfill_status(data_dir=str(data_dir), mapping_path=str(mapping_path))
    assert status["categories"]["ohlcv"]["oldest_mtime"] is None
    assert status["categories"]["ohlcv"]["newest_mtime"] is None
    assert status["categories"]["ohlcv"]["coverage_pct"] == 0.0


# ---------------------------------------------------------------------------
# margin_date_sources: per-date (not per-stock) coverage across finmind/margin/
# twse_official/tpex_official prefixes -- added for the free-official-endpoint
# margin history backfill (src/twse_tpex_margin_history.py).
# ---------------------------------------------------------------------------

def _touch_margin_date_file(margin_dir, prefix, date_str):
    os.makedirs(margin_dir, exist_ok=True)
    path = os.path.join(margin_dir, f"{prefix}_{date_str}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"payload": []}, f)
    return path


def test_scan_margin_date_sources_missing_dir(tmp_path):
    result = _scan_margin_date_sources(str(tmp_path))
    assert result["dir_exists"] is False
    assert result["all_dates"] == []


def test_scan_margin_date_sources_counts_by_prefix(tmp_path):
    margin_dir = os.path.join(str(tmp_path), "raw", "margin")
    _touch_margin_date_file(margin_dir, "twse_official", "2026-04-20")
    _touch_margin_date_file(margin_dir, "tpex_official", "2026-04-20")
    _touch_margin_date_file(margin_dir, "twse_official", "2026-04-21")
    _touch_margin_date_file(margin_dir, "margin", "2026-04-20")
    _touch_margin_date_file(margin_dir, "margin", "2026-04-22")

    result = _scan_margin_date_sources(str(tmp_path))

    assert result["dir_exists"] is True
    assert result["dates_by_prefix"]["twse_official"] == ["2026-04-20", "2026-04-21"]
    assert result["dates_by_prefix"]["tpex_official"] == ["2026-04-20"]
    assert result["dates_by_prefix"]["margin"] == ["2026-04-20", "2026-04-22"]
    assert result["dates_by_prefix"]["finmind"] == []
    assert result["all_dates"] == ["2026-04-20", "2026-04-21", "2026-04-22"]
    # Only 2026-04-20 has BOTH twse_official and tpex_official.
    assert result["twse_and_tpex_official_dates"] == ["2026-04-20"]


def test_scan_margin_date_sources_ignores_unrelated_files(tmp_path):
    margin_dir = os.path.join(str(tmp_path), "raw", "margin")
    os.makedirs(margin_dir, exist_ok=True)
    # Per-stock finmind file (different artifact family entirely) must not match.
    with open(os.path.join(margin_dir, "finmind_2330.json"), "w", encoding="utf-8") as f:
        json.dump({}, f)
    _touch_margin_date_file(margin_dir, "twse_official", "2026-04-20")

    result = _scan_margin_date_sources(str(tmp_path))

    assert result["all_dates"] == ["2026-04-20"]


def test_compute_backfill_status_includes_margin_date_sources(tmp_path):
    data_dir = tmp_path / "data"
    mapping_path = tmp_path / "data" / "reference" / "stock_industry_mapping.xlsx"
    os.makedirs(os.path.dirname(mapping_path), exist_ok=True)
    _write_mapping_xlsx(mapping_path, 1)

    margin_dir = os.path.join(str(data_dir), "raw", "margin")
    _touch_margin_date_file(margin_dir, "twse_official", "2026-04-20")
    _touch_margin_date_file(margin_dir, "tpex_official", "2026-04-20")

    status = compute_backfill_status(data_dir=str(data_dir), mapping_path=str(mapping_path))

    mds = status["margin_date_sources"]
    assert mds["dir_exists"] is True
    assert mds["counts_by_prefix"]["twse_official"] == 1
    assert mds["counts_by_prefix"]["tpex_official"] == 1
    assert mds["total_distinct_dates"] == 1
    assert mds["twse_and_tpex_official_paired_dates"] == 1
    assert mds["earliest_date"] == "2026-04-20"
    assert mds["latest_date"] == "2026-04-20"
