import pandas as pd
import numpy as np
from typing import Optional, Tuple
from loguru import logger

# SPEC section 16: individual stock scoring weights. Uncalibrated priors per
# SPEC_ADDENDUM B-1 until Milestone 5 backtest calibration.
DEFAULT_STOCK_WEIGHTS = {
    "sector_score": 0.35,          # PLACEHOLDER - UNCALIBRATED
    "relative_strength": 0.20,     # PLACEHOLDER - UNCALIBRATED
    "volume_structure": 0.15,      # PLACEHOLDER - UNCALIBRATED
    "rank_improvement": 0.10,      # PLACEHOLDER - UNCALIBRATED
    "breakout_quality": 0.10,      # PLACEHOLDER - UNCALIBRATED
    "institution": 0.10,           # PLACEHOLDER - UNCALIBRATED
}

ROLE_SCORE_THRESHOLDS = {
    "領先龍頭": 80,             # PLACEHOLDER - UNCALIBRATED
    "高流動性次龍頭": 65,       # PLACEHOLDER - UNCALIBRATED
    "基本面受惠股": 45,         # PLACEHOLDER - UNCALIBRATED
}


class StockScoring:
    def __init__(self, config_weights: Optional[dict] = None):
        self.default_weights = config_weights or dict(DEFAULT_STOCK_WEIGHTS)

    def score_stocks(self,
                     df_mapped_prices: pd.DataFrame,
                     df_scored_sectors: pd.DataFrame,
                     has_institutional: bool = True,
                     has_rank_improvement: bool = True,
                     has_breakout_quality: bool = False) -> Tuple[pd.DataFrame, str]:
        if df_mapped_prices.empty:
            return df_mapped_prices, "LOW"

        df = df_mapped_prices.copy()

        sector_scores = {}
        if not df_scored_sectors.empty and "score" in df_scored_sectors.columns:
            for _, r in df_scored_sectors.iterrows():
                sector_scores[r["sector_name"]] = r["score"]

        sec_scores_col = []
        for _, row in df.iterrows():
            sec_scores_col.append(sector_scores.get(row["primary_sector"], np.nan))
        df["sector_score"] = sec_scores_col

        active_weights = self.default_weights.copy()
        confidence = "FULL"

        has_sector_score = df["sector_score"].notna().any()
        if not has_sector_score:
            active_weights["sector_score"] = 0.0
            confidence = "LOW"

        n_valid = len(df)
        if n_valid > 1:
            df["score_strength"] = df["daily_return"].rank(pct=True) * 100 if "daily_return" in df.columns else np.nan
            df["score_volume"] = df["volume"].rank(pct=True) * 100 if "volume" in df.columns else np.nan
        else:
            df["score_strength"] = np.nan
            df["score_volume"] = np.nan

        if has_rank_improvement and "rank_improvement" in df.columns and n_valid > 1:
            df["score_improvement"] = df["rank_improvement"].rank(pct=True) * 100
        else:
            active_weights["rank_improvement"] = 0.0
            confidence = "DEGRADED" if confidence == "FULL" else confidence
            df["score_improvement"] = np.nan

        if has_breakout_quality and "dist_from_20d_high" in df.columns and df["dist_from_20d_high"].notna().any():
            # Closer to (or at) the 20-day high => higher breakout-quality percentile.
            df["score_breakout"] = df["dist_from_20d_high"].rank(pct=True) * 100
        else:
            active_weights["breakout_quality"] = 0.0
            confidence = "DEGRADED" if confidence == "FULL" else confidence
            df["score_breakout"] = np.nan

        if has_institutional and "foreign_net_buy" in df.columns and df["foreign_net_buy"].notna().any():
            df["score_institution"] = df["foreign_net_buy"].rank(pct=True) * 100
        else:
            active_weights["institution"] = 0.0
            confidence = "DEGRADED" if confidence == "FULL" else confidence
            df["score_institution"] = np.nan

        if df["score_strength"].isna().all():
            active_weights["relative_strength"] = 0.0
            confidence = "DEGRADED" if confidence == "FULL" else confidence
        if df["score_volume"].isna().all():
            active_weights["volume_structure"] = 0.0
            confidence = "DEGRADED" if confidence == "FULL" else confidence

        weight_sum = sum(active_weights.values())
        if weight_sum <= 0:
            logger.error("All stock scoring weights are zero due to data missing.")
            df["stock_score"] = np.nan
            df["stock_role"] = "資料不足"
            df["score_confidence"] = "LOW"
            return df, "LOW"

        normalized_weights = {k: v / weight_sum for k, v in active_weights.items()}

        def _fill(col):
            return df[col] if col in df.columns else pd.Series(np.nan, index=df.index)

        stock_scores = (
            normalized_weights.get("sector_score", 0.0) * _fill("sector_score").fillna(50.0) +
            normalized_weights.get("relative_strength", 0.0) * _fill("score_strength").fillna(50.0) +
            normalized_weights.get("volume_structure", 0.0) * _fill("score_volume").fillna(50.0) +
            normalized_weights.get("rank_improvement", 0.0) * _fill("score_improvement").fillna(50.0) +
            normalized_weights.get("breakout_quality", 0.0) * _fill("score_breakout").fillna(50.0) +
            normalized_weights.get("institution", 0.0) * _fill("score_institution").fillna(50.0)
        )
        df["stock_score"] = stock_scores.clip(0.0, 100.0)
        df["score_confidence"] = confidence

        roles = []
        for _, row in df.iterrows():
            s = row["stock_score"]
            if pd.isna(s):
                roles.append("資料不足")
            elif s >= ROLE_SCORE_THRESHOLDS["領先龍頭"]:
                roles.append("領先龍頭")
            elif s >= ROLE_SCORE_THRESHOLDS["高流動性次龍頭"]:
                roles.append("高流動性次龍頭")
            elif s >= ROLE_SCORE_THRESHOLDS["基本面受惠股"]:
                roles.append("基本面受惠股")
            else:
                roles.append("低位階補漲股")

        df["stock_role"] = roles
        return df.sort_values("stock_score", ascending=False, na_position="last"), confidence
