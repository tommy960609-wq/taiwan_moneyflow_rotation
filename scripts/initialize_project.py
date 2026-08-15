import os
import sys

def initialize_directories():
    base_dir = "C:\\Workspace_CN\\taiwan_moneyflow_rotation"
    dirs = [
        "config",
        "data/raw/reports",
        "data/raw/ohlcv",
        "data/raw/institutional",
        "data/raw/margin",
        "data/raw/market_index",
        "data/raw/fundamentals",
        "data/reference",
        "data/processed",
        "data/test_fixtures",
        "src",
        "tests/unit",
        "tests/integration",
        "tests/regression",
        "tests/property",
        "tests/leakage",
        "tests/acceptance",
        "scripts",
        "outputs/daily",
        "outputs/charts",
        "outputs/backtests",
        "outputs/logs",
        "docs",
        "loop/evidence/test_logs",
        "loop/evidence/screenshots",
        "loop/evidence/sample_outputs",
        "loop/evidence/performance",
        "loop/evidence/data_quality",
        "loop/evidence/raw_samples"
    ]
    
    print(f"Initializing directories under {base_dir}...")
    for d in dirs:
        path = os.path.join(base_dir, d)
        os.makedirs(path, exist_ok=True)
        print(f"Created: {path}")

if __name__ == "__main__":
    initialize_directories()
