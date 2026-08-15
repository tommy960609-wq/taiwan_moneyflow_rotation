# Known Issues（現況版,2026-07-22 M10 訊號選擇性修正後更新）

完整證據與逐項現況查核見 `docs/open_issues_audit_2026-07-19.md`(原始稽核)、
`docs/Milestone_8_Smallfix_Report.md`(本次修復細節)。本檔僅列現況仍為「未解決」或
「部分解決」且值得下一個 session 注意的項目,已接受為永久限制(P3)的項目不重複列在
此處(見完整報告)。

**進度以 `scripts/backfill_status.py`(M8 新增)為準**——直接數磁碟上
`finmind_<stock_id>.json` 檔案數,不是靠任何 receipt 檔或這份文件裡寫死的數字(那些一
寫下就過期,背景滴灌行程仍在跑)。跑法:`.venv\Scripts\python.exe scripts\backfill_status.py`
(人讀)或加 `--json`(嚴格 JSON)。

## P0（阻擋級,建議優先處理）

1. **法人/融資歷史回補嚴重落後(FinMind 逐股回補角度)**——2026-07-19 M8 session 內用
   `backfill_status.py` 實測: institutional 97/1963(4.94%,較稽核當下的 26/1963 已有
   進展)、margin 2/1963(0.1%,無變化;**2026-07-21 之後仍不變,因為本項是 FinMind
   逐股回補進度,這次沒有動 FinMind 相關程式碼**)。OHLCV 已到 1877/1963(95.62%)。此數字
   會持續變動,下次檢查請重跑 `backfill_status.py`,不要沿用這行文字裡的數字。
   **2026-07-21 補充(不同角度、已解決)**: 融資融券「逐日全市場」歷史缺口已用官方免費
   端點(非 FinMind)補齊——`twse_official_<date>.json`/`tpex_official_<date>.json`
   涵蓋 2026-04-20~2026-07-20 全部 63 個交易日、0 失敗(見
   `docs/Margin_History_Backfill_Report.md`)。這解決的是「逐日全市場快照」缺口,
   跟上面 FinMind「逐股歷史」缺口是兩件不同的事,`backfill_status.py` 新增
   `margin_date_sources` 區塊分開呈現,不要混為一談或誤以為 margin 缺口已全部解決。
2. **訊號選擇性**——M10 已修正 `_grade_new_gainer` 的通用 C 級保底邏輯。現在必須有
   明確 trigger、核心證據與（B 級）廣度證據；rule 7-10 是 fail-closed 否決，unevaluable
   不算通過。62 天重跑產生 78.89%/71.93% 無訊號（未校準/校準），但門檻仍是
   `PLACEHOLDER - UNCALIBRATED`，需獨立 forward window 才能再校準。詳見
   `docs/Milestone_10_Signal_Selectivity_Report.md` §1-2。
3. **回測 headline 仍為負且輸給動能基準**——M10 已讓事件研究可量測，但沒有證明預測能力：
   未校準/校準 C 級 10 日中位數為 -2.7852%/-2.8833%，均低於 -1.2338% 動能基準；
   A/B 沒有已實現樣本。這是目前仍未解決的研究結論，不得當成交易訊號。
4. **DQ 計價口徑問題**——已在 M10 前由 DQ gate 修正並用 62 天完整重跑驗證；未校準與校準
   均 62/62 成功，事件也不再集中於冷啟動/無法交易日。若未來改動 reconciliation 或資料
   口徑，必須重新產生兩模式的完整證據；本次沒有再修改 DQ 方法論。

## P1（資料齊後處理）

- **M10 樣本外資料尚未成熟（2026-07-22）**——M10 訓練窗口截至 7/17，現有新資料只有
   7/20 一天，且沒有後續 10 個評分交易日；Phase 2 已正確回報
   `INSUFFICIENT_OOS_DATA`，不是績效失敗。新日期累積到至少 20 個成熟 OOS 日期後，才可
   以 frozen calibration 重新執行 forward test。

4. **市場環境僅單一多頭期**——60 天回測窗口全程強勢多頭,無空頭/盤整對照,Research Ready
   判定明確 NOT MET 的原因之一。
5. **背景滴灌行程現況**——PID 2924(M5c 啟動)已於 2026-07-18 20:00:44 自然退出,890/1963
   OHLCV。**現役行程 PID 9836**(2026-07-18 22:17 啟動,`--sleep-between 30`,log=
   `outputs/logs/finmind_drip_3.log`)——此記錄已於 M8 補登 `loop/PROJECT_STATE.md`,治理
   記錄缺口(原稽核 #23)視為已補。若 PID 9836 停止,下次 session 需重新確認是否要重啟。

## P2（有空再做）

6. **除權息調整因子覆蓋率隨 OHLCV 擴大而相對下降**——`data/reference/price_adjustment_factors.csv`
   仍是 M7 當時的 31,937 行(516/890 股票),OHLCV universe 已擴大到近 1,877 檔,實際覆蓋比例
   未重新量測,估計更低。
7. **過熱風險 9 子因子仍只實作 3 個**——`src/sector_scoring.py::_compute_overheat_risk`
   只有 breadth/volume-surge/concentration;M7 已建好漲停歷史(`src/limit_up_history.py`)
   但刻意 observe-only 未接線(governance rule #9,等拍板)。
8. **處置股名單仍只有單日快照**（2026-07-18 一天）——5 個端點架構上都不支援歷史查詢,
   回測用今天的名單套用到過去 53 個歷史事件,非真實逐事件狀態。
9. **續漲訊號規則 5/6 恆不可評**——`src/signal_detector.py:414-415`,無資料源規劃。
10. **walk-forward 完全未實作**——全專案 grep `walk.forward`/`walk_forward` 零命中
    (`src/`/`scripts/`/`docs/backtest_methodology.md`),非部分而是完全沒有。

## 已解決（M8,2026-07-19)

## 已解決（M10,2026-07-22）

- **訊號偵測器每天全發訊號的結構性問題**——`_grade_new_gainer` 不再把任意一條通過
  條件當作 C 級；A/B/C 現在有明確核心、trigger、廣度與否決規則，unevaluable 也不會
  被當成通過。完整測試 463/463，實資料 62/62 重跑與限制見
  `docs/Milestone_10_Signal_Selectivity_Report.md`。
- **校準無法量測的冷啟動事件集合**——M10 重跑的事件分布跨 61/62 日期，2026-04-20
  冷啟動日事件為 0；事件 CSV 在校準前後已不同，現在可以觀察校準影響，但績效仍未證明。

- **`run_daily.py` 空市場 `KeyError('market_type')`**——原 P0 #1。已修:
  `scripts/run_daily.py` 在索引 `market_type` 欄位前先檢查欄位是否存在,兩市場皆空時
  乾淨走到 `BLOCKED_MISSING_MARKET`,不再 crash。回歸測試改為斷言修復後行為。
- **`load_excel_leaderboard` 硬編外部路徑**——原 P1 #5/#12。已修:路徑改由
  `config/default.yaml` 的 `reconciliation.leaderboard_dir` 控制(預設值=原硬編路徑,
  行為不變),資料夾不存在時安靜跳過並記 log。
- **`finmind_backfill_summary.json` 過期快照問題**——原 P1 #7。已用
  `scripts/backfill_status.py`(直接數磁碟)取代,不再需要信任任何 receipt 檔案。
- **coverage 套件未安裝**——原 P2 #11。已裝,首次量測見
  `loop/evidence/test_logs/coverage_first_measurement.txt`(核心 86%、全專案 80%,雙雙
  達 spec §28.1 門檻,僅量測未設 gate)。

## 已接受為限制,不預期會修（見完整報告 P3 項目）

TPEx/OTC 指數 FinMind 無資料架構性不可得、MSCI 調整日與題材週維護流程未規劃、個股突破品質/
族群延續性中性回退、FinMind 零價格污染列(已用防呆隔離)、2026-07-14/15 兩天 BLOCKED_LOW_DQ、
除權息調整因子改用還原法(直接調整價資料集不可得)。
- **M11 residual historical-source limitation** (2026-07-22): TPEx OHLCV late-data
  recovery is now covered by the official date-addressable `afterTrading/dailyQuotes`
  action and was verified for 2026-07-21 (10,072 rows). TPEx institutional and index
  endpoints remain latest/limited-date sources, so a future full historical correction
  may still be partial. The existing DATE_MISMATCH/DQ gates remain fail-closed; no old
  or empty payload is substituted.
