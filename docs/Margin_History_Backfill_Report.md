# Margin History Backfill Report（融資融券歷史回補，官方免費端點）

**日期**: 2026-07-21
**目的**: FinMind 免費額度已用完，改用 TWSE/TPEx 官方免費歷史端點回補融資融券歷史，不佔用 FinMind 額度。

## 1. 背景與範圍

現行 `src/data_loader.py` 的 `fetch_twse_margin_all()` / `fetch_tpex_margin_all()`
呼叫的是 OpenAPI「當日」端點（不吃日期參數，只會回今天）——這兩支**完全未改動**，
仍留給每日排程用。本次新增的是另一組「舊版歷史報表」端點，**確實吃日期參數**，
可回補任意過去交易日：

| 市場 | 端點 | 日期參數格式 |
| --- | --- | --- |
| TWSE（上市） | `https://www.twse.com.tw/exchangeReport/MI_MARGN?response=json&date=YYYYMMDD&selectType=ALL` | 西元年純數字，如 `20260714` |
| TPEx（上櫃） | `https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php?l=zh-tw&d=115/07/14&o=json` | **民國年斜線格式**，如 `115/07/14`（不是西元年、不是破折號） |

## 2. 兩端點格式差異（實測，非憑記憶）

### 2.1 回應外層結構
派工說明書原本假設 TWSE 會回傳扁平的 `{fields, data}`——**實測後發現是錯的**。兩端點
實際都是 `{"date": ..., "tables": [...]}` 巢狀結構：

- **TWSE**：`tables` 是兩張表，`tables[0]` 是全市場合計列（6 欄），`tables[1]` 才是逐股
  明細（16 欄）。逐股表欄位順序：代號/名稱/買進/賣出/現金償還/前日餘額/今日餘額/
  次一營業日限額/（以下為融券）買進/賣出/現券償還/前日餘額/今日餘額/次一營業日限額/
  資券互抵/註記。**這個欄位順序恰好跟 `src/data_cleaner.py::clean_margin_data` 現有
  TWSE 分支預期的 index 完全一致**（row[0]=代號、row[2]=資買、row[3]=資賣、
  row[6]=資餘額、row[8]=券買、row[9]=券賣、row[12]=券餘額），因此不需要改動
  cleaner，只需原樣傳入。
- **TPEx**：`tables[0]` 就是逐股明細（20 欄，913 檔股票），欄位順序：代號/名稱/
  前資餘額/資買/資賣/現償/資餘額/資屬證金/資使用率/資限額/前券餘額/**券賣**/
  **券買**/券償/券餘額/券屬證金/券使用率/券限額/資券相抵/備註。注意 TPEx 券的
  買賣欄位順序跟 TWSE 相反（TPEx 是「賣、買」，TWSE 是「買、賣」）——已在
  `transform_tpex_margin_rows` 用具名 index 註解清楚標出，避免未來誤用。

### 2.2 非交易日（假日/週末）的回應
- **TWSE**：非交易日回應**只有** `{"stat": "很抱歉，沒有符合條件的資料"}`，完全沒有
  `date` 欄位、也沒有 `tables` 欄位。（原本以為會有 `date` 但 `tables` 為空——實際
  更極端，`date` 也不存在。已修正 `fetch_twse_margin_history` 在做日期一致性檢查
  **之前**先判斷這種「兩個關鍵欄位都不存在」的訊號，歸類為「非交易日」而非
  「日期不符」的失敗——這是實跑回補時抓到的真實 bug，見第 4 節。）
- **TPEx**：非交易日回應**正常帶 `date` 欄位**（與請求日期一致），只是 `tables[0].data`
  是空陣列、`totalCount=0`——原本的日期一致性檢查邏輯天生就能正確處理，不需額外修正。

### 2.3 中文編碼
兩端點回應本身都是合法 UTF-8（用 `requests.get(...).json()` 直接解析完全正確，
已用原始 bytes 逐位元組核對過）。之前抽驗時在終端機印出中文出現亂碼，是本機終端機
編碼顯示問題，不是資料本身有問題——已改用寫檔案的方式核對，資料正確。

## 3. 抽驗證據（兩端點各至少 1 筆真實回應日期比對）

**TWSE**（`data/raw/margin/twse_official_2026-07-14.json`）：
- 請求 `date=20260714`，回應 `metadata.url` 記錄同一個請求 URL，`http_status=200`
- 回應內容中第一筆逐股資料 `stock_id="00400A"`，`row_count=1283`
- 日期一致性：程式碼在寫檔前已比對回應的 `date="20260714"` == 請求日期，一致才寫入

**TPEx**（`data/raw/margin/tpex_official_2026-07-14.json`）：
- 請求 `d=115/07/14`（民國年斜線，由 `iso_to_roc_slash("2026-07-14")` 轉換而得）
- 回應 `metadata.url` 記錄同一個請求 URL，`http_status=200`
- 轉換後第一筆 `{"SecuritiesCompanyCode": "00679B", "MarginPurchase": "76", "MarginSales": "151", "MarginPurchaseBalance": "4,827", "ShortSale": "0", "ShortConvering": "0", "ShortSaleBalance": "17", "Date": "2026-07-14"}`
- 日期一致性：回應的 `date="20260714"` 已轉換為 ISO 並比對請求日期一致才寫入
- `row_count=913`

## 4. 實跑過程中發現並修正的真實 bug

第一次執行完整回補時，發現 TWSE 每個週末/假日都被誤判為 `DATE_MISMATCH`（失敗），
而非「非交易日」。根因：非交易日回應完全沒有 `date` 欄位，原本的程式碼先做日期
一致性檢查，`payload.get("date")` 拿到 `None`，判定為不一致 → 回傳失敗。

**修正**：在日期一致性檢查**之前**，先判斷 `"date" not in payload and "tables" not in payload`
——這是非交易日的專屬訊號，直接視為「無資料/非交易日」回傳空列表，不再誤判為失敗。
已補上對應的迴歸測試 `test_fetch_twse_margin_history_weekend_no_date_or_tables_returns_empty_list`。

修正前後對比（同一批日期重跑）：修正前 2026-04-25/26、2026-05-01/02/03 等週末/假日
全部記錄為 `failed`；修正後全部正確記錄為 `skipped_non_trading_day`，`failed=0`。

## 5. 完整回補執行統計

回補範圍：2026-04-20 ~ 2026-07-20（92 個日曆天，含修正前後共執行兩次，第二次為
續傳，第一次已存的 41 天直接跳過重打）。

| 市場 | 成功寫入 (saved) | 跳過(續傳已存在) | 跳過(非交易日) | 失敗 |
| --- | --- | --- | --- | --- |
| TWSE | 63（41 舊 + 22 本次新增） | 41 | 29 | **0** |
| TPEx | 63（41 舊 + 22 本次新增） | 41 | 29 | **0** |

（`loop/evidence/fetch_receipts/margin_history_backfill_summary.json` 為第二次
〔續傳完成〕的執行摘要：`saved=22, skipped_existing=41, skipped_non_trading_day=29,
failed=0`，兩次合計每邊 63 個交易日全部成功。）

63 個交易日 + 29 個非交易日 = 92 天，與 92 天日曆範圍（含 26 個週末 + 3 個國定假日）
完全對得上，無遺漏、無誤判。

## 6. 回補前後覆蓋率對比

用 `scripts/backfill_status.py`（本次新增 `margin_date_sources` 區塊，per-date 統計，
與既有 per-stock FinMind 統計並列不互相干擾）量測：

| 指標 | 回補前 | 回補後 |
| --- | --- | --- |
| `margin`（per-stock，FinMind `finmind_<stock_id>.json`） | 2/1963 (0.1%) | 2/1963 (0.1%，不變——本次未動 FinMind 相關程式碼) |
| `twse_official_<date>.json`（per-date，新） | 0 | 63 個交易日 |
| `tpex_official_<date>.json`（per-date，新） | 0 | 63 個交易日 |
| 兩官方端點皆有資料的配對交易日 | 0 | 63（TWSE/TPEx 完全對齊，無單邊缺漏） |
| 融資融券歷史資料涵蓋的交易日範圍 | 無（僅 2 檔個股的 FinMind 抽樣） | 2026-04-20 ~ 2026-07-20 全 63 個交易日 |

**注意**：per-stock 覆蓋率（`margin: 0.1%`）衡量的是「FinMind 逐股回補了多少檔股票的
歷史」，per-date 覆蓋率（`margin_date_sources`）衡量的是「逐日全市場快照回補了幾天」
——兩者denominator 完全不同，不可互相取代或加總，`backfill_status.py` 的輸出也刻意
分開兩個區塊呈現，不混為一談。

## 7. 新增檔案清單

- `src/twse_tpex_margin_history.py`：`fetch_twse_margin_history()` /
  `fetch_tpex_margin_history()`（fail-closed，日期一致性檢查）、
  `iso_to_roc_slash()`（日期格式轉換）、`transform_twse_margin_rows()` /
  `transform_tpex_margin_rows()`（轉成 `clean_margin_data()` 現有認得的格式）、
  `build_history_envelope()`（專案標準信封格式）
- `scripts/backfill_margin_history.py`：CLI 回補工具，預設範圍
  2026-04-20~2026-07-20，可續傳（已存在檔案跳過），禮貌延遲 1.5 秒/請求
- `data/raw/margin/twse_official_<date>.json` × 63、
  `data/raw/margin/tpex_official_<date>.json` × 63（新檔名前綴，未覆蓋任何既有
  `margin_<date>.json` / `finmind_<stock_id>.json` 檔案）
- `tests/unit/test_twse_tpex_margin_history.py`（39 個測試）、
  `tests/unit/test_backfill_margin_history.py`（含在同一計數內，回補腳本續傳邏輯）
- `scripts/backfill_status.py`：新增 `margin_date_sources` 區塊（4 個新測試），
  向下相容，既有 8 個測試全部維持綠燈

## 8. 已知限制

1. **範圍內僅涵蓋 2026-04-20~2026-07-20**：這是本次任務指定的範圍；更早的歷史需
   另外指定日期區間執行 `scripts/backfill_margin_history.py --start ... --end ...`。
2. **舊版端點的長期穩定性未知**：這是 TWSE/TPEx 較舊的報表系統端點（非新版
   OpenAPI），沒有官方 SLA 保證會一直存在；若未來下架，需重新尋找替代來源。
3. **未做批次寫入速率極限測試**：本次以 1.5 秒/請求的保守節奏跑完全部 126 次請求
   （63 天 × 2 市場），0 次失敗、0 次疑似限速跡象，但未刻意測試更高頻率下的行為。
4. **`clean_margin_data()` 完全未修改**：轉換函式刻意對齊既有 index/欄位假設，
   意味著若未來 TWSE/TPEx 調整回應欄位順序，需要同時檢查
   `transform_twse_margin_rows`/`transform_tpex_margin_rows` 與
   `clean_margin_data` 兩邊的 index 假設是否還一致。
5. **尚未串接進每日排程**：本次僅新增回補工具與一次性完整回補，**未修改**
   `daily_report`/`run_daily.py` 等既有執行路徑，也未讓 `clean_margin_data` 的
   呼叫端自動去讀新的 `twse_official_*`/`tpex_official_*` 檔案——這兩者是否要接進
   既有管線需要另外拍板（治理鐵則 8：不動夜跑行為，先提案等拍板）。
