# Taiwan Moneyflow Rotation System - Signal and Tag Definitions

This document defines the mathematical logic and statistical guidelines for classifying the outcome of signals (Success/Failure tags) and the comparative benchmarks required for Research Ready validation.

## 1. Signal Categories and Entry Rules

We track two main classes of rotation signals. Both assume signals are generated at the market close of day \(T\), and execution occurs at the open of day \(T+1\).

*   **New Gainer (新起漲) Signal**: Triggered when a sector scores high (e.g. \(\ge 70\) points) after a period of dormancy (e.g. score was \(< 55\) on day \(T-1\) or it's the first breakout to \(\ge 70\) in the last 5 trading days).
*   **Continued Momentum (續漲) Signal**: Triggered when a sector remains strong and healthy (e.g. score remains \(\ge 65\) for two consecutive days without high-volume distribution or extreme overheat).

---

## 2. Outcome Labeling (Tagging) for Event Studies

To run backtests and evaluate expectation scores, every signal generated at day \(T\) must be evaluated against the forward post-signal window. Let:
- \(R_{sector, K}\) be the median return of the active sector's component stocks from the open of \(T+1\) to the close of \(T+K\) trading days.
- \(R_{market, K}\) be the return of the benchmark index (TAIEX Weighted Index) over the same period.
- \(AR_{sector, K} = R_{sector, K} - R_{market, K}\) be the cumulative sector excess return (alpha).

### 2.1 New Gainer (新起漲) Success/Failure Label
*   **Success**:
    \[
    AR_{sector, 10} > +3.0\%
    \]
*   **Failure**:
    \[
    AR_{sector, 10} \le +3.0\%
    \]
    *   *Minor Failure (小幅失效)*: \(0.0\% \ge AR_{sector, 10} \ge -3.0\%\)
    *   *Reversal (反轉)*: \(AR_{sector, 10} < -3.0\%\)

### 2.2 Continued Momentum (續漲) Success/Failure Label
*   **Success**:
    \[
    AR_{sector, 5} > 0.0\% \quad \text{AND} \quad \text{No "Fading (退潮)" status triggered within } T+1 \text{ to } T+5.
    \]
*   **Failure**:
    *   \(AR_{sector, 5} \le 0.0\%\) OR "Fading (退潮)" lifecycle is triggered in the window.

*Note: The thresholds above are initial uncalibrated parameters (PLACEHOLDER - UNCALIBRATED) and will be fine-tuned during the Milestone 5 optimization phase, but an explicit definition of success must exist at all times.*

---

## 3. Benchmarks (對照基準)

To prevent reporting "false alpha" from simple market momentum, the system implements two benchmark algorithms. All signal returns must be statistically compared against these baselines:

### 3.1 Momentum Extension Baseline (動能延續基準)
*   **Definition**: A simple heuristic strategy that buys the strongest sector from day \(T-1\) at day \(T\) open, and holds it for \(K\) days (for \(K \in \{1, 3, 5, 10, 20\}\)).
*   **Role**: Our New Gainer and Continued Momentum signals must show statistically significant excess returns *above* this momentum baseline to prove they add incremental predictive value.

### 3.2 Random Sector Bootstrap Baseline (隨機族群基準)
*   **Definition**: A random baseline built by sampling random sectors on day \(T\) and holding them for \(K\) days. By running bootstrap simulations \(N = 10,000\) times, we generate empirical distribution tables and confidence intervals of random sector holding returns.
*   **Role**: Used to verify if the signal's returns are not simply due to luck or generic market-wide beta.

---

## 3.5 Milestone 3: Signal Grading, 10/9-Condition Checklists, and Invalidation Rules

`src/signal_detector.py` (Milestone 3) implements the New Gainer 10-condition checklist
(SPEC Chapter 14) and Continued Momentum condition set (SPEC Chapter 15) as explicit,
per-condition pass/fail/unevaluable evaluators, never a single opaque score threshold.
Every sector row emitted by `SignalDetector.detect_signals` carries:

- `signal_type`: one of `A級新起漲` / `B級早期點火` / `C級個股事件` / `無效` (new-gainer
  track) or `續漲訊號` / `無訊號` (continued-momentum track).
- `conditions_passed` / `conditions_failed` / `conditions_unevaluable`: parallel
  "ruleN: description" strings. A condition that cannot be computed (missing upstream
  data) is placed in `conditions_unevaluable`, **never** silently counted as passed.
- `invalidation_condition`: the concrete condition(s) under which the signal should be
  considered void (SPEC Chapter 21 "失效條件" requirement).
- `signal_data_confidence`: FULL / DEGRADED / LOW, driven by how many conditions were
  unevaluable (0 -> FULL, 1-2 -> DEGRADED, 3+ -> LOW).

### 3.5.1 New Gainer (新起漲) 10-Condition Checklist (SPEC Chapter 14)

All thresholds are `config/default.yaml` keys under `new_gainer.*`. Most remain
marked `# PLACEHOLDER - UNCALIBRATED` (SPEC_ADDENDUM B-1). **Milestone 9**: rule 1
(`min_score`) and rule 2 (`prev_score_max`) are now `# CALIBRATED (n=28 trading days,
2026-04-20~2026-07-17) - PRELIMINARY, small sample` -- when `SignalDetector` is
constructed with `use_calibrated_thresholds=True`, these two are per-sector rolling
quantiles of that sector's own strictly-prior score history
(`src/threshold_calibration.py`), not the fixed numbers below (which remain the
fallback for a sector without enough history yet). See
`docs/Milestone_9_Calibration_Backtest_Report.md` for the full method and its
small-sample disclosure.

| Rule | Condition | Config key |
| --- | --- | --- |
| 1 | 今日族群總分 >= `min_score` (70, CALIBRATED fallback n=28) | `new_gainer.min_score` |
| 2 | 前一日分數 < `prev_score_max` (55, CALIBRATED fallback n=28)，或近 `score_breakout_days` (5) 日首次突破 `min_score` | `new_gainer.prev_score_max`, `score_breakout_days` |
| 3 | 前100名家數較前一日增加 >= `min_rank100_change` (3) | `new_gainer.min_rank100_change` |
| 4 | 成交額占比較前一日成長 >= `min_volume_growth_pct` (50%) | `new_gainer.min_volume_growth_pct` |
| 5 | 族群中位數報酬超過大盤中位數 >= `min_excess_return_pct` (2.0pp) | `new_gainer.min_excess_return_pct` |
| 6 | 族群內至少 `min_top50_count` (2) 檔個股進入全市場前50名 | `new_gainer.min_top50_count` |
| 7 | 龍頭股占族群成交額 <= `max_top1_volume_pct` (70%) | `new_gainer.max_top1_volume_pct` |
| 8 | 未連續 `max_overheat_days` (3) 日處於極端過熱(overheat_risk>=90) | `new_gainer.max_overheat_days` |
| 9 | 資料品質分數 >= `min_data_quality_score` (85) | `new_gainer.min_data_quality_score` |
| 10 | 產業映射覆蓋率 >= `min_mapping_coverage_pct` (80%) | `new_gainer.min_mapping_coverage_pct` |

Grading (Milestone 10 selectivity policy): rules 1/3/4/5/6 are core evidence, rule 2
is an explicit new-gainer trigger, and rules 7/8/9/10 are safety/data vetoes. **A**
requires the trigger plus all ten conditions to be positively evaluated and passed.
**B** requires the trigger, at least `min_core_passed_for_b` (design default 3) core
rules including at least one breadth rule (3 or 6), no failed/unevaluable veto, and
no more than `max_conditions_failed_for_b` (4) ordinary failures. **C** is no longer
the generic "any rule passed" fallback: it requires the trigger plus rule-6 individual
strength evidence while remaining below the B core minimum, or the explicit UAT-04
single-stock cap with at least one core rule passed. Otherwise the result is **無訊號**
(or **無效** only where a caller explicitly uses that legacy label).

The new core-count and breadth-count values are **PLACEHOLDER - UNCALIBRATED design
defaults**, not optimized from forward returns. An unevaluable rule never contributes
to a pass count; an unevaluable veto blocks A/B fail-closed.

**UAT-04 hard gate** (SPEC_ADDENDUM acceptance test, independent of the 10 numbered
conditions): a sector with fewer than 2 distinct up-moving stocks (`up_stock_count < 2`)
can **never** be graded A or B, regardless of how well the numbered conditions score.
It may be reported as C only when the new-gainer trigger and at least one core rule
also pass; otherwise it is 無訊號. This prevents a single stock's move from being
reported as a "族群性" (sector-wide) new-gainer event.

**Invalidation condition** (attached to every A/B/C-graded row): the signal should be
considered void if the sector score falls back below `prev_score_max`, breadth
contracts, the top-1 stock's turnover share exceeds `max_top1_volume_pct`, or the
sector triggers extreme overheat for `max_overheat_days` consecutive days.

### 3.5.2 Continued Momentum (續漲) Condition Checklist (SPEC Chapter 15)

| Rule | Condition | Config key |
| --- | --- | --- |
| 1 | 族群分數連續 `min_score_days` (2) 日 >= `min_score` (65, CALIBRATED fallback n=28, PRELIMINARY) | `continued_momentum.min_score_days`, `min_score` |
| 2 | 成交額占比維持或繼續增加 | `continued_momentum.min_volume_share_maintained` |
| 3 | 前100名家數降幅未超過 `max_rank100_drop_pct` (30%) | `continued_momentum.max_rank100_drop_pct` |
| 4 | 族群中位數報酬持續優於大盤 (>= `min_excess_return_pct`, 0.0pp) | `continued_momentum.min_excess_return_pct` |
| 5 | 龍頭整理時是否有次龍頭接棒 | *not yet wired -- always `conditions_unevaluable` (no per-stock leadership-continuity history in the pipeline yet)* |
| 6 | 無高檔爆量不漲 | *not yet wired -- always `conditions_unevaluable` (no intraday tick-level volume/price structure available)* |
| 7 | 過熱風險 < `max_overheat_risk` (75) | `continued_momentum.max_overheat_risk` |
| 8 | 法人未由連續買超轉為顯著賣超 (inst_flow_ratio >= 0) | *derived from `inst_flow_ratio`; no separate config key* |
| 9 | 資料品質分數 >= `min_data_quality_score` (70) | `continued_momentum.min_data_quality_score` |

Grading (Milestone 10 selectivity policy): `續漲訊號` still allows the deliberately
unevaluable rules 5/6, but rules 1 (two-day score) and 4 (relative strength) are
continuation core rules and must both be explicitly passed. Any failed condition, or
an unevaluable core rule, yields `無訊號`.

**Invalidation condition**: the signal should be considered void if the sector score
drops below `min_score`, volume share meaningfully declines, overheat risk reaches
`max_overheat_risk`, or institutions flip from sustained buying to significant selling.

### 3.5.3 Track Precedence

A sector is evaluated against both tracks independently every run. If it qualifies for
an A/B/C new-gainer grade, that takes precedence in the report (a fresh ignition event
is the system's primary purpose). Otherwise, if it qualifies for 續漲訊號, that is
reported. Otherwise 無訊號.

---

## 4. Backtest Rule Amendments for Taiwan Stock Market

The simulator must strictly respect three unique market constraints:

1.  **Limit-Up Lockout (漲停鎖死)**:
    - On day \(T+1\), if the opening price is equal to the limit-up price (漲停價) and the daily volume is extremely thin (meaning no sellers), the stock is considered *non-purchasable*.
    - The simulation must handle this by either **excluding the event** or **postponing entry to day \(T+2\)**. Both metrics must be reported for comparison.
2.  **Caution / Disposition Stocks (注意/處置股)**:
    - Stocks labeled under disposition (處置) have transactional constraints (e.g. 5-minute or 20-minute matching intervals).
    - The model will tag signals containing active disposition stocks and apply a **weight penalty** (e.g., reducing their allocation weight by 50%).
3.  **Ex-Dividend Adjustments (除權息)**:
    - Ex-dividend drops (除權息缺口) must be handled by using the fully adjusted close prices (`adjusted_close`) for return computations. High-focus unit tests will assert price integrity for July-September dividend seasons.
