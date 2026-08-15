# Milestone 9 — Threshold Quantile Calibration + Backtest Rerun

**Date**: 2026-07-21
**Role**: Maker (implementation), pending independent verifier gate.
**Conclusion level for every number in this report: 初步研究讀數 (PRELIMINARY RESEARCH
READING). NOT Research Ready, NOT "已校準完成".**

---

## 0. Headline (read this first)

**In plain terms**: we swapped in real, near-full-market margin/short-sale data (was
almost entirely missing before), turned the system's fixed absolute score cutoffs into
adaptive ones that adjust to each sector's own recent history, and reran the same
backtest. **The backtest numbers did not change at all** — both before and after
calibration, the same 53 trading events show B-grade signals losing to the market by a
median 11.28 percentage points over 10 days, and C-grade losing by 10.99 points, both
still worse than a simple "hold whatever was strongest yesterday" baseline. This isn't
because calibration didn't work — it demonstrably changed which grade 84 sector-days
got labeled — but because of a structural quirk in how "independent event" is counted
(explained in §3), literally every one of the 53 events this dataset can measure fires
on either the very first day of history (before any calibration data exists) or a day
with zero tradable data. **So this round's calibration work is real and correctly
implemented, but this particular 28-day, non-contiguous sample cannot show whether it
helps or hurts — that requires more accumulated history.**

| | Before (uncalibrated, real margin data) | After (calibrated) |
|---|---|---|
| Independent events | 53 | 53 (byte-identical event set) |
| B級早期點火 median 10d net excess | **-11.28%** (n=27, n_realized=24) | **-11.28%** (identical) |
| C級個股事件 median 10d net excess | **-10.99%** (n=26, n_realized=22) | **-10.99%** (identical) |
| B級 win rate | 0.0% | 0.0% (identical) |
| C級 win rate | 22.7% | 22.7% (identical) |
| vs momentum baseline (-0.39% median) | both signal tiers lose | both signal tiers lose (identical) |
| Sample sufficient (n≥30)? | **NO** for both tiers | **NO** for both tiers |

**Honest verdict**: no evidence either way that quantile calibration changes the
system's predictive value, because the event-study engine's "first occurrence only"
rule (already-accepted M5c methodology, not touched this round) concentrates every
measurable event onto days before calibration has enough history to act, or onto a day
with no tradable forward data. See §3 for the full mechanism, verified directly (not
inferred).

---

## 1. Step 0 — Margin Data Pipeline Wiring (real fix, not symbolic)

**Finding**: before this session, `data/raw/margin/twse_official_<date>.json` /
`tpex_official_<date>.json` (63 trading days, near-full-market coverage, backfilled in
the prior session per `docs/Margin_History_Backfill_Report.md`) were **not read by any
part of the live pipeline**. `scripts/run_daily.py::run_pipeline` only ever reads
`data/raw/margin/margin_<date>.json` / `tpex_margin_<date>.json` (the legacy filenames),
which were populated only by the FinMind per-stock bridge (near-zero coverage, 2/1963
stocks) or same-day official fetches. Confirmed by direct code read of
`src/data_loader.py`, `src/data_cleaner.py`, and `scripts/run_daily.py` — none reference
the `twse_official_`/`tpex_official_` prefix.

**Fix**: new `scripts/prepare_official_margin_history_snapshot.py` bridges the two new
official-history files into the legacy filenames `run_pipeline` reads, for every date
where both sides exist. The payloads on disk were already fully transformed by the
prior session's `scripts/backfill_margin_history.py` (via
`transform_twse_margin_rows`/`transform_tpex_margin_rows`), so this bridge is a pure
copy — no re-transformation (re-applying the transform to already-transformed data
would have corrupted it; caught during dry-run testing on 2026-04-20 before the full
backfill, see the bridge script's own docstring for the mechanism).

**Verification (real, not symbolic)**: ran `scripts/prepare_official_margin_history_snapshot.py --start 2026-04-20 --end 2026-07-20 --force`
(63/63 trading days bridged), then hand-verified via `DataCleaner.clean_margin_data`
directly:

```
df.shape = (1831, 9)   # was (2, 9) via the old FinMind-only legacy files
market_type counts: TWSE 1048, TPEx 783
margin_buy non-null: 1831 of 1831
```

This is the real coverage jump this milestone's data now reflects: from ~2 stocks/day
to ~1,831 stocks/day of real margin/short-sale data feeding
`InstitutionalFeatures`/`MarginFeatures`/`SectorScoring`'s "institution" sub-factor —
7 new unit tests in `tests/unit/test_prepare_official_margin_history_snapshot.py`.

---

## 2. A Real Regression Found: BLOCKED_LOW_DQ Jumped from 2/62 to 34/62

Rerunning `scripts/run_history_pipeline.py --use-finmind` with the newly-wired margin
data produced **28/62 SUCCESS, 34/62 BLOCKED_LOW_DQ** — a severe regression from the
prior M5c-prep milestone's 60/62 SUCCESS (only 2 blocked: 2026-07-14/15, genuinely thin
data).

**Root cause, verified directly (not guessed)**: `src/data_validator.py::calculate_quality_score`
never actually reads its `df_margin` parameter in its scoring formula (confirmed by
`grep` — margin data has zero effect on the DQ score). The real cause is
`src/data_cleaner.py::reconcile_with_leaderboard`, which compares this system's own
open-to-close `daily_return` against the leaderboard Excel's prev-close-basis 漲跌幅 —
**a basis mismatch disclosed since Milestone 3** (`docs/Milestone_3_Acceptance_Report.md`
§6: "Pre-existing M1 logic, disclosed rather than silently patched"). At M5c-prep time,
FinMind OHLCV coverage was only 571/1,963 stocks (29%), so most leaderboard tickers
found no match in `df_prices` and were silently skipped by the reconciliation check.
**FinMind OHLCV coverage is now 1,963/1,963 (100%)** (confirmed: `ls data/raw/ohlcv/finmind_*.json | wc -l` = 1963) — every leaderboard ticker now finds
a match, so the pre-existing basis mismatch now triggers `WARNING_HIGH_DEVIATION` (a
-15 point DQ penalty) on most days, pushing DQ below the 70-point BLOCKED threshold.

**This is not something introduced this session** — `reconcile_with_leaderboard` and
`calculate_quality_score` were not modified (verified: neither file appears in this
session's diff). It is a real, previously-latent consequence of OHLCV coverage
improving, now surfacing at scale for the first time. **Out of this milestone's
authorized scope to fix** (governance rule: only calibrate `sector_scoring.py`/
`signal_detector.py` thresholds, not statistical/reconciliation methodology) — disclosed
here rather than silently patched or hidden.

**Practical consequence**: this milestone's calibration and backtest work is based on
**28 non-contiguous trading days** (2026-04-20 to 2026-07-17, with large gaps), not the
full 62-day range. This is a real, material sample-size constraint on everything below.

---

## 3. Calibration Methodology

### 3.1 What was calibrated

Per SPEC_ADDENDUM B-1.3 ("M5 校準後，門檻改以「分位數」形式定義...不用絕對數字"), new
module `src/threshold_calibration.py`:

- `rolling_quantile_threshold(df_history, sector_name, metric_col, trade_date, quantile, fallback_value, min_periods=10)`:
  returns the `quantile`-th percentile of `metric_col` for `sector_name`, computed
  **only from rows strictly before `trade_date`** (never today's own value, never a
  future date — verified by 4 dedicated leakage tests, see §5). Falls back to the
  original absolute PLACEHOLDER when fewer than `min_periods=10` prior observations
  exist for that sector.
- `build_calibrated_new_gainer_config` / `build_calibrated_continued_momentum_config`:
  apply this per-sector, per-day, to exactly **3 of the 17 total threshold keys**:
  - `new_gainer.min_score` (rule 1): calibrated to the sector's own 85th percentile
    (SPEC_ADDENDUM's own literal example).
  - `new_gainer.prev_score_max` (rule 2): calibrated to the sector's own median (50th
    percentile).
  - `continued_momentum.min_score` (rule 1): calibrated to the sector's own 70th
    percentile.

**Why only these 3, not all 17**: these are the ones directly implicated in the M5c/M9
finding that a fixed `min_score` bar interacts with `signal_detector.py`'s C-grade
fallback ("if any of 10 conditions passed, grade C") to produce a signal on
effectively every sector-day. Calibrating all 17 thresholds off ~28 days of history
(often fewer than 10 same-sector observations for many sectors) would produce
estimates far less reliable than even these 3, and SPEC_ADDENDUM B-1.4 already gates
full threshold acceptance on 50 independent events per grade — a bar this dataset does
not meet regardless.

### 3.2 Honest small-sample disclosure

- **n=28 trading days, non-contiguous** (large gaps from the DQ regression in §2). A
  rolling quantile computed from 10-28 same-sector observations is a directionally
  reasonable first cut, **not a statistically robust estimate**.
- **Quantile choices (85th/50th/70th) are this session's judgment calls**, not derived
  from an independent parameter sweep against this same dataset (sweeping and then
  reporting the best-looking choice against the same 28-day sample used for the
  backtest would itself be an undisclosed multiple-comparison problem per
  SPEC_ADDENDUM B-3.3). Only 85th percentile (new-gainer rule 1) is the addendum's own
  literal example; the other two are reasonable analogues, not independently validated.
- **No genuine walk-forward validation across market regimes** — all 28 days fall in
  the same single bull-market window already disclosed in M5c/M7/M8.
- **Sector-level, not market-pooled**: `rolling_quantile_threshold` computes each
  sector's own history (matching SPEC_ADDENDUM's literal "自身滾動歷史" wording), not a
  market-wide pooled distribution. Most sectors have close to the full 28 observations
  (median 28 per sector, confirmed) since they are persistent industry categories
  scored on every successful day, not sporadic — this made a genuinely per-sector
  quantile feasible despite the small n, but 28 observations is still a small sample by
  any statistical standard.
- **No data leakage**: verified by construction (strict `<` date filter, never `<=`)
  and by 4 dedicated tests in `tests/leakage/test_threshold_calibration_no_future_function.py`
  (truncated-vs-full equivalence, future-row-append invariance, own-day-exclusion,
  end-to-end `build_calibrated_new_gainer_config` equivalence).

### 3.3 Wiring (opt-in, zero effect on existing callers)

`SignalDetector.__init__` gained two new optional parameters,
`use_calibrated_thresholds: bool = False` and `df_sector_history: Optional[pd.DataFrame] = None`,
both defaulting to exactly pre-M9 behavior. `scripts/run_daily.py::run_pipeline` gained
a matching `use_calibrated_thresholds: bool = False` parameter, threaded through to
`SignalDetector` using the already-accumulated `df_scored_sector_history` frame.
`scripts/run_history_pipeline.py` gained a `--calibrated` CLI flag and matching
`use_calibrated_thresholds` parameter. **No existing caller's behavior changes unless
it explicitly opts in** — proven by `TestCalibratedThresholds::test_default_off_preserves_exact_pre_m9_behavior`.

### 3.4 Signal distribution: before vs after (does calibration do anything at all?)

Across the 28 successfully-processed dates (1,294 sector-day rows):

| | Before (fixed thresholds) | After (calibrated) |
|---|---|---|
| B級早期點火 (count) | 144 | **228** (+84, +58%) |
| C級個股事件 (count) | 1,150 | **1,066** (-84) |
| 無訊號/無效 (count) | 0 | 0 (unchanged — see §3.5) |

Calibration is genuinely doing something: 84 of 1,294 sector-day rows (6.5%) were
upgraded from C-grade to B-grade once enough rolling history existed (first possible on
2026-05-05, the 11th trading day counting from 2026-04-20, once `MIN_CALIBRATION_PERIODS=10`
is satisfied). Direct row-by-row diff confirms every changed row is a C→B upgrade, never
a downgrade or a flip to 無訊號.

### 3.5 Did calibration fix the "signal every single day" problem? Honestly: no.

The root cause disclosed in the M5c report was never really "min_score is set to 70" —
it is `signal_detector.py::_grade_new_gainer`'s C-grade fallback: **"if even one of the
10 numbered conditions passed, grade C"** — a condition virtually always satisfied by
something (e.g. rule 7's top1_concentration<=70% passes easily). Calibrating `min_score`
downward (which is what an 85th-percentile-of-a-47-mean-distribution calibration
mechanically does — see §3.6) makes MORE sectors pass rule 1 and get upgraded to B, but
does **not** reduce the count of sectors receiving *some* signal every day, because that
count was never driven by rule 1 in the first place. **This is a grading-logic
interaction, not a threshold-calibration problem, and grading logic is explicitly out
of this milestone's authorized scope** (only thresholds/weights, not statistical
methodology). Disclosed honestly rather than claimed fixed.

### 3.6 Why calibration lowered the bar rather than raising it

The real `score` distribution across the 28-day/1,294-row sample: mean 46.75, std
13.96, 75th percentile 57.30, max 77.11. The fixed `min_score=70` sits near the
**historical maximum**, so it is rarely reached (this IS exactly the "score never
crosses 70" finding from M5c). An 85th-percentile-of-own-history calibration for a
"cold" sector whose scores cluster around 30-45 produces a calibrated `min_score`
around 40-50 — **lower** than the fixed 70, not higher. This is the correct, intended
behavior of self-relative calibration (a sector's own "unusually high for it" can be
an absolute 45 if it's normally very quiet) — but it means calibration in this
direction makes MORE things pass rule 1, the opposite of what would be needed to
reduce "signal every day." Reported as-is, not softened.

---

## 4. Backtest Rerun — Full Method

1. Restarted the calibrated 62-day historical pipeline run
   (`scripts/run_history_pipeline.py --start 2026-04-20 --end 2026-07-20 --use-finmind --calibrated`)
   to completion: **28/62 SUCCESS, 34/62 BLOCKED_LOW_DQ, identical blocked-date set to
   the uncalibrated run** (confirms the DQ regression in §2 is unrelated to
   calibration — it fires identically either way).
2. To isolate calibration's effect cleanly (not mixed with stale pre-margin-update
   data left over from the prior M5c-prep milestone for the 34 blocked dates), both
   the "before" and "after" backtest runs were restricted to **exactly the same 28
   dates that succeeded in both the calibrated and uncalibrated margin-updated runs**
   — an honest apples-to-apples comparison, not a full-62-day comparison (which this
   session's data does not support).
3. `scripts/run_backtest.py --n-bootstrap 10000` run twice, once against each isolated
   28-date signal/scored-frame set (`--report-date 2026-07-21-m9-uncalibrated` /
   `-m9-calibrated`). Same OHLCV/TAIEX/disposition inputs both times (those are not
   affected by signal-detector calibration).
4. Backups of the pre-rerun uncalibrated processed/signal state:
   `data/processed/_bak_m9_uncalibrated_20260721_114738/`,
   `outputs/signals/_bak_m9_uncalibrated_20260721_114738/` (122 + 61 files).

### 4.1 Full headline comparison (10-day horizon, net of cost)

| Signal Tier | Metric | Before (uncalibrated) | After (calibrated) | Changed? |
|---|---|---|---|---|
| B級早期點火 | n_events | 27 | 27 | No |
| B級早期點火 | n_realized | 24 | 24 | No |
| B級早期點火 | median excess % | -11.28% | -11.28% | **No — byte-identical** |
| B級早期點火 | mean excess % | -10.27% | -10.27% | No |
| B級早期點火 | win rate | 0.0% | 0.0% | No |
| C級個股事件 | n_events | 26 | 26 | No |
| C級個股事件 | n_realized | 22 | 22 | No |
| C級個股事件 | median excess % | -10.99% | -10.99% | **No — byte-identical** |
| C級個股事件 | mean excess % | -6.27% | -6.27% | No |
| C級個股事件 | win rate | 22.7% | 22.7% | No |
| vs momentum baseline (-0.39% median, n=25/26) | both tiers | LOSE | LOSE | No |
| A級新起漲 events | | 0 | 0 | No |
| 續漲訊號 events | | 0 | 0 | No |
| Total independent events | | 53 | 53 | **No — byte-identical event CSVs** |
| n≥30 sample-sufficient? | | NO (both tiers) | NO (both tiers) | No |

`diff -q backtest_events_2026-07-21-m9-uncalibrated.csv backtest_events_2026-07-21-m9-calibrated.csv`
→ **zero differences, confirmed byte-for-byte identical.**

### 4.2 Why identical — the exact mechanism, verified directly

Every one of the 53 independent events' first-occurrence `trade_date` falls on either:
- **2026-04-20** (46 events) — the cold-start day. It is literally the FIRST day in
  the entire history, so `rolling_quantile_threshold` has zero prior observations for
  every sector and falls back to the fixed absolute threshold **by construction**,
  identically whether `use_calibrated_thresholds` is True or False.
- **2026-07-17** (7 events) — all UNTRADABLE (zero FinMind OHLCV history for those
  sectors' member stocks, same root cause disclosed in the M5c report), contributing
  no realized return either way.

The 84 grade changes calibration DOES produce (§3.4, starting 2026-05-05 once enough
history exists) are all **persistence days of already-open events** under the M5c/
SPEC_ADDENDUM B-3.1 "first occurrence only" event-extraction rule — a sector that was
already B or C graded the day before never starts a new independent event just because
its grade changed. **This dataset's event-extraction structure makes it
mathematically impossible for this round's calibration to move the headline
event-study numbers at all**, regardless of whether the underlying threshold change is
good or bad. This is a genuine, verified structural finding — not a bug in either the
calibration code or the event extraction (both are independently unit- and
leakage-tested), and not something either module's PLACEHOLDER/CALIBRATED status
claims to fix.

---

## 5. Tests

- `tests/unit/test_threshold_calibration.py` (17 tests): known small-sample quantile
  values, fallback-below-min-periods, exactly-min-periods boundary, empty/None/missing-
  column history, cross-sector non-contamination, NaN handling, pooled variant,
  `build_calibrated_*_config` wiring (calibrates when enough history / falls back when
  not / does not mutate the input dict).
- `tests/leakage/test_threshold_calibration_no_future_function.py` (4 tests):
  truncated-vs-full-dataset threshold equivalence, appending pathologically-extreme
  future rows never changes an already-computed threshold, the evaluation day's own
  row is excluded from its own threshold, end-to-end `build_calibrated_new_gainer_config`
  no-lookahead check.
- `tests/unit/test_signal_detector.py` (+4 new in `TestCalibratedThresholds`):
  default-off preserves exact pre-M9 behavior, calibrated-on-with-no-history falls back
  correctly, calibrated-on-with-history genuinely lowers the bar for a historically-dormant
  sector, two sectors with different histories get independently different calibrated
  thresholds.
- `tests/unit/test_prepare_official_margin_history_snapshot.py` (7 tests): bridges both
  files when present, pure-copy (no double-transform) of already-transformed payloads,
  missing-source reported not silently skipped, default non-destructive / `--force`
  overwrite, date-discovery requiring both sides present, start/end filtering.

**Full suite**: `.venv/Scripts/python.exe -m pytest tests -p no:cacheprovider -q`

```
451 passed in 43.75s
```

(419 baseline + 7 margin-bridge + 17 threshold-calibration + 4 leakage + 4
signal-detector-calibration = 451; log at
`loop/evidence/test_logs/pytest_calibration_run_log.txt`.)

---

## 6. Known Limitations and Data-Leakage Disclosure

1. **Only 28 non-contiguous trading days** of usable calibrated data this round (§2),
   far short of the full 62-day range and far short of SPEC_ADDENDUM B-1.4's 50-events-
   per-grade bar for removing the "research candidate" label.
2. **Quantile calibration itself uses only strictly-prior data (no leakage)** — verified
   by construction and by 4 dedicated leakage tests. **No full-sample static quantile
   simplification was used** — every quantile is a genuine expanding rolling window as
   of each trading day, so there is nothing to disclose here as a leakage risk.
3. **The BLOCKED_LOW_DQ regression (§2) is a genuine, disclosed side-effect of THIS
   session's margin-wiring work being layered on top of separately-improved FinMind
   OHLCV coverage** (100%, up from 29% at M5c time) — not something this session
   introduced in the reconciliation logic itself, but a real consequence worth a
   dedicated follow-up decision (does the leaderboard reconciliation need a basis-
   aligned rewrite, given it now blocks half the calibration/backtest sample?).
4. **This round's backtest headline is unchanged not because calibration failed, but
   because of a structural interaction with the already-accepted event-extraction rule**
   (§4.2) — this says nothing about whether the calibrated thresholds are better or
   worse in a genuine forward sense; it says this specific 28-day sample cannot answer
   that question at all.
5. **Only 3 of 17 new-gainer/continued-momentum thresholds were calibrated this round**
   (§3.1) — the other 14 remain absolute PLACEHOLDER values, unchanged.
6. **`config/default.yaml`'s `new_gainer`/`continued_momentum` sections are NOT actually
   read by the live pipeline** (`SignalDetector()`/`SectorScoring()` are instantiated
   with no config args in `scripts/run_daily.py`) — this is a pre-existing gap, not
   introduced this milestone, disclosed here because it affects how to interpret the
   YAML file's "CALIBRATED fallback" comments (documentation only, not live wiring).
7. **`sector_scoring.py`'s `DEFAULT_SECTOR_WEIGHTS`/`OVERHEAT_SUBWEIGHTS` were NOT
   converted to quantiles** — SPEC_ADDENDUM B-1.3's quantile instruction targets
   *thresholds* (Ch.14/15), not scoring *weights* (Ch.12.1), which remain absolute
   PLACEHOLDER values per B-1.1's original (unchanged) instruction.
8. **No new sensitivity analysis or walk-forward validation** — correctly out of this
   milestone's scope (calibrate + rerun once, not tune).

---

## 7. Conclusion — Can This System Be Used to "Predict Which Sector Is About to Take
   Off"? Honest Answer

**No, not yet, and this milestone's real finding does not move that answer in either
direction.** The margin-data pipeline gap is now genuinely closed (§1) and the
threshold-calibration mechanism is real, tested, and demonstrably changes signal
grades (§3.4) — those are genuine, verifiable pieces of progress. But:

- The backtest headline is **completely unchanged** (§4.1) — not because the new
  calibrated thresholds are proven neutral, but because this dataset's event-extraction
  structure makes it structurally incapable of measuring calibration's effect at all
  (§4.2). This is a **measurement ceiling**, not a verdict on the underlying idea.
- The usable sample **shrank** to 28 non-contiguous days this round (§2), a real step
  backward in evidence quantity, caused by a newly-surfaced consequence of improved
  data coverage elsewhere in the system.
- **Zero A-grade or 續漲訊號 events have ever occurred** in any real dataset this
  project has processed across M5c/M7/M8/M9 — those two tiers still have no evidence
  whatsoever.
- The B/C-grade signals this dataset CAN measure (53 events, same across before/after)
  still lose to the market by ~11 percentage points over 10 days and still lose to a
  naive momentum-extension baseline — unchanged from M5c/M7's finding.

**Bottom line for a non-engineer reading this**: we fixed a real data-pipeline gap and
built a real, tested calibration mechanism this milestone, but we still cannot say
whether the resulting system is better, worse, or the same at picking the next hot
sector than before — the test we ran this round happened to be unable to tell either
way, through no fault of the calibration logic itself. More accumulated, unblocked
trading days are needed before that question can be answered. This is **not**
Research Ready, **not** "已校準完成", and should **not** be used to inform capital
allocation decisions.

---

## 8. Files Changed/Added This Milestone

**New:**
- `src/threshold_calibration.py` — rolling quantile calibration functions.
- `scripts/prepare_official_margin_history_snapshot.py` — margin data bridge.
- `tests/unit/test_threshold_calibration.py` (17 tests)
- `tests/leakage/test_threshold_calibration_no_future_function.py` (4 tests)
- `tests/unit/test_prepare_official_margin_history_snapshot.py` (7 tests)

**Modified:**
- `src/signal_detector.py` — `SignalDetector.__init__` gained
  `use_calibrated_thresholds`/`df_sector_history` (both default preserve exact pre-M9
  behavior); `_evaluate_new_gainer`/`_evaluate_continued_momentum` accept an explicit
  `cfg` parameter; `DEFAULT_NEW_GAINER_CONFIG["min_score"/"prev_score_max"]` and
  `DEFAULT_CONTINUED_MOMENTUM_CONFIG["min_score"]` comments updated to `# CALIBRATED
  (n=28 trading days...) - PRELIMINARY, small sample`.
- `scripts/run_daily.py` — `run_pipeline` gained `use_calibrated_thresholds: bool = False`,
  threaded to `SignalDetector`.
- `scripts/run_history_pipeline.py` — `--calibrated` CLI flag, matching parameter
  threaded through.
- `config/default.yaml` — matching comment updates + disclosure that this file is not
  actually read by the live pipeline (pre-existing gap).
- `docs/signal_definitions.md` — §3.5.1/§3.5.2 tables annotated with CALIBRATED status
  for the 3 affected rules.
- `tests/unit/test_run_history_pipeline.py` — stub's `__call__` signature updated to
  accept the new `use_calibrated_thresholds` kwarg (additive, non-breaking).

**Untouched** (governance rule #9, zero lines changed): `src/backtester.py`,
`src/benchmarks.py`, `src/sector_scoring.py`'s scoring formula (only its module-level
constants' comments were NOT changed — weights are out of quantile-calibration scope
per §6 item 7), event extraction rules, statistical methodology.
