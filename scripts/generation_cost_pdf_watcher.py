from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


PAGE_URL = "https://www.taipower.com.tw/2289/2363/2373/2375/10359/normalPost"
BASE_DIR = Path("data/generation_cost_pdf")
ARCHIVE_DIR = BASE_DIR / "archive"
LATEST_PDF = BASE_DIR / "latest.pdf"
METADATA_FILE = BASE_DIR / "metadata.json"


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", "_", name).strip("_")
    return name or "taipower_generation_cost"


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


def download_pdf_via_browser() -> tuple[bytes, str, str]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            accept_downloads=True,
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
            page.wait_for_load_state("networkidle", timeout=60000)
        except PlaywrightTimeoutError:
            # 某些網站 networkidle 可能不穩，至少頁面已打開就繼續找連結
            pass

        # 優先找 href 直接含 .pdf 的連結
        pdf_link = page.locator("a[href*='.pdf']").first
        title = ""
        pdf_url = ""

        if pdf_link.count() > 0:
            title = pdf_link.inner_text().strip()
            pdf_url = pdf_link.get_attribute("href") or ""

            with page.expect_download(timeout=60000) as download_info:
                pdf_link.click()

            download = download_info.value
            temp_path = download.path()
            pdf_bytes = Path(temp_path).read_bytes() if temp_path else b""
            if not pdf_bytes:
                raise RuntimeError("PDF 下載成功但檔案內容為空")

            browser.close()
            return pdf_bytes, title, download.url

        # 備援：找文字含 PDF 的連結
        text_link = page.locator("a", has_text="PDF").first
        if text_link.count() == 0:
            browser.close()
            raise RuntimeError("找不到 PDF 連結")

        title = text_link.inner_text().strip()
        pdf_url = text_link.get_attribute("href") or ""

        with page.expect_download(timeout=60000) as download_info:
            text_link.click()

        download = download_info.value
        temp_path = download.path()
        pdf_bytes = Path(temp_path).read_bytes() if temp_path else b""
        if not pdf_bytes:
            browser.close()
            raise RuntimeError("PDF 下載成功但檔案內容為空")

        browser.close()
        return pdf_bytes, title, download.url or pdf_url


def main() -> int:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    pdf_bytes, title, pdf_url = download_pdf_via_browser()

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
