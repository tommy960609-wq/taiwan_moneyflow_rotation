# Compliance Verification Report: Milestone 1

This report tracks system compliance of the project during the Milestone 1 verification audit.

---

## 1. Compliance Checklist & Audit Evidence

### 1.1 Project Layout & M0 Documents (PASSED)
-   **M0-01: Directory Setup**: Validated via JSON manifest.
-   **M0-02: Specifications**: Docs created under `docs/`.

### 1.2 M1-01: Full Market Dual-Market Merge & TPEx Normalizations (B1 Compliance)
-   *Evidence*: Mapped TPEx volume `'TradingShares'` and turnover `'TransactionAmount'` columns. Merged both markets inside the production daily runner `run_daily.py`.
-   *Source References*: [data_cleaner.py](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/src/data_cleaner.py) lines 73-77 and [run_daily.py](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/scripts/run_daily.py).
-   *Verification*: Checked inside `test_run_daily.py` ensuring loaders for both markets are called.
-   *Status*: **PASSED** (Resolves Blocker B1).

### 1.3 B-03: Date Mismatch check & Payload parsing (B3 Compliance)
-   *Evidence*: Parsed ROC Date payload format (`parse_roc_date`, e.g. `'1150716'` -> `'2026-07-16'`) and drops mismatched rows to prevent payload dates from being silently overwritten.
-   *Source References*: [data_cleaner.py](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/src/data_cleaner.py) lines 44-53.
-   *Verification*: Checked inside `test_data_cleaner.py` (`test_date_mismatch_dropped`).
-   *Status*: **PASSED** (Resolves Blocker B3).

### 1.4 B-02 / C07: Leaderboard Reconciliation warnings (B2 Compliance)
-   *Evidence*: Audits calculated returns against leaderboards. Any single stock discrepancy > 0.5% triggers `WARNING_HIGH_DEVIATION` status.
-   *Source References*: [data_cleaner.py](file:///C:/Workspace_CN/taiwan_moneyflow_rotation/src/data_cleaner.py) lines 145-148.
-   *Verification*: Checked inside `test_data_cleaner.py` (`test_reconciliation_any_deviation_warns`).
-   *Status*: **PASSED** (Resolves Blocker B2).

---

## 2. Milestone 1 Acceptance Verdict
The project has successfully cleared Milestone 1. The current baseline state is strictly set to **Milestone 1 Completed & Verified**. All subsequent code integrations (M2-M6) will be executed sequentially upon user approval.
