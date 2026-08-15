# CODEX 交辦書:盤後資料延遲自動補漏(Auto-Backfill on Late Official Data)

| 欄位 | 內容 |
|---|---|
| 交辦日期 | 2026-07-22 |
| 專案 | `C:\Workspace_CN\taiwan_moneyflow_rotation` |
| 實作者 | Codex |
| 驗收者 | Claude(對抗式,五步驗收法) |
| 變更性質 | 排程/編排層(orchestrator)行為擴充 — 缺口偵測 + 逐日補跑 |
| 測試基準 | 動工前先親跑 `.venv\Scripts\python.exe -m pytest tests -p no:cacheprovider -q` 確認綠燈基準數,寫進報告 |
| 使用者拍板 | 方案 =「改晚一點跑 + 自動補漏」(2026-07-22) |

---

## 1. 一頁問題陳述(讀這段就懂為什麼要改)

**現象**:今天 7/22 排程跑了 `daily_run.bat`,但沒有 7/22 報告,連 7/21 都沒有;最新報告停在 7/20。

**已對證的根因(非臆測)**:
- 7/22 audit(`outputs/logs/audit_2026-07-22.json`)= `BLOCKED_MISSING_MARKET`,`prices_twse_official: 0`、`prices_tpex_official: 869`。上櫃有、法人/融資有,**只有上市(TWSE)股價當日一筆都沒抓到**。
- 直接打 `openapi.twse.com.tw/v1/exchangeReport/MI_INDEX`,自報日期是 `1150721`(民國 115/07/21 = 西元 **2026-07-21**)。也就是 **7/22 17:16 當下,TWSE 免費 OpenAPI 供的還是 7/21 的收盤資料,7/22 尚未放出**。
- 系統把整天擋掉是**正確的 fail-closed 行為**(拒絕用殘缺/舊資料冒充當日)。問題不在 fail-closed,而在**沒有補漏機制**:當某天因資料延遲被擋,之後沒有任何流程回頭在資料放齊後把它補跑出來。

**下游後果**:每逢 TWSE 盤後延遲(這個免費端點常態現象,7/20 也發生過),當天就沒報告;而且該日**永久缺漏**,因為隔天的排程只跑隔天、不回補昨天。

**這批工作的目標**:讓編排器(orchestrator)具備兩個能力——
1. **缺口偵測**:每次執行時,先掃出「最近 N 個交易日內、狀態不是 SUCCESS 的日子」。
2. **就緒才補、沒就緒就跳過**:對每個缺口日,先探測「TWSE 官方端點的資料是否已放齊到該日」;放齊才補跑,沒放齊則跳過留待下一輪,**絕不硬跑、絕不用舊資料冒充**。

配合使用者拍板,排程時間也要改晚(見 §7,屬指令建議,不自動改系統排程)。

---

## 2. 現況對碼定位(先讀懂再改,行號以現檔為準)

檔案:`scripts/daily_orchestrator.py`
- `_most_recent_weekday(d)`(:90):只把週末往前退成工作日,**不知道哪天成功/失敗**,無補漏概念。
- `_auto_detect_prev_date(output_dir, trade_date)`(:96):已有「掃 `outputs/logs/audit_<date>.json`、找 status==SUCCESS」的成熟範式 —— **缺口偵測請沿用同一套掃描/解析邏輯**,不要另造一套。
- `run_daily_orchestration(...)`(:130):目前只處理**單一** `trade_date`。fetch→bridge→pipeline→signals 四步都圍繞單日。回傳 summary 並寫 `orchestrator_summary_<date>.json`。
- `main()`(:290):argparse 有 `--date/--prev-date/--data-dir/--output-dir/--receipts-dir`;`sys.exit(summary["exit_code"])`。

fetch 進入點:`scripts/fetch_daily_data.py::run_single_day(trade_date, receipts_dir=None)`(:31)。

「官方資料自報日期」既有工具:`src/data_fetcher.py::extract_payload_date(category, payload)`(:171)。**注意坑(見 §3.3)**:此函式對 dict 走 `payload.get("date")`,對 list-of-rows 走 `sample["Date"]`。MI_INDEX 實際回傳的形狀與欄位名**必須由 Codex 實打一次確認**,不可假設。

---

## 3. 設計方向(核心變更)

在 orchestrator **外層**加一個「補漏編排」,把既有的 `run_daily_orchestration`(單日)當成被呼叫的原子單位重複使用。**單日邏輯一行都不要改語意**。

### 3.1 新增:缺口偵測

新函式(建議 `_find_backfill_gaps(output_dir, lookback_days, today)`):
- 產生「今天回推 `lookback_days` 個**日曆日**內的所有工作日(跳週末)」清單。
- 對每個工作日 D,讀 `outputs/logs/orchestrator_summary_<D>.json`(沒有則讀 `audit_<D>.json`);判定該日是否已 `SUCCESS`。
- 回傳「非 SUCCESS 的工作日」由舊到新排序 = 待補清單。
- **休市日處理**:台股國定假日不在週末者(如農曆年、雙十),官方端點會回空。這種日子**不該被當成缺口無限重試**。判定規則:若某工作日的官方端點對「該日」明確回「休市空回應」(`is_holiday_response` 為真)且已探測過,標記為 `HOLIDAY_SKIP` 不再列入缺口。**實作前先想清楚:如何區分「休市回空」與「延遲尚未放齊」——兩者官方都可能回空**。建議:靠 §3.3 的「官方最新已放日期」判斷——若官方最新已放日期**已越過** D 但 D 當天仍空,才可判 D 為休市;若官方最新已放日期**尚未到** D,則是延遲,保留於缺口待下一輪。這段邏輯是本批最容易出錯處,**必須有測試覆蓋**(見 §6)。

### 3.2 新增:逐日補跑迴圈

- 對待補清單中每個 D(由舊到新):
  1. 先做 §3.3「就緒探測」:TWSE 官方是否已放齊到 D?
  2. **就緒** → 呼叫既有 `run_daily_orchestration(trade_date=D, prev_date=None, ...)`(prev_date 交給既有 `_auto_detect_prev_date` 自動抓,它會找 D 之前最近的 SUCCESS)。
  3. **未就緒** → 記錄 `DEFERRED_NOT_READY`,跳過,不呼叫 fetch/pipeline,**不產生任何 BLOCKED audit 汙染紀錄**(見 §4 硬約束 4)。
- 「今天」本身也是待補清單的一員(今天若還沒 SUCCESS 就是缺口)。因此**不需要**另外特別處理今天;今天走同一條就緒探測。
- 迴圈全程 fail-closed:任一天丟例外,記錄該天 EXCEPTION、繼續下一天,不讓單日失敗炸掉整批。

### 3.3 就緒探測(本批最關鍵、最易踩坑)

目標:回答「TWSE 官方 OpenAPI 目前供到哪一天?是否 ≥ D?」

- **不可假設 MI_INDEX 或 STOCK_DAY_ALL 的回傳形狀**。Codex **必須**先實打這兩個端點各一次,把真實 JSON 樣本存到 `loop/evidence/raw_samples/`(檔名註明抓取時戳),據實決定用哪個端點、哪個欄位判定「官方最新已放日期」。
  - 已知線索(仍須親驗):MI_INDEX 於 2026-07-22 17:16 回傳的列含中文欄位「日期」值 `1150721`。`extract_payload_date` 目前對 dict 走 `.get("date")`、對 list 走 `sample["Date"]` —— **中文欄位「日期」不在其中**,直接套用可能回 None。這正是坑。
- 探測函式(建議 `_twse_official_latest_date() -> Optional[str]`)須:
  - fail-closed:網路失敗/解析不出日期 → 回 None,呼叫端一律視為「未就緒」跳過(絕不因探測失敗就放行硬跑)。
  - 回傳 ISO `YYYY-MM-DD`。就緒判定:`latest_date >= D`。
- **禁止**用 FinMind 做任何探測或備援(使用者額度已用完,已於先前拍板全面移除;`run_daily.py` 內 FinMind fallback 為 DISABLED 狀態,不得復活)。

### 3.4 對外介面

- `main()` 新增旗標(預設值要讓「無參數執行」= 自動補漏最近 N 天 + 跑今天):
  - `--backfill-lookback-days N`(建議預設 **5**,足以涵蓋一個含週末的空窗;標 `# DEFAULT - 可調`)。
  - `--no-backfill`:只跑單日(維持舊行為,給手動指定 `--date` 時用)。
  - 當使用者明確給 `--date` 時,維持**單日**語意(不觸發補漏迴圈),與現行為相容。
- 回傳/退出碼語意(整批):
  - 有任一天成功產出報告 → exit 0。
  - 無任何天就緒(全部 DEFERRED)→ exit 0 但 summary 標明「本輪無就緒缺口,已跳過等待下一輪」(這**不是**錯誤,是正常等待)。
  - 真正的 fetch/pipeline 例外才給非 0。
  - **明確定義並在報告列出**每種情境的 exit code,對照 `daily_run.ps1` 既有 switch(0/1/2/3)語意,不要讓 .ps1 的訊息與新語意矛盾。

---

## 4. 硬性約束(違反=退件)

1. **確定性護城河零改動(使用者 2026-07-22 拍板釘死)**:`run_pipeline`(單日管線)、`src/backtester.py`、`src/benchmarks.py`、`src/signal_detector.py`(偵測器)、`src/threshold_calibration.py`、事件抽取規則 —— **一行不改**。這批**只碰排程/編排外層**(`scripts/daily_orchestrator.py` 新增缺口偵測與逐日補跑迴圈、`scripts/fetch_daily_data.py` 若需就緒探測輔助),**不得**觸碰上述任何單日管線/偵測器/回測檔。驗收會以 `git diff --stat` 逐檔核對:上述檔案清單若出現在 diff 中即**直接退件**。
2. **fail-closed 不得弱化**:探測不到官方日期、或官方未放齊 → 跳過該日,**絕不用舊資料/空資料冒充當日產報告**。既有 `BLOCKED_MISSING_MARKET` 護欄保留。
3. **不碰 FinMind**:不得以任何形式(探測、備援、補資料)呼叫 FinMind。
4. **未就緒的日子不得留下汙染紀錄**:DEFERRED 的日子**不可**跑 fetch→pipeline 再產生一份 `BLOCKED_MISSING_MARKET` 的 audit(那會把「還沒到、正常等待」誤記成「壞掉被擋」,污染缺口偵測與帳)。就緒探測要在呼叫 fetch **之前**擋下。
5. **休市日不得無限重試**:見 §3.1;需能穩定判定 HOLIDAY_SKIP,且此判定必須基於「官方最新已放日期已越過 D 但 D 仍空」,不可寫死節日表。
6. **冪等**:對「已 SUCCESS 的日子」重跑補漏,不得重複產出/破壞既有報告 —— 已 SUCCESS 的日子直接跳過,不列入缺口。
7. **不動 Quant-Agent 夜跑檔**:本專案獨立目錄,不碰 `C:\Workspace_CN\Quant-Agent\` 任何檔案。橋接契約(輸出檔名/欄位)不變。
8. **向後相容**:`--date`/`--prev-date` 手動單日路徑、`daily_run.bat`/`daily_run.ps1` 既有呼叫方式與 exit code 語意不得破壞。既有測試若因新增迴圈而斷言需調整,**改成反映新正確行為的斷言,不得直接刪測試**,每處變更在報告列「舊斷言→新斷言 + 為什麼舊的不再適用」。
9. **新常數標註**:`backfill_lookback_days` 等一律 `# DEFAULT - 可調`,不得宣稱經校準/最佳化。
10. 禁 commit;缺資料禁填 0 或當通過;不背誦端點形狀,一律以實打樣本為據。

---

## 5. 必須交付的驗證證據(這批的價值 = 證明「延遲會自動補、就緒才補」)

### 5.1 就緒探測實證(最關鍵)
- 附 §3.3 實打的 MI_INDEX / STOCK_DAY_ALL 原始樣本路徑,與「你據哪個欄位判官方最新已放日期」的說明。
- 一段可重現的 dry-run 輸出:當下 `_twse_official_latest_date()` 回什麼日期(對照現實:7/22 傍晚應回 `2026-07-21` 或更早,證明它能正確辨識「7/22 尚未放齊」)。

### 5.2 缺口偵測正確性
- 對現況(7/20 SUCCESS、7/21 缺、7/22 缺)跑缺口偵測,列出待補清單。**預期**:含 2026-07-21、2026-07-22;不含 7/20。
- 至少一組合成情境測試:中間夾週末、夾一個休市日,證明週末不列缺口、休市日走 HOLIDAY_SKIP、延遲日留在缺口。

### 5.3 逐日補跑行為(用注入 mock/stub,不打真網路)
- **就緒 → 補跑**:stub 探測回「已放齊」,驗證對缺口日呼叫了 `run_daily_orchestration`。
- **未就緒 → 跳過且不汙染**:stub 探測回「未放齊」,驗證**沒有**呼叫 fetch、**沒有**產生該日 BLOCKED audit,summary 標 DEFERRED。
- **冪等**:已 SUCCESS 日不重跑。
- 沿用既有測試注入範式(`fetch_fn`/`bridge_fn`/`pipeline_fn` 參數已支援 stub;新迴圈也要可注入探測函式以便測試)。

### 5.4 端到端(可選但加分,誠實標註是否真打網路)
- 若執行當下 TWSE 已放齊 7/21:實跑一次,證明 7/21 報告被自動補出(附 `outputs/daily/MoneyFlow_Rotation_2026-07-21.xlsx` 與 audit=SUCCESS)。
- 若當下仍未放齊:誠實標「7/21 官方尚未放齊,本輪正確跳過(DEFERRED)」,附 summary 佐證 —— 這同樣是通過(證明 fail-closed 正確)。

### 5.5 全測試綠燈
- 動工前基準數 + 動工後(含新增)全綠;收據 `loop/evidence/test_logs/pytest_auto_backfill_run_log.txt`(pytest 最後幾行原文)。

---

## 6. 測試要求(離線,不打真網路)

- **缺口偵測**:給定一組合成 `orchestrator_summary_*.json`/`audit_*.json`,驗證待補清單=預期(含延遲日、排除已 SUCCESS、排除週末)。
- **休市 vs 延遲的區分**(最易錯,必測):
  - 官方最新已放日期 > D 且 D 空 → HOLIDAY_SKIP。
  - 官方最新已放日期 < D 且 D 空 → 留在缺口(DEFERRED),下一輪再試。
- **就緒探測 fail-closed**:探測函式回 None(模擬網路/解析失敗)→ 該日視為未就緒跳過,絕不放行。
- **逐日迴圈**:就緒補跑、未就緒跳過不汙染、冪等跳過 SUCCESS、單日例外不炸全批 —— 各一測。
- **相容性**:`--date` 單日路徑仍走舊行為(不觸發補漏);`--no-backfill` 生效。
- **既有 orchestrator 測試**全數維持綠燈(或依 §4-8 規則調整斷言並列出對照)。

---

## 7. 排程改晚(指令建議,Codex 不自動改系統排程,列給使用者拍板)

- **使用者已拍板確切時間(2026-07-22):Windows Task Scheduler 同一支 `daily_run.bat`(無參數 = 自動補漏 + 跑今天)分三段觸發 — `18:30`、`20:00`、`22:00`。** 理由:此免費端點的盤後放齊時間不固定,補漏為冪等,多跑無害 —— 早時段補到就補,補不到的晚時段再補;哪段補到算哪段。
- **使用者已拍板:Codex 只把上述三時段寫進 `docs/operations_manual.md` 的排程建議說明(多時段 + 自動補漏如何運作),並在完工報告附上「使用者需在 Task Scheduler 手動設定的三個觸發時間清單」。嚴禁在程式內自動建立/修改/刪除任何 Windows 排程任務(`schtasks`、Task Scheduler COM、`Register-ScheduledTask` 等一律不得呼叫)。**
- `daily_run.bat`/`.ps1` 若需配合(例如無參數即自動補漏)要調整,務必保留既有「帶日期參數 = 單日」用法。

---

## 8. Claude 驗收會查的重點(先講明,誠實留痕)

1. 就緒探測是**真的實打端點取樣**決定欄位,不是假設 MI_INDEX 形狀;7/22 傍晚能正確判「7/22 尚未放齊」。
2. 未就緒的日子**確實沒有**跑 fetch/pipeline、沒有留下 BLOCKED audit 汙染。
3. 休市日與延遲日的區分邏輯正確、有測試,且非寫死節日表。
4. 單日管線內部(pipeline/backtester/signal_detector/校準/事件規則)**零改動**(`git diff --stat` 佐證)。
5. 冪等:已 SUCCESS 日不被重跑破壞。
6. FinMind 沒有以任何形式復活。
7. 既有測試斷言若變更,每處都有正當理由,無直接刪除弱化。
8. `--date` 單日相容路徑與 exit code 語意未破壞。

---

## 9. 完工回報格式

pytest 動工前基準數與動工後最後幾行原文、就緒探測的實打樣本與 dry-run 日期輸出、缺口偵測對現況(7/20/7/21/7/22)的結果、逐日迴圈四情境的測試證據、`git diff --stat`(證明單日核心零改動)、既有測試斷言變更清單(舊→新+理由)、排程建議與使用者需手動設定的觸發時間清單、誠實結論與已知限制。誠實優先:寧可回報「7/21 官方尚未放齊、本輪正確 DEFERRED」也不要為了展示而硬產。
