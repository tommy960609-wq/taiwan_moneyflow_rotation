"""
Milestone 8: `load_excel_leaderboard`'s leaderboard directory was hardcoded
(`C:/Workspace_CN/Quant-Agent`) since M1 (see docs/open_issues_audit_2026-07-19.md #12 /
#5). Made configurable via `reconciliation.leaderboard_dir` in config/default.yaml;
default value is unchanged from the pre-M8 hardcoded path (behavior-neutral for
existing deployments). These tests cover the new `leaderboard_dir` parameter directly
(unit-level, no ConfigManager involved) plus the "directory missing -> silent skip"
fail-open-to-skip behavior.
"""
import sys
import os

import openpyxl
import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from scripts.run_daily import load_excel_leaderboard
from src.config_manager import ConfigManager


def _write_report_xlsx(path, headers, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_missing_leaderboard_dir_returns_empty_and_does_not_raise(tmp_path):
    missing_dir = str(tmp_path / "does_not_exist")
    result = load_excel_leaderboard("2026-07-18", leaderboard_dir=missing_dir)
    assert isinstance(result, pd.DataFrame)
    assert result.empty


def test_configured_dir_with_no_matching_file_returns_empty(tmp_path):
    result = load_excel_leaderboard("2026-07-18", leaderboard_dir=str(tmp_path))
    assert isinstance(result, pd.DataFrame)
    assert result.empty


def test_configured_dir_finds_and_parses_report(tmp_path):
    sub = tmp_path / "nested" / "path"
    sub.mkdir(parents=True)
    report_path = sub / "Report_20260718.xlsx"
    _write_report_xlsx(
        report_path,
        headers=["排名", "代號", "名稱", "漲跌幅", "成交額"],
        rows=[[1, "2330", "台積電", 2.5, 1000000]],
    )

    result = load_excel_leaderboard("2026-07-18", leaderboard_dir=str(tmp_path))
    assert not result.empty
    assert "stock_id" in result.columns
    assert result.iloc[0]["stock_id"] == "2330"


def test_default_leaderboard_dir_matches_pre_m8_hardcoded_path():
    """
    Behavior-neutral guarantee: with no leaderboard_dir argument (and default config
    on disk untouched), the resolved directory is exactly the pre-M8 hardcoded value.
    """
    resolved = ConfigManager().get("reconciliation.leaderboard_dir")
    assert resolved == "C:/Workspace_CN/Quant-Agent"


def test_get_defaults_includes_reconciliation_leaderboard_dir():
    defaults = ConfigManager().get_defaults()
    assert defaults["reconciliation"]["leaderboard_dir"] == "C:/Workspace_CN/Quant-Agent"
