# Project State

> 2026-07-29 Batch 6 update: G1/G2/G3/G5 are complete in the read-only
> diagnostic; G4 made its single permitted TWSE request, failed with a PowerShell
> `NullReferenceException`, and was not retried. No 7/20 TAIEX snapshot was added.
> `market_1d` is no longer constant (35,142 rows, 55 unique values). The executable
> next-open headline remains **「樣本不足，不可裁決」**: 10-day D10-D1 +0.466pp,
> Spearman 0.079; its daily spread is +2.071%, Newey-West t=1.8166, n=43, positive
> on 72.1% of days. A separate close-to-close diagnostic is much stronger
> (Spearman 0.915, D10-D1 +1.533pp, t=2.9324) but includes the overnight gap and is
> not tradable after next-open entry. Wide-universe dates are 3/1/0/0/0 at
> 1/3/5/10/20d, and score Top-10 still trails volume Top-10 at 5/10/20d.
> Narrow-horizon unadjusted share is 2,224/23,938 = 9.29%. Full suite **523
> passed**. Protected/raw/processed/output manifests are unchanged; no commit.
> Evidence: `Quant-Agent/_workbench/out/stock_score_diagnostic_2026-07-29/REPORT.md`
> and `loop/evidence/test_logs/pytest_batch6_run_log.txt`.

> 2026-07-28 Batch 5 update: F1–F5 are fixed in the read-only diagnostic only.
> The all-market median now gates breadth on each return date; TAIEX combines
> FinMind with date-guarded official snapshots through 2026-07-24; stock paths
> reject missing pre-signal, T+1, and holding-period bars; OHLCV merges FinMind
> plus both TPEx schemas with official priority; and close<=0 is removed at read
> time. Full output has 39,008 FULL stock-days, `gross_10d` max 1.0357 (was
> 4.4144), and no <=-90% observations. The honest headline remains **「樣本不足，
> 不可裁決」**: only 4/2/0/0/0 wide-universe dates are mature at 1/3/5/10/20d.
> Score Top-10 trails volume Top-10 at every tested holding period (5d
> 1.74% vs 5.27%; 10d 10.43% vs 13.66%; 20d 13.54% vs 21.71%).
> Protected code/data manifests are unchanged; no network or commit. Final suite
> **520 passed**. Evidence: `Quant-Agent/_workbench/out/stock_score_diagnostic_2026-07-28/REPORT.md`
> and `loop/evidence/test_logs/pytest_batch5_run_log.txt`.

> 2026-07-28 Batch 4 update: The read-only stock-score diagnostic now uses only
> on-disk TWSE/TPEx snapshots (67 dates through 2026-07-24), with no fetcher import
> or network request. It produced 40,599 panel stock-days and **0**
> `gross_10d <= -0.9` observations after zero-close bars became null. The FULL-only
> headline is **「樣本不足，不可裁決」**: 10-day D10-D1 +0.320pp, Spearman 0.091,
> minimum decile n 2,151 (<10,000), minimum daily decile n 48 (<50), and 39 qualifying
> days (<40). Every 10/20d wide-universe maturity count is zero; no short horizon was
> substituted. `data/processed`, `outputs`, and official source-snapshot hashes/mtimes
> are unchanged; no weights or production modules changed. Evidence:
> `Quant-Agent/_workbench/out/stock_score_diagnostic_2026-07-28/REPORT.md`; final suite
> **511 passed** (`loop/evidence/test_logs/pytest_batch4_run_log.txt`).

## Current Position

- **2026-07-28 [STOCK-SCORE DIAGNOSTIC — BLOCKED BY DATA-PREMISE MISMATCH]**:
  Read-only diagnostic script and 8 unit tests are complete; it produced all four
  tables from local snapshots and left sampled `data/processed` and `outputs` SHA-256
  values unchanged.  The rank rule is positive (10-day D10-D1 **+1.206pp**,
  Spearman **0.697**), but this is **not acceptance-ready**: every one of the 68
  `stock_scored` snapshots actually contains only **568** scoreable stocks (not the
  task's assumed ~1,950), so each decile has only 2,917–2,964 mature observations
  (<10,000 requirement).  10-day IC has volume +8.77% (NW t=2.19) and sector +4.22%
  (t=1.88).  The best Top-10/10-day portfolio is net +22.51% (vs momentum +13.94%
  and random +4.62%) but loses to the required all-market-median reference (+118.81%);
  FULL-only deciles fail (rho=.079), while DEGRADED/LOW has only 9 dates.
  Do not tune or activate weights: repair/verify the stock-score universe first.
  Evidence: `Quant-Agent/_workbench/out/stock_score_diagnostic_2026-07-28/REPORT.md`.
- **2026-07-28 [DAILY-REPORT-FIELD D/E/F COMPLETE]**: Added a fail-open regression
  test for both observe-ranking build and write failures: the core run remains SUCCESS,
  produces the Excel, excludes the absent observe JSON from its audit, and records the
  non-fatal error. Mirrored the existing, uncalibrated observe display values in config
  (`ranking_depth=300`, `sector_top_n=5`) without changing their static fallback or any
  signal behavior. The M3 real-snapshot E2E now isolates both data and output under
  pytest temp paths; two runs passed and the real 2026-07-16 workbook remained byte
  unchanged (SHA-256 `eb1ddc66287a3d242d54adb67c21ecbd65142708f44b5d15624d96615e19fb72`).
  Full suite: **494 passed**; receipt
  `loop/evidence/test_logs/pytest_secondbatch_run_log.txt`. The separate external
  verification blocker below remains unchanged.
- **2026-07-27 [DAILY-REPORT-FIELD BLOCKED — external verification contract]**:
  Packages A and C are implemented and verified: the daily runner blocks low market
  coverage against recent successful-day medians, parses MI_INDEX's Chinese date
  field, skips the entire fetch atom for past dates, and writes the ranking appendix
  as observe-only data. Full suite: **493 passed**. Package B recovered the official
  TWSE MI_INDEX 2026-07-20 snapshot (1,371 rows; payload SHA-256
  `001380ed389f3dbce64358da3aa9a7e204dbfe79a0f3533383d915da35167f4d`; 2330 close
  2320), but the required independent official `STOCK_DAY?date=20260720&stockNo=2330`
  check returned 2026-07-27 data instead, ignoring the requested date. The pre-existing
  7/20 audit therefore remains `SUCCESS` with `price_source_twse=finmind_fallback` and
  130 TWSE rows; the pipeline was deliberately not rerun or relabelled as official.
  This is a hard external-data verification blocker, not a reason to fabricate
  confirmation. See `.ai/tasks/TASK-daily-report-field.md` Execution Results.
- **2026-07-22 [M11 MANUAL CORRECTION PERSISTENCE COMPLETE]**: Re-running the exact
  `scripts/daily_run.bat` now recovers TPEx 2026-07-21 OHLCV through the official
  date-addressable `afterTrading/dailyQuotes` action, verifies the self-reported date,
  writes 10,072 rows to the normal raw/bridge paths, and generates
  `outputs/daily/MoneyFlow_Rotation_2026-07-21.xlsx` (batch exit 0, audit `SUCCESS`).
  2026-07-22 remains `DEFERRED_NOT_READY` until the official readiness probe advances.
  Four new fail-closed tests plus the full suite are green: **487 passed**. TPEx
  institutional/index historical recovery remains a separate limitation; no signal,
  calibration, backtest, or DQ-gate core was changed.
- **2026-07-22 [M10 Phase 2 OOS AVAILABILITY GATE COMPLETE]**: frozen M10 parameters
  were checked against dates strictly after 2026-07-17. Only 2026-07-20 exists; there are
  0 dates with the required 10 subsequent scored dates, so the result is
  **`INSUFFICIENT_OOS_DATA`**, not a fabricated performance result. The candidate date's
  receipt shows DQ 70.0, 41 sectors, 997 stocks, TWSE FinMind fallback and TPEx official
  price source. Existing 7/20 signal files are date-presence evidence only and must be
  regenerated with frozen M10 settings before any performance measurement. OOS performance
  remains pending new dates; no production activation.
- **2026-07-22 [M10 Phase 1 配對校準審計 COMPLETE]**: 先建立計畫
  `Quant-Agent/_workbench/plans/PLAN_moneyflow_paired_calibration_oos_20260722.md`，再新增
  evidence-only pairing tool，不改 production backtester。2,857 個族群日全部一對一對齊；
  704 列 signal type 改變；事件交集 264、未校準獨有 231、校準獨有 367。228 個已實現
  交集事件的配對報酬差為 0，證明兩模式 aggregate 差異主要是事件選擇集合不同，不能
  直接宣稱校準改善或傷害預測力。配對工具測試 4/4；加上它後完整專案測試 **467 passed**。
  Phase 2（固定設定的樣本外 forward test）尚未開始。
- **2026-07-22 [M10 Signal Selectivity GATE APPROVED (PASS-WITH-CONCERNS) by Claude verifier]**: Root-cause selectivity fix worked and is real (main-conversation spot-checked selectivity_backtest_summary.json directly, not just subagent report). **First statistically-meaningful readings in project history**: cold-start-day events 46->0, events now spread across 61 trade dates (max 14/day), 無訊號 ratio ~0%->78.9%, and C級 now has n_realized=378 (sample_sufficient=TRUE — first bucket ever to cross n>=30). Backtester/benchmarks confirmed zero-diff (methodology untouched); UAT-04 single-stock guard preserved; veto confirmed firing via constructed case. 463 tests pass. **Honest headline**: C級 median 10d excess improved dramatically -11%->-2.79% but STILL loses to momentum baseline (-1.23%); B級 5 events but n_realized=0 (unmeasurable); A級 still zero events. **Notable (verifier's own read of the data): 續漲訊號 bucket is +0.52% median, 56.7% win rate, n=30 — the FIRST positive-excess bucket the project has ever produced, though barely at the n>=30 line and not yet cross-validated.** MAJORs (non-blocking): (1) report omitted a run_daily.py DQ-penalty change that did ship this session (verified pre-existing/necessary, not a data-chasing hack, but report's "zero DQ change" claim is imprecise); (2) report lacks the required old->new test-assertion mapping (verifier checked manually, no assertion silently weakened). Next: with C級 finally at n>=30 and 續漲 showing first positive signal, the calibration effect can FINALLY be measured — rerun calibrated-vs-uncalibrated on this new selective signal set to see if quantile calibration now moves the needle.
- **2026-07-22 [M10 Signal Detector Selectivity IMPLEMENTED, EVIDENCE COMPLETE]**:
  Replaced the old generic C-grade fallback with explicit trigger/core/breadth/veto
  grading in `src/signal_detector.py`; unevaluable conditions never count as passes,
  and UAT-04 remains `MIN_UP_STOCKS_FOR_SECTOR_SIGNAL=2`. Added 7 selectivity tests,
  updated config/documentation, and kept the backtester, calibration module, DQ gate,
  and night-run path untouched. Full suite is **463 passed**; targeted detector suite
  is **25 passed**. With the repaired DQ gate, both calibrated and uncalibrated 62-day
  runs succeed **62/62**. Signal rows now include 2,254/2,055 `無訊號` (uncalibrated/
  calibrated) instead of the old all-B/C distribution; independent events are 495/631,
  spread across 61 dates with zero cold-start events. Calibration therefore becomes
  measurable (704 daily signal-type changes and non-identical event CSVs), but C-grade
  10-day medians remain -2.7852%/-2.8833% versus the -1.2338% momentum baseline, while
  A/B have no realized samples. See `docs/Milestone_10_Signal_Selectivity_Report.md`.
- **2026-07-22 [Codex 62-day full backtest GATE APPROVED by Claude verifier]**: DQ-basis fix (prev-close-to-close reconciliation + 30-row/10% materiality gate) let all 62/62 days pass DQ (was 28/62). Independent adversarial re-verification (spot-checked by main conversation, not just subagent report): both event CSVs' SHA-256 hand-computed = f2f652...667e (matches claim, byte-identical calibrated vs uncalibrated); uncalibrated/data/processed holds real 62 sector_scored_*.csv spanning 2026-04-20..2026-07-17 (NOT the prior 28-day set — impostor hypothesis disproven); 53 events distribute 46 on cold-start day 2026-04-20 + 7 on final day 2026-07-17 (confirms structural event-extraction ceiling is real, matching M9). 456 tests pass. **Substantive result unchanged and honest**: calibration changed 244 sector-day grades but every measurable event still fires on cold-start/final day, so B級 -11.28% (n=24) / C級 -10.99% (n=22) both still lose to momentum baseline (-1.23%), both n<30. NOT Research Ready, NOT tradable. Open MAJORs carried from basis-fix review (not blocking, logged): (1) 30-row/10% gate has curve-fit smell (11 warning days all 1.04-7.41% deviation, just under the 10% bar); (2) <30 comparable rows never penalizes even at 100% deviation. Real remaining ceiling for measuring calibration value: the M5c first-occurrence event rule + a signal detector that grades every sector every single day (never 無訊號), collapsing all independent events onto day 1. That grading-logic interaction — not data or calibration — is the next thing to fix if the system is ever to show whether calibration helps.
- **2026-07-21 [M9 Threshold Calibration GATE APPROVED by Claude verifier]**: Independent rerun 451/451 passed. Spot-checked: FinMind OHLCV disk count = 1963/1963 (100%, matches report's "was 29% at M5c" claim); `diff` of the two backtest event CSVs confirmed zero differences (byte-identical, matching report's "no change" headline); backtest_summary JSON values (median -11.28%/-10.99%, n=53, both lose vs momentum baseline -0.39%) cross-checked exact match against report text. **Honest negative/neutral result accepted as-is**: calibration mechanism is real and tested (84/1294 sector-days changed grade, leakage-free by 4 dedicated tests) but this round's 28-day sample structurally cannot show whether it helps predictive value (every measurable event fires on cold-start day or all-untradable day, per the existing M5c first-occurrence event rule). A genuine new regression was found and correctly left unfixed (out of scope): BLOCKED_LOW_DQ jumped 2/62->34/62 because FinMind OHLCV reaching 100% coverage now triggers the pre-existing (M3-disclosed) leaderboard reconciliation basis-mismatch on most days. Verdict unchanged: NOT Research Ready. Recommended next-session priority (verifier's addition, not yet actioned): decide whether to fix the reconciliation basis mismatch (§2 of the M9 report) BEFORE attempting another calibration round, since it currently blocks more than half of all trading days from entering any measurement at all.
- **2026-07-21 [M9 Threshold Calibration + Backtest Rerun IMPLEMENTED, PENDING GATE]**:
  Maker delivered M9: (1) wired the previously-orphaned `twse_official_<date>.json`/
  `tpex_official_<date>.json` margin history (backfilled last session, 63 trading days,
  never actually consumed by the pipeline until now) into `run_pipeline` via new
  `scripts/prepare_official_margin_history_snapshot.py` -- verified real, not symbolic
  (`clean_margin_data` output went from 2 to 1,831 stocks/day). (2) Built
  `src/threshold_calibration.py`: per-sector rolling-quantile calibration (strictly
  prior history only, verified leak-free by 4 dedicated tests) for 3 of 17 new-gainer/
  continued-momentum thresholds (`new_gainer.min_score`/`prev_score_max`,
  `continued_momentum.min_score`), wired as an opt-in `SignalDetector(use_calibrated_
  thresholds=True, df_sector_history=...)` parameter -- default False preserves exact
  pre-M9 behavior for every existing caller. (3) **Real regression found**: rerunning
  the 62-day historical pipeline with the newly-wired margin data dropped SUCCESS days
  from 60/62 (M5c-prep) to 28/62 (34 newly BLOCKED_LOW_DQ) -- root-caused to
  `reconcile_with_leaderboard`'s pre-existing (disclosed since M3) open-to-close vs
  prev-close basis mismatch now firing on most days because FinMind OHLCV coverage
  reached 100% (was 29% at M5c time), so leaderboard tickers that previously found no
  match now do. Not caused by this session's margin work directly (`calculate_quality_
  score` never reads `df_margin`); disclosed, not silently fixed (out of authorized
  scope). (4) Backtest rerun on an isolated, clean 28-date subset (same dates
  succeeded both calibrated and uncalibrated): **headline is BYTE-IDENTICAL before vs
  after calibration** (B級 median -11.28% n=27, C級 -10.99% n=26, both still lose to
  -0.39% momentum baseline, both still n<30) -- root-caused directly (not assumed):
  every one of the 53 independent events first-fires on either the cold-start day
  (2026-04-20, zero prior history by construction) or 2026-07-17 (all UNTRADABLE), so
  the already-accepted "first occurrence only" event-extraction rule structurally
  cannot show calibration's effect on this dataset, even though calibration DID
  genuinely change 84/1,294 sector-day grades (144->228 B-grade rows) starting once
  enough rolling history existed (2026-05-05 onward). Full suite: 451 passed (419
  baseline + 7 margin-bridge + 17 threshold-calibration + 4 leakage + 4 signal-detector-
  calibration). See `docs/Milestone_9_Calibration_Backtest_Report.md` for full detail,
  honest headline table, and known-limitations disclosure.
- **2026-07-21 [Margin History Backfill GATE APPROVED by Claude verifier]**: Independent rerun 419/419 passed. Disk-verified: 63 twse_official_*.json + 63 tpex_official_*.json in data/raw/margin/ (63+29 non-trading days = 92 calendar days, exact match). Sample 2026-07-14 files confirmed real HTTP 200 responses with matching requested date (TWSE 1283 rows via www.twse.com.tw legacy endpoint, TPEx 913 rows via www.tpex.org.tw legacy endpoint with ROC-slash date format). Zero FinMind quota consumed -- both endpoints are free official sources found via two rounds of dry-run verification. This closes the last major data gap before threshold quantile calibration can begin (OHLCV ~96%, institutional ~88%+, margin now 63 trading days full-market coverage via this new source alongside the separate 2/1963 FinMind per-stock angle).
- **2026-07-21 [Margin History Backfill via official free endpoints]**: FinMind's
  free-tier quota exhausted; replaced FinMind for margin/short-sale HISTORY (not
  current-day, which is untouched) with two free official TWSE/TPEx legacy report
  endpoints that genuinely honor a date parameter (`src/twse_tpex_margin_history.py`,
  `scripts/backfill_margin_history.py`). Full real backfill executed for
  2026-04-20..2026-07-20: **63/63 trading days saved on both TWSE and TPEx, 29
  non-trading days correctly skipped, 0 failures**. Found and fixed a real bug during
  the live run (TWSE's non-trading-day response has no `date`/`tables` field at all;
  was initially misclassified as `DATE_MISMATCH` failure instead of a benign
  non-trading day — fixed, regression-tested). New files use distinct prefixes
  (`twse_official_<date>.json`/`tpex_official_<date>.json`) — zero existing FinMind or
  legacy `margin_<date>.json` files overwritten; `fetch_twse_margin_all`/
  `fetch_tpex_margin_all` (current-day OpenAPI fetchers) untouched; `clean_margin_data`
  untouched (both transform functions target its existing expected format exactly).
  `scripts/backfill_status.py` gained an additive `margin_date_sources` section
  (per-date coverage, distinct from the pre-existing per-stock FinMind coverage
  section). Full suite: 419 passed (376 baseline + 43 new). See
  `docs/Margin_History_Backfill_Report.md` for endpoint format details, live-probe
  evidence, and full before/after coverage numbers. Not yet wired into any daily
  pipeline read path — this session was backfill + tooling only, per instruction
  (governance rule #8: pipeline/scheduling changes need a separate proposal+approval).
- **2026-07-19 [M8 GATE APPROVED by Claude verifier]**: Independent rerun 374/374 passed. Five small fixes verified: run_daily empty-market clean BLOCKED (regression test flipped to assert fixed behavior), leaderboard_dir config-driven (default unchanged), backfill_status.py truth tool live (isolated run exit=0; an earlier 255 was verifier's own pipe-truncation artifact, not a defect), first coverage measurement recorded (src 86%/overall 80%), drip PID 9836 governance-registered. Backfill live status at gate time: ohlcv 95.62%, institutional 5.96% and climbing (drip entered phase 2), margin 0.1%. Remaining open chain: institutional/margin data fill -> threshold quantile calibration -> event-study rerun.
- **2026-07-19 [M8 IMPLEMENTED, PENDING GATE]**: Small-fix batch (5 items) from `docs/open_issues_audit_2026-07-19.md`. (1) `scripts/run_daily.py`'s empty-market fallback now guards `"market_type" not in df_prices.columns` before indexing, so both markets empty falls through to the pre-existing `BLOCKED_MISSING_MARKET` branch instead of raising `KeyError` — `tests/regression/test_run_daily_empty_market_crash.py` flipped from asserting the crash to asserting the clean blocked status (test renamed `test_both_markets_empty_returns_blocked_missing_market`). (2) `load_excel_leaderboard`'s hardcoded `C:/Workspace_CN/Quant-Agent` glob root is now `reconciliation.leaderboard_dir` in `config/default.yaml` (default value unchanged from the old hardcoded path — behavior-neutral); missing directory now logs and skips reconciliation instead of relying on glob returning empty. (3) New `scripts/backfill_status.py`: direct disk-scan of `finmind_<stock_id>.json` counts per category (ohlcv/institutional/margin) against the live `stock_industry_mapping.xlsx` universe size, strict-JSON (`--json`) or human table output — built because the existing `finmind_backfill_summary.json` receipt is a stale single-run snapshot, not cumulative progress (see KNOWN_ISSUES #7 below). (4) `coverage` package installed in `.venv`, first-ever measurement taken: core `src/` 86%, whole project (`src/`+`scripts/`) 80% — both meet spec §28.1's gates (85%/75%) on this first measurement; no CI gate wired up, measurement only. (5) This governance registration itself. Full suite: 374 passed (361 baseline + 5 leaderboard-config tests + 8 backfill_status tests, net of the 1 regression-test assertion flip). See `docs/Milestone_8_Smallfix_Report.md`.
- **Current Milestone**: `M8 - 修復批次小項包 (Small-fix Batch)`
- **Prior (M7) status, unchanged this milestone**: `M7 GATE APPROVED by Claude verifier`. Independent rerun 361/361 passed; all 6 claimed M7 artifacts + 36 copied leaderboard files verified on disk. Ex-dividend adjustment via TaiwanStockDividendResult fallback, 58% factor coverage disclosed; disposition/attention list live (41 stocks, same-day-only limitation disclosed); 36-day leaderboard reconciliation 0.97% rows over 0.5pp threshold; limit-up history kept observe-only per rule #9; backtest rerun headline unchanged.
- **Prior (M6) status, unchanged this milestone**: `M6 GATE APPROVED — ALL MILESTONES (M0-M6) COMPLETE`. FINAL VERDICT (verifier concurs with maker): Software Ready (candidate) — NOT Research Ready, NOT Trading Decision Support Ready.
- **FinMind drip backfill — PID lineage**: PID 2924 (launched M5c) completed and exited cleanly 2026-07-18 20:00:44 at 890/1963 OHLCV (45.3%). **A new drip process, PID 9836, was found alive during the 2026-07-19 audit** (`docs/open_issues_audit_2026-07-19.md` #23) — started 2026-07-18 22:17, `--sleep-between 30`, log at `outputs/logs/finmind_drip_3.log` — with no prior PROJECT_STATE.md record of who started it or why (a real governance gap the audit flagged; this entry closes that gap). **Live coverage counted via `scripts/backfill_status.py` at time of this M8 session (2026-07-19 09:36, NOT a receipt file — see KNOWN_ISSUES #7)**: ohlcv 1877/1963 (95.62%), institutional 97/1963 (4.94%, up from the audit's 26/1963 — the drip appears to now be advancing institutional too), margin 2/1963 (0.1%, unchanged). **This M8 session did not touch, restart, or interact with PID 9836 or its data/raw/ output files** — read-only observation only, per the task's explicit instruction. **Going forward, treat `scripts/backfill_status.py`'s live output as the source of truth for backfill progress, not any receipt JSON or a number written into a past PROJECT_STATE.md entry** — those go stale the moment the drip writes its next file.
- **M7's own new fetches** (dividend events for adjustment factors, disposition/attention snapshot) used distinct filename prefixes (`finmind_div_*`, `<endpoint>_<date>.json` under `data/raw/disposition/`) throughout and never competed with or overwrote FinMind OHLCV files, per that milestone's explicit instruction.

## Metric Summary
- **M7 Test Pass Rate**: 100% (361 tests passed: 305 pre-existing M0-M6 tests + 56 new M7 tests across 7 new test files + 3 additive tests in `tests/unit/test_report_generator.py`; see `loop/evidence/test_logs/pytest_m7_run_log.txt`)
- **M7 Ex-Dividend Adjustment**: direct FinMind adjusted-price dataset confirmed UNAVAILABLE (6 candidate names, all HTTP 400/422, live dry-run receipt in `loop/evidence/fetch_receipts/finmind_adjusted_price_probe_2026-07-18.json`). Fallback path (`TaiwanStockDividendResult`, verified live) used instead — `src/price_adjuster.py` computes backward-adjustment factors. Real fetch: 516/890 FinMind-backfilled stocks (58%) before hitting FinMind's rate limit; 208 of those 516 had a real ex-dividend event in the 2026-04-20..07-17 window. Backtest rerun with `use_adjusted_prices=true`: headline medians unchanged (B -11.28% n=27, C -10.41% n=19) — only 2/53 events' forward windows crossed an ex-div date in this sample, adjustment verified genuinely applied via direct event-level diff, effect just happened to be small for this dataset. 42.0% of the 890-stock universe remains UNADJUSTED this run (tagged, never blended).
- **M7 Disposition/Attention Stocks**: 5 real TWSE/TPEx endpoints (`/announcement/punish`, `/announcement/notice`, 3 TPEx warning endpoints) live-fetched 2026-07-18: 41 unique stocks (12 處置股 disposition, 29 注意股 attention). Wired into daily report's 個股優先排序 sheet (`disposition_flag` column) and `Backtester.run_event_study`'s pre-existing `disposition_stock_ids` parameter (previously always empty per M5c's own disclosed gap) — disclosed as a same-day-only snapshot (these endpoints have no historical date-range query parameter).
- **M7 Leaderboard Integration**: 36/36 `Report_YYYYMMDD.xlsx` files (2026-05-15..07-16, copied from read-only `Quant-Agent/台股漲幅排行/` source into `data/raw/reports/`) parsed cleanly. Limit-up history (proxy, ≥9.5% daily return): 2,502 stock-days across 36 sample dates, max consecutive streak 10 days (stock 8291). Persisted as an OBSERVE-ONLY dataset — NOT wired into `sector_scoring.py`'s live overheat-risk formula (already-accepted M2 weight contract, untouched per governance rule #9). 36-day reconciliation (basis-aligned: leaderboard's prev-close-basis 漲跌幅 vs an independently-computed FinMind prev-close return, NOT the system's own open-to-close `daily_return`): 40.0% coverage (4,318/10,800 rows, limited by FinMind OHLCV backfill progress), 0.97% of compared rows exceed the 0.5pp deviation threshold. Found and disclosed 3 genuine FinMind zero-price data-corruption rows (stocks 2321/2941/2073, 2026-06-08) during reconciliation.
- **M7 Untouched modules** (governance rule #9 / task instruction, zero lines changed): `src/backtester.py`, `src/benchmarks.py`, `src/sector_scoring.py`.
- **M6 Unit/Integration Test Pass Rate**: 100% (305 tests passed: 291 pre-existing M0-M5c tests + 12 new orchestrator tests in `tests/integration/test_daily_orchestrator.py` + 2 new regression tests in `tests/regression/test_run_daily_empty_market_crash.py`; see `loop/evidence/test_logs/pytest_m6_run_log.txt`)
- **M6 orchestrator real runs**: executed twice against live TWSE/TPEx endpoints. (1) 2026-07-18 (today): `final_status=EXCEPTION, exit_code=3` — official OHLCV endpoints still served 2026-07-17's data (DATE_MISMATCH correctly caught by M4's guard), which cascaded into a pre-existing `run_daily.py::run_pipeline` bug (`KeyError: 'market_type'` instead of clean `BLOCKED_MISSING_MARKET`, found not fixed — already-accepted code, out of scope). No data corrupted, no false report produced (verified via file timestamps). (2) 2026-07-17 (rerun): `final_status=SUCCESS, exit_code=0`, DQ 91.0, 53 signal events appended. Rerun a second time on the same date: byte-identical `sector_scored_2026-07-17.csv`/`stock_scored_2026-07-17.csv` (spec §28.1 reproducibility self-check, actually executed).
- **M6 FinMind drip backfill correction**: PID 2924 re-verified multiple times (15:33 launch through 18:38+) and found CONTINUOUSLY ALIVE (contradicting the prior "found dead" note below) — OHLCV coverage progressed 571/1963 -> 802/1963 (40.9%) during this session. NOT restarted (healthy, progressing process; restarting would be destructive without benefit).
- **Unit Test Pass Rate (M5c)**: 100% (291 tests passed: 249 pre-existing M0-M5c-prep tests + 42 new M5c tests — 30 in `tests/unit/test_backtester.py`, 9 in `tests/unit/test_benchmarks.py`, 3 in `tests/leakage/test_backtester_no_future_function.py`; see `loop/evidence/test_logs/pytest_m5c_run_log.txt`)
- **M5c Event-Study Backtest Core**: `src/backtester.py` fully rewritten (event extraction per SPEC 19.6/SPEC_ADDENDUM B-3.1 first-signal-only rule, T+1-open entry, limit-up lockout both exclude/postpone accountings, sector-median forward returns, cost model). New `src/benchmarks.py` (momentum-extension + random-sector-bootstrap baselines per SPEC_ADDENDUM A-3). New `scripts/run_backtest.py` orchestrator producing `outputs/backtests/backtest_report_<date>.xlsx` + CSV/JSON. Real 60-day run: 53 independent events (47 primary + 6 theme sector-type), headline 10-day net excess return B級 median -11.28% (n=27), C級 median -10.41% (n=19), both UNDERPERFORM the momentum baseline (-0.39%) -- SPEC_ADDENDUM A-3.3's own rule means this is reported as "無增量價值證據" for this window, not softened. Both tiers n<30 (sample insufficient per project's own rubric); 0 A-grade/續漲 events occurred. Conclusion level: 初步研究讀數 only.
- **M5c real-data finding**: the real 60-day/2,765-row signal dataset has ZERO `無訊號`/`無效` rows anywhere -- every scored sector carries a graded B/C signal every day it appears, which under the correct first-occurrence event rule collapses independent events to 53 total (46 concentrated on the window's first day, a cold-start artifact; 7 on the last day, all UNTRADABLE for lack of forward data). This is a genuine finding about the signal detector's current uncalibrated-threshold behavior on real data, not an event-extraction bug (6 dedicated unit tests confirm the extraction logic itself is correct).
- **M5c UNTRADABLE accounting**: 46 TRADABLE / 7 UNTRADABLE (both exclude and postpone conventions identical). All 7 are FinMind OHLCV coverage gaps (member stocks with zero history on disk), not limit-up locks -- zero real limit-up lockouts were exercised by this particular 60-day sample (the lockout logic itself is unit-tested, just not exercised by real data this round).
- **M5c performance fix (correctness-preserving)**: an identity-keyed (`id(df)`) cache was tried first to speed up the N=10,000 bootstrap run (initial attempt exceeded 6+ minutes and was killed), caught as UNSAFE by the test suite itself (4 real failures -- CPython can reuse a freed object's memory address, causing two different small DataFrames to collide on the same cache key and silently return the wrong stock's history), reverted in full before ever touching the real report. Replaced with an explicit caller-owned `index_ohlcv_by_stock()` pre-grouping with no implicit caching; the real N=10,000 run then completed in 2m41.7s with results identical to the pre-optimization (killed) run's earlier smoke-test values, confirming no correctness regression.
- **M5c FinMind drip backfill launched**: `--sleep-between 50` (new additive CLI flag, default `None`=unchanged 1.0s behavior) detached background process, PID 2924, started 2026-07-18 15:33:27, confirmed actually fetching new data (stock 2941 OHLCV saved) not a no-op. Left running unattended per the task's intent; will take many hours to materially close the 571/1963 OHLCV and 26/1963+2/1963 institutional/margin gaps at this rate.
- **M5c-prep Merge Bug Fix**: `scripts/run_daily.py`'s institutional-column merge now drops any stale institutional columns already present on `df_stock_features_today` (carried over via the multi-day CSV concat) before merging in today's fresh values. Directly reproduced pre-fix (day 2's persisted CSV lost its clean `foreign_net_buy` column, splitting into `_x`/`_y` duplicates) and confirmed fixed post-fix via a real 2-consecutive-day hermetic integration test.
- **M5c-prep Mock-File Unshadowing**: `data/raw/ohlcv/prices_2026-07-14/15/16.json` (synthetic demo data shadowing both the official and FinMind bridges) moved to `data/test_fixtures/legacy_mock/`. One dependent test (`test_m2_e2e_pipeline.py`) updated for the new path; the same file also needed an unrelated hermeticity fix (see next line).
- **M5c-prep test_m2_e2e_pipeline.py hermeticity fix**: independently discovered (not caused by the file move — isolation-tested) that this test's mock stock IDs (2330/2317/3017/etc) collide with a real external `Report_20260716.xlsx` leaderboard file `scripts/run_daily.py::load_excel_leaderboard` picks up via its pre-existing M1-documented hardcoded glob path, causing a real reconciliation-deviation `BLOCKED_LOW_DQ`. Fixed by mocking `load_excel_leaderboard` to return empty in this test (same hermeticity pattern as `test_run_daily.py`'s fully-mocked network layer) — test-only change, zero production code touched beyond the one authorized merge-bug fix.
- **M5c-prep FinMind Backfill Resume**: institutional 0->26/1963, margin 0->2/1963 (OHLCV unchanged at 571/1963, deprioritized per instruction this round). New finding: the rate limit is a short (~30-90s) burst-scale throttle, not a clean hourly window as M5b assumed — confirmed by 6+ repeated real resume attempts each netting only single-digit successes before re-402'ing. Session stopped after ~5-6 min per the "don't wait >30min" instruction; receipt `loop/evidence/fetch_receipts/finmind_backfill_summary.json` updated with the full honest attempt log.
- **M5c-prep Historical Batch Pipeline Rerun**: 60/62 days SUCCESS (was 2), 0 EXCEPTION (was 26, merge bug fixed), 2 BLOCKED_LOW_DQ (was 31, now only 2026-07-14/15 — genuinely thin institutional/margin data for those dates, fail-closed correctly), 0 BLOCKED_MISSING_MARKET (was 3, mock-file unshadowing). 2,765 total signal events, 383.94s elapsed. Backups of all pre-rerun processed CSVs/signals/audit JSONs taken before overwrite (`data/processed/_bak_m5c_prep_20260718_143440/` etc).
- **M5b FinMind Backfill (starting point this session)**: OHLCV 571/1963 stocks (29.1%) with full 62-trading-day history each; TAIEX index 100%; TPEx/OTC index UNAVAILABLE (dry-run verified no working series exists on this token, 8 candidate data_ids tried).
- **M5b Chinese Sector Name Conversion**: 1,955/1,955 eligible (non-reviewed) rows converted from raw numeric codes to real FinMind `TaiwanStockInfo` Chinese industry names (100%), 8 manually-reviewed rows protected untouched, raw code preserved in new `sector_code` column. Real 7/17 report re-verified showing Chinese names (e.g. 金融保險/食品工業/紡織纖維) in place of numeric codes.
- **M5b Reconciliation**: 569/571 FinMind-fetched stocks' 2026-07-17 closing price exact-matched (100%, 0 mismatches) against the real official TWSE/TPEx snapshot; stock 2330 individually confirmed exact match on open/high/low/close/volume/turnover. Only 1 date (2026-07-17) has a real official snapshot on disk to reconcile against (disclosed, not the full 3-date ask).
- **M5a Official Mapping Coverage**: 0.41% (8/1974) -> 98.58% (1946/1974) against the real 2026-07-17 trading universe. `industry_code_lookup_status=UNAVAILABLE` (neither TWSE nor TPEx swagger exposes a code->Chinese-name lookup endpoint) -- sector labels for the 1,955 newly-imported stocks are raw numeric codes (e.g. "28", "24"), disclosed not hidden, visible in the real 7/17 report's Dashboard sector-name column.
- **M5a Historical Backfill**: architecturally limited discovery (not a bug) -- of TWSE OHLCV/MI_MARGN/MI_INDEX and ALL TPEx endpoints, zero accept a date query parameter per their cached swagger definitions (verified, not guessed); only TWSE T86 (institutional, legacy RWD endpoint) genuinely honors `date=` (live-confirmed: requested 2026-06-01, payload echoed date=20260601). A new date-consistency guard (`src/data_fetcher.py::extract_payload_date`) now drops any saved payload whose self-reported date doesn't match the requested trade_date, preventing "today mislabeled as history." See acceptance report for the T86 backfill's actual day-by-day success/failure count (constrained this session by a sustained sandbox network outage, not by the guard).
- **M5a Real 7/17 Report**: `outputs/daily/MoneyFlow_Rotation_2026-07-17.xlsx` produced from real fetched data (no synthetic rows). status=SUCCESS, DQ score=91.0 (WARNING), mapping coverage=98.58%, 44 sectors scored, 1974 stocks scored, signal breakdown: 29 sectors B級早期點火, 15 sectors C級個股事件, 0 A/續漲 (no prev_date history available to evaluate day-over-day breakout conditions).
- **M0-M4 baseline** (unchanged this milestone): 134/134 tests passed: 87 pre-existing M0/M1/M2/M3 tests + 46 new M4 unit tests + 1 new M4 integration test
- **Code Coverage**: N/A (Coverage metrics explicitly not required for milestone gate clearance in this project's rubric)
- **E2E Pipe Status**: M3's real-snapshot single-day chain still green; NEW `tests/integration/test_m4_institutional_wiring_e2e.py` runs the same real 2026-07-16 TWSE+TPEx OHLCV/institutional/margin snapshots end-to-end and asserts `foreign_net_buy`/`score_institution` are actually non-null in the persisted `stock_scored_2026-07-16.csv` (closing a pre-existing wiring gap — see Revision Log below)
- **OpenAPI Verification**: unchanged base 6/6 from M1, PLUS 2 new verified index endpoints (TWSE `MI_INDEX`, TPEx `tpex_index`) confirmed against cached swagger definitions
- **Live Network Verification (NEW, M4)**: `--smoke` mode executed live: HTTP 200, 1,371 rows, real schema (`loop/evidence/fetch_receipts/smoke_receipt_2026-07-17.json`). Full single-day fetch for 2026-07-17 executed live: all 8 (category×market) endpoints succeeded with HTTP 200, each verified against its real on-disk `data/raw/<category>/<market>_2026-07-17.json` envelope + sha256 (`loop/evidence/fetch_receipts/fetch_receipt_2026-07-17.json`). This sandboxed dev environment's default network path intermittently DNS-sinkholes/times-out outbound HTTPS; the fetcher's fail-closed retry logic correctly never overwrote a file on failure — see `docs/Milestone_4_Acceptance_Report.md` §5 for the full disclosed investigation.
- **Excel Output verification**: unchanged from M3 (4-sheet schema); M4 does not touch `report_generator.py`

## Revision Logs
- **2026-07-19 [M8 IMPLEMENTED, PENDING GATE]**: Maker delivered M8 (修復批次小項包 /
  Small-fix Batch), 5 items from `docs/open_issues_audit_2026-07-19.md`, authorized
  small-fix scope only (no scoring/threshold/backtest logic touched).
  1. **`scripts/run_daily.py` empty-market `KeyError` fix** (audit #1, P0): guarded
     `"market_type" not in df_prices.columns` before the two `df_prices[...]` filter
     lines, so a zero-column `pd.concat` (both markets empty) now falls through to
     the pre-existing `BLOCKED_MISSING_MARKET` branch instead of raising. Regression
     test `tests/regression/test_run_daily_empty_market_crash.py` updated (function
     renamed, assertion flipped from "raises KeyError" to "returns
     BLOCKED_MISSING_MARKET with 0 row counts") — explicitly authorized by this
     milestone's task instructions.
  2. **`load_excel_leaderboard` configurable path** (audit #5/#12, P1): new
     `reconciliation.leaderboard_dir` key in `config/default.yaml` and
     `ConfigManager.get_defaults()`, default value = the exact pre-M8 hardcoded
     `C:/Workspace_CN/Quant-Agent` path (behavior-neutral for existing runs).
     Missing directory now short-circuits with a log message before the glob even
     runs. 5 new tests in `tests/unit/test_load_excel_leaderboard_config.py`.
  3. **`scripts/backfill_status.py`** (new, audit #22): direct-disk-scan progress
     tool — counts `finmind_<stock_id>.json` per category against the live
     `stock_industry_mapping.xlsx` row count, reports file count/coverage%/
     oldest+newest mtime, `--json` or human table. Built because
     `finmind_backfill_summary.json` is a stale one-time snapshot, not cumulative
     truth. 8 new tests in `tests/unit/test_backfill_status.py` (tmp_path fixtures,
     no real data/ touched).
  4. **First coverage measurement** (audit #10): `coverage` package installed,
     added to `requirements.txt` as dev-only. `loop/evidence/test_logs/
     coverage_first_measurement.txt`: core `src/` 86%, whole project 80% — meets
     spec §28.1's 85%/75% gates on this first measurement. No gate enforced, no
     test changed to chase the number.
  5. **This governance registration**: PID 9836 lineage/config documented above
     (was previously undocumented — audit #23); `KNOWN_ISSUES.md` items #1
     (KeyError) and #5 (leaderboard path) moved to a Resolved section.
  Full suite: **374 passed** (361 baseline + 13 new, net of 1 flipped assertion),
  see `loop/evidence/test_logs/pytest_m8_run_log.txt`. See
  `docs/Milestone_8_Smallfix_Report.md` for the short report.
- **2026-07-18 [M7 IMPLEMENTED, PENDING GATE]**: Maker delivered M7 (避坑補完包 / Pitfall
  Pack): ex-dividend price adjustment, disposition/attention stock fetcher, and 36-day
  user-collected leaderboard integration, plus a full backtest rerun.
  **`src/price_adjuster.py`** (new): direct FinMind "adjusted price" dataset confirmed
  UNAVAILABLE (6 candidates, all HTTP 400/422, live dry-run, never recalled from memory
  — receipt `loop/evidence/fetch_receipts/finmind_adjusted_price_probe_2026-07-18.json`).
  Fallback path used instead: `TaiwanStockDividendResult` (verified live, real
  before_price/after_price ex-dividend reference prices) drives a backward
  (multiplicative) adjustment-factor calculation, compounding across multiple events per
  stock. `scripts/fetch_price_adjustments.py` real-fetched 516/890 FinMind-backfilled
  stocks (58%, hit FinMind's rate limit mid-run — same short burst-scale throttle
  documented in M5b/M5c/M6; a resume attempt ~2min later got a different HTTP 403 failure
  this fetcher's rate-limit detector doesn't special-case, a minor real finding for a
  future session) into `data/reference/price_adjustment_factors.csv` (31,874 rows, 208
  stocks with a real event). New `config/default.yaml` key `backtest.use_adjusted_prices`
  (default true, additive). **`scripts/run_backtest.py`** wired to apply factors before
  the event study (unadjusted stocks tagged, never silently blended; 42.0% of the
  890-stock universe UNADJUSTED this run) — `src/backtester.py`/`src/benchmarks.py`
  themselves remain byte-for-byte unchanged (already-accepted M5c code). Rerun result:
  headline medians UNCHANGED (B級早期點火 -11.28% n=27, C級個股事件 -10.41% n=19, both
  still lose to the -0.39% momentum baseline, both still n<30) — only 2 of 53 real events
  had a forward window crossing an ex-dividend date in this specific sample (verified via
  direct event-by-event diff between old/new `backtest_events_2026-07-18.csv`, confirming
  the adjustment mechanism is genuinely applied, not a no-op). Old backtest outputs
  backed up to `outputs/backtests/_bak_pre_m7/*.bak` before rerun.
  **`src/disposition_fetcher.py`** (new): 5 real endpoints discovered by grepping
  punish/attention/disposition/notice/warning against the cached
  `loop/evidence/raw_samples/{twse,tpex}_swagger.json` (never recalled from memory), all
  live-verified 2026-07-18: TWSE `/announcement/punish` (處置股, 13 raw rows → 12 unique
  stock_id after dedup) and `/announcement/notice` (注意股, correctly filtered the
  live-observed zero-attention-stock sentinel row `Code=""` rather than treating it as a
  real stock), plus 3 TPEx endpoints (`tpex_trading_warning_information`/`_note`,
  `tpex_esb_warning_information`, 28+2+1 rows). A genuine TWSE-server-side mojibake
  defect was found in the punish/notice endpoints' free-text Chinese fields (numeric/
  ASCII fields unaffected) — stored as-is, disclosed, only the unaffected `Code` field
  used downstream. **Today's real consolidated list: 41 unique stocks** (12 disposition,
  29 attention; receipt `loop/evidence/fetch_receipts/disposition_today_list_
  2026-07-18.json`). Wired into **`scripts/run_daily.py`** (new
  `_load_disposition_ids_for_date` helper, disk-read-only, no live network call from
  inside the pipeline — a new `disposition_flag` column on `df_scored_stocks`, "N/A(未
  查核)" for any date without a fetch on disk rather than a fabricated "clean") and
  **`src/report_generator.py`** (new 處置/注意 column on 個股優先排序 sheet only) and
  **`scripts/run_backtest.py`** (`load_disposition_stock_ids` unions every snapshot file
  on disk, passes a real 41-stock set into `Backtester.run_event_study`'s pre-existing,
  unmodified `disposition_stock_ids` parameter — previously always an implicit empty
  set per M5c's own disclosed limitation; disclosed as same-day-snapshot-only since none
  of these 5 endpoints accept a historical date-range query parameter).
  **`src/leaderboard_loader.py`/`src/limit_up_history.py`/
  `src/leaderboard_reconciliation.py`** (new): all 36 `Report_YYYYMMDD.xlsx` files
  (2026-05-15..07-16) copied from the read-only `Quant-Agent/台股漲幅排行/` source into
  `data/raw/reports/` and parsed cleanly (300 rows × 36 files = 10,800 rows; confirmed
  the xlsx cells decode to correct real Unicode codepoints -- the mojibake seen in some
  terminal displays this session was a display-layer artifact, not real file corruption).
  Limit-up history (proxy: daily return >=9.5%, disclosed as a proxy not an official
  lock flag) built at market-wide and sector level (joined against this project's own
  `stock_industry_mapping`, unmapped stocks bucketed under 未分類 not dropped): 2,502
  stock-days across the 36 sample dates, max consecutive-limit-up streak 10 days (stock
  8291, ending 2026-05-28; streak calc correctly does not bridge the real sample gaps in
  the 36-file set, e.g. 2026-06-17..06-26 is entirely absent). **Scope decision: this
  dataset is OBSERVE-ONLY** — `src/sector_scoring.py::_compute_overheat_risk` (the
  already-accepted M2 formula, which explicitly disclosed consecutive-limit-up count as
  an unimplemented sub-factor since M2) is NOT modified, per governance rule #9 and this
  project's own "新機制一律先 observe 後 active" rule; wiring it into the live score is
  a future milestone's explicit decision. 36-day cross-reconciliation computed an
  INDEPENDENT FinMind prev-close-basis return (`close[t]/close[t-1]-1`) rather than
  comparing the leaderboard's prev-close-basis 漲跌幅 directly against this project's
  own OPEN-to-close `daily_return` (a real, already-disclosed-since-M3 basis mismatch) --
  40.0% coverage (4,318/10,800 rows, limited by FinMind OHLCV backfill progress, not a
  reconciliation-logic defect), 0.97% of compared rows (42) exceed the 0.5 percentage-
  point deviation threshold specified by the task. **A real FinMind data-quality finding
  surfaced along the way**: 3 of those 42 outlier rows (stocks 2321/2941/2073, all
  2026-06-08) trace to FinMind's own OHLCV feed genuinely reporting
  open=high=low=close=0.0 with nonzero volume for those exact stock/date combinations
  (verified directly in the raw per-stock JSON, not a parsing artifact) -- disclosed as
  a genuine upstream data-corruption finding. **A real bug was caught and fixed during
  this session's own test-writing**: dividing by a zero `prev_close` (as opposed to a
  zero `close`) was originally producing `+inf` rather than `NaN` in the reconciliation
  return calc, which would have silently poisoned the mean-deviation statistic; fixed
  with an explicit `prev_close > 0` guard before this milestone's real reconciliation run
  was ever executed. Orchestrated by `scripts/run_leaderboard_analysis.py`; outputs
  under `outputs/leaderboard_analysis/`.
  **FinMind drip backfill PID 2924**: confirmed alive at session start, progressed
  571→890/1963 OHLCV (45.3%) during this session's work, then completed its own run and
  exited cleanly at 20:00:44 (hit its own rate limit near the end). Not restarted (out
  of this milestone's scope). This milestone's own new fetches used distinct filename
  prefixes throughout and never competed with PID 2924's files, per the task's explicit
  instruction.
  **56 new tests** across 7 new test files + 3 additive tests in the existing
  `tests/unit/test_report_generator.py` (all offline/mocked, no live network in the
  pytest suite itself). Full suite: **361/361 passed** (305 pre-existing + 56 new, zero
  regressions), log at `loop/evidence/test_logs/pytest_m7_run_log.txt`. See
  `docs/Milestone_7_Pitfall_Pack_Report.md` for full detail, the complete old-vs-new
  backtest headline table, and all known limitations (adjustment coverage 58%,
  disposition same-day-only, reconciliation coverage 40%, limit-up history observe-only).
- **2026-07-18 [M6 IMPLEMENTED, PENDING GATE]**: Maker delivered M6 productionization.
  **`scripts/daily_orchestrator.py`** (new): one-click orchestrator chaining
  `scripts.fetch_daily_data.run_single_day` -> `scripts.prepare_legacy_raw_snapshot
  .prepare_legacy_snapshot` -> `scripts.run_daily.run_pipeline` -> signals-JSONL append
  (reuses `run_history_pipeline.py`'s existing `_extract_signal_events`/
  `_write_signals_jsonl` helpers so the daily-live and historical-batch paths never
  drift into two different event schemas). Dependency-injected (`fetch_fn`/`bridge_fn`/
  `pipeline_fn` params) for hermetic testing without monkeypatching module globals.
  Fail-closed contract for 3 named scenarios: network failure at fetch (stops before
  touching anything, exit 1), API empty/schema-mismatched response (proceeds to
  `run_pipeline`, which owns its own `BLOCKED_MISSING_MARKET` check, exit 2), DQ
  black-out (`BLOCKED_LOW_DQ`, no Excel report produced, no signals JSONL written, exit
  2) — plus an unexpected-exception catch-all (exit 3) so a scheduled task's exit code
  is always meaningful, never a bare traceback. **`scripts/daily_run.ps1`/`.bat`** (new):
  one-click wrappers, Windows Task Scheduler-ready (setup steps documented, scheduler
  NOT actually created per task instruction). **12 new tests**
  (`tests/integration/test_daily_orchestrator.py`): all 3 failure scenarios + happy path
  + prev_date auto-detection (from the most recent SUCCESS audit JSON, ignoring BLOCKED
  days) + exception-catching contract for each of the 3 chained steps + non-fatal
  signals-append-failure handling.
  **Real live-network runs executed twice** (not just mocked): (1) 2026-07-18 (today,
  actual trading day) — TWSE `STOCK_DAY_ALL` and all TPEx OpenAPI endpoints were still
  serving 2026-07-17's data at fetch time (18:41), correctly caught by M4's existing
  DATE_MISMATCH guard as a genuine data-availability gap (not a bug); because no OHLCV
  bridge files existed, `run_pipeline`'s legacy fallback path
  (`DataLoader.fetch_twse_ohlcv_all`/`fetch_tpex_ohlcv_all`) was exercised, and when both
  returned empty, **a real pre-existing bug was found**: `pd.concat([pd.DataFrame(),
  pd.DataFrame()])` produces zero columns, so `df_prices["market_type"]` raises
  `KeyError` two lines before the intended `BLOCKED_MISSING_MARKET` empty-check would
  have caught it. This is already-accepted M1-M5c code; per governance rule #9 ("不碰
  ...未經拍板一行不改" / task instruction "禁改已驗收模組既有行為") it was **found and
  disclosed, not fixed**. Practical impact assessed as low: the new orchestrator's own
  try/except already prevents any bad report or data overwrite (confirmed via file
  timestamps — the prior good `MoneyFlow_Rotation_2026-07-17.xlsx` was untouched); only
  the log/exit-code granularity differs (EXCEPTION+traceback vs. a clean BLOCKED_*
  status). Fixed hermetically in **`tests/regression/test_run_daily_empty_market_crash.py`**
  (2 tests) so this is reproducible without depending on real network timing and won't
  silently regress further. (2) 2026-07-17 (rerun via live network, since that date's
  official endpoints currently still serve it): full SUCCESS end-to-end — 7/8 categories
  fetched (only `market_index/tpex` failed, a pre-existing known TPEx/OTC-index-
  unavailable limitation from M4), 6/6 legacy files bridged, `run_pipeline` SUCCESS
  (DQ 91.0), 53 signal events appended to `outputs/signals/signals_2026-07-17.jsonl`.
  **Reran a second time on the same date** to execute spec §28.1's reproducibility
  self-check for real (not just claimed): `sector_scored_2026-07-17.csv` and
  `stock_scored_2026-07-17.csv` are byte-identical between the two independent runs
  (`diff` empty).
  **FinMind drip backfill correction**: `loop/PROJECT_STATE.md` (prior entry) recorded
  PID 2924 as "found dead" at M5c's verification time. Re-checked at multiple points
  during this session (`Get-Process -Id 2924`, `outputs/logs/finmind_drip.log` tail) and
  found **continuously alive** the entire time — `StartTime` matches the original
  2026-07-18 15:33:27 launch, OHLCV coverage progressed 571/1963 -> 802/1963 (40.9%)
  during this session's work. **NOT restarted** — the task instruction's premise ("上一個
  PID 2924 已死") was stale/incorrect at verification time; killing a healthy, actively-
  progressing background process to relaunch an identical one would be needlessly
  destructive with no benefit, and contrary to this project's fail-closed principles.
  **`docs/operations_manual.md`** (new): user-facing (investment-decision-maker, not
  engineer) operations manual per the 溝通鐵則 communication rules — daily run steps,
  4-sheet report reading guide (including the mandatory "訊號等級=未校準研究參考,不是
  買賣指令" disclosure), error reference table (FETCH_FAILED/BLOCKED_LOW_DQ/
  BLOCKED_MISSING_MARKET/BLOCKED_NO_MAPPING/UNEXPECTED EXCEPTION), backfill-progress
  check commands, FinMind quota characteristics (~570 req/hour burst-scale throttle),
  Windows Task Scheduler setup steps (documented only, not executed).
  **`README.md`** full rewrite: the previous version was M0-era, pointing at a wrong
  `Quant-Agent\.venv` interpreter path and claiming "Milestone 0" project status; now
  documents accurate venv/requirements/verify/first-run/reproducibility-self-check
  steps and an M0-M6 documentation index.
  **`docs/acceptance_report.md`** rewritten from its stale M0-only placeholder to the
  full spec Ch.36-format final report: P0 11/12 (the 1 non-pass is the disclosed
  found-not-fixed `run_daily.py` bug, assessed as not violating the core fail-closed
  safety property), P1 20/20 (100%), P2 5/9 (55.6%, below the 90% bar but P2 is not a
  Software Ready blocker — genuine gaps: no chart generation ever implemented, no
  walk-forward, no parameter sensitivity analysis, no anomaly notification mechanism),
  Critical=0/High=0. **Final verdict: Software Ready (candidate)** — "candidate" because
  spec §28.1's two test-coverage-percentage gates (core >=85%, project >=75%) have
  **never been measured** in this project (the `coverage` package was never installed;
  confirmed absent from both `requirements.txt` and the live `.venv`), so those two
  specific sub-criteria are honestly reported as UNVERIFIED rather than claimed met.
  **Research Ready explicitly judged NOT MET** against spec §28.2's own 10-item
  checklist (walk-forward/parameter-sensitivity/market-regime-stratification all FAIL;
  n<30, single bull-market regime, signal underperforms momentum baseline — all
  previously established by M5c, restated here with the checklist mapping made
  explicit). **Trading Decision Support Ready explicitly judged NOT MET** (§28.3).
  **`VERSION`** (new, `v1.0.0-software-ready-candidate`) + root **`CHANGELOG.md`** (new)
  + `loop/CHANGELOG.md` entry (this session). Full suite: **305/305 passed** (291
  pre-existing + 12 new orchestrator + 2 new regression), log at
  `loop/evidence/test_logs/pytest_m6_run_log.txt`. See `docs/acceptance_report.md` for
  full detail, the complete P0/P1/P2 itemization, and all disclosed limitations.
- **2026-07-18 [M5c IMPLEMENTED, PENDING GATE]**: Maker delivered M5c: event-study backtest core (P0-06). **`src/backtester.py`** fully rewritten from the M0-M5c-prep stub: `extract_events` (SPEC 19.6/SPEC_ADDENDUM B-3.1 first-signal-only independent-event extraction, family-level persistence tracking, gap-day reset), `resolve_sector_member_stock_ids` (reuses `sector_features.py`'s exact primary/theme membership rule), `compute_entry_price` (T+1-open entry, SPEC_ADDENDUM B-2.1 limit-up lockout via a documented price+volume proxy since no explicit lock flag exists in the FinMind feed, both exclude/postpone-to-T+2 accountings), `compute_stock_forward_returns`/`compute_sector_forward_returns` (sector = cross-sectional median of tradable members, `None` not 0% for immature horizons), `apply_trading_cost` (fee×2+tax+slippage, gross AND net always both reported), `Backtester.run_event_study` (full orchestration, wires `src/labels.py`'s existing SPEC_ADDENDUM A-2 outcome labels). **New `src/benchmarks.py`**: `momentum_extension_baseline` (daily-rebalanced highest-prior-score-sector heuristic) + `random_sector_bootstrap_baseline` (N=10,000-draw uniform random sector/date sampling, fixed seed=42) per SPEC_ADDENDUM A-3, plus `bootstrap_confidence_interval`. **New `scripts/run_backtest.py`** orchestrator: loads all 60 days of on-disk signals/scored-frames/FinMind-OHLCV/TAIEX, runs the event study + both benchmarks, writes `outputs/backtests/backtest_report_<date>.xlsx` (4 sheets) + CSV dumps + JSON summary. **Real 60-day run** (2026-04-20 to 2026-07-17, `--n-bootstrap 10000`): 53 independent events (47 primary + 6 theme). Headline 10-day net excess return: B級早期點火 median -11.28% (n=27 realized), C級個股事件 median -10.41% (n=19 realized); both underperform the momentum baseline's -0.39% median -- per SPEC_ADDENDUM A-3.3's own rule this is reported as "無增量價值證據" for this window. Both tiers n<30 (below this project's own 30-event decisiveness bar and SPEC_ADDENDUM B-1.4's 50-per-grade bar); 0 A-grade new-gainer and 0 續漲訊號 events occurred at all in the real dataset. UNTRADABLE: 46 TRADABLE / 7 UNTRADABLE (identical under exclude and postpone) -- all 7 are FinMind OHLCV coverage gaps (zero history for those member stocks), NOT limit-up locks; zero real limit-up lockouts were exercised by this particular sample (P0-06 lockout logic validated by unit test only, not by a real observed lockout this round). **A genuine, structural finding disclosed**: the real 2,765-row/60-day signal dataset has ZERO `無訊號`/`無效` rows anywhere -- every scored sector carries a graded B/C signal every single day it appears, which under the correct first-occurrence event rule collapses the independent-event count to 53 total, 46 of them concentrated on the window's very first day (a cold-start artifact of the 60-day left edge, not genuine ignition) and 7 on the last day (all UNTRADABLE for lack of forward data). Verified this is a real signal-detector-output fact, not an event-extraction bug, via 6 dedicated unit tests proving the extraction logic itself is correct. **A real bug caught and reverted mid-session** (performance optimization, not a shipped defect): an identity-keyed (`id(df)`) cache tried first to speed up the N=10,000 bootstrap run (initial attempt exceeded 6+ minutes and was killed) was caught as UNSAFE by the test suite itself (4 real failures -- CPython can reuse a freed object's memory address, silently returning a different stock's cached history) before it ever touched the real report; reverted in full and replaced with an explicit caller-owned `index_ohlcv_by_stock()` pre-grouping with no implicit caching. The real N=10,000 run then completed in 2m41.7s with results identical to the pre-optimization smoke-test values (correctness preserved). **`scripts/fetch_history_finmind.py`** gained one additive `--sleep-between <seconds>` CLI flag (default `None` = unchanged 1.0s `POLITE_DELAY_SEC` behavior); used to launch a detached slow drip backfill (PID 2924, `--sleep-between 50`, started 15:33:27, confirmed actually fetching new data) that will keep resuming the still-incomplete institutional/margin/OHLCV backfill unattended in the background. New `docs/backtest_methodology.md` (event definition, no-future-function guarantee, sector-return convention, all 5+ required disclosures including the honest "ex-dividend adjustment NOT implemented" finding) and `docs/Milestone_5c_Acceptance_Report.md`. 42 new tests, full suite 291/291 passed, log at `loop/evidence/test_logs/pytest_m5c_run_log.txt`. See `docs/Milestone_5c_Acceptance_Report.md` for full detail and all known limitations.
- **2026-07-18 [M5c-prep IMPLEMENTED, PENDING GATE]**: Maker delivered M5c-prep: fixed the M4 merge-suffix bug M5b disclosed but didn't fix, resolved the 3-day mock-file shadowing, resumed the FinMind backfill, reran the full 62-day batch. **Merge bug fix** (`scripts/run_daily.py`, institutional merge ~line 411-441, the ONE authorized change to already-accepted code): drops stale institutional columns (carried over via the multi-day CSV concat from a prior day's persisted `stock_features_<date>.csv`) from `df_stock_features_today` before merging in today's fresh `df_inst` values -- previously no `suffixes=` was specified, which either raised a MergeError or (directly reproduced) silently split `foreign_net_buy` into `_x`/`_y` duplicate columns, corrupting the persisted CSV. New regression test `tests/integration/test_run_daily_two_day_merge.py` runs 2 consecutive real days hermetically with deliberately different day-2 institutional values -- confirmed FAILING pre-fix (missing clean `foreign_net_buy` column, only `_x`/`_y` present) and PASSING post-fix (clean column, correct fresh day-2 value). **Mock-file unshadowing**: moved `data/raw/ohlcv/prices_2026-07-14/15/16.json` (synthetic demo data from `create_demo_data.py`, shadowing both the official and FinMind legacy bridges via a combined-file-checked-first code path) to `data/test_fixtures/legacy_mock/`; updated the one dependent test's fixture path (`test_m2_e2e_pipeline.py`). **A second, independent issue found while verifying the move didn't break anything**: that same test's mock stock IDs collide with a real external `Report_20260716.xlsx` leaderboard file `load_excel_leaderboard`'s pre-existing M1-documented hardcoded glob path picks up on this dev machine, causing a real `BLOCKED_LOW_DQ` unrelated to what the test verifies -- isolation-tested to confirm this is NOT caused by the file move (reproduced identically with files restored to the original location), then fixed by mocking `load_excel_leaderboard` in that one test (same hermeticity pattern as `test_run_daily.py`), zero production code touched beyond the authorized merge fix. **FinMind backfill resume**: institutional 0->26/1963, margin 0->2/1963 (OHLCV unchanged 571/1963, deprioritized this round per instruction). New finding: the observed rate limit is a short (~30-90s) burst-scale throttle, not the clean hourly window M5b assumed -- confirmed empirically via 6+ real resume attempts each netting single-digit successes before re-402'ing; session stopped after ~5-6 minutes per the "don't wait >30min" instruction, receipt updated with the full honest attempt log. **Full 62-day batch rerun** (`--use-finmind`, backups of all pre-rerun processed/signals/audit files taken first): 60/62 SUCCESS (was 2), 0 EXCEPTION (was 26, merge bug fixed), 2 BLOCKED_LOW_DQ (was 31, now only 2026-07-14/15 -- genuinely thin institutional/margin data for those 2 specific dates, correctly fail-closed, not a bug), 0 BLOCKED_MISSING_MARKET (was 3, mock-file unshadowing worked -- 2026-07-16 now SUCCEEDS). 2,765 total signal events, 383.94s elapsed. 1 new test, full suite 249/249 passed, log at `loop/evidence/test_logs/pytest_m5c_prep_run_log.txt`. See `docs/Milestone_5c_prep_Report.md` for full detail.
- **2026-07-18 [M5b IMPLEMENTED, PENDING GATE]**: Maker delivered M5b: FinMind historical data layer closing M5a's two carry-forwards (official-endpoint historical backfill impossibility, industry code->Chinese-name lookup). **New `src/finmind_fetcher.py`/`scripts/fetch_history_finmind.py`**: dataset names discovered by live dry-run (never recited from memory) against `https://api.finmindtrade.com/api/v4/data` -- confirmed usable: `TaiwanStockPrice` (per-stock OHLCV + TAIEX index via `data_id=TAIEX`), `TaiwanStockInstitutionalInvestorsBuySell`, `TaiwanStockMarginPurchaseShortSale`, `TaiwanStockInfo` (whole-market Chinese sector names); confirmed UNAVAILABLE: no working TPEx/OTC index series on this token after 8 candidate data_ids all returned HTTP 200 with zero rows. Fail-closed + rate-limit-aware (`RATE_LIMITED` short-circuit on HTTP 402/429, no wasted retry) + resumable (`skip_existing`, exact-date-range match required). **Real backfill executed**: 571/1963 stocks' OHLCV (29.1%, full 62-day history each) before the token's hourly quota was hit (HTTP 402 on request #572, confirmed genuine hourly-scale limit via a resume probe 23s later that immediately re-hit 402); institutional/margin 0/1963 (quota exhausted during the OHLCV pass); TAIEX index 100%; receipt `loop/evidence/fetch_receipts/finmind_backfill_summary.json`. **New `scripts/build_chinese_sector_mapping.py`**: converts the 1,955 non-reviewed rows' raw numeric `primary_sector` codes to real FinMind Chinese industry names (100% of eligible rows updated), preserves the old code in a new `sector_code` column, protects all 8 `reviewed=1` rows untouched -- verified against a genuine FinMind data-quality wrinkle (many stock_ids appear multiple times with different dates/categories; resolved via max-date-wins-then-first-occurrence, cross-checked exact against the reviewed ground-truth rows). Real 7/17 report re-run and confirmed showing Chinese sector names (金融保險/食品工業/etc) in the Dashboard, old report backed up to `.xlsx.bak`. A real bug was found and fixed during manual verification: the mapping backup path produced an invalid `.bak_<date>` (non-`.xlsx`) filename that crashed pandas' `to_excel` engine inference -- fixed, with a regression test added. **`src/data_loader.py` dual-source integration**: new additive `load_finmind_*_for_date` / `merge_*_sources` methods -- official data always wins on any stock_id conflict, FinMind only fills gaps, `source` column always distinguishes the two (never blended). **New `scripts/prepare_finmind_legacy_snapshot.py`** bridges FinMind's per-stock files into the same legacy per-day filenames M5a's official bridge uses, as a strict no-op (never overwrites) wherever an official-sourced file already exists. **`scripts/run_history_pipeline.py`** gained an additive `--use-finmind` flag (default off, exact M5a behavior preserved) that unions FinMind-covered dates with official-covered dates. **Batch pipeline actually run** for the full 62-day range: 2/62 days SUCCESS, 26 EXCEPTION, 31 BLOCKED_LOW_DQ, 3 BLOCKED_MISSING_MARKET -- the low SUCCESS count reflects genuine upstream data-completeness limits (institutional/margin quota exhaustion) PLUS a **newly-surfaced pre-existing latent bug in already-accepted M4 code**: `scripts/run_daily.py`'s institutional-column merge (~line 414) crashes once a prior day's persisted `stock_features_<date>.csv` already carries `foreign_net_buy`/etc columns from an earlier successful merge, because no `suffixes=` is specified -- never triggered before since M0-M5a never ran the real merge path across enough consecutive real days for this to occur. **NOT fixed this milestone** (governance rule #9, disclosed as highest-priority follow-up in the acceptance report, not silently patched). Also found: pre-existing demo-data leftover files (`data/raw/ohlcv/prices_2026-07-14/15/16.json`, from `create_demo_data.py`) shadow BOTH the official and FinMind legacy bridges for those 3 dates via a combined-file-checked-first code path -- disclosed, not deleted (outside stated scope). **Reconciliation**: 569/571 FinMind-fetched stocks' 2026-07-17 closing price exact-matched (100%, 0 mismatches) against the real official snapshot -- the full universe was checked (not just 3 stocks) because only 1 date (2026-07-17) has a genuine official raw snapshot on disk; the 7/16 combined file on disk was found to be synthetic demo data (~half the real price level) and correctly excluded from reconciliation rather than used misleadingly; 2330 individually confirmed exact match. 68 new unit tests (`test_finmind_fetcher.py` 27, `test_build_chinese_sector_mapping.py` 10, `test_data_loader_finmind.py` 15, `test_prepare_finmind_legacy_snapshot.py` 9, +7 in `test_run_history_pipeline.py`). Full suite: 248/248 passed, log at `loop/evidence/test_logs/pytest_m5b_run_log.txt`. See `docs/Milestone_5b_Acceptance_Report.md` for full detail.
- **2026-07-18 [M5a OPEN ITEMS CLOSED by maker, re-submitted for gate]**: Addressed all items the verifier's PARTIAL GATE pass flagged as open/rejected below. `docs/Milestone_5a_Acceptance_Report.md` now exists (was missing at the verifier's snapshot time because the maker was mid-writeup when the DNS sinkhole made the backfill run appear stalled). `loop/evidence/fetch_receipts/backfill_summary.json` now exists: honestly reports **0 of 65 requested trading days** succeeded this session (the T86-only backfill the verifier saw "left running" was aborted by the maker after 7 consecutive fully-failed days / ~30 minutes with zero signs of network recovery, rather than continuing for an estimated 2+ hours against a dead network — see the file's `root_cause_this_session` and `architectural_limitation` fields for the full honest breakdown, including why `ohlcv`/`margin`/`market_index` were correctly NOT attempted 65x each: they have zero query parameters per swagger, so historical backfill against them is a swagger-provable guaranteed-negative regardless of network health). `outputs/signals/` now exists: `scripts/run_history_pipeline.py` was run for real; `discover_available_dates` correctly found exactly 1 date (2026-07-17) with both markets' M4-format OHLCV on disk — an honest, direct consequence of the 0-day backfill result, not a driver bug (the driver's own logic is separately verified via 12 passing unit tests with 3-day stubbed scenarios) — producing `outputs/signals/signals_2026-07-17.jsonl` (44 lines, one per scored sector). Industry code->Chinese-name lookup remains genuinely `UNAVAILABLE` (verifier's own finding, unchanged — no verified official source exists in either swagger); flagged for M5b as the verifier recommended. Full suite re-run: 180/180 passed, `loop/evidence/test_logs/pytest_m5a_run_log.txt` regenerated.
- **2026-07-18 [M5a PARTIAL GATE by Claude verifier]**: Independent rerun 180/180 passed. ACCEPTED: official mapping import (coverage receipt + verification receipt on disk, 98.58% live-logged in pipeline run), real `MoneyFlow_Rotation_2026-07-17.xlsx` (4 sheets, 44 sectors, 29 B-level signals, substantive reasons), date-consistency guard, architectural backfill finding (only T86 honors date=; verified against swagger, not guessed). REJECTED/OPEN: `docs/Milestone_5a_Acceptance_Report.md` referenced by this file but DOES NOT EXIST (maker died mid-writeup — claim-vs-artifact mismatch); `backfill_summary.json` absent; `outputs/signals/` absent (no history to batch). Sector names are raw industry codes ('17','37','02') — official code->name lookup unavailable in swagger, needs alternative official source. Carry-forwards fold into M5b: FinMind historical ingestion (official endpoints architecturally cannot backfill), history batch -> signals JSONL, industry code->Chinese-name mapping from a verifiable official source, M5a closure documentation.
- **2026-07-18 [M5a IMPLEMENTED, PENDING GATE]**: Maker delivered M5a: official industry mapping auto-import, historical backfill infrastructure + attempt, historical batch pipeline, real 7/17 report. New `scripts/build_official_mapping.py`: fetches TWSE `/opendata/t187ap03_L` (上市公司基本資料) and TPEx `/mopsfin_t187ap03_O` (上櫃股票基本資料), both verified against cached swagger (not recalled from memory); live-fetched successfully (TWSE 1,090 rows -> 1,079 valid equities, TPEx 891 rows -> 884 valid equities). Merges into `data/reference/stock_industry_mapping.xlsx` protecting all `reviewed=1` manual rows (verified 2330/台積電 untouched, still shows human-curated "半導體" not the raw TWSE code), never overwriting a row the official source doesn't cover, never guessing an unclassified stock's sector. **Coverage**: 0.41% (8/1974) -> 98.58% (1946/1974) against the real 2026-07-17 trading universe (verified directly against the live mapping file + real OHLCV snapshot; receipt at `loop/evidence/fetch_receipts/official_mapping_coverage_verification_2026-07-18.json` since a same-day retry overwrote the original success receipt with a later network-outage failure -- mapping file itself unaffected, fail-closed protected it). **Honest limitation**: neither TWSE nor TPEx swagger exposes an industry-code -> Chinese-name lookup endpoint; `industry_code_lookup_status=UNAVAILABLE`, so the 1,955 newly-imported rows carry the raw numeric code (e.g. "28") as `primary_sector`, not a resolved label -- visible as-is in the Dashboard, not hidden. **Date-consistency guard** (`src/data_fetcher.py::extract_payload_date`/`_parse_roc_or_iso_date`): new fail-closed check added to `DataFetcher.fetch_and_save` -- if a payload self-reports a date (top-level `date` field or per-row `Date` field) that doesn't match the requested `trade_date`, the payload is dropped (not saved), logged as `DATE_MISMATCH`. Motivated by a hard technical finding: TWSE `STOCK_DAY_ALL`/`MI_MARGN`/`MI_INDEX` and ALL TPEx OpenAPI endpoints accept ZERO query parameters per their cached swagger definitions (grep-verified) -- they always return their latest trading day regardless of what date is requested. Only TWSE T86 (institutional, legacy RWD endpoint outside the OpenAPI swagger) genuinely honors `date=` (live-confirmed: requested 2026-06-01, payload echoed back `date: "20260601"`). **Resumable backfill**: `DataFetcher.fetch_and_save`/`fetch_all_categories`/`backfill` gained an additive `skip_existing` parameter (default `False`, preserving exact M4 behavior) that skips re-fetching a `(category, market, trade_date)` already on disk; `scripts/fetch_daily_data.py --backfill` now defaults to `skip_existing=True` (opt out via `--no-resume`). **Backfill attempt for 2026-04-20 to 2026-07-17**: this session's sandbox network experienced a SUSTAINED multi-hour DNS-sinkhole/timeout outage (100% connection failures across dozens of consecutive attempts to both `openapi.twse.com.tw` and `www.tpex.org.tw`/`www.twse.com.tw`, confirmed via `Resolve-DnsName` resolving to the unreachable `10.0.0.1` sinkhole address) -- qualitatively worse than M4's "intermittent" quirk. The T86-only backfill (the only endpoint architecturally capable of true historical data) was left running; actual day-by-day success/failure counts are in `docs/Milestone_5a_Acceptance_Report.md` and `loop/evidence/fetch_receipts/backfill_summary.json`, reported honestly including if the range did not fully complete. New `scripts/run_history_pipeline.py`: sequential driver reusing `scripts.run_daily.run_pipeline` (given an additive, backward-compatible return value it previously lacked) over every date with both markets' OHLCV on disk, writing `outputs/signals/signals_<date>.jsonl` per successful day; one blocked/failed day does not abort the batch. New `scripts/prepare_legacy_raw_snapshot.py`: bridges M4's `data_fetcher.py` filenames (`twse_<date>.json`) to the legacy filenames `run_pipeline` actually reads (`twse_prices_<date>.json` etc) -- a naming mismatch disclosed but not fixed in M4's own acceptance report ("run_pipeline was not re-run end-to-end against the new 2026-07-17 real data"), bridged here via pure file copy (never mutates/deletes the M4-format source). **Real 7/17 report**: `outputs/daily/MoneyFlow_Rotation_2026-07-17.xlsx` produced from real data end-to-end -- status=SUCCESS, DQ score=91.0/WARNING, mapping coverage=98.58% (low-coverage Dashboard warning correctly absent now), 44 sectors scored (29 B級早期點火, 15 C級個股事件, 0 A/續漲 since no `prev_date` day-over-day history was available for this standalone run). **M3 E2E test fix**: `tests/integration/test_m3_real_snapshot_e2e.py` previously hardcoded an assertion that the low-mapping-coverage warning must always appear -- now correctly reads the real coverage from the audit JSON and asserts the warning only when coverage `<80%`, and that the actual percentage displays when `>=80%` (the M5a coverage jump made the old hardcoded assertion obsolete, not the report_generator logic, which was already correctly conditional). See `docs/Milestone_5a_Acceptance_Report.md` for full detail and known limitations.
- **2026-07-18 [M4 GATE APPROVED by Claude verifier]**: Independent rerun 134/134 passed. Live-fetch receipts cross-checked: suspected sample-copy for `institutional/twse_2026-07-17.json` (byte-size identical to cached 7/16 sample) ruled out — sha256 differs and payload internally dated 20260717 ('115年07月17日 三大法人買賣超日報', 1,337 rows); TPEx OHLCV payload Date=1150717, 10,012 rows; index endpoints real (MI_INDEX 267 rows). M5 may start; priority re-ordered by verifier: official industry classification auto-import + historical backfill BEFORE backtester core, because 0.41% mapping coverage makes sector-level event study vacuous.
- **2026-07-18 [M4 IMPLEMENTED, PENDING GATE]**: Maker delivered M4 V2 data layer. New `src/data_fetcher.py` + `scripts/fetch_daily_data.py`: TWSE/TPEx daily OHLCV+institutional+margin+market-index fetcher writing the standard `{metadata:{url,fetch_time,http_status,row_count,sha256}, payload}` envelope to `data/raw/<category>/<market>_<date>.json`; fail-closed (HTTP!=200/empty payload/schema mismatch -> None, logged, never raises); 2 retries at 3s spacing; idempotent `.bak` backup before any overwrite; `--backfill start end` (skips weekends, holiday-empty-payload treated as a normal record); `--smoke` (single live endpoint + schema check only). Market index: TWSE `MI_INDEX` and TPEx `tpex_index`, both endpoints found and verified against the cached `loop/evidence/raw_samples/{twse,tpex}_swagger.json` definitions (not recalled from memory) — real, working, non-placeholder endpoints, so `INDEX_SOURCE_UNAVAILABLE` is implemented as a fail-closed code path but was not needed in practice. New `src/market_regime.py`: 6-state classifier (多頭擴張/多頭盤整/高檔鈍化/空頭反彈/空頭趨勢/極端風險) from index MA20/MA60/20d return/20d volatility plus full-market breadth; degrades to breadth-only classification with `DEGRADED` confidence when index history is absent, and separately reports `INSUFFICIENT_DATA` when index history exists but has fewer than 60 rows (can't compute MA60) — matches the M4 brief's distinction between "no index" and "not enough index history" degradation paths. New `src/institutional_features.py`: per-stock 3/5/10/20-day cumulative net buy (rolling sum, min_periods=window), consecutive-buy-day streak (resets to 0 on a sell day, NaN on a missing day), buy-as-pct-of-volume, foreign+trust same-direction flag; sector-level aggregation (net-buying stock count, net buy total, pct of sector turnover); SPEC_ADDENDUM C-1 quarter-end (Mar/Jun/Sep/Dec) last-5-trading-day window flag, boundary-tested exact-5th-day true / 6th-day false. New `src/margin_features.py`: margin balance % change (3d/5d), margin usage rate (real quota-based when a quota column exists, else a documented `_proxy`-suffixed rolling-60d-max fallback so it's never confused with the real regulatory rate), short-margin ratio (券資比) — NaN (never 0) on any missing/zero denominator. **Wiring gap closed**: `scripts/run_daily.py` previously computed `df_inst` and passed `has_institutional=not df_inst.empty` into `stock_scoring.score_stocks`, but never actually merged `foreign_net_buy`/`investment_trust_net_buy`/`dealer_net_buy` onto the stock-features frame that call receives — so the "institution" scoring sub-factor silently fell back to its neutral 50.0 prior every day even on days with real institutional data. Fixed by merging institutional flow onto `df_stock_features_today` before scoring, and by persisting/rebuilding institutional and margin rolling-history CSVs (`institutional_features_<date>.csv`, `margin_features_<date>.csv`) the same no-future-leakage way stock/sector features already work. Sector-level institutional aggregation columns (`net_buying_stock_count`, `sector_net_buy_total`, `sector_net_buy_pct_of_turnover`) are attached to `sector_features_<date>.csv` as additional reference columns; the sector_score "institution" sub-factor formula itself (still `inst_flow_ratio` from `SectorFeatures`) is unchanged per the "scoring weight contract unchanged" instruction. 46 new unit tests (`test_data_fetcher.py` 15, `test_market_regime.py` 10, `test_institutional_features.py` 13, `test_margin_features.py` 8) plus 1 new integration test `tests/integration/test_m4_institutional_wiring_e2e.py` proving the wiring fix with real 2026-07-16 snapshot data. Full suite: 134/134 passed, log at `loop/evidence/test_logs/pytest_m4_run_log.txt`. Live smoke test executed: HTTP 200, 1,371 rows. Live single-day fetch for 2026-07-17 executed: all 8 endpoints eventually succeeded (HTTP 200, real row counts, sha256-verified against on-disk files) after this sandboxed dev machine's outbound network exhibited transient DNS-sinkhole/timeout behavior on some attempts — the retry/fail-closed design meant no partial or corrupt file was ever written, only genuine HTTP 200 responses landed on disk; full root-cause narrative in `docs/Milestone_4_Acceptance_Report.md` §5. **Known limitations**: `run_pipeline` (full daily Excel report) was not re-run end-to-end against the new 2026-07-17 real data (only the fetcher was exercised live for that date); the existing M3 real-snapshot E2E + new M4 wiring E2E both continue to use the 2026-07-16 evidence-folder snapshots. Backtester/limit-up lockout (P0-06) correctly remains deferred to Milestone 5 per the original scope split.
- **2026-07-18 [M3 GATE APPROVED by Claude verifier]**: Independent rerun 87/87 passed. Real report `outputs/daily/MoneyFlow_Rotation_2026-07-16.xlsx` opened programmatically: exactly 4 sheets (Dashboard/新起漲族群/續漲族群/個股優先排序), Chinese text integrity asserted (台積電 cell exact match), uncalibrated-threshold and 0.41% mapping-coverage warnings present on Dashboard, empty continued-momentum sheet honestly labeled, audit JSON status SUCCESS with real row counts (1,104 TWSE + 871 TPEx). Known carry-forwards: continued-momentum rules 5/6 unevaluable (no data source), mapping coverage 0.41%, M1 `load_excel_leaderboard` return-basis mismatch vs external Quant-Agent Report file (disclosed, future milestone). M4 may start.
- **2026-07-18 [M3 IMPLEMENTED, PENDING GATE]**: Maker delivered M3 signal detection + Excel reporting. Rewrote `src/signal_detector.py` implementing SPEC Chapter 14's 10-condition New Gainer checklist and Chapter 15's Continued Momentum checklist as explicit per-condition pass/fail/unevaluable evaluators (never a single opaque score threshold); A/B/C/無效 grading with a hard UAT-04 gate (sectors with <2 distinct up-moving stocks can never grade A/B, only C/無效, regardless of score); every graded row carries `conditions_passed/failed/unevaluable`, `invalidation_condition`, and `signal_data_confidence` (FULL/DEGRADED/LOW). All 15 new thresholds added to `config/default.yaml` under `new_gainer.*`/`continued_momentum.*`, each `# PLACEHOLDER - UNCALIBRATED`, mirrored in `src/config_manager.py::get_defaults`. Rewrote `src/report_generator.py` to produce exactly 4 sheets per SPEC_ADDENDUM B-4 (down from the prior 4-sheet-but-differently-named/structured version): Dashboard (DQ score, mapping coverage with unmissable low-coverage warning, top-10 sector table), 新起漲族群, 續漲族群, 個股優先排序 (each with required columns and a data-quality/caveat block; unmapped stocks get an explicit "尚未完成產業分類" risk note and downgraded confidence rather than inherited FULL confidence). Extended `scripts/run_daily.py` additively: loguru file sink at `outputs/logs/run_<date>.log`, structured audit JSON at `outputs/logs/audit_<date>.json` (input files, row counts incl. DQ score/mapping coverage/confidences, output files, elapsed time, status), previous-day sector/stock-features loading for signal-detector day-over-day deltas, top-5-stocks-per-sector attachment. Ran the full pipeline against the REAL 2026-07-16 TWSE+TPEx OHLCV/institutional/margin snapshots end-to-end (no network calls, no synthetic data) producing a real `outputs/daily/MoneyFlow_Rotation_2026-07-16.xlsx`; discovered and disclosed (not silently patched) a pre-existing M1 environment-coupling issue where `load_excel_leaderboard`'s hardcoded external-project glob path picks up an incidental real leaderboard file on this dev machine, and reconciling against it surfaces a genuine return-basis mismatch (`daily_return`=(close-open)/open vs. the leaderboard's prev-close-to-close 漲跌幅) that legitimately BLOCKs the pipeline via the DQ score — full root-cause trace in `docs/Milestone_3_Acceptance_Report.md` §4, flagged as a recommendation for a future milestone, not fixed this milestone (M1 scoring logic is locked). 87/87 tests passed (59 baseline unchanged + 28 new), log at `loop/evidence/test_logs/pytest_m3_run_log.txt`. One pre-existing P0-03 critical test (`tests/acceptance/test_future_leakage.py`) had its sheet-name/header lookup updated to match the new B-4 schema; the actual leakage assertion is byte-for-byte unchanged. **Known limitations** (see `docs/Milestone_3_Acceptance_Report.md` §6): Continued Momentum rules 5/6 (次龍頭接棒/高檔爆量不漲) always unevaluable (no data source wired); industry mapping coverage remains the known 8/1988 (~0.4%); P0-06 backtest limit-up lockout correctly out of scope this milestone.
- **2026-07-18 [M2 IMPLEMENTED, PENDING GATE]**: Maker delivered M2 feature/scoring engine. Rewrote `stock_features.py` with multi-day rolling features (vol_ma5/20, turnover_ma5/20, relative_volume, 20d-high distance, 1/3/5/10/20d returns), all with `min_periods` enforced and verified leakage-free via a dedicated truncated-vs-full-dataset regression test. Rewrote `sector_features.py`: real full-market breadth, Top1/3/5 concentration, HHI, and P0-05 compliant `may_double_count` flag distinguishing primary_sector (never double-counted) from theme (may double-count, explicitly flagged) aggregates; added `calculate_relative_strength_history` for 3d/5d rolling relative strength. Rewrote `sector_scoring.py` with `# PLACEHOLDER - UNCALIBRATED` markers on all weights/thresholds, strict weight renormalization (never zero-fills a missing factor), `score_confidence` in {FULL, DEGRADED, LOW}, 0-100 clamping, and a partial Overheat Risk sub-score (breadth/volume divergence + volume surge proxy + concentration only; consecutive-limit-up/upper-shadow/institutional-reversal factors NOT implemented, no real-time data source wired yet). Created new `stock_scoring.py` (individual-stock 35/20/15/10/10/10 weights, same renormalization/confidence contract, role assignment). Rewrote `lifecycle_classifier.py` to require >=3 days of accumulated sector history (returns `資料不足`/`INSUFFICIENT_DATA` below that, `PARTIAL` for 3-9 days, `FULL` for >=10) and to classify using 3-day delta + 5/10-day trend evidence per SPEC 13.6, not a single day. Created `src/labels.py` implementing P0-02 New Gainer / Continued Momentum success/failure/reversal label functions matching `docs/signal_definitions.md`. Created `scripts/build_mapping_template.py` (P0-02/spec 8.2 compliant: discovers real stock universe from `loop/evidence/raw_samples`, never guesses sector for unmapped stocks, emits `data/reference/stock_industry_mapping_template.csv` with 1,980 unclassified stocks out of 1,988 discovered). Rewired `scripts/run_daily.py` to persist `data/processed/{stock_features,sector_features,sector_scored,stock_scored}_<date>.csv` per run and rebuild rolling history strictly from files dated <= the current run's trade_date (structural no-future-leakage guarantee), verified via a 3-day mock E2E test. 59/59 tests passed, log at `loop/evidence/test_logs/pytest_m2_run_log.txt`. **Known gaps** (see `docs/Milestone_2_Acceptance_Report.md`): sector "momentum/continuity" (15% weight) and stock "breakout quality" (10% weight for stocks without 20d-high data) sub-scores fall back to a neutral 50.0 prior when insufficient signal exists; Overheat Risk (SPEC 12.3) implements only 3 of ~9 listed sub-factors. These gaps are explicitly disclosed, not hidden, and do not block P0/P1 items this milestone claims.
- **2026-07-18 [M1 GATE APPROVED by Claude verifier]**: Independent adversarial re-verification of the 3 rejection blockers using REAL cached snapshots: B1 TPEx sample (10,012 payload rows) -> 871 cleaned equities, nonzero_volume=871, nonzero_turnover=871 (was 0/0); B2 single 10% deviation -> `WARNING_HIGH_DEVIATION` (was MATCH); B3 mismatched payload Date dropped, not relabeled (control row with matching date passes). Full suite 14/14 passed in fresh project venv `.venv` (py3.14, requirements.txt pinned). M2 may start.
- **2026-07-18 [M1 PASSED]**: Resolved M1 R3 gate audit issues. Fixed TPEx foreign institutional flow key mapping. Executed E2E smoke tests within temporary directories to prevent production folder pollution. Updated both E2E integration and future data leakage prevention tests to run hermetically without live network calls or warnings. Successfully ingested 1,975 rows of dual-market price data. Logged 14 passed tests in `pytest_run_log.txt`.
- **2026-07-17 [M0 PASSED]**: Rollback system to Milestone 0. Corrected TPEx Swagger paths, verified T86 RWD endpoint, and cached 6/6 API JSON responses in `loop/evidence/raw_samples/`. Verified 29-folder setup and manifest directory check.
- **2026-07-22 [M11 AUTO-BACKFILL IMPLEMENTED, ACCEPTANCE WITH LIMITATION]**: Late
  official-data recovery is now an orchestrator concern, not a signal-rule change.
  `daily_orchestrator.py` finds weekday gaps in a 5-calendar-day window, probes both
  TWSE endpoints once, runs only ready dates oldest-first, and records not-ready dates
  as `DEFERRED_NOT_READY` without creating a BLOCKED audit. Explicit date and
  `--no-backfill` behavior remains backward-compatible; holiday evidence is recorded
  as `HOLIDAY_SKIP`; idempotent successes are skipped. New tests: 12; full suite
  483/483 (baseline 471), logs at
  `loop/evidence/test_logs/pytest_auto_backfill_run_log.txt`. Live dry-run on 7/22:
  gaps 7/21 + 7/22, official latest 7/21, decisions READY + DEFERRED_NOT_READY.
  Live auto-backfill attempted 7/21 and honestly reached `PIPELINE_BLOCKED` because
  TPEx OHLCV/institutional/index payloads self-reported 7/22/7/1 and were rejected by
  the existing date-consistency guard; 7/22 was not fetched. This pre-existing
  endpoint/date-coverage limitation is disclosed, not bypassed. No signal detector,
  calibration, backtester, benchmark, or Windows Scheduler entry was modified.

---
## [2026-07-28 00:45] TASK-daily-report-field 三工作包 對抗式驗收:PASS-WITH-CONCERNS(gate 通過)
- 驗收報告:`Quant-Agent/_workbench/out/moneyflow_daily_report_field_verification_20260728.md`;規格+Execution Results:`.ai/tasks/TASK-daily-report-field.md`
- C(防呆):BLOCKED_LOW_COVERAGE 涵蓋率門檻(近10 SUCCESS 中位數×0.8,UNCALIBRATED)驗真——合成130檔被擋、68 audit 離線重放 0 誤擋、冷啟動不誤擋;extract_payload_date 認得中文「日期」key(含識破 7/18 污染檔);orchestrator 過去日期跳過無日期端點、「今天」路徑未誤傷。
- B(7/20):官方回補 1101 檔重跑成功(audit SUCCESS/1968 scored/official/dq90,舊 130 檔 finmind_fallback 版存 .bak);2330 OHLCV 與 STOCK_DAY 整月資料 115/07/20 列逐位一致。
- A(觀察欄位):observe_rankings 四項(漲/跌/成交值前300族群聚合+法人聚合)零影響既有輸出驗真(欄位集合零差異、既有分頁逐格一致、observe JSON 獨立重算逐位吻合、fail-open 注入實測成立)。測試 493 passed(487+6,無刪無弱化)。
- CONCERNS 待辦:①(中)signals_2026-07-20.jsonl 仍是殘缺日舊訊號(49 事件),與重跑後 sector_scored 不一致——待使用者拍板重生成或註記,勿擅動;②(低中)fail-open 建議補自動化回歸測試;③(低)observe 300/5 常數未鏡像 yaml;m3 e2e 測試會重寫 7/16 歷史報告為 5 分頁版,建議隔離。
- 執行插曲(教訓):Codex 前兩輪經轉發層啟動均被 10 分鐘前台時限連帶殺死;第三輪起改用 companion 原生 --background 才存活。companion 狀態面板多次假 running/丟紀錄,監視一律以 PID 存活為準。

## [2026-07-28 11:20] 使用者拍板:7/20 訊號檔重生成(完成)
- 舊 49 事件(殘缺日 997 檔算出)備份 `signals_2026-07-20.jsonl.bak_partialday`;以修復後完整資料(1,968 檔)重跑 pipeline+訊號抽取,新檔 53 事件。走純 run_pipeline 路徑,未觸碰 fetch/bridge(避開 fetcher 家族殘留污染檔)。
- 剩餘 backlog(低優先,未派工):fail-open 自動化回歸測試、observe 300/5 常數鏡像 yaml、m3 e2e 測試重寫歷史報告問題隔離。

---
## [2026-07-28 12:50] 第二批收尾 D/E/F 完成 — E 經一次 REJECT 後重做通過(gate PASSED)
- 規格:`.ai/tasks/TASK-daily-report-field.md`(第二批);驗收報告:`Quant-Agent/_workbench/out/moneyflow_secondbatch_verification_20260728.md`(第一輪)與 `..._e_redo_verification_20260728.md`(E redo 複驗)
- **D(fail-open 回歸測試)PASSED**:`tests/integration/test_run_daily.py` 參數化注入 build/write 兩條例外路徑。驗收親手拆掉 try/except → 兩條各自轉紅(RuntimeError 分別來自 run_daily.py:927/:949),證明非形式測試;還原後恢復綠燈。
- **E(observe 常數接 config)一度 REJECT 後 PASSED**:第一輪交付死設定(yaml 寫了但無人讀,改 50 仍跑 300;測試是 `assert config.get(X)==300` vs `assert 常數==300` 字面值互比)。重做後 `run_daily.py:932-936` 真從 ConfigManager 讀取並傳入,常數留作 fallback。決定性實測(改真 yaml、不 patch ConfigManager、隔離 output_dir):300/5→300/5、**50/2→50/2**、移除區塊→fallback 300/5。行為零變更:預設值產出 rankings JSON sha256 與正式 `outputs/observe/rankings_2026-07-16.json` 完全相同。舊死測試已刪,改為 `tests/integration/test_observe_ranking_config_wiring.py`(真跑 run_pipeline、不 mock 計算)。
- **F(m3 e2e 副作用隔離)PASSED**:改用 tmp_path 導向隔離目錄。驗收反解舊 pyc 確認**本批未新增任何 mock**、`run_pipeline` 仍真跑完整管線、斷言反而更強(多一條隔離斷言);連跑兩次 7/16 xlsx 的 sha256 與 mtime 皆不變。
- 測試:493(第一批)→ 496(494 −1 刪死測試 +2 參數化 +1 新增)。驗收員獨立重跑 `496 passed`,還原後複跑仍 496。
- 不可動清單零觸碰(signal_detector/backtester/benchmarks/threshold_calibration/sector_scoring/stock_scoring/finmind_fetcher mtime 全早於本批);FinMind DISABLED 區塊原樣;本批未重跑任何交易日、未重生成訊號檔。未 commit。
- 驗收零殘留:所有暫時改動皆備份+還原+sha256 比對;`outputs/`+`data/` 共 5,927 檔四次全量比對逐位一致。
- **第二批 backlog 已清空**;第一批遺留的 7/20 訊號檔已於當日稍早依使用者拍板重生成(53 事件)。
- 執行教訓(已驗證):Codex 經轉發層啟動會被 10 分鐘前台時限連帶殺死,須用 companion 原生 `--background`;companion 狀態面板會假 running / 丟任務紀錄,監視一律以 PID 存活為準,且任務登記需時,輪詢別太早放棄。

---
## [2026-07-28 14:30] 第三批:個股評分有效性診斷 — 對抗式驗收 REJECT(結論不可用,但揭露三個真問題)
- 規格:`.ai/tasks/TASK-daily-report-field.md`(第三批);Codex 報告:`Quant-Agent/_workbench/out/stock_score_diagnostic_2026-07-28/REPORT.md`;驗收報告:`Quant-Agent/_workbench/out/moneyflow_stock_diagnostic_verification_20260728.md`
- **工程紀律全部達標**:零副作用(data/ outputs/ 全目錄掃描,13:00 後 0 檔被改)、src/ 29 個 .py 零觸碰、無未來函數、重疊組合口徑、日序列 t-stat 皆真實做到。退件原因是**分析結論錯誤**,非工程失職。
- **錯誤 1(結論反向,最嚴重)**:`_price_path` 按股票列索引取 bar、median 分支卻按日曆日期彙總 → 出現 n=1 的「全市場中位數」(最大一筆 +224.77%,源自 `data/raw/ohlcv` 內 **804 列 close=0** 髒資料),單日 +81.4% 撐起整條基準曲線。原報告顯示 all_market_median 累積 65~119%(不可能)。真值:面板中位數買進持有 **−0.28%**、TAIEX **+15.46%**。**後果是反的:top-10/K=10 淨 +22.51% 其實贏過每一個誠實基準**(top-N 欄位走 mean 分支未被污染,已查證)。
- **錯誤 2(headline 誤導)**:表 A 判「通過」(Spearman 0.697)是假象。扣掉 DEGRADED 的 9 天後 Spearman → **0.079**,判定翻轉。且 `score_confidence` **不是資料品質分層而是純日期分層**(2026-04-20~04-30 全 DEGRADED、其餘 52 天全 FULL,同日混合 0 天),那 9 天是崩盤段,高分股「跌得少」被誤讀成選股力。另 decile n≥10,000 自承 met=False 卻仍寫 headline 通過。
- **錯誤 3(NW lag 過短)**:lag=3 對 10/20 日重疊報酬不足,修正為 h−1 後 t 值縮水 25~35%;乾淨子集 30 格 IC 僅剩 `score_volume@20d`(t=2.27)過關。
- **被推翻的兩個猜測**:①樣本流失 74% 非 join bug——61/68 天的評分宇宙本來就只有 ~567 檔,「~1,950 檔」自 2026-07-17 才開始且 OHLCV 快照也停在該日,故那 7 天完全用不到(Codex 寫「68 個 snapshot 全是 568 檔」為事實錯誤,實際 7 個是 ~1,960);②除權息 73.65% 不成立——母體用錯,面板實際僅 **9.4%** 未還原(54/571),且未還原組報酬反而較好(−1.20% vs −2.39%)。負超額真因是 TAIEX 市值加權 +15.46% 而中位數個股 −0.28%。
- **最刺眼的發現**:`score_volume` 與原始 `volume` 的 IC **逐位元組相同**(就是成交量百分位,是本波權值股行情的規模 beta)。決定性測試:**光買成交量最大 10 檔 = 淨 +39.2%,六因子評分只有 +22.5%** —— 整套評分輸給最笨的單一指標。
- **真實結論**:有一點選股力但不足以下注 —— 乾淨子集頭尾價差 +2.84%/t=2.45 顯著,但**十分位單調性為零**、D10 中位數仍為負(訊號全在右尾),且輸給「買量最大 10 檔」。落在分支 **B(只有尾端有訊號)+ A(權重配錯)**,但兩者都被「第四種:資料不足以定論」框住。
- 測試:驗收員獨立重跑 `504 passed`(496 基準 + 8 新增),與 Codex 收據一致。未 commit。
- **待辦(依 CP 值,未派工)**:P0 補抓 07-17 後行情 + 清 804 列 close=0(面板應從 34,584 → ~55,000+);並建議把「decile n≥10,000」門檻改為「每日每 decile ≥50 且累積 ≥40 天」(資料還沒長出來,硬卡 10,000 短期不可能過)。P1 修診斷腳本三處:median 基準日曆對齊、close≤0 視為缺漏、NW lag 改 `max(auto, h−1)`。P2 報告 headline 改以乾淨子集為準。**明確不建議**現在調 `DEFAULT_STOCK_WEIGHTS` 或動 `src/stock_scoring.py`(volume 的優勢是單一 regime 的規模 beta,調了就是曲線擬合)。
- 註:專案未納入版控(`git ls-files` = 0),不可動清單佐證改用 mtime。

---
## [2026-07-28 18:40] 第四批 P0/P1/P2 — 對抗式驗收 REJECT(三個核心目標無一達成,但卡點很小)
- 規格:`.ai/tasks/TASK-daily-report-field.md`(第四批);驗收報告:`Quant-Agent/_workbench/out/moneyflow_batch4_verification_20260728.md`
- **工程紀律全部乾淨**:`src/` 零改動、`DEFAULT_STOCK_WEIGHTS` 逐位元組未變、`data/`+`outputs/` 零副作用、**零網路呼叫屬實**(無 fetcher import、無網路符號)、未 commit。退件純因功能未達成。
- **P0 adapter 有生效,但寬宇宙 100% 被丟棄(真因已找到)**:9,809 列寬宇宙確實進了面板,`gross_1d` 9,796 筆 / `3d` 5,822 / `5d` 1,904 **都算得出來**,但 `market_*` 欄全空 → **TAIEX 快取停在 2026-07-17**。修法就在磁碟上(官方指數檔 `data/raw/market_index/twse_2026-07-18..24.json`),**零 API**。
- **P1-1 median 基準守錯變數,等於沒修**:守門寫成 `len(tranche_paths) < 30`(實測恆為 503~505,**從未觸發**),規格原文是 `len(returns) < 30`。K=5 基準仍 **+222.17%**(門檻 50%),比第三批的 +65% 更糟。改回規格原文即得 −2.70% / −1.15% / −1.05%(合理區間)。
- **形式測試**:`test_median_benchmark_requires_breadth...` 只餵 1 條路徑,對錯誤與正確實作**都會過** —— 正是應該抓到上述 bug 的那支測試。其餘 6 個新測試為真測試。
- **P1-3 NW lag 是唯一完整達成項**:`max(auto, h−1)` 受 `n−1` 上限,讀碼+實測 lag 3/3/4/9/19 全對。但 `score_volume@20d` 的 t 從 2.27 掉到 **0.73**(換資料源所致,非 lag 之故)。
- **兩個門檻差一點不達標非 off-by-one**(驗收員重算一致:48 / 39):窄宇宙 505÷10=50.5,是**規格門檻設計卡邊界**,不是執行問題。
- **新發現的兩個資料問題**:①`_price_path` 仍用列索引而非日曆對齊 → 停牌減資股(如 1435)造出 `gross_10d = +441%` 且落在 FULL 子集裡;②**舊版 TPEx schema 未處理**,少了 61 檔上櫃股 × 62 天。
- **真實結論(同口徑重算)**:日平均 D10−D1 從第三批的 +2.84%/t=2.45 掉到 **+1.82%/t=1.54**(未達顯著);Spearman **0.091**;十個 decile 中位數超額**全負**;30 格 IC 表 |t|>2 僅兩格且**方向都是反的**。**六因子評分仍輸給「買成交量最大 10 檔」**(全體 +22.18% vs +34.70%;FULL +16.02% vs +23.65%,三個持有期全輸)。落在**分支 D:資料仍不足以定案**。
- 測試:驗收員獨立重跑 `511 passed`(504 基準 + 7 新增),與 Codex 收據一致。
- **下一步(驗收員建議,依 CP 值)**:①**改兩處**(median 守門改回 `len(returns)`、TAIEX 快取接官方指數檔)—— 1~2 小時,立刻解鎖 9,796/5,822/1,904 筆寬宇宙樣本;②修 `_price_path` 列索引→日曆對齊 + 補舊版 TPEx schema;③時間估算:寬宇宙 **10 日 horizon 約 2026-09 底成熟、20 日約 2026-10 中**,但做完①後 **1/3/5 日結論 8 月上旬就能先出**。
- **仍不得調權重**(規格 §5、鐵則 5):volume 的優勢是單一 regime 的規模 beta。

---
## [2026-07-28 21:00] 第五批 F1~F5 — 對抗式驗收 PASS-WITH-CONCERNS(四個 bug 全部真修好)
- 規格:`.ai/tasks/TASK-daily-report-field.md`(第五批);驗收報告:`Quant-Agent/_workbench/out/moneyflow_batch5_verification_20260728.md`
- **四個 bug 全部真修好**:驗收員**獨立重建面板**(44,082 列/66 天),所有數字與 Codex 報告吻合到**小數第 6 位**。紅綠自證為真:親手把每個修復還原成舊寫法,**7 支測試確實轉紅**,還原後 sha256 逐位元組回基準。測試 511 → **520 passed**(新增 9 支)。
- **六個疑點:五個不成立,一個屬誠實揭露**
  - ①UNADJUSTED 99.99%**不成立**(我誤判):36,532 筆重疊 key 兩來源收盤價**100% 相同、最大相對差 0.0** —— FinMind 原本就是未還原價,「官方覆蓋掉已還原價」物理上不可能。還原機制仍有效(9,806 列真被縮放)。窄宇宙未還原僅 **9.3~9.5%**(=第四批的 9.4%,無倒退;第四批 REPORT 本身也是 0.9999)。
  - ②寬宇宙 5d=0**不成立,是必然**:唯一能算 gross_5d 的是「訊號 7/17→進場 7/20」那批,而 TAIEX 正好缺 7/20;其餘進場日都跑出 7/24。口徑亦不同(報告要 gross+market 皆非空,第四批的 1,904 只算 gross;同口徑重算得 **1,879**,對得上)。
  - ③解析失敗 14%**不成立**:31,908 筆 100% 是價格欄為 `"---"` 的當日零成交債券/反向 ETF。三方對帳完美(224,872 = 192,119 + 31,908 + 845)。
  - ④8,739 檔**不成立(零污染)**:其中 6,184 檔是權證,但 scored 檔裡**權證 0 檔**,權證從未進入面板。
  - ⑤7/27 未覆蓋**成立但誠實**:官方 OHLCV 最新只到 7/24,排程 log 自標 `DEFERRED_NOT_READY`。
  - ⑥紅綠自證**不成立(是真的)**:F1 測試精準構造「40 條路徑、每日 20 檔」;而**第四批那支形式測試在舊寫法下仍然通過**,決定性證實第四批驗收員判斷正確。
- **三個新 CONCERN(本批未解,列入待辦)**
  - **C1(HIGH)**:`market_1d` **結構上恆等於 0**(實測 n=42,160、unique=1)→ 那 7,747 筆「1 日解鎖」其實**沒有大盤基準**,`excess_1d ≡ gross_1d`,且已被新測試**固化成規格**。
  - **C2(HIGH)**:「十個 decile 全負」**約 22% 是量測人工產物** —— 個股從進場日 **open** 起算、大盤從 **close** 起算,差一整個盤中時段(實測 −0.25pp),**未揭露**。
  - **C3(MEDIUM)**:F2 最要害的「排除報酬指數」一行**無測試保護** —— 七個官方檔每個都同時含報酬指數,刪掉那行會讓七檔全被拒收、TAIEX **靜默退回 7/17**,而 24 支測試全綠。
- **工程紀律全部乾淨**:`src/` 零改動、`load_taiex` 未被碰、`DEFAULT_STOCK_WEIGHTS` sha256 與第四批相同、`data/` 零副作用、零網路呼叫、未 commit、只改規格允許的 5 個檔。
- **修完後的真實結論(比前批正面)**
  - 排序力**仍無**(Spearman 0.079),但**頭尾有微弱訊號**:驗收員補算日平均 D10−D1 = **+2.07%、t=1.82、72% 日為正**(第四批 +1.82%/t=1.54,**修完 bug 後改善**)。仍屬分支 D,但理由已從「面板有 bug」變成「**只有 43 個有效交易日**」。
  - **拿掉大盤基準看 gross,Spearman 升到 0.356、D1 明顯最差** —— 圖像比報告呈現的更正面(與 C2 的量測偏誤有關)。
  - **仍輸給「買量最大 10 檔」,三期全輸**(K=20 差 8.17pp);但六因子**贏過純動能、大幅贏過全市場中位數**。
  - `score_volume@1d` 是**真訊號**:IC 從 1d 的 −0.068 **單調翻轉**到 20d 的 +0.083(爆量→隔日跳空→盤中回吐→中期續強的教科書結構)。`score_institution@10d` 是**雜訊**(30 格裡 3 格 |t|>2,期望值 1.5;有效獨立樣本僅約 5)。
  - **報告與提問都漏掉一格**:`score_breakout` 五個 horizon **IC 全正**、20d **t=+2.27**、勝率 **79%** —— 是**最值得繼續 observe 的候選**。
- **下一步(驗收員建議)**:①修 C1 + 揭露 C2(半天);②補 7/20 TAIEX 與還原因子(各 1 小時,**但需使用者拍板同意一次連網**);③補一支測試守住 C3(10 分鐘)。**仍不要調權重** —— 本批新證據:volume 因子好壞**高度取決於持有期**,現在的 8pp 優勢很可能是 regime 產物。
