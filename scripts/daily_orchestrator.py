"""
Milestone 6: one-click unattended daily orchestrator.

Chains three already-accepted, independently-tested entry points into one
fail-closed run, without modifying any of their internal behavior:

  1. `scripts.fetch_daily_data.run_single_day` (M4)      -- fetch today's official
     TWSE/TPEx OHLCV/institutional/margin/index snapshots into
     data/raw/<category>/<market>_<date>.json.
  2. `scripts.prepare_legacy_raw_snapshot.prepare_legacy_snapshot` (M5a)  -- bridge
     those M4-format filenames into the legacy filenames `run_pipeline` reads
     (pure copy, never overwrites, never mutates the M4-format source).
  3. `scripts.run_daily.run_pipeline` (M1-M5c)            -- feature engineering ->
     scoring -> signal detection -> Excel report + audit JSON.

Then appends today's graded sector-signal rows to `outputs/signals/signals_<date>.jsonl`
(same JSONL shape `scripts/run_history_pipeline.py` already produces per-day, reusing its
`_extract_signal_events` helper so the historical and daily-live paths never drift into
two different event schemas).

## Fail-closed contract (three failure scenarios this script's job is to keep separate)

- **Network failure at fetch (step 1)**: `run_single_day` itself never raises (M4's
  `DataFetcher` is fail-closed internally: a failed endpoint saves nothing and is logged
  in `fetcher.failure_log`); this script additionally treats "zero categories fetched
  successfully for today" as FETCH_FAILED and does NOT proceed to steps 2-3 -- it exits
  non-zero without touching any previously-good data on disk (no partial legacy bridge,
  no pipeline run, no report). A previous day's good report/CSVs are never overwritten by
  a bad day's failed fetch.
- **API returned but empty / schema-mismatched (step 1 partial)**: `run_single_day`
  reports each category/market's success individually; if EITHER market's OHLCV category
  failed to save (empty payload, HTTP non-200, or schema mismatch -- all already
  fail-closed inside `DataFetcher.fetch_and_save`), this script still attempts the legacy
  bridge and `run_pipeline`, because `run_pipeline` has its OWN fail-closed check for
  exactly this case (`BLOCKED_MISSING_MARKET` when a market's row count is 0) -- no need
  to duplicate that logic here, just don't swallow the resulting status.
- **DQ black-out (step 3, spec Ch.9 阻擋)**: `run_pipeline` already implements this
  (`status == "BLOCKED_LOW_DQ"` / `BLOCKED_MISSING_MARKET` / `BLOCKED_NO_MAPPING`): no
  Excel report is generated on any BLOCKED_* status, only the audit JSON error record.
  This orchestrator surfaces that status honestly in its own summary and log, and exits
  non-zero, but does NOT retry or attempt to force a report out of blocked data.

In every scenario, whatever was already successfully written to disk from a PRIOR day's
run is left untouched -- this script never deletes or overwrites anything outside of
today's `trade_date`-suffixed files, and today's own steps only write additively (each
step's own fail-closed logic decides whether to write anything at all).

## Exit codes
  0  = full success (fetch + bridge + run_pipeline status == SUCCESS)
  1  = fetch step failed (no categories fetched) -- did not proceed further
  2  = run_pipeline did not reach SUCCESS (any BLOCKED_* status, incl. DQ black-out)
  3  = unexpected exception in the orchestrator itself (caught, logged, never a bare
       traceback exit -- so a scheduled task's exit code is always meaningful)

Usage:
    python scripts/daily_orchestrator.py --date 2026-07-18 --prev-date 2026-07-17
    python scripts/daily_orchestrator.py                      # automatic backfill + today
    python scripts/daily_orchestrator.py --no-backfill         # legacy one-day behavior

Automatic mode probes official readiness before invoking the existing one-day atom.
Dates that are not ready are recorded as DEFERRED_NOT_READY and never create a
BLOCKED audit; successful dates remain idempotently skipped on later runs.
"""

import os
import sys
import json
import time
import argparse
import datetime
import traceback
from typing import Any, Callable, List, Optional

import requests
import urllib3

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from loguru import logger

from scripts.fetch_daily_data import run_single_day
from scripts.prepare_legacy_raw_snapshot import prepare_legacy_snapshot
from scripts.run_daily import run_pipeline
from scripts.run_history_pipeline import _extract_signal_events, _write_signals_jsonl
from src.data_fetcher import ENDPOINTS as DATA_ENDPOINTS

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# DEFAULT - 可調
# 10 calendar days, raised from 5 on 2026-08-03. Five days spans only three or
# four trading days, so one weekend plus a single failed run pushed a date out
# of the window before it could ever be retried -- exactly how 2026-07-28 and
# 2026-07-29 were lost. Ten days always covers two weekends.
DEFAULT_BACKFILL_LOOKBACK_DAYS = 10
TWSE_READINESS_TIMEOUT_SEC = 30
_AUTO_BACKFILL_STATUSES = {"SUCCESS", "HOLIDAY_SKIP"}


def _default_data_dir() -> str:
    return "C:/Workspace_CN/taiwan_moneyflow_rotation/data"


def _default_output_dir() -> str:
    return "C:/Workspace_CN/taiwan_moneyflow_rotation/outputs"


def _most_recent_weekday(d: datetime.date) -> datetime.date:
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d


def _auto_detect_prev_date(output_dir: str, trade_date: str) -> Optional[str]:
    """
    Scans outputs/logs/audit_<date>.json for the most recent SUCCESS date strictly
    before trade_date. Best-effort only: if nothing is found (first-ever run, or all
    prior runs blocked), returns None -- run_pipeline already handles prev_date=None by
    skipping day-over-day delta computation (documented, existing behavior), it is not
    an error condition for this script to leave prev_date unset.
    """
    logs_dir = os.path.join(output_dir, "logs")
    if not os.path.isdir(logs_dir):
        return None
    candidates = []
    for fname in os.listdir(logs_dir):
        if not (fname.startswith("audit_") and fname.endswith(".json")):
            continue
        date_str = fname[len("audit_"):-len(".json")]
        try:
            datetime.date.fromisoformat(date_str)
        except ValueError:
            continue
        if date_str >= trade_date:
            continue
        try:
            with open(os.path.join(logs_dir, fname), "r", encoding="utf-8") as f:
                audit = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if audit.get("status") == "SUCCESS":
            candidates.append(date_str)
    if not candidates:
        return None
    return max(candidates)


def _default_receipts_dir() -> str:
    return "C:/Workspace_CN/taiwan_moneyflow_rotation/loop/evidence/fetch_receipts"


def _normalise_date(value: Any) -> Optional[str]:
    """Return an ISO date for ISO/Gregorian-compact/ROC date values."""
    if isinstance(value, datetime.datetime):
        return value.date().isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if value is None:
        return None
    raw = str(value).strip()
    try:
        return datetime.date.fromisoformat(raw).isoformat()
    except ValueError:
        pass
    digits = raw.replace("/", "").replace("-", "")
    if not digits.isdigit():
        return None
    try:
        if len(digits) == 7:  # ROC YYYMMDD, e.g. 1150721.
            parsed = datetime.date(int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:]))
            return parsed.isoformat()
        if len(digits) == 8 and int(digits[:4]) > 1911:
            parsed = datetime.date(int(digits[:4]), int(digits[4:6]), int(digits[6:]))
            return parsed.isoformat()
    except ValueError:
        return None
    return None


def _extract_official_latest_date(payload: Any) -> Optional[str]:
    """Extract the newest self-reported date from either TWSE payload shape.

    MI_INDEX uses the Chinese ``日期`` field while STOCK_DAY_ALL uses ``Date``.
    This helper intentionally does not rely on ``src.data_fetcher.extract_payload_date``
    because that established parser does not know the MI_INDEX Chinese field.
    """
    found: List[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key in ("日期", "Date", "date", "交易日期"):
                parsed = _normalise_date(value.get(key))
                if parsed:
                    found.append(parsed)
            for key in ("payload", "data", "result", "rows"):
                if key in value:
                    visit(value[key])
        elif isinstance(value, list):
            for row in value:
                visit(row)

    visit(payload)
    return max(found) if found else None


def _default_readiness_request(url: str):
    return requests.get(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            )
        },
        verify=False,
        timeout=TWSE_READINESS_TIMEOUT_SEC,
    )


def _twse_official_latest_date(
    request_fn: Optional[Callable[[str], Any]] = None,
) -> Optional[str]:
    """Probe MI_INDEX and STOCK_DAY_ALL once each and return their latest date.

    A network, HTTP, JSON, or date-shape failure returns ``None``.  The caller must
    treat ``None`` as not-ready, so a transient endpoint problem can never cause old
    or empty data to be processed.
    """
    requester = request_fn or _default_readiness_request
    dates: List[str] = []
    endpoints = (
        ("MI_INDEX", DATA_ENDPOINTS.get("market_index", {}).get("twse")),
        ("STOCK_DAY_ALL", DATA_ENDPOINTS.get("ohlcv", {}).get("twse")),
    )
    probe_failed = False
    for label, url in endpoints:
        if not url:
            logger.warning(f"[daily_orchestrator] readiness {label}: endpoint unavailable")
            probe_failed = True
            continue
        try:
            response = requester(url)
            if getattr(response, "status_code", None) != 200:
                logger.warning(
                    f"[daily_orchestrator] readiness {label}: HTTP {getattr(response, 'status_code', None)}"
                )
                probe_failed = True
                continue
            payload = response.json()
            parsed = _extract_official_latest_date(payload)
            if parsed is None:
                logger.warning(f"[daily_orchestrator] readiness {label}: no parseable self-reported date")
                probe_failed = True
                continue
            dates.append(parsed)
            logger.info(f"[daily_orchestrator] readiness {label}: latest official date={parsed}")
        except Exception as exc:
            logger.warning(f"[daily_orchestrator] readiness {label}: probe failed ({exc})")
            probe_failed = True
    if probe_failed or len(dates) != len(endpoints):
        return None
    # Both official feeds must have reached the requested day.  Using the older
    # (minimum) self-reported date is the fail-closed choice when they disagree.
    return min(dates) if dates else None


def _status_for_date(output_dir: str, trade_date: str) -> Optional[str]:
    """Read either the new orchestrator summary or the pipeline audit status."""
    logs_dir = os.path.join(output_dir, "logs")
    statuses: List[str] = []
    for filename, key in (
        (f"orchestrator_summary_{trade_date}.json", "final_status"),
        (f"audit_{trade_date}.json", "status"),
    ):
        path = os.path.join(logs_dir, filename)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                value = json.load(handle).get(key)
            if isinstance(value, str):
                statuses.append(value)
        except (OSError, json.JSONDecodeError, TypeError):
            continue
    if "SUCCESS" in statuses:
        return "SUCCESS"
    if "HOLIDAY_SKIP" in statuses:
        return "HOLIDAY_SKIP"
    return statuses[0] if statuses else None


def _find_backfill_gaps(
    output_dir: str,
    lookback_days: int = DEFAULT_BACKFILL_LOOKBACK_DAYS,
    today: Optional[Any] = None,
) -> List[str]:
    """Find weekday dates in a calendar lookback with no successful result.

    The window includes ``today`` and is deliberately calendar-based: weekends are
    filtered, but no exchange holiday calendar is guessed.  Holiday classification
    happens only after the official-date readiness probe, where it can be recorded as
    ``HOLIDAY_SKIP`` instead of being retried forever.
    """
    if lookback_days < 1:
        raise ValueError("lookback_days must be >= 1")
    today_date = datetime.date.fromisoformat(today) if isinstance(today, str) else today
    if today_date is None:
        today_date = datetime.date.today()
    if isinstance(today_date, datetime.datetime):
        today_date = today_date.date()
    if not isinstance(today_date, datetime.date):
        raise TypeError("today must be a date or YYYY-MM-DD string")

    gaps: List[str] = []
    for offset in range(lookback_days - 1, -1, -1):
        candidate = today_date - datetime.timedelta(days=offset)
        if candidate.weekday() >= 5:
            continue
        date_str = candidate.isoformat()
        if _status_for_date(output_dir, date_str) in _AUTO_BACKFILL_STATUSES:
            continue
        gaps.append(date_str)
    return gaps


def _has_holiday_evidence(
    output_dir: str,
    trade_date: str,
    receipts_dir: Optional[str] = None,
    data_dir: Optional[str] = None,
) -> bool:
    """Detect an explicit empty official response already recorded for a date."""
    paths = [
        os.path.join(output_dir, "logs", f"audit_{trade_date}.json"),
        os.path.join(output_dir, "logs", f"orchestrator_summary_{trade_date}.json"),
        os.path.join(receipts_dir or _default_receipts_dir(), f"fetch_receipt_{trade_date}.json"),
    ]
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                record = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("is_holiday_response") is True or record.get("holiday") is True:
            return True
        results = record.get("results")
        if isinstance(results, dict):
            infos = [
                info
                for by_market in results.values()
                if isinstance(by_market, dict)
                for info in by_market.values()
                if isinstance(info, dict)
            ]
            if infos and all(info.get("row_count") == 0 for info in infos):
                return True

    raw_root = os.path.join(data_dir or _default_data_dir(), "raw")
    raw_files: List[str] = []
    if os.path.isdir(raw_root):
        for root, _, filenames in os.walk(raw_root):
            raw_files.extend(
                os.path.join(root, name)
                for name in filenames
                if name.endswith(f"_{trade_date}.json")
            )
    raw_payloads: List[Any] = []
    for path in raw_files:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                envelope = json.load(handle)
            # Older evidence samples are bare payload lists; M4 daily files use an
            # envelope.  Both are read-only evidence, never a reason to invent data.
            raw_payloads.append(envelope.get("payload") if isinstance(envelope, dict) else envelope)
        except (OSError, json.JSONDecodeError):
            continue
    if raw_payloads and all(
        payload == []
        or (isinstance(payload, dict) and isinstance(payload.get("data"), list) and not payload["data"])
        for payload in raw_payloads
    ):
        return True
    return False


def _classify_gap(
    trade_date: str,
    latest_official_date: Optional[str],
    holiday_evidence: bool = False,
) -> str:
    """Return READY, DEFERRED_NOT_READY, or HOLIDAY_SKIP for one gap."""
    if latest_official_date is None or latest_official_date < trade_date:
        return "DEFERRED_NOT_READY"
    if latest_official_date > trade_date and holiday_evidence:
        return "HOLIDAY_SKIP"
    return "READY"


def run_daily_orchestration(trade_date: Optional[str] = None,
                             prev_date: Optional[str] = None,
                             data_dir: Optional[str] = None,
                             output_dir: Optional[str] = None,
                             receipts_dir: Optional[str] = None,
                             fetch_fn=run_single_day,
                             bridge_fn=prepare_legacy_snapshot,
                             pipeline_fn=run_pipeline) -> dict:
    """
    Runs the full fetch -> bridge -> pipeline -> signals-jsonl chain for one trade_date.
    The three *_fn parameters exist purely so tests can inject mocks/stubs without
    monkeypatching module-level names -- production callers never need to pass them.

    Returns a summary dict (also written to
    outputs/logs/orchestrator_summary_<date>.json) with keys:
      trade_date, prev_date, started_at, elapsed_sec,
      fetch: {status, categories_fetched, categories_failed},
      bridge: {status, files_bridged},
      pipeline: {status, dq_score, output_files},
      signals: {status, event_count, signal_file},
      final_status: "SUCCESS" | "FETCH_FAILED" | "PIPELINE_BLOCKED" | "EXCEPTION",
      exit_code: int
    """
    data_dir = data_dir or _default_data_dir()
    output_dir = output_dir or _default_output_dir()
    run_start = time.time()

    if trade_date is None:
        trade_date = _most_recent_weekday(datetime.date.today()).isoformat()
    if prev_date is None:
        prev_date = _auto_detect_prev_date(output_dir, trade_date)

    summary = {
        "trade_date": trade_date, "prev_date": prev_date,
        "started_at": datetime.datetime.now().isoformat(),
        "elapsed_sec": None,
        "fetch": None, "bridge": None, "pipeline": None, "signals": None,
        "final_status": None, "exit_code": None,
    }

    logger.info(f"[daily_orchestrator] === Starting unattended run for {trade_date} "
                f"(prev_date={prev_date}) ===")

    # ---- Step 1: fetch ----
    # Past dates used to skip the fetch atom entirely, because every endpoint but
    # T86 served only its own latest snapshot and a backfill would have written
    # today's data under a historical filename. That safeguard also made a missed
    # day unrecoverable -- 2026-07-28..07-31 were lost exactly that way. Since
    # 2026-08-03 the fetcher has dated fallbacks (DATED_ENDPOINTS) and verifies
    # the returned day at both envelope and row level, so backfilling is safe;
    # run_single_day additionally passes skip_existing for past dates so an
    # already-verified historical file is never re-fetched or overwritten.
    try:
        fetch_summary = fetch_fn(trade_date, receipts_dir=receipts_dir)
    except Exception as e:
        logger.error(f"[daily_orchestrator] Unexpected exception during fetch step: {e}")
        summary["fetch"] = {"status": "EXCEPTION", "error": str(e)}
        summary["final_status"] = "EXCEPTION"
        summary["exit_code"] = 3
        summary["elapsed_sec"] = round(time.time() - run_start, 2)
        _write_summary(output_dir, trade_date, summary)
        return summary
    categories_fetched = []
    categories_failed = []
    for category, by_market in fetch_summary.get("results", {}).items():
        for market, info in by_market.items():
            if info is not None:
                categories_fetched.append(f"{category}/{market}")
            else:
                categories_failed.append(f"{category}/{market}")
    fetch_ok = len(categories_fetched) > 0
    summary["fetch"] = {
        "status": "OK" if fetch_ok else "FETCH_FAILED",
        "categories_fetched": categories_fetched,
        "categories_failed": categories_failed,
    }

    if not fetch_ok:
        logger.error(f"[daily_orchestrator] FETCH_FAILED: zero categories fetched for "
                      f"{trade_date} (network failure or all endpoints returned empty/"
                      f"non-200). Stopping before touching any existing good data.")
        summary["final_status"] = "FETCH_FAILED"
        summary["exit_code"] = 1
        summary["elapsed_sec"] = round(time.time() - run_start, 2)
        _write_summary(output_dir, trade_date, summary)
        return summary

    if categories_failed:
        logger.warning(f"[daily_orchestrator] Partial fetch: {len(categories_failed)} "
                        f"categories/markets failed today ({categories_failed}); "
                        f"proceeding to pipeline, which has its own fail-closed "
                        f"BLOCKED_MISSING_MARKET / low-DQ checks for exactly this case.")

    # ---- Step 2: bridge M4 filenames -> legacy filenames run_pipeline reads ----
    try:
        bridge_report = bridge_fn(data_dir, trade_date)
    except Exception as e:
        logger.error(f"[daily_orchestrator] Unexpected exception during legacy bridge step: {e}")
        summary["bridge"] = {"status": "EXCEPTION", "error": str(e)}
        summary["final_status"] = "EXCEPTION"
        summary["exit_code"] = 3
        summary["elapsed_sec"] = round(time.time() - run_start, 2)
        _write_summary(output_dir, trade_date, summary)
        return summary

    summary["bridge"] = {"status": "OK", "files_bridged": bridge_report}

    # ---- Step 3: run_pipeline (feature engineering -> scoring -> signals -> Excel) ----
    try:
        audit = pipeline_fn(trade_date, prev_date=prev_date)
    except Exception as e:
        logger.error(f"[daily_orchestrator] Unexpected exception during run_pipeline: {e}\n"
                      f"{traceback.format_exc()}")
        summary["pipeline"] = {"status": "EXCEPTION", "error": str(e)}
        summary["final_status"] = "EXCEPTION"
        summary["exit_code"] = 3
        summary["elapsed_sec"] = round(time.time() - run_start, 2)
        _write_summary(output_dir, trade_date, summary)
        return summary

    pipeline_status = audit.get("status", "UNKNOWN") if audit else "UNKNOWN"
    df_final_sectors = audit.pop("_df_final_sectors", None) if audit else None
    audit.pop("_df_scored_stocks", None) if audit else None

    summary["pipeline"] = {
        "status": pipeline_status,
        "dq_score": audit.get("row_counts", {}).get("dq_score") if audit else None,
        "output_files": audit.get("output_files", []) if audit else [],
    }

    if pipeline_status != "SUCCESS":
        logger.error(f"[daily_orchestrator] run_pipeline did not reach SUCCESS for "
                      f"{trade_date}: status={pipeline_status}. Per spec Ch.9, a "
                      f"BLOCKED_* status means no formal report was generated this run "
                      f"(only the error audit JSON) -- this is the correct fail-closed "
                      f"'黑燈' behavior, not a bug in this orchestrator.")
        summary["signals"] = {"status": "SKIPPED_NOT_SUCCESS", "event_count": 0}
        summary["final_status"] = "PIPELINE_BLOCKED"
        summary["exit_code"] = 2
        summary["elapsed_sec"] = round(time.time() - run_start, 2)
        _write_summary(output_dir, trade_date, summary)
        return summary

    # ---- Step 4: append today's signals to the daily signals JSONL ----
    try:
        events = _extract_signal_events(trade_date, df_final_sectors)
        signal_path = _write_signals_jsonl(output_dir, trade_date, events)
        summary["signals"] = {
            "status": "OK", "event_count": len(events), "signal_file": signal_path,
        }
    except Exception as e:
        # Signal JSONL is a secondary artifact -- the Excel report has already been
        # written successfully by this point. A failure here must not retroactively
        # turn a good report into a failed run; log and report it as a degraded
        # (not failed) outcome instead.
        logger.error(f"[daily_orchestrator] Signals JSONL append failed (non-fatal, "
                      f"Excel report already succeeded): {e}")
        summary["signals"] = {"status": "EXCEPTION", "error": str(e), "event_count": 0}

    summary["final_status"] = "SUCCESS"
    summary["exit_code"] = 0
    summary["elapsed_sec"] = round(time.time() - run_start, 2)
    logger.info(f"[daily_orchestrator] === Completed {trade_date}: SUCCESS in "
                f"{summary['elapsed_sec']}s ===")
    _write_summary(output_dir, trade_date, summary)
    return summary


def _write_summary(output_dir: str, trade_date: str, summary: dict) -> str:
    logs_dir = os.path.join(output_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    path = os.path.join(logs_dir, f"orchestrator_summary_{trade_date}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    summary["summary_path"] = path
    return path


def _write_batch_summary(output_dir: str, batch_date: str, summary: dict) -> str:
    logs_dir = os.path.join(output_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    path = os.path.join(logs_dir, f"orchestrator_batch_summary_{batch_date}.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2, default=str)
    summary["summary_path"] = path
    return path


def run_auto_backfill(
    today: Optional[Any] = None,
    lookback_days: int = DEFAULT_BACKFILL_LOOKBACK_DAYS,
    data_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
    receipts_dir: Optional[str] = None,
    readiness_fn: Callable[[], Optional[str]] = _twse_official_latest_date,
    orchestration_fn: Callable[..., dict] = run_daily_orchestration,
) -> dict:
    """Run ready missing weekdays oldest-first, while leaving not-ready days alone."""
    data_dir = data_dir or _default_data_dir()
    output_dir = output_dir or _default_output_dir()
    receipts_dir = receipts_dir or _default_receipts_dir()
    today_date = datetime.date.fromisoformat(today) if isinstance(today, str) else today
    if today_date is None:
        today_date = datetime.date.today()
    if isinstance(today_date, datetime.datetime):
        today_date = today_date.date()
    if not isinstance(today_date, datetime.date):
        raise TypeError("today must be a date or YYYY-MM-DD string")
    batch_date = today_date.isoformat()
    started_at = datetime.datetime.now().isoformat()
    gaps = _find_backfill_gaps(output_dir, lookback_days=lookback_days, today=today_date)
    records: List[dict] = []

    # A fully idempotent run does not hit official endpoints when there is nothing
    # missing.  This matters on weekends and after a successful late-data retry.
    latest_official_date = None
    if gaps:
        try:
            latest_official_date = readiness_fn()
        except Exception as exc:
            logger.warning(f"[daily_orchestrator] readiness function exception: {exc}")
            latest_official_date = None

    for trade_date in gaps:
        holiday_evidence = _has_holiday_evidence(
            output_dir, trade_date, receipts_dir=receipts_dir, data_dir=data_dir
        )
        decision = _classify_gap(trade_date, latest_official_date, holiday_evidence)
        if decision == "DEFERRED_NOT_READY":
            logger.info(
                f"[daily_orchestrator] {trade_date}: DEFERRED_NOT_READY "
                f"(official_latest={latest_official_date}); no fetch/pipeline attempted"
            )
            records.append({
                "trade_date": trade_date,
                "status": "DEFERRED_NOT_READY",
                "official_latest_date": latest_official_date,
                "holiday_evidence": holiday_evidence,
            })
            continue
        if decision == "HOLIDAY_SKIP":
            logger.info(
                f"[daily_orchestrator] {trade_date}: HOLIDAY_SKIP "
                f"(official_latest={latest_official_date})"
            )
            records.append({
                "trade_date": trade_date,
                "status": "HOLIDAY_SKIP",
                "official_latest_date": latest_official_date,
                "holiday_evidence": holiday_evidence,
            })
            continue

        try:
            day_summary = orchestration_fn(
                trade_date=trade_date,
                prev_date=None,
                data_dir=data_dir,
                output_dir=output_dir,
                receipts_dir=receipts_dir,
            )
            if not isinstance(day_summary, dict):
                raise RuntimeError("daily orchestration returned a non-dict summary")
            records.append({
                "trade_date": trade_date,
                "status": day_summary.get("final_status", "UNKNOWN"),
                "official_latest_date": latest_official_date,
                "summary_path": day_summary.get("summary_path"),
            })
        except Exception as exc:
            # One bad date must not prevent a newer ready date from being attempted.
            logger.error(f"[daily_orchestrator] {trade_date}: EXCEPTION; continuing: {exc}")
            records.append({
                "trade_date": trade_date,
                "status": "EXCEPTION",
                "official_latest_date": latest_official_date,
                "error": str(exc),
            })

    statuses = [record["status"] for record in records]
    if not gaps:
        final_status, exit_code = "NO_GAPS", 0
    elif "EXCEPTION" in statuses:
        final_status, exit_code = "EXCEPTION", 3
    elif "SUCCESS" in statuses:
        # The scheduled wrapper treats a successful ready day as a successful cycle;
        # the batch record still exposes any deferred/blocked siblings explicitly.
        final_status, exit_code = "SUCCESS", 0
    elif all(status in {"DEFERRED_NOT_READY", "HOLIDAY_SKIP"} for status in statuses):
        final_status, exit_code = "DEFERRED", 0
    elif "PIPELINE_BLOCKED" in statuses:
        final_status, exit_code = "PIPELINE_BLOCKED", 2
    elif "FETCH_FAILED" in statuses:
        final_status, exit_code = "FETCH_FAILED", 1
    else:
        final_status, exit_code = "EXCEPTION", 3

    summary = {
        "mode": "auto_backfill",
        "batch_date": batch_date,
        "lookback_days": lookback_days,
        "started_at": started_at,
        "finished_at": datetime.datetime.now().isoformat(),
        "gap_dates": gaps,
        "official_latest_date": latest_official_date,
        "days": records,
        "final_status": final_status,
        "exit_code": exit_code,
    }
    _write_batch_summary(output_dir, batch_date, summary)
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Taiwan Moneyflow Rotation one-click unattended daily orchestrator (M6)."
    )
    parser.add_argument("--date", type=str, default=None,
                         help="Trade date YYYY-MM-DD. Defaults to today (or most recent weekday).")
    parser.add_argument("--prev-date", type=str, default=None,
                         help="Previous trade date for day-over-day deltas. "
                              "Auto-detected from the most recent SUCCESS audit if omitted.")
    parser.add_argument("--data-dir", type=str, default=None)
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument("--receipts-dir", type=str,
                         default=_default_receipts_dir())
    parser.add_argument("--backfill-lookback-days", type=int,
                         default=DEFAULT_BACKFILL_LOOKBACK_DAYS,  # DEFAULT - 可調
                         help="Calendar-day lookback for automatic late-data backfill.")
    parser.add_argument("--no-backfill", action="store_true",
                         help="Run only the normal single-day orchestration (no readiness probe/backfill).")
    args = parser.parse_args()

    if args.date is not None or args.no_backfill:
        # Backward-compatible explicit-date/manual path.  --date never triggers the
        # multi-day readiness probe, even if --backfill-lookback-days is supplied.
        summary = run_daily_orchestration(
            trade_date=args.date, prev_date=args.prev_date,
            data_dir=args.data_dir, output_dir=args.output_dir,
            receipts_dir=args.receipts_dir,
        )
    else:
        summary = run_auto_backfill(
            lookback_days=args.backfill_lookback_days,
            data_dir=args.data_dir, output_dir=args.output_dir,
            receipts_dir=args.receipts_dir,
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    sys.exit(summary["exit_code"])


if __name__ == "__main__":
    main()
