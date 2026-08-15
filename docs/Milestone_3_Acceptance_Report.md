# Milestone 3 Acceptance Report — Signal Detection & Excel Reporting

**Date**: 2026-07-18
**Role**: Maker (implementation), pending independent verifier gate (same pattern as M1/M2 gates in `loop/PROJECT_STATE.md`).
**Environment**: `C:\Workspace_CN\taiwan_moneyflow_rotation\.venv`, Python 3.14.3, `pytest -p no:cacheprovider`.

---

## 1. Test Results (Reproducible)

```
C:\Workspace_CN\taiwan_moneyflow_rotation\.venv\Scripts\python.exe -m pytest tests -p no:cacheprovider -v
```

Full output saved at `loop/evidence/test_logs/pytest_m3_run_log.txt`.

**Result: 87 passed, 0 failed, 0 skipped.**
- 59 pre-existing M0/M1/M2 tests (unmodified in behavior; 1 test's sheet-name assertion
  was updated to match the new B-4 4-sheet schema — see §5 "Modified tests" — all still green).
- 28 new M3 tests: 14 in `tests/unit/test_signal_detector.py`, 13 in
  `tests/unit/test_report_generator.py`, 1 in `tests/integration/test_m3_real_snapshot_e2e.py`.

Last line of the log:
```
============================= 87 passed in 25.29s =============================
```

---

## 2. Delivery Scope vs. Status

| # | Scope Item | Status | Evidence |
|---|---|---|---|
| 1 | New Gainer 10-condition signal detection (SPEC Ch.14), A/B/C grading, per-condition pass/fail | **Done** | `src/signal_detector.py::_evaluate_new_gainer`; `tests/unit/test_signal_detector.py` |
| 2 | Continued Momentum signal detection (SPEC Ch.15) | **Done** | `src/signal_detector.py::_evaluate_continued_momentum`; same test file |
| 3 | UAT-04 anti-single-stock-spike hard gate | **Done** | `MIN_UP_STOCKS_FOR_SECTOR_SIGNAL` gate; `TestUAT04SingleStockSpike` tests |
| 4 | All thresholds in `config/default.yaml`, `# PLACEHOLDER - UNCALIBRATED` marked | **Done** | `config/default.yaml` `new_gainer.*` / `continued_momentum.*`; mirrored in `src/config_manager.py::get_defaults` and `src/signal_detector.py` module-level defaults |
| 5 | Excel: exactly 4 sheets per SPEC_ADDENDUM B-4 | **Done** | `src/report_generator.py` rewritten; `tests/unit/test_report_generator.py::TestFourSheetsOnly` |
| 6 | Dashboard: DQ score, mapping coverage, low-coverage warning, top-10 sector table | **Done** | `_build_dashboard_sheet`; `TestDashboardSheet` |
| 7 | New Gainer / Continued Momentum sheets: grade, reason, failed conditions, invalidation, top-5 stocks, confidence | **Done** | `_build_new_gainer_sheet` / `_build_continued_momentum_sheet`; `TestNewGainerSheet` / `TestContinuedMomentumSheet` |
| 8 | Stock priority sheet: score, role, reasons, risk, confidence (works even with near-zero mapping coverage) | **Done** | `_build_stock_priority_sheet`; `TestStockPrioritySheet` |
| 9 | Real 2026-07-16 snapshot end-to-end, real Excel in `outputs/daily/` | **Done** | `tests/integration/test_m3_real_snapshot_e2e.py`; `outputs/daily/MoneyFlow_Rotation_2026-07-16.xlsx` (13,671 bytes) |
| 10 | Execution log (`outputs/logs/run_<date>.log`) + audit JSON | **Done** | `scripts/run_daily.py::_setup_run_logger` / `_write_audit_summary`; `outputs/logs/run_2026-07-16.log`, `outputs/logs/audit_2026-07-16.json` |
| 11 | `docs/signal_definitions.md` expanded with grade/condition/invalidation detail | **Done** | new §3.5 in that file |
| 12 | Backtester limit-up lockout (P0-06) | **Not in scope this milestone** | Correctly kept `Pending` in `loop/ACCEPTANCE_MATRIX.md` per task instructions (backtest milestone, not M3) |

---

## 3. What Was Actually Verified (and How)

### 3.1 Signal grading correctness
`tests/unit/test_signal_detector.py` constructs synthetic sector rows covering:
- All 10 New Gainer conditions passing simultaneously -> asserts grade `A級新起漲`,
  zero failed conditions, `FULL` confidence, non-empty invalidation text.
- `up_stock_count=1` (single-stock spike) with an otherwise "perfect" score profile ->
  asserts grade is capped at `C級個股事件` (never A/B), and the reason string contains
  `"UAT-04"`. Boundary-tested at `up_stock_count=2` (must NOT trigger the cap).
- Missing `inst_flow_ratio`, missing `dq_score`, and low `mapping_coverage_pct` ->
  asserts the corresponding rule lands in `conditions_unevaluable`/`conditions_failed`
  (never silently counted as passed) and `signal_data_confidence` degrades from FULL.
- No previous-day data (`df_sectors_prev=None`) -> asserts no exception and
  delta-dependent rules degrade gracefully.
- Continued-momentum-specific: overheat risk above threshold and institutional
  reversal to net-selling each independently block the `續漲訊號` grade.

### 3.2 Excel structure and content correctness
`tests/unit/test_report_generator.py` generates a report from synthetic sector/stock
data (deliberately including one `primary`-mapped sector, one `續漲訊號` sector, one
`無訊號`/theme sector, one mapped stock, one `待分類` stock) and reopens the file with
`openpyxl.load_workbook` (not a spy on the generator's Python objects) to assert:
- `wb.sheetnames == ["Dashboard", "新起漲族群", "續漲族群", "個股優先排序"]` exactly (4, no more).
- Dashboard contains the DQ score, mapping coverage %, and — when coverage is
  deliberately set below 80% — the literal "絕大多數股票尚未分類" warning string.
- New Gainer / Continued Momentum sheets contain the required 8 columns each and
  correctly *exclude* sectors that don't belong to that track (cross-checked by
  asserting `SectorB`/`SectorC` text does NOT appear in the New Gainer sheet, etc.).
- Stock priority sheet contains both a mapped and an unmapped stock, and the
  unmapped stock's row text contains "尚未完成產業分類" (risk-reason downgrade, not a
  silently-inherited FULL confidence).
- At least one Dashboard cell uses Excel's `0.0%` number format (mapping coverage).

### 3.3 Real 2026-07-16 snapshot end-to-end
`tests/integration/test_m3_real_snapshot_e2e.py` stages the REAL cached TWSE+TPEx
OHLCV/institutional/margin snapshots from `loop/evidence/raw_samples/` (1,371 TWSE +
10,012 TPEx raw OHLCV rows -> 1,104 + 871 = 1,975 cleaned equities after
`is_valid_equity` filtering, matching the M1/M2 gate evidence exactly) into an isolated
temp `data_dir`, points `output_dir` at the project's real `outputs/` directory, and
runs `run_pipeline("2026-07-16")` with **no network calls and no synthetic data**.
Asserts:
- The real Excel lands at `outputs/daily/MoneyFlow_Rotation_2026-07-16.xlsx` (not a
  temp file) with all 4 required sheets.
- Dashboard shows the honest 0.41% mapping coverage (8/1,975) and the mandatory
  low-coverage warning text.
- Stock priority sheet is non-empty (51 stocks) even though sector mapping coverage
  is near zero — confirming individual-stock ranking works independently of industry
  classification, per the task brief's explicit requirement.
- `outputs/logs/run_2026-07-16.log` and `outputs/logs/audit_2026-07-16.json` both
  exist; the audit JSON's `status` is `"SUCCESS"`, row counts for prices/institutional/
  margin/mapping-coverage/scored-sectors/scored-stocks are all present and > 0 where
  expected, and `output_files` lists all 4 processed CSVs plus the Excel path.

This is the actual file produced (not a copy, not regenerated for the report):
```
outputs/daily/MoneyFlow_Rotation_2026-07-16.xlsx   13,671 bytes
outputs/logs/run_2026-07-16.log                     1,157 bytes
outputs/logs/audit_2026-07-16.json                  1,112 bytes
```

---

## 4. Known Environment-Coupling Finding (Important — Read Before Re-Running)

While staging the real-snapshot end-to-end run, the pipeline **legitimately BLOCKED**
(Data Quality Score 61, below the 70 threshold) the first time it was run without any
patching. Root cause, fully traced:

1. `scripts/run_daily.py::load_excel_leaderboard` (pre-existing **M1** code, out of this
   milestone's modify-scope per the "don't change M1/M2 accepted module behavior" rule)
   globs `C:/Workspace_CN/Quant-Agent/**/Report_<date>.xlsx` — an external sibling
   project directory, not this project's own `data/`.
2. On this development machine, a real file
   `C:\Workspace_CN\Quant-Agent\台股漲幅排行\Report_20260716.xlsx` happens to exist.
   `reconcile_with_leaderboard` (also pre-existing M1 code) compared our computed
   `daily_return = (close - open) / open` (an intraday open-to-close proxy) against
   that file's genuine day-over-day 漲跌幅 (prev-close-to-close %). These are two
   **different return bases**, so the comparison surfaces 185 "deviations" that are
   largely a definitional mismatch, not real data corruption — e.g. stock 4534: our
   `(41.7-41.3)/41.3 = 0.97%` vs. the leaderboard's genuine `+10.00%` day-over-day move.
3. The resulting `-15` DQ penalty pushed the score from a base 76 (DEGRADED, would
   have produced a report) down to 61 (BLOCKED, produces none).

**This is real, pre-existing M1 behavior, not something introduced or fixed silently
in M3.** Because `reconcile_with_leaderboard`/`calculate_ranks`'s return-basis
semantics are locked M1/M2 scoring logic I am not authorized to change this milestone,
and because that external leaderboard file is an incidental artifact of this one
development machine (a clean checkout elsewhere would not have it, and it is not a
documented required M3 input), `test_m3_real_snapshot_e2e.py` patches
`scripts.run_daily.load_excel_leaderboard` to return an empty DataFrame for that one
test run — exactly mirroring the hermetic-isolation pattern
`tests/integration/test_run_daily.py` already uses (patching `os.path.exists` to hide
files) so the reconciliation optional-input path doesn't fire. With that path empty,
the real snapshot run reaches DQ=76 (DEGRADED, matches the base calculation in §3.3)
and produces the real report.

**Recommendation for a future milestone** (not actioned here, flagged for owner
decision): either (a) change `daily_return`'s definition to prev-close-to-close so it
is comparable to the leaderboard's 漲跌幅 semantics, or (b) make the leaderboard glob
path project-relative/configurable instead of hardcoded to a sibling project, or (c)
both. This is a real, actionable finding surfaced by running against real data end to
end — exactly the kind of gap this milestone was supposed to surface, not paper over.

---

## 5. Modified Pre-Existing Files (M1/M2 Behavior Preserved, Only Interfaces Extended)

- `src/signal_detector.py`: fully rewritten (was a 4-branch score/breadth stub). This
  file's public entrypoint (`SignalDetector().detect_signals(...)`) is called from
  `scripts/run_daily.py`, which is M2/M3 pipeline wiring, not a locked M1/M2 module —
  the task brief explicitly assigns this file to M3 scope ("src/signal_detector.py 完成化").
- `src/report_generator.py`: fully rewritten per SPEC_ADDENDUM B-4 (task brief's
  explicit M3 scope). Old M1-era `Font`/`Alignment` styling helpers reused; only the
  sheet layout and count changed (16-sheet-superset design was never implemented, so
  there is no "removal" of previously-shipped sheets — the old file already only had 4
  sheets with different English names).
- `src/config_manager.py`: `get_defaults()` dict extended with the 3 new `new_gainer`
  keys and 2 new `continued_momentum` keys (additive; existing keys/values unchanged).
- `config/default.yaml`: same additive extension, comments clarify which SPEC Ch.14/15
  rule each key maps to.
- `scripts/run_daily.py`: additive wiring only — added `_setup_run_logger`,
  `_write_audit_summary`, `_attach_top5_stocks` helpers; added previous-day sector/
  stock-features loading for signal-detector deltas; extended the `SignalDetector` and
  `ReportGenerator` calls with new keyword arguments (all optional/defaulted upstream,
  so no existing call signature broke). Did not change any M1/M2 cleaning, scoring, or
  feature-computation logic.
- `tests/acceptance/test_future_leakage.py` (P0-03 critical test): **only** the sheet
  name/header-row lookup was updated (`"Stock Observation Priority"` -> `"個股優先排序"`,
  `header=2` to skip the new title banner row) to match the new B-4 4-sheet Excel
  schema. The actual leakage assertion (`"9999" not in df_stocks["股票代號"]`) is
  byte-for-byte unchanged — the test still fails if a future-dated stock leaks in.

---

## 6. Known Limitations (Disclosed, Not Hidden)

- **Continued Momentum rules 5/6** (龍頭整理時次龍頭接棒 / 高檔爆量不漲偵測) are always
  marked `conditions_unevaluable` — no per-stock leadership-continuity history or
  intraday tick-level volume/price structure is wired into the pipeline yet. This
  degrades `signal_data_confidence` for every continued-momentum call but does not
  block the grade (per SPEC Ch.15, these were always the least-operationalizable of
  the 9 listed conditions).
- **Industry mapping coverage remains 8/1,988** (~0.4-0.41% depending on exact
  denominator on a given day) — this is the known M2-era reality, unchanged by M3. The
  Dashboard sheet surfaces this honestly with an unmissable red warning and the New
  Gainer/Continued Momentum sheets are consequently thin (theme-level signals only,
  since only a curated handful of AI-supply-chain stocks are mapped). Individual-stock
  ranking (Stock Priority sheet) does **not** depend on sector mapping and is fully
  populated (51 stocks in the real run).
- **New-gainer vs. continued-momentum track precedence**: a sector is evaluated
  against both tracks every run; if it qualifies for A/B/C it is reported under
  New Gainer even if it would also have qualified for Continued Momentum. This is a
  deliberate design choice (documented in `docs/signal_definitions.md` §3.5.3), not an
  oversight, but it means a sector can never appear on both sheets on the same day.
- **P0-06 (backtest limit-up lockout)**: correctly out of scope this milestone per
  task instructions; `loop/ACCEPTANCE_MATRIX.md` P0-06 row remains `Pending`.
- **Return-basis mismatch** between `daily_return` ((close-open)/open) and the
  leaderboard's 漲跌幅 (prev-close-to-close): see §4. Pre-existing M1 logic, disclosed
  rather than silently patched.

---

## 7. Files Changed/Added This Milestone

**Modified:**
- `src/signal_detector.py` (rewritten)
- `src/report_generator.py` (rewritten)
- `src/config_manager.py` (additive)
- `config/default.yaml` (additive)
- `scripts/run_daily.py` (additive wiring)
- `tests/acceptance/test_future_leakage.py` (sheet-name/header assertion updated only)
- `docs/signal_definitions.md` (new §3.5 appended)
- `pytest.ini` (new — registers the `slow` marker, silences a pytest warning)

**Added:**
- `tests/unit/test_signal_detector.py` (14 tests)
- `tests/unit/test_report_generator.py` (13 tests)
- `tests/integration/test_m3_real_snapshot_e2e.py` (1 test, marked `slow`)
- `docs/Milestone_3_Acceptance_Report.md` (this file)
- `loop/evidence/test_logs/pytest_m3_run_log.txt` (test receipt)

**Real output produced (gitignored `outputs/`, listed for verifier convenience):**
- `outputs/daily/MoneyFlow_Rotation_2026-07-16.xlsx`
- `outputs/logs/run_2026-07-16.log`
- `outputs/logs/audit_2026-07-16.json`

---

## 8. Decision

**PASS** (maker-side; pending independent verifier gate per project convention).

All P0/P1 items assigned to this milestone are implemented with reproducible test
evidence; the full suite (87 tests, 59 pre-existing + 28 new) is green; the real
2026-07-16 snapshot was run end-to-end with no network calls and no fabricated data,
producing a real 4-sheet Excel report plus log and audit artifacts; known limitations
and one environment-coupling finding are disclosed rather than hidden.
