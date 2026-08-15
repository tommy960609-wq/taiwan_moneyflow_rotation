"""
Milestone 6: regression test documenting a real bug found (NOT fixed that milestone,
per governance rule "禁改已驗收模組既有行為" -- out of scope at the time).

Milestone 8: bug FIXED (small-fix batch, explicitly authorized this milestone). This
test now asserts the intended fail-closed behavior instead of the crash.

## What was found (M6)

Running `scripts/daily_orchestrator.py` live against real TWSE/TPEx endpoints on
2026-07-18 (see docs/acceptance_report.md for the full real-run transcript) surfaced an
UNHANDLED exception (`KeyError: 'market_type'`) instead of the intended fail-closed
`BLOCKED_MISSING_MARKET` status, in this exact sequence:

1. Today's OHLCV legacy bridge files (`data/raw/ohlcv/{twse,tpex}_prices_<date>.json`)
   don't exist (M4's DataFetcher correctly dropped both TWSE and TPEx OHLCV payloads via
   the DATE_MISMATCH guard, because at fetch time both official endpoints were still
   serving the prior trading day's data -- a genuine, expected data-availability gap,
   not a bug).
2. `run_pipeline`'s legacy fallback (`scripts/run_daily.py` ~line 247-255) then calls
   `loader.fetch_twse_ohlcv_all()` / `loader.fetch_tpex_ohlcv_all()` directly (a SEPARATE,
   older live-fetch path in `src/data_loader.py` that predates M4's `data_fetcher.py` and
   has none of its DATE_MISMATCH protection).
3. When both of those calls return falsy/empty, `df_twse`/`df_tpex` are built as bare
   `pd.DataFrame()` (line 257-258: `... if raw_twse_prices else pd.DataFrame()`), and
   `pd.concat([pd.DataFrame(), pd.DataFrame()], ignore_index=True)` produces a DataFrame
   with **zero columns** (confirmed directly: `pd.concat(...).columns.tolist() == []`).
4. Line 262 (`df_prices[df_prices["market_type"] == "TWSE"]`) then raised `KeyError:
   'market_type'` instead of reaching the intended empty-check on line 266
   (`if df_twse_chk.empty or df_tpex_chk.empty:` -> `BLOCKED_MISSING_MARKET`) -- because
   the KeyError happened two lines before that check was ever evaluated.

## The M8 fix

`scripts/run_daily.py` now checks `"market_type" not in df_prices.columns` before
indexing by it; when the column is absent (zero-column empty-concat case), both
`df_twse_chk`/`df_tpex_chk` are set to empty DataFrames directly, so execution falls
through to the pre-existing `BLOCKED_MISSING_MARKET` fail-closed branch instead of
raising. No other pipeline behavior changed.

## Why this was never caught before M6

Every prior milestone's real and mocked runs always had at least one legacy bridge file
present (or a mock that always returned non-empty data) by the time `run_pipeline` ran,
so this specific "both official AND the legacy live-fallback are simultaneously empty"
combination was never exercised end-to-end until M6's orchestrator was run against a
real trading day where the official endpoints hadn't published yet.

## Practical impact (pre-fix, M6-M7)

Low: the orchestrator built in M6 (`scripts/daily_orchestrator.py`) already caught this
via its own try/except around the pipeline_fn call (see `run_daily_orchestration`'s
"Step 3" handling) and reported it as `final_status: EXCEPTION, exit_code: 3`, with a
full traceback logged -- no data was corrupted, no report was falsely produced, and a
previous day's good report was left untouched. The *symptom* (crash) differed from what
a human reading the code would expect (a clean BLOCKED_MISSING_MARKET record), but the
*externally observable safety property* (never silently produce a bad report, never
overwrite good prior data) was not violated even before the fix. The M8 fix makes the
observable symptom match the intended design (clean blocked status, exit code 2 via the
orchestrator) rather than an opaque exception.
"""

import os
import sys
import tempfile
import shutil
from unittest.mock import patch

import pytest
import pandas as pd
from loguru import logger

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from scripts.run_daily import run_pipeline
from src.config_manager import ConfigManager


@patch("src.data_loader.DataLoader.fetch_twse_ohlcv_all")
@patch("src.data_loader.DataLoader.fetch_tpex_ohlcv_all")
def test_both_markets_empty_returns_blocked_missing_market(
    mock_tpex_price, mock_twse_price
):
    """
    Reproduces the real 2026-07-18 scenario hermetically: no legacy OHLCV bridge files
    on disk AND the legacy live-fallback loaders both return empty/falsy. Post-M8-fix,
    this now asserts the INTENDED behavior (a clean BLOCKED_MISSING_MARKET audit record)
    rather than the pre-fix unhandled KeyError.
    """
    mock_twse_price.return_value = []
    mock_tpex_price.return_value = []

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_data_dir = os.path.join(temp_dir, "data")
        temp_output_dir = os.path.join(temp_dir, "outputs")
        os.makedirs(os.path.join(temp_data_dir, "reference"), exist_ok=True)
        os.makedirs(os.path.join(temp_data_dir, "raw/ohlcv"), exist_ok=True)
        os.makedirs(temp_output_dir, exist_ok=True)

        real_mapping = "C:/Workspace_CN/taiwan_moneyflow_rotation/data/reference/stock_industry_mapping.xlsx"
        shutil.copy(real_mapping, os.path.join(temp_data_dir, "reference/stock_industry_mapping.xlsx"))

        def mock_config_get(self, key: str, default=None):
            if key == "system.data_dir":
                return temp_data_dir
            elif key == "system.output_dir":
                return temp_output_dir
            elif key == "system.run_mode":
                return "production"
            defaults = ConfigManager().get_defaults()
            val = defaults
            for k in key.split("."):
                if isinstance(val, dict) and k in val:
                    val = val[k]
                else:
                    return default
            return val

        try:
            with patch("src.config_manager.ConfigManager.get", mock_config_get):
                audit = run_pipeline("2026-07-18")
        finally:
            # run_pipeline's loguru file sink (_setup_run_logger) is removed on the
            # fail-closed return path itself, but remove() again defensively so
            # tempfile cleanup can proceed on Windows even if that ever changes.
            logger.remove()

        assert audit["status"] == "BLOCKED_MISSING_MARKET"
        assert audit["row_counts"]["prices_twse"] == 0
        assert audit["row_counts"]["prices_tpex"] == 0

        # Confirm no report artifacts were produced from the blocked run.
        expected_excel = os.path.join(temp_output_dir, "daily", "MoneyFlow_Rotation_2026-07-18.xlsx")
        assert not os.path.exists(expected_excel)


def test_root_cause_empty_concat_has_no_market_type_column():
    """
    Isolates the exact mechanism (not the full pipeline): concatenating two empty
    DataFrames produces zero columns, so any later `df["market_type"]` access raises
    KeyError rather than returning an empty Series. This is the one-line fact the
    fallback path at scripts/run_daily.py ~line 257-262 doesn't guard against.
    """
    df_twse = pd.DataFrame()
    df_tpex = pd.DataFrame()
    df_prices = pd.concat([df_twse, df_tpex], ignore_index=True)

    assert df_prices.empty
    assert df_prices.columns.tolist() == []
    with pytest.raises(KeyError):
        _ = df_prices["market_type"]
