"""
Forward-test ledger for the money-flow rotation stock-picking signals
(TASK-20260804-moneyflow-forward-test-ledger, status = **observe**).

Why this exists
---------------
The 72-day win-rate validation finished 2026-08-04 covers 2026-04-20..2026-08-03.
Every one of those days was already looked at: M9 threshold calibration used it,
M10's selective revision used it, and the validation run itself used it. Re-tuning a
threshold on that same window is curve fitting. The only honest next step is a
forward test: freeze the current code, and from 2026-08-04 onward accumulate signals
that have never been used to tune anything.

So this script is a **read-only derived instrument**. It reads artifacts that the
nightly pipeline already wrote to disk, recomputes forward returns with the *existing*
`src/backtester.py` functions, and appends the result to a ledger under
`loop/evidence/forward_test/`. It:

  - never fetches anything (no FinMind, no network of any kind -- the user's FinMind
    quota is exhausted and that is a standing constraint),
  - never triggers a pipeline stage,
  - never writes outside `--ledger-dir`,
  - is not wired into the nightly run or any scheduler. You run it by hand.

Deleting this file plus `loop/evidence/forward_test/` restores the system exactly:
zero behavioral change (loop contract §8a.3's rollback column).

Four correctness decisions worth reading before changing anything
----------------------------------------------------------------

1. **Cutoff (`oos_starts_from`, frozen at 2026-08-04).** No ledger row may be dated
   before it. Backfilling older events to make the sample look bigger would import the
   in-sample contamination this whole exercise exists to avoid.

   Note the one deliberate subtlety: `src/backtester.extract_events` needs the *prior*
   days' signal rows to decide whether an 2026-08-04 signal is a fresh ignition
   (`is_event_start=True`) or day 2 of an episode that began on 2026-08-03. So the full
   on-disk signal history is fed to the event extractor, and the **output events** are
   then filtered to `trade_date >= oos_starts_from`. Pre-cutoff rows are used only as
   run-length context -- information available at signal time, containing no outcome --
   and can never become a ledger row. Filtering *before* extraction would be the actual
   bug: it would relabel every still-running episode as a brand-new event on day one of
   the window and inflate the OOS event count.

2. **Fingerprint isolation.** Each row carries the SHA-256 fingerprint of the five
   files that determine what a signal *is* (`FINGERPRINT_FILES`). The ledger key
   includes that fingerprint, so events graded by different code are stored side by
   side and **never summed into one statistic**. Changing the grading logic does not
   continue the experiment; it starts a new one, with its own count toward the 30-event
   threshold. `status.md` states in plain language whether the current fingerprint still
   equals the registered one.

3. **PENDING is not zero.** A horizon whose bars do not exist yet has `null` return and
   `status=PENDING`; it is excluded from the win-rate denominator rather than counted as
   a flat trade. This is `src/backtester.py`'s own semantics, reused, not reinvented.

4. **No re-implemented return or cost math.** Entry price, forward returns, limit-up
   lockout and trading cost all come from `src/backtester.py` via
   `Backtester.run_event_study` (which internally uses `extract_events`,
   `compute_entry_price`, `compute_stock_forward_returns`, `compute_market_forward_returns`
   and `apply_trading_cost`). Two return conventions in one repo is a defect, not a
   convenience. On 2026-08-13 the market-return origin was corrected to the prior
   trading day's close; the new registration supersedes the 2026-08-04 registration
   because the code fingerprint changed, while its cutoff and success rule stay fixed.

Merge policy (task spec §4.7 -- the "rewrite whole file, preserve every existing key,
update only mutable fields" option was chosen over "append a superseding version row")
------------------------------------------------------------------------------------
An event's row is keyed by
`(trade_date, sector_name, sector_type, signal_type, code_fingerprint)`. Re-running
updates that row's `status`, returns and `last_updated_at` in place -- PENDING becoming
TRADABLE as the T+10 bar arrives is normal maturation of one event, not a second event.
Existing keys are never dropped, and `first_seen_at` is immutable.

The version-append alternative was rejected because it makes the file unreadable without
bespoke logic: every consumer would have to reduce version chains before counting, and
any consumer that forgot would silently double-count the same event once per re-run --
exactly the kind of quiet statistical corruption this ledger is supposed to detect.
Supersession history is not lost in any way that matters here: the ledger is an evidence
artifact under `loop/evidence/`, and the previous file content is recoverable from the
`.prev` sidecar written on every merge.

Data sources (and why not the obvious one)
------------------------------------------
OHLCV comes from `data/processed/stock_features_<date>.csv`, not from
`data/raw/ohlcv/finmind_*.json`: the FinMind cache stops at 2026-07-17 and the quota is
exhausted, so it cannot cover any OOS date. The processed CSVs come from the official
TWSE/TPEx feed and carry the same open/high/low/close/volume columns that
`scripts/run_backtest.load_finmind_ohlcv_history` produces. Same substitution, same
reason, as the already-validated
`Quant-Agent/_workbench/tools/finalize_moneyflow_winrate_20260804.py`.

TAIEX comes from `data/raw/market_index/twse_<date>.json` (MI_INDEX), merged over the
FinMind index cache for the older dates. Those payloads contain BOTH 發行量加權股價指數
(~43,000) and 發行量加權股價報酬指數 (~100,000, a total-return index ~2.3x higher).
Picking the wrong row corrupts every excess return silently, so three guards are applied
together: the name must contain 發行 AND 加權 AND NOT 報酬; thousands separators are
stripped before float conversion; and the row's own 日期 (ROC calendar) must match the
date in the filename.

Usage
-----
    python scripts/run_forward_test_ledger.py
    python scripts/run_forward_test_ledger.py --ledger-dir <tmp>   # tests point at tmp

The path flags exist only so the unit tests can run against a temporary tree. They are
paths, not feature switches: there is no flag that changes what the ledger computes.
"""

from __future__ import annotations

import argparse
import datetime
import glob
import hashlib
import json
import os
import sys
from typing import Dict, List, Optional, Tuple

import pandas as pd
from loguru import logger

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from src.backtester import (  # noqa: E402
    Backtester,
    EVENT_STATUS_PENDING,
    HORIZONS_DAYS,
    compute_entry_price,
    index_ohlcv_by_stock,
    resolve_sector_member_stock_ids,
)

PROJECT_ROOT_DEFAULT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# The five files that define what a signal IS. Any change to any of them starts a new
# experiment (see module docstring, decision 2).
FINGERPRINT_FILES: Tuple[str, ...] = (
    "src/signal_detector.py",
    "src/stock_scoring.py",
    "src/threshold_calibration.py",
    "src/backtester.py",
    "config/default.yaml",
)

REGISTRATION_FILENAME = "registration_20260813.json"
LEDGER_FILENAME = "ledger.jsonl"
STATUS_FILENAME = "status.md"

# Tiers tracked separately. Never pooled: a C-grade single-stock event and an A-grade
# fresh ignition are different claims and get separate 30-event budgets.
TRACKED_TIERS: Tuple[str, ...] = ("A級新起漲", "B級早期點火", "C級個股事件", "續漲訊號")

PRIMARY_HORIZON_DAYS = 10
MIN_REALIZED_EVENTS_PER_TIER = 30

LEDGER_KEY_FIELDS = ("trade_date", "sector_name", "sector_type", "signal_type",
                     "code_fingerprint")
# Set once when the row is first written; a re-run must never rewrite these.
IMMUTABLE_FIELDS = LEDGER_KEY_FIELDS + ("first_seen_at",)


# ---------------------------------------------------------------------------
# fingerprint
# ---------------------------------------------------------------------------

def sha256_file(path: str) -> Optional[str]:
    """SHA-256 of a file, or None if it cannot be read (fail-closed: a missing
    fingerprint input is reported as null, never silently treated as unchanged)."""
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError as e:
        logger.warning(f"sha256_file: cannot read {path}: {e}")
        return None


def compute_code_fingerprint(project_root: str) -> Tuple[Dict[str, Optional[str]], str]:
    """Returns (per-file sha256 map, short combined fingerprint).

    The combined value is the SHA-256 of the canonical JSON of the per-file map,
    truncated to 16 hex chars -- short enough to read in status.md, wide enough that a
    collision is not a practical concern for a handful of code revisions."""
    per_file = {rel: sha256_file(os.path.join(project_root, rel)) for rel in FINGERPRINT_FILES}
    canonical = json.dumps(per_file, sort_keys=True, ensure_ascii=False)
    combined = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return per_file, combined


def registered_fingerprint(registration: dict) -> str:
    """Combined fingerprint implied by the registration file's recorded per-file map,
    computed with the exact same rule as `compute_code_fingerprint` so the two are
    comparable."""
    per_file = registration.get("code_fingerprint") or {}
    ordered = {rel: per_file.get(rel) for rel in FINGERPRINT_FILES}
    canonical = json.dumps(ordered, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# loaders (all read-only, all fail-closed)
# ---------------------------------------------------------------------------

def load_registration(ledger_dir: str) -> Optional[dict]:
    path = os.path.join(ledger_dir, REGISTRATION_FILENAME)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        logger.error(f"load_registration: cannot read {path}: {e}")
        return None


def load_all_signals(signals_dir: str) -> pd.DataFrame:
    """Every outputs/signals/signals_<date>.jsonl stacked into one frame.

    The FULL history is returned on purpose -- the cutoff is applied to extracted
    events, not to the extractor's input (module docstring, decision 1). `.bak*` files
    are skipped: they are pre-rerun snapshots, not live signal days."""
    frames: List[pd.DataFrame] = []
    for path in sorted(glob.glob(os.path.join(signals_dir, "signals_*.jsonl"))):
        if not path.endswith(".jsonl"):
            continue
        rows = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rows.append(json.loads(line))
        except (OSError, ValueError) as e:
            logger.warning(f"load_all_signals: skipping unreadable {path}: {e}")
            continue
        if rows:
            frames.append(pd.DataFrame(rows))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def load_ohlcv_panel(processed_dir: str) -> pd.DataFrame:
    """Stacked OHLCV from data/processed/stock_features_<date>.csv.

    Same substitution (and same reason) as the accepted
    finalize_moneyflow_winrate_20260804.py: the FinMind OHLCV cache stops at 2026-07-17
    and cannot cover any OOS date."""
    frames: List[pd.DataFrame] = []
    for path in sorted(glob.glob(os.path.join(processed_dir, "stock_features_*.csv"))):
        if "_bak_" in os.path.basename(path):
            continue
        try:
            df = pd.read_csv(
                path, dtype={"stock_id": str},
                usecols=["trade_date", "stock_id", "open", "high", "low", "close", "volume"],
            )
        except (OSError, ValueError) as e:
            logger.warning(f"load_ohlcv_panel: skipping unreadable {path}: {e}")
            continue
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["stock_id", "trade_date", "open", "high", "low",
                                      "close", "volume"])
    return pd.concat(frames, ignore_index=True)


def load_stock_scored_by_date(processed_dir: str) -> Dict[str, pd.DataFrame]:
    """{trade_date: stock_scored frame} -- sector membership as of that very day, which
    is what `Backtester.run_event_study` wants (never a later day's mapping)."""
    out: Dict[str, pd.DataFrame] = {}
    for path in sorted(glob.glob(os.path.join(processed_dir, "stock_scored_*.csv"))):
        fname = os.path.basename(path)
        if "_bak_" in fname:
            continue
        date_str = fname.replace("stock_scored_", "").replace(".csv", "")
        try:
            out[date_str] = pd.read_csv(path, dtype={"stock_id": str})
        except (OSError, ValueError) as e:
            logger.warning(f"load_stock_scored_by_date: skipping unreadable {path}: {e}")
    return out


def roc_date_to_iso(raw) -> Optional[str]:
    """TWSE MI_INDEX reports its own date in the ROC calendar ('1150803' = 2026-08-03,
    also seen as '115/08/03'). Returns ISO, or None if it cannot be parsed -- a date
    that cannot be parsed is not treated as a match."""
    if raw is None:
        return None
    s = str(raw).strip().replace("/", "").replace("-", "")
    if len(s) == 8 and s.isdigit():  # already Gregorian YYYYMMDD
        try:
            return datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8])).isoformat()
        except ValueError:
            return None
    if len(s) == 7 and s.isdigit():
        try:
            return datetime.date(int(s[:3]) + 1911, int(s[3:5]), int(s[5:7])).isoformat()
        except ValueError:
            return None
    return None


def taiex_close_from_index_file(path: str, expected_date: Optional[str]) -> Optional[float]:
    """The TAIEX close out of one MI_INDEX snapshot, with all three guards.

    MI_INDEX carries 發行量加權股價指數 (the price index, ~43,000) AND
    發行量加權股價報酬指數 (the total-return index, ~100,000). They differ by ~2.3x and
    the wrong pick silently wrecks every relative return, so:
      guard 1 -- name must contain 發行 and 加權 and must NOT contain 報酬;
      guard 2 -- strip thousands separators before float() (values arrive as '43,386.41');
      guard 3 -- the row's self-reported 日期 must match `expected_date`.
    Returns None on any failure. Never raises."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            env = json.load(f)
    except (OSError, ValueError) as e:
        logger.warning(f"taiex_close_from_index_file: unreadable {path}: {e}")
        return None
    rows = env.get("payload", env) if isinstance(env, dict) else env
    if not isinstance(rows, list):
        logger.warning(f"taiex_close_from_index_file: no payload list in {path}")
        return None
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = str(r.get("指數", ""))
        # guard 1
        if not ("發行" in name and "加權" in name and "報酬" not in name):
            continue
        # guard 3
        reported = roc_date_to_iso(r.get("日期"))
        if expected_date is not None and reported != expected_date:
            logger.warning(f"taiex_close_from_index_file: {os.path.basename(path)} row "
                           f"self-reports {reported!r} but filename says {expected_date!r} "
                           f"-- rejected (fail-closed)")
            return None
        # guard 2
        try:
            return float(str(r.get("收盤指數", "")).replace(",", "").strip())
        except (TypeError, ValueError):
            logger.warning(f"taiex_close_from_index_file: unparseable 收盤指數 in {path}")
            return None
    logger.warning(f"taiex_close_from_index_file: no 發行量加權股價指數 row in {path}")
    return None


def load_taiex(market_index_dir: str) -> pd.DataFrame:
    """TAIEX daily closes: the FinMind index cache (older dates) overlaid by the official
    MI_INDEX snapshots (which are the only source that reaches the OOS dates)."""
    closes: Dict[str, float] = {}
    finmind_path = os.path.join(market_index_dir, "finmind_index_twse.json")
    if os.path.exists(finmind_path):
        try:
            with open(finmind_path, "r", encoding="utf-8") as f:
                env = json.load(f)
            for r in env.get("payload", []) or []:
                if r.get("close") is not None:
                    closes[r["date"]] = float(r["close"])
        except (OSError, ValueError, TypeError) as e:
            logger.warning(f"load_taiex: unreadable FinMind index cache: {e}")

    for path in sorted(glob.glob(os.path.join(market_index_dir, "twse_*.json"))):
        base = os.path.basename(path)
        if not base.endswith(".json"):
            continue
        date_str = base[:-len(".json")].replace("twse_official_", "").replace("twse_", "")
        try:
            datetime.date.fromisoformat(date_str)
        except ValueError:
            continue
        value = taiex_close_from_index_file(path, expected_date=date_str)
        if value is not None:
            closes[date_str] = value

    if not closes:
        logger.error("load_taiex: no TAIEX closes found -- every market/excess return "
                     "will be null (fail-closed, not fabricated)")
        return pd.DataFrame(columns=["trade_date", "close"])
    return pd.DataFrame({"trade_date": list(closes.keys()), "close": list(closes.values())})


# ---------------------------------------------------------------------------
# ledger construction
# ---------------------------------------------------------------------------

def _median_entry_price(sector_name: str, sector_type: str, signal_date: str,
                         df_stock_scored: pd.DataFrame, ohlcv_idx) -> Optional[float]:
    """Descriptive-only: the median T+1-open entry price across the event's tradable
    member stocks, recorded because the loop contract's evidence column asks for
    '進場價與日期'. A sector-level event has no single scalar entry price by
    construction (its return is the cross-sectional median of member returns), so this
    is disclosure, not an input to any return calculation -- it reuses
    src.backtester.compute_entry_price rather than re-deriving anything."""
    member_ids = resolve_sector_member_stock_ids(sector_name, sector_type, df_stock_scored)
    prices = []
    for sid in member_ids:
        info = compute_entry_price(sid, signal_date, ohlcv_idx, "exclude")
        if info.get("entry_price") is not None:
            prices.append(float(info["entry_price"]))
    if not prices:
        return None
    return float(pd.Series(prices).median())


def _to_jsonable(value):
    """pandas/NumPy scalars -> plain Python; NaN/NaT -> None (never 0.0)."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except (AttributeError, ValueError):
            pass
    return value


def build_ledger_rows(df_signals_all: pd.DataFrame,
                      df_stock_scored_by_date: Dict[str, pd.DataFrame],
                      df_ohlcv: pd.DataFrame,
                      df_taiex: pd.DataFrame,
                      oos_starts_from: str,
                      code_fingerprint: str,
                      now_iso: str) -> List[dict]:
    """Runs the accepted event study over the full signal history, then keeps ONLY
    events dated on/after `oos_starts_from`.

    The order matters and is the point of the whole task: extraction sees the earlier
    days so episode boundaries are right; the ledger sees only OOS events so no
    in-sample outcome ever enters the statistics."""
    if df_signals_all.empty:
        return []

    backtester = Backtester()
    events = backtester.run_event_study(
        df_signals_all_days=df_signals_all,
        df_stock_scored_by_date=df_stock_scored_by_date,
        df_ohlcv_history=df_ohlcv,
        df_taiex=df_taiex,
    )
    if events.empty:
        return []

    # THE CUTOFF. Nothing dated before oos_starts_from may become a ledger row.
    events = events[events["trade_date"].astype(str) >= oos_starts_from].copy()
    if events.empty:
        return []

    ohlcv_idx = index_ohlcv_by_stock(df_ohlcv) if isinstance(df_ohlcv, pd.DataFrame) else df_ohlcv

    rows: List[dict] = []
    for _, ev in events.iterrows():
        trade_date = str(ev["trade_date"])
        sector_name = ev["sector_name"]
        sector_type = ev.get("sector_type", "primary")
        df_scored = df_stock_scored_by_date.get(trade_date, pd.DataFrame())
        row = {
            "trade_date": trade_date,
            "sector_name": sector_name,
            "sector_type": sector_type,
            "signal_type": ev.get("signal_type"),
            "event_family": _to_jsonable(ev.get("event_family")),
            "entry_date": _to_jsonable(ev.get("entry_date")),
            "entry_price_median": _median_entry_price(sector_name, sector_type, trade_date,
                                                       df_scored, ohlcv_idx),
            "member_stock_count": _to_jsonable(ev.get("member_stock_count")),
            "tradable_member_count": _to_jsonable(ev.get("tradable_member_count")),
            "status": _to_jsonable(ev.get("status")),
            "outcome_label": _to_jsonable(ev.get("outcome_label")),
            "code_fingerprint": code_fingerprint,
            "first_seen_at": now_iso,
            "last_updated_at": now_iso,
        }
        for k in HORIZONS_DAYS:
            # None, never 0.0, for a horizon whose bars have not happened yet.
            row[f"net_return_{k}d"] = _to_jsonable(ev.get(f"net_return_{k}d"))
            row[f"market_return_{k}d"] = _to_jsonable(ev.get(f"market_return_{k}d"))
            row[f"excess_return_net_{k}d"] = _to_jsonable(ev.get(f"excess_return_net_{k}d"))
        rows.append(row)
    return rows


def read_ledger(ledger_path: str) -> List[dict]:
    rows: List[dict] = []
    if not os.path.exists(ledger_path):
        return rows
    try:
        with open(ledger_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
    except (OSError, ValueError) as e:
        logger.error(f"read_ledger: {ledger_path} unreadable ({e}) -- refusing to "
                     f"overwrite a ledger we cannot parse")
        raise
    return rows


def ledger_key(row: dict) -> tuple:
    return tuple(str(row.get(f)) for f in LEDGER_KEY_FIELDS)


def merge_ledger(existing: List[dict], incoming: List[dict]) -> List[dict]:
    """Whole-file rewrite that preserves every existing key and updates only the mutable
    fields of a re-observed event (see module docstring, "Merge policy").

    A key present in `existing` but absent from `incoming` is kept untouched -- e.g. a
    signal day whose source jsonl was later archived must not silently vanish from the
    forward-test record."""
    merged: Dict[tuple, dict] = {}
    order: List[tuple] = []
    for row in existing:
        key = ledger_key(row)
        if key not in merged:
            order.append(key)
        merged[key] = dict(row)
    for row in incoming:
        key = ledger_key(row)
        if key not in merged:
            merged[key] = dict(row)
            order.append(key)
            continue
        target = merged[key]
        for field, value in row.items():
            if field in IMMUTABLE_FIELDS:
                continue
            target[field] = value
    return [merged[k] for k in order]


def write_ledger(ledger_path: str, rows: List[dict]) -> None:
    """Rewrites the ledger, keeping the previous content as `<name>.prev` so the merge
    is auditable and reversible even though this project is not under version control."""
    os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
    if os.path.exists(ledger_path):
        with open(ledger_path, "r", encoding="utf-8") as src:
            previous = src.read()
        with open(ledger_path + ".prev", "w", encoding="utf-8") as dst:
            dst.write(previous)
    rows_sorted = sorted(rows, key=lambda r: (str(r.get("trade_date")),
                                              str(r.get("sector_type")),
                                              str(r.get("sector_name")),
                                              str(r.get("signal_type")),
                                              str(r.get("code_fingerprint"))))
    with open(ledger_path, "w", encoding="utf-8") as f:
        for row in rows_sorted:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------

def summarize_by_fingerprint(rows: List[dict],
                             horizon: int = PRIMARY_HORIZON_DAYS) -> Dict[str, Dict[str, dict]]:
    """{code_fingerprint: {signal_type: stats}}.

    Grouping by fingerprint FIRST is the whole point: events graded by different code
    are different experiments and must never land in the same median or win rate. A
    PENDING event contributes to `n_events` but not to `n_realized`, so it can never be
    counted as a flat (0%) trade."""
    col = f"excess_return_net_{horizon}d"
    out: Dict[str, Dict[str, dict]] = {}
    for row in rows:
        fp = str(row.get("code_fingerprint"))
        tier = row.get("signal_type")
        bucket = out.setdefault(fp, {})
        stats = bucket.setdefault(tier, {"signal_type": tier, "n_events": 0,
                                          "_realized": []})
        stats["n_events"] += 1
        value = row.get(col)
        if value is not None and str(row.get("status")) != EVENT_STATUS_PENDING:
            stats["_realized"].append(float(value))
    for bucket in out.values():
        for stats in bucket.values():
            realized = stats.pop("_realized")
            n = len(realized)
            series = pd.Series(realized, dtype=float)
            stats["n_realized"] = n
            stats["median_excess_pct"] = float(series.median() * 100) if n else None
            stats["win_rate"] = float((series > 0).mean()) if n else None
            stats["sample_sufficient"] = n >= MIN_REALIZED_EVENTS_PER_TIER
    return out


# ---------------------------------------------------------------------------
# status.md
# ---------------------------------------------------------------------------

def _fmt_pct(value: Optional[float]) -> str:
    return "—" if value is None else f"{value:+.2f}%"


def _fmt_rate(value: Optional[float]) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def render_status_md(registration: dict, rows: List[dict], current_fp: str,
                     registered_fp: str, per_file_fp: Dict[str, Optional[str]],
                     now_iso: str) -> str:
    """Plain-language readout. Written for the decision maker, not for an engineer:
    the first line answers "can I act on this yet?" and the expected answer for a long
    time is no."""
    oos_from = registration.get("oos_starts_from", "2026-08-04")
    baseline = registration.get("in_sample_baseline", {}) or {}
    fp_matches = (current_fp == registered_fp)

    summary = summarize_by_fingerprint(rows)
    registered_rows = [r for r in rows if str(r.get("code_fingerprint")) == registered_fp]
    other_fps = sorted({str(r.get("code_fingerprint")) for r in rows} - {registered_fp})
    oos_days = sorted({str(r.get("trade_date")) for r in registered_rows})
    reg_summary = summary.get(registered_fp, {})

    ready = [t for t in TRACKED_TIERS
             if reg_summary.get(t, {}).get("n_realized", 0) >= MIN_REALIZED_EVENTS_PER_TIER]

    lines: List[str] = []
    lines.append("# 選股 forward-test 帳本 — 目前讀數")
    lines.append("")
    lines.append(f"> 自動產生於 {now_iso}。本檔每次執行重寫,不要手改。")
    lines.append("")
    if registration.get("supersedes"):
        lines.append("本實驗已於 2026-08-13 因修正大盤基準而重新註冊，起算日與成功判準未變。")
        lines.append("")
    lines.append("## 一句話結論")
    lines.append("")
    if not ready:
        lines.append(f"**還不能下結論。** 從 {oos_from} 開始重新計算的全新樣本目前累積 "
                     f"{len(registered_rows)} 筆、涵蓋 {len(oos_days)} 個交易日,離「每個等級至少 "
                     f"{MIN_REALIZED_EVENTS_PER_TIER} 筆已走完 10 天的樣本」還很遠。"
                     f"下面的數字只能看,**不可以拿來調參數或下單**。")
    else:
        lines.append(f"**下列等級的樣本已達門檻,可以進入討論(仍需你拍板才會改任何行為):**"
                     f" {', '.join(ready)}。")
    lines.append("")

    lines.append("## 程式有沒有被改過(改了就等於換一個實驗)")
    lines.append("")
    if fp_matches:
        lines.append(f"目前程式指紋 `{current_fp}` **等於**註冊時的指紋,實驗連續有效。")
    else:
        lines.append(f"### ⚠️ 實驗已重置")
        lines.append("")
        lines.append(f"目前程式指紋 `{current_fp}` **不等於**註冊指紋 `{registered_fp}`。"
                     f"選股邏輯被改過,新舊樣本**嚴禁合併計算**;新指紋的樣本要從 0 重新累積 "
                     f"{MIN_REALIZED_EVENTS_PER_TIER} 筆。")
    lines.append("")
    lines.append("| 檔案 | 目前 SHA-256 | 與註冊值相同? |")
    lines.append("|---|---|---|")
    registered_files = registration.get("code_fingerprint", {}) or {}
    for rel in FINGERPRINT_FILES:
        now_v = per_file_fp.get(rel)
        reg_v = registered_files.get(rel)
        same = "是" if (now_v is not None and now_v == reg_v) else "**否**"
        lines.append(f"| `{rel}` | `{(now_v or 'MISSING')[:16]}…` | {same} |")
    lines.append("")

    lines.append("## 各等級累積進度(只算註冊指紋的樣本)")
    lines.append("")
    lines.append("| 訊號等級 | 累積事件 | 已走完 10 天 | 還差幾筆到 30 | 10 日超額中位數 | 勝率 |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for tier in TRACKED_TIERS:
        stats = reg_summary.get(tier, {})
        n_events = stats.get("n_events", 0)
        n_realized = stats.get("n_realized", 0)
        gap = max(0, MIN_REALIZED_EVENTS_PER_TIER - n_realized)
        lines.append(f"| {tier} | {n_events} | {n_realized} | {gap} | "
                     f"{_fmt_pct(stats.get('median_excess_pct'))} | "
                     f"{_fmt_rate(stats.get('win_rate'))} |")
    lines.append("")
    lines.append(f"已累積 OOS 交易日:**{len(oos_days)}** 天"
                 + (f"({oos_days[0]} ~ {oos_days[-1]})" if oos_days else "(尚無)"))
    lines.append("")
    lines.append("> 「已走完 10 天」= 進場後第 10 個交易日的價格已經出現、報酬算得出來。"
                 "沒走完的用 `null` 記著,**不會**被當成 0% 塞進勝率分母。")
    lines.append("")

    lines.append("## 跟舊資料(已被用來調過參數的那批)比")
    lines.append("")
    lines.append("| 訊號等級 | 舊資料筆數 | 舊資料 10 日超額中位數 | 舊資料勝率 | 新樣本中位數 | 新樣本勝率 |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for tier in TRACKED_TIERS:
        base = baseline.get(tier, {}) or {}
        stats = reg_summary.get(tier, {})
        base_median = base.get("median_excess_pct")
        base_win = base.get("win_rate")
        lines.append(
            f"| {tier} | {base.get('n_realized', '—')} | "
            f"{_fmt_pct(base_median)} | {_fmt_rate(base_win)} | "
            f"{_fmt_pct(stats.get('median_excess_pct'))} | "
            f"{_fmt_rate(stats.get('win_rate'))} |"
        )
    lines.append("")
    mom = baseline.get("momentum_baseline_median_excess_pct")
    lines.append(f"舊資料的「什麼都不挑、單純追動能」基準 10 日超額中位數:{_fmt_pct(mom)}。"
                 "新樣本要能贏過這條線才算有選股能力。")
    lines.append("")

    if other_fps:
        lines.append("## 其他指紋的樣本(分開列,絕不與上表合併)")
        lines.append("")
        lines.append("| 指紋 | 事件數 | 已實現 |")
        lines.append("|---|---:|---:|")
        for fp in other_fps:
            bucket = summary.get(fp, {})
            n_events = sum(s.get("n_events", 0) for s in bucket.values())
            n_realized = sum(s.get("n_realized", 0) for s in bucket.values())
            lines.append(f"| `{fp}` | {n_events} | {n_realized} |")
        lines.append("")

    lines.append("## 怎麼判定成功(這條規則在看到任何新資料之前就寫死了,不得事後修改)")
    lines.append("")
    rule = (registration.get("decision_rule", {}) or {}).get("success_criteria", "—")
    lines.append(f"{rule}")
    lines.append("")
    lines.append("三個條件同時成立才可以討論升級:①該等級已實現樣本 ≥30 ②T+10 已成熟 "
                 "③使用者拍板。缺一不動。")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def run(project_root: str = PROJECT_ROOT_DEFAULT,
        data_dir: Optional[str] = None,
        output_dir: Optional[str] = None,
        ledger_dir: Optional[str] = None) -> Optional[dict]:
    """Read artifacts, refresh the ledger, rewrite status.md. Returns a small summary
    dict, or None if the run could not proceed (fail-closed -- callers must not treat
    None as "nothing changed, all good")."""
    data_dir = data_dir or os.path.join(project_root, "data")
    output_dir = output_dir or os.path.join(project_root, "outputs")
    ledger_dir = ledger_dir or os.path.join(project_root, "loop", "evidence", "forward_test")

    registration = load_registration(ledger_dir)
    if registration is None:
        logger.error("run: no registration file -- refusing to build a ledger without a "
                     "pre-registered cutoff and decision rule")
        return None
    oos_starts_from = registration.get("oos_starts_from")
    if not oos_starts_from:
        logger.error("run: registration has no oos_starts_from -- refusing to run")
        return None

    per_file_fp, current_fp = compute_code_fingerprint(project_root)
    registered_fp = registered_fingerprint(registration)
    if current_fp != registered_fp:
        logger.warning(f"run: code fingerprint {current_fp} != registered {registered_fp} "
                       f"-- new events are recorded under the NEW fingerprint and must "
                       f"never be pooled with the registered-fingerprint sample")

    processed_dir = os.path.join(data_dir, "processed")
    signals_dir = os.path.join(output_dir, "signals")
    market_index_dir = os.path.join(data_dir, "raw", "market_index")

    df_signals = load_all_signals(signals_dir)
    df_ohlcv = load_ohlcv_panel(processed_dir)
    scored_by_date = load_stock_scored_by_date(processed_dir)
    df_taiex = load_taiex(market_index_dir)

    now_iso = datetime.datetime.now().replace(microsecond=0).isoformat()
    incoming = build_ledger_rows(df_signals, scored_by_date, df_ohlcv, df_taiex,
                                 oos_starts_from, current_fp, now_iso)

    ledger_path = os.path.join(ledger_dir, LEDGER_FILENAME)
    existing = read_ledger(ledger_path)
    merged = merge_ledger(existing, incoming)

    # Belt and braces: the cutoff is enforced in build_ledger_rows, and re-asserted here
    # so a hand-edited or externally-produced ledger cannot smuggle in-sample rows past
    # it either.
    violations = [r for r in merged if str(r.get("trade_date")) < oos_starts_from]
    if violations:
        logger.error(f"run: {len(violations)} ledger rows are dated before "
                     f"{oos_starts_from} -- dropping them (in-sample contamination)")
        merged = [r for r in merged if str(r.get("trade_date")) >= oos_starts_from]

    write_ledger(ledger_path, merged)

    status_md = render_status_md(registration, merged, current_fp, registered_fp,
                                 per_file_fp, now_iso)
    with open(os.path.join(ledger_dir, STATUS_FILENAME), "w", encoding="utf-8") as f:
        f.write(status_md)

    min_trade_date = min((str(r.get("trade_date")) for r in merged), default=None)
    summary = {
        "oos_starts_from": oos_starts_from,
        "current_fingerprint": current_fp,
        "registered_fingerprint": registered_fp,
        "fingerprint_matches_registration": current_fp == registered_fp,
        "signal_rows_read": int(len(df_signals)),
        "new_rows_this_run": len(incoming),
        "ledger_rows_total": len(merged),
        "min_trade_date_in_ledger": min_trade_date,
        "ledger_path": ledger_path,
        "status_path": os.path.join(ledger_dir, STATUS_FILENAME),
    }
    logger.info(f"run: {json.dumps(summary, ensure_ascii=False)}")
    return summary


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Observe-only forward-test ledger for money-flow rotation signals "
                    "(read-only; never fetches, never touches the nightly run)."
    )
    parser.add_argument("--project-root", default=PROJECT_ROOT_DEFAULT,
                        help="root the code fingerprint is computed against")
    parser.add_argument("--data-dir", default=None, help="default <project-root>/data")
    parser.add_argument("--output-dir", default=None, help="default <project-root>/outputs")
    parser.add_argument("--ledger-dir", default=None,
                        help="default <project-root>/loop/evidence/forward_test")
    args = parser.parse_args(argv)

    summary = run(project_root=args.project_root, data_dir=args.data_dir,
                  output_dir=args.output_dir, ledger_dir=args.ledger_dir)
    if summary is None:
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
