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


def collect_anchor_candidates(page) -> list[dict]:
    anchors = page.locator("a")
    count = anchors.count()
    results: list[dict] = []

    for i in range(count):
        a = anchors.nth(i)
        try:
            text = a.inner_text(timeout=1000).strip()
        except Exception:
            text = ""

        try:
            href = a.get_attribute("href", timeout=1000) or ""
        except Exception:
            href = ""

        if text or href:
            results.append(
                {
                    "index": i,
                    "text": text,
                    "href": href,
                }
            )
    return results


def choose_pdf_candidate(candidates: list[dict]) -> dict | None:
    # 1. 最精準：文字同時含主題與 PDF
    for item in candidates:
        text = item["text"]
        if "各種發電方式之發電成本" in text and "PDF" in text.upper():
            return item

    # 2. 文字含主題且 href 指向 pdf
    for item in candidates:
        text = item["text"]
        href = item["href"]
        if "各種發電方式之發電成本" in text and ".pdf" in href.lower():
            return item

    # 3. href 為 pdf，且文字提到發電成本
    for item in candidates:
        text = item["text"]
        href = item["href"]
        if ".pdf" in href.lower() and "發電成本" in text:
            return item

    # 4. 最後退一步：任何文字含 PDF 的連結
    for item in candidates:
        text = item["text"]
        if "PDF" in text.upper():
            return item

    return None


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
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightTimeoutError:
                pass
        except Exception:
            browser.close()
            raise

        candidates = collect_anchor_candidates(page)

        print("ANCHOR_CANDIDATES_START")
        for item in candidates[:80]:
            print(
                f'[{item["index"]}] text={item["text"]!r} href={item["href"]!r}'
            )
        print("ANCHOR_CANDIDATES_END")

        chosen = choose_pdf_candidate(candidates)
        if not chosen:
            browser.close()
            raise RuntimeError("找不到 PDF 連結")

        idx = chosen["index"]
        title = chosen["text"] or "taipower_generation_cost_pdf"
        href = chosen["href"] or ""

        target = page.locator("a").nth(idx)
        target.scroll_into_view_if_needed(timeout=5000)

        with page.expect_download(timeout=60000) as download_info:
            target.click(timeout=10000)

        download = download_info.value
        temp_path = download.path()
        if not temp_path:
            browser.close()
            raise RuntimeError("PDF 已觸發下載，但找不到暫存檔")

        pdf_bytes = Path(temp_path).read_bytes()
        if not pdf_bytes:
            browser.close()
            raise RuntimeError("PDF 下載成功但內容為空")

        final_url = download.url or href
        browser.close()
        return pdf_bytes, title, final_url


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
