# GPT Verification Handbook: Milestone 1 Compliance

This handbook provides paths and instructions for another AI (GPT) to verify that **Milestone 1** (Data Integrations & Normalization) has been completed successfully and complies with the system specifications.

---

## 1. Directory Layout & Key Documents (M1 Setup)

GPT can verify the folders and documents created under the project root `C:\Workspace_CN\taiwan_moneyflow_rotation\`.

| Document / Asset | Description | Absolute Link |
| :--- | :--- | :--- |
| **System Architecture** | Pipeline layers & data flow diagrams | [architecture.md](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/docs/architecture.md) |
| **Data Dictionary** | Table schema and validation ranges | [data_dictionary.md](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/docs/data_dictionary.md) |
| **Signal Definitions** | Gainer and continued gainer rules | [signal_definitions.md](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/docs/signal_definitions.md) |
| **OpenAPI inspect log** | Crawl risks and endpoints logs | [data_catalog_and_risk_log.md](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/docs/data_catalog_and_risk_log.md) |
| **Leaderboard Analysis**| Historical Excel gainer schema study | [historical_reports_analysis.md](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/docs/historical_reports_analysis.md) |
| **Folder manifest** | 29 Directories JSON scan results | [directory_verification_manifest.json](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/loop/evidence/directory_verification_manifest.json) |
| **M1 Acceptance Report**| Verification verdict for Milestone 1 | [Milestone_1_Acceptance_Report.md](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/docs/Milestone_1_Acceptance_Report.md) |
| **Project State** | Current progress metrics (Set to M1) | [PROJECT_STATE.md](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/loop/PROJECT_STATE.md) |
| **Task Queue** | Checked tasks queue | [TASK_QUEUE.md](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/loop/TASK_QUEUE.md) |
| **Acceptance Matrix** | Verification items mapping (M1 Checked)| [ACCEPTANCE_MATRIX.md](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/loop/ACCEPTANCE_MATRIX.md) |
| **Changelog** | M1 modifications logs | [CHANGELOG.md](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/loop/CHANGELOG.md) |
| **Pytest Run Log** | Checksum execution receipt (14 tests) | [pytest_run_log.txt](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/loop/evidence/test_logs/pytest_run_log.txt) |

---

## 2. Milestone 1 Source Code Audit Points

1.  **Rule P0-01: Full Market Dual-Market Merge & TPEx Normalizations**
    -   *Where to verify*:
        -   [data_cleaner.py](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/src/data_cleaner.py) lines 73-77 (`TradingShares` & `TransactionAmount` mapped to normalized volume and turnover).
        -   [run_daily.py](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/scripts/run_daily.py) (fetches and merges TWSE + TPEx prices).
    -   *Integration Test*: [test_run_daily.py](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/tests/integration/test_run_daily.py) (Asserts entrypoint calls both market loaders).
2.  **Rule P0-04: Ticker zero padding & ETF/Warrant exclusion**
    -   *Where to verify*: [data_cleaner.py](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/src/data_cleaner.py) lines 11-33 (`clean_ticker` and `is_valid_equity`).
3.  **Rule B-02: Null Institutional flow & Downstream preservation**
    -   *Where to verify*:
        -   [data_cleaner.py](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/src/data_cleaner.py) lines 159-216 (`clean_institutional_data` parses TWSE/TPEx keys dynamically, keeping missing values as `None`).
        -   [sector_features.py](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/src/sector_features.py) lines 28-35 (retains NaN in downstream calculations).
    -   *Unit Test*: [test_sector_features_nulls.py](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/tests/unit/test_sector_features_nulls.py) (Asserts that `inst_flow_ratio` is NaN for missing stats).
4.  **Rule B-03: Date Mismatch check & Payload parsing**
    -   *Where to verify*: [data_cleaner.py](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/src/data_cleaner.py) lines 44-53 (`parse_roc_date` handles ROC format `'1150717'` -> `'2026-07-17'`) and lines 61-64 (drops rows if dates mismatch).
    -   *Unit Test*: [test_data_cleaner.py](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/tests/unit/test_data_cleaner.py) lines 71-80 (`test_date_mismatch_dropped`).
5.  **Rule B2 / C07: Leaderboard Deviation reconciliation check**
    -   *Where to verify*: [data_cleaner.py](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/src/data_cleaner.py) lines 145-148 (Any single deviation sets warning status).
    -   *Unit Test*: [test_data_cleaner.py](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/tests/unit/test_data_cleaner.py) lines 82-96 (`test_reconciliation_any_deviation_warns`).
6.  **Rule B3: Margin Trading Integration**
    -   *Where to verify*: [data_cleaner.py](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/src/data_cleaner.py) lines 218-274 (`clean_margin_data` parses TWSE/TPEx margin inputs, keeping missing stats as `None`).

---

## 3. Reproductibility Verification Commands

To check Python compilation and run verification scripts:
```powershell
Set-Location "C:\Workspace_CN"

# 1. Query endpoints and download raw json samples with meta logging
& "Quant-Agent\.venv\Scripts\python.exe" -X utf8 taiwan_moneyflow_rotation/scripts/inspect_endpoints.py

# 2. Run directory verification script
& "Quant-Agent\.venv\Scripts\python.exe" -X utf8 taiwan_moneyflow_rotation/scripts/verify_directories.py

# 3. Run E2E real-sample isolated full-market smoke test
& "Quant-Agent\.venv\Scripts\python.exe" -X utf8 taiwan_moneyflow_rotation/scripts/smoke_test_pipeline.py

# 4. Run test runner to generate pytest UTF-8 logs
& "Quant-Agent\.venv\Scripts\python.exe" -X utf8 taiwan_moneyflow_rotation/scripts/run_tests_and_log.py
```
