import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from scripts.prepare_official_margin_history_snapshot import (
    prepare_official_margin_history_snapshot,
    discover_official_margin_dates,
)


def _write_official_file(data_dir, prefix, date, payload):
    path = os.path.join(data_dir, "raw", "margin", f"{prefix}_{date}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"metadata": {"row_count": len(payload)}, "payload": payload}, f, ensure_ascii=False)
    return path


def test_bridges_both_legacy_filenames_when_both_sources_present(tmp_path):
    data_dir = str(tmp_path)
    date = "2026-07-14"
    twse_payload = [["2330", "台積電", "895", "439", "207", "11822", "12071", "471660",
                      "0", "0", "0", "3", "3", "471660", "6", " "]]
    tpex_payload = [{"SecuritiesCompanyCode": "6488", "MarginPurchase": "40", "MarginSales": "13",
                      "MarginPurchaseBalance": "5179", "ShortSale": "0", "ShortConvering": "0",
                      "ShortSaleBalance": "6", "Date": date}]
    _write_official_file(data_dir, "twse_official", date, twse_payload)
    _write_official_file(data_dir, "tpex_official", date, tpex_payload)

    report = prepare_official_margin_history_snapshot(data_dir, date)

    assert report["margin/margin_2026-07-14.json"] == "written"
    assert report["margin/tpex_margin_2026-07-14.json"] == "written"
    assert os.path.exists(os.path.join(data_dir, "raw", "margin", "margin_2026-07-14.json"))
    assert os.path.exists(os.path.join(data_dir, "raw", "margin", "tpex_margin_2026-07-14.json"))


def test_copy_preserves_already_transformed_payload_exactly_no_double_transform(tmp_path):
    """
    The payload on disk in twse_official_*/tpex_official_* is already fully
    transformed by scripts/backfill_margin_history.py (transform_twse_margin_rows /
    transform_tpex_margin_rows applied before saving) -- this bridge must be a pure
    copy, never re-applying the transform (which expects RAW rows and would corrupt
    already-transformed data).
    """
    data_dir = str(tmp_path)
    date = "2026-07-14"
    twse_payload = [["2330", "台積電", "895", "439", "207", "11822", "12071", "471660",
                      "0", "0", "0", "3", "3", "471660", "6", " "]]
    _write_official_file(data_dir, "twse_official", date, twse_payload)
    _write_official_file(data_dir, "tpex_official", date, [])

    prepare_official_margin_history_snapshot(data_dir, date)

    legacy_path = os.path.join(data_dir, "raw", "margin", "margin_2026-07-14.json")
    with open(legacy_path, encoding="utf-8") as f:
        copied = json.load(f)
    assert copied == twse_payload


def test_missing_source_reported_not_silently_skipped(tmp_path):
    data_dir = str(tmp_path)
    date = "2026-07-14"
    _write_official_file(data_dir, "twse_official", date, [["2330"] + [""] * 15])
    # tpex_official file intentionally absent.

    report = prepare_official_margin_history_snapshot(data_dir, date)

    assert report["margin/margin_2026-07-14.json"] == "written"
    assert report["margin/tpex_margin_2026-07-14.json"] == "source_missing"


def test_default_does_not_overwrite_existing_legacy_file(tmp_path):
    data_dir = str(tmp_path)
    date = "2026-07-14"
    _write_official_file(data_dir, "twse_official", date, [["2330"] + [""] * 15])
    _write_official_file(data_dir, "tpex_official", date, [])

    legacy_path = os.path.join(data_dir, "raw", "margin", f"margin_{date}.json")
    os.makedirs(os.path.dirname(legacy_path), exist_ok=True)
    with open(legacy_path, "w", encoding="utf-8") as f:
        json.dump([["9999"] + [""] * 15], f)

    report = prepare_official_margin_history_snapshot(data_dir, date, force=False)

    assert report["margin/margin_2026-07-14.json"] == "skipped_already_present"
    with open(legacy_path, encoding="utf-8") as f:
        content = json.load(f)
    assert content == [["9999"] + [""] * 15]  # untouched


def test_force_overwrites_existing_legacy_file(tmp_path):
    data_dir = str(tmp_path)
    date = "2026-07-14"
    new_payload = [["2330"] + [""] * 15]
    _write_official_file(data_dir, "twse_official", date, new_payload)
    _write_official_file(data_dir, "tpex_official", date, [])

    legacy_path = os.path.join(data_dir, "raw", "margin", f"margin_{date}.json")
    os.makedirs(os.path.dirname(legacy_path), exist_ok=True)
    with open(legacy_path, "w", encoding="utf-8") as f:
        json.dump([["9999"] + [""] * 15], f)

    report = prepare_official_margin_history_snapshot(data_dir, date, force=True)

    assert report["margin/margin_2026-07-14.json"] == "written"
    with open(legacy_path, encoding="utf-8") as f:
        content = json.load(f)
    assert content == new_payload


def test_discover_official_margin_dates_requires_both_sides_present(tmp_path):
    data_dir = str(tmp_path)
    _write_official_file(data_dir, "twse_official", "2026-07-14", [["2330"] + [""] * 15])
    _write_official_file(data_dir, "tpex_official", "2026-07-14", [])
    # 2026-07-15 has only TWSE side -- must be excluded.
    _write_official_file(data_dir, "twse_official", "2026-07-15", [["2330"] + [""] * 15])

    dates = discover_official_margin_dates(data_dir)

    assert dates == ["2026-07-14"]


def test_discover_official_margin_dates_respects_start_end_filter(tmp_path):
    data_dir = str(tmp_path)
    for d in ["2026-04-20", "2026-05-01", "2026-07-20"]:
        _write_official_file(data_dir, "twse_official", d, [["2330"] + [""] * 15])
        _write_official_file(data_dir, "tpex_official", d, [])

    dates = discover_official_margin_dates(data_dir, start="2026-04-25", end="2026-06-01")

    assert dates == ["2026-05-01"]
