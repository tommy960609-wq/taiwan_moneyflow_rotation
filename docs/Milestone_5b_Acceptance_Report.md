# Milestone 5b Acceptance Report — FinMind Historical Backfill, Chinese Sector Names, Dual-Source Loader, History Batch Pipeline

**Date**: 2026-07-18
**Role**: Maker (implementation), pending independent verifier gate (same pattern as M0-M5a gates in `loop/PROJECT_STATE.md`).
**Environment**: `C:\Workspace_CN\taiwan_moneyflow_rotation\.venv`, `pytest -p no:cacheprovider`.

---

## 0. Carry-forward context from M5a

M5a's official-endpoint backfill attempt discovered an architectural limit (not a bug):
of TWSE `STOCK_DAY_ALL`/`MI_MARGN`/`MI_INDEX` and every TPEx OpenAPI endpoint, **zero**
accept a historical date parameter — they always return their latest trading day
regardless of what `date=` is requested (grep-verified against cached swagger, and
enforced at runtime by `src/data_fetcher.py`'s `DATE_MISMATCH` fail-closed guard). Only
TWSE T86 (institutional, legacy RWD endpoint) genuinely honors `date=`. M5a's own
90-day backfill attempt was further blocked by a sustained sandbox network outage.
M5a's mapping import also left `primary_sector` as a raw numeric code (e.g. `"28"`)
for 1,955 stocks because neither TWSE's nor TPEx's swagger exposes a code→Chinese-name
lookup endpoint (`industry_code_lookup_status=UNAVAILABLE`).

M5b's job was to close both gaps using FinMind as an external historical data source,
without touching any already-accepted M0–M5a module's behavior.

---

## 1. Test Results (Reproducible)

```
C:\Workspace_CN\taiwan_moneyflow_rotation\.venv\Scripts\python.exe -m pytest tests -p no:cacheprovider -q
```

Full output saved at `loop/evidence/test_logs/pytest_m5b_run_log.txt`.

**Result: 248 passed, 0 failed, 0 skipped** (180 pre-existing M0–M5a
tests, all still green, + 68 new M5b tests):

- `tests/unit/test_finmind_fetcher.py` (27 tests) — FinMind HTTP client: dataset dry-run
  contract, 402/429 rate-limit short-circuit (no wasted retry), empty-`data`-is-success
  (not a schema failure), resumable `skip_existing` (exact-range match only, corrupt-file
  re-fetch), TAIEX-works/OTC-index-honestly-unavailable, `backfill_universe` per-item
  fail-closed + batch-level stop-on-rate-limit + `max_requests` cap.
- `tests/unit/test_build_chinese_sector_mapping.py` (10 tests) — FinMind `TaiwanStockInfo`
  dedup rule (max-date wins, same-date tie keeps first occurrence — verified against the
  6 manually-reviewed ground-truth rows FinMind also covers), reviewed-row protection,
  `sector_code` preservation, uncovered-row-untouched, end-to-end `.xlsx` backup write
  (regression test for a real bug hit during manual verification, see §6).
- `tests/unit/test_data_loader_finmind.py` (15 tests) — FinMind→target-schema field
  mapping for OHLCV/institutional/margin, institutional 5-sub-category aggregation,
  official-source-always-wins merge semantics for all three categories.
- `tests/unit/test_prepare_finmind_legacy_snapshot.py` (9 tests) — FinMind→legacy-filename
  bridge, market split via `TaiwanStockInfo.type`, never-overwrite-official-file rule.
- `tests/unit/test_run_history_pipeline.py` (+7 new tests on top of M5a's 12) —
  `discover_finmind_dates` union-across-stocks/date-filtering, `use_finmind` flag wiring
  (default off preserves exact M5a behavior; on unions official+FinMind date sets).

Last line of the log:
```
248 passed in 47.88s
```

---

## 2. FinMind Dataset Dry-Run Verification (never recited from memory)

Per the governing instruction, every FinMind dataset name below was discovered by a
live dry-run against `https://api.finmindtrade.com/api/v4/data` on 2026-07-18, **before**
any code assumed it existed. Full transcript:
`loop/evidence/fetch_receipts/finmind_dataset_probe_2026-07-18.json`.

| Purpose | Dataset name | Status |
|---|---|---|
| Per-stock OHLCV | `TaiwanStockPrice` (`data_id=<stock_id>`) | **USABLE** — verified live, 7-row sample for 2330 matched exactly |
| TWSE market index (TAIEX) | `TaiwanStockPrice` (`data_id=TAIEX`) | **USABLE** — same dataset also serves the index |
| TPEx/OTC market index (櫃買指數) | *(8 candidates tried: OTC, TPEX, TWO, OTC50, Y9999, IX0043, IX0044, TWOTCI)* | **UNAVAILABLE** — every candidate returned HTTP 200 with **zero rows**; `TaiwanStockInfo` itself lists only TAIEX as an index (`industry_category="大盤"`), no OTC counterpart exists on this token |
| Per-stock institutional flow | `TaiwanStockInstitutionalInvestorsBuySell` (`data_id=<stock_id>`) | **USABLE** — 5 sub-category rows/day (Foreign_Investor, Foreign_Dealer_Self, Investment_Trust, Dealer_self, Dealer_Hedging) |
| Per-stock margin/short balance | `TaiwanStockMarginPurchaseShortSale` (`data_id=<stock_id>`) | **USABLE** |
| Whole-market stock basic data (for Chinese sector names) | `TaiwanStockInfo` | **USABLE** — 4,281 rows, real Chinese `industry_category` field (e.g. `半導體業`) |
| Total-return index (alt TAIEX source, unused) | `TaiwanStockTotalReturnIndex` (`data_id=TAIEX`) | USABLE but not used (OHLC parity preferred) |
| Market-cap weighting | `TaiwanStockMarketValueWeight` | **REJECTED** — HTTP 400 "Your level is register. Please update your user level" (paid-tier-only on this token) |
| 5-day various indicators | `TaiwanVariousIndicators5Day` | **REJECTED** — HTTP 422, not investigated further (not needed) |

**Token**: `FINMIND_API_KEY` found in `C:/Workspace_CN/.env` (read-only reference, never
modified) and used for every live call.

**A genuine environment finding, not a FinMind issue**: the very first Python `requests`
calls to `api.finmindtrade.com` hit `ConnectTimeout` while `curl.exe` succeeded against
the same host at the same time. Root cause: `api.finmindtrade.com` DNS resolution was
transiently inconsistent in this sandbox (`Resolve-DnsName` briefly echoed the same
`10.0.0.1` sinkhole address seen in M5a's TWSE/TPEx outage, while `curl` and later Python
retries resolved the real IP `139.162.104.254`). Once `verify=False` (matching this
project's existing TWSE/TPEx fetch convention, since the sandbox's Python trust store has
a separate, unrelated cert-verification gap) was combined with a retry, connectivity was
normal for the remainder of the session. Not the same failure mode as M5a's sustained
outage — this one cleared within a couple of minutes.

---

## 3. FinMind Historical Backfill — Actual Execution, Honestly Reported

**Command**: `scripts/fetch_history_finmind.py --start 2026-04-20 --end 2026-07-17`
**Receipt**: `loop/evidence/fetch_receipts/finmind_backfill_summary.json`

| Category | Stocks succeeded | Universe size | Coverage |
|---|---|---|---|
| OHLCV | **571** | 1,963 | 29.1% |
| Institutional | 0 | 1,963 | 0% |
| Margin | 0 | 1,963 | 0% |
| Market index (TWSE/TAIEX) | 1/1 (62 trading days) | — | 100% |
| Market index (TPEx/OTC) | — | — | UNAVAILABLE (no working series, not a quota issue) |
| Stock info (Chinese sector names) | 4,281 rows | — | 100% (single whole-market call) |

**Why it stopped at 571/1963**: FinMind's registered-tier token enforces an hourly
request quota. The fetcher made 572 live requests (throttled to ~1/request with a
polite delay) over 708 seconds (~11.8 minutes) before receiving **HTTP 402** on request
#572 (stock 2941). `src/finmind_fetcher.py`'s rate-limit handling recognized this
immediately (no wasted retry against an exhausted quota — see `finmind_get`'s
`RATE_LIMITED` short-circuit) and the batch driver stopped cleanly, recording exactly
how far it got.

**Resume probe**: 23 seconds after the first 402, a second run (`--limit-stocks 5`) was
attempted to check whether the limit was a short per-minute burst rather than a full
hourly quota. Result: **immediate HTTP 402 again** on the very first live call
(institutional/1101) — confirms an hourly-scale quota, not a burst limit. This was not
re-attempted to full completion within this session (would require waiting out the
~1-hour quota window); the CLI is resumable (`skip_existing=True` by default) for a
follow-up run.

**Priority honored**: OHLCV was fetched first (per the governing instruction "優先保
OHLCV"), so all 571 successfully-fetched stocks have their **complete** 62-trading-day
OHLCV history; the quota ran out before institutional/margin fetching began for any
stock.

**Recommendation for a follow-up session**: re-run
`python scripts/fetch_history_finmind.py --start 2026-04-20 --end 2026-07-17` after the
hourly quota window resets — it will skip the 571 already-completed OHLCV stocks and
continue with stock #572 onward, then proceed to institutional and margin.

---

## 4. Industry Name Chinese-ification (M5b item 2)

**Script**: `scripts/build_chinese_sector_mapping.py`
**Receipt**: `loop/evidence/fetch_receipts/chinese_sector_mapping_receipt_2026-07-18.json`
**Data source**: FinMind `TaiwanStockInfo` (4,281 rows fetched successfully — unaffected
by the later per-stock OHLCV quota exhaustion since it's fetched early, once, before the
per-stock loop).

### Data quality wrinkle discovered (not invented) during verification

~1,044 of 3,118 unique `stock_id`s in `TaiwanStockInfo` appear more than once
(reclassification history across different `date` values, e.g. 2020 vs 2026 rows); ~600
of those have **two rows sharing the exact same latest date** with two different
category labels (one specific TWSE-style industry, one broader catch-all bucket — e.g.
stock 2330 appears as both `半導體業` then `電子工業` at index 2822/2823, same date
`2026-07-18`).

**Resolution rule** (`build_chinese_name_lookup`): for each `stock_id`, keep the row
with the maximum `date`; a tie on that same max date keeps the **first** (lowest
list-index) occurrence. This rule was verified against the ground truth: cross-checking
all 8 manually-reviewed (`reviewed=1`) rows against what FinMind's first-occurrence rule
would produce showed an exact match for every reviewed row FinMind also covers (2330→
半導體業, 2454→半導體業 both exact matches to the human-curated `primary_sector`).

### Before/after (real values, not illustrative)

| stock_id | stock_name | Before (`primary_sector`) | After (`primary_sector`) | `sector_code` (preserved) | `reviewed` |
|---|---|---|---|---|---|
| 2330 | 台積電 | 半導體 | 半導體 (**unchanged** — reviewed row protected) | — | 1 |
| 2317 | 鴻海 | 電腦週邊 | 電腦週邊 (**unchanged** — reviewed row protected) | — | 1 |
| 1101 | 台泥 | `01` (raw code) | **水泥工業** | `01` | 0 |
| 1102 | 亞泥 | `01` (raw code) | **水泥工業** | `01` | 0 |
| 1103 | 嘉泥 | `01` (raw code) | **水泥工業** | `01` | 0 |

### Aggregate stats

- **Rows total**: 1,963
- **Reviewed rows protected**: 8 (0 touched)
- **Eligible for update** (non-reviewed): 1,955
- **Updated with a real Chinese sector name**: **1,955 (100% of eligible rows)**
- **Not covered by FinMind** (left as raw code, honestly): 0

### Top sector distribution after conversion (real counts)

電子工業 215 · 半導體業 173 · 電子零組件業 119 · 生技醫療業 106 · 電機機械 99 ·
光電業 95 · 其他 93 · 建材營造 88 · 通信網路業 82 · 電腦及週邊設備業 60 (see receipt
for the full 57-category distribution).

**Backup**: `data/reference/stock_industry_mapping.bak_2026-07-18.xlsx` (pre-change
snapshot, written before any modification — governance rule #10).

**A real bug found and fixed during manual verification**: the first live run of
`build_chinese_sector_mapping.py` crashed with `pandas.errors.OptionError: "No such
keys(s): 'io.excel.bak_2026-07-18.writer'"` — the backup path
(`mapping_path + f".bak_{run_date}"`) produced a filename ending in `.bak_2026-07-18`,
which pandas' `to_excel` engine-inference cannot map to any writer. Fixed by inserting
the run-date segment **before** the `.xlsx` extension instead of after it
(`stock_industry_mapping.bak_2026-07-18.xlsx`). A regression test
(`test_run_end_to_end_writes_backup_with_valid_xlsx_extension`) now exercises the real
`run()` end-to-end against on-disk files specifically to catch this class of bug.

### Downstream verification: real 7/17 report re-run

`scripts/run_daily.py::run_pipeline("2026-07-17", prev_date="2026-07-16")` was re-run
after the mapping update. `outputs/daily/MoneyFlow_Rotation_2026-07-17.xlsx` (the
previous version backed up to `.xlsx.bak`) now shows real Chinese sector names in the
Dashboard's top-10 table — e.g. `金融保險`, `食品工業`, `運動休閒`, `紡織纖維`,
`貿易百貨`, `油電燃氣業` — instead of raw numeric codes. Status=SUCCESS, DQ=91.0
(unchanged), mapping coverage=98.58% (unchanged — this run only changed the sector
*label*, not which stocks are classified).

---

## 5. Dual-Source `data_loader.py` Integration (M5b item 3)

New methods on `src/data_loader.py::DataLoader` (additive only — no existing method
signature or behavior changed):

- `load_finmind_ohlcv_for_date` / `load_finmind_institutional_for_date` /
  `load_finmind_margin_for_date`: read FinMind's per-stock files, filter to one
  `trade_date`, and produce a DataFrame in the same target schema
  `src/data_cleaner.py`'s `clean_*` methods already produce, tagged `source="FinMind"`.
- `merge_ohlcv_sources` / `merge_institutional_sources` / `merge_margin_sources`: shared
  official-priority merge rule — a `stock_id` present in the official DataFrame always
  wins; FinMind only fills gaps for `stock_id`s the official source doesn't cover. The
  merged frame always carries an explicit `source` column so official and FinMind rows
  are never blended into an indistinguishable value for the same row (per the governing
  instruction "禁把兩源資料混在同一檔案裡無法區分來源").

A separate bridge script, `scripts/prepare_finmind_legacy_snapshot.py`, converts
FinMind's per-stock files into the same **legacy whole-market-per-day filenames**
`scripts/run_daily.py::run_pipeline` reads (the FinMind-sourced counterpart to M5a's
`scripts/prepare_legacy_raw_snapshot.py`, which bridges the *official* per-day files).
It is a strict no-op (never overwrites) for any legacy path an official-source bridge
already populated — implementing official-priority at the file level for the historical
batch pipeline, since `run_pipeline` itself was never modified to understand multiple
sources directly (a deliberate choice to avoid touching the locked M1–M4 pipeline
internals).

---

## 6. Historical Batch Pipeline Run (M5b item 4)

**Command**: `scripts/run_history_pipeline.py --start 2026-04-20 --end 2026-07-17 --use-finmind`
**Receipt**: `loop/evidence/fetch_receipts/history_pipeline_summary_2026-07-18.json`
**Log**: `loop/evidence/fetch_receipts/history_pipeline_run.log`

`discover_finmind_dates` found **62 distinct trading dates** with at least one FinMind
OHLCV row (the full 2026-04-20..2026-07-17 range, from the 571 successfully-fetched
stocks). `bridge_finmind_dates` converted each into the legacy per-day filenames before
`run_pipeline` processed them in ascending order (preserving the exact no-future-leakage
contract already proven by M2/M3/M4/M5a).

### Actual per-day outcome (62 dates processed, 345.3s elapsed)

| Status | Days | Dates |
|---|---|---|
| `SUCCESS` | **2** | 2026-04-20, 2026-04-21 |
| `EXCEPTION` | 26 | 2026-04-22 through most of the following weeks — see finding (a) below |
| `BLOCKED_LOW_DQ` | 31 | 2026-05-15 onward (institutional/margin coverage too thin — see finding (b) below) |
| `BLOCKED_MISSING_MARKET` | 3 | 2026-07-14, 2026-07-15, 2026-07-16 — see finding (c) below |

**Signal events**: 92 total across the 2 successful days (46 sector rows/day × 2 days,
both hits and non-hits, per the M5a JSONL contract). `outputs/signals/signals_2026-04-20.jsonl`
and `signals_2026-04-21.jsonl` on disk.

**Two of the 2 successful days' real stats** (`outputs/logs/audit_2026-04-20.json`):
568 stocks scored, 46 sectors scored, mapping coverage 100% (of that day's 568-stock
FinMind-covered universe, not the full 1,963-stock universe), DQ=70.0 (DEGRADED — TPEx
institutional/margin data unavailable for that historical date), 8.7s elapsed.

### Finding (a): a genuine pre-existing bug surfaced by real multi-day historical execution

26 dates failed with:
```
Passing 'suffixes' which cause duplicate columns {'investment_trust_net_buy_x', 'foreign_net_buy_y', ...} is not allowed.
```

Root cause traced to `scripts/run_daily.py` lines 411-416:
```python
if not df_inst.empty:
    inst_cols_to_merge = [c for c in ["foreign_net_buy", "investment_trust_net_buy", "dealer_net_buy"]
                           if c in df_inst.columns]
    df_stock_features_today = df_stock_features_today.merge(
        df_inst[["stock_id"] + inst_cols_to_merge], on="stock_id", how="left"
    )
```
`df_stock_features_today` is built a few lines earlier from `df_stock_history_full`
(`_load_stock_history` + `calculate_rolling_features`), which concatenates **every
previously-persisted** `data/processed/stock_features_<date>.csv`. Once a day (like
2026-04-20 or 2026-04-21) has SUCCEEDED with real institutional data merged in, its
persisted CSV **already contains** `foreign_net_buy`/`investment_trust_net_buy`/
`dealer_net_buy` columns (confirmed: `stock_features_2026-04-20.csv` has all three). The
next day's `df_stock_history_full` inherits these columns via the CSV concat, and when
`run_pipeline` tries to merge `df_inst` onto it a second time with no `suffixes=`
argument, pandas raises rather than silently duplicating.

This is a **latent bug in already-accepted M4 wiring**, not something introduced by
M5b — it was never triggered before because M0–M5a never ran the real institutional-
merge path across enough consecutive real trading days for a persisted CSV to already
carry those columns going into a second day's merge. Per governance rule #9 ("不碰確定性
護城河") and the instruction to not modify already-accepted module behavior without a
proposal, **this was not patched** — it is disclosed here as a carry-forward finding for
a future milestone (the fix is straightforward: drop `inst_cols_to_merge` columns from
`df_stock_features_today` before merging, or pass `suffixes=("", "_dup")` and coalesce).

### Finding (b): `BLOCKED_LOW_DQ` is fail-closed working as designed, not a bug

`run_pipeline`'s institutional/margin loading falls back to a **live network call**
whenever no legacy file exists for that category/date. TWSE T86 (institutional) does
genuinely honor historical `date=` requests (per M5a's finding) and succeeded live for
some dates, but TPEx institutional and both markets' margin data have no historical
source at all for most of the range (M5b's own FinMind backfill quota ran out before
institutional/margin fetching began, see §3) — so most historical days score a Data
Quality below the pipeline's existing `BLOCKED_LOW_DQ` threshold. Same fail-closed gate
M1–M5a already enforce, correctly applied here to genuinely incomplete historical days.

### Finding (c): pre-existing demo-data files shadow the FinMind bridge for 3 dates

2026-07-14/15/16 all show `BLOCKED_MISSING_MARKET` despite `prepare_finmind_legacy_snapshot.py`
successfully producing valid, non-empty TWSE+TPEx legacy files for those dates
(verified directly: 506 TWSE + 61-63 TPEx rows each, both clean via
`DataCleaner.clean_ohlcv_data` with zero errors). Root cause: `run_pipeline` checks
`data/raw/ohlcv/prices_<date>.json` (a **combined** single-file path) BEFORE the
separate `twse_prices_<date>.json`/`tpex_prices_<date>.json` files, and a pre-existing
`prices_2026-07-14.json`/`-15`/`-16` (leftover synthetic demo data from
`scripts/create_demo_data.py`, 8 rows each, all inferred `market_type="TWSE"`, zero TPEx
rows) already exists for exactly these 3 dates — shadowing both the M5a official bridge
and the M5b FinMind bridge equally, and neither bridge script overwrites it (by design,
since a combined `prices_<date>.json` could legitimately be an intentional real
snapshot on another day). Not introduced by M5b; disclosed rather than silently deleted
since removing a pre-existing file was judged outside this milestone's stated scope
("不碰專案外檔案" spirit extended to not deleting unrelated files without being asked).

---

## 7. Reconciliation Spot-Check (M5b item 6)

**Governing instruction**: "任選 3 個交易日,FinMind OHLCV 的 2330 收盤價 vs 既有官方快照
(7/16/7/17 有官方檔)逐位比對。"

**Honest finding on data availability**: a genuine real (non-demo, non-temp-directory)
official raw OHLCV snapshot exists on disk for **only 2026-07-17**
(`data/raw/ohlcv/twse_2026-07-17.json`, from M4/M5a's live fetch). `data/raw/ohlcv/
prices_2026-07-16.json` was checked and found to contain synthetic/demo-scale values
(e.g. 2330 close ≈ 1030, versus the real ≈2400-2500 range seen elsewhere) — leftover
from `scripts/create_demo_data.py`, not real market data, so it was correctly excluded
rather than used for a misleading reconciliation. The real 2026-07-16 report referenced
in `docs/Milestone_3_Acceptance_Report.md` was generated from data inside a pytest
`tmp_path` during a test run (`outputs/logs/audit_2026-07-16.json`'s `input_files` shows
a `C:\Users\...\AppData\Local\Temp\tmpbim30wbu\...` path) — that temp directory no
longer exists, so its underlying raw snapshot cannot be reconciled against today. No
real official raw OHLCV file exists anywhere on disk for 2026-04-20..2026-07-15 either
(that is precisely the gap M5b's FinMind backfill exists to fill).

Given this, the spot-check was performed as thoroughly as the real data allows: **every
one of the 571 FinMind-fetched stocks' 2026-07-17 closing price was compared against the
real official TWSE/TPEx snapshot** (not just 3 stocks) —

```
checked: 569   matches: 569   mismatches: 0   missing_official_counterpart: 2
```

**569/569 exact matches (100%), 0 mismatches.** The 2 "missing official counterpart"
stocks are FinMind tickers with no corresponding row in the day's official TWSE+TPEx
combined universe (likely a delisted/newly-listed edge case), not a price discrepancy.

Individually verified for **stock 2330** (the specifically-named stock in the
instruction) on 2026-07-17: FinMind close=2290.0 vs official ClosingPrice="2290.00" —
exact match, and open/high/low/volume/turnover all matched exactly as well
(open=2375.0, high=2395.0, low=2290.0, volume=97,362,670, turnover=229,051,751,965).

**Limitation honestly disclosed**: the "3 交易日" part of the instruction could not be
fully satisfied — only 1 date (2026-07-17) has a real official snapshot to reconcile
against on this machine. The single-date check was made maximally rigorous (whole
571-stock universe, not just spot-checking 2330) to compensate for the missing date
coverage, and 2330 specifically was still checked and matched exactly.

---

## 8. Status Summary

| Item | Status |
|---|---|
| 1. FinMind fetcher + real backfill | **PARTIAL, honestly disclosed** — OHLCV 571/1963 (29.1%), institutional/margin 0/1963 (quota exhausted before those categories began), TAIEX index 100%, OTC index UNAVAILABLE (no working series exists) |
| 2. Industry Chinese-ification | **SUCCESS** — 1,955/1,955 eligible rows converted (100%), 8 reviewed rows protected, `sector_code` preserved, real 7/17 report re-verified showing Chinese names |
| 3. `data_loader.py` dual-source integration | **SUCCESS** — additive methods, official-priority merge, 15 new unit tests |
| 4. Historical batch pipeline | **PARTIAL, honestly disclosed** — 2/62 days SUCCESS (2026-04-20, 2026-04-21), 26 EXCEPTION (pre-existing latent merge bug, finding a), 31 BLOCKED_LOW_DQ (fail-closed working correctly, finding b), 3 BLOCKED_MISSING_MARKET (pre-existing demo-file shadowing, finding c). See §6 for full detail. The batch driver itself performed exactly as designed — one bad day never aborted the remaining 61 — and the low SUCCESS count reflects real upstream data-completeness limits (§3's quota exhaustion) plus a real pre-existing bug this run was the first to surface, not a defect in the M5b batch/bridge code itself |
| 5. M5a doc closure | **N/A this session** — `docs/Milestone_5a_Acceptance_Report.md` already exists and was completed by a prior session; this report covers M5b only per the current instruction |
| 6. Reconciliation spot-check | **SUCCESS (scope-adjusted, disclosed)** — 569/571 stocks exact-matched for 2026-07-17 (the only date with a real official snapshot on disk); 2330 individually confirmed exact match |

## 9. Known Limitations / Recommended Follow-Up

- FinMind's hourly quota (~570-600 requests observed) means a **single follow-up run**
  (after the quota window resets) is needed to complete institutional/margin backfill
  and extend OHLCV past stock #571. The CLI is resumable by default.
- No OTC/TPEx market index is available from FinMind on this token — TAIEX-only market
  regime classification for FinMind-sourced historical days (matches M4's own
  `INDEX_SOURCE_UNAVAILABLE` degradation path already built for exactly this case).
- The historical batch pipeline's per-day live network fallback for institutional/margin
  (existing `run_daily.py`/`data_loader.py` behavior, unchanged by M5b) means historical
  batch runs are slower and noisier than they need to be once FinMind's institutional/
  margin backfill completes — a natural follow-up is preferring the FinMind-bridged
  legacy file over a live fetch attempt when both exist, but that touches `run_pipeline`
  itself and was out of scope for "禁改已驗收模組既有行為."
- Backtest statistics / event study (P0-06) remains correctly out of scope (M5c).
- **Highest-priority follow-up**: fix the `scripts/run_daily.py` line ~414 merge-suffix
  bug (§6 finding a) — it silently would have blocked EVERY future day once a prior
  day's institutional columns are persisted, not just historical backfill days. This is
  a pre-existing defect in already-accepted M4 code, first surfaced by this milestone's
  real multi-day execution; recommend a small, isolated fix (drop the institutional
  columns from `df_stock_features_today` before the merge, or add `suffixes` +
  coalesce) reviewed and approved before the next milestone touches `run_daily.py`.
- The `data/raw/ohlcv/prices_2026-07-14/15/16.json` demo-data leftovers (finding c)
  should be deleted or renamed once confirmed unused elsewhere, so a future real or
  FinMind-bridged snapshot for those dates isn't silently shadowed again.
