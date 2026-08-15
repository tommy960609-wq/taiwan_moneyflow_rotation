# 自動補回盤後晚到資料：設計變更與驗收報告

日期：2026-07-22  
範圍：`scripts/daily_orchestrator.py`、`scripts/daily_run.ps1/.bat`、`scripts/fetch_daily_data.py`、操作手冊與補漏測試  
不在範圍：訊號偵測、門檻校準、回測、DQ gate 內部規則、FinMind、Windows 工作排程器實體設定

## 1. 結論先行

自動補漏機制已完成，且完整測試通過。它會先確認官方資料真的到齊，再按日期由舊到新補跑；資料還沒公布時只記錄等待，不會抓空資料或製造 BLOCKED audit。手動重新執行同一個 `daily_run.bat` 也會把補正資料落盤並重新產出該日報表。

本次 7/22 現場 dry-run 的判定符合預期：缺口是 7/21、7/22；官方 TWSE 最新日是 7/21；7/21 判為 READY，7/22 判為 `DEFERRED_NOT_READY`。

真實 E2E 首次嘗試補 7/21 時確實被既有 TPEx 最新日端點的日期檢查擋下；本次已補上 TPEx 官方網站的「指定日期歷史行情」路徑，保留日期檢查後成功寫入 10,072 筆 TPEx OHLCV，並產出 `MoneyFlow_Rotation_2026-07-21.xlsx`。7/22 因官方就緒探針仍只回報 7/21，維持 `DEFERRED_NOT_READY`，不抓未公布資料。

## 2. 基線與修改後測試

| 項目 | 結果 | 證據 |
|---|---:|---|
| 修改前完整基線 | **471 passed** | `loop/evidence/test_logs/pytest_auto_backfill_baseline_run_log.txt` |
| 新增補漏測試 | **12 passed** | `tests/integration/test_auto_backfill.py` |
| 新增 TPEx 歷史補正測試 | **4 passed** | `tests/unit/test_tpex_historical_recovery.py` |
| 修改後完整回歸 | **487 passed** | `loop/evidence/test_logs/pytest_historical_tpex_recovery_run_log.txt` |
| 既有測試 assertion | **無刪除、無改寫** | 本次僅新增測試；沒有 old→new assertion 變更 |

## 3. 實作內容

### gap 掃描

`_find_backfill_gaps()` 掃描包含今天在內的 5 個日曆日，排除週末；讀取 `orchestrator_summary_<日期>.json` 或 `audit_<日期>.json`，任何 `SUCCESS` 都視為已完成。成功日因此具備冪等性，不會重抓。

### 官方就緒探針

`_twse_official_latest_date()` 每次探測各呼叫一次：

- TWSE `MI_INDEX`
- TWSE `STOCK_DAY_ALL`

兩個端點任一 HTTP、JSON 或日期解析失敗，整次回傳 `None`（白話：資料不確定就等待）。解析支援 ISO、8 碼西元、7 碼民國日期，以及 MI_INDEX 的中文欄位 `日期`，不再誤把它當成沒有日期。

### 補漏迴圈

- `READY`：呼叫既有 `run_daily_orchestration()` 單日原子流程，日期由舊到新。
- `DEFERRED_NOT_READY`：不呼叫 fetch、bridge、pipeline，也不寫 `audit_<日期>.json`。
- `HOLIDAY_SKIP`：只有官方最新日期已越過該日，且磁碟上已有明確空回應證據時才標記；避免假日無限重試。
- 單日例外：記錄 `EXCEPTION` 後繼續下一個日期。

批次摘要寫入 `outputs/logs/orchestrator_batch_summary_<日期>.json`。exit code 維持 wrapper 可辨識的 0/1/2/3：成功/無缺口/安全等待為 0，fetch 失敗為 1，pipeline BLOCKED 為 2，未預期例外為 3。

### 手動補正的歷史行情落盤

TPEx 的 OpenAPI 行情端點只回最新日；當人工補跑昨天而端點已滾到今天時，不能把今天資料改標成昨天。`scripts/fetch_daily_data.py` 現在在 TPEx OHLCV 失敗且日期不符時，改呼叫 TPEx 官方網站使用的指定日期 POST action `afterTrading/dailyQuotes`，再次驗證回應日期後才寫入既有 `data/raw/ohlcv/tpex_<日期>.json` 格式。成功後沿用既有 bridge、DQ gate 與 pipeline，不改回測或訊號邏輯；失敗仍回傳空值並記錄，不會捏造資料。

### CLI 與排程

- 無參數：自動補漏 + 今天。
- `--date`：維持既有單日路徑，永不觸發補漏探針。
- `--no-backfill`：明確要求舊的單日行為。
- `--backfill-lookback-days N`：可調的日曆回看天數（預設 5，程式內標註 `# DEFAULT - 可調`）。
- `daily_run.bat/.ps1` 向後相容；操作手冊建議人工在 18:30、20:00、22:00 觸發同一個 bat。本次沒有建立或修改 Windows Task Scheduler。

## 4. 現場官方資料證據

### raw samples

- [`mi_index_20260722T203706.json`](../loop/evidence/raw_samples/mi_index_20260722T203706.json)：HTTP 200，payload list；第一列含 `日期: 1150721`。
- [`stock_day_all_20260722T203706.json`](../loop/evidence/raw_samples/stock_day_all_20260722T203706.json)：HTTP 200，payload list；第一列含 `Date: 1150721`。

`1150721` 是民國年格式，換算為 **2026-07-21**。兩個端點都回同一天，因此探針沒有捏造「7/22 已就緒」。

### 不改資料的 dry-run

- [`auto_backfill_dry_run_20260722.json`](../loop/evidence/auto_backfill_dry_run_20260722.json)
- 判定：`gap_dates=[2026-07-21, 2026-07-22]`、`official_latest_date=2026-07-21`、7/21 `READY`、7/22 `DEFERRED_NOT_READY`。
- 模式明確為 `dry_run_no_fetch_no_pipeline`。

## 5. 真實 E2E 結果與限制

真實執行紀錄：[`manual_daily_run_after_historical_tpex_20260722.log`](../loop/evidence/manual_daily_run_after_historical_tpex_20260722.log)，批次摘要：`outputs/logs/orchestrator_batch_summary_2026-07-22.json`，抓取收據：[`fetch_receipt_2026-07-21.json`](../loop/evidence/fetch_receipts/fetch_receipt_2026-07-21.json)。

7/21 的 TPEx OpenAPI OHLCV 雖自報 2026-07-22，但歷史 POST action 回報指定的 2026-07-21 且有 10,072 列，通過日期驗證後寫入；既有 bridge 與 pipeline 隨後成功，`audit_2026-07-21.json` 狀態為 `SUCCESS`，報表為 `outputs/daily/MoneyFlow_Rotation_2026-07-21.xlsx`。7/22 沒有進入 fetch/pipeline，正確記錄 `DEFERRED_NOT_READY`。

本次只修復可指定日期的 TPEx OHLCV 落盤；TPEx 法人/指數的歷史口徑仍受既有端點限制，若日後要做完整歷史補正，需另案設計。這次沒有放寬 DATE_MISMATCH，也沒有用今天資料冒充昨天。

## 6. 變更檔案與核心保護

本次修改：

- `scripts/daily_orchestrator.py`
- `scripts/daily_run.ps1`
- `scripts/fetch_daily_data.py`
- `docs/operations_manual.md`
- `tests/integration/test_auto_backfill.py`
- `tests/unit/test_tpex_historical_recovery.py`
- `loop/CHANGELOG.md`、`PROJECT_STATE.md`、`TASK_QUEUE.md`、`KNOWN_ISSUES.md`、`ACCEPTANCE_MATRIX.md`

未修改：`src/signal_detector.py`、`src/threshold_calibration.py`、`src/backtester.py`、`src/benchmarks.py`、`scripts/run_daily.py`、FinMind 路徑與 Windows 排程器。沒有 commit。

## 7. CLAUDE 複核建議

請優先複核：

1. `DEFERRED_NOT_READY` 是否完全不呼叫單日流程、也不產生 BLOCKED audit。
2. MI_INDEX 中文 `日期` 與 ROC 1150721 的解析是否 fail-closed。
3. 7/21 READY、7/22 DEFERRED 的現場 dry-run 是否與 raw sample 一致。
4. `--date`、`--no-backfill` 是否維持舊 exit code 與單日行為。
5. TPEx 歷史 POST action 是否先驗證自報日期，再以既有 envelope 格式寫入 10,072 列，而非把最新日資料改標。
6. 7/21 報表、audit、fetch receipt 與批次摘要是否互相一致；7/22 是否仍保持 `DEFERRED_NOT_READY`。
