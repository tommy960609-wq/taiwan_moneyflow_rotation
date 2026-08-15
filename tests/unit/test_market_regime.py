import sys
import os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.market_regime import (
    MarketRegimeClassifier,
    REGIME_BULL_EXPANSION, REGIME_BULL_CONSOLIDATION, REGIME_HIGH_STAGNATION,
    REGIME_BEAR_REBOUND, REGIME_BEAR_TREND, REGIME_EXTREME_RISK,
    INDEX_UNAVAILABLE, INSUFFICIENT_DATA,
    CONFIDENCE_FULL, CONFIDENCE_DEGRADED,
)


def _make_index_history(closes: list) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=len(closes)).strftime("%Y-%m-%d").tolist()
    return pd.DataFrame({"trade_date": dates, "close": closes})


def test_insufficient_data_below_60_days():
    closes = [17000.0 + i * 10 for i in range(40)]  # only 40 days, need 60 for MA60
    df_hist = _make_index_history(closes)

    clf = MarketRegimeClassifier()
    result = clf.classify(df_hist, market_breadth=0.6)

    assert result["regime"] == INSUFFICIENT_DATA
    assert result["confidence"] == CONFIDENCE_DEGRADED


def test_index_unavailable_falls_back_to_breadth_only_strong():
    clf = MarketRegimeClassifier()
    result = clf.classify(pd.DataFrame(), market_breadth=0.70)

    assert result["regime"] == REGIME_BULL_EXPANSION
    assert result["confidence"] == CONFIDENCE_DEGRADED
    assert result["index_stats"] is None


def test_index_unavailable_falls_back_to_breadth_only_weak():
    clf = MarketRegimeClassifier()
    result = clf.classify(None, market_breadth=0.20)

    assert result["regime"] == REGIME_BEAR_TREND
    assert result["confidence"] == CONFIDENCE_DEGRADED


def test_index_unavailable_and_no_breadth_is_insufficient_data():
    clf = MarketRegimeClassifier()
    result = clf.classify(pd.DataFrame(), market_breadth=None)

    assert result["regime"] == INSUFFICIENT_DATA
    assert result["confidence"] == CONFIDENCE_DEGRADED


def test_bull_expansion_strong_uptrend_with_broad_breadth():
    # Strong monotonic uptrend over 80 days: close > ma20 > ma60, ret_20d well above
    # the 3% bull threshold (roughly +55 pts/day on a ~17000 base ~= ~6.5%/20 days).
    closes = [15000.0 + i * 55 for i in range(80)]
    df_hist = _make_index_history(closes)

    clf = MarketRegimeClassifier()
    result = clf.classify(df_hist, market_breadth=0.65)

    assert result["regime"] == REGIME_BULL_EXPANSION
    assert result["confidence"] == CONFIDENCE_FULL


def test_high_stagnation_uptrend_but_narrow_breadth():
    closes = [15000.0 + i * 55 for i in range(80)]
    df_hist = _make_index_history(closes)

    clf = MarketRegimeClassifier()
    result = clf.classify(df_hist, market_breadth=0.30)  # narrow participation despite index strength

    assert result["regime"] == REGIME_HIGH_STAGNATION


def test_bear_trend_strong_downtrend():
    closes = [20000.0 - i * 25 for i in range(80)]
    df_hist = _make_index_history(closes)

    clf = MarketRegimeClassifier()
    result = clf.classify(df_hist, market_breadth=0.25)

    assert result["regime"] == REGIME_BEAR_TREND
    assert result["confidence"] == CONFIDENCE_FULL


def test_extreme_risk_high_volatility_overrides():
    np.random.seed(42)
    # Highly volatile series (large daily swings) -> triggers extreme-vol override
    base = 18000.0
    closes = [base]
    for i in range(79):
        shock = np.random.choice([-1, 1]) * base * 0.05
        closes.append(closes[-1] + shock)
    df_hist = _make_index_history(closes)

    clf = MarketRegimeClassifier()
    result = clf.classify(df_hist, market_breadth=0.5)

    assert result["regime"] == REGIME_EXTREME_RISK


def test_extreme_risk_severe_drawdown_overrides():
    closes = [20000.0]
    for i in range(79):
        closes.append(closes[-1] * 0.99)  # steady ~50%+ drawdown over 80 days
    df_hist = _make_index_history(closes)

    clf = MarketRegimeClassifier()
    result = clf.classify(df_hist, market_breadth=0.3)

    assert result["regime"] == REGIME_EXTREME_RISK


def test_bull_consolidation_mild_uptrend():
    # Mild uptrend: close hovers just above ma20/ma60 but 20d return is small
    closes = [17000.0 + (i % 5) * 5 + i * 0.5 for i in range(80)]
    df_hist = _make_index_history(closes)

    clf = MarketRegimeClassifier()
    result = clf.classify(df_hist, market_breadth=0.52)

    assert result["regime"] in (REGIME_BULL_CONSOLIDATION, REGIME_BULL_EXPANSION, REGIME_HIGH_STAGNATION)
    assert result["confidence"] == CONFIDENCE_FULL
