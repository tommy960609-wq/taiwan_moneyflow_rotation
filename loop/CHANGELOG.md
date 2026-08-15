# Changelog

All notable changes to the Taiwan Moneyflow Rotation System will be documented in this file.

---

## [Unreleased] - 2026-07-22 (M10: Signal Detector Selectivity)

### Added
-   **Selective signal grading** (`src/signal_detector.py`): removed the generic
    `if passed -> C` fallback. New-gainer A/B/C now require an explicit trigger,
    core evidence, breadth evidence for B, and fail-closed safety/data vetoes;
    unevaluable rules never count as passed. UAT-04 remains fixed at
    `MIN_UP_STOCKS_FOR_SECTOR_SIGNAL=2`.
-   **Continued-momentum core gate**: rules 1 and 4 must pass; missing optional
    rules 5/6 remain visible as degraded confidence rather than being treated as
    passes.
-   **M10 acceptance report**: `docs/Milestone_10_Signal_Selectivity_Report.md`
    records the full 62-day signal distributions, event dispersion, backtest
    headlines, limitations, and exact evidence paths.

### Changed
-   Mirrored `min_core_passed_for_b=3` and `min_breadth_core_passed_for_b=1`
    (both `# PLACEHOLDER - UNCALIBRATED`) in `config/default.yaml` and
    `src/config_manager.py`.
-   Updated `docs/signal_definitions.md` and the signal-detector unit fixtures to
    reflect strict unevaluable/veto semantics.

### Verification
-   Targeted signal-detector tests: **25 passed**.
-   Full suite before the audit tool: **463 passed** (`loop/evidence/test_logs/pytest_signal_selectivity_run_log.txt`).
-   Phase 1 paired audit tests: **4 passed**; full suite after the additive audit tests: **467 passed** (`loop/evidence/test_logs/paired_calibration_full_pytest_log.txt`).
-   Clean 62-day rerun: both calibrated and uncalibrated pipelines **62/62**;
    events 495/631, with zero events on the cold-start date and first events on
    2026-04-21. C-grade 10-day medians remain -2.7852%/-2.8833% versus the
    -1.2338% momentum baseline; A/B have no realized samples.
-   Phase 1 pairing: all 2,857 sector-days align; event overlap 264, uncalibrated-only
    231, calibrated-only 367; 228 realized shared events have zero paired-return delta.
-   Phase 2 frozen-parameter OOS gate executed: **INSUFFICIENT_OOS_DATA**. Only one
    post-training date (2026-07-20) exists and zero dates have ten subsequent scored
    dates; no OOS performance number was emitted. Receipt at
    `Quant-Agent/_workbench/out/moneyflow_62d_backtest_20260722/frozen_oos_validation_receipt.json`.
-   Phase 2 guard tests: **4 passed**; complete suite after the OOS guard: **471 passed**
    (`loop/evidence/test_logs/phase2_full_pytest_log.txt`).

## [Unreleased] - 2026-07-21 (M9: Threshold Quantile Calibration + Backtest Rerun)

### Added
-   **`src/threshold_calibration.py`**: rolling-quantile calibration (SPEC_ADDENDUM
    B-1.3). `rolling_quantile_threshold()`/`rolling_quantile_threshold_pooled()`
    compute a per-sector (or market-pooled) quantile of a metric using only strictly-
    prior trade_dates, falling back to an absolute value below `MIN_CALIBRATION_
    PERIODS=10` prior observations. `build_calibrated_new_gainer_config()`/
    `build_calibrated_continued_momentum_config()` apply this to
    `new_gainer.min_score`/`prev_score_max` and `continued_momentum.min_score` only
    (3 of 17 total thresholds — see report §3.1 for why). No-lookahead guaranteed by
    construction and by 4 dedicated tests in `tests/leakage/
    test_threshold_calibration_no_future_function.py`.
-   **`scripts/prepare_official_margin_history_snapshot.py`**: bridges the previously-
    orphaned `data/raw/margin/twse_official_<date>.json`/`tpex_official_<date>.json`
    (backfilled last session, never actually consumed by any pipeline code) into the
    legacy filenames `run_pipeline` reads. Pure copy (payloads are already fully
    transformed at fetch time) — real coverage jump confirmed: 2 -> 1,831 stocks/day.
-   `SignalDetector.__init__` gained `use_calibrated_thresholds: bool = False` /
    `df_sector_history: Optional[pd.DataFrame] = None` (both default preserve exact
    pre-M9 behavior); `_evaluate_new_gainer`/`_evaluate_continued_momentum` now accept
    an explicit `cfg` parameter instead of always reading `self.ng_cfg`/`self.cm_cfg`.
-   `scripts/run_daily.py::run_pipeline` gained `use_calibrated_thresholds: bool = False`;
    `scripts/run_history_pipeline.py` gained a matching `--calibrated` CLI flag.

### Changed
-   `src/signal_detector.py`'s `DEFAULT_NEW_GAINER_CONFIG["min_score"/"prev_score_max"]`
    and `DEFAULT_CONTINUED_MOMENTUM_CONFIG["min_score"]` comments updated from
    `# PLACEHOLDER - UNCALIBRATED` to `# CALIBRATED (n=28 trading days,
    2026-04-20~2026-07-17) - PRELIMINARY, small sample` — these 3 literal numbers
    remain the fallback used only when a sector lacks enough rolling history.
-   `config/default.yaml`/`docs/signal_definitions.md` comments updated to match.

### Found (disclosed, not silently fixed — out of this milestone's authorized scope)
-   **BLOCKED_LOW_DQ regression**: rerunning the 62-day historical batch with the
    newly-wired margin data produced 28/62 SUCCESS (down from 60/62 at M5c-prep).
    Root-caused to `src/data_cleaner.py::reconcile_with_leaderboard`'s pre-existing
    (M3-disclosed) open-to-close vs prev-close basis mismatch, which now fires on most
    days because FinMind OHLCV coverage reached 100% (was 29% at M5c time) — more
    leaderboard tickers now find a match to compare against. Confirmed NOT caused by
    this session's margin work (`calculate_quality_score` never reads `df_margin`).
-   **Calibration's backtest effect is unmeasurable on this dataset**: rerunning
    `scripts/run_backtest.py` on an isolated, clean 28-date subset produced a
    byte-identical headline before vs after calibration (confirmed via `diff -q` on
    the raw event CSVs). Root-caused: all 53 independent events first-fire on either
    the cold-start day (zero prior history by construction) or an all-UNTRADABLE day,
    so the already-accepted "first occurrence only" event rule structurally cannot
    show calibration's effect here — even though calibration demonstrably changed
    84/1,294 sector-day grades (144 -> 228 B-grade rows) starting once enough rolling
    history existed.

### Tests
-   `tests/unit/test_threshold_calibration.py` (17 tests), `tests/leakage/
    test_threshold_calibration_no_future_function.py` (4 tests), `tests/unit/
    test_prepare_official_margin_history_snapshot.py` (7 tests), +4 new tests in
    `tests/unit/test_signal_detector.py::TestCalibratedThresholds`. Full suite: 451
    passed (419 baseline + 32 new); `loop/evidence/test_logs/pytest_calibration_run_log.txt`.

See `docs/Milestone_9_Calibration_Backtest_Report.md` for full detail.

---

## [Unreleased] - 2026-07-21 (Margin History Backfill：官方免費端點取代 FinMind)

### Added
-   **`src/twse_tpex_margin_history.py`**: new module fetching TWSE (`MI_MARGN`) and
    TPEx (`margin_bal_result.php`) legacy history endpoints, which (unlike the OpenAPI
    endpoints already wired into `src/data_loader.py`'s `fetch_twse_margin_all()` /
    `fetch_tpex_margin_all()`, both left untouched) genuinely honor a historical date
    parameter. Built to replace FinMind for margin/short-sale history after the
    FinMind free-tier quota was exhausted — these two endpoints are free and
    unlimited. `fetch_twse_margin_history(date)` / `fetch_tpex_margin_history(date)`
    are fail-closed (HTTP/timeout/JSON-parse/date-mismatch all return `None`, logged,
    never raise); `iso_to_roc_slash()` converts ISO dates to the ROC-year-slash format
    (`"115/07/14"`) TPEx's endpoint requires. `transform_twse_margin_rows()` /
    `transform_tpex_margin_rows()` reshape each endpoint's raw rows into the exact
    format `src/data_cleaner.py::clean_margin_data` already parses (TWSE's column
    order matched the cleaner's existing index assumptions exactly; TPEx rows are
    rebuilt into the openapi-style dict keys the cleaner's TPEx branch expects) — zero
    changes needed to `data_cleaner.py`. Found and fixed a real bug during the live
    backfill run: TWSE's non-trading-day response has neither a `date` nor a `tables`
    field at all, which the date-consistency guard was initially misreading as
    `DATE_MISMATCH` (a failure) instead of a benign non-trading day; fixed and
    regression-tested (`test_fetch_twse_margin_history_weekend_no_date_or_tables_returns_empty_list`).
-   **`scripts/backfill_margin_history.py`**: resumable CLI backfill over a date range
    (default 2026-04-20..2026-07-20), writing `data/raw/margin/twse_official_<date>.json`
    / `tpex_official_<date>.json` (new filename prefixes — never overwrites any
    existing FinMind or legacy `margin_<date>.json` file). 1.5s polite delay between
    requests. Real full-range execution: 63/63 trading days saved on both TWSE and
    TPEx, 29 non-trading days correctly skipped, 0 failures (see
    `docs/Margin_History_Backfill_Report.md`).
-   **`scripts/backfill_status.py`**: additive `margin_date_sources` section —
    per-DATE (not per-stock) file coverage across all four margin source prefixes
    (`finmind_`/`margin_`/`twse_official_`/`tpex_official_`), distinct from the
    existing per-stock `categories.margin` section (different denominator, reported
    side-by-side, never conflated). Existing 8 tests unchanged/still passing; 4 new
    tests added.
-   **`docs/Margin_History_Backfill_Report.md`**: endpoint format differences
    (TWSE/TPEx response shapes, ROC-slash date quirk, non-trading-day response
    shapes), the DATE_MISMATCH-vs-non-trading-day bug found and fixed, full backfill
    statistics, before/after coverage comparison, known limitations.

Tests: 419 passed (376 baseline + 39 in `test_twse_tpex_margin_history.py` /
`test_backfill_margin_history.py` + 4 in `test_backfill_status.py`). See
`loop/evidence/test_logs/pytest_margin_history_run_log.txt`.

---

## [Unreleased] - 2026-07-19 (Milestone 8：修復批次小項包 / Small-fix Batch)

### Fixed
-   **`scripts/run_daily.py`**: empty-market fallback no longer raises
    `KeyError('market_type')`. When both TWSE and TPEx price frames are empty (both
    the M4 bridge files absent AND the legacy live-fallback also returns empty), the
    zero-column `pd.concat` result is now guarded with a
    `"market_type" not in df_prices.columns` check before indexing, so execution
    falls through to the pre-existing `BLOCKED_MISSING_MARKET` fail-closed branch
    instead of crashing (`docs/open_issues_audit_2026-07-19.md` #1, P0).
    `tests/regression/test_run_daily_empty_market_crash.py` updated to assert the
    fixed behavior (explicitly authorized this milestone — was previously a
    documented-not-fixed regression test).

### Changed
-   **`load_excel_leaderboard`** (`scripts/run_daily.py`): the hardcoded
    `C:/Workspace_CN/Quant-Agent` leaderboard glob root is now
    `reconciliation.leaderboard_dir` in `config/default.yaml` (and
    `ConfigManager.get_defaults()`). Default value is unchanged from the pre-M8
    hardcoded path, so existing behavior is preserved; a missing directory now logs
    and skips reconciliation instead of relying on an empty glob result
    (`docs/open_issues_audit_2026-07-19.md` #5/#12, P1).

### Added
-   **`scripts/backfill_status.py`**: direct-disk-scan FinMind backfill progress
    tool. Counts `finmind_<stock_id>.json` files per category (ohlcv/institutional/
    margin) against the live row count of `stock_industry_mapping.xlsx`, reporting
    file count, coverage %, and oldest/newest file mtime. `--json` for strict JSON,
    plain invocation for a human-readable table. Built because
    `loop/evidence/fetch_receipts/finmind_backfill_summary.json` is a stale
    single-execution snapshot, not cumulative progress
    (`docs/open_issues_audit_2026-07-19.md` #22).
-   **`coverage` package**: installed into `.venv`, added to `requirements.txt` as a
    dev-only dependency. First-ever measurement taken:
    `loop/evidence/test_logs/coverage_first_measurement.txt` — core `src/` 86%,
    whole project (`src/`+`scripts/`) 80%, both meet spec §28.1's 85%/75% gates on
    this first measurement. Measurement only; no CI gate wired up, no test changed
    to influence the number.

### Tests
-   374 passed (361 baseline + 5 new in `tests/unit/test_load_excel_leaderboard_config.py`
    + 8 new in `tests/unit/test_backfill_status.py`, net of 1 flipped assertion in
    the regression test above). `loop/evidence/test_logs/pytest_m8_run_log.txt`.

---

## [Unreleased] - 2026-07-18 (Milestone 7：避坑補完包 / Pitfall Pack)

### Added
-   **`src/price_adjuster.py`**: ex-dividend backward price-adjustment factors, computed
    from FinMind `TaiwanStockDividendResult` (the only usable dividend/adjustment dataset
    on this token — 6 candidate direct "adjusted price" dataset names all confirmed
    UNAVAILABLE via live dry-run, receipt in `loop/evidence/fetch_receipts/`).
    `scripts/fetch_price_adjustments.py` fetched 516/890 FinMind-backfilled stocks (58%,
    rate-limited mid-run, disclosed) into `data/reference/price_adjustment_factors.csv`.
-   **`config/default.yaml` / `src/config_manager.py`**: new `backtest.use_adjusted_prices`
    key (default `true`). `scripts/run_backtest.py` now applies adjustment factors before
    the event study, tagging any stock without a factor `UNADJUSTED` (42.0% of the 890-
    stock universe this run) — never silently blended.
-   **`src/disposition_fetcher.py`**: 處置股/注意股 fetcher across 5 real TWSE/TPEx
    endpoints (`/announcement/punish`, `/announcement/notice`,
    `tpex_trading_warning_information/_note`, `tpex_esb_warning_information`), fail-closed
    per-endpoint. Live-fetched today: 41 unique stocks (12 disposition, 29 attention).
    Wired into `scripts/run_daily.py` (new `disposition_flag` column on the daily
    report's 個股優先排序 sheet) and `scripts/run_backtest.py` (real
    `disposition_stock_ids` set passed into `Backtester.run_event_study`'s pre-existing,
    unmodified parameter — previously always empty).
-   **`src/leaderboard_loader.py` / `src/limit_up_history.py` /
    `src/leaderboard_reconciliation.py`**: parses the 36-day user-collected
    台股漲幅排行 leaderboard (copied read-only source into `data/raw/reports/`). Builds
    a 漲停家數/連續漲停 history (market-wide + sector, OBSERVE-ONLY — not wired into
    `sector_scoring.py`'s live overheat-risk formula, an already-accepted M2 weight
    contract left untouched per governance rule #9) and a basis-aligned 36-day
    cross-reconciliation against FinMind (0.97% of comparable rows exceed the 0.5pp
    deviation threshold; found and disclosed 3 genuine FinMind zero-price data-corruption
    rows in the process). Orchestrated by `scripts/run_leaderboard_analysis.py`.

### Changed (additive only — no existing behavior altered)
-   `src/report_generator.py`: 個股優先排序 sheet gained a 處置/注意 column.
-   `scripts/run_daily.py`: new `_load_disposition_ids_for_date` helper (reads
    already-fetched disk files, no live network call from inside the pipeline).

### Verified unchanged
-   `src/backtester.py`, `src/benchmarks.py`, `src/sector_scoring.py`: zero lines
    modified this milestone (governance rule #9 / task instruction).

### Backtest rerun (adjusted prices)
-   Headline medians **unchanged**: B級早期點火 -11.28% (n=27), C級個股事件 -10.41%
    (n=19), both still underperform the -0.39% momentum baseline, both still n<30. Only
    2 of 53 real events had their forward-return window cross an ex-dividend date in
    this specific sample — the adjustment mechanism is verified genuinely applied
    (direct event-level diff confirms it), it simply had limited effect on this
    particular already-small dataset. Old outputs backed up to
    `outputs/backtests/_bak_pre_m7/*.bak` before rerun. Conclusion level unchanged:
    初步研究讀數 (PRELIMINARY RESEARCH READING).

### Tests
-   56 new tests (7 new files + 3 additive in `test_report_generator.py`), full suite
    361/361 passed (305 pre-existing + 56 new), zero regressions. Log:
    `loop/evidence/test_logs/pytest_m7_run_log.txt`.

See `docs/Milestone_7_Pitfall_Pack_Report.md` for full detail and all known limitations.

---

## [1.0.0-software-ready-candidate] - 2026-07-18 (Milestone 6：正式化)

### Added
-   **`scripts/daily_orchestrator.py`**: one-click unattended daily orchestrator chaining
    fetch -> legacy-filename bridge -> `run_pipeline` -> signals-JSONL append, with a
    documented and tested fail-closed contract for 3 named failure scenarios (network
    failure at fetch, API returned empty/schema-mismatched, DQ black-out). Exit codes
    0/1/2/3 distinguish success / fetch-failed / pipeline-blocked / unexpected-exception.
    Real live-network run executed twice: 2026-07-18 (today) surfaced a genuine
    DATE_MISMATCH data-availability gap that cascaded into a pre-existing bug (see
    Fixed/Found below); 2026-07-17 (rerun) completed full SUCCESS end-to-end, with a
    second rerun of the same date proving byte-identical processed-CSV reproducibility.
-   **`scripts/daily_run.ps1` / `scripts/daily_run.bat`**: one-click wrapper scripts,
    Windows Task Scheduler-ready (setup steps documented in
    `docs/operations_manual.md`; scheduler NOT actually created, per task instruction).
-   **`docs/operations_manual.md`**: user-facing (investment-decision-maker, not
    engineer) operations manual — daily run steps, 4-sheet report reading guide (incl.
    the mandatory "訊號等級=未校準研究參考,不是買賣指令" disclosure), error reference
    table, backfill-progress check commands, FinMind quota characteristics, Windows
    Task Scheduler setup steps.
-   **`README.md`** full rewrite: accurate new-environment reproduction steps (was
    stale M0-era content pointing at a wrong `Quant-Agent\.venv` path); documents and
    actually executes the spec §28.1 reproducibility self-check.
-   **`docs/acceptance_report.md`**: final acceptance report per spec Ch.36 format.
    Verdict: **Software Ready (candidate)**. Explicitly judged **NOT Research Ready**
    (spec §28.2's own 10-item checklist: n<30, single bull-market regime, 29-41%
    historical coverage, uncalibrated thresholds, signal underperforms momentum
    baseline) and **NOT Trading Decision Support Ready** (§28.3).
-   **`VERSION`** (`v1.0.0-software-ready-candidate`) + root **`CHANGELOG.md`**.
-   `tests/integration/test_daily_orchestrator.py` (12 tests, fully offline via
    dependency injection) + `tests/regression/test_run_daily_empty_market_crash.py`
    (2 tests, documents a found-not-fixed bug, see below).

### Found (NOT fixed — already-accepted M1-M5c code, out of this milestone's authorized scope)
-   **`run_daily.py::run_pipeline` legacy-fallback `KeyError`**: when today's M4-format
    legacy bridge files don't exist AND the internal legacy live-fallback
    (`DataLoader.fetch_twse_ohlcv_all`/`fetch_tpex_ohlcv_all`) also returns empty, the
    resulting `pd.concat([pd.DataFrame(), pd.DataFrame()])` has zero columns, so
    `df_prices["market_type"]` raises `KeyError` instead of reaching the intended
    `BLOCKED_MISSING_MARKET` fail-closed check two lines later. Reproduced live on
    2026-07-18 (TWSE/TPEx OHLCV endpoints both still serving 2026-07-17's data at fetch
    time — a genuine, expected data-availability gap, not a bug) and hermetically via
    `tests/regression/test_run_daily_empty_market_crash.py`. Practical impact assessed
    as low: the new orchestrator's own try/except already prevents any bad report or
    data overwrite; only the log/exit-code granularity differs from the ideal clean
    `BLOCKED_MISSING_MARKET` status.

### Corrected (prior state record was stale)
-   **FinMind drip backfill PID 2924**: `loop/PROJECT_STATE.md` recorded this process as
    "found dead" at M5c's verification time. Re-checked at M6 verification: **still
    alive** (`Get-Process -Id 2924`, `StartTime` matches the original 2026-07-18 15:33:27
    launch), OHLCV coverage progressed 571/1963 -> 802/1963 in the interval. NOT
    restarted — killing a healthy, actively-progressing background process would be
    needlessly destructive and contrary to the fail-closed spirit of this project.

### Test suite
-   305/305 passed (291 pre-existing + 12 new orchestrator + 2 new regression), 0
    failed, 0 skipped. `loop/evidence/test_logs/pytest_m6_run_log.txt`.

---

## [0.7.1-M5c-prep] - 2026-07-18

### Fixed
-   **M4 institutional-column merge-suffix bug** (`scripts/run_daily.py`, ~line 411-441): disclosed but deliberately not fixed in M5b per governance rule #9 (don't touch already-accepted module behavior without a proposal). This session was explicitly authorized to fix exactly this one bug. Root cause: `df_stock_features_today` inherits institutional columns from previously-persisted `stock_features_<date>.csv` files via the multi-day rolling-history concat; merging `df_inst`'s fresh institutional columns back onto it a second time with no `suffixes=` either raised a MergeError or silently split the column into `_x`/`_y` duplicates. Fixed by dropping any stale institutional columns from `df_stock_features_today` before the merge. New regression test `tests/integration/test_run_daily_two_day_merge.py` runs 2 consecutive real days hermetically and directly proves the bug pre-fix (missing clean `foreign_net_buy` column) and the fix post-fix.
-   **`tests/integration/test_m2_e2e_pipeline.py` hermeticity**: independently discovered (not caused by the mock-file move below) that this test's mock stock IDs collide with a real external leaderboard file `scripts/run_daily.py::load_excel_leaderboard`'s pre-existing hardcoded glob path picks up on this dev machine (documented since M3), causing an unrelated `BLOCKED_LOW_DQ`. Fixed by mocking `load_excel_leaderboard` to return empty in this one test — test-only change.

### Changed
-   **Mock-file unshadowing**: moved `data/raw/ohlcv/prices_2026-07-14/15/16.json` (synthetic demo data flagged in M5b as shadowing both the official and FinMind legacy bridges) to `data/test_fixtures/legacy_mock/`. Updated the one dependent test's fixture path. Production code (`run_pipeline`'s combined-file-checked-first logic) unchanged.

### Added
-   **FinMind backfill resumed**: institutional 0->26/1963, margin 0->2/1963 (OHLCV unchanged at 571/1963, deprioritized this round per instruction). New finding: FinMind's rate limit behaves as a short (~30-90 second) per-minute-scale burst throttle, not the clean hourly window M5b assumed — confirmed by 6+ real resume attempts each netting only single-digit successes before re-hitting HTTP 402.
-   **Full 62-day historical batch pipeline rerun**: 60/62 SUCCESS (was 2 in M5b), 0 EXCEPTION (was 26, closed by the merge fix above), 2 BLOCKED_LOW_DQ (was 31, now only 2026-07-14/15, genuinely thin data for those 2 dates, fail-closed correctly), 0 BLOCKED_MISSING_MARKET (was 3, mock-file unshadowing). 2,765 total signal events. Backups of all pre-rerun processed CSVs/signal JSONLs/audit JSONs taken before overwrite.
-   Test suite: 249/249 passed (248 pre-existing + 1 new regression test). `loop/evidence/test_logs/pytest_m5c_prep_run_log.txt`.

### Known Findings (see `docs/Milestone_5c_prep_Report.md`)
-   FinMind institutional/margin backfill is still far from complete (26/1963, 2/1963). A follow-up session should use short (60-120s) retry intervals given the newly-observed burst-throttle behavior, but full completion will still require multiple hours of patient resumption.
-   The 2 remaining `BLOCKED_LOW_DQ` days (2026-07-14/15) are a direct, expected consequence of the still-incomplete institutional/margin backfill for those specific dates.
-   `load_excel_leaderboard`'s hardcoded external-project glob path (documented since M3) remains a live environmental-coupling risk, flagged again by this session's test hermeticity fix — not fixed (outside this session's authorized scope of exactly one bug in `run_daily.py`).

---

## [0.7.0-M5b] - 2026-07-18

### Added
-   **FinMind Historical Fetcher** (`src/finmind_fetcher.py`, `scripts/fetch_history_finmind.py`): closes M5a's architectural finding that official TWSE/TPEx endpoints cannot serve historical dates. Dataset names dry-run verified live against `https://api.finmindtrade.com/api/v4/data` (never recited from memory) — usable: `TaiwanStockPrice` (per-stock OHLCV + TAIEX index), `TaiwanStockInstitutionalInvestorsBuySell`, `TaiwanStockMarginPurchaseShortSale`, `TaiwanStockInfo`; confirmed unavailable: no working TPEx/OTC index series (8 candidate `data_id`s all returned HTTP 200 with zero rows). Fail-closed, rate-limit-aware (HTTP 402/429 short-circuits without a wasted retry), resumable (`skip_existing`, requires an exact date-range match).
-   **Real backfill executed**: 571 of 1,963 stocks' full 62-trading-day OHLCV history (29.1%) fetched before FinMind's hourly quota was exhausted (HTTP 402 on request #572; confirmed a genuine hourly-scale limit via an immediate-402 resume probe). Institutional/margin: 0/1,963 (quota ran out during the OHLCV pass, which was deliberately fetched first). TAIEX index: 100%. Resumable for a follow-up session.
-   **Chinese Sector Name Conversion** (`scripts/build_chinese_sector_mapping.py`): converts M5a's raw numeric `primary_sector` codes to real Chinese industry names using FinMind's `TaiwanStockInfo`. 1,955/1,955 eligible (non-reviewed) rows converted (100%); the 8 manually-reviewed rows are protected untouched; the old numeric code is preserved in a new `sector_code` column rather than discarded. A genuine FinMind data-quality wrinkle (many stock_ids carry multiple classification-history rows, ~600 with same-date ties between a specific and a broader-bucket label) was resolved via a max-date-wins/first-occurrence-on-tie rule, verified exact against the reviewed ground-truth rows. Real `outputs/daily/MoneyFlow_Rotation_2026-07-17.xlsx` re-run and confirmed showing Chinese names in the Dashboard; prior version backed up to `.xlsx.bak`.
-   **`data_loader.py` Dual-Source Integration**: additive `load_finmind_ohlcv_for_date`/`load_finmind_institutional_for_date`/`load_finmind_margin_for_date`/`merge_ohlcv_sources`/`merge_institutional_sources`/`merge_margin_sources` methods. Official data always wins on any `stock_id` conflict; FinMind only fills gaps the official source doesn't cover; every merged row carries an explicit `source` column so the two are never blended into an indistinguishable value.
-   **`scripts/prepare_finmind_legacy_snapshot.py`**: bridges FinMind's per-stock historical files into the same legacy per-day filenames M5a's official-source bridge (`prepare_legacy_raw_snapshot.py`) uses — implemented as a strict no-op wherever an official-sourced legacy file already exists for that date (official-source priority enforced at the file level).
-   **`scripts/run_history_pipeline.py --use-finmind`**: new additive flag (default off, preserving exact M5a behavior) that unions FinMind-covered dates with official-covered dates via new `discover_finmind_dates`/`bridge_finmind_dates` functions.
-   **Real historical batch pipeline run**: 62 dates processed end-to-end. 2 SUCCESS, 26 EXCEPTION, 31 BLOCKED_LOW_DQ, 3 BLOCKED_MISSING_MARKET — see Known Findings below for the root cause of each non-success category (all investigated, none silently absorbed).
-   **Reconciliation spot-check**: all 571 FinMind-fetched stocks' 2026-07-17 closing prices compared against the real official TWSE/TPEx snapshot — 569/571 exact matches (100% of comparable rows, 0 mismatches), stock 2330 individually confirmed exact across open/high/low/close/volume/turnover.
-   **Test Suite Growth**: 68 new tests — `test_finmind_fetcher.py` (27), `test_build_chinese_sector_mapping.py` (10, incl. a real end-to-end backup-file regression test), `test_data_loader_finmind.py` (15), `test_prepare_finmind_legacy_snapshot.py` (9), +7 in `test_run_history_pipeline.py`. Full suite: 248/248 passed.

### Fixed
-   `scripts/build_chinese_sector_mapping.py`: a real bug found during manual live verification — the mapping-file backup path produced a non-`.xlsx`-suffixed filename (`stock_industry_mapping.bak_2026-07-18` instead of `stock_industry_mapping.bak_2026-07-18.xlsx`), which crashed pandas' `to_excel` engine inference. Fixed by inserting the date segment before the extension; a regression test (`test_run_end_to_end_writes_backup_with_valid_xlsx_extension`) now exercises the real file-writing path end-to-end to catch this class of bug.

### Known Findings (see `docs/Milestone_5b_Acceptance_Report.md`)
-   **A pre-existing latent bug in already-accepted M4 code was surfaced by this milestone's real multi-day batch execution, and was deliberately NOT fixed** (governance rule #9: don't modify already-accepted module behavior without a proposal). `scripts/run_daily.py`'s institutional-column merge (~line 414) raises `"Passing 'suffixes' which cause duplicate columns..."` once a prior day's persisted `stock_features_<date>.csv` already carries `foreign_net_buy`/`investment_trust_net_buy`/`dealer_net_buy` from an earlier successful merge — this was never triggered before because M0–M5a never ran the real institutional-merge path across enough consecutive real trading days for a persisted CSV to already carry those columns going into a second merge. Flagged as the highest-priority follow-up for the next milestone that touches `run_daily.py`.
-   Pre-existing demo-data leftover files (`data/raw/ohlcv/prices_2026-07-14/15/16.json`, from `scripts/create_demo_data.py`) shadow BOTH the M5a official bridge and the new M5b FinMind bridge for those 3 dates, because `run_pipeline` checks the combined-file path before the separate per-market legacy files. Not introduced by M5b; disclosed rather than silently deleted.
-   FinMind's hourly request quota means institutional/margin backfill and OHLCV coverage past stock #571 require a follow-up run after the quota window resets (the fetcher is resumable by default).
-   Only 1 date (2026-07-17) has a genuine official raw OHLCV snapshot on disk to reconcile FinMind data against — the instruction's "3 trading days" spot-check could not be fully satisfied due to real data-availability limits on this machine, not an oversight; the single available date was checked across the full fetched universe (571 stocks) rather than just 3 to compensate.
-   Backtest statistics / event study (P0-06) remains correctly out of scope (M5c).

---

## [0.6.0-M5a] - 2026-07-18

### Added
-   **Official Industry Mapping Import** (`scripts/build_official_mapping.py`): live-fetches TWSE `/opendata/t187ap03_L` (上市公司基本資料) and TPEx `/mopsfin_t187ap03_O` (上櫃股票基本資料), both verified against the cached swagger definitions. Merges into `data/reference/stock_industry_mapping.xlsx`: manually-reviewed rows (`reviewed=1`) are never overwritten; stocks the official source doesn't cover stay unclassified rather than being guessed. Also emits a CSV twin. Coverage jumped from 0.41% (8/1974) to 98.58% (1946/1974) against the real 2026-07-17 trading universe.
-   **Honest industry-code disclosure**: neither TWSE nor TPEx's OpenAPI swagger exposes a code->Chinese-name lookup endpoint (verified by exhaustive search, not assumed). The importer keeps the raw numeric code (e.g. "28") as `primary_sector` for newly-imported stocks and records `industry_code_lookup_status=UNAVAILABLE`; the real 7/17 Dashboard shows these raw codes as-is rather than inventing a translation table.
-   **Payload date-consistency guard** (`src/data_fetcher.py::extract_payload_date`, `_parse_roc_or_iso_date`): `DataFetcher.fetch_and_save` now drops (never saves) a fetched payload whose self-reported date (top-level `date` field, or per-row `Date` field) doesn't match the requested `trade_date`, logging a `DATE_MISMATCH` failure entry. Motivated by a swagger-verified finding: TWSE `STOCK_DAY_ALL`/`MI_MARGN`/`MI_INDEX` and every TPEx OpenAPI endpoint accept zero query parameters (always return their latest trading day); only TWSE T86 (institutional, legacy RWD endpoint) genuinely honors a `date=` parameter (live-confirmed).
-   **Resumable backfill**: `DataFetcher.fetch_and_save`/`fetch_all_categories`/`backfill` gained an additive `skip_existing` parameter (default `False`, exactly preserving M4's always-refetch behavior) that skips re-fetching a `(category, market, trade_date)` combination already saved on disk. `scripts/fetch_daily_data.py --backfill` now defaults to `skip_existing=True` (resumable); `--no-resume` restores the old always-refetch behavior.
-   **`scripts/run_history_pipeline.py`**: sequential batch driver over `scripts.run_daily.run_pipeline` (which gained an additive return value it previously lacked) across every date with both markets' OHLCV present on disk, in ascending order so rolling multi-day features accumulate exactly as in normal daily operation. Writes `outputs/signals/signals_<date>.jsonl` (one JSON object per sector-signal row, hits and non-hits both included) per successfully-processed day. A single blocked/failed day is recorded and the batch continues -- does not abort the remaining historical days.
-   **`scripts/prepare_legacy_raw_snapshot.py`**: bridges M4's `data_fetcher.py` raw-snapshot filenames (`twse_<date>.json`) to the legacy filenames `scripts/run_daily.py::run_pipeline` actually reads (`twse_prices_<date>.json`, `inst_<date>.json`, `margin_<date>.json`, etc.) via a pure file copy -- never mutates or deletes the M4-format source, never touches `run_pipeline` itself. Closes a naming mismatch M4's own acceptance report disclosed but didn't fix.
-   **Real 2026-07-17 Report**: `outputs/daily/MoneyFlow_Rotation_2026-07-17.xlsx` produced end-to-end from real fetched data with the new official mapping applied. Audit: status=SUCCESS, DQ score=91.0 (WARNING), mapping coverage=98.58%, 44 sectors scored (29 B級早期點火, 15 C級個股事件, 0 A/續漲 since this standalone run had no `prev_date` history for day-over-day breakout conditions), 1,974 stocks scored.
-   **Test Suite Growth**: `test_build_official_mapping.py` (18 tests), `test_run_history_pipeline.py` (12 tests), `test_prepare_legacy_raw_snapshot.py` (4 tests), plus 12 new tests in `test_data_fetcher.py` (date-consistency guard + resumable-backfill skip_existing).

### Fixed
-   `tests/integration/test_m3_real_snapshot_e2e.py`: the low-mapping-coverage-warning Dashboard assertion was hardcoded to always require the warning text, which became false once the M5a official mapping import raised real coverage above the 80% threshold. Now reads the actual coverage from the run's audit JSON and asserts conditionally: warning required when `<80%`, warning absent + actual percentage displayed when `>=80%`. All other pre-existing assertions (4-sheet schema, uncalibrated-threshold warning, log/audit file existence, non-empty stock-priority sheet) are unchanged.

### Known Findings (see `docs/Milestone_5a_Acceptance_Report.md`)
-   **Historical backfill (2026-04-20 to 2026-07-17) did not fully complete this session.** This sandbox's outbound network to both TWSE and TPEx hosts experienced a SUSTAINED (not merely intermittent, as M4 described) multi-hour total outage -- every connection attempt across dozens of consecutive tries failed, independently confirmed via `Resolve-DnsName` resolving to the unreachable `10.0.0.1` sinkhole address. The actual number of trading days successfully backfilled (only TWSE T86 institutional is architecturally capable of true historical data -- every other endpoint has zero date query parameters per swagger and would only ever return "today" regardless of network health) is reported honestly in `loop/evidence/fetch_receipts/backfill_summary.json`, not padded to look complete.
-   Industry code -> Chinese name resolution remains unresolved (no verified official source found); sector names in the real 7/17 report show raw numeric codes for the 1,955 newly-imported (non-manually-reviewed) stocks.
-   Backtester / limit-up lockout (P0-06), disposition/caution stock tagging, and ex-dividend adjusted-price correctness remain correctly deferred to Milestone 5b.

---

## [0.5.0-M4] - 2026-07-18

### Added
-   **Daily Data Fetcher** (`src/data_fetcher.py`, `scripts/fetch_daily_data.py`): fetches TWSE+TPEx daily OHLCV/institutional/margin/market-index from the same real verified endpoints already used by `scripts/inspect_endpoints.py`/`src/data_loader.py`, writing the standard `{metadata, payload}` envelope to `data/raw/<category>/<market>_<date>.json`. Fail-closed on HTTP != 200, empty payload, or schema mismatch (returns None, logs, never raises); retries up to 2 times at 3s spacing; idempotent (`.bak` backup before any overwrite); `--backfill start end` (weekends skipped, holiday-empty-payload treated as a normal record, not a failure); `--smoke` mode (single live endpoint + schema validation only).
-   **Market Index Fetch**: TWSE `MI_INDEX` (大盤統計資訊/TAIEX) and TPEx `tpex_index` (櫃買指數歷史資料), both discovered and verified against the cached `loop/evidence/raw_samples/{twse,tpex}_swagger.json` OpenAPI definitions — not recalled from memory. Both are real, working endpoints, so the `INDEX_SOURCE_UNAVAILABLE` fail-closed marker exists as a code path but was not triggered in practice.
-   **`src/market_regime.py`** (SPEC Chapter 18): 6-state market regime classifier (多頭擴張/多頭盤整/高檔鈍化/空頭反彈/空頭趨勢/極端風險) from index MA20/MA60/20-day return/20-day volatility plus full-market breadth. Degrades to breadth-only classification (`DEGRADED` confidence) when index history is entirely absent; reports `INSUFFICIENT_DATA` when index history exists but has fewer than 60 rows (can't compute MA60). All thresholds `# PLACEHOLDER - UNCALIBRATED`.
-   **`src/institutional_features.py`**: per-stock 3/5/10/20-day cumulative net buy (rolling sum, `min_periods` = window size), consecutive-buy-day streak, buy-as-pct-of-volume, foreign+trust same-direction flag; sector-level aggregation (net-buying stock count, net buy total, pct of sector turnover); SPEC_ADDENDUM C-1 investment-trust quarter-end (Mar/Jun/Sep/Dec) last-5-trading-day window flag (`quarter_end_window`).
-   **`src/margin_features.py`**: margin balance % change (3d/5d), margin usage rate (real quota-based when a quota column is present, else a documented `_proxy`-suffixed rolling-60-day-max fallback), short-margin ratio (券資比). Null discipline throughout — never zero-fills a missing/zero denominator.
-   **Wiring Fix** (`scripts/run_daily.py`): closed a pre-existing gap where `foreign_net_buy`/`investment_trust_net_buy`/`dealer_net_buy` were computed (`df_inst`) but never actually merged onto the stock-features frame passed into `stock_scoring.score_stocks` — so the "institution" scoring sub-factor silently used a neutral 50.0 prior every day even when real institutional data existed. Now merged before scoring; institutional/margin rolling-history CSVs (`institutional_features_<date>.csv`, `margin_features_<date>.csv`) persisted and rebuilt the same no-future-leakage way as stock/sector features. Sector-level institutional aggregation columns attached to `sector_features_<date>.csv` as additional reference columns (sector_score formula itself unchanged).
-   **Test Suite Growth**: 46 new unit tests (`test_data_fetcher.py` 15, `test_market_regime.py` 10, `test_institutional_features.py` 13, `test_margin_features.py` 8) + 1 new integration test (`tests/integration/test_m4_institutional_wiring_e2e.py`, real 2026-07-16 snapshot, proves `foreign_net_buy`/`score_institution` are actually populated post-fix). Full suite: 134/134 passed.
-   **Live Network Verification**: `--smoke` executed live (HTTP 200, 1,371 rows). Full single-day fetch for 2026-07-17 executed live: all 8 (category×market) endpoints succeeded (HTTP 200, real row counts, sha256-verified). Receipts at `loop/evidence/fetch_receipts/{smoke_receipt_2026-07-17.json, fetch_receipt_2026-07-17.json}`.

### Known Findings (see `docs/Milestone_4_Acceptance_Report.md`)
-   This sandboxed dev machine's default outbound network path intermittently DNS-sinkholes/times-out HTTPS connections to TWSE/TPEx hosts (confirmed via independent DNS/socket-level investigation — not specific to this fetcher's code); individual CLI invocations transiently failed different subsets of the 8 endpoints across attempts. The fetcher's fail-closed contract worked correctly throughout: no file was ever overwritten except on a genuine HTTP 200 + schema-valid response. Full root-cause narrative disclosed in the acceptance report rather than hidden.
-   `run_pipeline` (full daily Excel report) was not re-run end-to-end against the newly fetched 2026-07-17 real data this milestone; the M3 and new M4 E2E tests continue to use the 2026-07-16 evidence-folder snapshots.
-   Backtester / limit-up lockout (P0-06), disposition/caution stock tagging, and ex-dividend adjusted-price correctness remain correctly deferred to Milestone 5 (backtest milestone, out of M4 scope).

---

## [0.4.0-M3] - 2026-07-18

### Added
-   **Signal Detector Rewrite** (`src/signal_detector.py`): implements SPEC Chapter 14's 10-condition New Gainer (新起漲) checklist and Chapter 15's Continued Momentum (續漲) checklist as explicit per-condition pass/fail/unevaluable evaluators. A/B/C/無效 grading for new-gainer, 續漲訊號/無訊號 for continued-momentum. Every graded row carries `conditions_passed`, `conditions_failed`, `conditions_unevaluable`, `invalidation_condition`, and `signal_data_confidence` (FULL/DEGRADED/LOW).
-   **UAT-04 Hard Gate**: sectors with fewer than 2 distinct up-moving stocks (`up_stock_count`) can never be graded A or B new-gainer, regardless of score — capped at C or 無效, preventing single-stock moves from being reported as sector-wide events.
-   **15 New Config Thresholds** (`config/default.yaml` `new_gainer.*`/`continued_momentum.*`, mirrored in `src/config_manager.py::get_defaults`), each `# PLACEHOLDER - UNCALIBRATED` and commented with its SPEC chapter rule number.
-   **Excel Report Rewrite** (`src/report_generator.py`): exactly 4 sheets per SPEC_ADDENDUM B-4 — Dashboard (資料品質、映射覆蓋率、未分類警語、前10族群分數表), 新起漲族群, 續漲族群, 個股優先排序 — each with a data-quality/caveat block, Chinese column headers, and percent/thousand-separator number formatting. Unmapped (待分類) stocks get an explicit risk-downgrade note rather than inherited FULL confidence.
-   **Execution Logging + Audit JSON** (`scripts/run_daily.py`): loguru file sink at `outputs/logs/run_<date>.log` (key steps, row counts, DQ score); structured audit summary at `outputs/logs/audit_<date>.json` (input files, row counts, output files, elapsed time, status).
-   **Real 2026-07-16 End-to-End Run**: full pipeline executed against the real cached TWSE+TPEx OHLCV/institutional/margin snapshots (no network calls, no synthetic data), producing a real `outputs/daily/MoneyFlow_Rotation_2026-07-16.xlsx` (13,671 bytes), covered by `tests/integration/test_m3_real_snapshot_e2e.py`.
-   **Test Suite Growth**: 28 new tests — `tests/unit/test_signal_detector.py` (14), `tests/unit/test_report_generator.py` (13), `tests/integration/test_m3_real_snapshot_e2e.py` (1, marked `slow`). Full suite: 87/87 passed.
-   **`docs/signal_definitions.md`** expanded with a new §3.5 documenting the full 10/9-condition checklists, grading rules, UAT-04, and track precedence.
-   **`pytest.ini`** added to register the `slow` marker.

### Changed
-   `tests/acceptance/test_future_leakage.py` (P0-03 critical test): sheet-name lookup updated from the old English `"Stock Observation Priority"` to the new B-4 Chinese `"個股優先排序"` (with `header=2` to skip the new title banner row). The actual future-leakage assertion is unchanged.

### Known Findings (see `docs/Milestone_3_Acceptance_Report.md` §4 and §6)
-   Discovered (not silently fixed) a pre-existing M1 environment-coupling issue: `load_excel_leaderboard`'s hardcoded glob into a sibling `Quant-Agent` project directory can pick up an incidental real leaderboard file, and reconciling against it surfaces a genuine `daily_return` ((close-open)/open) vs. leaderboard 漲跌幅 (prev-close-to-close) return-basis mismatch that can legitimately BLOCK the pipeline via the Data Quality Score. Flagged as a recommendation for a future milestone; M1 scoring logic is locked this milestone.
-   Continued Momentum rules 5/6 (次龍頭接棒、高檔爆量不漲) always `conditions_unevaluable` — no per-stock leadership-continuity or intraday tick data wired yet.
-   Industry mapping coverage remains the known ~0.4% (8/1988) — Dashboard surfaces this honestly; individual-stock ranking works independently of it.

---

## [0.3.0-M2] - 2026-07-18

### Added
-   **Rolling Stock Features** (`src/stock_features.py::calculate_rolling_features`): multi-day rolling volume/turnover means (5d/20d, `min_periods` enforced), relative volume, 20-day-high distance, and 1/3/5/10/20-day returns. All windows computed per-stock via groupby+transform; verified leakage-free with a truncated-vs-full-dataset regression test.
-   **Sector Concentration & Relative Strength** (`src/sector_features.py`): Top1/Top3/Top5 turnover concentration, and `calculate_relative_strength_history` for 3d/5d rolling relative strength.
-   **P0-05 No-Double-Counting Flag**: sector/theme aggregate rows now carry `may_double_count` (False for primary_sector, True for theme), with dedicated unit + integration test coverage.
-   **Sector Scoring Overhaul** (`src/sector_scoring.py`): all weights/thresholds explicitly marked `# PLACEHOLDER - UNCALIBRATED`; strict dynamic weight renormalization (never zero-fills a missing factor); `score_confidence` in {FULL, DEGRADED, LOW}; scores clamped to [0, 100]; partial Overheat Risk sub-score (breadth/volume divergence, volume-surge proxy, concentration).
-   **New `src/stock_scoring.py`**: individual-stock scoring (35% sector / 20% relative strength / 15% volume structure / 10% rank improvement / 10% breakout quality / 10% institutional), same renormalization/confidence contract, role assignment (領先龍頭/高流動性次龍頭/基本面受惠股/低位階補漲股/資料不足).
-   **Lifecycle Classifier Rewrite** (`src/lifecycle_classifier.py`): now requires >=3 days of accumulated sector history (SPEC 13.6 compliance); returns `資料不足`/`INSUFFICIENT_DATA` below that threshold, `PARTIAL` confidence for 3-9 days, `FULL` for >=10 days; classification uses 3-day delta plus 5/10-day trend evidence, not a single day's snapshot.
-   **New `src/labels.py`** (P0-02): New Gainer / Continued Momentum success/minor-failure/reversal label functions matching `docs/signal_definitions.md`, with insufficient-data handling for missing forward returns.
-   **New `scripts/build_mapping_template.py`**: discovers the real stock universe from cached TWSE/TPEx OHLCV snapshots, cross-references against the existing mapping file, and emits a CSV template for unmapped stocks with empty (never guessed) sector columns.
-   **Pipeline Multi-Day Accumulation** (`scripts/run_daily.py`): persists `data/processed/{stock_features,sector_features,sector_scored,stock_scored}_<date>.csv` per run; rebuilds rolling history strictly from files dated on or before the current run's trade_date, giving a structural (not just test-asserted) no-future-leakage guarantee.
-   **Test Suite Growth**: 45 new tests across `tests/unit/test_stock_features.py`, `test_sector_features.py`, `test_sector_scoring_confidence.py`, `test_stock_scoring.py`, `test_lifecycle_classifier.py`, `test_labels.py`, plus `tests/integration/test_m2_real_snapshot_integration.py` (real cached snapshot, 1,975 cleaned equities) and `tests/integration/test_m2_e2e_pipeline.py` (3-day mock E2E). Full suite: 59/59 passed.

### Known Limitations (see `docs/Milestone_2_Acceptance_Report.md`)
-   Overheat Risk implements only 3 of the ~9 SPEC 12.3 sub-factors (no consecutive-limit-up count, upper-shadow-candle ratio, or institutional-selling-reversal signal wired yet).
-   Sector "momentum/continuity" (15% weight) and stock "breakout quality" sub-scores fall back to a neutral 50.0 prior when the underlying signal is unavailable (which is the entire pipeline run today, since momentum continuity is not yet independently modeled).
-   `scripts/build_mapping_template.py` has no automated pytest coverage (manually verified against real snapshots only).

---

## [0.2.0-M1] - 2026-07-17

### Added
-   **Dual-Market Integration**: Implemented price and volume cleanup from TWSE `STOCK_DAY_ALL` and TPEx `/tpex_mainboard_daily_close_quotes` (P0-01).
-   **Prefix Padded Standardizer**: Forces stock code standardization (e.g. 50 -> "0050") and filters out ETFs and warrants (P0-04).
-   **Embrace Null Fact Contract**: Updated Pydantic schema in `data_contracts.py` to use `Optional[float] = None` for institutional transactions to prevent zero-filling (B-02).
-   **Date Payload Checks**: Integrated date mismatch validation (B-03) and schema checker inside `DataValidator`.
-   **Leaderboard Reconciler**: Coded `DataCleaner.reconcile_with_leaderboard` matching returns against Excel logs (C07).
-   **Integration Tests**: Created `tests/integration/test_m1_integration.py` to audit real response JSON normalization.

---

## [0.1.0-M0] - 2026-07-17

### Added
-   **Directory Isolation Setup**: Initialized 29 required directories for source code, loop files, and validation evidence.
-   **M0 Specifications**: Written `docs/architecture.md`, `docs/data_dictionary.md`, `docs/signal_definitions.md`, and `docs/data_catalog_and_risk_log.md` detailing system flow.
-   **Correct OpenAPI Caching**: Coded `scripts/inspect_endpoints.py` mapping actual TWSE/TPEx routes with metadata logging (fetch time, status codes, sha256). Cached 6 JSON response samples.
-   **Deterministic Mock Generation**: Fixed random seed to 42 in `create_demo_data.py` for E2E validation.
-   **Historical Leaderboard Reports Analysis**: Decoded CP950-scrambled Excel logs and compiled gainer schema findings and missing data lists in `docs/historical_reports_analysis.md`.
-   **Mechanical Auditing Scripts**: Coded `scripts/verify_directories.py` validating 29-folder manifests with non-zero exit rules.
-   **Verification Logs**: Configured test suites with logged execution traces.
# 2026-07-22 — Auto-backfill late official data (M11)

- Added `scripts/daily_orchestrator.py` automatic mode: scan the last 5 calendar
  days' weekdays, probe TWSE `MI_INDEX` + `STOCK_DAY_ALL`, run ready missing dates
  oldest-first, and record `DEFERRED_NOT_READY` without invoking fetch/pipeline.
- Added holiday classification (`HOLIDAY_SKIP`) from explicit empty-response evidence;
  successful dates remain idempotently skipped. Explicit `--date` and `--no-backfill`
  preserve the one-day path. New constants are marked `# DEFAULT - 可調`.
- Updated `scripts/daily_run.ps1` and `docs/operations_manual.md`; no Windows Task
  Scheduler entries were created or modified. FinMind and all signal/backtest core
  modules remain untouched.
- Added 12 hermetic tests in `tests/integration/test_auto_backfill.py`.
- Evidence: baseline `471 passed`, post-change `483 passed`; live raw samples and
  no-fetch dry-run under `loop/evidence/`; live E2E attempted 2026-07-21 and correctly
  ended `PIPELINE_BLOCKED` because TPEx latest payloads were date-mismatched, while
  2026-07-22 was safely deferred. See `docs/Auto_Backfill_Late_Data_Report_20260722.md`.

## M11 follow-up — manual correction persistence

- Added a fail-closed TPEx historical OHLCV fallback in `scripts/fetch_daily_data.py`.
  It POSTs the official TPEx `afterTrading/dailyQuotes` action for the requested date,
  verifies the response date, and writes the normal raw envelope before the existing
  bridge/pipeline runs. It never relabels the latest-day OpenAPI response.
- Re-running the exact `scripts/daily_run.bat` recovered 2026-07-21 (10,072 TPEx
  rows), wrote raw and bridge files, and generated `outputs/daily/MoneyFlow_Rotation_2026-07-21.xlsx`;
  the batch exited 0. 2026-07-22 remained `DEFERRED_NOT_READY` because the official
  readiness probe had not advanced.
- Added four unit/integration tests for successful persistence, date mismatch, HTTP/JSON
  fail-closed behavior, and `run_single_day` receipt wiring. Full suite: **487 passed**.
  Evidence: `loop/evidence/manual_daily_run_after_historical_tpex_20260722.log` and
  `loop/evidence/test_logs/pytest_historical_tpex_recovery_run_log.txt`.
