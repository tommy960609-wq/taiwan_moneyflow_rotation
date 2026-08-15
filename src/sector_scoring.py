import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple
from loguru import logger

# SPEC section 12.1 / SPEC_ADDENDUM B-1: all weights below are first-cut, uncalibrated
# priors carried over from the original spec document. They must not be treated as
# validated until Milestone 5 backtesting calibration is complete.
DEFAULT_SECTOR_WEIGHTS = {
    "breadth": 0.25,       # PLACEHOLDER - UNCALIBRATED
    "volume_share": 0.25,  # PLACEHOLDER - UNCALIBRATED
    "strength": 0.20,      # PLACEHOLDER - UNCALIBRATED
    "momentum": 0.15,      # PLACEHOLDER - UNCALIBRATED
    "institution": 0.10,   # PLACEHOLDER - UNCALIBRATED
    "health": 0.05,        # PLACEHOLDER - UNCALIBRATED
}

# SPEC section 12.3: overheat risk sub-weights (also uncalibrated placeholders).
OVERHEAT_SUBWEIGHTS = {
    "breadth_vs_volume_divergence": 0.35,  # PLACEHOLDER - UNCALIBRATED
    "volume_surge": 0.35,                  # PLACEHOLDER - UNCALIBRATED
    "concentration": 0.30,                 # PLACEHOLDER - UNCALIBRATED
}

OVERHEAT_RISK_PENALTY_FACTOR = 0.002  # PLACEHOLDER - UNCALIBRATED


class SectorScoring:
    def __init__(self, config_weights: Optional[dict] = None):
        self.default_weights = config_weights or dict(DEFAULT_SECTOR_WEIGHTS)

    def score_sectors(self,
                      df_sectors: pd.DataFrame,
                      has_institutional: bool = True,
                      has_momentum: bool = True) -> Tuple[pd.DataFrame, str]:
        if df_sectors.empty:
            return df_sectors, "LOW"

        df = df_sectors.copy()
        active_weights = self.default_weights.copy()
        confidence = "FULL"

        if not has_institutional:
            active_weights["institution"] = 0.0
            confidence = "DEGRADED"
        if not has_momentum:
            active_weights["momentum"] = 0.0
            confidence = "DEGRADED"

        # If breadth/volume_share/strength/health themselves are entirely missing
        # (e.g. NaN for every row because of upstream data gaps), zero their weight too
        # and reflect that as a further-degraded LOW confidence rather than silently
        # filling missing factors with a neutral score.
        factor_to_column = {
            "breadth": "breadth",
            "volume_share": "volume_share",
            "strength": "relative_strength",
            "health": "hhi",
        }
        missing_factor_count = 0
        for factor, col in factor_to_column.items():
            if col not in df.columns or df[col].isna().all():
                if active_weights.get(factor, 0.0) > 0:
                    missing_factor_count += 1
                active_weights[factor] = 0.0

        weight_sum = sum(active_weights.values())
        if weight_sum <= 0:
            logger.error("All scoring weights are zero due to data missing.")
            df["score"] = np.nan
            df["score_confidence"] = "LOW"
            return df, "LOW"

        # Dynamic weight renormalization (SPEC 12.2 / B-1): missing factors are NEVER
        # scored as zero; instead the remaining active weights are rescaled so they
        # still sum to 1.0.
        normalized_weights = {k: v / weight_sum for k, v in active_weights.items()}

        if missing_factor_count > 0:
            confidence = "LOW"

        for col in ["breadth", "volume_share", "relative_strength", "inst_flow_ratio", "hhi"]:
            if col in df.columns and df[col].notna().sum() > 1:
                if col == "hhi":
                    # Lower HHI (less concentrated / healthier structure) -> higher score
                    df["score_" + col] = (1.0 - df[col].rank(pct=True)) * 100
                else:
                    df["score_" + col] = df[col].rank(pct=True) * 100
            elif col in df.columns and df[col].notna().sum() == 1:
                # Single valid observation: percentile rank is undefined: use midpoint
                # rather than fabricating a distribution.
                df["score_" + col] = df[col].notna().map({True: 50.0, False: np.nan})
            else:
                df["score_" + col] = np.nan

        raw_scores = []
        overheat_risks = []

        for _, row in df.iterrows():
            s_breadth = row["score_breadth"] if pd.notna(row.get("score_breadth")) else 50.0
            s_vol = row["score_volume_share"] if pd.notna(row.get("score_volume_share")) else 50.0
            s_strength = row["score_relative_strength"] if pd.notna(row.get("score_relative_strength")) else 50.0
            s_inst = row["score_inst_flow_ratio"] if (has_institutional and pd.notna(row.get("score_inst_flow_ratio"))) else 50.0
            s_health = row["score_hhi"] if pd.notna(row.get("score_hhi")) else 50.0
            s_mom = 50.0  # momentum/continuity sub-score not yet independently modeled; neutral prior

            score_val = (
                normalized_weights.get("breadth", 0.0) * s_breadth +
                normalized_weights.get("volume_share", 0.0) * s_vol +
                normalized_weights.get("strength", 0.0) * s_strength +
                normalized_weights.get("momentum", 0.0) * s_mom +
                normalized_weights.get("institution", 0.0) * s_inst +
                normalized_weights.get("health", 0.0) * s_health
            )
            # Clamp to the documented 0-100 scoring range (SPEC 12.1/16).
            score_val = float(np.clip(score_val, 0.0, 100.0))
            raw_scores.append(score_val)

            overheat = self._compute_overheat_risk(row, s_breadth, s_vol)
            overheat_risks.append(overheat)

        df["raw_score"] = raw_scores
        df["overheat_risk"] = overheat_risks

        df["score"] = (df["raw_score"] * (1 - (df["overheat_risk"] * OVERHEAT_RISK_PENALTY_FACTOR).clip(0.0, 0.5))).clip(0.0, 100.0)
        df["score_confidence"] = confidence

        return df, confidence

    def _compute_overheat_risk(self, row: pd.Series, s_breadth: float, s_vol: float) -> float:
        """
        Overheat Risk (SPEC 12.3), scaled 0-100. Only the sub-factors computable from
        currently available sector-level aggregates are implemented (breadth/volume
        divergence, volume surge proxy, single-stock concentration). Factors requiring
        data not yet wired into the pipeline (consecutive-limit-up counts, upper-shadow
        candle ratios, institutional-selling reversal) are intentionally NOT
        approximated here; see docs/Milestone_2_Acceptance_Report.md for the explicit
        list of unimplemented sub-factors.
        """
        # High volume share concentrated in very few names + weak breadth => divergence risk.
        divergence = max(0.0, s_vol - s_breadth)

        volume_surge = s_vol  # proxy: high percentile volume share vs peers

        hhi = row.get("hhi", np.nan)
        concentration = float(np.clip(hhi, 0.0, 1.0)) * 100 if pd.notna(hhi) else 50.0

        risk = (
            OVERHEAT_SUBWEIGHTS["breadth_vs_volume_divergence"] * divergence +
            OVERHEAT_SUBWEIGHTS["volume_surge"] * volume_surge +
            OVERHEAT_SUBWEIGHTS["concentration"] * concentration
        )
        return float(np.clip(risk, 0.0, 100.0))
