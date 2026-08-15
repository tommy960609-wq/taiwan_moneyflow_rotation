import sys
import os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.signal_detector import (
    SignalDetector, GRADE_A, GRADE_B, GRADE_C, GRADE_NONE, GRADE_CONTINUED, GRADE_NO_SIGNAL,
)


def _base_sector_row(**overrides):
    row = {
        "sector_name": "TestSector",
        "score": 75.0,
        "breadth": 0.6,
        "volume_share": 0.15,
        "relative_strength": 0.03,   # +3.0pp, expressed as a decimal fraction
        "top1_concentration": 0.40,
        "up_stock_count": 5,
        "stock_count": 8,
        "overheat_risk": 30.0,
        "hhi": 0.20,
        "inst_flow_ratio": 0.02,
    }
    row.update(overrides)
    return row


def _base_prev_row(**overrides):
    row = {"sector_name": "TestSector", "score": 40.0, "volume_share": 0.08}
    row.update(overrides)
    return row


def _stock_features(sector_name, ranks):
    return pd.DataFrame([{"primary_sector": sector_name, "current_rank": r} for r in ranks])


class TestNewGainerAGrade:
    def test_all_10_conditions_pass_yields_a_grade(self):
        """
        SPEC Chapter 14: when every one of the 10 numbered conditions passes, the
        sector must be graded A (全數條件通過, 族群性新起漲成立), never B or C.
        """
        detector = SignalDetector()
        df_today = pd.DataFrame([_base_sector_row()])
        df_prev = pd.DataFrame([_base_prev_row()])
        stock_feat = _stock_features("TestSector", [5, 10, 20, 30, 40])
        stock_feat_prev = _stock_features("TestSector", [50, 60])

        out = detector.detect_signals(
            df_today, df_prev, stock_feat, stock_feat_prev,
            dq_score=95.0, mapping_coverage_pct=0.90,
        )

        assert out.iloc[0]["signal_type"] == GRADE_A
        assert out.iloc[0]["conditions_failed"] == "(無)"
        assert out.iloc[0]["signal_data_confidence"] == "FULL"
        # Invalidation condition must be a concrete, non-empty statement (SPEC Ch.21).
        assert "失效條件" in out.iloc[0]["invalidation_condition"]

    def test_a_grade_requires_uat04_multi_stock_participation(self):
        """
        Even a "perfect-looking" score profile must not earn A/B if virtually the
        whole move is attributable to a single stock (up_stock_count < 2).
        """
        detector = SignalDetector()
        row = _base_sector_row(up_stock_count=1)
        df_today = pd.DataFrame([row])
        df_prev = pd.DataFrame([_base_prev_row()])
        stock_feat = _stock_features("TestSector", [5, 10, 20, 30, 40])
        stock_feat_prev = _stock_features("TestSector", [120, 130])

        out = detector.detect_signals(
            df_today, df_prev, stock_feat, stock_feat_prev,
            dq_score=95.0, mapping_coverage_pct=0.9,
        )
        assert out.iloc[0]["signal_type"] not in (GRADE_A, GRADE_B)


class TestUAT04SingleStockSpike:
    def test_single_stock_spike_capped_at_c_not_a_or_b(self):
        """
        UAT-04 (SPEC_ADDENDUM acceptance test): a sector must not be certified as a
        "新起漲" (new gainer) sector purely because one stock spiked. Even with a
        high score/breadth/volume-share profile, up_stock_count=1 must hard-cap the
        grade at C (or 無效), never A or B.
        """
        detector = SignalDetector()
        row = _base_sector_row(
            score=85.0, breadth=0.05, volume_share=0.25, top1_concentration=0.95,
            up_stock_count=1, hhi=0.9,
        )
        df_today = pd.DataFrame([row])
        df_prev = pd.DataFrame([_base_prev_row()])

        out = detector.detect_signals(df_today, df_prev, dq_score=95.0, mapping_coverage_pct=0.9)

        assert out.iloc[0]["signal_type"] == GRADE_C
        assert "UAT-04" in out.iloc[0]["signal_reason"]

    def test_two_up_stocks_is_the_minimum_for_sector_level_signal(self):
        """Boundary check: exactly 2 up-moving stocks should NOT trigger the UAT-04 cap."""
        detector = SignalDetector()
        row = _base_sector_row(up_stock_count=2)
        df_today = pd.DataFrame([row])
        df_prev = pd.DataFrame([_base_prev_row()])
        stock_feat = _stock_features("TestSector", [5, 10, 20, 30, 40])
        stock_feat_prev = _stock_features("TestSector", [120, 130])

        out = detector.detect_signals(
            df_today, df_prev, stock_feat, stock_feat_prev,
            dq_score=95.0, mapping_coverage_pct=0.9,
        )
        assert out.iloc[0]["signal_type"] == GRADE_A


class TestDataDegradation:
    def test_missing_institutional_data_degrades_confidence_not_silently_passes(self):
        """
        When inst_flow_ratio (法人籌碼) is unavailable, whichever track's rule
        evaluates institutional flow must mark that condition unevaluable (never
        silently assumed to pass), and overall signal_data_confidence must degrade
        below FULL as a result of the missing input feeding into the grade decision.
        """
        detector = SignalDetector()
        row = _base_sector_row(score=68.0, inst_flow_ratio=np.nan)
        prev = _base_prev_row(score=66.0)
        df_today = pd.DataFrame([row])
        df_prev = pd.DataFrame([prev])

        out = detector.detect_signals(df_today, df_prev, dq_score=95.0, mapping_coverage_pct=0.9)
        assert out.iloc[0]["signal_data_confidence"] in ("DEGRADED", "LOW")
        assert out.iloc[0]["conditions_unevaluable"] != "(無)"

    def test_missing_institutional_data_marks_continued_momentum_rule8_unevaluable(self):
        """
        Directly exercises the continued-momentum evaluator (bypassing the new-gainer
        track's grade-selection precedence) to confirm rule 8 (法人未由連續買超轉成
        顯著賣超) is marked unevaluable, not silently passed, when inst_flow_ratio is
        missing.
        """
        detector = SignalDetector()
        row = _base_sector_row(inst_flow_ratio=np.nan)
        prev = _base_prev_row()
        cm_result = detector._evaluate_continued_momentum(pd.Series(row), prev, None, None, dq_score=95.0)
        assert "rule8" in cm_result["unevaluable"]
        assert "rule8" not in cm_result["passed"]

    def test_missing_data_quality_score_marks_rule9_unevaluable(self):
        """A missing dq_score must never be treated as a passing rule 9."""
        detector = SignalDetector()
        row = _base_sector_row()
        prev = _base_prev_row()
        out = detector.detect_signals(pd.DataFrame([row]), pd.DataFrame([prev]), dq_score=None, mapping_coverage_pct=0.9)
        assert "rule9" in out.iloc[0]["conditions_unevaluable"]
        assert "rule9" not in out.iloc[0]["conditions_passed"]

    def test_low_mapping_coverage_fails_rule10_and_can_prevent_a_grade(self):
        """
        Low industry-mapping coverage must fail rule 10 explicitly (SPEC Chapter 14
        rule 10, SPEC_ADDENDUM known-reality: most stocks are 待分類/unmapped) rather
        than being silently skipped or assumed to pass.
        """
        detector = SignalDetector()
        row = _base_sector_row()
        prev = _base_prev_row()
        stock_feat = _stock_features("TestSector", [5, 10, 20, 30, 40])
        out = detector.detect_signals(
            pd.DataFrame([row]), pd.DataFrame([prev]), stock_feat,
            dq_score=95.0, mapping_coverage_pct=0.05,
        )
        assert "rule10" in out.iloc[0]["conditions_failed"]
        assert out.iloc[0]["signal_type"] != GRADE_A

    def test_no_previous_day_data_degrades_but_does_not_crash(self):
        """Day-1 runs (no prior history) must not raise and must mark delta-dependent
        conditions unevaluable rather than guessing pass/fail."""
        detector = SignalDetector()
        row = _base_sector_row()
        out = detector.detect_signals(pd.DataFrame([row]), df_sectors_prev=None, dq_score=95.0, mapping_coverage_pct=0.9)
        assert not out.empty
        assert out.iloc[0]["signal_type"] in (GRADE_A, GRADE_B, GRADE_C, GRADE_NONE, GRADE_CONTINUED, GRADE_NO_SIGNAL)


class TestBGrade:
    def test_b_grade_when_a_few_conditions_unmet(self):
        """
        SPEC Chapter 14: B-grade (早期點火) sectors pass most conditions but have some
        (<= max_conditions_failed_for_b) still pending confirmation -- must never be
        reported as a confirmed new mainstream (A).
        """
        detector = SignalDetector()
        row = _base_sector_row(score=68.0, volume_share=0.07, relative_strength=-0.01)  # rule1/4/5 fail
        prev = _base_prev_row(score=66.0)   # rule2 also fails (not <55, no breakout hist)
        stock_feat = _stock_features("TestSector", [5, 10])
        out = detector.detect_signals(pd.DataFrame([row]), pd.DataFrame([prev]), stock_feat, dq_score=95.0, mapping_coverage_pct=0.9)
        # The old failure-count-only grader called this B/C.  The selectivity
        # contract now requires a real breakout trigger (rule 2), so this is no
        # signal even though several safety rules pass.
        assert out.iloc[0]["signal_type"] == GRADE_NO_SIGNAL


class TestSelectivityGrading:
    def test_plain_day_with_only_safety_rules_is_no_signal(self):
        """Safety rules must not turn a routine/low-score day into C."""
        detector = SignalDetector()
        row = _base_sector_row(score=42.0, up_stock_count=0)
        prev = _base_prev_row(score=68.0)

        out = detector.detect_signals(
            pd.DataFrame([row]), pd.DataFrame([prev]),
            dq_score=95.0, mapping_coverage_pct=0.9,
        )

        assert out.iloc[0]["signal_type"] == GRADE_NO_SIGNAL

    def test_b_grade_requires_three_core_rules_and_breadth_evidence(self):
        """B requires the design minimum of three core rules, including breadth."""
        detector = SignalDetector()
        row = _base_sector_row(volume_share=0.15)  # rule 4 will fail vs unchanged prev
        prev = _base_prev_row(score=40.0, volume_share=0.15)
        today_stocks = _stock_features("TestSector", [5, 10])
        prev_stocks = _stock_features("TestSector", [120, 130])

        out = detector.detect_signals(
            pd.DataFrame([row]), pd.DataFrame([prev]),
            today_stocks, prev_stocks, dq_score=95.0, mapping_coverage_pct=0.9,
        )

        assert out.iloc[0]["signal_type"] == GRADE_B

    def test_missing_breadth_evidence_cannot_fill_b_grade(self):
        """Unevaluable breadth rules cannot be replaced by score/strength passes."""
        detector = SignalDetector()
        row = _base_sector_row()
        prev = _base_prev_row(score=40.0)

        out = detector.detect_signals(
            pd.DataFrame([row]), pd.DataFrame([prev]),
            dq_score=95.0, mapping_coverage_pct=0.9,
        )

        assert out.iloc[0]["signal_type"] == GRADE_NO_SIGNAL
        assert "rule3" in out.iloc[0]["conditions_unevaluable"]
        assert "rule6" in out.iloc[0]["conditions_unevaluable"]

    def test_multi_stock_rule6_evidence_can_produce_c_not_b(self):
        """A real top-50 individual signal may be C when sector evidence is weak."""
        detector = SignalDetector()
        row = _base_sector_row(score=60.0, relative_strength=0.0)
        prev = _base_prev_row(score=40.0)
        today_stocks = _stock_features("TestSector", [5, 10])
        prev_stocks = _stock_features("TestSector", [5, 10])

        out = detector.detect_signals(
            pd.DataFrame([row]), pd.DataFrame([prev]),
            today_stocks, prev_stocks, dq_score=95.0, mapping_coverage_pct=0.9,
        )

        assert out.iloc[0]["signal_type"] == GRADE_C
        assert "rule6" in out.iloc[0]["conditions_passed"]

    def test_rule3_growth_without_rule6_does_not_create_individual_c(self):
        """Top-100 breadth growth alone is not the individual-event C evidence."""
        detector = SignalDetector()
        row = _base_sector_row(score=60.0, relative_strength=0.0)
        prev = _base_prev_row(score=40.0)
        today_stocks = _stock_features("TestSector", [60, 70, 80, 90])
        prev_stocks = _stock_features("TestSector", [120, 130])

        out = detector.detect_signals(
            pd.DataFrame([row]), pd.DataFrame([prev]),
            today_stocks, prev_stocks, dq_score=95.0, mapping_coverage_pct=0.9,
        )

        assert out.iloc[0]["signal_type"] == GRADE_NO_SIGNAL
        assert "rule3" in out.iloc[0]["conditions_passed"]
        assert "rule6" in out.iloc[0]["conditions_failed"]

    def test_veto_failure_blocks_a_and_b_even_with_all_core_rules(self):
        """Overheat/concentration/DQ/mapping vetoes cannot yield A or B."""
        detector = SignalDetector()
        row = _base_sector_row(overheat_risk=95.0)
        prev = _base_prev_row(score=40.0)
        today_stocks = _stock_features("TestSector", [5, 10, 20, 30, 40])
        prev_stocks = _stock_features("TestSector", [120, 130])

        out = detector.detect_signals(
            pd.DataFrame([row]), pd.DataFrame([prev]),
            today_stocks, prev_stocks, dq_score=95.0, mapping_coverage_pct=0.9,
        )

        assert out.iloc[0]["signal_type"] not in (GRADE_A, GRADE_B)
        assert "rule8" in out.iloc[0]["conditions_failed"]

    def test_continued_requires_both_core_rules_to_be_evaluable_and_pass(self):
        """A missing continuation core input must fail closed, not become continued."""
        detector = SignalDetector()
        row = _base_sector_row(score=67.0, inst_flow_ratio=0.01)
        result = detector._evaluate_continued_momentum(
            pd.Series(row), prev=None, top100_count=None, prev_top100_count=None,
            dq_score=95.0,
        )

        assert result["grade"] == GRADE_NO_SIGNAL
        assert "rule1" in result["unevaluable"]


class TestContinuedMomentum:
    def test_continued_momentum_signal_when_stable_and_no_new_gainer_conditions_met(self):
        """
        SPEC Chapter 15: a sector with score >= 65 sustained across 2 days, healthy
        volume/breadth, low overheat risk, and non-negative institutional flow should
        be graded 續漲訊號 (continued momentum) when it doesn't independently qualify
        as a fresh new-gainer ignition (score already elevated on both days).
        """
        detector = SignalDetector()
        row = _base_sector_row(score=67.0, top1_concentration=0.3, overheat_risk=20.0, inst_flow_ratio=0.01)
        prev = _base_prev_row(score=68.0, volume_share=0.15)  # score >= 65 on both days
        out = detector.detect_signals(pd.DataFrame([row]), pd.DataFrame([prev]), dq_score=95.0, mapping_coverage_pct=0.9)
        assert out.iloc[0]["signal_type"] in (GRADE_CONTINUED, GRADE_B, GRADE_C)

    def test_overheat_risk_above_threshold_fails_continued_momentum(self):
        """An overheat_risk >= max_overheat_risk must fail continued-momentum rule 7."""
        detector = SignalDetector()
        row = _base_sector_row(score=67.0, overheat_risk=90.0)
        prev = _base_prev_row(score=68.0, volume_share=0.15)
        out = detector.detect_signals(pd.DataFrame([row]), pd.DataFrame([prev]), dq_score=95.0, mapping_coverage_pct=0.9)
        assert out.iloc[0]["signal_type"] != GRADE_CONTINUED

    def test_institutional_reversal_to_selling_fails_continued_momentum(self):
        """Institutions flipping to net selling (inst_flow_ratio < 0) must fail rule 8."""
        detector = SignalDetector()
        row = _base_sector_row(score=67.0, overheat_risk=20.0, inst_flow_ratio=-0.05)
        prev = _base_prev_row(score=68.0, volume_share=0.15)
        out = detector.detect_signals(pd.DataFrame([row]), pd.DataFrame([prev]), dq_score=95.0, mapping_coverage_pct=0.9)
        assert out.iloc[0]["signal_type"] != GRADE_CONTINUED


class TestEmptyInput:
    def test_empty_dataframe_returns_empty_without_error(self):
        detector = SignalDetector()
        out = detector.detect_signals(pd.DataFrame())
        assert out.empty


class TestCalibratedThresholds:
    """
    Milestone 9 (SPEC_ADDENDUM B-1.3): SignalDetector(use_calibrated_thresholds=True,
    df_sector_history=...) must apply a per-sector rolling-quantile threshold instead
    of the fixed DEFAULT_NEW_GAINER_CONFIG/DEFAULT_CONTINUED_MOMENTUM_CONFIG numbers,
    but ONLY when explicitly opted in -- every existing caller (use_calibrated_
    thresholds defaults False) must see byte-identical behavior to before this
    milestone.
    """

    def _sector_history(self, sector_name, scores, start="2026-01-01"):
        dates = pd.date_range(start, periods=len(scores), freq="D").strftime("%Y-%m-%d")
        return pd.DataFrame({
            "sector_name": [sector_name] * len(scores),
            "trade_date": list(dates),
            "score": scores,
        })

    def test_default_off_preserves_exact_pre_m9_behavior(self):
        """Constructing SignalDetector with no calibration args must behave exactly
        like before this milestone (fixed absolute thresholds)."""
        detector_default = SignalDetector()
        detector_explicit_off = SignalDetector(use_calibrated_thresholds=False)
        row = _base_sector_row(score=68.0)  # below fixed min_score=70
        prev = _base_prev_row(score=40.0)

        out_default = detector_default.detect_signals(pd.DataFrame([row]), pd.DataFrame([prev]),
                                                        dq_score=95.0, mapping_coverage_pct=0.9)
        out_explicit = detector_explicit_off.detect_signals(pd.DataFrame([row]), pd.DataFrame([prev]),
                                                             dq_score=95.0, mapping_coverage_pct=0.9)

        assert out_default.iloc[0]["signal_type"] == out_explicit.iloc[0]["signal_type"]
        assert out_default.iloc[0]["signal_type"] != GRADE_A  # rule1 fails at fixed min_score=70

    def test_calibrated_on_with_no_history_falls_back_to_fixed_threshold(self):
        """use_calibrated_thresholds=True but df_sector_history is None/empty must
        fall back to the exact fixed-threshold behavior (never crash, never silently
        assume a threshold of 0)."""
        detector = SignalDetector(use_calibrated_thresholds=True, df_sector_history=None)
        row = _base_sector_row(score=68.0)
        prev = _base_prev_row(score=40.0)
        out = detector.detect_signals(pd.DataFrame([row]), pd.DataFrame([prev]),
                                       dq_score=95.0, mapping_coverage_pct=0.9)
        assert "rule1: 今日總分68.0未達門檻70" in out.iloc[0]["conditions_failed"]

    def test_calibrated_on_with_enough_history_lowers_bar_for_dormant_low_score_sector(self):
        """
        Reproduces the real M5c/M9 finding at unit-test scale: a sector whose score
        never exceeds ~50 in its own history should get a calibrated min_score well
        below the fixed 70, so a today-score of 55 (which would fail the fixed rule 1)
        can pass rule 1 once calibrated.
        """
        sector_name = "TestSector"
        scores = [30 + i for i in range(15)]  # 15 prior days, 30..44
        history = self._sector_history(sector_name, scores)
        eval_date = pd.date_range("2026-01-01", periods=16, freq="D")[-1].strftime("%Y-%m-%d")

        detector = SignalDetector(use_calibrated_thresholds=True, df_sector_history=history)
        row = _base_sector_row(sector_name=sector_name, score=45.0)
        row["trade_date"] = eval_date
        prev = _base_prev_row(sector_name=sector_name, score=20.0)

        out = detector.detect_signals(pd.DataFrame([row]), pd.DataFrame([prev]),
                                       dq_score=95.0, mapping_coverage_pct=0.9)

        # rule1 should now PASS (calibrated min_score ~85th pct of 30..44 is far below
        # the fixed 70, and well below today's score of 45).
        assert "rule1" in out.iloc[0]["conditions_passed"]

    def test_each_sector_gets_its_own_independently_calibrated_threshold(self):
        """Two sectors with very different score histories must receive different
        calibrated min_score values -- calibration is per-sector, never pooled market-wide
        for this function."""
        hot_scores = [70 + i for i in range(15)]     # hot sector: consistently high
        cold_scores = [20 + i for i in range(15)]    # cold sector: consistently low
        history = pd.concat([
            self._sector_history("HotSector", hot_scores),
            self._sector_history("ColdSector", cold_scores),
        ], ignore_index=True)
        eval_date = pd.date_range("2026-01-01", periods=16, freq="D")[-1].strftime("%Y-%m-%d")

        detector = SignalDetector(use_calibrated_thresholds=True, df_sector_history=history)
        hot_cfg = detector._cfg_for_sector("HotSector", eval_date, detector.ng_cfg, "new_gainer")
        cold_cfg = detector._cfg_for_sector("ColdSector", eval_date, detector.ng_cfg, "new_gainer")

        assert hot_cfg["min_score"] > cold_cfg["min_score"]
