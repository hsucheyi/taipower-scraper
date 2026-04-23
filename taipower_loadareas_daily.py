import argparse
import csv
import io
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

PAGE_URL = "https://www.taipower.com.tw/d006/loadGraph/loadGraph/load_areas_.html"
CSV_URL = "https://www.taipower.com.tw/d006/loadGraph/loadGraph/data/loadareas.csv"


def normalize_time_str(t: str) -> str:
    t = str(t).strip()
    if not t:
        return ""

    if ":" not in t and t.isdigit():
        return f"{int(t):02d}:00"

    hh, mm = t.split(":")
    return f"{int(hh):02d}:{int(mm):02d}"


def fetch_csv_text_with_browser() -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="zh-TW",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        resp = page.goto(PAGE_URL, wait_until="domcontentloaded", timeout=60000)
        if resp is None:
            raise RuntimeError("failed to open entry page")
        if resp.status >= 400:
            raise RuntimeError(f"entry page failed: HTTP {resp.status}")

        csv_text = page.evaluate(
            """async (url) => {
                const r = await fetch(url, {
                    method: 'GET',
                    credentials: 'include',
                    cache: 'no-store'
                });
                if (!r.ok) {
                    throw new Error(`csv fetch failed: HTTP ${r.status}`);
                }
                return await r.text();
            }""",
            CSV_URL + "?_ts=" + str(int(datetime.now().timestamp()))
        )

        browser.close()

        csv_text = (csv_text or "").strip()
        if not csv_text:
            raise RuntimeError("empty CSV response")
        return csv_text


def parse_csv_text(csv_text: str, target_date: str) -> pd.DataFrame:
    rows = []
    reader = csv.reader(io.StringIO(csv_text))

    for row in reader:
        if not row or all(not str(x).strip() for x in row):
            continue

        row = [str(x).strip() for x in row[:5]]
        if len(row) < 5:
            continue

        raw_time = row[0]
        try:
            t = normalize_time_str(raw_time)
            datetime.strptime(t, "%H:%M")
        except Exception:
            continue

        # 原本穩定版只抓到 11:50
        if not ("00:00" <= t <= "11:50"):
            continue

        def to_num(x):
            try:
                return float(x)
            except Exception:
                return None

        east = to_num(row[1])
        north = to_num(row[2])
        center = to_num(row[3])
        south = to_num(row[4])

        total = None
        if all(v is not None for v in [east, north, center, south]):
            total = east + north + center + south

        rows.append(
            {
                "date": target_date,
                "time": t,
                "east": east,
                "north": north,
                "center": center,
                "south": south,
                "total": total,
                "unit": "萬瓩",
                "source_url": CSV_URL,
            }
        )

    if not rows:
        raise RuntimeError("parsed 0 rows from CSV")

    df = pd.DataFrame(rows).sort_values(["date", "time"]).reset_index(drop=True)
    return df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="output")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    target_date = datetime.now().strftime("%Y-%m-%d")

    csv_text = fetch_csv_text_with_browser()
    df = parse_csv_text(csv_text, target_date)

    output_path = Path(args.output_dir) / f"taipower_loadareas_{target_date}_0000_1150.csv"
    df.to_csv(output_path, index=False, encoding="utf-8-sig")

    print(f"saved: {output_path}")
    print(f"rows: {len(df)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
