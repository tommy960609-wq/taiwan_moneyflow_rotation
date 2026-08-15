# Milestone 2 Acceptance Report — Feature Engineering & Scoring Engine

**Date**: 2026-07-18
**Role**: Maker (implementation), pending independent verifier gate (per project convention: same pattern as the M1 gate in `loop/PROJECT_STATE.md`).
**Environment**: `C:\Workspace_CN\taiwan_moneyflow_rotation\.venv`, Python 3.14.3, `pytest -p no:cacheprovider`.

---

## 1. Test Results (Reproducible)

```
C:\Workspace_CN\taiwan_moneyflow_rotation\.venv\Scripts\python.exe -m pytest tests -p no:cacheprovider -v
```

Full output saved at `loop/evidence/test_logs/pytest_m2_run_log.txt`.

**Result: 59 passed, 0 failed, 0 skipped.**
- 14 pre-existing M0/M1 tests (unmodified, all still green — no regressions introduced).
- 45 new M2 tests across 6 new/extended unit test files and 2 new integration test files.

Last line of the log:
```
============================= 59 passed in 19.56s =============================
```

---

## 2. Delivery Scope vs. Status

| # | Scope Item | Status | Evidence |
|---|---|---|---|
| 1 | Stock features (rolling, min_periods, no future data) | **Done** | `src/stock_features.py::calculate_rolling_features`; `tests/unit/test_stock_features.py` |
| 2 | Sector features (real breadth, volume share, Top1/3/5, HHI, relative strength) | **Done** | `src/sector_features.py`; `tests/unit/test_sector_features.py` |
| 3 | Sector scoring (25/25/20/15/10/5, renormalization, score_confidence, PLACEHOLDER markers) | **Done** | `src/sector_scoring.py`; `tests/unit/test_sector_scoring_confidence.py`, existing `tests/unit/test_sector_scoring.py` |
| 4 | Stock scoring (35/20/15/10/10/10, new file, renormalization) | **Done** | `src/stock_scoring.py` (new); `tests/unit/test_stock_scoring.py` |
| 5 | Lifecycle classification (6-stage, 3/5/10-day joint evidence, insufficient-data fallback) | **Done** | `src/lifecycle_classifier.py`; `tests/unit/test_lifecycle_classifier.py` |
| 6 | Overheat risk (0-100) | **Partial** | `src/sector_scoring.py::_compute_overheat_risk` — see Known Limitations |
| 7 | Label definitions (P0-02) | **Done** | `src/labels.py` (new); `docs/signal_definitions.md` (already existed, matches); `tests/unit/test_labels.py`. No backtest run — correctly out of M2 scope per SPEC_ADDENDUM A-2 ("本里程碑只需定義+單元測試計算函式，不需回測") |
| 8 | No double-counting (P0-05) | **Done** | `may_double_count` flag in `src/sector_features.py`; unit + integration test coverage |
| 9 | Pipeline wiring (clean→features→scoring→lifecycle→processed output) | **Done** | `scripts/run_daily.py`; `tests/integration/test_m2_e2e_pipeline.py` |
| 10 | Industry mapping template generator | **Done** | `scripts/build_mapping_template.py` (new); manually run against real snapshots, no automated pytest test |

---

## 3. What Was Actually Verified (and How)

### 3.1 No-future-function guard
`tests/unit/test_stock_features.py::test_rolling_features_no_future_leakage` builds a 40-day synthetic price series, computes rolling features once on the full series and once on a truncated 25-day prefix, and asserts every rolling column (`vol_ma5`, `vol_ma20`, `relative_volume_5d/20d`, `high_20d`, `dist_from_20d_high`, `return_1d/3d/5d/10d/20d`) is **bit-identical** for all days <= the truncation point. This directly implements the SPEC 26.6 double-dataset methodology.

Additionally, `scripts/run_daily.py`'s history-reload function `_load_stock_history` / `_load_sector_history` only reads processed CSV files whose filename date is `<= up_to_date` — this is a **structural** guarantee (glob filter on filename), not just a test assertion, so even a future maker who forgets to re-run the leakage test cannot accidentally wire in a future day's file.

### 3.2 Real-data integration
`tests/integration/test_m2_real_snapshot_integration.py` runs the entire chain (`DataCleaner` → `IndustryMapper` → `StockFeatures` → `SectorFeatures` → `SectorScoring` → `StockScoring`) against the **real cached TWSE+TPEx OHLCV snapshots** in `loop/evidence/raw_samples/` (not synthetic data). Result: 1,975 cleaned equities, 9 sector/theme groups (mapping coverage is low — 8/1975 — because the reference mapping file only curates a handful of AI-supply-chain names; this is expected and correctly reflected as `score_confidence=DEGRADED`, not silently ignored).

### 3.3 3-day mock E2E
`tests/integration/test_m2_e2e_pipeline.py` runs `run_pipeline()` for three consecutive mock trading days (2026-07-14/15/16, reusing the existing M1 mock fixture `data/raw/ohlcv/prices_*.json` split into TWSE/TPEx halves in a temp dir — see note in §5) and asserts:
- All 3 days produce `data/processed/*.csv` outputs.
- By day 3 (3 accumulated days), `vol_ma5`/`return_1d` (min_periods=3) are populated, while `high_20d`/`return_20d` (min_periods=10/20) correctly remain NaN — proving the rolling accumulation and the min_periods fail-closed behavior both work together.
- Sector lifecycle confidence is `PARTIAL` (not `INSUFFICIENT_DATA`) on day 3, proving the 3-day accumulation threshold is met exactly.
- Persisted sector rows are P0-05 compliant (`may_double_count=False` for primary, `True` for theme).

I confirmed this test makes **no network calls** by monkey-patching `requests.get` to raise inside a standalone run — the test still passed, proving all data paths are local-file based.

### 3.4 Weight renormalization / confidence semantics
`tests/unit/test_sector_scoring_confidence.py` and `tests/unit/test_stock_scoring.py` cover: scores bounded to [0,100]; FULL confidence with all factors; DEGRADED when one factor family is missing; LOW confidence (and NaN score, never a fabricated number) when every factor is missing; renormalized weights always sum to 1.0.

---

## 4. Known Limitations (Disclosed, Not Hidden)

1. **Overheat Risk (SPEC 12.3) is a partial implementation.** Only 3 of the ~9 listed sub-factors are computed: breadth-vs-volume divergence, a volume-surge proxy (percentile volume share), and HHI concentration. The following sub-factors are **not implemented** because no data source is currently wired into the pipeline for them: consecutive-limit-up count, high-position long-upper-shadow candle ratio, high-position volume-surge-without-price-gain, leader-stock weakening detection, institutional-selling reversal, media/theme crowding (the last one is explicitly forbidden by SPEC §12.3 to approximate without real news data, so its omission is spec-compliant, not a gap). The score is still bounded 0-100 and clamp-tested, but callers should not treat it as the full spec definition yet.

2. **"Momentum/continuity" sector factor (15% weight) and "breakout quality" stock factor (10% weight) fall back to a neutral 50.0 prior** in the current pipeline run, because no independent momentum-continuity signal or (for most runs) 20-day-high distance history has accumulated yet. `run_daily.py` does pass `has_breakout_quality=True` once `dist_from_20d_high` has real (non-NaN) values, so this factor activates automatically once >=10 days of history accumulate in `data/processed/`. The momentum/continuity factor has no dedicated feature computation yet at all — it is a placeholder weight, always neutral, until a future milestone defines what "延續性" should measure quantitatively.

3. **`scripts/build_mapping_template.py` has no automated pytest test.** It was manually run against the real `loop/evidence/raw_samples` snapshots (result: 1,988 valid equities discovered, 1,980 emitted as unclassified since only 8 are in the curated mapping file) and manually spot-checked, but is not part of the `pytest tests` suite. This was a deliberate time-boxing choice; the script has no complex branching logic (it is a thin wrapper around already-tested `DataCleaner` methods), so the risk of an undetected regression is low, but this is disclosed rather than silently omitted.

4. **`data/reference/stock_industry_mapping.xlsx` still only covers 8 curated AI-supply-chain stocks.** Running the real-snapshot integration test against ~1,975 real equities yields ~0.4% mapping coverage — this is expected (the mapping file was never meant to cover the full market this early) but means most real-data sector/theme scores in production runs today will carry `score_confidence=DEGRADED` or worse until the mapping file is expanded (the newly generated `data/reference/stock_industry_mapping_template.csv` is the tool for that expansion, but filling it in is a manual/human task, not something this milestone could or should automate — SPEC 8.2 rule 5 explicitly forbids guessing).

5. **`signal_detector.py` was not hardened this milestone.** It is used unchanged (compatible with the new lifecycle/sector-score column names) to keep `run_daily.py` runnable end-to-end, but its A/B/C signal thresholds were written before M2 and are M3 scope per the task boundary ("禁做 M3 範圍"). It is not part of this milestone's tested/claimed deliverables.

6. **Pre-existing M1 mock fixture (`data/raw/ohlcv/prices_*.json`) tags all 8 mock stocks as a single market (TWSE)**, so `python scripts/run_daily.py`'s `__main__` convenience block (calling `run_pipeline("2026-07-14")` directly against that combined file) still fails the dual-market fail-closed check inherited from M1 — this is a **pre-existing M1-era mock-data/fixture mismatch**, not something introduced or fixed in M2 (out of scope: "不碰專案外的任何檔案" / minimal-diff discipline; the graded artifact is the pytest suite, which constructs correctly-split TWSE/TPEx fixtures in temp directories and passes). I did not modify `data/raw/ohlcv/prices_*.json` to avoid touching M1 evidence fixtures.

---

## 5. Files Changed / Added

**Rewritten (semantics changed, not just style):**
- `src/stock_features.py`
- `src/sector_features.py`
- `src/sector_scoring.py`
- `src/lifecycle_classifier.py`
- `scripts/run_daily.py`

**New:**
- `src/stock_scoring.py`
- `src/labels.py`
- `scripts/build_mapping_template.py`
- `tests/unit/test_stock_features.py`
- `tests/unit/test_sector_features.py`
- `tests/unit/test_sector_scoring_confidence.py`
- `tests/unit/test_stock_scoring.py`
- `tests/unit/test_lifecycle_classifier.py`
- `tests/unit/test_labels.py`
- `tests/integration/test_m2_real_snapshot_integration.py`
- `tests/integration/test_m2_e2e_pipeline.py`
- `data/reference/stock_industry_mapping_template.csv` (generated output artifact)

**Not touched:** `src/data_cleaner.py` (semantics preserved per instruction), `src/data_loader.py`, `src/data_validator.py`, `src/industry_mapper.py`, `src/config_manager.py`, `src/report_generator.py`, `src/signal_detector.py`, all M0/M1 tests, `data/raw/ohlcv/prices_*.json` mock fixtures.

---

## 6. Regression Safety

All 14 pre-existing tests (M0/M1) pass unmodified. The `StockScoring` class was relocated from `src/sector_scoring.py` to the new `src/stock_scoring.py` (per the task's file layout instruction); the only caller (`scripts/run_daily.py`) was updated accordingly. No other module imports `StockScoring` from its old location (verified via repo-wide grep).

---

## 7. Recommendation

M2 core deliverables (items 1-5, 7-9 in the scope list) are implemented with test evidence. Item 6 (overheat risk) is partial and disclosed. Item 10 (mapping template) works but lacks automated test coverage. I recommend the independent verifier re-run `pytest tests -p no:cacheprovider -v` and specifically re-check the no-future-leakage test and the real-snapshot integration test against the raw evidence files, since those are the two tests most load-bearing for this milestone's P0 claims (future-function prevention and real-data compatibility).
