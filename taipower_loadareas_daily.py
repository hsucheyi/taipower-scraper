import argparse
import io
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

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

        resp = context.request.get(
            CSV_URL + "?_ts=" + str(int(datetime.now().timestamp())),
            headers={
                "Accept": "text/csv, text/plain, */*",
                "Referer": "https://www.taipower.com.tw/",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            },
            timeout=60000,
        )

        if not resp.ok:
            browser.close()
            raise RuntimeError(f"csv fetch failed: HTTP {resp.status}")

        csv_text = resp.text()
        browser.close()

    csv_text = (csv_text or "").strip()
    if not csv_text:
        raise RuntimeError("empty CSV response")

    return csv_text


def parse_csv_text(csv_text: str, target_date: str) -> pd.DataFrame:
    # 台電這個 CSV 沒有欄名，通常是：
    # 時間, 東部, 北部, 中部, 南部
    raw = pd.read_csv(io.StringIO(csv_text), header=None)

    if raw.shape[1] < 5:
        raise RuntimeError(f"unexpected CSV format, columns={raw.shape[1]}")

    raw = raw.iloc[:, :5].copy()
    raw.columns = ["time", "east", "north", "center", "south"]

    raw["time"] = raw["time"].astype(str).map(normalize_time_str)

    # 只保留當天完整區間 00:00 ~ 23:50
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

    df = df.sort_values(["date", "time"]).reset_index(drop=True)
    return df


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
