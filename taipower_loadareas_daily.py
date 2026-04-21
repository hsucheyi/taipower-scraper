import argparse
import csv
import io
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

PAGE_URL = "https://www.taipower.com.tw/2289/2363/2367/2368/10263/normalPost"
CSV_URL = "https://www.taipower.com.tw/d006/loadGraph/loadGraph/data/loadareas.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,text/plain,*/*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Referer": PAGE_URL,
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def fetch_csv_text(session: requests.Session) -> str:
    # 先進頁面拿 cookie / 建立正常來源脈絡
    page_resp = session.get(PAGE_URL, timeout=30)
    page_resp.raise_for_status()

    last_error = None
    candidate_urls = [
        CSV_URL,
        f"{CSV_URL}?_ts={int(time.time())}",
    ]

    for url in candidate_urls:
        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
            resp.encoding = resp.encoding or "utf-8"
            text = resp.text.strip()
            if text:
                return text
        except Exception as e:
            last_error = e

    raise RuntimeError(f"download failed after retries: {last_error}")


def normalize_time_str(t: str) -> str:
    t = t.strip()
    if not t:
        return ""

    # 例如 "00" -> "00:00", "01" -> "01:00"
    if ":" not in t:
        if t.isdigit():
            return f"{int(t):02d}:00"

    hh, mm = t.split(":")
    return f"{int(hh):02d}:{int(mm):02d}"


def parse_csv_text(csv_text: str, target_date: str) -> pd.DataFrame:
    rows = []
    reader = csv.reader(io.StringIO(csv_text))

    for row in reader:
        # 跳過空列
        if not row or all(not str(x).strip() for x in row):
            continue

        # 只取前五欄：時間 + 東北中南
        row = [str(x).strip() for x in row[:5]]
        if len(row) < 5:
            continue

        raw_time = row[0]
        try:
            t = normalize_time_str(raw_time)
            dt = datetime.strptime(t, "%H:%M")
        except Exception:
            # 不是資料列就跳過
            continue

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

    session = build_session()
    csv_text = fetch_csv_text(session)
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
