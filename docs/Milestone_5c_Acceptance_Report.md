# Milestone 5c Acceptance Report — Event-Study Backtest Core

**Date**: 2026-07-18
**Role**: Maker (implementation), pending independent verifier gate (same pattern as
M0-M5c-prep gates in `loop/PROJECT_STATE.md`).
**Environment**: `C:\Workspace_CN\taiwan_moneyflow_rotation\.venv`, `pytest -p
no:cacheprovider`.

**Conclusion level for every number in this report: 初步研究讀數 (PRELIMINARY RESEARCH
READING). NOT Research Ready.** See §7 for why, per SPEC_ADDENDUM A-3/B-1.

---

## 0. Headline (read this first)

Running the real 60-day (2026-04-20 to 2026-07-17), 53-sector signal history through the
new event-study engine against real FinMind OHLCV (571/1,963 stocks) and the real TAIEX
index:

| Signal Tier | Independent Events | Realized (10d) | Median Excess Return (net, 10d) | Win Rate | vs Momentum Baseline (median) |
|---|---|---|---|---|---|
| B級早期點火 | 30 | 27 | **-11.28%** | 0.0% | Baseline: -0.39% → **signal loses** |
| C級個股事件 | 23 | 19 | **-10.41%** | 26.3% | Baseline: -0.39% → **signal loses** |

**In plain terms**: over this specific 60-day window, sectors that got a B or C grade
signal did *worse* than the market by about 10-11 percentage points over the following
10 trading days (after subtracting trading costs), and worse than a naive "just buy
yesterday's strongest sector" baseline. Both grades' sample sizes (27 and 19 realized
events) are **below the 30-event minimum this project's own rubric requires to call
anything decisive** (SPEC_ADDENDUM B-3.3 "樣本不足不可裁決"). **No A-grade or 續漲訊號
event occurred at all** in the real 60-day dataset, so those two tiers have zero
evidence either way.

**The honest one-line verdict**: this dataset gives **no evidence of increment value**
for the new-gainer B/C signals over this window — if anything, the opposite — but the
sample is too small and too concentrated in one market regime (a strong ~10%/10-trading-
day TAIEX rally) to generalize from. This is exactly the kind of preliminary,
inconclusive-but-honestly-reported result SPEC_ADDENDUM A-3 anticipates; it does **not**
mean the underlying trading idea is proven bad, only that this particular
uncalibrated-threshold configuration, on this particular 60-day sample, shows no
measured edge.

---

## 1. What Was Built

### 1.1 `src/backtester.py` (full rewrite of the M0-M5c-prep stub)

- `extract_events`: SPEC 19.6 / SPEC_ADDENDUM B-3.1 first-signal-only event extraction.
  A sector's signal family (NEW_GAINER = A/B/C grades; CONTINUED_MOMENTUM = 續漲訊號)
  starts a new independent event the first day it appears after a gap (無訊號/無效) or a
  family switch; every subsequent consecutive day of the same family is "persistence,"
  tracked but never counted as a second independent event.
- `resolve_sector_member_stock_ids`: reuses `src/sector_features.py`'s exact membership
  rule (primary = exact match, never double-counted; theme = any of theme_1/2/3, may
  double-count) so return computation and feature computation agree on "who's in this
  sector."
- `compute_entry_price`: T+1-open entry with SPEC_ADDENDUM B-2.1 limit-up lockout
  (price+volume proxy, since no explicit "locked with zero liquidity" flag exists in the
  FinMind feed), both **exclude** and **postpone-to-T+2** accountings.
- `compute_stock_forward_returns` / `compute_sector_forward_returns` /
  `compute_market_forward_returns`: 1/3/5/10/20-day cumulative returns, sector return =
  cross-sectional median of tradable members (documented rationale in
  `docs/backtest_methodology.md` §3), `None` (never 0%) for any horizon not yet mature.
- `apply_trading_cost`: config-driven fee(×2)+tax+slippage, gross AND net columns always
  both reported.
- `Backtester.run_event_study`: orchestrates the above into one row per independent
  event, both limit-up accountings, SPEC_ADDENDUM A-2 outcome labels via `src/labels.py`
  (already-accepted M2 module, reused unmodified).
- `Backtester.simulate_trades` (legacy stub's per-stock-row contract): kept, not
  deleted, now built on the same underlying primitives — no caller in this codebase
  depended on its removal, so it's retained per "don't touch already-accepted behavior
  without a stated reason."
- `index_ohlcv_by_stock`: a pre-grouping performance helper (every OHLCV-consuming
  function accepts either a raw DataFrame or this pre-built dict). **A real
  correctness bug was caught and reverted during this session**: an earlier attempt
  memoized per-stock history by `id(df_ohlcv_history)`, which is unsafe — CPython
  reuses freed objects' memory addresses, so two unrelated small DataFrames (e.g. two
  different unit tests) could collide on the same `id()` and silently return the wrong
  stock's cached history. Caught by the test suite itself (4 failures), reverted, and
  replaced with this explicit caller-owned index instead. Documented in the function's
  own docstring as a "don't repeat this mistake" note.

### 1.2 `src/benchmarks.py` (new, SPEC_ADDENDUM A-3)

- `momentum_extension_baseline`: daily-rebalanced "buy yesterday's highest-score sector"
  heuristic, same T+1-open entry convention as the real signals.
- `random_sector_bootstrap_baseline`: N-draw (10,000 in the real report, per
  SPEC_ADDENDUM 3.2) uniform-random `(sector, date)` sampling with forward returns,
  fixed `random_seed=42` for exact reproducibility (recorded in the output's `.attrs`
  and the JSON summary).
- `bootstrap_confidence_interval`: simple percentile bootstrap CI of a mean (SPEC 19.4).

### 1.3 `scripts/run_backtest.py` (new orchestrator)

Loads all 60 days of on-disk signals/scored-frames/FinMind-OHLCV/TAIEX, runs the event
study + both benchmarks, writes `outputs/backtests/backtest_report_<date>.xlsx` (4
sheets: Headline, Event Detail, Momentum Baseline, Random Baseline sample) plus raw CSV
dumps of every frame (`backtest_events_<date>.csv`, `backtest_momentum_baseline_<date>
.csv`, `backtest_random_baseline_<date>.csv`) and a `backtest_summary_<date>.json`.
Read-only with respect to every already-accepted `data/raw`/`data/processed` artifact.

### 1.4 `scripts/fetch_history_finmind.py` (additive CLI flag only)

Added `--sleep-between <seconds>` (default `None`, meaning **exact unchanged behavior**
— `FinMindFetcher`'s own `POLITE_DELAY_SEC=1.0s` default is untouched unless this flag
is explicitly passed). `run_backfill()` gained a matching optional `sleep_between_sec`
parameter, purely additive. No existing call site, test, or default changed. See §6 for
the drip backfill this enables.

### 1.5 `docs/backtest_methodology.md` (new)

Full methodology writeup: event definition, no-future-function guarantee, sector-return
convention and rationale, Taiwan-specific rules (limit-up / disposition / ex-dividend —
including the honest "ex-dividend is NOT implemented" disclosure), cost model, and a
dedicated §6 "Known Data Limitations" section listing all 5 required disclosures.

---

## 2. Real Results (from the actual 60-day dataset, not synthetic)

**Run**: `python scripts/run_backtest.py --n-bootstrap 10000 --report-date 2026-07-18`
**Elapsed**: 2m41.7s (initial unoptimized attempt exceeded 6+ minutes and was killed;
see §5 for the correctness-preserving performance fix that made this run practical)

### 2.1 Independent Event Count

**53 total independent events** across the full 60-day/53-sector dataset (47 `primary`
sector-type, 6 `theme`). This is far below what a healthy per-grade event study would
want, for a structural reason disclosed in `docs/backtest_methodology.md` §1: **the real
signal detector output has ZERO `無訊號`/`無效` rows anywhere in the entire 2,765-row,
60-day dataset** — every sector that is ever scored carries a graded B or C signal on
literally every day it appears (verified directly, not assumed). Under the correct SPEC
19.6 "first occurrence = event" rule, this collapses almost the entire dataset into
persistence of a small number of already-open events: 46 of the 53 events fire on
2026-04-20 (the first day any prior-day comparison is even possible — a cold-start
artifact of the 60-day window's left edge, not genuine "ignition"), and 7 more fire on
2026-07-17 (sectors appearing for the first time on the data endpoint's last day, all
UNTRADABLE for lack of forward data — see §2.3).

### 2.2 Headline Per-Tier Statistics (10-day horizon, net of cost)

| Signal Tier | n_events | n_realized | median excess % | mean excess % | win rate | n≥30? |
|---|---|---|---|---|---|---|
| B級早期點火 | 30 | 27 | -11.28% | -10.42% | 0.0% | **NO** |
| C級個股事件 | 23 | 19 | -10.41% | -5.46% | 26.3% | **NO** |
| A級新起漲 | 0 | — | — | — | — | — (no events occurred) |
| 續漲訊號 | 0 | — | — | — | — | — (no events occurred) |

90%-CI (2,000-resample bootstrap of the mean, net excess return, per horizon) — full
table in `outputs/backtests/backtest_summary_2026-07-18.json`'s source data
(`backtest_events_2026-07-18.csv`):

- B級 10d: mean -10.42%, CI [-11.44%, -9.33%] (n=27) — the whole CI is negative.
- C級 10d: mean -5.46%, CI [-11.52%, +2.11%] (n=19) — CI straddles zero (genuinely
  inconclusive at this sample size).

### 2.3 UNTRADABLE Accounting (both conventions, per SPEC_ADDENDUM B-2.1)

| | exclude | postpone (T+2) |
|---|---|---|
| TRADABLE | 46 | 46 |
| UNTRADABLE | 7 | 7 |

**Important disclosure**: all 7 UNTRADABLE events are on 2026-07-17 (the data
endpoint's last day) and are **NOT limit-up lockouts** — they are sectors whose member
stocks have zero FinMind OHLCV history at all (the 571/1,963 coverage gap, §7.1),
confirmed by direct file inspection (e.g. `數位雲端`'s 11 members include stock_ids
3130/6165/6614/etc, none of which have a `data/raw/ohlcv/finmind_<id>.json` file on
disk). The `exclude` vs `postpone` conventions produce identical counts here because the
underlying problem is "no data exists," not "T+1 was locked and T+2 wasn't" — postponing
an entry by one day cannot fix a stock that has zero history in either source. **Zero
events in the realized 46 hit a genuine price-based limit-up lock this run** (none of
the 46 TRADABLE events' T+1 opens matched the limit-up proxy threshold) — a finding
worth noting on its own: this dataset happened not to exercise the limit-up lockout path
at all, so P0-06's limit-up logic is validated by unit test (§4) but not by a real
observed lockout in this particular 60-day sample.

### 2.4 vs Momentum Extension Baseline (10-day horizon)

| Signal Tier | Signal median (n) | Baseline median (n) | Beats baseline? |
|---|---|---|---|
| B級早期點火 | -11.28% (27) | -0.39% (51) | **NO** |
| C級個股事件 | -10.41% (19) | -0.39% (51) | **NO** |

Per SPEC_ADDENDUM A-3.3: "新起漲/續漲訊號的超額報酬必須顯著優於動能延續基準,否則判定
「無增量價值」." Both grades' median excess return underperforms the momentum baseline's
median by roughly 10 percentage points at the 10-day horizon. **Per the addendum's own
rule, this dataset supports "無增量價值證據" (no evidence of incremental value) for both
B級 and C級 over this window** — reported plainly, not softened. This is a descriptive
median comparison, not a formal significance test (see `docs/backtest_methodology.md`
§7 for why a t-test would be misleading at n<30).

### 2.5 Random Sector Bootstrap Baseline

N=10,000 requested, 9,794 draws resolved (206 draws landed on a `(sector, date)` with
zero tradable FinMind-covered members and were skipped rather than fabricated),
`random_seed=42`. 10-day excess return distribution: mean -2.53%, median -2.34%, std
7.14%, min -107.2%, max +55.1% (n=8,697 realized). The wide spread and negative median
reflect the same single-regime (strong-rally) window every other number in this report
was computed from — a random sector, held through this specific 10-day rally window,
still tends to trail the index because the index itself rallied unusually hard.

---

## 3. Statistical Discipline (SPEC_ADDENDUM B-3.3)

- **Independent event count, not signal-row count, used throughout**: 53 events, not
  2,765 signal rows. Every headline table above uses `n_events`/`n_realized`, never the
  raw row count.
- **n<30 explicitly flagged**: `sample_sufficient` column in
  `backtest_summary_2026-07-18.json` is `False` for both B級 (n=27) and C級 (n=19) —
  neither tier meets this project's own 30-event decisiveness bar, let alone
  SPEC_ADDENDUM B-1.4's 50-event-per-grade bar for removing the "research candidate"
  label.
- **Parameter combinations tested this round**: exactly **1** (`config/default.yaml` as
  shipped; "postpone" is an alternative *accounting convention* for the same run, not a
  second tuned configuration). Recorded as `n_param_combinations_tested: 1` in the
  summary JSON, per the addendum's multiple-comparison honesty requirement.
- **Event overlap warning**: `primary` and `theme` sector types are tracked as fully
  independent series (a stock can be double-counted across multiple `theme` sectors);
  every headline table is implicitly summed across both types without separate
  breakdown by type in this report's top-level numbers (47 primary + 6 theme = 53) —
  the per-event detail CSV carries `sector_type` for anyone who needs the split.

---

## 4. Tests

### 4.1 New Test Files

- `tests/unit/test_backtester.py` (30 tests): event extraction (first-day/gap-reset/
  grade-change-is-persistence/family-switch-is-new-event/independent-sector-tracking),
  sector membership resolution, limit-up lockout (locked/unlocked/postponed/both-days-
  locked/missing-volume-fail-closed/no-T+1-bar-is-pending), forward returns (basic/
  missing-horizon-is-None/sector-median/below-min-constituents), market returns, cost
  application, disposition penalty wiring, cost-config wiring, and two end-to-end
  `run_event_study` scenarios (small synthetic universe; untradable event).
- `tests/unit/test_benchmarks.py` (9 tests): momentum baseline sector selection (prior-
  day-only, NaN-score exclusion), random bootstrap reproducibility/seed recording/empty-
  universe handling, bootstrap CI basic/empty/NaN-filtering behavior.
- `tests/leakage/test_backtester_no_future_function.py` (3 tests, SPEC 19.1 / §26.6
  spirit): truncated-vs-full-dataset event-return equivalence (30-day synthetic universe
  truncated to exactly the first event's 20-day-horizon maturity point — every gross/
  net/excess return and the outcome label are asserted byte-identical between the
  truncated and full runs), appending-future-bars-does-not-change-already-realized-
  returns, and an event whose horizon hasn't matured yet correctly reports PENDING
  (never a fabricated return).

### 4.2 Full Suite Result

```
C:\Workspace_CN\taiwan_moneyflow_rotation\.venv\Scripts\python.exe -m pytest tests -p no:cacheprovider -q
```

**291 passed, 0 failed, 0 skipped** (249 pre-existing M0-M5c-prep tests, all still
green + 42 new M5c tests: 30 + 9 + 3). Full log saved at
`loop/evidence/test_logs/pytest_m5c_run_log.txt`.

Last line of the log:
```
291 passed in 38.64s
```

---

## 5. A Real Bug Caught and Fixed Mid-Session (Performance Optimization)

The first full-report attempt (N=10,000 bootstrap draws) was killed after 6+ minutes
because the naive per-lookup DataFrame filter (`df[df.stock_id==x]` re-scanning the full
~35,000-row, 571-stock OHLCV frame on every single stock lookup, potentially tens of
thousands of times across 10,000 draws) made it impractically slow.

**First fix attempt was itself buggy and was caught by the test suite, not shipped**: an
identity-keyed cache (`{id(df_ohlcv_history): ...}`) was tried first — this is unsafe in
CPython because a garbage-collected object's memory address can be reused by an
unrelated, differently-contented object, so two different small test DataFrames could
collide on the same cache key and silently return the WRONG stock's history. Running the
test suite immediately after this "optimization" surfaced 4 real failures (wrong return
values, e.g. `0.05 == 0.01` assertion failure) — caught before it ever reached the real
data run, reverted in full.

**The actual fix shipped**: `index_ohlcv_by_stock()`, an explicit, caller-owned
pre-grouping (`{stock_id: sorted DataFrame}`) built once per real `df_ohlcv_history` the
orchestrator/benchmark functions intend to reuse, with no implicit identity-based
caching anywhere. Every function that accepts `df_ohlcv_history` now accepts either the
raw DataFrame (simple, safe, used by all existing unit tests unchanged) or this
pre-built dict (fast path). Result: the same N=10,000 bootstrap run that was killed
after 6+ minutes with no end in sight completed in 2m39s end-to-end (including the
event study and momentum baseline) once wired through `scripts/run_backtest.py` and
`src/benchmarks.py`. All 42 new tests plus the full 249-test baseline pass identically
before and after this change — this was purely a performance fix, not a behavior
change, and the buggy intermediate version never touched the real report output.

---

## 6. FinMind Drip Backfill (Completion Step)

Per the task's optional completion step, a slow, detached background drip backfill was
launched to keep resuming the still-incomplete institutional/margin FinMind backfill
(26/1,963 and 2/1,963 respectively as of M5c-prep) without blocking this session, using
the newly-added `--sleep-between` flag at 50 seconds (within the M5c brief's 45-60s
range) and the `--no-resume`-free (i.e. resumable) default:

```
Start-Process -FilePath "C:\Workspace_CN\taiwan_moneyflow_rotation\.venv\Scripts\python.exe" `
  -ArgumentList "scripts/fetch_history_finmind.py","--start","2026-04-20","--end","2026-07-17","--sleep-between","50" `
  -WorkingDirectory "C:\Workspace_CN\taiwan_moneyflow_rotation" `
  -RedirectStandardOutput "outputs/logs/finmind_drip.log" `
  -RedirectStandardError "outputs/logs/finmind_drip_err.log" `
  -WindowStyle Hidden -PassThru
```

**Confirmed launched**: PID **2924**, started 2026-07-18 15:33:27, detached (survives
this session). First log lines confirm real resumption, not a no-op: skipped the
already-covered TAIEX/stock-info fetches (`skip_existing`), then began fetching new
per-stock OHLCV series starting with stock 2941 (62 rows, previously missing from the
571/1,963 baseline) — `outputs/logs/finmind_drip.log`. Category order used the CLI's
documented default (`ohlcv` first, then `institutional`, then `margin`) since this
session's instruction did not specify a category override; institutional/margin will
resume once the OHLCV pass reaches FinMind's rate limit or completes. At 50s/request
and ~1,392 remaining OHLCV stocks alone, this will run for many hours — left running
unattended per the task's "background drip" intent, not waited on synchronously.

---

## 7. Known Limitations (must-read; full detail in `docs/backtest_methodology.md` §6)

1. **FinMind OHLCV coverage is 571/1,963 stocks (29.1%)** — any sector's forward return
   this report computes may be based on a partial, possibly unrepresentative subset of
   its true membership. `member_stock_count` vs `tradable_member_count` in the event
   detail CSV make this gap visible per-event, not averaged away.
2. **Institutional/margin historical coverage is near-zero** (26/1,963, 2/1,963) — the
   signal detector's institutional condition falls back to the documented neutral 50.0
   prior for nearly the entire historical window, so any apparent institutional pattern
   in these historical signals is largely a fallback artifact, not real historical flow.
3. **All signal-detector thresholds are uncalibrated placeholders**
   (`config/default.yaml`, every relevant key marked `# PLACEHOLDER - UNCALIBRATED`) —
   this report describes what these specific uncalibrated numbers emit, not a claim that
   they're good numbers.
4. **60 days is one single market regime** (a strong TAIEX rally, confirmed +10.3% over
   just the first 10 trading days of the window) with zero environment stratification
   (SPEC §18 defers this to more accumulated history). Every number in this report
   describes performance specifically during a strong bull run and should not be read as
   representative of sideways or bear-market behavior.
5. **No ex-dividend/adjusted-price handling** — no `adjusted_close` field exists
   anywhere in this project's data pipeline. This window runs directly into the
   July-September dividend season the addendum names explicitly; any event whose holding
   window crosses a real ex-dividend date will show an unadjusted, artificially negative
   price move unrelated to actual performance. **Not implemented, not silently patched.**
6. **No disposition/caution stock list exists on disk** — the weight-penalty mechanism
   is implemented and unit-tested but every real event this run had an empty disposition
   set, so `has_disposition_member=False` for all 53 real events (not "verified clean,"
   simply "not checked").
7. **Only 1 parameter configuration tested** this milestone — no sensitivity analysis,
   no walk-forward validation (SPEC Ch.19.3/20), both correctly out of scope for this
   milestone's brief (event-study engine + benchmarks only) and would require materially
   more historical data to be meaningful anyway.
8. **No A-grade or 續漲訊號 events occurred** in the real dataset — those two tiers have
   literally zero evidence, not weak evidence.
9. **The independent-event count (53) falls far short of SPEC_ADDENDUM B-1.4's 50-per-
   grade bar** — a structural consequence of the real signal detector emitting a graded
   B/C signal on effectively every sector-day in this window (zero 無訊號/無效 rows in
   2,765 total), not a bug in the event-extraction logic itself (verified correct by 6
   dedicated unit tests). A future milestone with a longer, more varied history and/or
   recalibrated (harder-to-trigger) thresholds would be needed to accumulate a genuinely
   decisive per-grade sample.

## 8. Explicitly NOT Claimed

This report does **not** claim: Research Ready status (SPEC §28.2); that the B/C-grade
signals have negative true expected value (the sample is too small/short/single-regime
to conclude that either — only that this specific test found no positive evidence);
that limit-up lockout logic has been validated against a real observed lockout (none
occurred in this sample; validated by unit test only); or that ex-dividend/disposition
handling is complete (both explicitly disclosed as unimplemented/unused, §7.5-6).
