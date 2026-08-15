# Milestone 10：Signal Detector Selectivity 變更報告

**日期**：2026-07-22  
**範圍**：`src/signal_detector.py` 的評級層；未修改特徵計算、門檻校準、DQ、事件回測器、基準線或夜跑入口。  
**驗證等級**：完整 62 天實資料重跑；結果仍是研究性證據，不是可交易訊號。

## 0. 結論先行

這次修正確實讓訊號變得有選擇性：過去每個族群日幾乎都有 B/C，現在大多數列會明確標成「無訊號」。在 DQ gate 修好後，未校準與校準兩條管線都能完整跑完 62/62 天；事件數也從原先 53 個，變成未校準 495 個、校準 631 個，且不再集中在第一天或無法交易日。

這讓「校準是否改變可測事件」第一次可被量到：兩個事件 CSV 不再相同，且每日 704 列的 signal type 發生變化。不過這不是績效改善證明：C 級 10 日超額報酬中位數仍低於動能基準；A/B 級目前沒有任何已實現樣本，不能下結論。

## 1. 修改內容

### 1.1 新起漲評級政策

`_grade_new_gainer` 不再使用「只要任一條件通過就給 C」的寬鬆退路，改成可審計的條件分層：

| 類別 | 規則 | 政策 |
|---|---|---|
| 核心證據 | 1、3、4、5、6 | A/B 的必要證據；rule 3 或 6 其中至少一項作為 B 的廣度證據 |
| 觸發條件 | 2 | A/B/C 都必須明確通過 |
| 安全/資料否決 | 7、8、9、10 | 失敗或資料不可評估時，阻擋 A/B |
| A | 10 條全部通過 | 不允許任何 failed 或 unevaluable |
| B | 觸發通過、至少 3 個核心、含廣度核心、否決條件全確認、一般失敗數不超過 4 | `min_core_passed_for_b=3`、`min_breadth_core_passed_for_b=1` 均標記 `PLACEHOLDER - UNCALIBRATED` |
| C | 觸發 + rule 6 個股強度，但核心不足以達 B；或 UAT-04 單股事件分支 | 不再是任意條件的通用 fallback |
| 無訊號 | 以上皆不成立 | 不捏造評級 |

`MIN_UP_STOCKS_FOR_SECTOR_SIGNAL=2` 保持不變；單一上漲股票最多只可留下 C 級個股事件，不能升為族群級 A/B。`unevaluable` 永遠不算通過。

### 1.2 續漲評級政策

續漲必須同時通過 rule 1 與 rule 4；rule 5/6 若無資料仍可保留訊號，但會降低資料信心。缺少核心條件或出現失敗時改為「無訊號」。

### 1.3 設定與文件同步

- `config/default.yaml` 與 `src/config_manager.py` 同步新增兩個 B 級設計參數。
- `docs/signal_definitions.md` 更新 A/B/C、UAT-04、否決條件與 unevaluable 語義。
- 沒有新增前視資料；評級只讀當日已計算的 passed/failed/unevaluable 結果。

## 2. 62 天訊號分布

日期範圍：2026-04-20 至 2026-07-17；每條管線 2,857 列、62/62 天成功。

| 訊號類型 | M10 前歷史基線（參考） | 未校準重跑 | 校準重跑 |
|---|---:|---:|---:|
| 無訊號 | 0（所有列皆 B/C） | 2,254（78.8939%） | 2,055（71.9286%） |
| C 級個股事件 | 2,567（89.85%） | 558（19.5310%） | 719（25.1663%） |
| B 級早期點火 | 290（10.15%） | 5（0.1750%） | 5（0.1750%） |
| A 級新起漲 | 0 | 0 | 1（0.0350%） |
| 續漲訊號 | 0 | 40（1.4001%） | 77（2.6951%） |

校準前後共 704 列的 `signal_type` 改變；主要轉換為無訊號↔C/續漲，另有 1 列無訊號→B、1 列 B→A。這證明校準有改變評級輸入結果，但不能把分布變化直接當成預測能力。

## 3. 事件可測性與 10 日事件研究

| 指標 | 未校準 | 校準 |
|---|---:|---:|
| 獨立事件 | 495 | 631 |
| 可交易 TRADABLE | 471 | 600 |
| 待資料成熟 PENDING | 24 | 31 |
| 無法交易 UNTRADABLE | 0 | 0 |
| 有第一個事件的日期 | 61/62 | 61/62 |
| 第一個事件日 | 2026-04-21 | 2026-04-21 |
| 最後事件日 | 2026-07-17 | 2026-07-17 |
| 冷啟動日 2026-04-20 事件 | 0 | 0 |

相較 M9 的 53 個事件（46 個集中在冷啟動日），新的評級邏輯已移除「每天都有訊號」造成的事件抽樣死角。校準事件 CSV 的 bytes 已不同，事件研究因此不再是同一批事件的重複計算。

### 3.1 10 日超額報酬 headline

超額報酬均相對同日動能基準；基準中位數為 **-1.2338%（n=51）**。數字為淨交易成本後結果，未成熟事件不填入報酬。

| 模式 / 等級 | 事件數 | 已實現 | 10 日中位數 | 勝率 | 可否判定 |
|---|---:|---:|---:|---:|---|
| 未校準 B | 5 | 0 | — | — | 不可，全部 PENDING |
| 未校準 C | 457 | 378 | **-2.7852%** | 29.10% | C 仍輸動能基準 |
| 未校準 續漲 | 33 | 30 | +0.5203% | 56.67% | 描述性，非因果證明 |
| 校準 A | 1 | 0 | — | — | 不可，PENDING |
| 校準 B | 4 | 0 | — | — | 不可，全部 PENDING |
| 校準 C | 551 | 451 | **-2.8833%** | 29.49% | C 仍輸動能基準 |
| 校準 續漲 | 75 | 63 | -0.3633% | 46.03% | 描述性，未證明校準改善 |

因此，本輪可以回答「校準是否有機會影響事件集合」：**有**；不能回答「校準是否提升預測績效」：**尚未**。C 級仍沒有增量價值證據；A/B 沒有已實現樣本，不能宣稱有效或無效。

## 4. 驗證證據

- 先寫測試後實作：舊寬鬆邏輯下新增選擇性測試先出現 6 個失敗，修正後轉綠。
- 針對訊號偵測器：**25 passed**，`loop/evidence/test_logs/pytest_signal_selectivity_targeted_run_log.txt`。
- 完整專案測試：**463 passed in 121.62s**，`loop/evidence/test_logs/pytest_signal_selectivity_run_log.txt`。
- 加入 Phase 1 配對審計測試後，完整專案回歸仍為 **467 passed in 144.95s**，`loop/evidence/test_logs/paired_calibration_full_pytest_log.txt`；配對工具本身 **4 passed**。
- Phase 2 OOS availability tests **4 passed**；加入 OOS guard 後完整回歸為 **471 passed in 144.80s**，`loop/evidence/test_logs/phase2_full_pytest_log.txt`。
- 編譯檢查：`signal_detector.py`、`config_manager.py`、測試檔均通過 `py_compile`。
- 62 天摘要：`Quant-Agent/_workbench/out/moneyflow_62d_backtest_20260722/selectivity_backtest_summary.json`。
- 事件/回測原始輸出與校準差異分析同一資料夾；摘要由可重跑工具 `Quant-Agent/_workbench/tools/summarize_selectivity_backtest.py` 產生。
- 事件 CSV SHA-256：未校準 `05f6696fdfabbd7a3901c5743512430c1be10bd001b477dc3d3e58a1748c777b`；校準 `f9b8993e3065f034b016e012a9e2e54cd8eaf9857e3c51d4745b6c05e54b3e82`。

## 4A. 配對校準審計（Phase 1）

以 `(trade_date, sector_name, sector_type)` 對齊兩模式的全部 2,857 個族群日，結果如下：

| 配對結果 | 數量 |
|---|---:|
| 兩模式都有同一族群日 | 2,857 |
| 每日 signal type 改變 | 704 |
| 事件集合交集 | 264 |
| 僅未校準成為事件 | 231 |
| 僅校準成為事件 | 367 |
| 交集內同類別 / 類別改變 | 250 / 14 |
| 可配對且已實現的事件 | 228（49 個日期） |

交集事件使用相同的族群日與未來價格，因此校準相對未校準的配對報酬差為 **0.0000 個百分點**，以交易日分群的 95% bootstrap CI 也是 `[0.0, 0.0]`。這不是「校準已被證明無效」，而是證明兩模式的 aggregate 差異主要來自**事件選擇集合改變**，不是同一事件的報酬被校準改寫。

事件集合的選擇差異也不能直接當成因果結果：未校準獨有 C 事件的已實現中位數為 -1.7513%，校準獨有 C 為 -2.3164%；未校準獨有續漲為 +2.6384%，校準獨有續漲為 -0.0476%。這些是診斷性分組，仍需樣本外日期驗證。

配對工具與原始輸出：`Quant-Agent/_workbench/tools/run_paired_calibration_audit.py`、
`Quant-Agent/_workbench/out/moneyflow_62d_backtest_20260722/paired_calibration_audit.json`、
`Quant-Agent/_workbench/out/moneyflow_62d_backtest_20260722/paired_calibration_audit.md`。

## 4B. Phase 2 樣本外驗證：資料閘門結果

Phase 2 已按 frozen M10 設定執行，但**沒有足夠的樣本外資料可計算績效**：訓練窗口截至 2026-07-17，之後只有 2026-07-20 一個新訊號日；它後面沒有 10 個後續評分交易日，因此成熟 OOS 日期為 0/20。7/20 的資料收據為 DQ 70.0、41 個族群、997 檔股票，TWSE 走 FinMind fallback、TPEx 走官方來源。

因此本階段狀態是 **`INSUFFICIENT_OOS_DATA`**，不是績效通過或失敗；沒有產出任何 OOS 報酬 headline，也沒有重用 4/20–7/17 訓練資料。可重跑收據：
`Quant-Agent/_workbench/out/moneyflow_62d_backtest_20260722/frozen_oos_validation_receipt.json`、
`Quant-Agent/_workbench/out/moneyflow_62d_backtest_20260722/frozen_oos_validation_receipt.md`。
目前 7/20 的既有 signal/processed 檔只作「日期存在性」證據，尚未證明由 frozen M10 設定重新產生；真正量績效前必須先用 frozen M10 重跑該日期，不能直接沿用舊檔。

## 5A. 驗收補充：DQ 前提與測試斷言對照

### DQ 前提（必要但非 M10 評級邏輯）

本輪 62/62 可重跑的前提，是先前已完成的 DQ gate 修正：對帳改用前收盤到前收盤口徑，並只有在至少 30 筆可比資料且偏差比例達 10% 時才施加阻擋性懲罰。這不是 M10 的訊號評級修改，也沒有改變事件回測器；它只是讓完整日期範圍不再被舊的計價口徑誤擋。M10 保留此 gate 的既有行為，沒有再調整門檻。

### M10 新增/修改斷言對照

| 測試 | 斷言的行為 | 目的 |
|---|---|---|
| `test_plain_day_with_only_safety_rules_is_no_signal` | 只有安全條件通過時不給 C | 防止舊的任意通過 fallback 回歸 |
| `test_b_grade_requires_three_core_rules_and_breadth_evidence` | B 必須有至少 3 個核心且含廣度 | 防止分數或單一條件直接升 B |
| `test_missing_breadth_evidence_cannot_fill_b_grade` | 廣度資料缺失不能補成通過 | unevaluable fail-closed |
| `test_multi_stock_rule6_evidence_can_produce_c_not_b` | 個股強度不足以升 B 時可留 C | 保留個股事件語義 |
| `test_rule3_growth_without_rule6_does_not_create_individual_c` | 只有成長規則不能製造 C | 防止 C 再次變成通用 fallback |
| `test_veto_failure_blocks_a_and_b_even_with_all_core_rules` | rule 7-10 否決阻擋 A/B | 驗證 safety/data veto |
| `test_continued_requires_both_core_rules_to_be_evaluable_and_pass` | 續漲核心規則 1、4 必須通過 | 防止續漲訊號過寬 |

既有 UAT-04、校準 no-lookahead 與完整回歸測試未刪除、未弱化；本輪 targeted 25/25、full 463/463。

## 5. 未解決限制與下一步

1. 這不是 Research Ready：C 級仍落後動能基準；A/B 尚無成熟樣本。
2. `min_core_passed_for_b=3` 與 `min_breadth_core_passed_for_b=1` 是未校準設計值，尚未用獨立 forward window 校準。
3. 事件數增加伴隨抽樣集合改變，不能把未校準與校準績效差異解讀成單一校準因果效果。
4. 已修好的 DQ gate 是本輪必要前提；若未來資料口徑或可交易性再次改變，必須重新產生兩模式的完整 62 天證據。
5. 本次刻意沒有修改 `src/backtester.py`、`src/benchmarks.py`、`src/threshold_calibration.py`、DQ/reconciliation 或夜跑入口；這些是後續獨立變更，避免把評級選擇性效果與計價口徑混在一起。
6. 配對審計與後續 OOS 的執行規格已鎖定於 `Quant-Agent/_workbench/plans/PLAN_moneyflow_paired_calibration_oos_20260722.md`；Phase 2 的資料閘門已執行但回報 `INSUFFICIENT_OOS_DATA`，不能把本輪 62 天結果寫成樣本外證據。

**目前決策**：可以把本輪結果交給 Claude 做設計與證據審查；不能把任何 A/B/C 訊號當成已驗證的起漲預測器。
