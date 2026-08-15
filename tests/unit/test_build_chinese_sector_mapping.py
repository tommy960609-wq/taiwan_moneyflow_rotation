import sys
import os
import json
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from scripts.build_chinese_sector_mapping import (
    build_chinese_name_lookup, apply_chinese_names, MAPPING_COLUMNS, run,
)

SAMPLE_STOCK_INFO = [
    # 2330: two rows on the SAME latest date -- first occurrence (半導體業) must win.
    {"stock_id": "2330", "stock_name": "台積電", "industry_category": "半導體業", "type": "twse", "date": "2026-07-18"},
    {"stock_id": "2330", "stock_name": "台積電", "industry_category": "電子工業", "type": "twse", "date": "2026-07-18"},
    # 5450: reclassification history -- older 2020 row, newer 2026 row; newer must win.
    {"stock_id": "5450", "stock_name": "寶聯通", "industry_category": "電腦及週邊設備業", "type": "tpex", "date": "2020-06-03"},
    {"stock_id": "5450", "stock_name": "寶聯通", "industry_category": "其他", "type": "tpex", "date": "2026-07-18"},
    # 1101: single row, straightforward.
    {"stock_id": "1101", "stock_name": "台泥", "industry_category": "水泥工業", "type": "twse", "date": "2026-07-18"},
    # Index/ETF-bucket rows must never be treated as a real per-stock sector name.
    {"stock_id": "TAIEX", "stock_name": "加權指數", "industry_category": "大盤", "type": "twse", "date": "None"},
]


def test_build_chinese_name_lookup_basic():
    lookup = build_chinese_name_lookup(SAMPLE_STOCK_INFO)

    assert lookup["1101"] == "水泥工業"


def test_build_chinese_name_lookup_same_date_tie_keeps_first_occurrence():
    lookup = build_chinese_name_lookup(SAMPLE_STOCK_INFO)

    assert lookup["2330"] == "半導體業"  # first occurrence, not 電子工業


def test_build_chinese_name_lookup_newer_date_wins_over_older():
    lookup = build_chinese_name_lookup(SAMPLE_STOCK_INFO)

    assert lookup["5450"] == "其他"  # 2026 row, not the 2020 row


def test_build_chinese_name_lookup_excludes_index_bucket_labels():
    lookup = build_chinese_name_lookup(SAMPLE_STOCK_INFO)

    assert "TAIEX" not in lookup


def _base_mapping_df():
    return pd.DataFrame([
        # Reviewed row (must never change)
        {"stock_id": "2330", "stock_name": "台積電", "primary_sector": "半導體",
         "secondary_sector": "先進製程", "theme_1": None, "theme_2": None, "theme_3": None,
         "supply_chain_role": "Upstream", "valid_from": "2026-01-01", "valid_to": None,
         "source": None, "reviewed": 1},
        # Non-reviewed, coded row that FinMind covers
        {"stock_id": "1101", "stock_name": "台泥", "primary_sector": "01",
         "secondary_sector": None, "theme_1": None, "theme_2": None, "theme_3": None,
         "supply_chain_role": None, "valid_from": "2026-07-18", "valid_to": None,
         "source": "TWSE官方", "reviewed": 0},
        # Non-reviewed, coded row that FinMind does NOT cover
        {"stock_id": "9999", "stock_name": "未知股", "primary_sector": "99",
         "secondary_sector": None, "theme_1": None, "theme_2": None, "theme_3": None,
         "supply_chain_role": None, "valid_from": "2026-07-18", "valid_to": None,
         "source": "TWSE官方", "reviewed": 0},
    ])


def test_apply_chinese_names_protects_reviewed_row():
    df = _base_mapping_df()
    lookup = {"1101": "水泥工業", "2330": "電子工業"}  # deliberately wrong for 2330 to prove protection

    df_updated, stats = apply_chinese_names(df, lookup)

    row_2330 = df_updated[df_updated["stock_id"] == "2330"].iloc[0]
    assert row_2330["primary_sector"] == "半導體"  # unchanged
    assert stats["reviewed_protected"] == 1


def test_apply_chinese_names_updates_covered_row_and_preserves_code():
    df = _base_mapping_df()
    lookup = {"1101": "水泥工業"}

    df_updated, stats = apply_chinese_names(df, lookup)

    row_1101 = df_updated[df_updated["stock_id"] == "1101"].iloc[0]
    assert row_1101["primary_sector"] == "水泥工業"
    assert row_1101["sector_code"] == "01"  # old code preserved, not discarded
    assert row_1101["source"] == "FinMind"
    assert stats["updated"] == 1


def test_apply_chinese_names_leaves_uncovered_row_untouched():
    df = _base_mapping_df()
    lookup = {"1101": "水泥工業"}  # does not cover 9999

    df_updated, stats = apply_chinese_names(df, lookup)

    row_9999 = df_updated[df_updated["stock_id"] == "9999"].iloc[0]
    assert row_9999["primary_sector"] == "99"  # unchanged, still a code (never blanked/guessed)
    assert stats["not_covered_by_finmind"] == 1


def test_apply_chinese_names_never_overwrites_existing_sector_code():
    """If sector_code already has a value (e.g. from a prior run), a second run must
    not clobber it with whatever primary_sector happens to be at that point."""
    df = _base_mapping_df()
    df["sector_code"] = [None, "01", None]  # 1101 already has sector_code recorded
    lookup = {"1101": "水泥工業"}

    df_updated, stats = apply_chinese_names(df, lookup)

    row_1101 = df_updated[df_updated["stock_id"] == "1101"].iloc[0]
    assert row_1101["sector_code"] == "01"


def test_apply_chinese_names_column_set_matches_expected_schema():
    df = _base_mapping_df()
    df_updated, _ = apply_chinese_names(df, {})

    for col in MAPPING_COLUMNS:
        assert col in df_updated.columns


# ---------------------------------------------------------------------------
# run(): end-to-end, real files on disk -- exercises the .xlsx backup write path
# (regression coverage for a real bug hit during manual verification: the backup
# filename must keep a valid .xlsx extension or pandas' to_excel engine inference
# fails with "No engine for filetype").
# ---------------------------------------------------------------------------

def test_run_end_to_end_writes_backup_with_valid_xlsx_extension(tmp_path):
    mapping_path = str(tmp_path / "stock_industry_mapping.xlsx")
    _base_mapping_df().to_excel(mapping_path, index=False)

    stock_info_path = str(tmp_path / "finmind_stock_info.json")
    with open(stock_info_path, "w", encoding="utf-8") as f:
        json.dump({"metadata": {}, "payload": SAMPLE_STOCK_INFO}, f, ensure_ascii=False)

    receipts_dir = str(tmp_path / "receipts")

    receipt = run(mapping_path=mapping_path, stock_info_path=stock_info_path,
                   receipts_dir=receipts_dir)

    assert receipt["status"] == "SUCCESS"
    assert os.path.exists(receipt["backup_path"])
    assert receipt["backup_path"].endswith(".xlsx")
    # backup readable back as a real xlsx (proves the write didn't silently corrupt)
    df_bak = pd.read_excel(receipt["backup_path"], dtype={"stock_id": str})
    assert len(df_bak) == 3

    df_after = pd.read_excel(mapping_path, dtype={"stock_id": str})
    row_1101 = df_after[df_after["stock_id"] == "1101"].iloc[0]
    assert row_1101["primary_sector"] == "水泥工業"
    row_2330 = df_after[df_after["stock_id"] == "2330"].iloc[0]
    assert row_2330["primary_sector"] == "半導體"  # reviewed row untouched
