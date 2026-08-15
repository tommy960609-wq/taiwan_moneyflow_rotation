# Taiwan Moneyflow Rotation System - Data Dictionary

This document defines the schema, data types, validation constraints, and sources for all datasets used in the system.

## 1. Full Market Daily Closing Prices (OHLCV)
This dataset represents the daily price and volume data for all listed (TWSE) and OTC (TPEx) stocks.

| Standard Field Name | Data Type | Source Endpoints | Constraints | Description |
| :--- | :--- | :--- | :--- | :--- |
| `trade_date` | String (YYYY-MM-DD) | TWSE `STOCK_DAY_ALL`, TPEx OpenAPI | Primary Key, Not Null | The trading day date in ISO-8601 format. |
| `stock_id` | String | TWSE `STOCK_DAY_ALL`, TPEx OpenAPI | Primary Key, Regex `^[A-Z0-9]{4,6}$` | 4 to 6 character stock code (e.g. "2330", "3711"). Must preserve leading zeros (e.g., "0050" not "50"). |
| `stock_name` | String | TWSE `STOCK_DAY_ALL`, TPEx OpenAPI | Not Null | Stock name. |
| `open` | Float | TWSE `STOCK_DAY_ALL`, TPEx OpenAPI | > 0 | Opening price in TWD. |
| `high` | Float | TWSE `STOCK_DAY_ALL`, TPEx OpenAPI | >= `open`, >= `low`, >= `close` | Highest price in TWD. |
| `low` | Float | TWSE `STOCK_DAY_ALL`, TPEx OpenAPI | <= `open`, <= `high`, <= `close` | Lowest price in TWD. |
| `close` | Float | TWSE `STOCK_DAY_ALL`, TPEx OpenAPI | > 0 | Closing price in TWD. |
| `volume` | Integer | TWSE `STOCK_DAY_ALL`, TPEx OpenAPI | >= 0 (Unit: Shares) | Total trading volume in shares. |
| `turnover` | Float | TWSE `STOCK_DAY_ALL`, TPEx OpenAPI | >= 0 (Unit: TWD) | Total trading turnover (value) in TWD. |
| `market_type` | String | Derived | Value in `["TWSE", "TPEx"]` | Market identifier. |

*   **Validation Rules**:
    1.  No negative volume or turnover.
    2.  `low <= open, close, high` must be mathematically true.
    3.  Exclude ETFs and warrants: Ignore stock IDs starting with letters unless they represent valid stock classes (e.g. avoid TDR, warrants, etc. by checking if length is 4-6 numeric characters, or checking symbol suffixes).
    4.  Ex-dividend adjustments: Uses corporate action database or yfinance adjusted price columns when computing historical returns.

---

## 2. Institutional Buy/Sell Net Flow
Tracks daily buying and selling activities by major domestic and foreign institutions.

| Standard Field Name | Data Type | Source Endpoints | Constraints | Description |
| :--- | :--- | :--- | :--- | :--- |
| `trade_date` | String (YYYY-MM-DD) | TWSE `/fund/T86`, TPEx OpenAPI | Primary Key, Not Null | Trading day date. |
| `stock_id` | String | TWSE `/fund/T86`, TPEx OpenAPI | Primary Key, Not Null | Stock code. |
| `foreign_net_buy` | Float | TWSE `/fund/T86`, TPEx OpenAPI | None (Unit: Shares) | Net buy/sell volume of foreign institutions. |
| `investment_trust_net_buy`| Float | TWSE `/fund/T86`, TPEx OpenAPI | None (Unit: Shares) | Net buy/sell volume of domestic investment trusts. |
| `dealer_net_buy` | Float | TWSE `/fund/T86`, TPEx OpenAPI | None (Unit: Shares) | Net buy/sell volume of proprietary dealers. |

*   **Validation Rules**:
    1.  Units must be aligned. All raw data (often in shares or TWD depending on TWSE format) must be normalized to **shares**.
    2.  If data for a stock is missing in a daily file, default to `0` and record a warning log.

---

## 3. Margin Trading (融資融券)
Tracks daily retail leverage data.

| Standard Field Name | Data Type | Source Endpoints | Constraints | Description |
| :--- | :--- | :--- | :--- | :--- |
| `trade_date` | String (YYYY-MM-DD) | TWSE /exchangeReport/MI_MARGN, TPEx | Primary Key | Trading day date. |
| `stock_id` | String | TWSE /exchangeReport/MI_MARGN, TPEx | Primary Key | Stock code. |
| `margin_buy` | Float | TWSE /exchangeReport/MI_MARGN, TPEx | >= 0 (Unit: Shares) | Daily margin purchase. |
| `margin_sell` | Float | TWSE /exchangeReport/MI_MARGN, TPEx | >= 0 (Unit: Shares) | Daily margin redemption. |
| `margin_balance` | Float | TWSE /exchangeReport/MI_MARGN, TPEx | >= 0 (Unit: Shares) | Total outstanding margin balance. |
| `short_buy` | Float | TWSE /exchangeReport/MI_MARGN, TPEx | >= 0 (Unit: Shares) | Daily short covering. |
| `short_sell` | Float | TWSE /exchangeReport/MI_MARGN, TPEx | >= 0 (Unit: Shares) | Daily short selling. |
| `short_balance` | Float | TWSE /exchangeReport/MI_MARGN, TPEx | >= 0 (Unit: Shares) | Total outstanding short balance. |

---

## 4. Caution and Disposition Stocks (注意/處置股)
List of stocks tagged by TWSE/TPEx under transaction warning criteria.

| Standard Field Name | Data Type | Source Endpoints | Constraints | Description |
| :--- | :--- | :--- | :--- | :--- |
| `trade_date` | String (YYYY-MM-DD) | TWSE/TPEx Announcement | Primary Key | Announcement/Effective date. |
| `stock_id` | String | TWSE/TPEx Announcement | Primary Key | Stock code. |
| `status` | String | TWSE/TPEx Announcement | `["CAUTION", "DISPOSITION"]` | Warning tier. |
| `disposition_period` | Integer | Derived | >= 0 | Number of days under disposition (e.g. 10 or 12 days). |

---

## 5. Stock to Sector/Theme Mapping Table
A manual and official taxonomy mapping stock IDs to primary/secondary sectors and theme groups.

| Field Name | Data Type | Format/Source | Constraints | Description |
| :--- | :--- | :--- | :--- | :--- |
| `stock_id` | String | Reference Excel | Unique Key | Stock code. |
| `stock_name` | String | Reference Excel | Not Null | Stock name. |
| `primary_sector` | String | Reference Excel | Not Null | Primary sector (e.g. "半導體", "電子零組件"). |
| `secondary_sector` | String | Reference Excel | Nullable | Sub-sector (e.g. "IC設計", "散熱"). |
| `theme_1` | String | Reference Excel | Nullable | Theme 1 (e.g. "CoWoS", "CPO"). |
| `theme_2` | String | Reference Excel | Nullable | Theme 2. |
| `theme_3` | String | Reference Excel | Nullable | Theme 3. |
| `supply_chain_role`| String | Reference Excel | Nullable | Role (e.g. "Upstream", "Downstream"). |
| `valid_from` | String | YYYY-MM-DD | Not Null | Sector definition start date. |
| `valid_to` | String | YYYY-MM-DD | Nullable | Sector definition end date. |
| `reviewed` | Integer | `0` or `1` | Not Null | Manual audit flag. |
