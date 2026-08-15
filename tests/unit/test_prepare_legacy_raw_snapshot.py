import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from scripts.prepare_legacy_raw_snapshot import prepare_legacy_snapshot


def _write_m4_file(data_dir, category, market, date, payload):
    path = os.path.join(data_dir, "raw", category, f"{market}_{date}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"metadata": {"row_count": len(payload)}, "payload": payload}, f, ensure_ascii=False)
    return path


def test_bridges_all_six_legacy_filenames_when_all_sources_present(tmp_path):
    data_dir = str(tmp_path)
    date = "2026-07-17"
    for category, market in [("ohlcv", "twse"), ("ohlcv", "tpex"),
                              ("institutional", "twse"), ("institutional", "tpex"),
                              ("margin", "twse"), ("margin", "tpex")]:
        _write_m4_file(data_dir, category, market, date, [{"x": 1}])

    report = prepare_legacy_snapshot(data_dir, date)

    assert report["ohlcv/twse_prices_2026-07-17.json"] == "copied"
    assert report["ohlcv/tpex_prices_2026-07-17.json"] == "copied"
    assert report["institutional/inst_2026-07-17.json"] == "copied"
    assert report["institutional/tpex_inst_2026-07-17.json"] == "copied"
    assert report["margin/margin_2026-07-17.json"] == "copied"
    assert report["margin/tpex_margin_2026-07-17.json"] == "copied"

    for legacy_relpath in report:
        assert os.path.exists(os.path.join(data_dir, "raw", legacy_relpath))


def test_copy_preserves_payload_content_exactly(tmp_path):
    data_dir = str(tmp_path)
    date = "2026-07-17"
    payload = [{"Code": "2330", "Name": "台積電"}]
    _write_m4_file(data_dir, "ohlcv", "twse", date, payload)

    prepare_legacy_snapshot(data_dir, date)

    legacy_path = os.path.join(data_dir, "raw", "ohlcv", "twse_prices_2026-07-17.json")
    with open(legacy_path, encoding="utf-8") as f:
        copied = json.load(f)
    assert copied["payload"] == payload


def test_missing_source_reported_not_silently_skipped(tmp_path):
    data_dir = str(tmp_path)
    date = "2026-07-17"
    # Only ohlcv/twse exists; everything else is missing.
    _write_m4_file(data_dir, "ohlcv", "twse", date, [{"x": 1}])

    report = prepare_legacy_snapshot(data_dir, date)

    assert report["ohlcv/twse_prices_2026-07-17.json"] == "copied"
    assert report["ohlcv/tpex_prices_2026-07-17.json"] == "source_missing"
    assert report["institutional/inst_2026-07-17.json"] == "source_missing"


def test_does_not_mutate_or_delete_original_m4_file(tmp_path):
    data_dir = str(tmp_path)
    date = "2026-07-17"
    src_path = _write_m4_file(data_dir, "ohlcv", "twse", date, [{"x": 1}])

    prepare_legacy_snapshot(data_dir, date)

    assert os.path.exists(src_path)  # original untouched
    with open(src_path, encoding="utf-8") as f:
        original = json.load(f)
    assert original["payload"] == [{"x": 1}]
