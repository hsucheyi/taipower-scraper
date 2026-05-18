# Taipower Scraper

本專案用於自動化抓取台電公開資料，並透過 GitHub Actions 定期執行，保存歷史資料以供後續分析使用。

## 專案目標

* 自動抓取台電網站公開資訊
* 避免 403 封鎖問題
* 定期更新資料（排程）
* 保存歷史版本（可追蹤變化）
* 將資料整理為 CSV / Excel / PDF Archive

---

## 技術架構

### 核心工具

* Python 3.12
* Playwright（重點：避免 403）
* pandas / openpyxl（資料處理）
* GitHub Actions（排程與自動化）
* SHA256（判斷 PDF 或頁面資料是否更新）

### 關鍵設計原則

台電網站會阻擋非瀏覽器請求（403），因此本專案統一採用：

* 使用 Playwright 啟動瀏覽器
* 在瀏覽器 context 中抓資料
* 必要時使用 fetch + credentials: include
* PDF 類資料優先沿用既有 PDF watcher 的下載與比對流程

避免使用：

* requests
* 直接 API 呼叫
* 不經瀏覽器 context 的下載方式

---

## 功能一：區域用電負載（loadareas）(修復中)

### 資料來源

https://www.taipower.com.tw/d006/loadGraph/loadGraph/data/loadareas.csv

### 抓取方式

* Playwright 開頁建立 context
* 在 page.evaluate() 中用 fetch()
* 帶入 credentials: include 避開 403

### 排程

* GitHub Actions
* 每日台灣時間 23:55

### 輸出

```text
output/taipower_loadareas_YYYY-MM-DD_0000_2350.csv
```

累積 Excel：

```text
output/taipower_loadareas_all.xlsx
```

### 特性

* 每日 144 筆（00:00 ~ 23:50）
* 同一天重跑會覆蓋避免重複
* 所有資料寫入同一工作表

---

## 功能二：發電成本 PDF 監控

### 資料來源

https://www.taipower.com.tw/2289/2363/2373/2375/10359/normalPost

### 功能

* 每週檢查 PDF 是否更新
* 自動下載 PDF
* 保留歷史版本
* 以 SHA256 判斷內容是否變更

### 技術

* Playwright 抓 HTML
* regex 抓 PDF URL
* 使用瀏覽器 context 下載 PDF
* SHA256 判斷是否更新

### 輸出

```text
data/generation_cost_pdf/
├─ latest.pdf
├─ metadata.json
└─ archive/
```

---

## 功能三：電價成本結構 PDF 監控

### 資料來源

https://www.taipower.com.tw/2289/2363/2373/2375/10358/normalPost

### 功能

* 每週檢查 PDF 是否更新
* 自動下載 PDF
* 自動下載與保存歷史版本
* 以 SHA256 判斷內容是否變更

### 技術

* Playwright 抓 HTML
* regex 抓 PDF URL
* 使用瀏覽器 context 下載 PDF
* SHA256 判斷是否更新

### 輸出

```text
data/tariff_cost_structure_pdf/
├─ latest.pdf
├─ metadata.json
└─ archive/
```

---

## 功能四：天然氣價格與採購數據監控

### 資料來源

https://www.taipower.com.tw/2289/2363/2373/2377/10367/normalPost

### 抓取內容

每次更新時記錄：

1. 中油天然氣牌價（元／立方公尺）
2. 天然氣採購期間
3. 採購數量（百萬立方公尺）
4. 採購加權平均單價

### 技術

* Playwright 抓 HTML
* regex 擷取數值
* SHA256 判斷是否變更

### 輸出

```text
output/taipower_natural_gas_prices_all.xlsx
```

### 特性

* 僅在資料變更時新增一列
* 保留歷史變動紀錄
* 避免重複資料

---

## 功能五：簡明月報 PDF 監控

### 資料來源

https://www.taipower.com.tw/2289/2345/50429/54971/57690/

### 功能

* 每週檢查台電「簡明月報」PDF 是否更新
* 自動下載最新簡明月報 PDF
* 保留最新版本與歷史版本
* 以 SHA256 判斷 PDF 內容是否變更
* 若 PDF 未更新，workflow 不會產生新的 commit
* 若 PDF 有更新，會自動 commit 並 push 至 repository

### 抓取邏輯

此頁面同時可能包含多個 PDF，例如：

* 簡明月報
* 電業年報

因此本功能不單純抓頁面上的第一個 PDF，而是鎖定連結文字包含「簡明月報」的 PDF，避免誤抓其他報告。

### 技術

* Playwright 抓 HTML
* regex 擷取「簡明月報」PDF URL
* 使用 Playwright browser context 下載 PDF
* SHA256 判斷是否更新
* 更新時寫入 latest.pdf、metadata.json 與 archive

### 排程

* GitHub Actions
* 每週一台灣時間 09:10 執行
* 也可手動透過 workflow_dispatch 執行

### 輸出

第一次執行或 PDF 更新時，會自動產生：

```text
data/monthly_report_pdf/
├─ latest.pdf
├─ metadata.json
└─ archive/
   └─ YYYYMMDDTHHMMSSZ_簡明月報檔名.pdf
```

### metadata.json 內容

```json
{
  "page_url": "https://www.taipower.com.tw/2289/2345/50429/54971/57690/",
  "pdf_url": "最新簡明月報 PDF URL",
  "title": "簡明月報標題",
  "sha256": "PDF SHA256",
  "latest_file": "data/monthly_report_pdf/latest.pdf",
  "archived_file": "data/monthly_report_pdf/archive/歷史版本.pdf",
  "fetched_at_utc": "UTC 抓取時間"
}
```

### 注意事項

`data/monthly_report_pdf/` 不需要手動建立。

程式執行時會自動建立：

```python
BASE_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
```

GitHub 無法 commit 空資料夾，因此資料夾與檔案會在第一次 workflow 成功執行後自動產生並 commit 回 repository。

---

## 自動化（GitHub Actions）

所有資料皆透過 GitHub Actions 自動執行：

* 每日任務
  * 區域用電負載（loadareas）
* 每週任務
  * 發電成本 PDF
  * 電價成本結構 PDF
  * 天然氣價格與採購數據
  * 簡明月報 PDF

若資料有更新：

* 自動 commit
* push 至 repository

若資料未更新：

* workflow 正常結束
* 不產生新的 commit
* 避免重複資料與不必要的版本紀錄

---

## 專案結構

```text
.
├─ scripts/
│  ├─ loadareas scraper
│  ├─ PDF watchers
│  ├─ gas price watcher
│  └─ monthly report PDF watcher
├─ output/
│  ├─ CSV / Excel
├─ data/
│  ├─ generation_cost_pdf/
│  │  ├─ latest.pdf
│  │  ├─ metadata.json
│  │  └─ archive/
│  ├─ tariff_cost_structure_pdf/
│  │  ├─ latest.pdf
│  │  ├─ metadata.json
│  │  └─ archive/
│  └─ monthly_report_pdf/
│     ├─ latest.pdf
│     ├─ metadata.json
│     └─ archive/
├─ .github/workflows/
│  ├─ daily jobs
│  └─ weekly jobs
└─ README.md
```

---

## 本機測試

安裝套件：

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
```

執行單一 watcher：

```bash
python scripts/monthly_report_pdf_watcher.py
```

第一次執行通常會顯示：

```text
UPDATED=true
```

若 PDF 內容未變更，之後再次執行會顯示：

```text
UPDATED=false
```

---

## 開發原則（重要）

1. 抓取邏輯優先穩定
2. 不輕易更改 scraping 方法
3. 抓取與資料處理分離
4. 所有資料需可追蹤歷史
5. 所有流程需可自動化
6. PDF 類資料需保留 latest 與 archive
7. 以 SHA256 作為內容更新判斷基準
8. workflow 僅在資料真的更新時 commit

---

## 未來擴充方向

* 更多台電公開資料來源
* 視覺化分析（Power BI / Python）
* API 化資料輸出
* 資料品質檢查機制
* PDF 內容解析與文字化
* 更新通知機制

---

## License

MIT License
