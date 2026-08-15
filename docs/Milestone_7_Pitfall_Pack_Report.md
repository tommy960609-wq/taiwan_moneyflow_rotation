# Milestone 7 (避坑補完包 / Pitfall Pack) Acceptance Report

**Date**: 2026-07-18
**Role**: Maker (implementation), pending independent verifier gate (same pattern as
M0-M6 gates in `loop/PROJECT_STATE.md`).
**Environment**: `C:\Workspace_CN\taiwan_moneyflow_rotation\.venv`, `pytest -p
no:cacheprovider`.

---

## 0. Headline (read this first)

Reran the 60-day event-study backtest with ex-dividend adjusted prices instead of raw
close. **The B/C-tier headline verdict from M5c is UNCHANGED**: B級早期點火 10-day net
excess return median is still **-11.28%** (was -11.28%), C級個股事件 still **-10.41%**
(was -10.41%) — both still underperform the momentum baseline (-0.39%), both still
n<30 (below this project's own decisiveness bar). The means shifted marginally
(B: -10.42%→-10.39%, C: unchanged at -5.46%) because only 2 of the 53 real events had a
member stock whose 10-day forward window crossed an ex-dividend date in this particular
sample — the adjustment logic is verified working (direct event-by-event diff confirms
it), it just didn't have much to bite on for this specific 60-day/53-event window. **The
theoretical concern that Apr-Jul dividend season understated returns is real, but for
this specific already-small event sample it happened not to matter much** — a genuine,
honestly-reported non-finding, not a failure to implement.

Three other deliverables landed real, verified data:
- **Disposition/attention list**: 5 real TWSE/TPEx endpoints wired, live-fetched today —
  **41 stocks** flagged (12 處置股/disposition, 29 注意股/attention), now shown on the
  daily report's 個股優先排序 sheet and wired into the backtester's
  `disposition_stock_ids`.
- **36-day leaderboard reconciliation**: of the 40% of leaderboard rows FinMind coverage
  allows comparing (4,318/10,800), only **0.97%** (42 rows) deviate by more than 0.5
  percentage points from this project's own FinMind-derived numbers — a clean result,
  with 3 genuine FinMind zero-price data-corruption rows found and disclosed along the
  way.
- **漲停家數 history**: built from the same 36 files — 2,502 stock-days at the daily
  limit over 36 sample dates (mean 69.5/day), max consecutive-limit-up streak 10 days
  (stock 8291, ending 2026-05-28). Persisted as an **observe-only** dataset; NOT wired
  into the live overheat-risk score (see §3 for why).

**Known incomplete pieces, disclosed not hidden**: ex-dividend adjustment factor
coverage is 58% of the FinMind-backfilled universe (516/890 stocks) — FinMind's rate
limit was hit mid-fetch (same short burst-scale throttle documented in M5b/M5c/M6) and a
resume attempt ~2 minutes later still got HTTP 403, so this session stopped rather than
burn more time; the remaining 42% of stocks fall back to raw (unadjusted) price, tagged
`UNADJUSTED`, never silently blended.

---

## 1. What Was Built

### 1.1 Ex-dividend price adjustment (`src/price_adjuster.py`, new)

**Dry-run finding (dataset discovery, never recalled from memory)**: none of
`TaiwanStockPriceAdj` / `TaiwanStockPriceAdjusted` / `TaiwanStockAdjPrice` /
`TaiwanStockPriceAdjustment` / `TaiwanStockPriceAdjustmentFactor` / `TaiwanStockAdjustment`
exist on this FinMind token — all returned HTTP 400/422 on a live probe. Receipt:
`loop/evidence/fetch_receipts/finmind_adjusted_price_probe_2026-07-18.json`.

**Path taken (the task's documented fallback)**: `TaiwanStockDividendResult` **is**
available and verified live — a per-stock list of real ex-dividend events, each carrying
`date` (ex-div trading date), `before_price` (reference close the prior day), and
`after_price` (the exchange's official post-adjustment reference price). This module
computes a classic backward (multiplicative) adjustment factor per stock:
`factor = after_price / before_price`, applied to every bar strictly before the
ex-dividend date, compounding across multiple events in the same stock's history. Bars
on/after the latest event always carry `factor=1.0` (today's raw price is never touched).

`scripts/fetch_price_adjustments.py` drove the real fetch: discovers every stock with a
FinMind OHLCV file on disk (890 as of this session — PID 2924's drip backfill kept
progressing concurrently and finished mid-session at 890/1963, see §5), fetches each
one's dividend-event history for 2026-04-20..2026-07-17, and writes a consolidated
`data/reference/price_adjustment_factors.csv` (31,874 rows). Per-stock raw dividend-event
JSON is cached under `data/raw/fundamentals/dividends/finmind_div_<id>.json` — a distinct
filename prefix from the concurrent drip process's own `finmind_<id>.json` files, so the
two never collided.

**Result**: **516/890 stocks (58%) fetched successfully** before hitting FinMind's rate
limit (HTTP 402, same short burst-scale throttle as every prior FinMind fetch in this
project — see M5b/M5c/M6 notes). A resume attempt ~2 minutes later got a *different*
failure mode (HTTP 403, not 402/429 — this fetcher's rate-limit detector only special-
cases 402/429; 403 falls through to the normal retry-then-fail path, a minor real finding
worth a future session's attention) and made no further progress, so this session stopped
rather than wait longer. **208 of the 516 fetched stocks had at least one real
ex-dividend event** in the window (the rest are confirmed-clean, not "unknown" — a
dividend-free stock genuinely returns an empty event list from FinMind, which this
module distinguishes from a fetch failure). Receipt:
`loop/evidence/fetch_receipts/price_adjustment_fetch_summary_2026-07-18.json`.

### 1.2 Backtester wiring (`scripts/run_backtest.py`, additive changes only)

New `config/default.yaml` key `backtest.use_adjusted_prices: true` (mirrored in
`src/config_manager.py`'s in-code defaults). `apply_price_adjustment()` merges the
factor table onto the loaded FinMind OHLCV before it reaches `Backtester.run_event_study`
— every stock without a factor entry keeps its raw price and is tagged
`price_unadjusted=True` in the merged frame; **never silently blended**. This flows
through unchanged into `src/backtester.py`'s existing (already-accepted, unmodified)
entry-price/forward-return math and into `src/benchmarks.py`'s momentum/random baselines
(both consume the same adjusted OHLCV frame, no separate wiring needed). Universe-wide:
**42.0% of the 890 FinMind-covered stocks (374) are UNADJUSTED** this run — reported in
`backtest_summary_2026-07-18.json`'s `unadjusted_stock_pct` field, and in the Excel
report's disclosures block.

`src/backtester.py` and `src/benchmarks.py` themselves are **byte-for-byte unchanged**
(already-accepted M5c code; governance rule #9). Only the caller (`run_backtest.py`) now
passes pre-adjusted prices in and a real `disposition_stock_ids` set (previously always
empty, per M5c's own disclosed limitation).

### 1.3 Disposition/attention stock fetcher (`src/disposition_fetcher.py`, new)

**Endpoint discovery** (grepped `punish`/`attention`/`disposition`/`notice`/`warning`
against `loop/evidence/raw_samples/{twse,tpex}_swagger.json`, 5 real candidates found,
all live-verified 2026-07-18):

| Endpoint | Market | Kind | Live row count today |
|---|---|---|---|
| `/announcement/punish` | TWSE | 處置股 disposition | 13 raw → 12 unique stock_id |
| `/announcement/notice` | TWSE | 注意股 attention | 0 (real: empty-day sentinel row filtered, not a stock) |
| `/tpex_trading_warning_information` | TPEx | 注意股 attention | 28 |
| `/tpex_trading_warning_note` | TPEx | 注意股 attention | 2 |
| `/tpex_esb_warning_information` | TPEx (興櫃) | 注意股 attention | 1 |

**Real finding, disclosed**: TWSE's own JSON API response bodies for `punish`/`notice`
contain genuine mojibake/replacement-character Chinese text in the free-text fields
(`ReasonsOfDisposition`, `Detail`, `TradingInfoForAttention`, etc.) — verified this is a
server-side defect in the raw HTTP response itself (the numeric/ASCII fields like `Code`/
`Date` are intact; only Chinese-text fields are corrupted). Stored as-is, not
re-guessed/discarded; only `Code` (unaffected) is used for the flag this milestone wires
downstream. `/announcement/notice` also returns a **sentinel row**
(`Number="0", Code=""`) on a zero-attention-stock day — correctly filtered out as "no
rows," never treated as a real stock named `""`.

**Today's real consolidated list**: **41 unique stocks** — **12 處置股** (disposition,
hard restriction) and **29 注意股** (attention, softer watch flag; disposition wins when
a stock appears on both). Receipt:
`loop/evidence/fetch_receipts/disposition_today_list_2026-07-18.json`. Raw envelopes at
`data/raw/disposition/<endpoint>_2026-07-18.json`.

**Wiring**:
- `scripts/run_daily.py::_load_disposition_ids_for_date` (new helper) reads whatever
  `data/raw/disposition/*_<trade_date>.json` files exist for the pipeline's `trade_date`
  (no live network call inside the pipeline itself — fetch is a separate, explicit step,
  matching every other data source's convention in this project) and attaches a
  `disposition_flag` column (處置股/注意股/正常) to `df_scored_stocks`. A date with no
  fetch on disk gets `"N/A(未查核)"` — an honest "not checked," never silently "clean."
- `src/report_generator.py`'s 個股優先排序 sheet gained a **處置/注意** column (bold red
  when flagged), plus an updated caveat line explaining the `N/A(未查核)` sentinel.
- `scripts/run_backtest.py::load_disposition_stock_ids` unions every stock_id across
  every disposition/attention snapshot file on disk and passes it into
  `Backtester.run_event_study`'s pre-existing (unmodified) `disposition_stock_ids`
  parameter — **41 stocks**, honestly disclosed as a **same-day-only snapshot** (these
  TWSE/TPEx endpoints have no historical date-range query parameter, so there is no way
  to reconstruct which stocks were disposition/attention-flagged on each of the 53
  events' actual historical dates; the current list is applied uniformly, a real
  limitation stated in the backtest report's disclosures, not hidden).

### 1.4 36-day leaderboard integration (`src/leaderboard_loader.py`,
`src/limit_up_history.py`, `src/leaderboard_reconciliation.py`, all new)

36 `Report_YYYYMMDD.xlsx` files copied from the read-only source
(`Quant-Agent/台股漲幅排行/`) into `data/raw/reports/` (verified: xlsx cell content
decodes to correct Unicode via openpyxl/pandas — the mojibake seen in some terminal
displays is a display-layer artifact of this session's bash tool, not real file
corruption; confirmed by checking raw codepoints). All 36 files parsed cleanly (300 rows
each, 10,800 total), 2026-05-15..2026-07-16.

**Use A — 漲停家數/連續漲停 history** (proxy: 漲跌幅>=9.5% treated as limit-up, disclosed
as a proxy since the leaderboard only reports closing return, not an official "locked
with zero liquidity" flag):
- Market-wide: `outputs/leaderboard_analysis/limit_up_market_wide.csv` — 2,502 total
  limit-up stock-days across the 36 sample dates, mean 69.5/day.
- Sector-level: `outputs/leaderboard_analysis/limit_up_by_sector.csv` — joined against
  this project's own `stock_industry_mapping`; unmapped stocks bucketed under 未分類
  rather than dropped or misattributed (sum of per-sector counts reconciles exactly to
  the market-wide total for each date, verified by test).
- Consecutive streaks: `outputs/leaderboard_analysis/consecutive_limit_up_streaks.csv` —
  streaks are defined against the **observed leaderboard sample's own date sequence**,
  not calendar dates (the 36 files have real gaps, e.g. 2026-06-17..06-26 is entirely
  absent — a streak never silently bridges across a gap). Max: stock **8291, 10
  consecutive limit-up days ending 2026-05-28**.

**Scope decision — this is OBSERVE-ONLY, per governance rule #9 and the task's own "禁改
已驗收模組既有行為" instruction**: `src/sector_scoring.py::_compute_overheat_risk` (the
already-accepted M2 scoring formula) is **NOT modified**. This is the "consecutive-
limit-up count" sub-factor M2's own acceptance report explicitly listed as unimplemented
— it is now computed and persisted as a real, disclosed dataset, but wiring it into the
LIVE overheat-risk score is a future milestone's decision after this observe-only series
has been reviewed (this project's own "新機制一律先 observe 後 active" rule).

**Use B — 36-day cross-reconciliation**: computed an independent prev-close-basis return
straight from FinMind OHLCV (`close[t]/close[t-1] - 1`) rather than comparing the
leaderboard's 漲跌幅 (prev-close basis) directly against this project's own
`daily_return` (open-to-close basis — a real, pre-existing, already-disclosed basis
mismatch from M3). Result:

| Metric | Value |
|---|---|
| Total leaderboard rows | 10,800 |
| Rows with a FinMind comparison available | 4,318 (**40.0% coverage** — limited by FinMind OHLCV backfill progress) |
| Rows exceeding 0.5pp deviation threshold | **42 (0.97% of compared rows)** |
| Median absolute deviation | 0.0024pp (essentially exact) |
| Mean absolute deviation | 0.10pp |

**A genuine data-quality finding surfaced by this exercise**: 3 of the 42 outlier rows
(stocks 2321/2941/2073, all on 2026-06-08) show a **-100% deviation** — traced to
FinMind's own `TaiwanStockPrice` feed genuinely reporting `open=high=low=close=0.0` with
nonzero volume for those 3 stocks on that exact date (verified directly in the raw
per-stock JSON, not a parsing artifact of this module). This is a real, disclosed
FinMind upstream data-corruption finding, not a defect in this milestone's reconciliation
logic. A second, non-zero-price-related bug was caught and fixed during this session's
own testing: dividing by a zero `prev_close` (rather than a zero `close`) was originally
producing `+inf` instead of `NaN`, silently poisoning the mean; fixed with an explicit
`prev_close > 0` guard before computing the ratio (see
`src/leaderboard_reconciliation.py::compute_finmind_prevclose_returns`).

Orchestrated by `scripts/run_leaderboard_analysis.py`; outputs under
`outputs/leaderboard_analysis/`.

---

## 2. Backtest Rerun — Old vs New Headline

Old backtest outputs backed up to `outputs/backtests/_bak_pre_m7/*.bak` before rerunning.
`scripts/run_backtest.py --n-bootstrap 10000` (same real 60-day signal history, 2,765
signal rows, 53 independent events, unchanged) rerun with `use_adjusted_prices=true`:

| Signal Tier | OLD median (net, 10d) | NEW median (net, 10d) | OLD mean | NEW mean | Win Rate | vs Momentum (-0.39%) |
|---|---|---|---|---|---|---|
| B級早期點火 (n=27 realized) | -11.28% | **-11.28%** (unchanged) | -10.42% | **-10.39%** | 0.0% | still loses |
| C級個股事件 (n=19 realized) | -10.41% | **-10.41%** (unchanged) | -5.46% | **-5.46%** (unchanged) | 26.3% | still loses |

**Only 2 of 53 events changed at all** (`數學工業`/`塑膠工業` sectors on 2026-04-20,
verified by direct event-level diff between old and new `backtest_events_*.csv`) — the
adjustment is confirmed genuinely applied (not a no-op bug), it simply had few
opportunities to matter in this specific already-small 53-event sample, because most
events' member stocks' 10-day forward windows didn't happen to cross one of their
sector's ex-dividend dates. **The theoretical concern (Apr-Jul is peak dividend season,
understating returns) is real and the mechanism now exists to correct it**, but for
*this specific* 60-day/53-event dataset the correction turned out to be small. UNTRADABLE
accounting unchanged (2 untradable, 5 pending, 46 tradable, both exclude/postpone
conventions). Conclusion level unchanged: **初步研究讀數 (PRELIMINARY RESEARCH READING)**,
not Research Ready — n<30 at both realized tiers, still below this project's own 30-event
decisiveness bar.

New outputs: `outputs/backtests/backtest_report_2026-07-18.xlsx`,
`backtest_events_2026-07-18.csv`, `backtest_summary_2026-07-18.json` (now also carries
`use_adjusted_prices`, `unadjusted_stock_pct`, `disposition_stock_count` fields).

---

## 3. Tests

56 new tests added (all offline, mocked — no live network in the pytest suite):

| File | Tests | Coverage |
|---|---|---|
| `tests/unit/test_price_adjuster.py` | 11 | Factor math (single/multi-event compounding, malformed-event skip), `apply_adjustment` UNADJUSTED tagging, universe-build fetch/failure accounting |
| `tests/unit/test_disposition_fetcher.py` | 7 | Empty-sentinel filtering, disposition-wins-over-attention, per-endpoint failure isolation, positional id extraction |
| `tests/unit/test_leaderboard_loader.py` | 7 | Column normalization, malformed-file fail-closed, multi-file stacking, limit-up-proxy threshold |
| `tests/unit/test_limit_up_history.py` | 7 | Market/sector aggregation reconciliation, unmapped-stock bucketing, streak calc incl. sample-gap non-bridging |
| `tests/unit/test_leaderboard_reconciliation.py` | 9 | Basis-aligned return calc, zero-prev-close guard (the bug caught above), threshold flagging, headline summary |
| `tests/unit/test_run_backtest_m7_wiring.py` | 8 | `apply_price_adjustment` enabled/disabled paths, `load_disposition_stock_ids` union-across-dates |
| `tests/unit/test_run_daily_disposition_loading.py` | 4 | Data-unavailable vs confirmed-clean distinction, date-file matching |
| `tests/unit/test_report_generator.py` (additive) | 3 | 處置/注意 column header, N/A(未查核) default, real-flag display |

Full suite: **361/361 passed** (305 pre-existing + 56 new), zero regressions. Log:
`loop/evidence/test_logs/pytest_m7_run_log.txt`.

---

## 4. Known Limitations (disclosed, not hidden)

1. **Adjustment factor coverage 58%** (516/890 FinMind-backfilled stocks) — FinMind rate
   limit hit mid-fetch; a resume attempt got a different HTTP 403 failure mode this
   fetcher's rate-limit detector doesn't special-case (only 402/429 are treated as
   `RATE_LIMITED`). The remaining 374 stocks fall back to raw price, tagged
   `price_unadjusted=True`, never silently blended with adjusted prices.
2. **Disposition/attention list is a same-day snapshot only** — none of the 5 endpoints
   accept a historical date-range query parameter, so the 41-stock list used in the
   backtester is applied uniformly across all 53 historical events rather than being a
   true per-event historical lookup. Stated explicitly in the backtest report's
   disclosures block.
3. **Limit-up history is observe-only** — not wired into `sector_scoring.py`'s live
   overheat-risk score (an already-accepted M2 weight contract this task's instructions
   say not to change). A future milestone's explicit decision after this dataset has
   been reviewed.
4. **Leaderboard reconciliation coverage 40%** — limited by FinMind OHLCV backfill
   progress (890/1963 stocks as of this session), not a defect in the reconciliation
   logic itself.
5. **3 genuine FinMind zero-price data-corruption rows found** (stocks 2321/2941/2073,
   2026-06-08) — a real upstream data-quality issue, disclosed, not silently smoothed
   over or excluded without mention.
6. Every pre-existing M5c backtester limitation (n<30 samples, uncalibrated thresholds,
   single-market-regime window, no walk-forward) remains unchanged and still applies —
   this milestone closes 3 previously-disclosed gaps, it does not change the overall
   conclusion-level ceiling (still PRELIMINARY RESEARCH READING).

---

## 5. Background Process Note

PID 2924 (FinMind OHLCV drip backfill, running since M5c) was confirmed alive at session
start and continued progressing throughout this session's work (571→890/1963 stocks,
45.3%), then completed its run and exited cleanly at 2026-07-18 20:00:44 (hit its own
rate limit near the end, same family of throttle as everything else in this report — see
`outputs/logs/finmind_drip.log`). This session's new fetches (`finmind_div_*.json` for
dividend events) used a distinct filename prefix throughout and never competed with or
overwrote the drip process's own `finmind_<id>.json` OHLCV files, per the task's explicit
instruction.

---

## 6. Files Changed/Added (this milestone)

**New source modules**: `src/price_adjuster.py`, `src/disposition_fetcher.py`,
`src/leaderboard_loader.py`, `src/limit_up_history.py`, `src/leaderboard_reconciliation.py`

**New scripts**: `scripts/fetch_price_adjustments.py`, `scripts/run_leaderboard_analysis.py`

**Modified (additive only)**: `config/default.yaml` (+`backtest.use_adjusted_prices`),
`src/config_manager.py` (+ same default), `scripts/run_backtest.py` (+adjustment/
disposition wiring, unchanged existing logic), `scripts/run_daily.py`
(+`_load_disposition_ids_for_date`, +`disposition_flag` column, unchanged existing
logic), `src/report_generator.py` (+處置/注意 column on 個股優先排序 sheet only)

**Untouched (per governance rule #9 / task instruction)**: `src/backtester.py`,
`src/benchmarks.py`, `src/sector_scoring.py`, `src/conviction_engine`-class modules —
zero lines changed.

**New test files**: 7 new files + 1 additive block in `test_report_generator.py`, 56 tests.

**New data artifacts**: `data/raw/reports/*.xlsx` (36 files, copied), `data/raw/disposition/
*.json` (5 files), `data/raw/fundamentals/dividends/finmind_div_*.json` (516 files),
`data/reference/price_adjustment_factors.csv`, `outputs/leaderboard_analysis/*`.

**New evidence/receipts**: `loop/evidence/fetch_receipts/finmind_adjusted_price_probe_
2026-07-18.json`, `loop/evidence/fetch_receipts/price_adjustment_fetch_summary_
2026-07-18.json`, `loop/evidence/fetch_receipts/disposition_today_list_2026-07-18.json`.
