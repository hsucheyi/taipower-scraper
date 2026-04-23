from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

PAGE_URL = "https://www.taipower.com.tw/2289/2363/2373/2377/10367/normalPost"
OUTPUT_XLSX = Path("output/taipower_natural_gas_prices_all.xlsx")
SHEET_NAME = "gas_price"


def fetch_page_html() -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="zh-TW",
        )
        page = context.new_page()

        try:
            page.goto(PAGE_URL, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightTimeoutError:
                pass

            return page.content()
        finally:
            browser.close()


def normalize_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    text = text.replace("&nbsp;", " ")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_values(text: str) -> dict:
    updated_match = re.search(r"更新日期\s*(\d{4}-\d{2}-\d{2})", text)
    if not updated_match:
        raise RuntimeError("找不到更新日期")

    # 例：
    # 台灣中油115年2月發電用戶天然氣牌價 (未稅，元／立方公尺) 基準熱值: 9,700 kcal／立方公尺 12.2355
    cpc_match = re.search(
        r"(台灣中油\d{3}年\d{1,2}月發電用戶天然氣牌價)\s*"
        r"\(未稅，元／立方公尺\)\s*"
        r"基準熱值:\s*9,700\s*kcal／立方公尺\s*"
        r"([0-9]+\.[0-9]+)",
        text,
    )
    if not cpc_match:
        raise RuntimeError("找不到中油天然氣牌價")

    # 例：
    # 115年1-2月 2,446 12.1719
    procurement_match = re.search(
        r"(\d{3}年\d{1,2}(?:-\d{1,2})?月)\s+"
        r"([\d,]+)\s+"
        r"([0-9]+\.[0-9]+)"
        r"(?:\s+114年|\s+113年|\s+112年|$)",
        text,
    )
    if not procurement_match:
        procurement_match = re.search(
            r"天然氣統約\s*數量\s*"
            r"\(百萬立方公尺\)\s*採購數量加權平均單價\s*"
            r"\(元／立方公尺 未稅\)\s*"
            r"(\d{3}年\d{1,2}(?:-\d{1,2})?月)\s+"
            r"([\d,]+)\s+"
            r"([0-9]+\.[0-9]+)",
            text,
        )
    if not procurement_match:
        raise RuntimeError("找不到天然氣採購數量 / 均價")

    canonical_content = "|".join(
        [
            updated_match.group(1),
            cpc_match.group(1),
            cpc_match.group(2),
            procurement_match.group(1),
            procurement_match.group(2),
            procurement_match.group(3),
        ]
    )

    return {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "page_updated_date": updated_match.group(1),
        "source_url": PAGE_URL,
        "cpc_price_label": cpc_match.group(1),
        "cpc_price_value": float(cpc_match.group(2)),
        "procurement_period": procurement_match.group(1),
        "procurement_volume_million_m3": int(procurement_match.group(2).replace(",", "")),
        "weighted_avg_unit_price": float(procurement_match.group(3)),
        "content_sha256": hashlib.sha256(canonical_content.encode("utf-8")).hexdigest(),
    }


def load_existing() -> pd.DataFrame:
    if OUTPUT_XLSX.exists():
        try:
            return pd.read_excel(OUTPUT_XLSX, sheet_name=SHEET_NAME)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def save_excel(df: pd.DataFrame) -> None:
    OUTPUT_XLSX.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(OUTPUT_XLSX, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=SHEET_NAME, index=False)


def main() -> int:
    html = fetch_page_html()
    text = normalize_text(html)
    row = parse_values(text)

    df_old = load_existing()

    if not df_old.empty and "content_sha256" in df_old.columns:
        latest_sha = str(df_old.iloc[-1]["content_sha256"])
        if latest_sha == row["content_sha256"]:
            print("UPDATED=false")
            print("No change detected.")
            print(f"CPC_LABEL={row['cpc_price_label']}")
            print(f"CPC_PRICE={row['cpc_price_value']}")
            print(f"PROCUREMENT_PERIOD={row['procurement_period']}")
            print(f"PROCUREMENT_VOLUME={row['procurement_volume_million_m3']}")
            print(f"WEIGHTED_AVG_PRICE={row['weighted_avg_unit_price']}")
            return 0

    df_new_row = pd.DataFrame([row])

    if df_old.empty:
        df_all = df_new_row
    else:
        df_all = pd.concat([df_old, df_new_row], ignore_index=True)

    save_excel(df_all)

    print("UPDATED=true")
    print(f"CPC_LABEL={row['cpc_price_label']}")
    print(f"CPC_PRICE={row['cpc_price_value']}")
    print(f"PROCUREMENT_PERIOD={row['procurement_period']}")
    print(f"PROCUREMENT_VOLUME={row['procurement_volume_million_m3']}")
    print(f"WEIGHTED_AVG_PRICE={row['weighted_avg_unit_price']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
