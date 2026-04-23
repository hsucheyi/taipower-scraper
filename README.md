# Taipower Scraper

本專案用於自動化抓取台電公開資料，並透過 GitHub Actions 定期執行，保存歷史資料以供後續分析使用。

## 專案目標

- 自動抓取台電網站公開資訊
- 避免 403 封鎖問題
- 定期更新資料（排程）
- 保存歷史版本（可追蹤變化）
- 將資料整理為 CSV / Excel

---

## 技術架構

### 核心工具

- Python 3.12
- Playwright（重點：避免 403）
- pandas / openpyxl（資料處理）
- GitHub Actions（排程與自動化）

### 關鍵設計原則

台電網站會阻擋非瀏覽器請求（403），因此本專案統一採用：

- 使用 Playwright 啟動瀏覽器
- 在瀏覽器 context 中抓資料
- 必要時使用 fetch + credentials: include

避免使用：

- requests
- 直接 API 呼叫
- context.request.get（不穩）

---

## 功能一：區域用電負載（loadareas）

### 資料來源

https://www.taipower.com.tw/d006/loadGraph/loadGraph/data/loadareas.csv

### 抓取方式

- Playwright 開頁建立 context
- 在 page.evaluate() 中用 fetch()
- 帶入 credentials: include 避開 403

### 排程

- GitHub Actions
- 每日台灣時間 23:55

### 輸出

每日 CSV：

```
output/taipower_loadareas_YYYY-MM-DD_0000_2350.csv
```

累積 Excel：

```
output/taipower_loadareas_all.xlsx
```

### 特性

- 每日 144 筆（00:00 ~ 23:50）
- 同一天重跑會覆蓋避免重複
- 所有資料寫入同一工作表

---

## 功能二：發電成本 PDF 監控

### 資料來源

https://www.taipower.com.tw/2289/2363/2373/2375/10359/normalPost

### 功能

- 每週檢查 PDF 是否更新
- 自動下載 PDF
- 保留歷史版本

### 技術

- Playwright 抓 HTML
- regex 抓 PDF URL
- 使用瀏覽器 context 下載
- SHA256 判斷是否更新

### 輸出

```
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

- 每週檢查 PDF 是否更新
- 自動下載與保存歷史版本

### 輸出

```
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

- Playwright 抓 HTML
- regex 擷取數值
- SHA256 判斷是否變更

### 輸出

```
output/taipower_natural_gas_prices_all.xlsx
```

### 特性

- 僅在資料變更時新增一列
- 保留歷史變動紀錄
- 避免重複資料

---

## 自動化（GitHub Actions）

所有資料皆透過 GitHub Actions 自動執行：

- 每日任務（loadareas）
- 每週任務（PDF / 天然氣資料）

若資料有更新：

- 自動 commit
- push 至 repository

---

## 專案結構

```
.
├─ scripts/
│  ├─ loadareas scraper
│  ├─ PDF watchers
│  └─ gas price watcher
├─ output/
│  ├─ CSV / Excel
├─ data/
│  ├─ PDF archives
├─ .github/workflows/
│  ├─ daily jobs
│  └─ weekly jobs
```

---

## 開發原則（重要）

1. 抓取邏輯優先穩定
2. 不輕易更改 scraping 方法
3. 抓取與資料處理分離
4. 所有資料需可追蹤歷史
5. 所有流程需可自動化

---

## 未來擴充方向

- 更多台電公開資料來源
- 視覺化分析（Power BI / Python）
- API 化資料輸出
- 資料品質檢查機制

---

## License

MIT License
