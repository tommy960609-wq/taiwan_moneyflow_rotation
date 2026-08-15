import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from scripts.run_daily import _load_disposition_ids_for_date


def test_no_files_on_disk_returns_data_unavailable(tmp_path):
    result = _load_disposition_ids_for_date(str(tmp_path), "2026-07-18")
    assert result["stocks"] == {}
    assert result["data_available"] == False


def test_files_present_but_empty_payload_is_data_available_and_clean(tmp_path):
    disp_dir = tmp_path / "raw" / "disposition"
    disp_dir.mkdir(parents=True)
    with open(disp_dir / "twse_punish_2026-07-18.json", "w", encoding="utf-8") as f:
        json.dump({"metadata": {}, "payload": []}, f)

    result = _load_disposition_ids_for_date(str(tmp_path), "2026-07-18")
    assert result["data_available"] == True
    assert result["stocks"] == {}


def test_real_disposition_row_consolidated(tmp_path):
    disp_dir = tmp_path / "raw" / "disposition"
    disp_dir.mkdir(parents=True)
    envelope = {"metadata": {}, "payload": [
        {"Number": "1", "Date": "x", "Code": "2330", "Name": "X",
         "ReasonsOfDisposition": "r", "DispositionPeriod": "p",
         "DispositionMeasures": "m", "Detail": "d", "LinkInformation": "l"},
    ]}
    with open(disp_dir / "twse_punish_2026-07-18.json", "w", encoding="utf-8") as f:
        json.dump(envelope, f)

    result = _load_disposition_ids_for_date(str(tmp_path), "2026-07-18")
    assert result["data_available"] == True
    assert result["stocks"]["2330"]["kind"] == "disposition"


def test_wrong_date_file_not_picked_up(tmp_path):
    disp_dir = tmp_path / "raw" / "disposition"
    disp_dir.mkdir(parents=True)
    envelope = {"metadata": {}, "payload": [
        {"Number": "1", "Date": "x", "Code": "2330", "Name": "X",
         "ReasonsOfDisposition": "r", "DispositionPeriod": "p",
         "DispositionMeasures": "m", "Detail": "d", "LinkInformation": "l"},
    ]}
    with open(disp_dir / "twse_punish_2026-07-17.json", "w", encoding="utf-8") as f:
        json.dump(envelope, f)

    result = _load_disposition_ids_for_date(str(tmp_path), "2026-07-18")
    assert result["data_available"] == False
    assert result["stocks"] == {}
