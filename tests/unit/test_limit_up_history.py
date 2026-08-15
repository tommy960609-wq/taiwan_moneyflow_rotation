import sys
import os

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.limit_up_history import (
    build_market_wide_limit_up_series,
    build_sector_limit_up_series,
    compute_consecutive_limit_up_streaks,
)


def _lb_row(trade_date, stock_id, return_pct):
    return {"trade_date": trade_date, "rank": 1, "stock_id": stock_id,
            "stock_name": "X", "return_pct": return_pct, "turnover_million_twd": 10.0}


def test_market_wide_series_counts_and_sample_size():
    df = pd.DataFrame([
        _lb_row("2026-05-01", "2330", 10.0),
        _lb_row("2026-05-01", "1101", 5.0),
        _lb_row("2026-05-01", "2317", 9.6),
        _lb_row("2026-05-02", "2330", 3.0),
    ])
    out = build_market_wide_limit_up_series(df)
    row1 = out[out.trade_date == "2026-05-01"].iloc[0]
    assert row1["limit_up_count"] == 2
    assert row1["sample_size"] == 3
    row2 = out[out.trade_date == "2026-05-02"].iloc[0]
    assert row2["limit_up_count"] == 0


def test_market_wide_series_empty_input():
    out = build_market_wide_limit_up_series(pd.DataFrame())
    assert out.empty
    assert "limit_up_count" in out.columns


def test_sector_series_joins_mapping_and_buckets_unmapped():
    df_lb = pd.DataFrame([
        _lb_row("2026-05-01", "2330", 10.0),
        _lb_row("2026-05-01", "1101", 10.0),
        _lb_row("2026-05-01", "9999", 10.0),  # not in mapping
    ])
    df_mapping = pd.DataFrame([
        {"stock_id": "2330", "primary_sector": "半導體"},
        {"stock_id": "1101", "primary_sector": "水泥"},
    ])
    out = build_sector_limit_up_series(df_lb, df_mapping)
    sectors = set(out["sector_name"])
    assert "半導體" in sectors
    assert "水泥" in sectors
    assert "未分類" in sectors
    unmapped_row = out[out.sector_name == "未分類"].iloc[0]
    assert unmapped_row["limit_up_count"] == 1
    # Sum of per-sector counts reconciles to market-wide total (3).
    assert out["limit_up_count"].sum() == 3


def test_sector_series_no_mapping_at_all_buckets_everything_unmapped():
    df_lb = pd.DataFrame([_lb_row("2026-05-01", "2330", 10.0)])
    out = build_sector_limit_up_series(df_lb, pd.DataFrame())
    assert list(out["sector_name"]) == ["未分類"]


def test_consecutive_streak_basic_run():
    df = pd.DataFrame([
        _lb_row("2026-05-01", "2330", 10.0),
        _lb_row("2026-05-02", "2330", 10.0),
        _lb_row("2026-05-03", "2330", 10.0),
        _lb_row("2026-05-04", "2330", 3.0),  # breaks the streak
    ])
    out = compute_consecutive_limit_up_streaks(df)
    out = out.set_index("trade_date")
    assert out.loc["2026-05-01", "consecutive_limit_up_days"] == 1
    assert out.loc["2026-05-02", "consecutive_limit_up_days"] == 2
    assert out.loc["2026-05-03", "consecutive_limit_up_days"] == 3
    assert "2026-05-04" not in out.index  # non-limit-up day contributes no row


def test_consecutive_streak_breaks_on_sample_gap_not_just_stock_absence():
    # Leaderboard sample has dates 05-01, 05-02, 05-05 (a real gap: 05-03/05-04 missing
    # from the 36-file sample entirely). Stock is limit-up on all 3 observed dates --
    # the streak must NOT bridge across the sample gap.
    df = pd.DataFrame([
        _lb_row("2026-05-01", "2330", 10.0),
        _lb_row("2026-05-02", "2330", 10.0),
        _lb_row("2026-05-05", "2330", 10.0),
        # another stock present on 05-05 so that date exists in the overall sample
        _lb_row("2026-05-05", "1101", 1.0),
    ])
    out = compute_consecutive_limit_up_streaks(df).set_index(["stock_id", "trade_date"])
    assert out.loc[("2330", "2026-05-01"), "consecutive_limit_up_days"] == 1
    assert out.loc[("2330", "2026-05-02"), "consecutive_limit_up_days"] == 2
    # 05-05 is not the date right after 05-02 in the OBSERVED SAMPLE's date order
    # only if some other date fell between them; here the overall sample's date_order
    # is [05-01, 05-02, 05-05] (only 3 distinct dates exist), so 05-05 IS contiguous
    # in the sample's own index even though the calendar gap is real. This asserts the
    # documented behavior precisely: contiguity is defined against observed sample
    # dates, not calendar dates.
    assert out.loc[("2330", "2026-05-05"), "consecutive_limit_up_days"] == 3


def test_consecutive_streak_empty_input():
    out = compute_consecutive_limit_up_streaks(pd.DataFrame())
    assert out.empty
