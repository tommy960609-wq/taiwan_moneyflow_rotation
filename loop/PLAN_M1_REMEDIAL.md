# Plan: Milestone 1 Remedial & Verification Gate

## 1. Goal & Objectives
Clear all M1 acceptance blockers raised in `taiwan_moneyflow_m1_acceptance_verdict_20260717.md` and secure M1 gate clearance.

## 2. Scope & Target Files
-   **Modify**:
    -   `scripts/run_daily.py`: Integrate both TWSE & TPEx OHLCV, parse correct date payload arguments, and merge markets.
    -   `loop/PROJECT_STATE.md` & `loop/ACCEPTANCE_MATRIX.md` & `loop/TASK_QUEUE.md`: Keep in sync with M1 test counts and gate verdicts.
-   **Add**:
    -   `tests/integration/test_run_daily.py`: Wire an entrypoint test to prove TPEx prices are parsed and merged.
    -   `scripts/smoke_test_pipeline.py`: Run an isolated pipeline smoke test to record row counts against full-market scale.
    -   `loop/evidence/test_logs/pytest_run_log.txt`: Regenerate test receipt correctly labeled Milestone 1 with checksums.
-   **Document**:
    -   `docs/Milestone_1_Acceptance_Report.md`: Detail execution evidence for file discovery, industry mapping, and quality reports.

## 3. Out of Scope (Exclusions)
-   Do not implement M2 feature calculations (rank history state).
-   Do not run live network calls in standard test suites.
-   Do not overwrite existing mock Excel reports.

## 4. Acceptance Criteria
-   `py_compile` checks successfully exit 0.
-   Pytest suite runs successfully and logs all tests passed (with M1 label).
-   E2E daily runner integrates TPEx prices and merges without TypeError.
