import argparse
import io
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

ENTRY_URLS = [
    "https://www.taipower.com.tw/",
    "https://www.taipower.com.tw/2289/2363/2367/2368/10263/normalPost",
]
CSV_URL = "https://www.taipower.com.tw/d006/loadGraph/loadGraph/data/loadareas.csv"


def normalize_time_str(t: str) -> str:
    t = str(t).strip()
    if not t:
        return ""

    if ":" not in t and t.isdigit():
        return f"{int(t):02d}:00"

    hh, mm = t.split(":")
    return f"{int(hh):02d}:{int(mm):02d}"


def try_fetch_in_page(page, csv_url: str) -> str:
    return page.evaluate(
        """async (url) => {
            const r = await fetch(url, {
                method: 'GET',
                credentials: 'include',
                cache: 'no-store',
                headers: {
                    'Accept': 'text/csv, text/plain, */*'
                }
            });
            if (!r.ok) {
                throw new Error(`csv fetch failed: HTTP ${r.status}`);
            }
            return await r.text();
        }""",
        csv_url + "?_ts=" + str(int(time.time() * 1000)),
    )


def try_fetch_with_request(context, csv_url: str) -> str:
    resp = context.request.get(
        csv_url + "?_ts=" + str(int(time.time() * 1000)),
        headers={
            "Accept": "text/csv, text/plain, */*",
            "Referer": "https://www.taipower.com.tw/",
            "Origin": "https://www.taipower.com.tw",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
        timeout=60000,
    )
    if not resp.ok:
        raise RuntimeError(f"csv fetch failed: HTTP {resp.status}")
    return resp.text()


def fetch_csv_text_with_browser() -> str:
    errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="zh-TW",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            extra_http_headers={
                "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
            },
        )
        page = context.new_page()

        try:
            # 先試兩個不同的 entry page，建立第一方瀏覽器脈絡
            for entry_url in ENTRY_URLS:
                try:
                    resp = page.goto(entry_url, wait_until="domcontentloaded", timeout=60000)
                    if resp is None:
                        raise RuntimeError("empty response")
                    if resp.status >= 400:
                        raise RuntimeError(f"entry page failed: HTTP {resp.status}")

                    try:
                        page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:
                        pass

                    csv_text = try_fetch_in_page(page, CSV_URL)
                    csv_text = (csv_text or "").strip()
                    if csv_text:
                        print(f"fetched via in-page fetch from: {entry_url}")
                        return csv_text
                except Exception as e:
                    errors.append(f"in-page via {entry_url}: {e}")

            # 最後再退回 request API
            try:
                csv_text = try_fetch_with_request(context, CSV_URL)
                csv_text = (csv_text or "").strip()
                if csv_text:
                    print("fetched via context.request.get fallback")
                    return csv_text
            except Exception as e:
                errors.append(f"request fallback: {e}")

        finally:
            browser.close()

    raise RuntimeError(" | ".join(errors))


def parse_csv_text(csv_text: str, target_date: str) -> pd.DataFrame:
    raw = pd.read_csv(io.StringIO(csv_text), header=None)

    if raw.shape[1] < 5:
        raise RuntimeError(f"unexpected CSV format, columns={raw.shape[1]}")

    raw = raw.iloc[:, :5].copy()
    raw.columns = ["time", "east", "north", "center", "south"]

    raw["time"] = raw["time"].astype(str).map(normalize_time_str)
    raw = raw[(raw["time"] >= "00:00") & (raw["time"] <= "23:50")].copy()

    if raw.empty:
        raise RuntimeError("parsed 0 rows from CSV")

    for col in ["east", "north", "center", "south"]:
        raw[col] = pd.to_numeric(raw[col], errors="coerce")

    raw["total"] = raw[["east", "north", "center", "south"]].sum(axis=1, min_count=4)
    raw["date"] = target_date
    raw["unit"] = "萬瓩"
    raw["source_url"] = CSV_URL
    raw["fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    df = raw[
        ["date", "time", "east", "north", "center", "south", "total", "unit", "source_url", "fetched_at"]
    ].copy()

    return df.sort_values(["date", "time"]).reset_index(drop=True)


def upsert_excel(df_new: pd.DataFrame, excel_path: Path, sheet_name: str) -> None:
    if excel_path.exists():
        try:
            df_old = pd.read_excel(excel_path, sheet_name=sheet_name, engine="openpyxl")
        except Exception:
            df_old = pd.DataFrame(columns=df_new.columns)

        target_dates = set(df_new["date"].astype(str).unique())
        if "date" in df_old.columns:
            df_old = df_old[~df_old["date"].astype(str).isin(target_dates)]

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
    parser.add_argument("--excel-name", default="taipower_loadareas.xlsx")
    parser.add_argument("--sheet-name", default="loadareas")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    target_date = datetime.now().strftime("%Y-%m-%d")
    csv_text = fetch_csv_text_with_browser()
    df = parse_csv_text(csv_text, target_date)

    output_path = Path(args.output_dir) / args.excel_name
    upsert_excel(df, output_path, args.sheet_name)

    print(f"saved: {output_path}")
    print(f"sheet: {args.sheet_name}")
    print(f"date: {target_date}")
    print(f"rows_written_today: {len(df)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
