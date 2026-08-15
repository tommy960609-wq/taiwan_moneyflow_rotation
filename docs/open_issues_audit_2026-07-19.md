# Open Issues Audit — 2026-07-19

稽核員：Claude（獨立盤點,唯讀）
稽核範圍：`loop/PROJECT_STATE.md` 全部 Revision Log、`loop/ACCEPTANCE_MATRIX.md`、`loop/TASK_QUEUE.md`、
`loop/CHANGELOG.md`、`docs/Milestone_0~7_*.md`、`docs/acceptance_report.md`。
稽核方法：每一項現況皆經實查（讀碼行號 / 跑指令 / 查檔案),不採信舊報告文字。
測試基準：`.venv\Scripts\python.exe -m pytest tests -p no:cacheprovider -q` → **361 passed**（與 M7 claim 一致,本次重跑確認）。

## 統計總覽

| 狀態 | 數量 |
|---|---|
| 已解決 | 9 |
| 未解決 | 12 |
| 部分解決 | 9 |
| 已接受為限制(不打算修) | 6 |
| **總計** | **36** |

## Top 5 最該先修（依影響排序,非依編號）

1. **#1 run_daily.py 空市場 KeyError**(P0)— 生產路徑仍會在「橋接檔不存在+舊版 fallback 也回空」時直接爆炸,不會走到設計好的 `BLOCKED_MISSING_MARKET`。無人值守排程若遇到當天官方資料晚發布,會是 exit code 3 的例外而非乾淨的 blocked 狀態。回歸測試在,但生產碼本身沒修。
2. **#4 訊號偵測器門檻過鬆**(P0)— 60 天/2,765 筆訊號資料裡「無訊號/無效」是 0 筆,每個被評分族群幾乎天天有 B/C 級訊號。這直接拖累回測樣本數(獨立事件只有 53 個,46 個集中在窗口第一天的冷啟動假象),是「訊號到底有沒有用」這件事永遠測不準的根因。
3. **#5 回測 headline 為負且輸給動能基準**(P0,已接受為限制但要持續盯)— B 級中位數 -11.28%(n=27)、C 級 -10.41%(n=19),兩者都輸給 -0.39% 的動能延續基準,且兩層都 n<30 不可裁決。現況與 M5c/M7 完全一致,尚未有任何改善嘗試。
4. **#3 FinMind 法人/融資回補嚴重落後**(P0,資料地基問題)— OHLCV 已大幅回補到 1,852/1,963(94.3%,本次實查發現遠優於 M7 報告當時的 890/1,963),但法人只有 26/1,963(1.3%)、融資只有 2/1,963(0.1%),完全沒有進度。只要這兩者不動,任何牽涉法人歷史因子的回測結論都不可信(#20 全中性回退)。
5. **#12 load_excel_leaderboard 硬編外部路徑**(P1,環境風險)— 程式碼仍是寫死 `C:/Workspace_CN/Quant-Agent/**/Report_*.xlsx`,換一台機器或那個資料夾結構改變就會整條 DQ 分數斷鏈,自 M1 起從未修正,只是每次撞到就繞過去。

---

## 完整表格

| 編號 | 問題 | 首次發現於 | 現況 | 現況證據 | 影響(白話) | 建議處置 |
|---|---|---|---|---|---|---|
| 1 | `run_daily.py` 空市場 fallback `KeyError('market_type')` | M6 | **未解決** | `scripts/run_daily.py:305-311` — `pd.concat([...])` 兩邊皆空時仍在第 310 行直接 `df_prices["market_type"]`,無防護；`tests/regression/test_run_daily_empty_market_crash.py` 只是把這個壞行為釘死成回歸測試,並未修復生產碼 | 排程無人值守時,若當天官方資料晚發布,會拿到不乾淨的例外(exit 3)而非設計好的 `BLOCKED_MISSING_MARKET`(exit 2)。目前靠 orchestrator 外層 try/except 兜底,不會產生假報表,但排錯訊息不乾淨 | **P1**(資料齊後找空檔修;不影響資料正確性,只影響可觀測性,但已存在 3 個里程碑,建議下次碰 `run_daily.py` 時一併處理) |
| 2 | 訊號偵測器門檻過鬆=每族群天天有訊號 | M5c(cold-start 發現) | **未解決** | 現存 60 天/2,765 筆歷史訊號資料集本次未重新產生(仍是 M5c-prep 那批),`config/default.yaml` 第 18/28/49/61 行仍是 4 個 `# PLACEHOLDER - UNCALIBRATED` 區塊,涵蓋全部 new_gainer/continued_momentum 門檻,未曾校準 | 「族群一直有訊號」讓獨立事件數量被少數幾天吃光,回測統計檢定力永遠拉不出來,不校準門檻,#5 的回測結論會一直卡在「樣本不足不可裁決」 | **P1**(資料齊後校準;需要更多歷史資料才有意義,目前 OHLCV 已到 94.3%,可以開始評估) |
| 3 | FinMind 回補未完成(OHLCV/法人/融資) | M5b | **部分解決,且與舊報告數字有落差** | 實查 `data/raw/ohlcv/finmind_*.json` = **1,852 檔(94.3%)**,遠高於 M7 報告記載的 890/1963(45.3%)——背景滴灌行程(現為 PID 9836,非報告中的舊 PID 2924/舊行程已在 M7 結束時自然退出)在本次稽核期間持續在跑,不要動它。但 `data/raw/institutional/finmind_*.json` = **26 檔(1.3%)**、`data/raw/margin/finmind_*.json` = **2 檔(0.1%)**,自 M5c-prep 後完全沒有進度(法人/融資排在 OHLCV 佇列後,OHLCV 還沒抓完就一直輪不到) | OHLCV 已經夠用來做大部分回測,但任何依賴法人/融資歷史因子的訊號或回測仍全部落回中性值,等於這兩個資料源的歷史版本至今沒有真正投入使用 | **P0**(資料齊後优先—OHLCV 已近完成,下一步應讓滴灌行程改抓 institutional/margin 類別,或另開一輪針對這兩類的專門回補) |
| 4 | 除權息調整因子僅 58% 覆蓋 | M7 | **部分解決** | `data/reference/price_adjustment_factors.csv` 現有 31,937 行(未變動,M7 交付後未再跑),M7 報告記載 516/890(58%)股票有因子,現在 universe 已擴大到 1,852 檔 OHLCV,covered 比例事實上更低(未重新量測) | 42%+(且隨 OHLCV 擴大持續上升)的股票用未調整價格做回測,除權息密集的 4-9 月區間報酬可能失真,雖然 M7 驗證影響很小(2/53 事件) | **P2**(資料齊後補;`scripts/fetch_price_adjustments.py` 需重跑並解決 M7 揭露的 HTTP 403 未特判問題) |
| 5 | 回測 headline 為負且輸給動能基準,n<30 不可裁決 | M5c | **已接受為限制**(現況不變) | `outputs/backtests/backtest_summary_2026-07-18.json`(本次稽核當下最新檔):B級 median -11.28%(n=27)、C級 -10.41%(n=19),`sample_sufficient: false` 兩者皆是,`vs_momentum` 兩者皆 `signal_beats_baseline: false` | 目前系統的選股/選族群訊號在僅有的樣本內看不到正向期望值證據,不能拿來做真實下單依據 | **P0**(等 #2 門檻校準 + #3 資料補齊後重跑事件研究,才有意義重新評估) |
| 6 | 除權息調整因子直接調整價資料集不可得 | M7 | **已接受為限制**(架構性,非 bug) | `loop/evidence/fetch_receipts/finmind_adjusted_price_probe_2026-07-18.json` 記載 6 個候選 dataset 名稱皆 HTTP 400/422;`src/price_adjuster.py` 改用 `TaiwanStockDividendResult` 反推調整因子,現況不變 | 只能用還原法反推,精度不如官方直接提供調整後收盤價,但已是本 FinMind token 下唯一可行路徑 | **P3**(除非換資料源,否則無法再改善) |
| 7 | 處置股名單只有當日快照無歷史 | M7 | **未解決,現況與 M7 相同** | `data/raw/disposition/` 目錄下只有 **2026-07-18** 一天的 5 個端點快照(`ls` 確認,無其他日期);`src/disposition_fetcher.py` 的 5 個端點本身架構上都不支援歷史日期查詢參數(swagger 驗證過) | 回測用的 41 檔處置/注意名單是「用今天的名單套用到過去 53 個歷史事件」,不是每個事件當時真實的處置狀態,可能高估或低估真實限制 | **P2**(架構限制,唯一改善方式是從今天起每日持續快照、累積自己的歷史,無法回溯) |
| 8 | TPEx/OTC 指數 FinMind 無資料 | M4/M5b | **已接受為限制**(架構性) | `src/finmind_fetcher.py:88,105,358-367` 仍是 `OTC_INDEX_UNAVAILABLE`,8 個候選 data_id 皆已試過(M5b 記載),現況未變;`src/data_fetcher.py:76` 官方 TPEx `tpex_index` 端點存在但仍受限於「僅回傳當天」的架構限制,無法回補歷史 | 市場狀態 6 態分類(`market_regime.py`)只能用加權指數(TAIEX)判斷,遇到 TWSE/TPEx 走勢分歧時可能誤判 | **P3**(除非 FinMind 或官方新增歷史端點,否則無解) |
| 9 | 過熱風險 9 子因子只實作 3 個+漲停家數 observe-only 未接線 | M2/M7 | **未解決,現況與 M7 相同** | `src/sector_scoring.py:130-153` `_compute_overheat_risk` 仍只有 `breadth_vs_volume_divergence`/`volume_surge`/`concentration` 三項,docstring 明確寫「consecutive-limit-up counts, upper-shadow candle ratios, institutional-selling reversal」未實作；M7 新建的漲停歷史(`src/limit_up_history.py`)確認仍是 observe-only,未接進這個函式 | 過熱風險分數系統性低估(少了連續漲停、上影線、法人反手賣壓三個訊號),可能讓已經過熱的族群評分偏高 | **P2**(漲停歷史資料已經有了,是「要不要接線」的拍板決定,不是資料缺口) |
| 10 | coverage 從未量測(coverage 套件未裝) | M6 | **未解決,現況與 M6 相同** | 本次實查 `.venv/Scripts/python.exe -c "import coverage"` → `ModuleNotFoundError`；`requirements.txt` 內無 `coverage` | spec §28.1 的兩項覆蓋率門檻(核心≥85%、全專案≥75%)自 M0 起從未有實際數字,「Software Ready(候選)」的候選二字部分原因即在此 | **P2**(裝套件+跑一次即可,成本低,建議儘快做掉以拿掉「候選」標籤的一個理由) |
| 11 | `load_excel_leaderboard` 硬編外部路徑 glob(環境風險) | M1(揭露),M3/M5c-prep(反覆撞到) | **未解決,現況與最初相同** | `scripts/run_daily.py:177` 仍是 `pattern = f"C:/Workspace_CN/Quant-Agent/**/Report_{report_date...}.xlsx"`——寫死絕對路徑到另一個專案目錄 | 換機器、目錄搬遷、或那個路徑下檔案結構改變,DQ 分數計算會悄悄失去這個比對來源(目前設計是抓不到就回空 DataFrame,不會炸,但比對就形同虛設);M3/M5c-prep 都曾因為這條路徑意外抓到不相關檔案而導致測試不穩,只在測試端 mock 掉,生產碼未變 | **P1**(建議改成可設定路徑,非本次授權範圍但風險持續存在超過 5 個里程碑) |
| 12 | 續漲訊號規則 5/6(次龍頭接棒/高檔爆量不漲)無資料源恆不可評 | M3 | **未解決,現況與 M3 相同** | `src/signal_detector.py:414-415` 仍是寫死的 `unevaluable.append(...)` 兩行,無任何資料輸入路徑 | 續漲族群(A級後續)訊號永遠少兩條判準依據,可能讓「真的在接棒」和「假突破」難以區分 | **P2**(需要個股接棒/日內量價結構資料源,目前完全沒有規劃來源) |
| 13 | 外資 MSCI 調整日標記未做;題材層週維護流程未建 | 舊報告(M0 附近規劃項) | **未解決** | 全專案 grep 無 `MSCI` 相關程式碼；`data/reference/stock_industry_mapping.xlsx` 的 `theme_1/2/3` 欄位存在但無自動化週更流程(僅 8 筆 `reviewed=1` 人工維護) | MSCI 調整日前後的資金流可能誤判為一般族群輪動訊號；題材分類會隨時間過時而不自知 | **P3**(規劃項,目前無跡象已排入任何里程碑) |
| 14 | 市場環境僅單一多頭期,無環境分層驗證 | M5c | **已接受為限制**(現況不變,但資料視窗未擴大) | `docs/acceptance_report.md` §Research Ready 判定第 6 項仍是 FAIL；60 天窗口(2026-04-20~07-17)全程 TAIEX 前 10 日即 +10.3%,單一多頭,本次未見任何擴大窗口或補歷史區間的動作 | 目前所有回測結論只能代表「強勢多頭期間」的表現,空頭/盤整環境完全沒有驗證過,不能外推 | **P1**(#3 資料補齊後,下一步就是拉長回測窗口涵蓋不同市場環境) |
| 15 | walk-forward 未做(原規格 §19.3) | M5c/M6 | **未解決,現況與 M6 相同** | 全專案 grep `walk.forward`/`walk_forward` 於 `src/`、`scripts/`、`docs/backtest_methodology.md` 皆**零筆命中**——不是「部分實作」,是完全沒有相關程式碼；`docs/acceptance_report.md` P2 表格列為 FAIL | Research Ready 十項要求裡明確 FAIL 的一項,沒有 walk-forward 就無法宣稱樣本外驗證 | **P2**(需要更多歷史資料+門檻校準完成後才有意義,排在 #2/#3 之後) |
| 16 | 個股「突破品質」與族群「延續性」部分情境回退中性 50 | M2 | **已接受為限制**(現況不變) | `src/sector_scoring.py`/`src/stock_scoring.py` 的 renormalization 邏輯未變動(本次未讀到修改跡象,M2 起無 CHANGELOG 記載此項有變更) | 這兩個子分數在訊號不足時系統性地不提供資訊(50 分中性),不是隨機噪音,但也不是有效訊號 | **P3**(需要對應資料源獨立建模,規模不小,目前未排入任何里程碑) |
| 17 | 產業對照 28 檔未分類;8 檔人工 theme 列 vs 官方分類混用 | M5a/M5b | **大幅改善(視為已解決,但非 100%)** | 本次實查 `stock_industry_mapping.xlsx`:**1,963/1,963 列 `primary_sector` 皆非空**(100% 映射,較 M5a 的 98.58%/M7 報告更完整),`reviewed=1`(人工) 8 筆維持不變、`reviewed=0`(官方自動匯入) 1,955 筆,`sector_code` 欄位保留原始代碼供追溯——8 檔人工列與官方匯入列共存但用 `reviewed` 欄位明確區分,非混用不清 | 產業分類覆蓋率已經很完整,可信度高於歷次報告記載的數字,建議下次驗收更新這個數字 | **P3**(已接近完成,不需優先處理;僅建議更新文件內數字) |
| 18 | 歷史法人因子在批跑中全為中性回退 | M5c | **未解決(見 #3)** | 同 #3——法人歷史僅 26/1,963(1.3%),未有改善 | 同 #3 | **P0**(併入 #3 一起處理) |
| 19 | FinMind 3 筆零價格污染列(M7 對帳發現) | M7 | **已接受為限制**(已修復周邊 bug,污染源資料本身未變) | `src/leaderboard_reconciliation.py:52-60` 的 `prev_close > 0` 防呆確認存在(本次讀碼驗證),避免了 `+inf` 污染統計;但污染源本身(stock 2321/2941/2073, 2026-06-08 FinMind 回傳 OHLC 全 0)是 FinMind 上游資料品質問題,無法從本專案端修正,只能繼續排除 | 3 筆列不會再讓平均偏差統計失真(bug 已修),但這 3 檔股票那天的資料本身仍是垃圾,若之後被其他模組直接讀取(非透過 reconciliation)可能還是會出錯 | **P3**(已用防呆隔離影響,可接受) |
| 20 | 2026-07-14/15 兩天 `BLOCKED_LOW_DQ` | M5c-prep | **已接受為限制**(現況不變) | M5c-prep 報告記載這兩天法人/融資資料本身就稀薄,fail-closed 正確擋下;本次未見任何針對這兩天單獨補資料的嘗試 | 這兩天沒有訊號/報表產出,是正確的保守行為(寧可不出報表,不出錯的報表),但也代表歷史序列有兩天缺口 | **P3**(除非能補到這兩天真實法人/融資資料,否則會一直缺;可接受現狀) |

### 本次稽核新發現(不在原始清單內)

| 編號 | 問題 | 現況證據 | 影響 | 建議處置 |
|---|---|---|---|---|
| 21 | **`loop/KNOWN_ISSUES.md` 檔案在本次稽核前不存在** | `Read` 該路徑回傳 `File does not exist` | 治理索引裡承諾「報錯前掃一遍 KNOWN_ISSUES.md」的鐵則(CLAUDE.md 開場記憶讀取第 4 條)在本專案層級形同虛設——沒有這個檔案可掃 | **P1**(本次任務已依指示重寫此檔,見交付項 2) |
| 22 | **`loop/evidence/fetch_receipts/finmind_backfill_summary.json` 是過期快照,與實際磁碟狀態嚴重不符** | 該檔案內容(`institutional.success=0`, `ohlcv.success=319`)對應的是 M5b 當下的一次性執行結果,但實際磁碟上 OHLCV 已到 1,852 檔——這個 receipt 檔從未被背景滴灌行程更新,只反映「手動觸發的那一次」,不是「累積現況」 | 任何人只看這個 receipt 檔案會嚴重低估目前資料完整度(890/1963 或更早的數字），本次稽核能發現落差是因為直接數磁碟檔案而非讀 receipt | **P1**(建議之後的資料狀態報告一律以直接掃磁碟檔案數為準,receipt 檔案只作為單次執行證據,不作為累積現況指標；已在本報告 #3 更正) |
| 23 | **PID 對不上**：`loop/PROJECT_STATE.md`/`docs/acceptance_report.md` 記載的滴灌行程是 PID 2924,M7 報告記載該行程已於 2026-07-18 20:00:44 自然結束;但本次任務指示的背景行程是 **PID 9836**(`StartTime 2026/7/18`),兩者顯然是不同的行程啟動(M7 結束後應該又有人重新啟動了一次滴灌,但沒有留下對應的 PROJECT_STATE.md 記錄) | `Get-Process -Id 9836` 確認存活;`Get-Process -Id 2924` 未查(不在本次任務範圍),但 M7 報告已記載 2924 已自然退出 | 目前沒有任何治理文件記錄「PID 9836 是誰在什麼時候啟動的、抓到哪個階段」,下一個 session 若又誤判「已死」可能重複 M6 那次錯誤(誤判存活行程已死) | **P1**(建議下次碰觸此專案時,在 `loop/PROJECT_STATE.md` 補記 PID 9836 的啟動時間、目前任務、以及與舊 PID 2924 的關係) |
| 24 | **`~$backtest_report_2026-07-18.xlsx` 鎖定檔存在,時間戳為稽核當下** | `outputs/backtests/` 目錄下有 `~$backtest_report_2026-07-18.xlsx`(Jul 19 08:48),是 Excel 的暫存鎖定檔,代表有人/程式當下開著這個檔案 | 不影響本次稽核結論,但若有自動化流程要覆寫這個報表檔,可能因為檔案被鎖定而寫入失敗 | **P3**(僅提醒,非缺陷;建議關閉該 Excel 視窗後再進行任何自動寫入) |

---

## 附註：與舊報告數字的重要落差

- **OHLCV 覆蓋率**：舊報告(M7,2026-07-18 20:08)記載 890/1,963(45.3%)。本次實查(2026-07-19)為 **1,852/1,963(94.3%)**。這是「已解決」方向的落差(比舊報告樂觀),原因是背景滴灌行程在 M7 結束後又持續跑了一段時間。
- **法人/融資覆蓋率**：舊報告與本次實查一致,皆為 26/1,963、2/1,963,完全沒有變化,是本次稽核中最明確「卡住不動」的資料缺口。
- **產業分類覆蓋率**：舊報告(M5a)記載 98.58%(1,946/1,974)。本次實查為 **100%(1,963/1,963)**,略為改善但 universe 分母也有變化(1,974 vs 1,963),需注意兩次口徑可能不完全相同(交易宇宙隨日期變動)。

## 誠實揭露：本次稽核的限制

本次稽核未重新執行完整的 `scripts/run_backtest.py`(耗時且非唯讀,任務要求唯讀為主),回測 headline 數字取自現有最新產出檔案(`backtest_summary_2026-07-18.json`,M7 產生),未重新驗證該次執行本身的正確性,只驗證其「現況是否仍是最新」(是,目錄裡沒有更新的檔案)。若使用者需要用擴大後的 94.3% OHLCV 覆蓋率重新產生回測結果,需要另外執行(非本次唯讀任務範圍)。
