import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple

from src.threshold_calibration import (
    build_calibrated_new_gainer_config,
    build_calibrated_continued_momentum_config,
)

# SPEC Chapter 14 (New Gainer / 新起漲) and Chapter 15 (Continued Momentum / 續漲)
# default thresholds. All are first-cut, uncalibrated priors carried over from the
# original spec document (SPEC_ADDENDUM B-1): they must not be treated as validated
# until Milestone 5 backtest calibration, and every threshold below is mirrored in
# config/default.yaml under the same key names with a `# PLACEHOLDER - UNCALIBRATED`
# comment so operators reading the config see the same warning operators reading this
# module see.
#
# Milestone 9 (SPEC_ADDENDUM B-1.3): `min_score`/`prev_score_max` (new_gainer) and
# `min_score` (continued_momentum) are the ones most directly implicated in the M5c/M9
# finding that a fixed absolute score bar interacts with this module's C-grade
# fallback to produce a signal on effectively every sector-day. These three values
# below remain the FALLBACK used only when `SignalDetector(use_calibrated_thresholds=
# True, df_sector_history=...)` doesn't have enough same-sector history yet (see
# src/threshold_calibration.py MIN_CALIBRATION_PERIODS) -- when it does, the sector's
# own rolling-quantile value is used instead
# (# CALIBRATED (n=28 trading days, 2026-04-20~2026-07-17) - PRELIMINARY, small sample,
# non-contiguous history -- see docs/Milestone_9_Calibration_Backtest_Report.md).
# The other 7 new_gainer conditions and 6 continued_momentum conditions are left as
# absolute PLACEHOLDER values this milestone (not enough independent history to
# calibrate 17 thresholds credibly off ~28 days -- see the report's methodology
# section for why only these 3 were prioritized).
DEFAULT_NEW_GAINER_CONFIG = {
    "min_score": 70,                    # CALIBRATED (n=28 trading days, 2026-04-20~2026-07-17) - PRELIMINARY, small sample; this literal 70 is the fallback used only when a sector lacks enough prior history (see src/threshold_calibration.py)
    "prev_score_max": 55,               # CALIBRATED (n=28 trading days, 2026-04-20~2026-07-17) - PRELIMINARY, small sample; fallback-only, see above
    "score_breakout_days": 5,           # PLACEHOLDER - UNCALIBRATED
    "min_rank100_change": 3,            # PLACEHOLDER - UNCALIBRATED
    "min_volume_growth_pct": 0.50,      # PLACEHOLDER - UNCALIBRATED
    "min_excess_return_pct": 2.0,       # PLACEHOLDER - UNCALIBRATED
    "min_top50_count": 2,               # PLACEHOLDER - UNCALIBRATED
    "max_top1_volume_pct": 0.70,        # PLACEHOLDER - UNCALIBRATED
    "max_overheat_days": 3,             # PLACEHOLDER - UNCALIBRATED
    "min_data_quality_score": 85,       # PLACEHOLDER - UNCALIBRATED
    "min_mapping_coverage_pct": 0.80,   # PLACEHOLDER - UNCALIBRATED
    "max_conditions_failed_for_b": 4,   # PLACEHOLDER - UNCALIBRATED
    # PLACEHOLDER - UNCALIBRATED: selectivity design default, not optimized from
    # forward returns.  B also requires at least one breadth rule (3 or 6) to pass.
    "min_core_passed_for_b": 3,
    "min_breadth_core_passed_for_b": 1,
}

DEFAULT_CONTINUED_MOMENTUM_CONFIG = {
    "min_score_days": 2,                  # PLACEHOLDER - UNCALIBRATED
    "min_score": 65,                      # CALIBRATED (n=28 trading days, 2026-04-20~2026-07-17) - PRELIMINARY, small sample; fallback-only, see DEFAULT_NEW_GAINER_CONFIG comment above
    "min_volume_share_maintained": True,  # PLACEHOLDER - UNCALIBRATED
    "max_rank100_drop_pct": 0.30,         # PLACEHOLDER - UNCALIBRATED
    "min_excess_return_pct": 0.0,         # PLACEHOLDER - UNCALIBRATED
    "max_overheat_risk": 75,              # PLACEHOLDER - UNCALIBRATED
    "min_data_quality_score": 70,         # PLACEHOLDER - UNCALIBRATED
}

GRADE_A = "A級新起漲"
GRADE_B = "B級早期點火"
GRADE_C = "C級個股事件"
GRADE_NONE = "無效"
GRADE_CONTINUED = "續漲訊號"
GRADE_NO_SIGNAL = "無訊號"

# UAT-04 (SPEC_ADDENDUM acceptance test): a sector cannot be judged "New Gainer" on the
# strength of a single stock moving. We require at least this many *distinct* stocks
# among the sector's up-movers before any A/B/C new-gainer grade is possible; below
# this floor the sector is hard-capped at C (or 無效 if it also fails structurally).
MIN_UP_STOCKS_FOR_SECTOR_SIGNAL = 2

# Selectivity policy (design defaults, not calibrated values).  Rules 1/3/4/5/6
# are evidence of a sector-wide move; rules 7/8/9/10 are safety/data vetoes.  Rule
# 2 is a trigger and must be explicitly passed before any new-gainer grade is emitted.
NEW_GAINER_CORE_RULES = frozenset({1, 3, 4, 5, 6})
NEW_GAINER_BREADTH_CORE_RULES = frozenset({3, 6})
NEW_GAINER_VETO_RULES = frozenset({7, 8, 9, 10})
NEW_GAINER_TRIGGER_RULE = 2
NEW_GAINER_INDIVIDUAL_RULE = 6
CONTINUED_CORE_RULES = frozenset({1, 4})


class SignalDetector:
    """
    Detects New Gainer (新起漲, SPEC Chapter 14) and Continued Momentum (續漲, SPEC
    Chapter 15) sector signals from a scored+lifecycle-classified sector history.

    Every signal-eligible row is annotated with:
      - signal_type: one of GRADE_A/B/C/NONE (new-gainer track) or GRADE_CONTINUED/
        GRADE_NO_SIGNAL (continued-momentum track).
      - signal_reason: human-readable Chinese summary (kept for backward
        compatibility with M1/M2 report code paths).
      - conditions_passed / conditions_failed: parallel lists of "rule N: description"
        strings so every downstream report can show exactly which of the 10 (new
        gainer) / 9 (continued momentum) SPEC conditions fired.
      - invalidation_condition: the specific condition under which this signal should
        be considered void (SPEC Chapter 21 "失效條件" requirement).
      - data_confidence: FULL / DEGRADED / LOW, reflecting how many conditions could
        not be evaluated due to missing upstream data (never silently treated as pass
        or fail -- an unevaluable condition is excluded from both the pass and fail
        counts and pulls confidence down instead).

    Input contract: `df_classified_sectors` must be the CURRENT trading day's slice of
    the sector history (one row per sector_name), already carrying score/breadth/
    hhi/volume_share/relative_strength/overheat_risk/lifecycle from upstream stages.
    `df_sectors_prev` (optional) is the previous trading day's equivalent slice, used
    for day-over-day deltas (score breakout, rank100 change, volume growth). Passing
    None degrades every delta-dependent condition to "unevaluable" rather than
    guessing a value.
    """

    def __init__(self,
                 new_gainer_config: Optional[dict] = None,
                 continued_momentum_config: Optional[dict] = None,
                 df_sector_history: Optional[pd.DataFrame] = None,
                 use_calibrated_thresholds: bool = False):
        self.ng_cfg = {**DEFAULT_NEW_GAINER_CONFIG, **(new_gainer_config or {})}
        self.cm_cfg = {**DEFAULT_CONTINUED_MOMENTUM_CONFIG, **(continued_momentum_config or {})}
        # Milestone 9 (SPEC_ADDENDUM B-1.3): when `use_calibrated_thresholds=True` and
        # `df_sector_history` (a sector_name/trade_date/score history frame, e.g.
        # run_daily.py's df_scored_sector_history) is supplied, `min_score`/
        # `prev_score_max` (new-gainer) and `min_score` (continued-momentum) are
        # recomputed PER SECTOR PER DAY as rolling quantile thresholds instead of the
        # fixed absolute placeholders -- see src/threshold_calibration.py for the exact
        # method, the no-lookahead guarantee, and the PRELIMINARY/small-sample
        # disclosure. Default False preserves the exact pre-M9 behavior (fixed
        # thresholds for every sector) so no existing caller is affected unless it
        # explicitly opts in.
        self.df_sector_history = df_sector_history
        self.use_calibrated_thresholds = use_calibrated_thresholds

    def _cfg_for_sector(self, sector_name: str, trade_date, base_cfg: dict, kind: str) -> dict:
        """
        Returns `base_cfg` unchanged unless `use_calibrated_thresholds` is on and a
        usable `df_sector_history` was supplied at construction time -- in which case
        returns the per-sector, per-day calibrated config (src/threshold_calibration.py).
        `kind` is "new_gainer" or "continued_momentum".
        """
        if not self.use_calibrated_thresholds or self.df_sector_history is None:
            return base_cfg
        if kind == "new_gainer":
            return build_calibrated_new_gainer_config(
                self.df_sector_history, sector_name, trade_date, base_cfg)
        return build_calibrated_continued_momentum_config(
            self.df_sector_history, sector_name, trade_date, base_cfg)

    def detect_signals(self,
                       df_classified_sectors: pd.DataFrame,
                       df_sectors_prev: Optional[pd.DataFrame] = None,
                       df_stock_features: Optional[pd.DataFrame] = None,
                       df_stock_features_prev: Optional[pd.DataFrame] = None,
                       dq_score: Optional[float] = None,
                       mapping_coverage_pct: Optional[float] = None,
                       score_history: Optional[Dict[str, List[float]]] = None) -> pd.DataFrame:
        """
        Args:
          df_classified_sectors: current-day sector rows (score/breadth/hhi/
            volume_share/relative_strength/overheat_risk/lifecycle/top1_concentration/
            up_stock_count/stock_count/sector_type/may_double_count).
          df_sectors_prev: previous trading day's equivalent sector rows (optional).
          df_stock_features: current-day stock-level rows with `current_rank` and
            `primary_sector`/theme columns, used to count each sector's presence in
            the market top-50/top-100 (rules 3 and 6). Optional; when absent those
            rules are marked unevaluable rather than assumed to pass.
          df_stock_features_prev: previous trading day's equivalent stock-level rows,
            used only to compute the prior day's per-sector top-100 count for the
            day-over-day delta in rules 3 (new gainer) / 3 (continued momentum).
            Optional; without it those specific deltas are marked unevaluable.
          dq_score: overall pipeline Data Quality Score (0-100) for rule 9. None if
            unavailable (condition marked unevaluable, not assumed to pass).
          mapping_coverage_pct: industry mapping coverage ratio (0.0-1.0) for rule 10.
          score_history: optional {sector_name: [score_day_(t-5), ..., score_day_(t-1)]}
            recent-score list (oldest first, NOT including today) used for the "first
            breakout to >=70 within last 5 days" branch of rule 2 and the "extreme
            overheat for 3 consecutive days" check of rule 8. Without it, those specific
            sub-checks fall back to the simpler prev-day-only comparison and are noted
            as reduced-evidence in the invalidation condition text.
        """
        if df_classified_sectors.empty:
            return df_classified_sectors

        df = df_classified_sectors.copy()

        prev_by_name: Dict[str, dict] = {}
        if df_sectors_prev is not None and not df_sectors_prev.empty:
            for _, r in df_sectors_prev.iterrows():
                prev_by_name[r["sector_name"]] = r.to_dict()

        top_counts = self._compute_sector_top_counts(df_stock_features, df_stock_features_prev)

        signal_types, reasons = [], []
        conditions_passed_list, conditions_failed_list, conditions_unevaluable_list = [], [], []
        invalidation_list, data_confidence_list = [], []

        for _, row in df.iterrows():
            name = row["sector_name"]
            trade_date = row.get("trade_date")
            prev = prev_by_name.get(name)
            top50_count, top100_count, prev_top100_count = top_counts.get(name, (None, None, None))
            hist = (score_history or {}).get(name)

            ng_cfg = self._cfg_for_sector(name, trade_date, self.ng_cfg, "new_gainer")
            cm_cfg = self._cfg_for_sector(name, trade_date, self.cm_cfg, "continued_momentum")

            ng_result = self._evaluate_new_gainer(row, prev, top50_count, top100_count,
                                                    prev_top100_count, dq_score,
                                                    mapping_coverage_pct, hist, ng_cfg)
            cm_result = self._evaluate_continued_momentum(row, prev, top100_count,
                                                            prev_top100_count, dq_score, cm_cfg)

            # New-gainer and continued-momentum are evaluated independently; a sector
            # already in an active uptrend is reported under whichever track has the
            # more specific/actionable grade. Preference: A/B/C new-gainer grades are
            # reported first (they represent a fresh ignition event, the system's
            # primary purpose); continued-momentum is reported when no new-gainer
            # grade applies but the continuation conditions are met; otherwise 無訊號.
            if ng_result["grade"] in (GRADE_A, GRADE_B, GRADE_C):
                signal_types.append(ng_result["grade"])
                reasons.append(ng_result["reason"])
                conditions_passed_list.append(ng_result["passed"])
                conditions_failed_list.append(ng_result["failed"])
                conditions_unevaluable_list.append(ng_result["unevaluable"])
                invalidation_list.append(ng_result["invalidation"])
                data_confidence_list.append(ng_result["confidence"])
            elif cm_result["grade"] == GRADE_CONTINUED:
                signal_types.append(cm_result["grade"])
                reasons.append(cm_result["reason"])
                conditions_passed_list.append(cm_result["passed"])
                conditions_failed_list.append(cm_result["failed"])
                conditions_unevaluable_list.append(cm_result["unevaluable"])
                invalidation_list.append(cm_result["invalidation"])
                data_confidence_list.append(cm_result["confidence"])
            else:
                signal_types.append(GRADE_NO_SIGNAL)
                reasons.append("未達新起漲或續漲門檻")
                conditions_passed_list.append(ng_result["passed"])
                conditions_failed_list.append(ng_result["failed"])
                conditions_unevaluable_list.append(ng_result["unevaluable"])
                invalidation_list.append("無有效訊號，無失效條件適用")
                data_confidence_list.append(ng_result["confidence"])

        df["signal_type"] = signal_types
        df["signal_reason"] = reasons
        df["conditions_passed"] = conditions_passed_list
        df["conditions_failed"] = conditions_failed_list
        df["conditions_unevaluable"] = conditions_unevaluable_list
        df["invalidation_condition"] = invalidation_list
        df["signal_data_confidence"] = data_confidence_list
        return df

    # ------------------------------------------------------------------
    # New Gainer (新起漲, SPEC Chapter 14) -- 10 conditions
    # ------------------------------------------------------------------
    def _evaluate_new_gainer(self, row, prev, top50_count, top100_count,
                              prev_top100_count, dq_score, mapping_coverage_pct,
                              score_hist, cfg: Optional[dict] = None) -> dict:
        cfg = cfg if cfg is not None else self.ng_cfg
        passed, failed, unevaluable = [], [], []

        score = row.get("score")
        breadth = row.get("breadth")
        volume_share = row.get("volume_share")
        relative_strength_pct = row.get("relative_strength")
        top1_conc = row.get("top1_concentration")
        up_stock_count = row.get("up_stock_count")
        overheat_risk = row.get("overheat_risk")

        # Rule 1: today's score >= min_score
        if pd.isna(score):
            unevaluable.append("rule1: 今日族群總分不可用")
        elif score >= cfg["min_score"]:
            passed.append(f"rule1: 今日總分{score:.1f}達門檻{cfg['min_score']}")
        else:
            failed.append(f"rule1: 今日總分{score:.1f}未達門檻{cfg['min_score']}")

        # Rule 2: prev score < prev_score_max, OR first breakout to >=min_score in
        # the last `score_breakout_days` days (score_hist, if provided).
        prev_score = prev.get("score") if prev else None
        rule2_pass = None
        if prev_score is not None and pd.notna(prev_score):
            if prev_score < cfg["prev_score_max"]:
                rule2_pass = True
                passed.append(f"rule2: 前一日總分{prev_score:.1f}低於{cfg['prev_score_max']}(由潛伏轉強)")
            elif score_hist:
                recent = [s for s in score_hist if pd.notna(s)]
                first_breakout = bool(recent) and all(s < cfg["min_score"] for s in recent) and pd.notna(score) and score >= cfg["min_score"]
                if first_breakout:
                    rule2_pass = True
                    passed.append(f"rule2: 近{cfg['score_breakout_days']}日首次突破{cfg['min_score']}分")
                else:
                    rule2_pass = False
                    failed.append(f"rule2: 前一日總分{prev_score:.1f}未低於{cfg['prev_score_max']}，且非近{cfg['score_breakout_days']}日首次突破")
            else:
                rule2_pass = False
                failed.append(f"rule2: 前一日總分{prev_score:.1f}未低於{cfg['prev_score_max']}(無近5日歷史可判斷是否首次突破)")
        else:
            unevaluable.append("rule2: 缺前一日分數，無法判斷是否由潛伏轉強")

        # Rule 3: top-100 membership count grew by >= min_rank100_change vs prior day
        if top100_count is not None and prev_top100_count is not None:
            delta = top100_count - prev_top100_count
            if delta >= cfg["min_rank100_change"]:
                passed.append(f"rule3: 前100名家數增加{delta}檔達門檻{cfg['min_rank100_change']}")
            else:
                failed.append(f"rule3: 前100名家數變化{delta}檔未達門檻{cfg['min_rank100_change']}")
        else:
            unevaluable.append("rule3: 缺個股排名資料，無法計算前100名家數變化")

        # Rule 4: volume_share growth vs prior day >= min_volume_growth_pct
        prev_volume_share = prev.get("volume_share") if prev else None
        if (prev is not None and prev_volume_share is not None and pd.notna(prev_volume_share)
                and prev_volume_share > 0 and pd.notna(volume_share)):
            growth = (volume_share - prev_volume_share) / prev_volume_share
            if growth >= cfg["min_volume_growth_pct"]:
                passed.append(f"rule4: 成交額占比成長{growth:.1%}達門檻{cfg['min_volume_growth_pct']:.0%}")
            else:
                failed.append(f"rule4: 成交額占比成長{growth:.1%}未達門檻{cfg['min_volume_growth_pct']:.0%}")
        else:
            unevaluable.append("rule4: 缺前一日成交額占比，無法計算成長率")

        # Rule 5: sector median return exceeds market median by >= min_excess_return_pct
        # (relative_strength is already median_sector_return - median_market_return,
        # expressed as a decimal fraction; threshold is in percentage points).
        if pd.isna(relative_strength_pct):
            unevaluable.append("rule5: 缺相對強度資料")
        elif relative_strength_pct * 100 >= cfg["min_excess_return_pct"]:
            passed.append(f"rule5: 相對強度{relative_strength_pct*100:.2f}pp達門檻{cfg['min_excess_return_pct']}pp")
        else:
            failed.append(f"rule5: 相對強度{relative_strength_pct*100:.2f}pp未達門檻{cfg['min_excess_return_pct']}pp")

        # Rule 6: at least min_top50_count stocks from this sector are in the market
        # top 50 by daily return rank. This rule doubles as part of the UAT-04
        # anti-single-stock guard (see also up_stock_count check below).
        if top50_count is None:
            unevaluable.append("rule6: 缺個股排名資料，無法計算前50名家數")
        elif top50_count >= cfg["min_top50_count"]:
            passed.append(f"rule6: 前50名內有{top50_count}檔達門檻{cfg['min_top50_count']}")
        else:
            failed.append(f"rule6: 前50名內僅{top50_count}檔未達門檻{cfg['min_top50_count']}")

        # Rule 7: single-largest stock's turnover share of the sector must be <= max_top1_volume_pct
        if pd.isna(top1_conc):
            unevaluable.append("rule7: 缺個股集中度資料")
        elif top1_conc <= cfg["max_top1_volume_pct"]:
            passed.append(f"rule7: 龍頭股占比{top1_conc:.1%}未超過門檻{cfg['max_top1_volume_pct']:.0%}")
        else:
            failed.append(f"rule7: 龍頭股占比{top1_conc:.1%}超過門檻{cfg['max_top1_volume_pct']:.0%}(過度集中)")

        # Rule 8: not in extreme overheat for `max_overheat_days` consecutive days.
        # Uses overheat_risk >= 90 as the "extreme overheat" bar (consistent with the
        # 0-100 overheat_risk scale; PLACEHOLDER - UNCALIBRATED, no separate config key
        # yet since only a single day of overheat_risk is reliably available pre-M5).
        EXTREME_OVERHEAT_BAR = 90
        if pd.isna(overheat_risk):
            unevaluable.append("rule8: 缺過熱風險資料")
        elif overheat_risk < EXTREME_OVERHEAT_BAR:
            passed.append(f"rule8: 過熱風險{overheat_risk:.1f}未達極端過熱門檻{EXTREME_OVERHEAT_BAR}")
        else:
            failed.append(f"rule8: 過熱風險{overheat_risk:.1f}達極端過熱門檻{EXTREME_OVERHEAT_BAR}")

        # Rule 9: pipeline data quality score >= min_data_quality_score
        if dq_score is None:
            unevaluable.append("rule9: 缺資料品質分數")
        elif dq_score >= cfg["min_data_quality_score"]:
            passed.append(f"rule9: 資料品質{dq_score:.1f}達門檻{cfg['min_data_quality_score']}")
        else:
            failed.append(f"rule9: 資料品質{dq_score:.1f}未達門檻{cfg['min_data_quality_score']}")

        # Rule 10: industry mapping coverage >= min_mapping_coverage_pct
        if mapping_coverage_pct is None:
            unevaluable.append("rule10: 缺產業映射覆蓋率")
        elif mapping_coverage_pct >= cfg["min_mapping_coverage_pct"]:
            passed.append(f"rule10: 映射覆蓋率{mapping_coverage_pct:.1%}達門檻{cfg['min_mapping_coverage_pct']:.0%}")
        else:
            failed.append(f"rule10: 映射覆蓋率{mapping_coverage_pct:.1%}未達門檻{cfg['min_mapping_coverage_pct']:.0%}(族群訊號可信度嚴重降級)")

        # UAT-04 hard gate: a sector cannot be certified new-gainer on a single stock's
        # move. Requires >=2 distinct up-moving stocks in the sector regardless of how
        # the 10 numbered conditions above scored.
        single_stock_spike = (pd.notna(up_stock_count) and up_stock_count < MIN_UP_STOCKS_FOR_SECTOR_SIGNAL)

        n_failed = len(failed)
        grade, reason = self._grade_new_gainer(
            passed, failed, unevaluable, n_failed, single_stock_spike, up_stock_count, cfg)

        confidence = "FULL"
        if unevaluable:
            confidence = "DEGRADED" if len(unevaluable) <= 2 else "LOW"

        invalidation = self._new_gainer_invalidation_text(row, cfg)

        return {
            "grade": grade, "reason": reason,
            "passed": "; ".join(passed) if passed else "(無)",
            "failed": "; ".join(failed) if failed else "(無)",
            "unevaluable": "; ".join(unevaluable) if unevaluable else "(無)",
            "invalidation": invalidation,
            "confidence": confidence,
        }

    @staticmethod
    def _rule_numbers(conditions) -> set:
        """Extract rule IDs from the persisted ``ruleN: ...`` condition strings."""
        rule_numbers = set()
        for condition in conditions or []:
            prefix = str(condition).split(":", 1)[0].strip()
            if prefix.startswith("rule") and prefix[4:].isdigit():
                rule_numbers.add(int(prefix[4:]))
        return rule_numbers

    def _grade_new_gainer(self, passed, failed, unevaluable, n_failed,
                          single_stock_spike, up_stock_count,
                          cfg: Optional[dict] = None) -> Tuple[str, str]:
        """Apply the selectivity policy after all ten rules are evaluated.

        Safety/data rules are vetoes for sector-level A/B grades.  C is deliberately
        narrower than the historical ``if passed`` fallback: it needs a breakout
        trigger plus evidence of an individual top-50 move (rule 6), or the explicit
        UAT-04 single-stock cap with at least one core condition passed.  Unevaluable
        conditions never enter any pass count.
        """
        cfg = cfg if cfg is not None else self.ng_cfg
        passed_rules = self._rule_numbers(passed)
        failed_rules = self._rule_numbers(failed)
        unevaluable_rules = self._rule_numbers(unevaluable)

        core_passed = passed_rules & NEW_GAINER_CORE_RULES
        breadth_core_passed = passed_rules & NEW_GAINER_BREADTH_CORE_RULES
        veto_not_confirmed = NEW_GAINER_VETO_RULES & (failed_rules | unevaluable_rules)
        trigger_passed = NEW_GAINER_TRIGGER_RULE in passed_rules
        min_core_for_b = cfg.get("min_core_passed_for_b", 3)
        min_breadth_for_b = cfg.get("min_breadth_core_passed_for_b", 1)

        # UAT-04 remains a hard cap.  It is still allowed to report a C-level
        # individual event, but only when a real trigger and core evidence exist.
        if single_stock_spike:
            if trigger_passed and core_passed:
                count = int(up_stock_count) if pd.notna(up_stock_count) else "單一"
                return GRADE_C, f"僅{count}檔個股帶動，不構成族群性新起漲(UAT-04)"
            return GRADE_NONE, "資料不足或結構不健康，且僅單一個股上漲不構成族群訊號"

        # A is fully evaluated and fully passed.  The explicit unevaluable check
        # prevents a cold-start/missing-data row from becoming an A by omission.
        if (trigger_passed and not failed_rules and not unevaluable_rules
                and core_passed == NEW_GAINER_CORE_RULES):
            return GRADE_A, "十項條件全數通過，族群性新起漲成立"

        # B requires a minimum amount of core evidence, including breadth, and every
        # veto must be positively confirmed.  Missing core evidence cannot be used as
        # a pass; missing veto evidence is fail-closed and blocks B.
        if (trigger_passed
                and len(core_passed) >= min_core_for_b
                and len(breadth_core_passed) >= min_breadth_for_b
                and not veto_not_confirmed
                and n_failed <= cfg.get("max_conditions_failed_for_b", 4)):
            return GRADE_B, (
                f"核心條件通過{len(core_passed)}項(含廣度)，否決條件均通過，"
                f"尚有{n_failed}項一般條件待確認"
            )

        # C is an individual-event label, not a generic fallback.  A top-50 hit is
        # the observable individual-strength evidence; it must still have the new-
        # gainer trigger and remain below the B core threshold.
        if (trigger_passed and NEW_GAINER_INDIVIDUAL_RULE in passed_rules
                and len(core_passed) < min_core_for_b):
            return GRADE_C, (
                f"個股強度(rule 6)已出現，但族群核心條件僅通過{len(core_passed)}項，"
                "未構成族群性新起漲"
            )

        return GRADE_NONE, "核心條件或否決條件未達要求，無法判定新起漲"

    def _new_gainer_invalidation_text(self, row, cfg) -> str:
        return (
            f"失效條件：族群總分回落至{cfg['prev_score_max']}以下，或上漲廣度收縮、"
            f"或龍頭股成交占比超過{cfg['max_top1_volume_pct']:.0%}造成結構過度集中，"
            f"或連續{cfg['max_overheat_days']}日觸發極端過熱，任一項出現即應視訊號失效。"
        )

    # ------------------------------------------------------------------
    # Continued Momentum (續漲, SPEC Chapter 15)
    # ------------------------------------------------------------------
    def _evaluate_continued_momentum(self, row, prev, top100_count, prev_top100_count, dq_score,
                                      cfg: Optional[dict] = None) -> dict:
        cfg = cfg if cfg is not None else self.cm_cfg
        passed, failed, unevaluable = [], [], []

        score = row.get("score")
        volume_share = row.get("volume_share")
        relative_strength_pct = row.get("relative_strength")
        overheat_risk = row.get("overheat_risk")
        inst_flow_ratio = row.get("inst_flow_ratio")

        prev_score = prev.get("score") if prev else None

        # Rule 1: score >= min_score for >= min_score_days consecutive days (today + prev)
        if prev_score is not None and pd.notna(prev_score) and pd.notna(score):
            if score >= cfg["min_score"] and prev_score >= cfg["min_score"]:
                passed.append(f"rule1: 連續{cfg['min_score_days']}日總分達門檻{cfg['min_score']}")
            else:
                failed.append(f"rule1: 今日{score:.1f}/前一日{prev_score:.1f}未能連續達門檻{cfg['min_score']}")
        else:
            unevaluable.append("rule1: 缺前一日分數，無法確認連續達標")

        # Rule 2: volume_share maintained or increasing vs prior day
        prev_volume_share = prev.get("volume_share") if prev else None
        if prev_volume_share is not None and pd.notna(prev_volume_share) and pd.notna(volume_share):
            if volume_share >= prev_volume_share:
                passed.append(f"rule2: 成交額占比維持或增加({prev_volume_share:.1%}->{volume_share:.1%})")
            else:
                failed.append(f"rule2: 成交額占比下滑({prev_volume_share:.1%}->{volume_share:.1%})")
        else:
            unevaluable.append("rule2: 缺前一日成交額占比")

        # Rule 3: top-100 membership count has not fallen more than max_rank100_drop_pct
        if top100_count is not None and prev_top100_count is not None and prev_top100_count > 0:
            drop_pct = (prev_top100_count - top100_count) / prev_top100_count
            if drop_pct <= cfg["max_rank100_drop_pct"]:
                passed.append(f"rule3: 前100名家數降幅{drop_pct:.1%}未超過門檻{cfg['max_rank100_drop_pct']:.0%}")
            else:
                failed.append(f"rule3: 前100名家數降幅{drop_pct:.1%}超過門檻{cfg['max_rank100_drop_pct']:.0%}")
        else:
            unevaluable.append("rule3: 缺個股排名資料，無法計算前100名家數變化")

        # Rule 4: sector median return continues to beat market median
        if pd.isna(relative_strength_pct):
            unevaluable.append("rule4: 缺相對強度資料")
        elif relative_strength_pct * 100 >= cfg["min_excess_return_pct"]:
            passed.append(f"rule4: 相對強度{relative_strength_pct*100:.2f}pp持續優於大盤")
        else:
            failed.append(f"rule4: 相對強度{relative_strength_pct*100:.2f}pp未優於大盤")

        # Rule 7 (numbering follows SPEC Chapter 15 list; rules 5/6 -- leader handoff,
        # no high-volume-no-follow-through -- require per-stock leadership-continuity
        # history not yet wired into this pipeline stage, so they are marked
        # unevaluable rather than assumed to pass):
        unevaluable.append("rule5: 龍頭整理時是否有次龍頭接棒，尚無個股接棒資料可判斷")
        unevaluable.append("rule6: 高檔爆量不漲偵測，尚無日內量價結構資料可判斷")

        if pd.isna(overheat_risk):
            unevaluable.append("rule7: 缺過熱風險資料")
        elif overheat_risk < cfg["max_overheat_risk"]:
            passed.append(f"rule7: 過熱風險{overheat_risk:.1f}低於門檻{cfg['max_overheat_risk']}")
        else:
            failed.append(f"rule7: 過熱風險{overheat_risk:.1f}達門檻{cfg['max_overheat_risk']}，續漲條件不成立")

        # Rule 8: institutions have not flipped from sustained buying to significant selling
        if pd.isna(inst_flow_ratio):
            unevaluable.append("rule8: 缺法人籌碼資料")
        elif inst_flow_ratio >= 0:
            passed.append(f"rule8: 法人籌碼比率{inst_flow_ratio:.3f}未轉為顯著賣超")
        else:
            failed.append(f"rule8: 法人籌碼比率{inst_flow_ratio:.3f}為淨賣超")

        # Rule 9: data quality sufficient to support the call
        if dq_score is None:
            unevaluable.append("rule9: 缺資料品質分數")
        elif dq_score >= cfg["min_data_quality_score"]:
            passed.append(f"rule9: 資料品質{dq_score:.1f}足以支援判斷")
        else:
            failed.append(f"rule9: 資料品質{dq_score:.1f}不足以支援續漲判斷")

        n_failed = len(failed)
        continued_core_passed = self._rule_numbers(passed) & CONTINUED_CORE_RULES
        if n_failed == 0 and continued_core_passed == CONTINUED_CORE_RULES:
            grade = GRADE_CONTINUED
            reason = "資金結構與強度維持穩定上揚，未見明確破壞跡象"
        else:
            grade = GRADE_NO_SIGNAL
            reason = f"續漲條件有{n_failed}項未通過，未認定為續漲訊號"

        confidence = "FULL"
        if unevaluable:
            confidence = "DEGRADED" if len(unevaluable) <= 2 else "LOW"

        invalidation = (
            f"失效條件：族群總分跌破{cfg['min_score']}、成交額占比顯著下滑、"
            f"過熱風險達{cfg['max_overheat_risk']}以上、或法人由連續買超轉為顯著賣超，"
            "任一項出現即應視續漲訊號失效。"
        )

        return {
            "grade": grade, "reason": reason,
            "passed": "; ".join(passed) if passed else "(無)",
            "failed": "; ".join(failed) if failed else "(無)",
            "unevaluable": "; ".join(unevaluable) if unevaluable else "(無)",
            "invalidation": invalidation,
            "confidence": confidence,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _compute_sector_top_counts(self,
                                    df_stock_features: Optional[pd.DataFrame],
                                    df_stock_features_prev: Optional[pd.DataFrame] = None
                                    ) -> Dict[str, Tuple[Optional[int], Optional[int], Optional[int]]]:
        """
        Returns {sector_name: (top50_count, top100_count, prev_top100_count)} computed
        from `current_rank` on the stock-features frames. Today's counts come from
        `df_stock_features`; the prior-day top100 count (used only for day-over-day
        deltas in rule 3) comes from `df_stock_features_prev`, itself just today's
        same computation applied to the previous day's already-persisted snapshot --
        never a forward-looking value.
        """
        def _counts_for(df: Optional[pd.DataFrame]) -> Dict[str, Tuple[int, int]]:
            out: Dict[str, Tuple[int, int]] = {}
            if df is None or df.empty or "current_rank" not in df.columns or "primary_sector" not in df.columns:
                return out
            for sector_name, group in df.groupby("primary_sector"):
                if sector_name in ("待分類", "未分類"):
                    continue
                out[sector_name] = (int((group["current_rank"] <= 50).sum()), int((group["current_rank"] <= 100).sum()))
            return out

        today_counts = _counts_for(df_stock_features)
        prev_counts = _counts_for(df_stock_features_prev)

        result: Dict[str, Tuple[Optional[int], Optional[int], Optional[int]]] = {}
        for sector_name, (top50, top100) in today_counts.items():
            prev_top100 = prev_counts.get(sector_name, (None, None))[1]
            result[sector_name] = (top50, top100, prev_top100)
        return result
