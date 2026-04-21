#!/usr/bin/env python3
"""Download Taipower regional load data for today 00:00-11:50 and save to CSV.

Source:
  https://www.taipower.com.tw/d006/loadGraph/loadGraph/data/loadareas.csv

Expected CSV columns in source:
  time,east,north,center,south
Unit:
  萬瓩

Output filename example:
  output/taipower_loadareas_2026-04-21_0000_1150.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import requests

SOURCE_URL = "https://www.taipower.com.tw/d006/loadGraph/loadGraph/data/loadareas.csv"
TIMEZONE_NAME = "Asia/Taipei"
OUTPUT_DIR_DEFAULT = "output"
TARGET_END_MINUTES = 11 * 60 + 50
EXPECTED_COLUMNS = ["time", "east", "north", "center", "south"]


@dataclass
class Record:
    time: str
    east: float
    north: float
    center: float
    south: float

    @property
    def total(self) -> float:
        return self.east + self.north + self.center + self.south

    def as_row(self, date_str: str) -> dict[str, object]:
        return {
            "date": date_str,
            "time": self.time,
            "east": self.east,
            "north": self.north,
            "center": self.center,
            "south": self.south,
            "total": round(self.total, 1),
            "unit": "萬瓩",
            "source_url": SOURCE_URL,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Taipower regional load data and save today's 00:00-11:50 records to CSV."
    )
    parser.add_argument(
        "--output-dir",
        default=OUTPUT_DIR_DEFAULT,
        help=f"Directory for CSV output (default: {OUTPUT_DIR_DEFAULT})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="HTTP timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--filename",
        default="",
        help="Optional output filename. If omitted, an automatic name is used.",
    )
    return parser.parse_args()


def normalize_time_label(raw: str) -> str | None:
    value = raw.strip()
    if not value:
        return None
    if ":" not in value:
        value = f"{value}:00"
    hh_str, mm_str = value.split(":", 1)
    try:
        hh = int(hh_str)
        mm = int(mm_str)
    except ValueError:
        return None
    if hh < 0 or hh > 23 or mm < 0 or mm > 59:
        return None
    return f"{hh:02d}:{mm:02d}"


def to_minutes(hhmm: str) -> int:
    hh, mm = hhmm.split(":")
    return int(hh) * 60 + int(mm)


def fetch_source_csv(timeout: int) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TaipowerLoadAreasBot/1.0)",
        "Accept": "text/csv,text/plain,*/*",
        "Referer": "https://www.taipower.com.tw/2289/2363/2367/2368/10263/normalPost",
    }
    response = requests.get(SOURCE_URL, headers=headers, timeout=timeout)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def parse_records(csv_text: str) -> list[Record]:
    records: list[Record] = []
    reader = csv.reader(csv_text.splitlines())
    for row in reader:
        if len(row) < 5:
            continue
        time_label = normalize_time_label(row[0])
        if not time_label:
            continue
        try:
            east = float(row[1])
            north = float(row[2])
            center = float(row[3])
            south = float(row[4])
        except ValueError:
            continue
        if to_minutes(time_label) <= TARGET_END_MINUTES:
            records.append(
                Record(
                    time=time_label,
                    east=east,
                    north=north,
                    center=center,
                    south=south,
                )
            )
    records.sort(key=lambda item: to_minutes(item.time))
    deduped: list[Record] = []
    seen: set[str] = set()
    for item in records:
        if item.time in seen:
            continue
        seen.add(item.time)
        deduped.append(item)
    return deduped


def resolve_output_path(output_dir: str, filename: str, today_str: str) -> Path:
    base_dir = Path(output_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    if filename:
        return base_dir / filename
    auto_name = f"taipower_loadareas_{today_str}_0000_1150.csv"
    return base_dir / auto_name


def write_output(path: Path, rows: Iterable[dict[str, object]]) -> None:
    fieldnames = [
        "date",
        "time",
        "east",
        "north",
        "center",
        "south",
        "total",
        "unit",
        "source_url",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    args = parse_args()
    today_str = datetime.now().strftime("%Y-%m-%d")
    try:
        csv_text = fetch_source_csv(timeout=args.timeout)
        records = parse_records(csv_text)
    except requests.RequestException as exc:
        print(f"[ERROR] download failed: {exc}", file=sys.stderr)
        return 1

    if not records:
        print("[ERROR] no valid records found in source CSV", file=sys.stderr)
        return 2

    output_path = resolve_output_path(args.output_dir, args.filename, today_str)
    write_output(output_path, (r.as_row(today_str) for r in records))
    print(f"saved: {output_path}")
    print(f"rows: {len(records)}")
    print(f"time_range: {records[0].time} -> {records[-1].time}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
