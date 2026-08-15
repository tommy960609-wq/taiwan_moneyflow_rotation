import os
import yaml
from loguru import logger

class ConfigManager:
    def __init__(self, config_path: str = "C:/Workspace_CN/taiwan_moneyflow_rotation/config/default.yaml"):
        self.config_path = config_path
        self.config = {}
        self.load_config()

    def load_config(self):
        if not os.path.exists(self.config_path):
            logger.warning(f"Config path {self.config_path} not found. Using defaults.")
            self.config = self.get_defaults()
            return
        
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f)
            logger.info(f"Loaded configuration from {self.config_path}")
            self.warn_uncalibrated()
        except Exception as e:
            logger.error(f"Error loading config: {e}. Falling back to default settings.")
            self.config = self.get_defaults()

    def warn_uncalibrated(self):
        warning_msg = (
            "============================================================\n"
            "WARNING: Thresholds and weights are placeholders and have not\n"
            "been calibrated against Taiwan stock market data.\n"
            "============================================================"
        )
        logger.warning(warning_msg)
        print(warning_msg)

    def get(self, key: str, default=None):
        keys = key.split(".")
        val = self.config
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val

    def get_defaults(self) -> dict:
        return {
            "system": {
                "run_mode": "production",
                "data_dir": "C:/Workspace_CN/taiwan_moneyflow_rotation/data",
                "output_dir": "C:/Workspace_CN/taiwan_moneyflow_rotation/outputs"
            },
            "data_quality": {
                "min_completeness_pct": 0.90,
                "min_mapping_rate_pct": 0.80,
                "score_warnings_threshold": 85,
                "score_blocked_threshold": 70
            },
            "reconciliation": {
                "leaderboard_dir": "C:/Workspace_CN/Quant-Agent"
            },
            "weights": {
                "breadth": 0.25,
                "volume_share": 0.25,
                "strength": 0.20,
                "momentum": 0.15,
                "institution": 0.10,
                "health": 0.05
            },
            "new_gainer": {
                "min_score": 70,
                "prev_score_max": 55,
                "score_breakout_days": 5,
                "min_rank100_change": 3,
                "min_volume_growth_pct": 0.50,
                "min_excess_return_pct": 2.0,
                "min_top50_count": 2,
                "max_top1_volume_pct": 0.70,
                "max_overheat_days": 3,
                "min_data_quality_score": 85,
                "min_mapping_coverage_pct": 0.80,
                "max_conditions_failed_for_b": 4,
                "min_core_passed_for_b": 3,
                "min_breadth_core_passed_for_b": 1
            },
            "continued_momentum": {
                "min_score_days": 2,
                "min_score": 65,
                "min_volume_share_maintained": True,
                "max_rank100_drop_pct": 0.30,
                "min_excess_return_pct": 0.0,
                "max_overheat_risk": 75,
                "min_data_quality_score": 70
            },
            "backtest": {
                "slippage_pct": 0.001,
                "fee_pct": 0.001425,
                "tax_pct": 0.003,
                "entry_delay_days": 1,
                "use_adjusted_prices": True
            }
        }
