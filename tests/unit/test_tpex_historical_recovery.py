import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.data_fetcher import DataFetcher
import scripts.fetch_daily_data as fetch_daily_data


TRADE_DATE = "2026-07-21"


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, json_error=False):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("invalid json")
        return self._payload


def _payload(date="20260721"):
    return {
        "date": date,
        "tables": [{
            "fields": [
                "代號", "名稱", "收盤", "漲跌", "開盤", "最高", "最低",
                "均價", "成交股數", "成交金額(元)",
            ],
            "data": [[
                "6488", "環球晶", "420.00", "+5.00", "415.00", "425.00",
                "410.00", "418.00", "123456", "51980000",
            ]],
        }],
    }


def test_tpex_historical_recovery_writes_date_addressable_payload(tmp_path):
    fetcher = DataFetcher(data_dir=str(tmp_path))
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return _FakeResponse(payload=_payload())

    envelope = fetch_daily_data._fetch_tpex_historical_ohlcv(
        TRADE_DATE, fetcher, post_fn=post
    )

    assert envelope is not None
    assert calls[0][0] == fetch_daily_data.TPEX_HISTORICAL_DAILY_QUOTES_URL
    assert calls[0][1]["data"]["date"] == "2026/07/21"
    path = tmp_path / "raw" / "ohlcv" / "tpex_2026-07-21.json"
    assert path.exists()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["metadata"]["source"] == "TPEx_HISTORICAL_WEB"
    assert saved["metadata"]["row_count"] == 1
    assert saved["payload"][0]["SecuritiesCompanyCode"] == "6488"
    assert saved["payload"][0]["Close"] == "420.00"
    assert saved["payload"][0]["Date"] == "20260721"


def test_tpex_historical_recovery_rejects_date_mismatch_without_write(tmp_path):
    fetcher = DataFetcher(data_dir=str(tmp_path))
    envelope = fetch_daily_data._fetch_tpex_historical_ohlcv(
        TRADE_DATE, fetcher, post_fn=lambda *args, **kwargs: _FakeResponse(
            payload=_payload("20260722")
        )
    )

    assert envelope is None
    assert not (tmp_path / "raw" / "ohlcv" / "tpex_2026-07-21.json").exists()


def test_tpex_historical_recovery_fails_closed_on_http_or_json_error(tmp_path):
    fetcher = DataFetcher(data_dir=str(tmp_path))
    http_result = fetch_daily_data._fetch_tpex_historical_ohlcv(
        TRADE_DATE, fetcher,
        post_fn=lambda *args, **kwargs: _FakeResponse(status_code=503),
    )
    json_result = fetch_daily_data._fetch_tpex_historical_ohlcv(
        TRADE_DATE, fetcher,
        post_fn=lambda *args, **kwargs: _FakeResponse(json_error=True),
    )

    assert http_result is None
    assert json_result is None
    assert not (tmp_path / "raw" / "ohlcv" / "tpex_2026-07-21.json").exists()


def test_run_single_day_records_historical_recovery(monkeypatch, tmp_path):
    fetcher = DataFetcher(data_dir=str(tmp_path))
    fetcher.fetch_all_categories = lambda trade_date, **kwargs: {
        "ohlcv": {"twse": {"metadata": {"row_count": 1, "http_status": 200}}, "tpex": None},
        "institutional": {"twse": None, "tpex": None},
        "margin": {"twse": None, "tpex": None},
        "market_index": {"twse": None, "tpex": None},
    }
    recovered = {
        "metadata": {"row_count": 10072, "http_status": 200},
        "payload": [{"SecuritiesCompanyCode": "6488"}],
    }
    monkeypatch.setattr(fetch_daily_data, "DataFetcher", lambda data_dir: fetcher)
    monkeypatch.setattr(fetch_daily_data, "_fetch_tpex_historical_ohlcv", lambda *args: recovered)

    summary = fetch_daily_data.run_single_day(TRADE_DATE, receipts_dir=str(tmp_path / "receipts"))

    assert summary["results"]["ohlcv"]["tpex"]["row_count"] == 10072
    assert summary["historical_recovery"] == [{
        "category": "ohlcv",
        "market": "tpex",
        "source": "TPEx_HISTORICAL_WEB",
        "row_count": 10072,
    }]
    receipt = tmp_path / "receipts" / "fetch_receipt_2026-07-21.json"
    assert json.loads(receipt.read_text(encoding="utf-8"))["historical_recovery"]
