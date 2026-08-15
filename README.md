# Taiwan Moneyflow Rotation System（台股主流族群與資金輪動追蹤系統）

一套在 Windows 環境下每天自動讀取 TWSE/TPEx 行情、法人買賣超、融資券與產業對照資料，
判斷當日新起漲族群、續漲族群、資金輪動狀態的量化研究工具。

**目前版本狀態：見 [`VERSION`](VERSION) 與 [`docs/acceptance_report.md`](docs/acceptance_report.md)（最終判定與已知限制）。**

---

## 1. 環境安裝與重現步驟（新環境從零開始）

### 1.1 需求

- Windows 10/11
- Python 3.11+（本專案開發時使用 3.14.3；`.venv` 已鎖定版本相容的 `requirements.txt`）
- 可上網（僅資料抓取腳本需要；`pytest` 全程離線，不會呼叫任何外部網路）

### 1.2 建立虛擬環境

```powershell
Set-Location "C:\Workspace_CN\taiwan_moneyflow_rotation"
python -m venv .venv
```

### 1.3 安裝依賴

```powershell
& ".venv\Scripts\pip.exe" install -r requirements.txt
```

### 1.4 驗證安裝（跑離線測試）

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
& ".venv\Scripts\python.exe" -m pytest tests -p no:cacheprovider -q
```

預期結果：**291 個測試全數通過**，0 失敗、0 跳過（本次交付時的基準；新增測試會使總數增加，
請以執行當下實際輸出為準，見 `loop/evidence/test_logs/` 下最新的 run log）。

### 1.5 首次執行（產生今天的報表）

```powershell
& ".venv\Scripts\python.exe" scripts\daily_orchestrator.py
```

或直接雙擊 `scripts\daily_run.bat`（等同上述指令的一鍵包裝，見
[`docs/operations_manual.md`](docs/operations_manual.md)）。

首次執行會：
1. 向 TWSE/TPEx 官方 API 抓取當日行情/法人/融資券資料（需要網路）。
2. 把抓到的資料橋接成既有管線讀取的檔名格式。
3. 執行特徵工程 → 評分 → 訊號偵測 → 產生 Excel 報表。
4. 把當日訊號附加進 `outputs\signals\signals_<日期>.jsonl`。

輸出報表位於 `outputs\daily\MoneyFlow_Rotation_<日期>.xlsx`。

### 1.6 重現性自查（依規格書 28.1「相同資料、相同設定重跑結果一致」）

```powershell
& ".venv\Scripts\python.exe" scripts\daily_orchestrator.py --date 2026-07-17 --prev-date 2026-07-16
# 再跑一次同一天，比對兩次輸出的 CSV/Excel 核心數值與排序是否一致
& ".venv\Scripts\python.exe" scripts\daily_orchestrator.py --date 2026-07-17 --prev-date 2026-07-16
```

本次交付已對 2026-07-17 執行過此項自查，結果與方法記錄於
[`docs/acceptance_report.md`](docs/acceptance_report.md) 對應章節。

---

## 2. 每天怎麼用（給非工程師使用者）

見 [`docs/operations_manual.md`](docs/operations_manual.md)：如何一鍵執行、報表四張表怎麼讀、
常見錯誤對照、資料補齊進度怎麼查、FinMind 額度特性、Windows 排程設定步驟。

**先讀這句**：報表上的訊號分級（A/B/C）是**未經校準的研究參考，不是買賣指令**——目前的回測
結果顯示尚無證據支持這套訊號組合具有超越簡單動能基準的增量價值，詳見
[`docs/Milestone_5c_Acceptance_Report.md`](docs/Milestone_5c_Acceptance_Report.md)。

---

## 3. 專案文件索引

| 文件 | 內容 |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | 系統架構 |
| [`docs/data_dictionary.md`](docs/data_dictionary.md) | 資料字典 |
| [`docs/signal_definitions.md`](docs/signal_definitions.md) | 訊號定義 |
| [`docs/backtest_methodology.md`](docs/backtest_methodology.md) | 回測方法（事件定義、無未來函數保證、成本模型、已知限制） |
| [`docs/operations_manual.md`](docs/operations_manual.md) | 操作手冊（每日流程、報表判讀、錯誤對照、排程設定） |
| [`docs/data_catalog_and_risk_log.md`](docs/data_catalog_and_risk_log.md) | 資料來源盤點與風險紀錄 |
| [`docs/acceptance_report.md`](docs/acceptance_report.md) | 最終驗收報告（P0/P1/P2 結果、測試統計、最終判定、後續行動） |
| [`docs/Milestone_*_Acceptance_Report.md`](docs) | 各里程碑驗收報告存檔 |
| [`loop/PROJECT_STATE.md`](loop/PROJECT_STATE.md) | 專案狀態真值（各里程碑 gate 紀錄） |
| [`CHANGELOG.md`](CHANGELOG.md) | 版本變更紀錄 |
| [`VERSION`](VERSION) | 目前版本標記 |

---

## 4. 專案目錄結構（節錄）

```
scripts/
  daily_orchestrator.py     # M6：一鍵每日執行 orchestrator（fetch -> bridge -> pipeline -> signals）
  daily_run.ps1 / .bat      # M6：一鍵執行包裝腳本
  fetch_daily_data.py       # M4：TWSE/TPEx 當日資料抓取
  fetch_history_finmind.py  # M5b：FinMind 歷史資料補抓（含 --sleep-between 慢速滴灌選項）
  run_daily.py              # M1-M5c：核心管線（run_pipeline）
  run_history_pipeline.py   # M5a：歷史批次跑法 + 訊號 JSONL 產生
  run_backtest.py           # M5c：事件研究回測 orchestrator
src/                        # 核心邏輯模組（資料清理/特徵工程/評分/訊號偵測/回測）
config/default.yaml         # 系統設定（含未校準門檻，逐項標註 PLACEHOLDER）
data/                       # 原始/處理後資料、產業對照表（gitignored 內容視 .gitignore 而定）
outputs/                    # 每日報表、log、audit JSON、訊號 JSONL、回測報告
tests/                      # unit/integration/leakage/regression/acceptance/property
docs/                       # 所有文件（見上表）
loop/                       # Loop Engineering 狀態與證據
```

---

## 5. 已知限制（摘要，完整版見驗收報告）

- FinMind 歷史 OHLCV 覆蓋率尚未達 100%（背景補抓持續中，進度見操作手冊第 5 節）。
- 訊號組尚未經歷史回測驗證出正向增量價值（60 天樣本、單一多頭市場環境、n<30）。
- 產業分類仍有少數股票（<2%）無法對應。
- 續漲族群訊號兩條規則（次龍頭接棒、高檔爆量不漲）目前無資料來源，恆為 unevaluable。

不隱藏、不美化——完整清單見 `docs/acceptance_report.md` 的「未解問題」與「限制」章節。
