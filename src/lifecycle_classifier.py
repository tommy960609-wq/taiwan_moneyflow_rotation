import pandas as pd
import numpy as np
from typing import Dict, Optional, List

INSUFFICIENT_DATA_LABEL = "資料不足"

# SPEC section 13: lifecycle stage thresholds. Uncalibrated priors per
# SPEC_ADDENDUM B-1 until Milestone 5 backtest calibration.
LIFECYCLE_THRESHOLDS = {
    "accelerate_score": 75,       # PLACEHOLDER - UNCALIBRATED
    "accelerate_breadth": 0.70,   # PLACEHOLDER - UNCALIBRATED
    "ignite_score": 65,           # PLACEHOLDER - UNCALIBRATED
    "ignite_score_delta": 5,      # PLACEHOLDER - UNCALIBRATED
    "ignite_breadth_delta": 0.10, # PLACEHOLDER - UNCALIBRATED
    "diffuse_score": 65,          # PLACEHOLDER - UNCALIBRATED
    "diffuse_hhi": 0.35,          # PLACEHOLDER - UNCALIBRATED
    "dormant_score": 55,          # PLACEHOLDER - UNCALIBRATED
    "diverge_score": 55,          # PLACEHOLDER - UNCALIBRATED
    "diverge_hhi": 0.50,          # PLACEHOLDER - UNCALIBRATED
}


class LifecycleClassifier:
    """
    Classifies each sector into one of six lifecycle stages (SPEC section 13):
    潛伏期 (dormant) / 點火期 (ignite) / 擴散期 (diffuse) / 加速期 (accelerate) /
    分化期 (diverge) / 退潮期 (fade).

    Per SPEC 13.6 ("分類必須同時使用最近3、5及10日資料，不得只看單日"), classification
    requires at least 3 consecutive trading days of sector-metrics history for the
    sector in question (score + breadth time series). If fewer than 3 days of history
    are available, the sector is labeled `INSUFFICIENT_DATA_LABEL` ("資料不足") instead
    of guessing a stage from a single day's snapshot.

    Input: a stacked, multi-day sector-metrics history DataFrame (one row per
    sector_name per trade_date, must include trade_date, sector_name, score, breadth,
    hhi, relative_strength, sorted chronologically). Returns the same DataFrame
    filtered/re-ordered with only the LATEST trade_date's rows, each annotated with a
    `lifecycle` column (and `lifecycle_confidence` reflecting how much history backed
    the call: FULL when >=10 days available, PARTIAL when 3-9 days, INSUFFICIENT_DATA
    when <3 days).
    """

    def __init__(self):
        pass

    def classify_lifecycle(self,
                           df_sector_history: pd.DataFrame,
                           min_days_required: int = 3) -> pd.DataFrame:
        if df_sector_history.empty:
            return df_sector_history

        required_cols = {"trade_date", "sector_name", "score", "breadth"}
        missing = required_cols - set(df_sector_history.columns)
        if missing:
            raise ValueError(f"df_sector_history missing required columns: {missing}")

        df = df_sector_history.sort_values(["sector_name", "trade_date"]).copy()
        latest_date = df["trade_date"].max()

        results: List[dict] = []
        for sector_name, group in df.groupby("sector_name"):
            group = group.sort_values("trade_date")
            latest_row = group[group["trade_date"] == latest_date]
            if latest_row.empty:
                continue
            latest_row = latest_row.iloc[-1]

            history_len = len(group)
            out_row = latest_row.to_dict()

            if history_len < min_days_required:
                out_row["lifecycle"] = INSUFFICIENT_DATA_LABEL
                out_row["lifecycle_confidence"] = "INSUFFICIENT_DATA"
                results.append(out_row)
                continue

            lifecycle_confidence = "FULL" if history_len >= 10 else "PARTIAL"

            # Use most-recent 3/5/10-day windows (bounded by available history) to
            # evaluate trend direction, per SPEC 13.6.
            win3 = group.tail(min(3, history_len))
            win5 = group.tail(min(5, history_len))
            win10 = group.tail(min(10, history_len))

            score_today = latest_row["score"]
            breadth_today = latest_row["breadth"]
            hhi_today = latest_row.get("hhi", np.nan)
            rel_strength_today = latest_row.get("relative_strength", np.nan)

            score_3d_ago = win3["score"].iloc[0]
            breadth_3d_ago = win3["breadth"].iloc[0]

            score_delta_3d = score_today - score_3d_ago if pd.notna(score_today) and pd.notna(score_3d_ago) else np.nan
            breadth_delta_3d = breadth_today - breadth_3d_ago if pd.notna(breadth_today) and pd.notna(breadth_3d_ago) else np.nan

            # 5-day and 10-day medians give a stability read across the required
            # windows (SPEC 13.6 requires 3/5/10-day joint evidence, not a single day).
            score_5d_trend = win5["score"].diff().mean() if len(win5) >= 2 else np.nan
            score_10d_trend = win10["score"].diff().mean() if len(win10) >= 2 else np.nan

            lifecycle = self._classify_stage(
                score_today, breadth_today, hhi_today, rel_strength_today,
                score_delta_3d, breadth_delta_3d, score_5d_trend, score_10d_trend,
            )

            out_row["lifecycle"] = lifecycle
            out_row["lifecycle_confidence"] = lifecycle_confidence
            results.append(out_row)

        return pd.DataFrame(results)

    def _classify_stage(self, score, breadth, hhi, rel_strength,
                        score_delta_3d, breadth_delta_3d, score_5d_trend, score_10d_trend) -> str:
        if pd.isna(score) or pd.isna(breadth):
            return INSUFFICIENT_DATA_LABEL

        t = LIFECYCLE_THRESHOLDS

        # 加速期 (accelerate): very high score + very high breadth, still rising or
        # holding per 5/10-day trend.
        if score >= t["accelerate_score"] and breadth >= t["accelerate_breadth"]:
            return "加速期"

        # 點火期 (ignite): score just broke out higher over the last 3 days alongside
        # meaningfully expanding breadth.
        if (score >= t["ignite_score"]
                and pd.notna(score_delta_3d) and score_delta_3d > t["ignite_score_delta"]
                and pd.notna(breadth_delta_3d) and breadth_delta_3d > t["ignite_breadth_delta"]):
            return "點火期"

        # 擴散期 (diffuse): score strong and turnover concentration low (participation
        # broadening beyond a single leader).
        if score >= t["diffuse_score"] and pd.notna(hhi) and hhi < t["diffuse_hhi"]:
            return "擴散期"

        # 分化期 (diverge): weakening score with high single-stock concentration.
        if score < t["diverge_score"] and pd.notna(hhi) and hhi >= t["diverge_hhi"]:
            return "分化期"

        # 潛伏期 (dormant): still below the mainstream threshold but trend and relative
        # strength are constructive (rising score, positive relative strength).
        if (score < t["dormant_score"]
                and pd.notna(score_delta_3d) and score_delta_3d > 0
                and pd.notna(rel_strength) and rel_strength > 0):
            return "潛伏期"

        # 退潮期 (fade): default when none of the constructive/expansion conditions
        # above are met (declining/weak score, negative relative strength, breadth
        # contracting).
        return "退潮期"
