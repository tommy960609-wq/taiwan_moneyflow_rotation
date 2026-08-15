# Milestone 0: Data Catalog & Risk Log

This document lists the official TWSE/TPEx data sources inspected for V1 daily data and outlines potential data quality and infrastructure risks along with mitigation designs.

---

## 1. Data Catalog (資料盤點)

To support the daily sector moneyflow rotation calculations, we integrate data from the following public API feeds:

### 1.1 TWSE (上市市場)
-   **Daily OHLCV (全市場收盤行情)**:
    -   *URL*: `https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL`
    -   *Update Frequency*: Post-market close (~14:30 TWD).
    -   *Key Fields*: Code, Name, OpeningPrice, HighestPrice, LowestPrice, ClosingPrice, TradeVolume, TradeValue.
-   **Institutional Trading (三大法人買賣金額/明細)**:
    -   *URL*: `https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date=YYYYMMDD&selectType=ALLBUT0999` (T86 RWD endpoint)
    -   *Update Frequency*: Evening (~18:00 TWD).
    -   *Key Fields*: Code, Name, ForeignNetBuy, TrustNetBuy, DealerNetBuy.
-   **Margin Trading (融資融券)**:
    -   *URL*: `https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN`
    -   *Update Frequency*: Night (~21:00 TWD).

### 1.2 TPEx OpenAPI (上櫃市場)
-   **Daily OHLCV**:
    -   *URL*: `https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes`
-   **Institutional Trading**:
    -   *URL*: `https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading`
-   **Margin Trading**:
    -   *URL*: `https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance`

---

## 2. API Endpoints Change Logs (2026-07-17 Audit)

During the M0 verification gate audit, several discrepancies between theoretical OpenAPI specs and actual endpoints were resolved:

1.  **TWSE Institutional Flow (T86)**:
    -   *Old Route (Decommissioned)*: `https://openapi.twse.com.tw/v1/fund/T86`
    -   *New Route (Activated)*: `https://www.twse.com.tw/rwd/zh/fund/T86?response=json`
    -   *Reason*: TWSE OpenAPI does not officially host a direct `/fund/T86` JSON endpoint. Switched to TWSE's stable RWD JSON interface.
2.  **TPEx Endpoints Paths**:
    -   *Old Routes (Decommissioned)*: `/v1/tpex_main_01`, `/v1/tpex_main_06`, `/v1/tpex_main_13`
    -   *New Routes (Activated)*: `/v1/tpex_mainboard_daily_close_quotes`, `/v1/tpex_3insti_daily_trading`, `/v1/tpex_mainboard_margin_balance`
    -   *Reason*: Mapped actual paths parsed from `tpex_swagger.json` to avoid 404 response errors.

---

## 3. Infrastructure and Data Risks (風險清單)

| Risk ID | Risk Description | Severity | Mitigation Design |
| :--- | :--- | :--- | :--- |
| **R-01** | **SSL Handshake Failure** (Corporate network blocking endpoints). | High | Bypass validation in requests (`verify=False`) as per `ENV_TRAPS E4`. |
| **R-02** | **OpenAPI Rate Limiting or Outages** (TWSE/TPEx server returns non-200). | High | **Fail-Closed Strategy**: Loader returns `None` and raises warning alerts instead of breaking daily reports. |
| **R-03** | **Missing Institutional Data** (T86 updates later than OHLCV). | Medium | **Dynamic Normalization**: Score model ignores the 10% Institutional factor, adjusts remaining factors to sum up to 1.0, and flags report quality as `DEGRADED`. |
| **R-04** | **Float-to-String Conversion** (e.g. ticker symbol "0050" converted to 50). | High | Force string parsing inside cleaner and check layout patterns using regex `^[A-Z0-9]{4,6}$`. |
| **R-05** | **Warrant & ETF Noise** (Warrants mimicking regular stocks). | Medium | Explicitly filter out tickers of length > 5 or symbols containing ETF identifiers inside `DataCleaner`. |
| **R-06** | **Future Information Leakage** (Peeking into tomorrow's prices). | Critical | Write a double-dataset test (`test_future_leakage.py`) comparing variables calculated at day T with data ending at T vs data ending at T+20. |
| **R-07** | **Locked Limit-Up Purchase** (Backtest assume buying at open when it is impossible). | High | Check if open = limit-up price and volume is zero on entry day. Exclude or postpone entry. |
