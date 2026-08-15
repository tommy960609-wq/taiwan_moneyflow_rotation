import sys
import os
import json

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "run_backtest", os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts/run_backtest.py"))
)
run_backtest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_backtest)


# ---------------------------------------------------------------------------
# load_adjustment_factors / apply_price_adjustment
# ---------------------------------------------------------------------------

def test_load_adjustment_factors_missing_file_returns_empty(tmp_path):
    df = run_backtest.load_adjustment_factors(str(tmp_path))
    assert df.empty
    assert list(df.columns) == ["stock_id", "trade_date", "adj_factor"]


def test_load_adjustment_factors_reads_csv(tmp_path):
    ref_dir = tmp_path / "reference"
    ref_dir.mkdir()
    pd.DataFrame([{"stock_id": "2330", "trade_date": "2026-04-20", "adj_factor": 0.9}]) \
        .to_csv(ref_dir / "price_adjustment_factors.csv", index=False)
    df = run_backtest.load_adjustment_factors(str(tmp_path))
    assert len(df) == 1
    assert df.iloc[0]["stock_id"] == "2330"


def test_apply_price_adjustment_disabled_marks_everything_unadjusted(tmp_path):
    df_ohlcv = pd.DataFrame([
        {"stock_id": "2330", "trade_date": "2026-04-20", "open": 100.0, "high": 101.0,
         "low": 99.0, "close": 100.0},
    ])
    out, pct = run_backtest.apply_price_adjustment(df_ohlcv, str(tmp_path), use_adjusted_prices=False)
    assert out.iloc[0]["price_unadjusted"] == True
    assert out.iloc[0]["close"] == 100.0  # unchanged
    assert pct == 1.0


def test_apply_price_adjustment_enabled_applies_known_factor(tmp_path):
    ref_dir = tmp_path / "reference"
    ref_dir.mkdir()
    pd.DataFrame([{"stock_id": "2330", "trade_date": "2026-04-20", "adj_factor": 0.9}]) \
        .to_csv(ref_dir / "price_adjustment_factors.csv", index=False)

    df_ohlcv = pd.DataFrame([
        {"stock_id": "2330", "trade_date": "2026-04-20", "open": 100.0, "high": 101.0,
         "low": 99.0, "close": 100.0},
        {"stock_id": "9999", "trade_date": "2026-04-20", "open": 50.0, "high": 51.0,
         "low": 49.0, "close": 50.0},  # no factor entry -> stays UNADJUSTED
    ])
    out, pct = run_backtest.apply_price_adjustment(df_ohlcv, str(tmp_path), use_adjusted_prices=True)
    row_2330 = out[out.stock_id == "2330"].iloc[0]
    row_9999 = out[out.stock_id == "9999"].iloc[0]
    assert abs(row_2330["close"] - 90.0) < 1e-9
    assert row_2330["price_unadjusted"] == False
    assert row_9999["close"] == 50.0
    assert row_9999["price_unadjusted"] == True
    assert pct == 0.5  # 1 of 2 stocks unadjusted


def test_apply_price_adjustment_empty_ohlcv(tmp_path):
    out, pct = run_backtest.apply_price_adjustment(pd.DataFrame(), str(tmp_path), True)
    assert out.empty
    assert pct is None


# ---------------------------------------------------------------------------
# load_disposition_stock_ids
# ---------------------------------------------------------------------------

def test_load_disposition_stock_ids_no_dir_returns_empty(tmp_path):
    result = run_backtest.load_disposition_stock_ids(str(tmp_path))
    assert result["disposition_stock_ids"] == set()
    assert result["dates_covered"] == []


def test_load_disposition_stock_ids_unions_across_endpoints_and_dates(tmp_path):
    disp_dir = tmp_path / "raw" / "disposition"
    disp_dir.mkdir(parents=True)

    envelope1 = {"metadata": {}, "payload": [
        {"Number": "1", "Date": "x", "Code": "2330", "Name": "X",
         "ReasonsOfDisposition": "r", "DispositionPeriod": "p",
         "DispositionMeasures": "m", "Detail": "d", "LinkInformation": "l"},
    ]}
    with open(disp_dir / "twse_punish_2026-07-18.json", "w", encoding="utf-8") as f:
        json.dump(envelope1, f)

    envelope2 = {"metadata": {}, "payload": [
        {"Date": "x", "SecuritiesCompanyCode": "1101", "CompanyName": "X",
         "TradingInformation": "t", "ClosePrice": "1", "PriceEarningRatio": "1"},
    ]}
    with open(disp_dir / "tpex_warning_info_2026-07-17.json", "w", encoding="utf-8") as f:
        json.dump(envelope2, f)

    result = run_backtest.load_disposition_stock_ids(str(tmp_path))
    assert result["disposition_stock_ids"] == {"2330", "1101"}
    assert result["dates_covered"] == ["2026-07-17", "2026-07-18"]


def test_load_disposition_stock_ids_unreadable_file_skipped_not_raised(tmp_path):
    disp_dir = tmp_path / "raw" / "disposition"
    disp_dir.mkdir(parents=True)
    (disp_dir / "twse_punish_2026-07-18.json").write_text("not valid json{{{", encoding="utf-8")
    result = run_backtest.load_disposition_stock_ids(str(tmp_path))
    assert result["disposition_stock_ids"] == set()
