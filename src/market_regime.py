"""
Market regime classification (SPEC Chapter 18).

Six states, per SPEC:
  1. 多頭擴張 (Bull Expansion)
  2. 多頭盤整 (Bull Consolidation)   -- SPEC uses "多頭震盪"; report label in
     SPEC_ADDENDUM keeps 多頭盤整/多頭震盪 synonymous, we use the M4 task's naming.
  3. 高檔鈍化 (High-Level Stagnation) -- SPEC calls this "高檔分化"; identical concept.
  4. 空頭反彈 (Bear Rebound)
  5. 空頭趨勢 (Bear Trend)
  6. 極端風險 (Extreme Risk)

Inputs (per SPEC Ch.18): index MA20/MA60, 20-day index return, index volatility,
plus full-market breadth (% of stocks up). If index data is unavailable
(INDEX_SOURCE_UNAVAILABLE from the fetcher, or simply missing), the classifier
degrades to breadth-only classification and marks confidence DEGRADED, never
raising and never fabricating an index value (constitution 3.3 / BEHAVIOR_RULES #1).
If there isn't enough index history for MA60 (60 days) the result is
INSUFFICIENT_DATA regardless of breadth.
"""

import numpy as np
import pandas as pd
from typing import Optional


REGIME_BULL_EXPANSION = "多頭擴張"
REGIME_BULL_CONSOLIDATION = "多頭盤整"
REGIME_HIGH_STAGNATION = "高檔鈍化"
REGIME_BEAR_REBOUND = "空頭反彈"
REGIME_BEAR_TREND = "空頭趨勢"
REGIME_EXTREME_RISK = "極端風險"

INDEX_UNAVAILABLE = "INDEX_UNAVAILABLE"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

CONFIDENCE_FULL = "FULL"
CONFIDENCE_DEGRADED = "DEGRADED"


class MarketRegimeClassifier:
    """
    Classifies market regime from a chronologically-sorted index history DataFrame
    (columns: trade_date, close [+ optional volatility columns]) plus a same-day
    market-breadth ratio (up_stock_count / total_stock_count, in [0, 1]).

    Thresholds below are all `# PLACEHOLDER - UNCALIBRATED` (SPEC_ADDENDUM B-1):
    no Taiwan-market forward-test calibration has been done yet.
    """

    # PLACEHOLDER - UNCALIBRATED thresholds
    EXTREME_VOL_THRESHOLD = 0.03       # 20d annualized-proxy daily-return stdev
    EXTREME_RETURN_20D = -0.10         # 20-day index return below this -> extreme risk candidate
    BULL_RETURN_20D = 0.03             # 20-day index return above this -> bullish regime candidate
    BEAR_RETURN_20D = -0.03            # 20-day index return below this -> bearish regime candidate
    BREADTH_STRONG = 0.55              # market-breadth ratio above this -> broad-based strength
    BREADTH_WEAK = 0.45                # below this -> broad-based weakness
    MIN_MA60_HISTORY_DAYS = 60

    def __init__(self):
        pass

    def _compute_index_stats(self, df_index_history: pd.DataFrame) -> Optional[dict]:
        """
        Computes MA20, MA60, 20-day return, and 20-day daily-return volatility from a
        chronologically sorted index history. Returns None if fewer than
        MIN_MA60_HISTORY_DAYS rows are available (insufficient for MA60).
        """
        if df_index_history is None or df_index_history.empty:
            return None
        df = df_index_history.sort_values("trade_date").copy()
        if len(df) < self.MIN_MA60_HISTORY_DAYS:
            return None

        df["daily_return"] = df["close"].pct_change()
        ma20 = df["close"].rolling(20, min_periods=20).mean().iloc[-1]
        ma60 = df["close"].rolling(60, min_periods=60).mean().iloc[-1]
        ret_20d = df["close"].pct_change(periods=20).iloc[-1]
        vol_20d = df["daily_return"].rolling(20, min_periods=20).std().iloc[-1]
        latest_close = df["close"].iloc[-1]

        if pd.isna(ma20) or pd.isna(ma60) or pd.isna(ret_20d) or pd.isna(vol_20d):
            return None

        return {
            "close": float(latest_close),
            "ma20": float(ma20),
            "ma60": float(ma60),
            "return_20d": float(ret_20d),
            "volatility_20d": float(vol_20d),
        }

    def classify(self, df_index_history: pd.DataFrame,
                 market_breadth: Optional[float] = None) -> dict:
        """
        Returns a dict:
          {
            "regime": one of the 6 Chinese labels, or INDEX_UNAVAILABLE / INSUFFICIENT_DATA,
            "confidence": FULL / DEGRADED,
            "basis": short string explaining which inputs drove the call,
            "index_stats": the computed stats dict, or None,
            "market_breadth": the input breadth (echoed back for the report layer),
          }
        """
        stats = self._compute_index_stats(df_index_history)

        if stats is None:
            if df_index_history is None or df_index_history.empty:
                # No index data at all -- degrade to breadth-only classification.
                return self._classify_breadth_only(market_breadth, reason=INDEX_UNAVAILABLE)
            # Index data exists but insufficient rows for MA60 -> per spec, report
            # "insufficient data", not a degraded breadth-only guess, since we don't
            # yet know whether the index itself is even usable.
            return {
                "regime": INSUFFICIENT_DATA,
                "confidence": CONFIDENCE_DEGRADED,
                "basis": f"Index history has fewer than {self.MIN_MA60_HISTORY_DAYS} rows; cannot compute MA60.",
                "index_stats": None,
                "market_breadth": market_breadth,
            }

        regime = self._classify_from_stats(stats, market_breadth)
        return {
            "regime": regime,
            "confidence": CONFIDENCE_FULL,
            "basis": (
                f"close={stats['close']:.2f} ma20={stats['ma20']:.2f} ma60={stats['ma60']:.2f} "
                f"return_20d={stats['return_20d']:.2%} vol_20d={stats['volatility_20d']:.2%} "
                f"breadth={market_breadth if market_breadth is not None else 'N/A'}"
            ),
            "index_stats": stats,
            "market_breadth": market_breadth,
        }

    def _classify_breadth_only(self, market_breadth: Optional[float], reason: str) -> dict:
        if market_breadth is None or pd.isna(market_breadth):
            return {
                "regime": INSUFFICIENT_DATA,
                "confidence": CONFIDENCE_DEGRADED,
                "basis": f"{reason}; no market_breadth fallback available either.",
                "index_stats": None,
                "market_breadth": None,
            }

        if market_breadth >= self.BREADTH_STRONG:
            regime = REGIME_BULL_EXPANSION
        elif market_breadth <= self.BREADTH_WEAK:
            regime = REGIME_BEAR_TREND
        else:
            regime = REGIME_BULL_CONSOLIDATION

        return {
            "regime": regime,
            "confidence": CONFIDENCE_DEGRADED,
            "basis": f"{reason}; degraded classification uses market_breadth={market_breadth:.2%} only.",
            "index_stats": None,
            "market_breadth": market_breadth,
        }

    def _classify_from_stats(self, stats: dict, market_breadth: Optional[float]) -> str:
        ret_20d = stats["return_20d"]
        vol_20d = stats["volatility_20d"]
        close = stats["close"]
        ma20 = stats["ma20"]
        ma60 = stats["ma60"]

        breadth = market_breadth if market_breadth is not None and not pd.isna(market_breadth) else None

        # 1. Extreme risk: overrides everything else when volatility or drawdown is severe.
        if vol_20d >= self.EXTREME_VOL_THRESHOLD or ret_20d <= self.EXTREME_RETURN_20D:
            return REGIME_EXTREME_RISK

        is_uptrend = close > ma20 > ma60
        is_downtrend = close < ma20 < ma60

        if is_uptrend and ret_20d >= self.BULL_RETURN_20D:
            if breadth is not None and breadth < self.BREADTH_WEAK:
                # Price/index rising but breadth narrow -> high-level stagnation
                # (divergence between index strength and broad participation).
                return REGIME_HIGH_STAGNATION
            return REGIME_BULL_EXPANSION

        if is_uptrend and ret_20d >= 0:
            return REGIME_BULL_CONSOLIDATION

        if is_downtrend and ret_20d <= self.BEAR_RETURN_20D:
            return REGIME_BEAR_TREND

        if is_downtrend:
            return REGIME_BEAR_REBOUND if ret_20d > 0 or close > ma20 else REGIME_BEAR_TREND

        # Mixed signal (e.g. close above MA20 but below MA60, or vice versa) with a
        # positive 20d return but not a clean uptrend structure -> treat as a rebound
        # attempt within a broader downtrend if MA60 slope/level says so, else
        # consolidation.
        if close < ma60 and ret_20d > 0:
            return REGIME_BEAR_REBOUND
        if breadth is not None and breadth <= self.BREADTH_WEAK:
            return REGIME_HIGH_STAGNATION
        return REGIME_BULL_CONSOLIDATION
