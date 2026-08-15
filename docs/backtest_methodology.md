# Milestone 5c Backtest Methodology

**Status of every result this document describes: 初步研究讀數 (PRELIMINARY RESEARCH
READING). Not Research Ready (SPEC §28.2 / SPEC_ADDENDUM A-3).** All thresholds feeding
the signals under test remain `# PLACEHOLDER - UNCALIBRATED` (SPEC_ADDENDUM B-1). This
document describes *how* the numbers in `docs/Milestone_5c_Acceptance_Report.md` and
`outputs/backtests/backtest_report_<date>.xlsx` were computed, not a claim that the
system is tradable.

---

## 1. Event Definition (SPEC 19.6, SPEC_ADDENDUM B-3.1)

`src/backtester.py::extract_events` walks each `(sector_name, sector_type)` pair's
signal history in trade-date order and marks a row as an **independent event** the first
time its signal family (新起漲 A/B/C = `NEW_GAINER`; 續漲訊號 = `CONTINUED_MOMENTUM`)
differs from the immediately preceding day's family for that same sector. Every
subsequent consecutive day carrying the same family is **persistence**, not a new event.
A day with no signal (無訊號/無效) resets the run so the next graded day starts fresh.

Grade *changes within* the same family (e.g. B級 today, A級 tomorrow, same sector) are
treated as persistence of one event, not two — SPEC 19.6's "連續多天出現訊號=持續狀態"
is read at the family level, since the underlying 10-condition checklist can flip a
sector between A/B/C purely from one borderline condition's daily noise; that is not a
fresh ignition.

`primary` and `theme` sectors sharing the same Chinese name (e.g. a "半導體" primary
sector and an "AI" theme sector) are tracked as **fully independent series** — a stock
can belong to exactly one `primary_sector` (never double-counted) but multiple `theme_1/
2/3` tags (may double-count, per `src/sector_features.py`'s existing `may_double_count`
flag). All headline statistics in the acceptance report are broken out by `sector_type`
so `theme`-sector overlap with `primary`-sector membership is visible, never silently
pooled.

**Real, disclosed finding from running this on the actual 60-day/53-sector dataset**:
zero of the 2,765 persisted signal rows across the full window are 無訊號/無效 — every
sector that is ever scored carries a graded new-gainer signal (B or C; no A-grade and no
續漲訊號 occurred at all in this window) on literally every day it appears. Structurally,
this collapses the independent-event count to essentially one event per sector (53
sectors total across the whole 60-day run), overwhelmingly concentrated on the very
first day the pipeline has any prior-day history to compare against (2026-04-20, 46 of
53 events) plus a handful of sectors that first appear on the last day (2026-07-17, 7
events, all UNTRADABLE/PENDING for lack of forward data). **This means the "≥50
independent events per signal grade" bar (SPEC_ADDENDUM B-1.4) cannot be met by this
dataset** — B級 has at most ~30 independent events, C級 at most ~23, and both grades'
"first day" concentration overlaps heavily with each other and with the single 60-day
window's one market regime. This is not a code defect; it is what the current C/B-grade-
saturated (`min_score`, `prev_score_max`, breakout-window thresholds all uncalibrated)
signal detector emits on real data.

## 2. Entry Timing and No-Future-Function Guarantee (SPEC 19.1)

Every event's entry is the **T+1 opening price** where T is the signal's trade_date.
`compute_entry_price`/`compute_stock_forward_returns`/`compute_sector_forward_returns`
locate T by exact `trade_date` match inside the per-stock OHLCV history and index
strictly forward from there — no function in this module ever looks at a `trade_date`
column and reasons "as of today"; it only walks forward through whatever frame it's
given. `tests/leakage/test_backtester_no_future_function.py` verifies directly:
truncating a stock's OHLCV history to end exactly when an event's longest tested horizon
(20 trading days) has matured produces byte-identical returns/labels to running against
the full 60-day dataset, and appending further future bars never changes an
already-realized return.

## 3. Sector-Level Forward Return (docs/signal_definitions.md R_sector,K)

Sector membership for return computation is resolved with the exact same rule
`src/sector_features.py` already uses for feature aggregation: `primary` sector match =
`stock.primary_sector == sector_name`; `theme` sector match = `sector_name` present in
any of `theme_1`/`theme_2`/`theme_3`. Sector membership is read from that **signal
date's own** `stock_scored_<date>.csv` snapshot (never a later date's), so a stock that
later gets reclassified into a different sector cannot retroactively change which
members an already-realized historical event's forward return is computed over.

The sector-level K-day forward return is the **cross-sectional median** of tradable
member stocks' own individual K-day forward returns (median, not a turnover-weighted
mean) — chosen because a turnover-weighted number lets one giant-cap constituent
dominate the "sector" read, which would contradict this system's own breadth-based
design philosophy (SPEC's whole premise is breadth/participation, not single-stock
dominance). A sector's return at a given horizon is reported as `None` (not silently
skipped or zero-filled) if fewer than `min_constituents` (default 1; effectively "at
least one realized member return") member stocks have a realized value at that horizon
— with only 571/1,963 stocks covered by FinMind OHLCV this milestone (29.1%), many real
sectors this run only had 1-2 tradable FinMind-covered members, a disclosed statistical
thinness (see §6).

## 4. Taiwan-Specific Rules (SPEC_ADDENDUM B-2)

### 4.1 Limit-Up Lockout (漲停鎖死)

No field in this project's FinMind-sourced OHLCV feed directly flags "this bar was
locked at the daily limit with zero sell-side liquidity." A price+volume proxy is used
instead (`LIMIT_UP_THRESHOLD_PCT=9.5%` open-vs-prior-close, `LOW_VOLUME_LOCK_THRESHOLD
<=1,000 shares`), disclosed as a proxy, not asserted as ground truth. Both required
accountings are computed and reported side by side for every event:

- **exclude**: a locked T+1 bar drops the event from tradable statistics entirely.
- **postpone**: a locked T+1 bar tries T+2's open instead; if T+2 is *also* locked, the
  event is UNTRADABLE under this accounting too.

Missing volume data is treated as "not confirmed locked" (fail-closed toward inclusion,
not exclusion) — falsely excluding a real tradable event on missing volume would bias
the surviving sample.

**A stock with zero FinMind OHLCV history at all** (571/1,963 coverage gap, see §6) also
surfaces through the same `UNTRADABLE` status via a distinct internal `reason` code
(`NO_SIGNAL_DATE_IN_HISTORY`, visible in the per-event detail sheet) — this is a data-
availability gap, not a limit-up lock, and the acceptance report's UNTRADABLE count
should be read alongside that distinction, not as "X% of events hit the daily limit."

### 4.2 Disposition / Caution Stocks (處置/注意股)

No processed disposition/caution stock list exists anywhere on disk this milestone (no
fetcher for it has been built in any prior milestone). `Backtester.run_event_study`
accepts an optional `disposition_stock_ids` set and applies a 0.5x `weight_penalty` flag
to any event whose sector has a member in that set — the mechanism is implemented and
unit-tested, but every real run this milestone passes an empty set, so
`has_disposition_member` is `False` for all 53 real events. Disclosed, not hidden.

### 4.3 Ex-Dividend Adjustment (除權息)

**Not implemented.** No `adjusted_close` field exists anywhere in this project's data
pipeline — `src/finmind_fetcher.py`'s `TaiwanStockPrice` payload parsing
(`src/data_loader.py::load_finmind_ohlcv_for_date`, and this milestone's
`load_finmind_ohlcv_history`) only ever reads raw `open`/`max`/`min`/`close`. All
forward returns in this report are computed on **unadjusted** close-to-close prices. Any
event whose holding window crosses a real ex-dividend date will show an artificial price
drop unrelated to actual investment performance. July-September is the addendum's
explicitly named dividend season and this milestone's 60-day window (2026-04-20 to
2026-07-17) runs directly into the start of it — this is a live, not hypothetical, risk
for the report's own numbers. No unit test asserts this is handled correctly, because it
is not handled at all; `tests/unit/test_dividend_adjustment.py` (pre-existing, M2-era)
tests adjusted-return *arithmetic* in isolation only — it does not exercise any code
path in `src/backtester.py`, and its passing does not mean the pipeline adjusts for
dividends.

## 5. Trading Cost (SPEC 19.5)

`apply_trading_cost(gross, fee_pct, tax_pct, slippage_pct)` = `gross - (fee_pct*2 +
tax_pct + slippage_pct)`, matching the Taiwan convention of 手續費 charged on both the
buy and sell leg and 證交稅 charged once, on the sell leg (numerically the same total
whether or not you name which leg each piece belongs to, but now isolated in one
documented/tested function rather than inlined). Config defaults (`config/default.yaml
backtest.*`): `fee_pct=0.001425` (assumes 0% broker discount — a conservative/worst-case
default, disclosed as such, not calibrated against any real brokerage), `tax_pct=0.003`,
`slippage_pct=0.001`. Every event and every benchmark draw reports **both** gross (no
cost) and net (cost-adjusted) return columns side by side, per the milestone brief's
explicit "含成本前後兩組數字" requirement.

## 6. Known Data Limitations (must-read before trusting any number in this report)

1. **FinMind OHLCV coverage is 571/1,963 stocks (29.1%)** as of this milestone (see
   `docs/Milestone_5c_prep_Report.md` §3). Any sector whose real membership includes
   stocks outside this 571 will have its forward return computed from a partial,
   possibly unrepresentative sample of its true membership. Reported `member_stock_count`
   vs `tradable_member_count` in the event-detail sheet make this gap directly visible
   per event, not averaged away.
2. **Institutional/margin historical coverage is near-zero** (institutional 26/1,963,
   margin 2/1,963). The signal detector's own institutional condition (rule 8 of the
   續漲 checklist / the sector score's `institution` sub-weight) falls back to the
   documented neutral 50.0 prior for almost every historical day in this window — so any
   apparent institutional-driven pattern in the historical signals is largely an
   artifact of that neutral fallback, not real historical institutional flow.
3. **All thresholds feeding the signal detector are uncalibrated placeholders**
   (`config/default.yaml`, every `new_gainer.*`/`continued_momentum.*`/`weights.*` key
   marked `# PLACEHOLDER - UNCALIBRATED`). This report cannot and does not claim these
   specific numeric thresholds are good; it reports what they emit as-is.
4. **60 days is one single market regime** (a strong, roughly +10%/10-trading-day TAIEX
   rally window per the on-disk TAIEX series) with zero environment stratification (SPEC
   §18 explicitly defers this to more accumulated history). Every headline number in
   this report describes performance *during a strong bull run specifically*, and cannot
   be extrapolated to sideways or bear conditions.
5. **No ex-dividend adjustment** (§4.3) — a live risk given the window runs into
   dividend season.
6. **Only one parameter configuration was tested** this milestone (`config/default.yaml`
   as-is; "postpone" is reported as an alternative *accounting convention* for the same
   run, not a second tuned parameter set) — SPEC_ADDENDUM B-3.3's multiple-comparison
   disclosure is `n_param_combinations_tested=1`, recorded in the JSON summary.
7. **No A-grade new-gainer or 續漲訊號 events occurred at all** in the real 60-day
   dataset — the acceptance report's per-tier statistics only exist for B級/C級.

## 7. Benchmarks (SPEC_ADDENDUM A-3)

- **Momentum Extension Baseline** (`src/benchmarks.py::momentum_extension_baseline`):
  every trading day T (given a scored T-1), "buys" the single highest-`score` sector as
  of T-1 at T's T+1 open, holds the same 1/3/5/10/20-day horizons. One row per trading
  day (not per event) — a daily-rebalanced heuristic, structurally different from the
  event study's episodic sampling, and always reported with its own `n` so the two are
  never implicitly treated as the same size of evidence.
- **Random Sector Bootstrap Baseline** (`random_sector_bootstrap_baseline`): draws
  `n_draws` uniformly random `(sector_name, sector_type, trade_date)` triples from the
  full available universe (default N=10,000 in the real report run per SPEC_ADDENDUM
  3.2, fixed `random_seed=42` for exact reproducibility, recorded in the output frame's
  `.attrs` and the JSON summary).
- **Comparison** (`scripts/run_backtest.py::compare_vs_momentum_baseline`): reports each
  distribution's median excess return at the 10-day horizon and whether the signal's
  median beats the momentum baseline's median. This is a **descriptive comparison only —
  no formal significance test (t-test/Mann-Whitney) is run.** Given B級/C級's n<30 (see
  §1), a t-test result would very likely be underpowered/misleading if presented as a
  clean pass/fail; the honest treatment this milestone gives it is "here are the two
  medians, side by side, with their real sample sizes" — the acceptance report's prose
  states outright whether that comparison supports "increment value" or not, without
  dressing a small-sample gap up as statistical significance.

## 8. What Is NOT Implemented This Milestone

- Walk-forward validation (SPEC 19.3) — needs materially more than 60 days of history to
  be meaningful; explicitly deferred, not attempted with an inadequate window.
- Parameter sensitivity analysis / overfitting checks (SPEC Ch.20) — out of scope for
  this milestone's brief (event-study engine + benchmarks only); would need a
  calibration pass this milestone does not perform.
- Market-regime stratification (SPEC §18) — the whole window is one regime; see §6.4.
- Formal significance testing for signal-vs-baseline comparison — see §7.
