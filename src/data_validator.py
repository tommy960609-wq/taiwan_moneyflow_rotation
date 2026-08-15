import pandas as pd
import datetime
from loguru import logger

class DataValidator:
    def __init__(self):
        pass

    def calculate_quality_score(self, 
                                df_ohlcv: pd.DataFrame, 
                                df_inst: pd.DataFrame, 
                                df_margin: pd.DataFrame,
                                mapping_coverage_pct: float,
                                target_date: str = "") -> tuple[float, str, list[str]]:
        """
        Calculates a quantitative Data Quality (DQ) score based on 5 metrics.
        Validates date formats, market bounds, and column schemas (B-03/M1 compliance).
        """
        score = 100.0
        issues = []
        
        # 1. Completeness (30%)
        completeness_penalty = 0.0
        if df_ohlcv.empty:
            completeness_penalty += 30.0
            issues.append("OHLCV data is completely empty.")
        else:
            # Check core schema columns existence
            expected_cols = ["open", "high", "low", "close", "volume", "trade_date", "market_type"]
            missing_cols = [c for c in expected_cols if c not in df_ohlcv.columns]
            if missing_cols:
                completeness_penalty += 20.0
                issues.append(f"Missing core schema columns: {missing_cols}")
            else:
                null_cols = df_ohlcv[["open", "high", "low", "close", "volume"]].isnull().sum().sum()
                if null_cols > 0:
                    completeness_penalty += min(15.0, null_cols * 1.0)
                    issues.append(f"OHLCV contains {null_cols} null values in core columns.")
                
                # Check date payload matching (B-03 compliance)
                if target_date:
                    mismatched_dates = (df_ohlcv["trade_date"] != target_date).sum()
                    if mismatched_dates > 0:
                        completeness_penalty += 15.0
                        issues.append(f"Date payload discrepancy: {mismatched_dates} rows do not match target date {target_date}.")
                
                # Check row count scale
                if len(df_ohlcv) < 800:
                    completeness_penalty += 15.0
                    issues.append(f"Market data rows count ({len(df_ohlcv)}) is critically low (expected > 800 for full universe).")
                
        if mapping_coverage_pct < 0.80:
            pct_diff = (0.80 - mapping_coverage_pct) * 100
            completeness_penalty += min(15.0, pct_diff * 0.5)
            issues.append(f"Industry mapping coverage ({mapping_coverage_pct:.2%}) is below 80%.")

        score -= completeness_penalty

        # 2. Uniqueness (15%)
        uniqueness_penalty = 0.0
        if not df_ohlcv.empty:
            dup_count = df_ohlcv["stock_id"].duplicated().sum()
            if dup_count > 0:
                uniqueness_penalty += min(15.0, dup_count * 1.5)
                issues.append(f"Duplicate stock_ids found: {dup_count} instances.")
        score -= uniqueness_penalty

        # 3. Format (15%)
        format_penalty = 0.0
        if not df_ohlcv.empty:
            invalid_prices = ((df_ohlcv["open"] <= 0) | (df_ohlcv["high"] <= 0) | 
                              (df_ohlcv["low"] <= 0) | (df_ohlcv["close"] <= 0)).sum()
            if invalid_prices > 0:
                format_penalty += min(10.0, invalid_prices * 2.0)
                issues.append(f"Negative or zero prices found: {invalid_prices} rows.")
            
            invalid_volume = (df_ohlcv["volume"] < 0).sum()
            if invalid_volume > 0:
                format_penalty += min(5.0, invalid_volume * 1.0)
                issues.append(f"Negative volumes found: {invalid_volume} rows.")
                
            invalid_mtype = (~df_ohlcv["market_type"].isin(["TWSE", "TPEx"])).sum()
            if invalid_mtype > 0:
                format_penalty += min(5.0, invalid_mtype * 1.0)
                issues.append(f"Invalid market types found: {invalid_mtype} rows.")
        score -= format_penalty

        # 4. Reasonability (15%)
        reasonability_penalty = 0.0
        if not df_ohlcv.empty:
            high_low_violation = (df_ohlcv["high"] < df_ohlcv["low"]).sum()
            if high_low_violation > 0:
                reasonability_penalty += min(15.0, high_low_violation * 5.0)
                issues.append(f"High-low violation (high < low): {high_low_violation} rows.")
        score -= reasonability_penalty

        # 5. Consistency (15%)
        consistency_penalty = 0.0
        if not df_ohlcv.empty and not df_inst.empty:
            inst_tickers = set(df_inst["stock_id"])
            price_tickers = set(df_ohlcv["stock_id"])
            unmatched_inst = len(inst_tickers - price_tickers)
            if unmatched_inst > 0 and len(inst_tickers) > 0:
                unmatched_ratio = unmatched_inst / len(inst_tickers)
                if unmatched_ratio > 0.10:
                    consistency_penalty += 15.0
                    issues.append(f"High inconsistency between Institutional Flow and Prices table ({unmatched_ratio:.1%} unmatched).")
                else:
                    consistency_penalty += min(10.0, unmatched_inst * 0.5)
        score -= consistency_penalty

        score = max(0.0, score)
        
        if score >= 95.0:
            status = "NORMAL"
        elif score >= 85.0:
            status = "WARNING"
        elif score >= 70.0:
            status = "DEGRADED"
        else:
            status = "BLOCKED"
            
        logger.info(f"Data Quality Score: {score:.2f} | Status: {status}")
        return score, status, issues
