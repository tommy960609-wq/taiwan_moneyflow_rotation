# Task Queue

## [x] Milestone 0: API Verification & Initial Design
- `[x]` Create 29 required directories
- `[x]` Document contracts (`data_dictionary.md`, `signal_definitions.md`, `architecture.md`, `data_catalog_and_risk_log.md`)
- `[x]` Run `inspect_endpoints.py` to query TWSE/TPEx OpenAPI endpoints and save raw JSON responses to `loop/evidence/raw_samples/`
- `[x]` Fix random seed 42 in `create_demo_data.py` for deterministic data setup
- `[x]` Create README and requirements.txt for environmental reproducibility
- `[x]` Audit 3 historical leaderboard files and output analysis to `historical_reports_analysis.md`

## [x] Milestone 1: Data Integrations & Schema Normalization
- `[x]` Integrate TWSE + TPEx dual-market daily price & volume streams (P0-01)
- `[x]` Map margin trading and institutional statistics without zero-filling missing values (B-02)
- `[x]` Add date payload parsing, ticker standardization, and validation boundary tests (B-03)
- `[x]` Clean and filter out ETFs and warrants (P1-03)
- `[x]` Implement leaderboard reconciler (C07)

## [x] Milestone 2: Feature Engineering & Scoring Engine (Implemented by maker, pending independent verifier gate)
- `[x]` Stock level rank improvements and daily returns (kept `calculate_ranks` API)
- `[x]` Multi-day rolling stock features (vol_ma5/20, turnover_ma5/20, relative volume, 20d-high distance, 1/3/5/10/20d returns), min_periods-enforced, no-future-leakage regression tested
- `[x]` Sector level real full-market breadth, Top1/3/5 concentration, HHI, and institutional flow calculations
- `[x]` P0-05: primary_sector vs theme `may_double_count` flag (no double counting of primary aggregate turnover)
- `[x]` Sector relative strength rolling history (1d/3d/5d)
- `[x]` Implement dynamic scoring weight normalizations when columns are missing (sector + stock scoring, `score_confidence` FULL/DEGRADED/LOW)
- `[x]` New `src/stock_scoring.py` individual-stock scoring model
- `[x]` Lifecycle classifier rewrite requiring 3/5/10-day history evidence, insufficient-data fallback
- `[x]` P0-02: `src/labels.py` success/failure label definitions + unit tests (no backtest run, out of scope)
- `[x]` `scripts/build_mapping_template.py` (never-guess unmapped-stock template generator)
- `[x]` Pipeline wiring: `scripts/run_daily.py` persists processed multi-day feature/score CSVs and rebuilds rolling history from disk
- `[~]` Overheat risk score (0-100): PARTIAL, 3 of ~9 spec sub-factors implemented, disclosed as known limitation

## [x] Milestone 3: Signal Detection & Excel Reporting (Implemented by maker, pending independent verifier gate)
- `[x]` New Gainer 10-condition signal detection (SPEC Ch.14), A/B/C/無效 grading, per-condition pass/fail/unevaluable + invalidation condition + data confidence (`src/signal_detector.py` full rewrite)
- `[x]` Continued Momentum signal detection (SPEC Ch.15)
- `[x]` UAT-04: single-stock spike hard-capped at C, never A/B new-gainer
- `[x]` All 15 new signal thresholds in `config/default.yaml`, `# PLACEHOLDER - UNCALIBRATED` marked
- `[x]` Excel Slim Output: exactly 4 sheets per SPEC_ADDENDUM B-4 (Dashboard/新起漲族群/續漲族群/個股優先排序), `src/report_generator.py` rewrite, verified via openpyxl reopen
- `[x]` Real 2026-07-16 snapshot run end-to-end -> real `outputs/daily/MoneyFlow_Rotation_2026-07-16.xlsx`
- `[x]` Execution log (`outputs/logs/run_<date>.log`) + audit JSON (`outputs/logs/audit_<date>.json`)
- `[x]` `docs/signal_definitions.md` expanded with grade/condition/invalidation detail
- `[ ]` Backtester entry delays and limit-up checkout logic (P0-06, correctly deferred — backtest milestone, not M3 scope)

## [x] Milestone 4: V2 Data — Daily Fetcher, Market Regime, Institutional/Margin Features (Implemented by maker, pending independent verifier gate)
- `[x]` `src/data_fetcher.py` + `scripts/fetch_daily_data.py`: daily TWSE/TPEx OHLCV+institutional+margin fetcher, fail-closed retry (2 retries/3s delay), idempotent `.bak` backup, `--backfill start end` (skips weekends), `--smoke` live-endpoint-and-schema-only mode
- `[x]` Market index fetch: TWSE `MI_INDEX` (TAIEX) + TPEx `tpex_index` (櫃買指數), both verified against cached swagger paths (not recalled from memory)
- `[x]` `src/market_regime.py`: 6-state classification (多頭擴張/多頭盤整/高檔鈍化/空頭反彈/空頭趨勢/極端風險) from index MA20/MA60/20d return/volatility + market breadth; degrades to breadth-only DEGRADED confidence when index unavailable; INSUFFICIENT_DATA below 60 days of index history
- `[x]` `src/institutional_features.py`: individual-stock 3/5/10/20d cumulative net buy, consecutive-buy-day streak, buy-pct-of-volume, foreign+trust same-direction flag; sector-level aggregation (net-buying stock count, net buy total, pct of sector turnover); C-1 quarter-end (3/6/9/12 month) last-5-trading-day window flag
- `[x]` `src/margin_features.py`: margin balance change rate (3d/5d), margin usage rate (real quota-based or documented rolling-max proxy), short-margin ratio (券資比); Null discipline throughout (never zero-filled)
- `[x]` Wiring fix: `scripts/run_daily.py` now actually merges `foreign_net_buy`/`investment_trust_net_buy`/`dealer_net_buy` onto the stock-features frame before scoring — closes a pre-existing gap where `stock_scoring`'s "institution" factor silently fell back to a neutral 50.0 prior every day even when institutional data existed
- `[x]` 46 new unit tests (`test_data_fetcher.py`, `test_market_regime.py`, `test_institutional_features.py`, `test_margin_features.py`) + 1 new integration test (`test_m4_institutional_wiring_e2e.py`, real 2026-07-16 snapshot, asserts `foreign_net_buy`/`score_institution` are actually populated, not silently NaN)
- `[x]` Live smoke test executed: HTTP 200, 1371 rows, real schema (see `loop/evidence/fetch_receipts/smoke_receipt_2026-07-17.json`)
- `[x]` Live single-day fetch executed for 2026-07-17: 7/7 endpoints succeeded after retry (see `loop/evidence/fetch_receipts/fetch_receipt_2026-07-17.json`); this environment's default sandboxed network path DNS-sinkholes all outbound HTTPS hosts to `10.0.0.1`, so the fetch/smoke had to be re-run with the sandbox network restriction lifted — disclosed in `docs/Milestone_4_Acceptance_Report.md` §5, not hidden
- `[ ]` Backtester entry delays, limit-up lockout handling (P0-06) — correctly deferred to Milestone 5 (backtest milestone)
- `[ ]` Disposition/caution stock tagging and weight penalty — deferred to Milestone 5
- `[ ]` Ex-dividend adjusted-price return correctness — deferred to Milestone 5

## [x] Milestone 5a: Official Mapping, Historical Backfill, History Pipeline, Real 7/17 Report (Implemented by maker, pending independent verifier gate)
- `[x]` `scripts/build_official_mapping.py`: live-fetched TWSE `/opendata/t187ap03_L` + TPEx `/mopsfin_t187ap03_O` (both swagger-verified), merged into `data/reference/stock_industry_mapping.xlsx` protecting all `reviewed=1` rows, never guessing unmapped stocks. Coverage 0.41% -> 98.58% against real 2026-07-17 universe
- `[~]` Industry code -> Chinese name resolution: PARTIAL, honestly `UNAVAILABLE` (no lookup endpoint exists in either swagger); raw numeric codes kept and disclosed, not invented
- `[x]` Date-consistency guard (`src/data_fetcher.py::extract_payload_date`): drops any saved payload whose self-reported date doesn't match the requested trade_date -- fail-closed, never mislabels "today" as history
- `[x]` Swagger-verified finding: TWSE `STOCK_DAY_ALL`/`MI_MARGN`/`MI_INDEX` and ALL TPEx endpoints take zero query parameters (latest-day-only); only TWSE T86 (institutional) genuinely supports historical `date=`
- `[x]` Resumable `--backfill` (`skip_existing`, additive, default-False preserves M4 behavior; CLI defaults to resumable)
- `[~]` Historical backfill 2026-04-20 to 2026-07-17: PARTIAL, sustained sandbox network outage during this session constrained actual days fetched -- see `docs/Milestone_5a_Acceptance_Report.md` and `loop/evidence/fetch_receipts/backfill_summary.json` for the honest day-by-day count
- `[x]` `scripts/run_history_pipeline.py`: sequential batch driver reusing `run_pipeline`, writes `outputs/signals/signals_<date>.jsonl` per successful day, one bad day doesn't abort the batch
- `[x]` `scripts/prepare_legacy_raw_snapshot.py`: bridges M4 fetcher filenames to the legacy filenames `run_pipeline` reads (pure copy, disclosed pre-existing M4 gap, doesn't touch locked M1-M4 code)
- `[x]` Real 2026-07-17 report: `outputs/daily/MoneyFlow_Rotation_2026-07-17.xlsx`, SUCCESS, DQ 91.0, coverage 98.58%, 44 sectors (29 B級 + 15 C級)
- `[x]` `tests/integration/test_m3_real_snapshot_e2e.py` low-coverage-warning assertion made conditional on real coverage (was hardcoded to the old low-coverage state)
- `[x]` New offline test files: `test_build_official_mapping.py` (18), `test_run_history_pipeline.py` (12), `test_prepare_legacy_raw_snapshot.py` (4), plus 12 new tests added to `test_data_fetcher.py` (date-consistency + resumable backfill)

## [x] Milestone 5b: FinMind Historical Backfill, Chinese Sector Names, Dual-Source Loader, History Batch Pipeline (Implemented by maker, pending independent verifier gate)
- `[x]` `src/finmind_fetcher.py`/`scripts/fetch_history_finmind.py`: FinMind dataset names dry-run verified live (never recited), fail-closed, rate-limit-aware (HTTP 402/429 short-circuit), resumable
- `[~]` Real backfill executed: OHLCV 571/1963 stocks (29.1%, full 62-day history each) before FinMind's hourly quota was hit; institutional/margin 0/1963 (quota exhausted first, OHLCV was deliberately prioritized); TAIEX index 100%; TPEx/OTC index confirmed UNAVAILABLE (8 candidates tried, none usable) -- resumable via default `skip_existing=True`
- `[x]` `scripts/build_chinese_sector_mapping.py`: converts M5a's raw numeric codes to real FinMind Chinese sector names, 1,955/1,955 eligible rows updated (100%), 8 reviewed rows protected, old code preserved in new `sector_code` column
- `[x]` Real 7/17 report re-run and verified showing Chinese sector names in the Dashboard; old report backed up to `.xlsx.bak`
- `[x]` `data_loader.py` dual-source integration: `load_finmind_*_for_date`/`merge_*_sources`, official data always wins on conflict, `source` column never blended
- `[x]` `scripts/prepare_finmind_legacy_snapshot.py` + `run_history_pipeline.py --use-finmind`: FinMind data bridged into the batch pipeline, official-source priority preserved at the file level, default behavior unchanged
- `[~]` Historical batch pipeline actually run over the full 62-day range: 2 SUCCESS, 26 EXCEPTION (pre-existing M4 merge bug newly surfaced, NOT fixed per governance rule #9, disclosed), 31 BLOCKED_LOW_DQ (fail-closed correctly), 3 BLOCKED_MISSING_MARKET (pre-existing demo-file shadowing, disclosed)
- `[x]` Reconciliation spot-check: 569/571 FinMind-fetched stocks exact-matched official 2026-07-17 close (100%, 0 mismatches); 2330 individually confirmed; only 1 date had a real official snapshot available (disclosed, not the full 3-date ask)
- `[x]` 68 new tests: `test_finmind_fetcher.py` (27), `test_build_chinese_sector_mapping.py` (10), `test_data_loader_finmind.py` (15), `test_prepare_finmind_legacy_snapshot.py` (9), +7 in `test_run_history_pipeline.py`. Full suite 248/248 passed

## [x] Milestone 5c-prep: Merge Bug Fix, Mock-File Unshadowing, FinMind Backfill Resume, Full Batch Rerun (Implemented by maker, pending independent verifier gate)
- `[x]` Fix the M4 institutional-column merge-suffix bug (M5b's highest-priority carry-forward): `scripts/run_daily.py` now drops stale institutional columns before merging in fresh values; regression test `tests/integration/test_run_daily_two_day_merge.py` directly reproduces the bug pre-fix and confirms the fix post-fix. Only this one call site touched, no other production behavior changed
- `[x]` Resolve the 3-day `BLOCKED_MISSING_MARKET` mock-file shadowing: moved `prices_2026-07-14/15/16.json` to `data/test_fixtures/legacy_mock/`, updated the one dependent test's path, verified via the batch rerun that all 3 dates are no longer shadowed
- `[x]` Found and fixed (test-only) an independent hermeticity issue in `test_m2_e2e_pipeline.py`: mock stock IDs collided with a real external leaderboard file, causing an unrelated `BLOCKED_LOW_DQ`; isolation-tested to confirm this was NOT caused by the mock-file move
- `[~]` FinMind institutional/margin backfill resumed: PARTIAL, institutional 0->26/1963, margin 0->2/1963 (OHLCV unchanged at 571/1963, deprioritized this round). New finding: the rate limit is a short burst-scale throttle (~30-90s), not a clean hourly window as M5b assumed
- `[x]` Full 62-day historical batch pipeline rerun: 60/62 SUCCESS (was 2), 0 EXCEPTION (was 26), 2 BLOCKED_LOW_DQ (was 31, now only 2 genuinely-thin dates), 0 BLOCKED_MISSING_MARKET (was 3). Backups of pre-rerun processed/signals/audit files taken before overwrite
- `[x]` `docs/Milestone_5c_prep_Report.md` + loop 4-file sync + pytest receipt (249/249 passed)

## [x] Milestone 5c: Event-Study Backtest Core (P0-06) (GATE APPROVED — see `loop/PROJECT_STATE.md`)
- `[x]` Backtester entry delays, limit-up lockout handling (exclude vs. postpone-to-T+2, both reported) — `src/backtester.py`
- `[x]` `src/benchmarks.py`: momentum-extension + random-sector-bootstrap (N=10,000) baselines
- `[x]` `scripts/run_backtest.py` orchestrator, real 60-day run: 53 independent events, B級/C級 both underperform momentum baseline (「無增量價值證據」), n<30 both tiers
- `[~]` Ex-dividend adjusted-price return correctness — NOT implemented, explicitly disclosed (no `adjusted_close` field exists anywhere in the pipeline)
- `[ ]` Disposition/caution stock tagging weight penalty — implemented and unit-tested, but never exercised by real data (0 real events had a disposition-listed member this round)
- `[~]` Complete FinMind institutional/margin backfill — still in progress via background drip (see M6 below)

## [x] Milestone 6: 正式化 (Implemented by maker, pending independent verifier gate)
- `[x]` `scripts/daily_orchestrator.py`: one-click fetch -> legacy-bridge -> run_pipeline -> signals-JSONL chain, fail-closed contract for 3 named scenarios (network failure/API empty response/DQ black-out), dependency-injected for hermetic testing
- `[x]` `scripts/daily_run.ps1` / `scripts/daily_run.bat`: one-click wrapper scripts, Windows Task Scheduler-ready (scheduler setup documented, NOT actually created per task instruction)
- `[x]` `tests/integration/test_daily_orchestrator.py` (12 tests): all 3 failure scenarios + happy path + exception-catching contract, fully offline via dependency injection
- `[x]` `docs/operations_manual.md`: user-facing (non-engineer) daily operation guide — how to run, how to read the 4 report sheets, error reference table, backfill progress check, FinMind quota characteristics, scheduler setup steps
- `[x]` `README.md` full rewrite: accurate new-environment reproduction steps (venv -> requirements -> verify -> first run -> reproducibility self-check), fixed stale M0-era content pointing at the wrong venv path
- `[x]` `docs/acceptance_report.md`: final acceptance report per spec Ch.36 format, P0/P1/P2 itemized, honest Software-Ready-candidate verdict, explicit NOT Research Ready / NOT Trading Decision Support Ready with evidence
- `[x]` `VERSION` (`v1.0.0-software-ready-candidate`) + `CHANGELOG.md` final entry
- `[x]` Real orchestrator run executed twice against live TWSE/TPEx endpoints: once for 2026-07-18 (today) surfacing a genuine data-availability gap (official endpoints hadn't published yet) that exposed a pre-existing `run_daily.py` bug (see below), once for 2026-07-17 demonstrating full SUCCESS end-to-end incl. reproducibility (byte-identical processed CSVs across 2 independent runs)
- `[x]` `tests/regression/test_run_daily_empty_market_crash.py` (2 tests): hermetically reproduces a real bug FOUND but NOT fixed (already-accepted M1-M5c code, out of this milestone's authorized scope) — `run_daily.py::run_pipeline`'s legacy fallback raises `KeyError: 'market_type'` instead of reaching its own `BLOCKED_MISSING_MARKET` fail-closed path when both the M4 bridge files are absent AND the legacy live-fallback also returns empty
- `[x]` FinMind drip backfill (PID 2924) verified STILL ALIVE and progressing (OHLCV 571/1963 at M5c -> 802/1963 at M6 verification) — corrects `loop/PROJECT_STATE.md`'s prior "found dead" claim; NOT restarted (killing a healthy, progressing background process would be needlessly destructive)
- `[x]` Full suite: 305 passed (291 baseline + 12 orchestrator + 2 regression), 0 failed; `loop/evidence/test_logs/pytest_m6_run_log.txt`
- `[ ]` P2 items NOT reaching the 90% bar (55.6% actual): charts/圖表 (never implemented), walk-forward, parameter sensitivity, anomaly notification — all disclosed in `docs/acceptance_report.md`, do not block Software Ready (P2 isn't required for it)
- `[ ]` Test coverage percentage — `coverage` package never installed/run since M0; spec §28.1's two coverage-percentage gates are UNVERIFIED, not claimed as met

## [x] Milestone 7: 避坑補完包 (Pitfall Pack) (Implemented by maker, pending independent verifier gate)
- `[x]` Dry-run verify FinMind adjusted-price dataset (6 candidates, all UNAVAILABLE) -> fallback to `TaiwanStockDividendResult`-derived backward adjustment factors (`src/price_adjuster.py`)
- `[~]` Fetch adjustment factors for the FinMind-backfilled universe — 516/890 stocks (58%), rate-limited mid-run, disclosed (`scripts/fetch_price_adjustments.py`)
- `[x]` `backtest.use_adjusted_prices` config switch (default true) wired into `scripts/run_backtest.py`; `src/backtester.py`/`src/benchmarks.py` themselves unmodified; UNADJUSTED stocks tagged, never blended
- `[x]` Disposition/caution stock endpoints discovered from swagger (5 real endpoints), fetcher built fail-closed (`src/disposition_fetcher.py`); today's real list: 41 stocks (12 disposition, 29 attention)
- `[x]` Disposition/attention flag wired into daily report's 個股優先排序 sheet AND `Backtester.run_event_study`'s pre-existing `disposition_stock_ids` parameter (previously always empty per M5c's own disclosed gap) — disclosed as same-day-snapshot-only
- `[x]` 36-day user-collected leaderboard integration: limit-up count/streak history (proxy) at market + sector level (`src/leaderboard_loader.py`+`src/limit_up_history.py`) — OBSERVE-ONLY, deliberately not wired into `sector_scoring.py`'s live overheat-risk formula (governance rule #9)
- `[x]` 36-day cross-reconciliation, basis-mismatch-aware (`src/leaderboard_reconciliation.py`): 40.0% coverage, 0.97% of compared rows exceed the 0.5pp deviation threshold; found+disclosed 3 genuine FinMind zero-price data-corruption rows
- `[x]` Backtest rerun with adjusted prices, old-vs-new headline comparison (backed up old outputs first): headline medians UNCHANGED, adjustment mechanism verified genuinely applied via event-level diff (2/53 events changed)
- `[x]` 56 new tests (7 new files + 3 additive), full suite 361/361 passed, 0 regressions; `loop/evidence/test_logs/pytest_m7_run_log.txt`
- `[x]` `docs/Milestone_7_Pitfall_Pack_Report.md` + loop 4-file sync
- `[ ]` Adjustment factor coverage gap (374/890 stocks still UNADJUSTED) — future session should retry `scripts/fetch_price_adjustments.py` once FinMind's rate limit clears; investigate the HTTP 403 failure mode this fetcher's rate-limit detector doesn't currently special-case
- `[ ]` Disposition/attention historical per-event lookup — none of the 5 endpoints support a historical date-range query; the current 41-stock list is same-day-only, applied uniformly across all 53 historical backtest events
- `[ ]` Limit-up history activation decision — dataset is built and persisted (observe-only); a future milestone should explicitly decide whether/how to wire it into `sector_scoring.py`'s overheat-risk sub-factors

## [x] Milestone 8: 修復批次小項包 (Small-fix Batch) (Implemented by maker, pending independent verifier gate)
- `[x]` Fix `run_daily.py` empty-market fallback `KeyError('market_type')` — guarded column existence check before indexing, falls through to pre-existing `BLOCKED_MISSING_MARKET`; `tests/regression/test_run_daily_empty_market_crash.py` reasserted (explicitly authorized this milestone)
- `[x]` `load_excel_leaderboard` hardcoded path made configurable via `config/default.yaml`'s new `reconciliation.leaderboard_dir` (default = old hardcoded path, behavior-neutral); missing dir now logs+skips instead of relying on glob-returns-empty; 5 new tests
- `[x]` `scripts/backfill_status.py` (new): direct-disk-scan progress truth tool, counts `finmind_<stock_id>.json` per category against the live trading-universe row count; `--json`/human output; 8 new tests (tmp_path fixtures only, never touches real data/)
- `[x]` First-ever `coverage` measurement: package installed (`requirements.txt` dev-only annotation), full suite run under coverage, `loop/evidence/test_logs/coverage_first_measurement.txt` — core `src/` 86%, whole project 80%, both meet spec §28.1's gates on this first measurement; no gate wired up, no test changed to chase the number
- `[x]` Governance registration: PID 9836 (current drip process) lineage documented in `loop/PROJECT_STATE.md`; `loop/KNOWN_ISSUES.md` items for the KeyError and leaderboard path moved to Resolved; backfill_status.py established as the source of truth over any receipt file
- `[x]` 13 new tests, full suite 374/374 passed, 0 regressions (net of 1 flipped regression-test assertion); `loop/evidence/test_logs/pytest_m8_run_log.txt`
- `[x]` `docs/Milestone_8_Smallfix_Report.md` + loop 4-file sync
- `[ ]` Institutional/margin backfill still far behind OHLCV (out of this milestone's scope — data acquisition, not a code fix); see `loop/KNOWN_ISSUES.md` #1
- `[ ]` Signal-detector threshold calibration, backtest headline — unchanged this milestone (out of scope, governance rule #9)

## [x] Milestone 9: Margin Wiring + Threshold Calibration (implemented; see M9 acceptance report)
- `[x]` Official margin-history bridge consumed by the live pipeline; real coverage verified at 1,831 stocks/day instead of 2.
- `[x]` Rolling-quantile calibration for the three in-scope thresholds, opt-in and leakage-tested; no future rows consumed.
- `[x]` DQ gate repaired before this M10 run; both calibrated and uncalibrated 62-day pipelines now reach 62/62.
- `[x]` M9's measurement ceiling recorded in `docs/Milestone_9_Calibration_Backtest_Report.md`; signal grading selectivity intentionally deferred to M10.

## [x] Milestone 10: Signal Detector Selectivity (2026-07-22)
- `[x]` Replace generic C-grade fallback with explicit trigger/core/breadth/veto policy; unevaluable never counts as passed.
- `[x]` Preserve UAT-04 hard gate (`MIN_UP_STOCKS_FOR_SECTOR_SIGNAL=2`) and cap single-stock moves at C/無訊號.
- `[x]` Require continued-momentum core rules 1 and 4; retain optional unevaluable rule 5/6 as degraded confidence.
- `[x]` Mirror `min_core_passed_for_b=3` and `min_breadth_core_passed_for_b=1` as `PLACEHOLDER - UNCALIBRATED` in YAML/runtime defaults.
- `[x]` Add seven selectivity boundary tests; targeted 25/25 and full 463/463 pass.
- `[x]` Rerun full 62-day event study in both modes: 62/62 success, events 495/631, zero cold-start events; report at `docs/Milestone_10_Signal_Selectivity_Report.md`.
- `[x]` Phase 1 paired calibration audit: all 2,857 sector-days aligned; event overlap 264, uncalibrated-only 231, calibrated-only 367; shared realized-event delta = 0. Evidence tool and JSON/Markdown output under `Quant-Agent/_workbench/out/moneyflow_62d_backtest_20260722/`.
- `[x]` Additive audit tests: 4 new tests; full suite after tool addition 467/467.
- `[x]` Phase 2 frozen-parameter OOS availability gate executed: `INSUFFICIENT_OOS_DATA` (only 2026-07-20 post-training, 0 mature dates); existing 7/20 outputs are date-presence evidence only and require a frozen-M10 rerun before measurement. Receipt under `Quant-Agent/_workbench/out/moneyflow_62d_backtest_20260722/frozen_oos_validation_receipt.json`.
- `[ ]` Phase 2 performance evaluation after at least 20 mature post-training dates; no production activation until then.
- `[ ]` Research-readiness decision: C-grade still trails momentum; A/B lack realized samples, so no trading activation.
- [x] **M11 auto-backfill late official data (2026-07-22)** — implemented and verified
  with 12 auto-backfill tests, 4 historical-recovery tests, and full 487/487 regression
  suite. Manual `daily_run.bat` now persists the requested TPEx historical OHLCV day
  and generates the 2026-07-21 report; 2026-07-22 remains DEFERRED_NOT_READY. See
  `docs/Auto_Backfill_Late_Data_Report_20260722.md`.
- [ ] Extend historical correction to TPEx institutional/index only if a separate
  official date-addressable source is approved; keep DATE_MISMATCH fail-closed.
