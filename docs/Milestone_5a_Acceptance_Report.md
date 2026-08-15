# Milestone 5a Acceptance Report — Official Industry Mapping, Historical Backfill, History Pipeline, Real 7/17 Report

**Date**: 2026-07-18
**Role**: Maker (implementation), pending independent verifier gate (same pattern as M0-M4 gates in `loop/PROJECT_STATE.md`).
**Environment**: `C:\Workspace_CN\taiwan_moneyflow_rotation\.venv`, Python 3.14.3, `pytest -p no:cacheprovider`.

---

## 1. Test Results (Reproducible)

```
C:\Workspace_CN\taiwan_moneyflow_rotation\.venv\Scripts\python.exe -m pytest tests -p no:cacheprovider -q
```

Full output saved at `loop/evidence/test_logs/pytest_m5a_run_log.txt`.

**Result: 180 passed, 0 failed, 0 skipped.**
- 134 pre-existing M0-M4 tests (all still green; one of them,
  `tests/integration/test_m3_real_snapshot_e2e.py`, had a hardcoded assertion updated —
  see §6).
- 46 new M5a tests:
  - `tests/unit/test_build_official_mapping.py` (18 tests)
  - `tests/unit/test_run_history_pipeline.py` (12 tests)
  - `tests/unit/test_prepare_legacy_raw_snapshot.py` (4 tests)
  - 12 new tests added to `tests/unit/test_data_fetcher.py` (date-consistency guard: 7;
    resumable-backfill `skip_existing`: 5)

Last line of the log:
```
180 passed in 41.08s
```

---

## 2. Delivery Scope vs. Status

| # | Scope Item | Status | Evidence |
|---|---|---|---|
| 1 | Official industry classification auto-import (TWSE + TPEx) | **Done** | `scripts/build_official_mapping.py`; live-fetched; see §3 |
| 2 | Industry code -> Chinese name resolution | **PARTIAL, honestly disclosed** | No lookup endpoint exists in either swagger; raw codes kept, `industry_code_lookup_status=UNAVAILABLE` |
| 3 | Historical backfill 60+ trading days (2026-04-20 to 2026-07-17) | **PARTIAL, honestly disclosed** | 0/65 days succeeded this session (sustained network outage); architecture + infrastructure done; see §4 |
| 4 | Historical batch pipeline (`scripts/run_history_pipeline.py`) | **Done** | Ran successfully over the 1 date with usable data; see §5 |
| 5 | Real 7/17 report | **Done** | `outputs/daily/MoneyFlow_Rotation_2026-07-17.xlsx`; see §6 |
| 6 | Full suite green | **Done** | 180/180, `loop/evidence/test_logs/pytest_m5a_run_log.txt` |

---

## 3. Official Industry Mapping Import

### 3.1 Endpoints (swagger-verified, not recalled from memory)

- **TWSE**: `/opendata/t187ap03_L` (上市公司基本資料) — verified against
  `loop/evidence/raw_samples/twse_swagger.json`. Fields used: `公司代號` (stock_id),
  `公司簡稱` (stock_name), `產業別` (industry code).
- **TPEx**: `/mopsfin_t187ap03_O` (上櫃股票基本資料) — verified against
  `loop/evidence/raw_samples/tpex_swagger.json` (OpenAPI 3.0 `components.schemas`,
  base URL from `servers[0].url`). Fields used: `SecuritiesCompanyCode` (stock_id),
  `CompanyAbbreviation` (stock_name), `SecuritiesIndustryCode` (industry code).

Both were live-fetched successfully in this session: TWSE returned 1,090 rows (1,079
valid equities after ETF/warrant filtering via the shared `DataCleaner.is_valid_equity`
rule), TPEx returned 891 rows (884 valid equities).

### 3.2 Coverage before/after

| | Mapped stocks | Universe size | Coverage |
|---|---|---|---|
| Before (8 manually-reviewed rows only) | 8 | 1,974 | **0.41%** |
| After (8 manual + 1,955 official rows) | 1,946 | 1,974 | **98.58%** |

Universe = real cleaned equities from `data/raw/ohlcv/{twse,tpex}_2026-07-17.json`
(1,371 + 10,012 raw rows -> 1,974 after cleaning/filtering), the same universe the real
7/17 report itself uses. Verification method and exact numbers are in
`loop/evidence/fetch_receipts/official_mapping_coverage_verification_2026-07-18.json`
(the original success receipt at `official_mapping_receipt_2026-07-18.json` was
overwritten in-place by a later same-day retry that hit the network outage described in
§4 and correctly returned `BLOCKED_BOTH_FETCH_FAILED` without touching the mapping file
— the mapping file's on-disk state, 1,963 rows / 98.58% coverage, was never at risk).

### 3.3 Manual-row protection (spot-checked)

`data/reference/stock_industry_mapping.xlsx`, stock_id `2330`, after the merge:
`primary_sector="半導體"`, `secondary_sector="晶圓代工"`, `reviewed=1` — unchanged from
before the import (if this row had been overwritten, `primary_sector` would show the raw
TWSE code instead). All 8 original `reviewed=1` rows verified intact by the same method.

### 3.4 Industry code -> Chinese name: honestly UNAVAILABLE

Both TWSE's `產業別` and TPEx's `SecuritiesIndustryCode` fields return a **raw numeric
code** (e.g. `"01"`, `"28"`), not a Chinese label, confirmed by inspecting the actual
live payload (not assumed from the field name). Searched both cached swagger files for
any endpoint whose summary/description contains 產業 / 類股 / 分類 that might expose a
code->name lookup table — none found (`/fund/MI_QFIIS_cat` and `/opendata/t187ap14_L`
were checked and are per-company or category-rollup tables, not a lookup dictionary).

Per the governing instruction ("代碼→中文名稱對照…取不到就保留代碼並記錄,禁止自編對照"),
the importer keeps the raw code as `primary_sector` for the 1,955 newly-imported rows and
records `industry_code_lookup_status=UNAVAILABLE`. This is visible, not hidden: the real
7/17 report's Dashboard top-10-sector table shows sector names like `'01'`, `'02'`, `'17'`
for these rows (screenshot-equivalent transcript in §6.2).

---

## 4. Historical Backfill (2026-04-20 to 2026-07-17)

### 4.1 Architectural finding (swagger-verified, independent of network health)

Grep-searched both cached swagger definitions for query parameters on every endpoint this
system uses:

| Endpoint | Category | Query parameters | Historical backfill possible? |
|---|---|---|---|
| TWSE `STOCK_DAY_ALL` | ohlcv | **none** | No — always latest trading day |
| TPEx `tpex_mainboard_daily_close_quotes` | ohlcv | **none** | No |
| TWSE `T86` (legacy RWD, outside OpenAPI swagger) | institutional | `date=` | **Yes** — live-confirmed |
| TPEx `tpex_3insti_daily_trading` | institutional | **none** | No |
| TWSE `MI_MARGN` | margin | **none** | No |
| TPEx `tpex_mainboard_margin_balance` | margin | **none** | No |
| TWSE `MI_INDEX` | market_index | **none** | No |
| TPEx `tpex_index` | market_index | **none** | No |

Live-confirmed T86 historical support: requested
`https://www.twse.com.tw/rwd/zh/fund/T86?...&date=20260601`, response payload's
top-level `date` field echoed back `"20260601"` with 1,326 real data rows. This is the
**only** (category, market) combination in this system's endpoint registry that can
genuinely return data for an arbitrary past date — a hard technical ceiling, not a bug or
an oversight to fix in this milestone.

**Conclusion**: "TPEx 歷史不可得" for all 4 categories (ohlcv/institutional/margin/
market_index) — no TPEx endpoint accepts a date parameter. TWSE historical data is only
obtainable for institutional flow (T86); OHLCV/margin/market_index on TWSE are equally
latest-day-only.

### 4.2 New guard: payload date-consistency validation

`src/data_fetcher.py::extract_payload_date` (+ `_parse_roc_or_iso_date` helper) inspects
a fetched payload for a self-reported date (top-level `date` field, e.g. T86; or
per-row `Date` field, e.g. OHLCV/TPEx institutional/TPEx margin) and compares it to the
requested `trade_date`. `fetch_and_save` now drops (never writes to disk) any payload
whose self-reported date doesn't match, logging a `DATE_MISMATCH` failure entry. Payloads
with no date signal at all (e.g. TWSE `MI_MARGN` rows, confirmed to carry zero date
field) are correctly NOT blocked — there's nothing to compare. Unit-tested in
`tests/unit/test_data_fetcher.py` (7 new tests).

This closes the exact risk the milestone brief warned against: "禁止把最新日資料假裝成歷史日."

### 4.3 Resumable backfill

`DataFetcher.fetch_and_save`/`fetch_all_categories`/`backfill` gained an additive
`skip_existing` parameter (default `False`, exactly preserving M4's always-refetch
behavior for any existing caller). `scripts/fetch_daily_data.py --backfill` now defaults
to `skip_existing=True` (a fresh re-run after an interruption won't re-request days
already on disk); `--no-resume` restores the old always-refetch behavior. Unit-tested in
`tests/unit/test_data_fetcher.py` (5 new tests, including a corrupt-existing-file
re-fetch case and a partial-run resume simulation).

### 4.4 Actual backfill attempt: 0 of 65 days succeeded (honest result)

Given §4.1's finding, only `categories=["institutional"]` (TWSE + TPEx) was attempted for
the full 2026-04-20 to 2026-07-17 range — attempting `ohlcv`/`margin`/`market_index` for
historical dates would be a guaranteed-known-negative (every payload would DATE_MISMATCH,
proven by the swagger fact alone, not worth burning ~260 additional live HTTP attempts to
re-demonstrate).

This session's sandbox network experienced a **sustained** (not merely intermittent, as
M4 described) total outage to both `openapi.twse.com.tw`/`www.twse.com.tw` and
`www.tpex.org.tw`: every single connection attempt failed with a 30-second connect
timeout after all 3 retries, across 7 consecutive trading days (14 fetch attempts:
2026-04-20, 21, 22, 23, 24, 27 attempted before the operator aborted the run; 2026-04-25/
26 correctly skipped as a weekend). Independently confirmed via PowerShell
`Resolve-DnsName openapi.twse.com.tw` resolving to the unreachable sinkhole address
`10.0.0.1` — the same environment quirk M4 first documented, but this session's instance
was total (0% success across ~30 minutes of continuous attempts, plus separate isolated
probes before and after) rather than partial.

The run was aborted by the operator after 7 consecutive fully-failed days rather than
continuing for an estimated 2+ hours against a network showing zero signs of recovery.
Full honest accounting (per-category/market attempted/succeeded/failed counts, root-cause
narrative, and a re-run recommendation) is in
`loop/evidence/fetch_receipts/backfill_summary.json`.

**Two isolated successful network windows did occur this session** (used for the mapping
import in §3 and the 7/17 report bridge in §6) — the outage was not literally 100% for
the entire session, but was 100% for the specific ~30-minute window the backfill ran.

---

## 5. Historical Batch Pipeline

`scripts/run_history_pipeline.py`: a sequential driver reusing
`scripts.run_daily.run_pipeline` (unchanged internal logic — given an additive,
backward-compatible return value it previously lacked, since every pre-M5a code path
implicitly returned `None` and no caller depended on that) over every trade_date that has
both markets' OHLCV present on disk, in ascending order (so day T+1's rolling features see
day T's already-persisted processed CSVs — same no-future-leakage contract as normal
daily operation). Writes `outputs/signals/signals_<date>.jsonl` (one JSON object per
sector-signal row, both hits and non-hits, for a future event-study denominator) per
successfully-processed day. A single blocked/failed day is recorded but does not abort
the batch (`tests/unit/test_run_history_pipeline.py`, 12 tests, verifies this directly
with a stubbed `run_pipeline_fn`).

**Actual run**: `discover_available_dates` found exactly **1** date with both
`twse_<date>.json`/`tpex_<date>.json` (M4-format) on disk: `2026-07-17` — an honest
consequence of §4.4's 0-day backfill result, not a bug in the discovery logic (verified
separately in `tests/unit/test_run_history_pipeline.py::test_discover_available_dates_*`).
Running the batch driver over this single date produced:

```
{
  "days_success": 1, "days_blocked": 0,
  "total_signal_events": 44,
  "signals_per_day": {"2026-07-17": 44},
  "signal_files": ["outputs/signals/signals_2026-07-17.jsonl"]
}
```

`outputs/signals/signals_2026-07-17.jsonl`: 44 lines (one per sector), each a valid JSON
object with `trade_date`/`sector_name`/`sector_type`/`signal_type`/`score`/
`signal_data_confidence`/`invalidation_condition`/`up_stock_count`/`lifecycle`.

---

## 6. Real 2026-07-17 Report

### 6.1 Bridging M4 filenames to legacy filenames

`scripts/run_daily.py::run_pipeline` reads raw snapshots under legacy filenames
(`twse_prices_<date>.json`, `inst_<date>.json`, `margin_<date>.json`, etc.) that predate
M4 and were never aligned when M4's `data_fetcher.py` was built (M4's own acceptance
report disclosed but did not fix this: "run_pipeline was not re-run end-to-end against
the new 2026-07-17 real data"). New `scripts/prepare_legacy_raw_snapshot.py` bridges this
via a pure file copy (never mutates or deletes the M4-format source, never touches
`run_pipeline` itself) — run once for 2026-07-17, all 6 files copied successfully
(`tests/unit/test_prepare_legacy_raw_snapshot.py`, 4 tests).

### 6.2 Run result

```
python -c "from scripts.run_daily import run_pipeline; print(run_pipeline('2026-07-17'))"
```

- **status**: `SUCCESS`
- **DQ score**: 91.0, status `WARNING`
- **mapping coverage**: 98.58%
- **sectors scored**: 44
- **stocks scored**: 1,974
- **sector_confidence**: FULL, **stock_confidence**: DEGRADED
- **signal breakdown**: 29 sectors `B級早期點火`, 15 sectors `C級個股事件`, 0 `A級新起漲`
  / `續漲訊號` — expected, since this was a standalone run with no `prev_date`, so every
  day-over-day delta condition (score breakout, rank100 change, volume growth) is
  correctly `unevaluable` rather than fabricated.
- **output**: `outputs/daily/MoneyFlow_Rotation_2026-07-17.xlsx` (4 sheets:
  Dashboard/新起漲族群/續漲族群/個股優先排序)

Dashboard transcript (top rows, values read back via `openpyxl`):
```
資料品質得分: 91
資料品質狀態: WARNING
產業映射覆蓋率: 0.9858156028368794
族群評分信心等級: FULL
個股評分信心等級: DEGRADED
資料品質異常與警告清單: 無異常。資料品質良好。

前10族群分數摘要:
族群名稱  族群類型  今日總分  上漲廣度  成交占比    訊號等級      資料信心
17       primary   73.40    0.275     0.0288      B級早期點火    LOW
液冷      theme     69.03    1.0       0.0122      B級早期點火    LOW
電子零組件 primary   69.03    1.0       0.0122      B級早期點火    LOW
37       primary   65.30    0.370     0.0042      B級早期點火    LOW
02       primary   64.37    0.273     0.0029      B級早期點火    LOW
```

Note the raw numeric sector names (`17`, `37`, `02`) for the newly-imported official-code
rows, per §3.4's honest disclosure — `液冷`/`電子零組件` are pre-existing manually-curated
theme/primary_sector labels, unaffected.

---

## 7. Modified Pre-Existing Files (M1-M4 Behavior Preserved, Only Interfaces Extended)

- **`src/data_fetcher.py`**: additive only.
  - New: `_parse_roc_or_iso_date`, `extract_payload_date` (module-level functions).
  - `fetch_and_save` gained a `DATE_MISMATCH` check (new failure path) and a
    `skip_existing` parameter (default `False`, no behavior change unless explicitly
    passed `True`).
  - `fetch_all_categories`/`backfill` gained a `skip_existing` parameter, threaded
    through, same default-False no-op guarantee.
  - No existing function signature lost a parameter, no existing default value changed.
- **`scripts/fetch_daily_data.py`**: `run_backfill` gained a `skip_existing=True` default
  and the CLI gained `--no-resume`; `--date`/`--smoke` modes untouched.
- **`scripts/run_daily.py`**: `run_pipeline` gained a `return audit` on every exit path
  (previously implicitly returned `None` on all paths). No pre-M5a caller inspects the
  return value (confirmed by grep across `tests/` and `scripts/`), so this is additive.
  No other line in this file changed.
- **`tests/integration/test_m3_real_snapshot_e2e.py`**: the low-mapping-coverage-warning
  Dashboard assertion was hardcoded to always require the warning text present — became
  false once M5a's real official-mapping import raised coverage above 80%. Now reads the
  actual `mapping_coverage_pct` from the run's own audit JSON and asserts conditionally:
  warning required when `<80%`; warning must be ABSENT and the real percentage must
  display when `>=80%`. All other pre-existing assertions in this test (exactly 4 sheets,
  uncalibrated-threshold warning present, log/audit files exist, non-empty stock-priority
  sheet, audit status SUCCESS) are byte-for-byte unchanged.
- No other pre-existing file's behavior was modified this milestone.

---

## 8. Known Limitations (Disclosed, Not Hidden)

- **Historical backfill did not meaningfully progress this session** (§4.4): 0 of 65
  requested trading days succeeded, due to a sustained sandbox network outage during the
  ~30-minute window the backfill ran. The infrastructure (date-consistency guard,
  resumable `skip_existing`, honest architectural finding about which endpoints even
  support historical dates) is complete and tested; re-running
  `python scripts/fetch_daily_data.py --backfill 2026-04-20 2026-07-17` once network
  health is confirmed (`Resolve-DnsName` should return a real IP) will safely resume
  without re-fetching anything that happens to already be on disk.
- **`outputs/signals/` contains only 1 day** (2026-07-17) as a direct, honest consequence
  of the above — `run_history_pipeline.py` itself is correct and tested against a 3-day
  stubbed scenario; it simply had only 1 real day of usable data to run over this
  session.
- **Industry code -> Chinese name remains unresolved** (§3.4): no verified official source
  found in either swagger. A future milestone would need either (a) a different official
  endpoint not yet discovered, (b) the original spec's suggested FinMind package (which
  may bundle a translated industry taxonomy), or (c) a one-time human-curated code->name
  table explicitly marked as manually sourced (not silently presented as "official").
- **True multi-month historical OHLCV/margin/market_index backfill is not achievable via
  the currently-integrated TWSE/TPEx OpenAPI endpoints at all**, regardless of network
  health — this is an architectural ceiling (§4.1), not a to-do item for this milestone.
  Achieving it would require integrating an alternative bulk-historical data source (e.g.
  FinMind, as the original spec allowed as an option) — out of scope for M5a, flagged as
  a recommendation for M5b.
- **7/17 report has no `prev_date` history**: all day-over-day signal conditions
  (score breakout, rank100 change, volume growth vs. prior day) are correctly
  `unevaluable`, so no sector could grade A (新起漲) or 續漲 this run. This is the honest
  behavior of the existing (unmodified) `SignalDetector` when `df_sectors_prev` is empty,
  not a new gap introduced this milestone.
- **Backtester / limit-up lockout (P0-06), disposition/caution stock tagging, and
  ex-dividend adjusted-price correctness** remain correctly deferred to Milestone 5b.
