"""Observe-only sector aggregates for daily top-300 rankings."""

from __future__ import annotations

import json
import os
from typing import Any, Dict

import pandas as pd


# PLACEHOLDER - UNCALIBRATED: display depth for forward observation, not a signal gate.
DEFAULT_RANKING_DEPTH = 300
# PLACEHOLDER - UNCALIBRATED: number of sector rows displayed in the Excel summary.
DEFAULT_SECTOR_TOP_N = 5
TIE_BREAK_RULE = "metric, then turnover descending, then stock_id ascending"


def _safe_number(value: Any) -> float:
    try:
        return 0.0 if pd.isna(value) else float(value)
    except (TypeError, ValueError):
        return 0.0


def _stock_rows(frame: pd.DataFrame) -> list[dict]:
    return [{
        "stock_id": str(row.get("stock_id", "")),
        "stock_name": str(row.get("stock_name", "")),
        "sector_name": str(row.get("primary_sector", "待分類")),
        "daily_return": _safe_number(row.get("daily_return")),
        "turnover": _safe_number(row.get("turnover")),
    } for row in frame.to_dict("records")]


def _sector_summary(selected: pd.DataFrame, universe: pd.DataFrame, kind: str, sector_top_n: int) -> Dict[str, Any]:
    if selected.empty:
        return {"selected_stock_count": 0, "sectors": [], "top5_sectors": []}
    universe_counts = universe.groupby("primary_sector", dropna=False).size().rename("sector_stock_count")
    grouped = selected.groupby("primary_sector", dropna=False).agg(
        selected_stock_count=("stock_id", "size"), selected_turnover=("turnover", "sum"),
    ).reset_index()
    grouped["sector_stock_count"] = grouped["primary_sector"].map(universe_counts).fillna(0).astype(int)
    grouped["selected_stock_ratio"] = grouped["selected_stock_count"] / grouped["sector_stock_count"].replace(0, pd.NA)
    if kind == "top_turnover":
        total = float(selected["turnover"].sum())
        grouped["turnover_share_of_top300"] = grouped["selected_turnover"] / total if total else 0.0
    grouped = grouped.sort_values(["selected_stock_count", "selected_turnover", "primary_sector"], ascending=[False, False, True], kind="mergesort")
    sectors = []
    for row in grouped.to_dict("records"):
        item = {
            "sector_name": str(row["primary_sector"]), "selected_stock_count": int(row["selected_stock_count"]),
            "sector_stock_count": int(row["sector_stock_count"]), "selected_stock_ratio": _safe_number(row["selected_stock_ratio"]),
            "selected_turnover": _safe_number(row["selected_turnover"]),
        }
        if kind == "top_turnover":
            item["turnover_share_of_top300"] = _safe_number(row["turnover_share_of_top300"])
        sectors.append(item)
    return {"selected_stock_count": int(len(selected)), "sectors": sectors, "top5_sectors": sectors[:sector_top_n]}


def _rank_section(frame: pd.DataFrame, metric: str, ascending: bool, ranking_depth: int, sector_top_n: int) -> Dict[str, Any]:
    selected = frame.sort_values([metric, "turnover", "stock_id"], ascending=[ascending, False, True], kind="mergesort").head(ranking_depth).copy()
    result = _sector_summary(selected, frame, "top_turnover" if metric == "turnover" else metric, sector_top_n)
    result["stocks"] = _stock_rows(selected)
    return result


def _institutional_summary(frame: pd.DataFrame, sector_top_n: int) -> Dict[str, Any]:
    flow_columns = ["foreign_net_buy", "investment_trust_net_buy", "dealer_net_buy"]
    working = frame.copy()
    for column in flow_columns:
        working[column] = pd.to_numeric(working.get(column, 0.0), errors="coerce").fillna(0.0)
    working["net_buy_total"] = working[flow_columns].sum(axis=1)
    grouped = working.groupby("primary_sector", dropna=False)[flow_columns + ["net_buy_total"]].sum().reset_index()
    rows = [{
        "sector_name": str(row["primary_sector"]), "foreign_net_buy": _safe_number(row["foreign_net_buy"]),
        "investment_trust_net_buy": _safe_number(row["investment_trust_net_buy"]), "dealer_net_buy": _safe_number(row["dealer_net_buy"]),
        "net_buy_total": _safe_number(row["net_buy_total"]),
    } for row in grouped.sort_values(["primary_sector"], kind="mergesort").to_dict("records")]
    return {
        "unit": "shares", "sectors": rows,
        "net_buy_top5": sorted(rows, key=lambda row: (-row["net_buy_total"], row["sector_name"]))[:sector_top_n],
        "net_sell_top5": sorted(rows, key=lambda row: (row["net_buy_total"], row["sector_name"]))[:sector_top_n],
    }


def build_observe_rankings(df_stocks: pd.DataFrame, trade_date: str, ranking_depth: int = DEFAULT_RANKING_DEPTH,
                           sector_top_n: int = DEFAULT_SECTOR_TOP_N) -> Dict[str, Any]:
    """Build deterministic, observe-only top-ranking sector aggregates."""
    required = {"stock_id", "stock_name", "primary_sector", "daily_return", "turnover"}
    missing = required.difference(df_stocks.columns)
    if missing:
        raise ValueError(f"observe rankings missing required columns: {sorted(missing)}")
    if ranking_depth <= 0 or sector_top_n <= 0:
        raise ValueError("ranking_depth and sector_top_n must be positive")
    frame = df_stocks.copy()
    frame["stock_id"] = frame["stock_id"].astype(str)
    frame["primary_sector"] = frame["primary_sector"].fillna("待分類").astype(str)
    frame["daily_return"] = pd.to_numeric(frame["daily_return"], errors="coerce").fillna(0.0)
    frame["turnover"] = pd.to_numeric(frame["turnover"], errors="coerce").fillna(0.0)
    return {
        "trade_date": trade_date,
        "metadata": {"ranking_depth": int(ranking_depth), "sector_top_n": int(sector_top_n),
                     "tie_break_rule": TIE_BREAK_RULE, "network_calls": 0},
        "rankings": {
            "top_gainers": _rank_section(frame, "daily_return", False, ranking_depth, sector_top_n),
            "top_losers": _rank_section(frame, "daily_return", True, ranking_depth, sector_top_n),
            "top_turnover": _rank_section(frame, "turnover", False, ranking_depth, sector_top_n),
        },
        "institutional_by_sector": _institutional_summary(frame, sector_top_n),
    }


def write_observe_rankings(output_dir: str, trade_date: str, result: Dict[str, Any]) -> str:
    observe_dir = os.path.join(output_dir, "observe")
    os.makedirs(observe_dir, exist_ok=True)
    path = os.path.join(observe_dir, f"rankings_{trade_date}.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True)
    return path
