"""Dated-endpoint fallback (2026-08-03).

Context: every endpoint in ENDPOINTS except TWSE T86 serves only its own latest
trading day, so a day the nightly run missed could never be recovered -- the
re-run fetched "today", the DATE_MISMATCH guard dropped it, and the pipeline
stayed BLOCKED for that date forever. 2026-07-28..07-31 were lost exactly that
way. DATED_ENDPOINTS adds a fallback that honors a date parameter.

Fixtures below are trimmed copies of real responses probed on 2026-07-30; no
test here touches the network.
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.data_fetcher import (
    DataFetcher, FetchResult, DATED_ENDPOINTS, normalize_dated_payload,
    _build_dated_url,
)
from src.data_cleaner import DataCleaner

import hashlib
import json


def _envelope(payload, http_status=200):
    raw_text = json.dumps(payload, ensure_ascii=False)
    return {
        "metadata": {
            "url": "http://stub", "http_status": http_status,
            "fetch_time": "2026-07-30 21:00:00",
            "row_count": len(payload) if isinstance(payload, list) else 1,
            "sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        },
        "payload": payload,
    }


class _ScriptedFetch:
    """fetch_fn stand-in returning a scripted FetchResult per URL substring."""

    def __init__(self, by_substring):
        self.by_substring = by_substring
        self.calls = []

    def __call__(self, url, category, max_retries=2, retry_delay_sec=3, **kwargs):
        self.calls.append(url)
        for needle, result in self.by_substring.items():
            if needle in url:
                return result
        return FetchResult(success=False, error="no stub for url", http_status=404)


# --- fixtures: trimmed real responses (2026-07-30) --------------------------

TWSE_OHLCV_DATED = {
    "stat": "OK",
    "date": "20260730",
    "tables": [
        {
            "title": "115年07月30日 價格指數(臺灣證券交易所)",
            "fields": ["指數", "收盤指數", "漲跌(+/-)", "漲跌點數", "漲跌百分比(%)", "特殊處理註記"],
            "data": [
                ["發行量加權股價指數", "44,114.49", "<p style ='color:green'>-</p>", "179.03", "-0.40", ""],
                ["寶島股價指數", "47,596.17", "<p style ='color:red'>+</p>", "3,481.68", "7.89", ""],
            ],
        },
        {
            "title": "報酬指數(臺灣證券交易所)",
            "fields": ["報酬指數", "收盤指數", "漲跌(+/-)", "漲跌點數", "漲跌百分比(%)", "特殊處理註記"],
            "data": [["發行量加權股價報酬指數", "97,721.96", "<p style ='color:green'>-</p>", "396.6", "-0.40", ""]],
        },
        {
            "title": "115年07月30日 每日收盤行情(全部(不含權證、牛熊證、可展延牛熊證))",
            "fields": ["證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額", "開盤價",
                       "最高價", "最低價", "收盤價", "漲跌(+/-)", "漲跌價差",
                       "最後揭示買價", "最後揭示買量", "最後揭示賣價", "最後揭示賣量", "本益比"],
            "data": [
                ["2330", "台積電", "22,158,000", "31,442", "26,589,600,000", "1,200.00",
                 "1,205.00", "1,195.00", "1,200.00", "<p style ='color:green'>-</p>",
                 "5.00", "1,199.00", "150", "1,200.00", "88", "24.51"],
                ["2317", "鴻海", "40,000,000", "12,000", "8,000,000,000", "200.00",
                 "202.00", "199.00", "201.00", "<p style ='color:red'>+</p>",
                 "1.00", "200.50", "300", "201.00", "120", "15.02"],
                # A suspended stock: TWSE publishes "--" rather than a zero.
                ["9999", "停牌股", "0", "0", "0", "--", "--", "--", "--", "", "0.00",
                 "--", "0", "--", "0", "--"],
            ],
        },
    ],
}

TPEX_OHLCV_DATED = {
    "stat": "ok",
    "date": "20260730",
    "tables": [
        {
            "title": "上櫃股票每日收盤行情(不含定價)",
            "fields": ["代號", "名稱", "收盤 ", "漲跌", "開盤 ", "最高 ", "最低",
                       "成交股數  ", " 成交金額(元)", " 成交筆數 ", "最後買價",
                       "最後買量<br>(張數)", "最後賣價", "最後賣量<br>(張數)",
                       "發行股數 ", "次日漲停價 ", "次日跌停價"],
            "data": [
                ["6488", "環球晶", "520.00", "+8.00", "515.00", "525.00", "512.00",
                 "1,234,000", "640,000,000", "2,100", "519.00", "5", "520.00", "3",
                 "435,000,000", "572.00", "468.00"],
            ],
        },
        {"title": None, "fields": None, "data": []},
    ],
}

TPEX_INST_DATED = {
    "stat": "ok",
    "date": "20260730",
    "tables": [
        {
            "title": "三大法人買賣明細資訊",
            "fields": ["代號", "名稱"] + ["買進股數", "賣出股數", "買賣超股數"] * 7
                      + ["三大法人買賣超股數合計"],
            "data": [
                # 外資不含自營 / 外資自營 / 外資合計 / 投信 / 自營自行 / 自營避險 / 自營合計
                ["6488", "環球晶",
                 "51,000", "51,000", "0",
                 "0", "0", "0",
                 "51,000", "51,000", "0",
                 "115,000", "0", "115,000",
                 "0", "0", "0",
                 "190,601", "545,850", "-355,249",
                 "190,601", "545,850", "-355,249",
                 "-240,249"],
            ],
        },
    ],
}

TWSE_MARGIN_DATED = {
    "stat": "OK",
    "date": "20260730",
    "tables": [
        {
            "title": "115年07月30日 信用交易統計",
            "fields": ["項目", "買進", "賣出", "現金(券)償還", "前日餘額", "今日餘額"],
            "data": [["融資(交易單位)", "410,406", "461,293", "12,548", "8,764,867", "8,701,432"]],
        },
        {
            "title": "115年07月30日 融資融券彙總 (全部)",
            "fields": ["代號", "名稱", "買進", "賣出", "現金償還", "前日餘額", "今日餘額",
                       "次一營業日限額", "買進", "賣出", "現券償還", "前日餘額", "今日餘額",
                       "次一營業日限額", "資券互抵", "註記"],
            "data": [
                ["2330", "台積電", "340", "422", "47", "11,100", "10,971", "520,160",
                 "12", "9", "0", "14", "17", "520,160", "0", "X "],
            ],
        },
    ],
}

TPEX_MARGIN_DATED = {
    "stat": "ok",
    "date": "20260730",
    "tables": [
        {
            "title": "上櫃股票融資融券餘額",
            "fields": ["代號", "名稱", "前資餘額(張)", "資買", "資賣", "現償", "資餘額",
                       "資屬證金", "資使用率(%)", "資限額", "前券餘額(張)", "券賣", "券買",
                       "券償", "券餘額", "券屬證金", "券使用率(%)", "券限額",
                       "資券相抵(張)", "備註"],
            "data": [
                ["6488", "環球晶", "3,831", "394", "47", "0", "4,178", "9", "0.26",
                 "1,590,798", "24", "31", "7", "0", "48", "0", "0.0", "1,590,798", "10", ""],
            ],
        },
    ],
}


# --- normalization ---------------------------------------------------------

def test_twse_ohlcv_normalizes_to_stock_day_all_shape_and_cleans():
    records = normalize_dated_payload("ohlcv", "twse", TWSE_OHLCV_DATED, "2026-07-30")

    assert records is not None
    tsmc = [r for r in records if r["Code"] == "2330"][0]
    # Keys must match STOCK_DAY_ALL exactly so data_cleaner needs no changes.
    assert tsmc["Date"] == "1150730"
    assert tsmc["Name"] == "台積電"
    assert tsmc["OpeningPrice"] == "1200.00"
    assert tsmc["ClosingPrice"] == "1200.00"
    assert tsmc["TradeVolume"] == "22158000"     # thousands separators stripped
    assert tsmc["TradeValue"] == "26589600000"
    assert tsmc["Transaction"] == "31442"
    assert tsmc["Change"] == "-5.00"             # sign cell merged into magnitude
    assert [r for r in records if r["Code"] == "2317"][0]["Change"] == "1.00"

    # End-to-end through the real cleaner.
    df = DataCleaner().clean_ohlcv_data(records, trade_date="2026-07-30", market_type="TWSE")
    row = df[df["stock_id"] == "2330"].iloc[0]
    assert row["open"] == 1200.0 and row["close"] == 1200.0
    assert row["volume"] == 22158000.0
    assert row["market_type"] == "TWSE"
    # The suspended "--" stock must be dropped, not turned into a zero-price bar.
    assert "9999" not in set(df["stock_id"])


def test_tpex_ohlcv_normalizes_despite_padded_field_labels():
    records = normalize_dated_payload("ohlcv", "tpex", TPEX_OHLCV_DATED, "2026-07-30")

    assert records is not None and len(records) == 1
    row = records[0]
    assert row["SecuritiesCompanyCode"] == "6488"
    assert row["CompanyName"] == "環球晶"
    assert row["Open"] == "515.00" and row["Close"] == "520.00"
    assert row["TradingShares"] == "1234000"
    assert row["TransactionAmount"] == "640000000"

    df = DataCleaner().clean_ohlcv_data(records, trade_date="2026-07-30", market_type="TPEx")
    assert len(df) == 1
    assert df.iloc[0]["close"] == 520.0
    assert df.iloc[0]["market_type"] == "TPEx"


def test_tpex_institutional_maps_the_seven_group_layout_to_openapi_keys():
    """The dated feed publishes 7 buy/sell/net groups; OpenAPI exposes 5.

    Getting the offsets wrong here would silently swap 投信 for 自營避險, so the
    mapping is pinned against the row's own grand total:
    外資合計 0 + 投信 115000 + 自營合計 -355249 = -240249.
    """
    records = normalize_dated_payload("institutional", "tpex", TPEX_INST_DATED, "2026-07-30")

    assert records is not None
    row = records[0]
    # NB: the live OpenAPI feed really does spell this key with a stray space
    # inside "Include MainlandArea"; the normalizer reproduces it verbatim so the
    # payload stays byte-comparable with the undated feed.
    assert row["ForeignInvestorsInclude MainlandAreaInvestors-Difference"] == "0"
    assert row["Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference"] == "0"
    assert row["SecuritiesInvestmentTrustCompanies-Difference"] == "115000"
    assert row["Dealers-Difference"] == "-355249"
    assert row["TotalDifference"] == "-240249"
    total = (int(row["ForeignInvestorsInclude MainlandAreaInvestors-Difference"])
             + int(row["SecuritiesInvestmentTrustCompanies-Difference"])
             + int(row["Dealers-Difference"]))
    assert total == int(row["TotalDifference"])

    df = DataCleaner().clean_institutional_data(None, records, trade_date="2026-07-30")
    got = df[df["stock_id"] == "6488"].iloc[0]
    assert got["investment_trust_net_buy"] == 115000.0
    assert got["dealer_net_buy"] == -355249.0


def test_twse_margin_keeps_the_positional_order_clean_margin_data_reads():
    """clean_margin_data indexes TWSE margin dicts by POSITION (vals[2]/[3]/[6]...).

    A reordered key map would keep every test on shapes passing while feeding
    融資限額 in as 融資今日餘額.
    """
    records = normalize_dated_payload("margin", "twse", TWSE_MARGIN_DATED, "2026-07-30")

    assert records is not None
    vals = list(records[0].values())
    assert vals[0] == "2330"
    assert vals[2] == "340" and vals[3] == "422"      # 融資買進 / 融資賣出
    assert vals[6] == "10971"                          # 融資今日餘額
    assert vals[8] == "12" and vals[9] == "9"          # 融券買進 / 融券賣出
    assert vals[12] == "17"                            # 融券今日餘額

    df = DataCleaner().clean_margin_data(records, None, trade_date="2026-07-30")
    row = df[df["stock_id"] == "2330"].iloc[0]
    assert row["margin_buy"] == 340.0
    assert row["margin_balance"] == 10971.0
    assert row["short_balance"] == 17.0


def test_tpex_margin_normalizes_to_openapi_keys():
    records = normalize_dated_payload("margin", "tpex", TPEX_MARGIN_DATED, "2026-07-30")

    assert records is not None
    df = DataCleaner().clean_margin_data(None, records, trade_date="2026-07-30")
    row = df[df["stock_id"] == "6488"].iloc[0]
    assert row["margin_buy"] == 394.0
    assert row["margin_balance"] == 4178.0
    assert row["short_sell"] == 31.0
    assert row["short_balance"] == 48.0


def test_market_index_emits_both_price_and_return_rows_so_callers_can_filter():
    """Downstream keeps its own 發行/加權/not-報酬 filter; don't pre-pick here.

    The two indices differ by 2.2x (44,114 vs 97,722), so silently handing back
    the 報酬指數 row would corrupt every market-relative return.
    """
    records = normalize_dated_payload("market_index", "twse", TWSE_OHLCV_DATED, "2026-07-30")

    assert records is not None
    names = [r["指數"] for r in records]
    assert "發行量加權股價指數" in names
    assert "發行量加權股價報酬指數" in names

    taiex = [r for r in records if "發行" in r["指數"] and "加權" in r["指數"]
             and "報酬" not in r["指數"]]
    assert len(taiex) == 1
    assert taiex[0]["收盤指數"] == "44114.49"   # comma stripped
    assert taiex[0]["漲跌"] == "-"              # markup stripped
    assert taiex[0]["日期"] == "1150730"


# --- fail-closed behavior --------------------------------------------------

def test_envelope_date_mismatch_is_rejected():
    payload = dict(TWSE_OHLCV_DATED, date="20260731")
    assert normalize_dated_payload("ohlcv", "twse", payload, "2026-07-30") is None


def test_error_stat_is_rejected():
    payload = dict(TWSE_OHLCV_DATED, stat="很抱歉，沒有符合條件的資料!")
    assert normalize_dated_payload("ohlcv", "twse", payload, "2026-07-30") is None


def test_missing_target_table_returns_none_rather_than_the_nearest_table():
    payload = {
        "stat": "OK", "date": "20260730",
        "tables": [t for t in TWSE_OHLCV_DATED["tables"] if "每日收盤行情" not in (t["title"] or "")],
    }
    assert normalize_dated_payload("ohlcv", "twse", payload, "2026-07-30") is None


def test_ambiguous_table_match_returns_none():
    """Two tables matching the signature means the layout changed. Don't guess."""
    quotes = [t for t in TWSE_OHLCV_DATED["tables"] if "每日收盤行情" in (t["title"] or "")][0]
    payload = {"stat": "OK", "date": "20260730", "tables": [quotes, dict(quotes)]}
    assert normalize_dated_payload("ohlcv", "twse", payload, "2026-07-30") is None


def test_changed_column_count_returns_none():
    quotes = [t for t in TWSE_OHLCV_DATED["tables"] if "每日收盤行情" in (t["title"] or "")][0]
    widened = dict(quotes, fields=list(quotes["fields"]) + ["新欄位"])
    payload = {"stat": "OK", "date": "20260730", "tables": [widened]}
    assert normalize_dated_payload("ohlcv", "twse", payload, "2026-07-30") is None


def test_no_dated_endpoint_for_tpex_market_index():
    assert DATED_ENDPOINTS["market_index"]["tpex"] is None
    assert _build_dated_url("market_index", "tpex", "2026-07-30") is None


def test_url_templates_use_each_site_s_own_date_format():
    assert "date=20260730" in _build_dated_url("ohlcv", "twse", "2026-07-30")
    assert "date=2026/07/30" in _build_dated_url("ohlcv", "tpex", "2026-07-30")


# --- integration with fetch_and_save --------------------------------------

def test_fetch_and_save_falls_back_to_dated_after_date_mismatch(tmp_path):
    """The exact 2026-07-28..31 failure: undated feed has moved on to a later day."""
    stale_undated = [{"Date": "1150803", "Code": "2330", "Name": "台積電",
                      "OpeningPrice": "1100", "ClosingPrice": "1110",
                      "HighestPrice": "1115", "LowestPrice": "1098",
                      "TradeVolume": "1000", "TradeValue": "1110000"}]
    stub = _ScriptedFetch({
        "openapi.twse.com.tw": FetchResult(success=True, envelope=_envelope(stale_undated),
                                            http_status=200),
        "www.twse.com.tw/rwd": FetchResult(success=True, envelope=_envelope(TWSE_OHLCV_DATED),
                                            http_status=200),
    })
    fetcher = DataFetcher(data_dir=str(tmp_path), fetch_fn=stub)

    envelope = fetcher.fetch_and_save("ohlcv", "twse", "2026-07-30")

    assert envelope is not None
    assert envelope["metadata"]["source"] == "dated"
    assert {r["Code"] for r in envelope["payload"]} == {"2330", "2317", "9999"}
    # The stale 8/03 payload must not have been written under a 7/30 filename.
    saved = json.loads((tmp_path / "raw" / "ohlcv" / "twse_2026-07-30.json").read_text(encoding="utf-8"))
    assert all(r["Date"] == "1150730" for r in saved["payload"])


def test_fetch_and_save_same_day_success_never_calls_the_dated_endpoint(tmp_path):
    """Guards CLAUDE.md rule 8: the nightly happy path must be unchanged."""
    fresh = [{"Date": "1150730", "Code": "2330", "Name": "台積電",
              "OpeningPrice": "1200", "ClosingPrice": "1200",
              "HighestPrice": "1205", "LowestPrice": "1195",
              "TradeVolume": "1000", "TradeValue": "1200000"}]
    stub = _ScriptedFetch({
        "openapi.twse.com.tw": FetchResult(success=True, envelope=_envelope(fresh),
                                            http_status=200),
    })
    fetcher = DataFetcher(data_dir=str(tmp_path), fetch_fn=stub)

    envelope = fetcher.fetch_and_save("ohlcv", "twse", "2026-07-30")

    assert envelope is not None
    assert envelope["metadata"]["source"] == "undated"
    assert len(stub.calls) == 1
    assert "www.twse.com.tw/rwd" not in stub.calls[0]


def test_fetch_and_save_returns_none_and_logs_once_when_both_paths_fail(tmp_path):
    stub = _ScriptedFetch({})   # every URL fails
    fetcher = DataFetcher(data_dir=str(tmp_path), fetch_fn=stub)

    assert fetcher.fetch_and_save("ohlcv", "twse", "2026-07-30") is None
    assert not (tmp_path / "raw" / "ohlcv" / "twse_2026-07-30.json").exists()
    assert len(fetcher.failure_log) == 1
