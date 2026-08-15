# Taiwan Moneyflow Rotation System - Milestone 0 Acceptance Report

This document compiles the absolute audit trail, verification metrics, environment parity checks, and parsed API response schemas for Milestone 0.

---

## 1. Project Health Status

-   **Target Verdict**: Milestone 0 Completed & Verified
-   **Execution Directory**: `C:\Workspace_CN\taiwan_moneyflow_rotation\`
-   **Verification Environment**: Windows 11 | Python 3.14.3 | Pytest 9.0.3

---

## 2. Milestone 0 Compliance Checklist & Evidence

### 2.1 M0-01: Directory Setup Verification (100% PASSED)
We verified the existence of all 29 expected folders. The mechanical validation manifest is saved below:
-   **Verification Manifest**: [directory_verification_manifest.json](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/loop/evidence/directory_verification_manifest.json)
-   *Execution Script*: `python taiwan_moneyflow_rotation/scripts/verify_directories.py` (Exits 0 if all folders exist).

### 2.2 M0-02: Design Specifications & Report Analysis (100% PASSED)
Core engineering specs have been successfully designed:
-   [architecture.md](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/docs/architecture.md) (Pipeline wiring spec)
-   [data_dictionary.md](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/docs/data_dictionary.md) (Standard columns and types)
-   [signal_definitions.md](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/docs/signal_definitions.md) (tagging rules)
-   [data_catalog_and_risk_log.md](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/docs/data_catalog_and_risk_log.md) (API routes map)
-   [historical_reports_analysis.md](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/docs/historical_reports_analysis.md) (Analysis of 300-row gainer Excel reports and missing data gaps)

### 2.3 M0-03: OpenAPI Dry-Run & Metadata Caching (100% PASSED)
Successfully validated connectivity and saved 5 response rows along with request metadata (URL, HTTP status, fetch time, row count, SHA256) for all 6 endpoints:
1.  **TWSE OHLCV Sample**: [twse_ohlcv_sample.json](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/loop/evidence/raw_samples/twse_ohlcv_sample.json)
2.  **TWSE Institutional Sample (T86)**: [twse_inst_sample.json](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/loop/evidence/raw_samples/twse_inst_sample.json) (Resolved to stable RWD JSON endpoint)
3.  **TWSE Margin Trading Sample**: [twse_margin_sample.json](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/loop/evidence/raw_samples/twse_margin_sample.json)
4.  **TPEx OHLCV Sample**: [tpex_ohlcv_sample.json](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/loop/evidence/raw_samples/tpex_ohlcv_sample.json) (Resolved to board quotes path)
5.  **TPEx Institutional Sample**: [tpex_inst_sample.json](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/loop/evidence/raw_samples/tpex_inst_sample.json) (Resolved to daily trading path)
6.  **TPEx Margin Trading Sample**: [tpex_margin_sample.json](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/loop/evidence/raw_samples/tpex_margin_sample.json) (Resolved to balance quotes path)

### 2.4 M0-05: Test Execution & Logs (PASSED)
 Pytest logs are captured in clean UTF-8 format inside loops files:
-   **Pytest Run Log**: [pytest_run_log.txt](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/loop/evidence/test_logs/pytest_run_log.txt)
-   **Changelog**: [CHANGELOG.md](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/loop/CHANGELOG.md)

---

## 3. How to Run Auditing Commands (For GPT / Human Reviewers)

To reproduce the Milestone 0 validation suite, execute the following PowerShell block:

```powershell
Set-Location "C:\Workspace_CN"

# 1. Install dependencies
& "Quant-Agent\.venv\Scripts\pip.exe" install -r taiwan_moneyflow_rotation/requirements.txt

# 2. Run API verification (exits non-zero on failure)
& "Quant-Agent\.venv\Scripts\python.exe" -X utf8 taiwan_moneyflow_rotation/scripts/inspect_endpoints.py

# 3. Verify folders manifest
& "Quant-Agent\.venv\Scripts\python.exe" -X utf8 taiwan_moneyflow_rotation/scripts/verify_directories.py

# 4. Run tests and log results
& "Quant-Agent\.venv\Scripts\python.exe" -X utf8 taiwan_moneyflow_rotation/scripts/run_tests_and_log.py
```
