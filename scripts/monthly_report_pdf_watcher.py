from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

PAGE_URL = "https://www.taipower.com.tw/2289/2345/50429/54971/57690/"
BASE_DIR = Path("data/monthly_report_pdf")
ARCHIVE_DIR = BASE_DIR / "archive"
LATEST_PDF = BASE_DIR / "latest.pdf"
METADATA_FILE = BASE_DIR / "metadata.json"


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", "_", name).strip("_")
    return name or "taipower_monthly_report"


def load_metadata() -> dict:
    if METADATA_FILE.exists():
        text = METADATA_FILE.read_text(encoding="utf-8").strip()
        if text:
            return json.loads(text)
    return {}


def save_metadata(data: dict) -> None:
    METADATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def extract_pdf_info_from_html(html: str) -> tuple[str, str]:
    """Find the newest monthly report PDF on the Taipower monthly/annual report page."""
    # 台電頁面上同時有「簡明月報」與「電業年報」；這裡只鎖定簡明月報的 anchor。
    monthly_report_links = re.findall(
        r'<a[^>]+href=["\'](?P<href>[^"\']+?\.pdf)["\'][^>]*>\s*(?P<title>[^<]*?簡明月報\s*\(PDF\))\s*</a>',
        html,
        flags=re.IGNORECASE,
    )

    if not monthly_report_links:
        raise RuntimeError("HTML 中找不到簡明月報 PDF URL")

    href, title = monthly_report_links[0]
    pdf_url = urljoin(PAGE_URL, href.replace("&amp;", "&"))
    title = re.sub(r"\s+", "", title).strip()
    return pdf_url, title


def fetch_html_and_pdf() -> tuple[bytes, str, str]:
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

            html = page.content()
            print("HTML_LENGTH=", len(html))

            pdf_url, title = extract_pdf_info_from_html(html)
            print(f"FOUND_TITLE={title}")
            print(f"FOUND_PDF_URL={pdf_url}")

            # 與其他 PDF watcher 一樣：用 Playwright context 下載，避免直接 requests 被擋。
            resp = context.request.get(pdf_url, timeout=60000)
            if not resp.ok:
                raise RuntimeError(f"PDF 下載失敗: status={resp.status}")

            pdf_bytes = resp.body()
            if not pdf_bytes:
                raise RuntimeError("PDF 內容為空")

            return pdf_bytes, title, pdf_url
        finally:
            browser.close()


def main() -> int:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    pdf_bytes, title, pdf_url = fetch_html_and_pdf()
    new_sha = sha256_bytes(pdf_bytes)

    old_metadata = load_metadata()
    old_sha = old_metadata.get("sha256")

    if new_sha == old_sha:
        print("UPDATED=false")
        print("No change detected.")
        print(f"TITLE={title}")
        print(f"PDF_URL={pdf_url}")
        return 0

    LATEST_PDF.write_bytes(pdf_bytes)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_name = f"{timestamp}_{sanitize_filename(title)}.pdf"
    archive_path = ARCHIVE_DIR / archive_name
    archive_path.write_bytes(pdf_bytes)

    metadata = {
        "page_url": PAGE_URL,
        "pdf_url": pdf_url,
        "title": title,
        "sha256": new_sha,
        "latest_file": str(LATEST_PDF),
        "archived_file": str(archive_path),
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    save_metadata(metadata)

    print("UPDATED=true")
    print(f"TITLE={title}")
    print(f"PDF_URL={pdf_url}")
    print(f"ARCHIVED_FILE={archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
