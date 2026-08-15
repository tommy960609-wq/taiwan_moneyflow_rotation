import json
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from scripts.run_stock_score_diagnostic import (
    ROUND_TRIP_COST,
    _market_forward_returns,
    _narrow_unadjusted_stats,
    _price_path,
    assign_daily_deciles,
    build_return_panel,
    decile_table,
    horizon_availability_table,
    horizon_newey_west_tstat,
    load_official_ohlcv_history,
    load_taiex,
    newey_west_tstat,
    rank_ic_table,
    select_top,
    simulate_overlapping_portfolio,
    write_report,
)


def _panel(rows_per_day=10, days=3):
    rows = []
    for day in range(days):
        for rank in range(rows_per_day):
            rows.append({
                "row_id": day * rows_per_day + rank,
                "trade_date": f"2026-01-{day + 1:02d}",
                "stock_score": float(rank),
                "daily_return": float(rank) / 100,
                "volume": float(rows_per_day - rank),
                "sector_score": float(rank),
                "score_strength": float(rank),
                "score_volume": float(rank),
                "score_improvement": float(rank),
                "score_breakout": float(rank),
                "score_institution": float(rank),
                "score_confidence": "FULL",
                "gross_1d": float(rank) / 100,
                "gross_3d": float(rank) / 100,
                "gross_5d": float(rank) / 100,
                "gross_10d": float(rank) / 100,
                "gross_20d": float(rank) / 100,
                "market_1d": 0.0,
                "market_3d": 0.0,
                "market_5d": 0.0,
                "market_10d": 0.0,
                "market_20d": 0.0,
                "excess_10d": float(rank) / 100,
            })
    return pd.DataFrame(rows)


def test_assign_daily_deciles_has_one_decile_per_score_bucket():
    ranked = assign_daily_deciles(_panel(rows_per_day=10, days=1))
    assert ranked["decile"].tolist() == [f"D{i}" for i in range(1, 11)]


def test_decile_table_applies_preregistered_pass_rule():
    table, decision = decile_table(_panel(rows_per_day=10, days=3))
    assert len(table) == 10
    assert decision["d10_minus_d1"] > 0
    assert decision["spearman"] == pytest.approx(1.0)
    assert decision["passed"] is True
    assert decision["sample_requirement_met"] is False


def test_newey_west_uses_daily_observation_count_and_never_zero_fills():
    result = newey_west_tstat([0.01, None, np.nan, -0.01, 0.02])
    assert result["n_daily"] == 3
    assert result["nw_lag"] <= 2
    assert result["mean"] == pytest.approx((0.01 - 0.01 + 0.02) / 3)


def test_newey_west_short_series_is_honest_about_tstat():
    result = newey_west_tstat([0.03])
    assert result["n_daily"] == 1
    assert result["t_stat"] is None


def test_horizon_newey_west_lag_covers_overlapping_returns():
    result = horizon_newey_west_tstat([0.01] * 30, horizon=20)
    assert result["nw_lag"] == 19


def test_rank_ic_is_daily_not_stock_day_tstat():
    table = rank_ic_table(_panel(rows_per_day=10, days=3), horizons=(1,))
    row = table.loc[table["factor"] == "score_strength"].iloc[0]
    assert row["n_daily"] == 3
    assert row["mean_ic"] == pytest.approx(1.0)


def test_top_selection_uses_only_mature_horizon_rows():
    panel = _panel(rows_per_day=10, days=1)
    panel.loc[panel.index[-1], "gross_5d"] = np.nan
    selected = select_top(panel, "stock_score", n=2, horizon=5)
    assert selected["2026-01-01"] == [8, 7]


def test_overlapping_portfolio_applies_cost_once_per_round_trip():
    paths = {
        1: {2: [("2026-01-02", 0.0), ("2026-01-03", 0.10)]},
        2: {2: [("2026-01-02", 0.0), ("2026-01-03", 0.10)]},
    }
    result = simulate_overlapping_portfolio({"2026-01-01": [1, 2]}, paths, horizon=2)
    # A half-capital tranche earns 10% over its two days and pays half of the
    # documented 0.685% round-trip cost on the entry day.
    assert result["average_holding_days"] == pytest.approx(2.0)
    assert result["average_daily_turnover"] == pytest.approx(0.5)
    assert result["gross_total_return"] == pytest.approx(0.05)
    assert result["net_total_return"] == pytest.approx((1 - ROUND_TRIP_COST / 2) * 1.05 - 1)


def test_overlapping_portfolio_leaves_missing_paths_out_instead_of_substituting_zero():
    result = simulate_overlapping_portfolio({"2026-01-01": [999]}, {}, horizon=5)
    assert result["gross_total_return"] is None
    assert result["n_daily_portfolio_observations"] == 0


def test_official_adapter_parses_roc_dates_and_deduplicates_with_twse_priority(tmp_path):
    twse = {
        "payload": [{"Date": "1150724", "Code": "2330", "OpeningPrice": "100", "HighestPrice": "101",
                     "LowestPrice": "99", "ClosingPrice": "100", "TradeVolume": "1,234"}],
    }
    tpex = {
        "payload": [{"Date": "115/07/24", "SecuritiesCompanyCode": "2330", "Open": "200", "High": "201",
                     "Low": "199", "Close": "200", "TradingShares": "4321"}],
    }
    (tmp_path / "twse_prices_2026-07-24.json").write_text(json.dumps(twse), encoding="utf-8")
    (tmp_path / "tpex_prices_2026-07-24.json").write_text(json.dumps(tpex), encoding="utf-8")
    adapted = load_official_ohlcv_history(tmp_path)
    assert adapted.to_dict(orient="records") == [{
        "stock_id": "2330", "trade_date": "2026-07-24", "open": 100.0, "high": 101.0,
        "low": 99.0, "close": 100.0, "volume": 1234.0,
    }]


def test_price_path_rejects_zero_close_instead_of_creating_a_negative_hundred_percent_return():
    history = pd.DataFrame({
        "trade_date": ["2026-01-02", "2026-01-03"], "close": [10.0, 0.0],
    })
    assert _price_path("2330", "2026-01-02", 10.0, {"2330": history}, maximum_horizon=2) is None


def test_return_panel_leaves_zero_close_horizon_null_instead_of_negative_hundred_percent():
    dates = pd.date_range("2026-01-01", periods=22, freq="D").strftime("%Y-%m-%d").tolist()
    closes = [10.0] * len(dates)
    closes[3] = 0.0
    history = pd.DataFrame({"stock_id": "2330", "trade_date": dates, "open": [10.0] * len(dates),
                            "high": [10.0] * len(dates), "low": [10.0] * len(dates),
                            "close": closes, "volume": [1.0] * len(dates)})
    scored = {dates[0]: pd.DataFrame({"stock_id": ["2330"], "trade_date": [dates[0]], "stock_score": [80.0]})}
    taiex = pd.DataFrame({"trade_date": dates, "close": [100.0] * len(dates)})
    panel, _ = build_return_panel(scored, {"2330": history}, taiex)
    assert pd.isna(panel.loc[0, "gross_3d"])
    assert not (pd.to_numeric(panel["gross_10d"], errors="coerce") <= -0.9).any()


def test_median_benchmark_requires_breadth_and_never_uses_a_single_constituent():
    paths = {1: {1: [("2026-01-02", 0.10)]}}
    result = simulate_overlapping_portfolio({"2026-01-01": [1]}, paths, horizon=1,
                                            constituent_aggregation="median")
    assert result["gross_total_return"] is None


def test_median_benchmark_checks_breadth_per_return_date_not_total_paths():
    paths = {}
    for row_id in range(40):
        return_date = "2026-01-02" if row_id < 20 else "2026-01-03"
        paths[row_id] = {1: [(return_date, 0.10)]}
    result = simulate_overlapping_portfolio(
        {"2026-01-01": list(paths)}, paths, horizon=1, constituent_aggregation="median",
    )
    assert result["gross_total_return"] is None
    assert result["net_total_return"] is None
    assert result["n_daily_portfolio_observations"] == 0


def test_taiex_extends_finmind_with_valid_official_rows_and_rejects_date_mismatch(tmp_path):
    finmind = {"payload": [{"date": "2026-07-17", "close": 42671.27}]}
    official_17 = {"payload": [
        {"日期": "1150717", "指數": "發行量加權股價指數", "收盤指數": "42,671.27"},
        {"日期": "1150717", "指數": "發行量加權股價報酬指數", "收盤指數": "99,999.99"},
    ]}
    polluted_20 = {"payload": [{"日期": "1150717", "指數": "發行量加權股價指數",
                                "收盤指數": "42671.27"}]}
    official_20 = {"payload": [
        {"日期": "1150720", "指數": "發行量加權股價指數", "收盤指數": "43,500.25"},
        {"日期": "1150720", "指數": "發行量加權股價報酬指數", "收盤指數": "100,100.00"},
    ]}
    official_23 = {"payload": [
        {"日期": "1150723", "指數": "發行量加權股價指數", "收盤指數": "44,850.81"},
        {"日期": "1150723", "指數": "發行量加權股價報酬指數", "收盤指數": "100,574.58"},
    ]}
    (tmp_path / "finmind_index_twse.json").write_text(json.dumps(finmind), encoding="utf-8")
    (tmp_path / "twse_2026-07-17.json").write_text(json.dumps(official_17, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "twse_2026-07-20.json").write_text(json.dumps(polluted_20, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "twse_official_2026-07-20.json").write_text(
        json.dumps(official_20, ensure_ascii=False), encoding="utf-8",
    )
    (tmp_path / "twse_2026-07-23.json").write_text(json.dumps(official_23, ensure_ascii=False), encoding="utf-8")
    taiex = load_taiex(tmp_path).set_index("trade_date")["close"].to_dict()
    assert taiex == {
        "2026-07-17": 42671.27,
        "2026-07-20": 43500.25,
        "2026-07-23": 44850.81,
    }


def test_market_return_does_not_fill_or_skip_missing_taiex_date():
    taiex = pd.DataFrame({
        "trade_date": ["2026-07-16", "2026-07-17", "2026-07-21"],
        "close": [42000.0, 42671.27, 44232.87],
    })
    result = _market_forward_returns(
        "2026-07-17", taiex,
        ["2026-07-16", "2026-07-17", "2026-07-20", "2026-07-21"],
        horizons=(1, 3),
    )
    assert result[1] == pytest.approx(42671.27 / 42000.0 - 1)
    assert result[3] is None


def test_return_panel_keeps_tradable_open_return_and_adds_aligned_close_to_close_excess():
    dates = ["2026-01-01", "2026-01-02"]
    history = pd.DataFrame({
        "stock_id": ["2330", "2330"], "trade_date": dates,
        "open": [10.0, 10.0], "high": [10.0, 11.0], "low": [10.0, 10.0],
        "close": [10.0, 11.0], "volume": [1000.0, 1000.0],
        "price_unadjusted": [False, True],
    })
    scored = {dates[0]: pd.DataFrame({
        "stock_id": ["2330"], "trade_date": [dates[0]], "stock_score": [80.0],
    })}
    taiex = pd.DataFrame({"trade_date": dates, "close": [100.0, 102.0]})
    panel, _ = build_return_panel(scored, {"2330": history}, taiex)
    assert panel.loc[0, "gross_1d"] == pytest.approx(0.10)
    assert panel.loc[0, "close_to_close_1d"] == pytest.approx(0.10)
    assert panel.loc[0, "market_1d"] == pytest.approx(0.02)
    assert panel.loc[0, "aligned_excess_1d"] == pytest.approx(0.08)
    assert panel.loc[0, "excess_1d"] == pytest.approx(0.10)
    assert bool(panel.loc[0, "price_unadjusted"]) is True


def test_decile_decision_reports_daily_d10_minus_d1_newey_west_statistics():
    _, decision = decile_table(_panel(rows_per_day=500, days=3))
    assert decision["daily_d10_minus_d1_n"] == 3
    assert decision["daily_d10_minus_d1_mean"] == pytest.approx(4.5)
    assert decision["daily_d10_minus_d1_positive_rate"] == 1.0
    assert decision["daily_d10_minus_d1_nw_lag"] == 2


def test_unadjusted_ratio_uses_only_realized_narrow_horizon_rows():
    panel = pd.DataFrame({
        "stock_id": ["A", "B", "C", "D"],
        "excess_10d": [0.1, 0.2, 0.3, np.nan],
    })
    stats = _narrow_unadjusted_stats(panel, {"A", "C"})
    assert stats["unadjusted_rows"] == 1
    assert stats["total_rows"] == 3
    assert stats["ratio"] == pytest.approx(1 / 3)


def test_price_path_rejects_stock_gap_against_market_calendar():
    stock = pd.DataFrame({
        "stock_id": ["1435", "1435"],
        "trade_date": ["2026-01-02", "2026-01-04"],
        "close": [10.0, 20.0],
    })
    market_peer = pd.DataFrame({
        "stock_id": ["2330", "2330", "2330"],
        "trade_date": ["2026-01-02", "2026-01-03", "2026-01-04"],
        "close": [100.0, 100.0, 100.0],
    })
    assert _price_path("1435", "2026-01-02", 10.0,
                       {"1435": stock, "2330": market_peer}, maximum_horizon=2) is None


def test_return_panel_rejects_delayed_entry_after_missing_market_t_plus_one_bar():
    stock = pd.DataFrame({
        "stock_id": ["1435", "1435"],
        "trade_date": ["2026-06-11", "2026-06-17"],
        "open": [5.0, 14.0], "high": [5.0, 14.0], "low": [5.0, 14.0],
        "close": [5.0, 14.0], "volume": [1000.0, 1000.0],
    })
    peer_dates = ["2026-06-11", "2026-06-12", "2026-06-15", "2026-06-16", "2026-06-17"]
    peer = pd.DataFrame({
        "stock_id": ["2330"] * len(peer_dates), "trade_date": peer_dates,
        "open": [100.0] * len(peer_dates), "high": [100.0] * len(peer_dates),
        "low": [100.0] * len(peer_dates), "close": [100.0] * len(peer_dates),
        "volume": [1000.0] * len(peer_dates),
    })
    scored = {"2026-06-11": pd.DataFrame({
        "stock_id": ["1435"], "trade_date": ["2026-06-11"], "stock_score": [90.0],
    })}
    taiex = pd.DataFrame({"trade_date": peer_dates, "close": [100.0] * len(peer_dates)})
    panel, paths = build_return_panel(scored, {"1435": stock, "2330": peer}, taiex)
    assert panel.empty
    assert paths == {}


def test_return_panel_rejects_signal_immediately_after_a_missing_market_bar():
    stock_dates = ["2026-06-15", "2026-06-17", "2026-06-18"]
    stock = pd.DataFrame({
        "stock_id": ["1435"] * len(stock_dates), "trade_date": stock_dates,
        "open": [5.0, 5.5, 14.0], "high": [5.0, 5.5, 14.0],
        "low": [5.0, 5.5, 14.0], "close": [5.0, 5.5, 14.0],
        "volume": [1000.0] * len(stock_dates),
    })
    market_dates = ["2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18"]
    peer = pd.DataFrame({
        "stock_id": ["2330"] * len(market_dates), "trade_date": market_dates,
        "open": [100.0] * len(market_dates), "high": [100.0] * len(market_dates),
        "low": [100.0] * len(market_dates), "close": [100.0] * len(market_dates),
        "volume": [1000.0] * len(market_dates),
    })
    scored = {"2026-06-17": pd.DataFrame({
        "stock_id": ["1435"], "trade_date": ["2026-06-17"], "stock_score": [90.0],
    })}
    taiex = pd.DataFrame({"trade_date": market_dates, "close": [100.0] * len(market_dates)})
    panel, paths = build_return_panel(scored, {"1435": stock, "2330": peer}, taiex)
    assert panel.empty
    assert paths == {}


def test_official_adapter_supports_legacy_tpex_schema(tmp_path):
    legacy = [{
        "Date": "20260716", "Code": "1240", "OpeningPrice": 55.4,
        "HighestPrice": 55.5, "LowestPrice": 55.3, "ClosingPrice": 55.5,
        "TradeVolume": 10777,
    }]
    (tmp_path / "tpex_prices_2026-07-16.json").write_text(json.dumps(legacy), encoding="utf-8")
    adapted = load_official_ohlcv_history(tmp_path)
    assert adapted[["stock_id", "trade_date", "close"]].to_dict(orient="records") == [
        {"stock_id": "1240", "trade_date": "2026-07-16", "close": 55.5},
    ]


def test_ohlcv_adapter_merges_finmind_fallback_with_official_priority(tmp_path):
    finmind = {"payload": [
        {"date": "2026-07-16", "open": 10, "max": 11, "min": 9, "close": 10,
         "Trading_Volume": 100},
    ]}
    official = [{
        "Date": "20260716", "Code": "2330", "OpeningPrice": 20,
        "HighestPrice": 21, "LowestPrice": 19, "ClosingPrice": 20, "TradeVolume": 200,
    }]
    (tmp_path / "finmind_1240.json").write_text(json.dumps(finmind), encoding="utf-8")
    (tmp_path / "twse_prices_2026-07-16.json").write_text(json.dumps(official), encoding="utf-8")
    adapted = load_official_ohlcv_history(tmp_path)
    assert adapted.set_index("stock_id")["close"].to_dict() == {"1240": 10.0, "2330": 20.0}


def test_ohlcv_adapter_filters_nonpositive_close_at_read_layer(tmp_path):
    bad = [{
        "Date": "20260716", "Code": "1240", "OpeningPrice": 1,
        "HighestPrice": 1, "LowestPrice": 0, "ClosingPrice": 0, "TradeVolume": 100,
    }]
    (tmp_path / "tpex_prices_2026-07-16.json").write_text(json.dumps(bad), encoding="utf-8")
    adapted = load_official_ohlcv_history(tmp_path)
    assert adapted.empty
    assert adapted.attrs["cleaning_stats"]["nonpositive_close_rows"] == 1


def test_horizon_table_marks_immature_wide_universe_as_not_decisive():
    panel = _panel(rows_per_day=10, days=3)
    table = horizon_availability_table(panel, horizons=(5, 10))
    assert table["status"].tolist() == ["insufficient_not_decisive", "insufficient_not_decisive"]
    assert table["n_stock_days"].tolist() == [30, 30]


def test_report_headline_refuses_to_decide_when_decile_samples_are_small(tmp_path):
    table, decision = decile_table(_panel(rows_per_day=10, days=3))
    availability = horizon_availability_table(_panel(rows_per_day=10, days=3), horizons=(10, 20))
    write_report(tmp_path, _panel(rows_per_day=10, days=3), table, decision,
                 pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), availability,
                 None, {}, {}, {}, {}, 0, smoke=True)
    assert "樣本不足，不可裁決" in (tmp_path / "REPORT.md").read_text(encoding="utf-8")
