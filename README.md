# Taipower Scraper

自動抓取台電公開資料，包括：

- 📊 區域用電負載（CSV / Excel）
- 📄 發電成本 PDF（版本追蹤）

並透過 GitHub Actions 定期更新與保存歷史紀錄。

---

## 📊 功能一：區域用電負載（Load Areas）

### 📌 功能

- 每日抓取台電區域用電資料（10 分鐘粒度）
- 取得 `00:00 → 23:50`（共 144 筆）
- 儲存每日 CSV
- 累積至單一 Excel 檔案

---

### 📂 輸出

#### 每日 CSV

    output/taipower_loadareas_YYYY-MM-DD_0000_2350.csv

#### 歷史 Excel

    output/taipower_loadareas_all.xlsx

- 工作表：`loadareas`
- 每天資料會自動追加
- 若同一天重跑，會覆蓋該日資料（避免重複）

---

### ⏱️ 排程

    cron: "55 15 * * *"

- 對應台灣時間：**23:55**
- 每天抓取當日完整資料

---

### 🔧 技術

- 使用 Playwright 模擬瀏覽器
- 在瀏覽器上下文中執行 `fetch()`
- 搭配 `credentials: include` 避開台電 403 限制

---

## 📄 功能二：發電成本 PDF 監控

### 📌 功能

- 每週檢查台電發電成本 PDF 是否更新
- 自動下載最新版本
- 保留歷史版本（不覆蓋）
- 使用 SHA256 判斷是否有更新

---

### 📂 輸出

    data/generation_cost_pdf/
    ├─ latest.pdf
    ├─ metadata.json
    └─ archive/

#### archive 範例

    archive/
    20260423T060033Z_各種發電方式之發電成本-115年2月底止_(PDF).pdf

---

### ⏱️ 排程

- 每週執行一次（由 GitHub Actions 控制）

---

### 🔧 技術

- 使用 Playwright 取得頁面 HTML
- 透過 regex 抓取 PDF `/media/...pdf`
- 使用瀏覽器 request 下載 PDF
- SHA256 比對版本是否更新

---

## ⚠️ 注意事項

### 1️⃣ 台電網站 403（重要）

台電會阻擋：

- requests
- 直接 API 呼叫

👉 解法：

- 必須使用 Playwright
- 必須模擬瀏覽器行為
- 保持 `fetch + credentials` 架構

---

### 2️⃣ 資料更新時間

- 用電資料：每 10 分鐘更新
- 每日最後一筆：23:50

👉 若抓取時間太早，可能缺少最後幾筆

---

### 3️⃣ Git repo 會變大

因為：

- CSV 每天增加
- PDF 持續累積

👉 建議未來：

- 使用 Git LFS
- 或改用雲端儲存（S3 / GCS）

---

## 📊 資料來源

### 區域用電資料

    https://www.taipower.com.tw/d006/loadGraph/loadGraph/data/loadareas.csv

### 發電成本 PDF 頁面

    https://www.taipower.com.tw/2289/2363/2373/2375/10359/normalPost

---

## 🚀 未來可擴充

- 📈 用電趨勢圖
- 📬 通知（LINE / Telegram）
- 📊 PDF 解析成數據
- 🧠 用電預測
- ☁️ 上傳資料庫（BigQuery / PostgreSQL）

---

## 📄 License

MIT License
