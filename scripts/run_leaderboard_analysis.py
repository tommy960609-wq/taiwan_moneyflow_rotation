"""
Milestone 7 (Pitfall Pack): orchestrates the 36-day user-collected leaderboard analysis
(src/leaderboard_loader.py + src/limit_up_history.py + src/leaderboard_reconciliation.py)
and persists the results:

  - outputs/leaderboard_analysis/limit_up_market_wide.csv
  - outputs/leaderboard_analysis/limit_up_by_sector.csv
  - outputs/leaderboard_analysis/consecutive_limit_up_streaks.csv
  - outputs/leaderboard_analysis/reconciliation_detail.csv
  - outputs/leaderboard_analysis/reconciliation_summary_<date>.json  (headline stats)

Read-only w.r.t. `data/raw/reports/` (the copied leaderboard files) and every other
already-persisted artifact this script consumes -- never mutates FinMind OHLCV,
processed CSVs, or the industry mapping.
"""

import os
import sys
import glob
import json
import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

import pandas as pd
from loguru import logger

from src.leaderboard_loader import load_all_leaderboards
from src.limit_up_history import (
    build_market_wide_limit_up_series,
    build_sector_limit_up_series,
    compute_consecutive_limit_up_streaks,
)
from src.leaderboard_reconciliation import reconcile_leaderboard_vs_finmind, summarize_reconciliation
from src.data_loader import DataLoader


def _load_finmind_ohlcv_close_only(ohlcv_dir: str) -> pd.DataFrame:
    """Lightweight loader (stock_id, trade_date, close only) -- reconciliation doesn't
    need open/high/low/volume, and building only the needed columns keeps this fast
    across ~900 per-stock files."""
    rows = []
    for path in sorted(glob.glob(os.path.join(ohlcv_dir, "finmind_*.json"))):
        fname = os.path.basename(path)
        if fname == "_smoke_twse_sample.json" or not fname.startswith("finmind_"):
            continue
        stock_id = fname.replace("finmind_", "").replace(".json", "")
        try:
            with open(path, "r", encoding="utf-8") as f:
                env = json.load(f)
        except Exception as e:
            logger.warning(f"_load_finmind_ohlcv_close_only: unreadable {path}: {e}")
            continue
        for r in env.get("payload", []) or []:
            try:
                rows.append({"stock_id": stock_id, "trade_date": r["date"], "close": float(r["close"])})
            except (KeyError, TypeError, ValueError):
                continue
    return pd.DataFrame(rows)


def run(reports_dir: str = None, data_dir: str = None, output_dir: str = None) -> dict:
    data_dir = data_dir or "C:/Workspace_CN/taiwan_moneyflow_rotation/data"
    reports_dir = reports_dir or os.path.join(data_dir, "raw", "reports")
    output_dir = output_dir or "C:/Workspace_CN/taiwan_moneyflow_rotation/outputs/leaderboard_analysis"
    os.makedirs(output_dir, exist_ok=True)

    logger.info(f"Loading leaderboard files from {reports_dir}...")
    df_lb = load_all_leaderboards(reports_dir)
    if df_lb.empty:
        logger.error("run_leaderboard_analysis: no leaderboard data loaded. Aborting.")
        return {"status": "ABORTED_NO_LEADERBOARD_DATA"}

    n_dates = df_lb["trade_date"].nunique()
    logger.info(f"Loaded {len(df_lb)} leaderboard rows across {n_dates} trade_dates "
                f"({df_lb['trade_date'].min()}..{df_lb['trade_date'].max()}).")

    # Use A: limit-up history (market-wide + sector).
    df_market = build_market_wide_limit_up_series(df_lb)
    df_market.to_csv(os.path.join(output_dir, "limit_up_market_wide.csv"), index=False, encoding="utf-8-sig")

    loader = DataLoader()
    mapping_path = os.path.join(data_dir, "reference", "stock_industry_mapping.xlsx")
    df_mapping = loader.load_industry_mapping(mapping_path)
    df_sector = build_sector_limit_up_series(df_lb, df_mapping)
    df_sector.to_csv(os.path.join(output_dir, "limit_up_by_sector.csv"), index=False, encoding="utf-8-sig")

    df_streaks = compute_consecutive_limit_up_streaks(df_lb)
    df_streaks.to_csv(os.path.join(output_dir, "consecutive_limit_up_streaks.csv"), index=False, encoding="utf-8-sig")

    # Use B: 36-day cross-reconciliation vs FinMind.
    logger.info("Loading FinMind OHLCV (close-only) for reconciliation...")
    df_ohlcv = _load_finmind_ohlcv_close_only(os.path.join(data_dir, "raw", "ohlcv"))
    logger.info(f"Loaded {len(df_ohlcv)} FinMind close rows across {df_ohlcv['stock_id'].nunique() if not df_ohlcv.empty else 0} stocks.")

    df_reconciled = reconcile_leaderboard_vs_finmind(df_lb, df_ohlcv)
    df_reconciled.to_csv(os.path.join(output_dir, "reconciliation_detail.csv"), index=False, encoding="utf-8-sig")
    recon_summary = summarize_reconciliation(df_reconciled)

    max_streak_row = df_streaks.loc[df_streaks["consecutive_limit_up_days"].idxmax()] if not df_streaks.empty else None

    summary = {
        "status": "SUCCESS",
        "leaderboard_files_loaded": n_dates,
        "leaderboard_date_range": [str(df_lb["trade_date"].min()), str(df_lb["trade_date"].max())],
        "market_wide_limit_up_total_stock_days": int(df_market["limit_up_count"].sum()) if not df_market.empty else 0,
        "market_wide_limit_up_mean_per_day": float(df_market["limit_up_count"].mean()) if not df_market.empty else None,
        "max_consecutive_limit_up_streak": {
            "stock_id": max_streak_row["stock_id"], "trade_date": max_streak_row["trade_date"],
            "consecutive_days": int(max_streak_row["consecutive_limit_up_days"]),
        } if max_streak_row is not None else None,
        "reconciliation": recon_summary,
        "known_limitations": [
            "漲停家數為 proxy（漲跌幅>=9.5% 視為漲停），非官方鎖漲停旗標；leaderboard 僅收錄當日 top300，"
            "非全市場（惟真實漲停股票實務上幾乎必落在 top300 內，未逐一驗證全市場外是否遺漏）",
            "36 個檔案之間存在真實日期缺口（如 2026-06-17~2026-06-26 完全缺收，非本系統之錯）；"
            "連續漲停 streak 計算已對此缺口斷開，不跨缺口累計",
            "族群歸屬使用本系統既有 stock_industry_mapping，未分類個股計入「未分類」",
            f"對帳覆蓋率僅 {recon_summary.get('coverage_pct')}（受限於 FinMind OHLCV 回補進度，非全部 300*36 筆皆可比對）",
        ],
        "output_files": [
            os.path.join(output_dir, "limit_up_market_wide.csv"),
            os.path.join(output_dir, "limit_up_by_sector.csv"),
            os.path.join(output_dir, "consecutive_limit_up_streaks.csv"),
            os.path.join(output_dir, "reconciliation_detail.csv"),
        ],
    }

    summary_path = os.path.join(output_dir, f"reconciliation_summary_{datetime.date.today().isoformat()}.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"Leaderboard analysis summary written to {summary_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return summary


if __name__ == "__main__":
    run()
