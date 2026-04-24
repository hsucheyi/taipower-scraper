import argparse
import csv
import io
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

ENTRY_URL = "https://www.taipower.com.tw/tc/page.aspx?mid=97"
CSV_URL = "https://www.taipower.com.tw/d006/loadGraph/loadGraph/data/loadareas.csv"
TAIPEI_TZ = ZoneInfo("Asia/Taipei")


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
            timezone_id="Asia/Taipei",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            extra_http_headers={
                "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            },
        )
        page = context.new_page()

        # Step 1: 先進首頁，讓瀏覽器取得 cookie 與完整 session
        print("Step 1: loading entry page...")
        try:
            page.goto(
                "https://www.taipower.com.tw/",
                wait_until="networkidle",
                timeout=60000,
            )
        except Exception as e:
            print(f"Warning: entry page networkidle timeout, continue: {e}")

        # Step 2: 再進圖表頁，等頁面穩定
        print("Step 2: loading chart page...")
        try:
            page.goto(
                ENTRY_URL,
                wait_until="networkidle",
                timeout=60000,
            )
        except Exception as e:
            print(f"Warning: chart page networkidle timeout, continue: {e}")

        # Step 3: 用頁面內的 fetch 發出請求（帶完整 cookie、Referer、Origin）
        print("Step 3: fetching CSV via in-page fetch...")
        ts = int(datetime.now(TAIPEI_TZ).timestamp())
        csv_url_with_ts = f"{CSV_URL}?_ts={ts}"

        result = page.evaluate(
            """async (url) => {
                try {
                    const r = await fetch(url, {
                        method: 'GET',
                        credentials: 'include',
                        cache: 'no-store',
                        headers: {
                            'Accept': 'text/csv,text/plain,*/*',
                            'Referer': 'https://www.taipower.com.tw/tc/page.aspx?mid=97',
                            'Origin': 'https://www.taipower.com.tw',
                        }
                    });
                    if (!r.ok) {
                        return { ok: false, status: r.status, body: null };
                    }
                    const body = await r.text();
                    return { ok: true, status: r.status, body: body };
                } catch (e) {
                    return { ok: false, status: 0, body: String(e) };
                }
            }""",
            csv_url_with_ts,
        )

        browser.close()

        if not result.get("ok"):
            status = result.get("status", "unknown")
            body = result.get("body", "")
            raise RuntimeError(f"csv fetch failed: HTTP {status} / {body}")

        csv_text = (result.get("body") or "").strip()
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
        if not ("00:00" <= t <= "23:50"):
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


def upsert_excel(df_new: pd.DataFrame, excel_path: Path, sheet_name: str) -> None:
    if excel_path.exists():
        try:
            df_old = pd.read_excel(excel_path, sheet_name=sheet_name, engine="openpyxl")
        except Exception:
            df_old = pd.DataFrame(columns=df_new.columns)
        if "date" in df_old.columns:
            df_old = df_old[df_old["date"].astype(str) != df_new["date"].iloc[0]]
        df_all = pd.concat([df_old, df_new], ignore_index=True)
    else:
        df_all = df_new.copy()

    df_all["date"] = df_all["date"].astype(str)
    df_all["time"] = df_all["time"].astype(str)
    df_all = (
        df_all.sort_values(["date", "time"])
        .drop_duplicates(subset=["date", "time"], keep="last")
        .reset_index(drop=True)
    )

    with pd.ExcelWriter(excel_path, engine="openpyxl", mode="w") as writer:
        df_all.to_excel(writer, sheet_name=sheet_name, index=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--excel-name", default="taipower_loadareas_all.xlsx")
    parser.add_argument("--sheet-name", default="loadareas")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    target_date = datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d")

    csv_text = fetch_csv_text_with_browser()
    df = parse_csv_text(csv_text, target_date)

    csv_output_path = Path(args.output_dir) / f"taipower_loadareas_{target_date}_0000_2350.csv"
    df.to_csv(csv_output_path, index=False, encoding="utf-8-sig")

    excel_output_path = Path(args.output_dir) / args.excel_name
    upsert_excel(df, excel_output_path, args.sheet_name)

    print(f"saved csv: {csv_output_path}")
    print(f"saved excel: {excel_output_path}")
    print(f"sheet: {args.sheet_name}")
    print(f"rows: {len(df)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
