import os
import sys
import requests
import json
import urllib3
import hashlib
from datetime import datetime
from loguru import logger

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def calculate_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def fetch_and_save_full_payload(url: str, save_path: str, name: str) -> bool:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    logger.info(f"Fetching full endpoint response for {name} from {url}...")
    fetch_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        res = requests.get(url, headers=headers, verify=False, timeout=30)
        http_status = res.status_code
        if http_status == 200:
            data = res.json()
            row_count = 0
            
            if isinstance(data, dict):
                if "payload" in data:
                    payload = data["payload"]
                else:
                    payload = data
                
                if "data" in payload and isinstance(payload["data"], list):
                    row_count = len(payload["data"])
                elif isinstance(payload, dict):
                    row_count = len(payload)
                else:
                    row_count = 1
            elif isinstance(data, list):
                payload = data
                row_count = len(data)
            else:
                payload = data
                row_count = 1
                
            raw_text = json.dumps(payload, ensure_ascii=False)
            sha256_val = calculate_sha256(raw_text)
            
            meta_json = {
                "metadata": {
                    "url": url,
                    "http_status": http_status,
                    "fetch_time": fetch_time,
                    "row_count": row_count,
                    "sha256": sha256_val
                },
                "payload": payload
            }
            
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(meta_json, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved full response ({row_count} rows) & metadata to {save_path}")
            return True
        else:
            logger.error(f"Failed to fetch {name}: HTTP {http_status}")
            return False
    except Exception as e:
        logger.error(f"Error fetching full data for {name}: {e}")
        return False

def inspect_and_cache_openapi():
    base_dir = "C:/Workspace_CN/taiwan_moneyflow_rotation"
    sample_dir = f"{base_dir}/loop/evidence/raw_samples"
    os.makedirs(sample_dir, exist_ok=True)
    
    # B3 compliance: Query TWSE T86 on date 20260717 to match TPEx latest trading day naturally
    endpoints = [
        {
            "url": "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
            "path": f"{sample_dir}/twse_ohlcv_sample.json",
            "name": "TWSE Daily OHLCV"
        },
        {
            "url": "https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date=20260717&selectType=ALLBUT0999",
            "path": f"{sample_dir}/twse_inst_sample.json",
            "name": "TWSE Institutional Flow (T86)"
        },
        {
            "url": "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN",
            "path": f"{sample_dir}/twse_margin_sample.json",
            "name": "TWSE Margin Trading"
        },
        {
            "url": "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
            "path": f"{sample_dir}/tpex_ohlcv_sample.json",
            "name": "TPEx Daily OHLCV"
        },
        {
            "url": "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading",
            "path": f"{sample_dir}/tpex_inst_sample.json",
            "name": "TPEx Institutional Flow"
        },
        {
            "url": "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance",
            "path": f"{sample_dir}/tpex_margin_sample.json",
            "name": "TPEx Margin Trading"
        }
    ]
    
    success_count = 0
    all_success = True
    for ep in endpoints:
        if fetch_and_save_full_payload(ep["url"], ep["path"], ep["name"]):
            success_count += 1
        else:
            all_success = False
            
    logger.info(f"OpenAPI verification complete. {success_count}/{len(endpoints)} endpoints successfully cached.")
    if not all_success:
        logger.error("Some OpenAPI checks failed. Terminating with non-zero exit code.")
        sys.exit(1)
    else:
        logger.info("All OpenAPI verification passed successfully. Terminating with exit 0.")
        sys.exit(0)

if __name__ == "__main__":
    inspect_and_cache_openapi()
