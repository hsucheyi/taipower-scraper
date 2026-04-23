# taipower-scraper

這個 repo 用來抓取台電公開資料，目前包含：

- `taipower_loadareas_daily.py`
  - 每日抓取負載區域相關資料
- `scripts/generation_cost_pdf_watcher.py`
  - 每週檢查台電「各種發電方式之發電成本」PDF 是否更新
  - 若更新則下載並保存到 `data/generation_cost_pdf/`

## 結構

```text
.github/workflows/
scripts/
data/
