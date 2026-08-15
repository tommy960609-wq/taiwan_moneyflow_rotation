# CHANGELOG

## v1.0.0-software-ready-candidate — 2026-07-18 (Milestone 6：正式化)

**候選判定：Software Ready 候選（見 `docs/acceptance_report.md` 最終判定與證據）。
明確 NOT Research Ready、NOT Trading Decision Support Ready。**

### 新增
- `scripts/daily_orchestrator.py`：一鍵每日執行 orchestrator，串接
  fetch → legacy 檔名橋接 → run_pipeline → 訊號 JSONL 附加，四步驟皆 fail-closed。
  三種失敗情境（網路失敗/API 空回應/DQ 黑燈）行為分開處理並有對應測試。
- `scripts/daily_run.ps1` / `scripts/daily_run.bat`：一鍵執行包裝腳本，可接 Windows
  工作排程器無人值守執行（本次交付**不**實際建立排程,設定步驟見操作手冊）。
- `docs/operations_manual.md`：使用者（投資決策者）視角操作手冊——每天怎麼跑、報表
  四張表怎麼讀、常見錯誤對照、資料補齊進度查詢、FinMind 額度特性、排程設定步驟。
- `tests/integration/test_daily_orchestrator.py`（12 tests）：orchestrator 三種失敗
  情境 + 成功路徑 + 例外捕捉的 mock 測試,全程離線。
- `tests/regression/test_run_daily_empty_market_crash.py`（2 tests）：記錄本次交付
  發現、但依治理規則未修復的既有模組 bug（見下方「已知問題」）。
- `README.md` 全面重寫：正確的新環境重現步驟（venv 建立 → requirements 安裝 → 驗證
  → 首跑 → 重現性自查），修正舊版指向錯誤路徑（`Quant-Agent\.venv`）的問題。
- `VERSION`、本 `CHANGELOG.md`。

### 發現但依治理規則未修復的問題（disclosed, not silently patched）
- **`scripts/run_daily.py::run_pipeline` 既有 bug**：當合法橋接檔案（M4 格式)不存在
  且內部舊版 fallback（`DataLoader.fetch_twse_ohlcv_all`/`fetch_tpex_ohlcv_all`）也回傳
  空值時，兩個空 DataFrame 合併後沒有 `market_type` 欄位,導致 `KeyError` 而非預期的
  `BLOCKED_MISSING_MARKET` fail-closed 狀態。已用真實 2026-07-18 執行重現(當時 TWSE/
  TPEx 官方端點尚未發布當天資料),並用 hermetic 回歸測試固定重現步驟。
  orchestrator 自身有 try/except 包住此步驟,不會產生錯誤報表或覆寫舊資料,只是exit
  code/log 顯示 EXCEPTION 而非乾淨的 BLOCKED 狀態。未修復原因：`run_daily.py` 是
  已驗收模組,依規則「禁改已驗收模組既有行為」,超出本里程碑授權範圍。

### 沿用/未變更
- M0-M5c 所有已驗收模組行為完全不變（orchestrator 是外層新檔,只呼叫既有入口）。
- FinMind 背景滴灌補抓（PID 2924）本次交付時發現其實**仍在存活**且持續進度中（見驗收
  報告 §滴灌回補；先前狀態記錄誤判其已死亡,本次交付澄清並保留，未重啟）。

### 測試
- 305 個測試全數通過（291 基準 + 12 orchestrator + 2 回歸），0 失敗、0 跳過。
  Log：`loop/evidence/test_logs/pytest_m6_run_log.txt`。

---

## M0-M5c（詳見各自 `docs/Milestone_*_Acceptance_Report.md` 與 `loop/PROJECT_STATE.md`）

- M0：需求盤點、API 連線乾跑、目錄骨架。
- M1：V1 資料管線（TWSE/TPEx 清理、對帳）。
- M2：特徵工程與評分引擎。
- M3：訊號偵測（新起漲/續漲）與 Excel 四表報告。
- M4：V2 資料層（多市場 fetcher、市場狀態分類、法人/融資特徵）。
- M5a：官方產業分類自動匯入、歷史回補基礎設施、歷史批次管線。
- M5b：FinMind 歷史資料層（雙來源整合、中文產業名稱對照）。
- M5c-prep：既有 merge bug 修復、mock 檔案去遮蔽、歷史批次重跑。
- M5c：事件研究回測核心（`src/backtester.py`、`src/benchmarks.py`）、真實 60 天
  回測（結論：本樣本無證據支持訊號組具增量價值，n<30，單一多頭市場環境）。
