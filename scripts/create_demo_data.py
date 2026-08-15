import os
import pandas as pd
import numpy as np

def generate_mock_data():
    # Fix random seed for strict repeatability (B-04 / B-10 compliance)
    np.random.seed(42)
    
    base_dir = "C:/Workspace_CN/taiwan_moneyflow_rotation"
    raw_dir = f"{base_dir}/data/raw"
    ref_dir = f"{base_dir}/data/reference"
    
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(ref_dir, exist_ok=True)
    
    stocks = [
        {"stock_id": "2330", "stock_name": "台積電", "primary_sector": "半導體", "secondary_sector": "晶圓代工", "theme_1": "CoWoS", "theme_2": "ASIC", "theme_3": "CPO", "supply_chain_role": "Upstream", "valid_from": "2026-01-01", "reviewed": 1},
        {"stock_id": "2317", "stock_name": "鴻海", "primary_sector": "電腦週邊", "secondary_sector": "伺服器代工", "theme_1": "GB200", "theme_2": None, "theme_3": None, "supply_chain_role": "Downstream", "valid_from": "2026-01-01", "reviewed": 1},
        {"stock_id": "2454", "stock_name": "聯發科", "primary_sector": "半導體", "secondary_sector": "IC設計", "theme_1": "Edge AI", "theme_2": None, "theme_3": None, "supply_chain_role": "Upstream", "valid_from": "2026-01-01", "reviewed": 1},
        {"stock_id": "3017", "stock_name": "奇鋐", "primary_sector": "電子零組件", "secondary_sector": "散熱模組", "theme_1": "液冷", "theme_2": "GB200", "theme_3": None, "supply_chain_role": "Midstream", "valid_from": "2026-01-01", "reviewed": 1},
        {"stock_id": "3324", "stock_name": "雙鴻", "primary_sector": "電子零組件", "secondary_sector": "散熱模組", "theme_1": "液冷", "theme_2": "GB200", "theme_3": None, "supply_chain_role": "Midstream", "valid_from": "2026-01-01", "reviewed": 1},
        {"stock_id": "3661", "stock_name": "世芯-KY", "primary_sector": "半導體", "secondary_sector": "IC設計", "theme_1": "ASIC", "theme_2": "CoWoS", "theme_3": None, "supply_chain_role": "Upstream", "valid_from": "2026-01-01", "reviewed": 1},
        {"stock_id": "3231", "stock_name": "緯創", "primary_sector": "電腦週邊", "secondary_sector": "伺服器代工", "theme_1": "GB200", "theme_2": None, "theme_3": None, "supply_chain_role": "Downstream", "valid_from": "2026-01-01", "reviewed": 1},
        {"stock_id": "2382", "stock_name": "廣達", "primary_sector": "電腦週邊", "secondary_sector": "伺服器代工", "theme_1": "GB200", "theme_2": None, "theme_3": None, "supply_chain_role": "Downstream", "valid_from": "2026-01-01", "reviewed": 1},
    ]
    df_map = pd.DataFrame(stocks)
    mapping_path = f"{ref_dir}/stock_industry_mapping.xlsx"
    df_map.to_excel(mapping_path, index=False)
    print(f"Created: {mapping_path}")

    dates = ["2026-07-14", "2026-07-15", "2026-07-16"]
    
    base_prices = {
        "2330": 1000.0,
        "2317": 200.0,
        "2454": 1200.0,
        "3017": 600.0,
        "3324": 700.0,
        "3661": 2500.0,
        "3231": 120.0,
        "2382": 280.0
    }
    
    returns_matrix = {
        "2026-07-14": {"2330": 0.005, "2317": -0.005, "2454": 0.0, "3017": 0.01, "3324": 0.008, "3661": -0.01, "3231": 0.0, "2382": -0.002},
        "2026-07-15": {"2330": 0.01, "2317": 0.015, "2454": 0.005, "3017": 0.052, "3324": 0.061, "3661": 0.02, "3231": 0.02, "2382": 0.018},
        "2026-07-16": {"2330": 0.015, "2317": 0.035, "2454": 0.02, "3017": 0.098, "3324": 0.099, "3661": 0.04, "3231": 0.045, "2382": 0.051}
    }
    
    for date in dates:
        daily_prices = []
        inst_records = []
        
        for s in stocks:
            tid = s["stock_id"]
            name = s["stock_name"]
            ret = returns_matrix[date][tid]
            
            prev_price = base_prices[tid]
            close_price = prev_price * (1.0 + ret)
            open_price = prev_price * (1.0 + ret * 0.2)
            high_price = max(open_price, close_price) * 1.01
            low_price = min(open_price, close_price) * 0.99
            
            base_prices[tid] = close_price
            
            volume = int(np.random.randint(5, 30) * 1000)
            turnover = float(volume * close_price)
            
            daily_prices.append({
                "Code": tid,
                "Name": name,
                "OpeningPrice": open_price,
                "HighestPrice": high_price,
                "LowestPrice": low_price,
                "ClosingPrice": close_price,
                "TradeVolume": volume,
                "TradeValue": turnover
            })
            
            inst_records.append({
                "stock_id": tid,
                "trade_date": date,
                "foreign_net_buy": float(np.random.randint(-10, 50) * 1000),
                "investment_trust_net_buy": float(np.random.randint(0, 30) * 1000),
                "dealer_net_buy": 0.0
            })
            
        daily_price_df = pd.DataFrame(daily_prices)
        price_dir = f"{raw_dir}/ohlcv"
        os.makedirs(price_dir, exist_ok=True)
        price_path = f"{price_dir}/prices_{date}.json"
        daily_price_df.to_json(price_path, orient="records", force_ascii=False)
        print(f"Created: {price_path}")
        
        inst_df = pd.DataFrame(inst_records)
        inst_out_dir = f"{raw_dir}/institutional"
        os.makedirs(inst_out_dir, exist_ok=True)
        inst_path = f"{inst_out_dir}/inst_{date}.json"
        inst_df.to_json(inst_path, orient="records", force_ascii=False)
        print(f"Created: {inst_path}")

if __name__ == "__main__":
    generate_mock_data()
