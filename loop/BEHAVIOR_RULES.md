# Loop Behavior Rules

This document records the strict behavioral constraints and coding standards for this project.

1.  **Embrace Null (擁抱空值)**: If data is missing (e.g., missing institutional flow or margin values), return `None` or structured empty entries and trigger the degraded mode. Never fabricate mock data, zero-fill, or average-fill financial facts in the production pipeline.
2.  **No Future Information Leakage (不可引入未來函數)**: Technical features and signal scoring at day \(T\) must strictly be computed using data available at or before day \(T\) close. Ensure double-dataset comparison tests are run and pass before any release.
3.  **Ticker symbol integrity**: Stock tickers must always be represented as **Strings** to preserve leading zeros (e.g., "0050", "0056").
4.  **No overlapping volume count**: Ensure primary sector volume and secondary sector volume are computed cleanly. Component stock volume should not be double-counted during sector aggregation.
5.  **Reconciliation Guard**: Leaderboard Excel data must only be used as a reconciliation check source. The primary calculations for price moves and rankings must be derived directly from the full-market closing prices.
6.  **Realistic Executions**: Simulating purchases at day \(T+1\) must account for limit-up lockouts. Assuming entries at open is forbidden if the open price matches the daily limit-up price and transaction volume is zero.
7.  **Warning/Disclaimer Enforcements**: Every report output must carry the explicit uncalibrated warning banner: *"Thresholds are placeholder and uncalibrated against Taiwan stock market data"*, unless backtesting calibration is completed and validated.
8.  **Test Evidence Preservation**: Every code modification must trigger verification tests. Test execution logs and evidence files must be saved under `loop/evidence/test_logs/`.
9.  **Fail-Closed Integrations**: All API integrations, including TWSE OpenAPI or TPEx OpenAPI connections, must fail closed. If the server is unreachable or responds with a bad schema, downgrade to a warning or exit cleanly rather than throwing unhandled exceptions.
