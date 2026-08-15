# Milestone 8: 修復批次小項包 (Small-fix Batch) — Report

**Date**: 2026-07-19
**Scope**: 5 small, independent fixes from `docs/open_issues_audit_2026-07-19.md`.
Explicitly excluded: signal detector thresholds, sector/stock scoring weights, backtest
logic, and any interaction with the live FinMind drip backfill process (PID 9836).

## Summary

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | `run_daily.py` empty-market `KeyError` fix | **DONE** | `scripts/run_daily.py`, `tests/regression/test_run_daily_empty_market_crash.py` |
| 2 | `load_excel_leaderboard` path configurable | **DONE** | `config/default.yaml`, `src/config_manager.py`, `scripts/run_daily.py`, `tests/unit/test_load_excel_leaderboard_config.py` |
| 3 | `scripts/backfill_status.py` truth tool | **DONE** | `scripts/backfill_status.py`, `tests/unit/test_backfill_status.py` |
| 4 | First coverage measurement | **DONE** | `loop/evidence/test_logs/coverage_first_measurement.txt` |
| 5 | Governance registration | **DONE** | `loop/PROJECT_STATE.md`, `loop/KNOWN_ISSUES.md` |

Full suite: **374 passed**, 0 failed (361 baseline + 13 new, net of 1 flipped
assertion). Log: `loop/evidence/test_logs/pytest_m8_run_log.txt`.

## Item 1: `run_daily.py` empty-market `KeyError`

**Root cause** (unchanged from the original M6 finding): when both TWSE and TPEx
OHLCV sources are empty (no bridge file on disk AND the legacy live-fallback fetch
also returns nothing), `pd.concat([pd.DataFrame(), pd.DataFrame()])` produces a
zero-column frame. The old code indexed `df_prices["market_type"]` immediately,
raising `KeyError` two lines before the intended `BLOCKED_MISSING_MARKET` check could
run.

**Fix**: in `scripts/run_daily.py`, before the two `df_prices[df_prices["market_type"]
== ...]` lines, added:
```python
if "market_type" not in df_prices.columns:
    df_twse_chk = pd.DataFrame()
    df_tpex_chk = pd.DataFrame()
else:
    df_twse_chk = df_prices[df_prices["market_type"] == "TWSE"]
    df_tpex_chk = df_prices[df_prices["market_type"] == "TPEx"]
```
Both resulting frames are empty either way, so the existing `if df_twse_chk.empty or
df_tpex_chk.empty:` branch (already writing `BLOCKED_MISSING_MARKET` + audit summary)
now runs cleanly instead of the crash ever happening. No other line in `run_pipeline`
changed.

**Test**: `tests/regression/test_run_daily_empty_market_crash.py`'s first test was
renamed `test_both_markets_empty_returns_blocked_missing_market` and its assertion
flipped from `pytest.raises(KeyError, match="market_type")` to asserting
`audit["status"] == "BLOCKED_MISSING_MARKET"` and both row counts are `0`. This is the
authorized assertion-direction flip called out in the task. The second test in that
file (`test_root_cause_empty_concat_has_no_market_type_column`) is unchanged — it
documents the underlying pandas mechanism, not `run_daily.py`'s handling of it, and is
still a true fact after the fix.

## Item 2: `load_excel_leaderboard` path configurable

**Change**: `config/default.yaml` gained a new `reconciliation.leaderboard_dir` key
(also added to `ConfigManager.get_defaults()`), default value
`"C:/Workspace_CN/Quant-Agent"` — the exact string that was previously hardcoded
directly into the glob pattern in `scripts/run_daily.py`. `load_excel_leaderboard` now
takes an optional `leaderboard_dir` parameter; `run_pipeline` reads it from the
already-instantiated `config` object and passes it through explicitly (rather than
having the function build its own `ConfigManager()`, so tests that mock
`ConfigManager.get` still control this path).

If the resolved directory doesn't exist on disk, the function now logs
`"Leaderboard directory not found (...); skipping reconciliation"` and returns an
empty DataFrame immediately, before ever calling `glob.glob`. Previously an
already-missing directory would just produce an empty glob result silently (same
observable outcome, but now explicit and logged, and the directory itself is
guaranteed to exist before any filesystem walk is attempted).

**Behavior-neutral**: with the config file untouched, `load_excel_leaderboard`
resolves to the identical directory it always searched — verified by
`test_default_leaderboard_dir_matches_pre_m8_hardcoded_path`.

**Tests** (`tests/unit/test_load_excel_leaderboard_config.py`, 5 tests): missing
directory returns empty without raising; configured directory with no matching file
returns empty; configured directory that does contain a matching `Report_*.xlsx` is
found and parsed correctly (built a synthetic xlsx with the real Chinese headers);
default config value matches the pre-M8 hardcoded path; `get_defaults()` includes the
new key.

`scripts/smoke_test_pipeline.py`'s existing `mock_load_leaderboard` helper was updated
to accept the new `leaderboard_dir` keyword argument (it's a plain function used with
`patch(..., mock_load_leaderboard)`, not a `MagicMock`, so it needed the signature
change to not break when `run_pipeline` now calls it with that kwarg).

## Item 3: `scripts/backfill_status.py`

**Why**: the audit found `loop/evidence/fetch_receipts/finmind_backfill_summary.json`
is a stale snapshot of one past execution and does not reflect the live background
drip process's cumulative progress. This tool has no memory of past runs — it counts
`finmind_<stock_id>.json` files under `data/raw/{ohlcv,institutional,margin}/` on disk,
right now, every time it's invoked, and divides by the live row count of
`data/reference/stock_industry_mapping.xlsx` (1,963 as of this session, read live —
not hardcoded).

It deliberately does **not** count same-day snapshot files (`twse_prices_<date>.json`,
`margin_<date>.json`, etc.) — those are a separate, unrelated artifact family; a regex
(`^finmind_(?P<stock_id>[A-Za-z0-9]+)\.json$`) restricts the scan to per-stock backfill
files only.

Output modes: plain invocation prints a human-readable table; `--json` prints strict
JSON (`generated_at`, `universe_size`, `universe_source`, and per-category
`file_count`/`universe_size`/`coverage_pct`/`oldest_mtime`/`newest_mtime`).
`coverage_pct` is `None` (never `0` or a fabricated number) when the universe size is
unavailable, per the project's "缺數據就留空" rule.

**Live run against the real `data/` directory during this session** (2026-07-19,
~09:36, read-only, did not touch the drip process or its output files):

```
Category                Files    Coverage                Oldest                Newest
ohlcv               1877/1963      95.62%   2026-07-18T13:41:13   2026-07-19T08:59:46
institutional         97/1963       4.94%   2026-07-18T14:32:55   2026-07-19T09:36:06
margin                 2/1963        0.1%   2026-07-18T14:32:58   2026-07-18T14:33:00
```

This is meaningfully different from the audit's snapshot the day before (institutional
26/1963) — the drip process appears to now be progressing institutional data too, not
just OHLCV. This number is already stale by the time you read this report; re-run the
tool for the current state.

**Tests** (`tests/unit/test_backfill_status.py`, 8 tests, all `tmp_path`-based, none
touch real `data/`): missing mapping file returns `None` universe size; mapping row
count read correctly; missing category directory reported as `dir_exists: False`;
scan counts only `finmind_<stock_id>.json` and correctly excludes same-day snapshot
filenames; full computed status with 100% coverage; missing-universe case never
fabricates a percentage; mtimes reflect actual file modification times; empty
directories report `None` mtimes and `0.0%` (not `None`) coverage since the universe
size is known in that case.

`loop/KNOWN_ISSUES.md`'s item about the stale receipt file has been moved to the
Resolved section, annotated to point at this tool.

## Item 4: first coverage measurement

`coverage` (7.15.2) installed into `.venv`, added to `requirements.txt` under a
dev-only comment block. Full suite run once via `coverage run -m pytest tests -p
no:cacheprovider -q` (374 passed under coverage too, confirming no interaction with
the coverage instrumentation). Report generated with `coverage report -m
--include="src/*,scripts/*"` and saved verbatim (with a header explaining methodology
and headline numbers) to `loop/evidence/test_logs/coverage_first_measurement.txt`.

**Headline**: core `src/` = 86% (2,786 statements, 378 missed); whole project
(`src/`+`scripts/`) = 80% (4,449 statements, 884 missed). Both meet spec §28.1's gates
(core ≥85%, whole project ≥75%) on this first measurement.

This is explicitly measurement-only, per the task instruction — no test was added or
altered to move this number, and no CI gate has been wired to enforce it going
forward. The lowest-coverage files (`scripts/run_backtest.py` 28%,
`scripts/fetch_daily_data.py` 16%, `scripts/backfill_status.py` 62% for its own new
CLI wrapper) are noted in the evidence file as informational only — not acted on this
milestone, since touching backtest logic and chasing coverage numbers are both outside
this milestone's authorized scope.

## Item 5: governance registration

`loop/PROJECT_STATE.md`: added a new Current Position entry for M8 and a matching
Revision Log entry; documented the PID lineage gap the audit found (`PID 2924`
completed cleanly 2026-07-18 20:00:44 at 890/1963 OHLCV; a new, previously
undocumented `PID 9836` was found alive, started 2026-07-18 22:17 with
`--sleep-between 30`, logging to `outputs/logs/finmind_drip_3.log`) and pointed future
sessions at `scripts/backfill_status.py`'s live output rather than any receipt file or
a number frozen into a past PROJECT_STATE.md entry.

`loop/KNOWN_ISSUES.md`: rewritten with a "已解決（M8）" section containing the 4 items
this milestone closed (empty-market KeyError, leaderboard hardcoded path, stale
receipt file, missing coverage package), and a note at the top directing readers to
run `backfill_status.py` for current backfill numbers instead of trusting any number
written into this file.

`loop/ACCEPTANCE_MATRIX.md`, `loop/CHANGELOG.md`, `loop/TASK_QUEUE.md` all received a
matching M8 entry in the same style as prior milestones.

## What was explicitly NOT touched

- Signal detector thresholds / `config/default.yaml`'s `# PLACEHOLDER - UNCALIBRATED`
  weight blocks — unchanged.
- `src/backtester.py`, `src/benchmarks.py`, `src/sector_scoring.py` scoring/backtest
  logic — unchanged, zero lines.
- The background drip process (PID 9836) and any file under `data/raw/` it is
  currently writing — observed read-only via `backfill_status.py`, never modified,
  restarted, or interacted with.
- No `git commit` was made (out of this milestone's authorized scope; task explicitly
  says commit only when the user asks).

## Known limitations of this batch

- The `reconciliation.leaderboard_dir` default still points at
  `C:/Workspace_CN/Quant-Agent`, a directory outside this project — this is
  intentional (behavior-neutral default per the task's requirement), not a leftover
  bug; a future session/user can override it in `config/default.yaml` for a different
  machine.
- `scripts/backfill_status.py`'s own `main()`/CLI argument-parsing path and the
  human-readable table renderer aren't unit-tested line-by-line (62% coverage on this
  new file) — the core computation functions (`compute_backfill_status`,
  `_scan_category`, `_get_universe_size`) are fully covered; the thin CLI wrapper was
  smoke-tested manually (see the live run above) rather than unit-tested.
- Coverage was measured once, is not gated in CI, and will drift as code changes —
  treat the numbers in `coverage_first_measurement.txt` as a 2026-07-19 snapshot.
