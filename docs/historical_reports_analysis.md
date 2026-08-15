# Historical Reports Analysis & Missing Data Catalog

This document registers the structural audit of the three historical daily leaderboard reports and establishes the missing data catalog required for the V1 rotation system.

---

## 1. Structure Analysis of the Three Historical Reports

We analyzed the historical files located at `C:\Workspace_CN\Quant-Agent\台股漲幅排行/` representing daily market gainer logs:
-   **File 1**: `Report_20260714.xlsx` (301 rows)
-   **File 2**: `Report_20260715.xlsx` (301 rows)
-   **File 3**: `Report_20260716.xlsx` (301 rows)

### 1.1 Sheet Mappings & Schema
Each workbook contains a single sheet named `Report (1)`. The column structures are identical:

| Column Index | Field Name (Chinese) | Field Description | Data Type | Sample Value |
| :--- | :--- | :--- | :--- | :--- |
| **Col A** | 排名 | Daily Gainer Rank | Integer | `1` |
| **Col B** | 代號 | Stock Identifier | String | `"1517"` (Preserves zero-prefixes) |
| **Col C** | 名稱 | Stock Name | String | `"利奇"` |
| **Col D** | 漲跌幅 | Daily return in % | Float | `10.0` (Represents +10% limit-up) |
| **Col E** | 成交額(百萬) | Daily Turnover in Millions TWD | Float | `49.6` |

---

## 2. Missing Data Catalog

The historical reports represent a filtered gainer list (top 300) rather than a full market state. To calculate multi-factor sector scores (relative strength, HHI, volume shares, etc.) and run E2E backtests, the following datasets are missing:

| Missing Category | Specific Missing Columns / Fields | Impact on Scoring / Backtester | Resolution (M1 Source) |
| :--- | :--- | :--- | :--- |
| **Core Prices** | Open, High, Low, Close (Full-market) | Missing entry prices (T+1 Open) and limit-up lockout volume checks. | Mapped to TWSE `STOCK_DAY_ALL` and TPEx `tpex_mainboard_daily_close_quotes`. |
| **Market Scales** | Market Total Volumes & Index Returns | Cannot compute relative strength or HHI concentration without full universe. | Mapped to TPEx daily board totals and TWSE daily summary endpoints. |
| **Institutional Flow** | Foreign Net Buy, Investment Trust Net Buy, Dealer Net Buy | Missing Institutional Flow factor (P1 scoring weight). | Mapped to TWSE RWD T86 and TPEx `tpex_3insti_daily_trading`. |
| **Credit Balances** | Margin Purchase / Short Sale Balance and Changes | Missing Margin factor for retail leverage tracking. | Mapped to TWSE `MI_MARGN` and TPEx `tpex_mainboard_margin_balance`. |
| **Risk Status** | Caution / Disposition Stock Flag List | Backtest cannot apply sizing reduction (50% penalty) on restricted equities. | Mapped to TWSE daily caution announcements. |

---

## 3. Reconciliation Rules
The system will run `reconcile_with_leaderboard` in M1 to cross-check computed stock daily returns from the full-market feed against these Excel rankings:
-   **Tolerance Threshold**: Discrepancies in `return_pct` > 0.05% will flag warnings.
