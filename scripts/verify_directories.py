import os
import sys
import json
from datetime import datetime

def verify_dirs():
    base_dir = "C:/Workspace_CN/taiwan_moneyflow_rotation"
    expected_dirs = [
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
    
    check_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    manifest = {
        "metadata": {
            "verified_at": check_time,
            "total_expected": len(expected_dirs),
            "total_found": 0
        },
        "results": []
    }
    
    all_found = True
    found_count = 0
    
    for d in expected_dirs:
        full_path = os.path.join(base_dir, d)
        exists = os.path.exists(full_path) and os.path.isdir(full_path)
        
        manifest["results"].append({
            "relative_path": d,
            "absolute_path": full_path,
            "status": "PASSED" if exists else "FAILED"
        })
        
        if exists:
            found_count += 1
        else:
            all_found = False
            
    manifest["metadata"]["total_found"] = found_count
    
    manifest_path = os.path.join(base_dir, "loop/evidence/directory_verification_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        
    print(f"Directory verification manifest generated at {manifest_path}")
    print(f"Total directories checked: {len(expected_dirs)}. Found: {found_count}.")
    
    if not all_found:
        print("Error: Some directories are missing.")
        sys.exit(1)
    else:
        print("Success: All 29 directories are present.")
        sys.exit(0)

if __name__ == "__main__":
    verify_dirs()
