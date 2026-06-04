from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin

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


def normalize_title(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = unquote(text)
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"\(PDF\)$", "(PDF)", text, flags=re.IGNORECASE)
    return text.strip()


def extract_monthly_report_version(text: str) -> int:
    """
    例如：
    - 11504簡明月報(PDF) -> 11504
    - 11503簡明月報(PDF) -> 11503
    """
    text = unquote(text)
    m = re.search(r"(\d{5})\s*簡明月報", text)
    if not m:
        return 0
    return int(m.group(1))


def extract_pdf_info_from_html(html: str) -> tuple[str, str]:
    """
    Find the newest monthly report PDF on the Taipower monthly/annual report page.
    台電頁面上同時可能有「簡明月報」與「電業年報」；這裡只鎖定簡明月報。
    """

    links = re.findall(
        r'<a\b[^>]*href=["\']([^"\']+?\.pdf)["\'][^>]*>(.*?)</a>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    candidates: list[tuple[int, str, str]] = []

    for href, raw_text in links:
        href = href.replace("&amp;", "&")
        absolute_url = urljoin(PAGE_URL, href)
        decoded_url = unquote(absolute_url)
        title = normalize_title(raw_text)

        combined = f"{title} {decoded_url}"
        if "簡明月報" not in combined:
            continue

        version = extract_monthly_report_version(combined)

        if not title:
            title = Path(unquote(absolute_url)).name

        candidates.append((version, absolute_url, title))

    if not candidates:
        raise RuntimeError("HTML 中找不到簡明月報 PDF URL")

    # 挑最新月份，例如 11504 > 11503。
    _, pdf_url, title = max(candidates, key=lambda item: item[0])
    return pdf_url, title


def debug_html_state(page, response, html: str) -> None:
    print("PAGE_URL=", page.url)
    print("RESPONSE_STATUS=", response.status if response else None)
    print("HTML_LENGTH=", len(html))
    print("HTML_PREVIEW=", html[:1000])


def fetch_pdf_in_browser(page, pdf_url: str) -> bytes:
    result = page.evaluate(
        """
        async ({ pdfUrl }) => {
          const resp = await fetch(pdfUrl, {
            method: "GET",
            credentials: "include",
            cache: "no-store",
            headers: {
              "Accept": "application/pdf,*/*"
            }
          });

          const buffer = await resp.arrayBuffer();
          const bytes = Array.from(new Uint8Array(buffer));
          const binary = bytes.reduce((s, b) => s + String.fromCharCode(b), "");

          return {
            ok: resp.ok,
            status: resp.status,
            contentType: resp.headers.get("content-type") || "",
            base64: btoa(binary)
          };
        }
        """,
        {"pdfUrl": pdf_url},
    )

    if not result["ok"]:
        raise RuntimeError(f"PDF 下載失敗: status={result['status']} url={pdf_url}")

    pdf_bytes = base64.b64decode(result["base64"])

    if not pdf_bytes:
        raise RuntimeError("PDF 內容為空")

    if not pdf_bytes.startswith(b"%PDF"):
        preview = pdf_bytes[:300].decode("utf-8", errors="replace")
        raise RuntimeError(
            "下載結果不是 PDF: "
            f"status={result['status']}, "
            f"content_type={result['contentType']}, "
            f"preview={preview}"
        )

    return pdf_bytes


def fetch_html_and_pdf() -> tuple[bytes, str, str]:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="zh-TW",
            timezone_id="Asia/Taipei",
            viewport={"width": 1366, "height": 900},
            extra_http_headers={
                "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;"
                    "q=0.9,image/avif,image/webp,*/*;q=0.8"
                ),
                "Referer": "https://www.taipower.com.tw/",
            },
        )

        page = context.new_page()

        try:
            response = page.goto(PAGE_URL, wait_until="domcontentloaded", timeout=60000)

            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeoutError:
                pass

            html = page.content()
            debug_html_state(page, response, html)

            if len(html) < 5000 or ".pdf" not in html.lower() or "簡明月報" not in html:
                raise RuntimeError(
                    "沒有拿到正常台電簡明月報頁面，可能被擋、被導頁或頁面尚未載入；"
                    f"url={page.url}, length={len(html)}, preview={html[:500]!r}"
                )

            pdf_url, title = extract_pdf_info_from_html(html)

            print(f"FOUND_TITLE={title}")
            print(f"FOUND_PDF_URL={pdf_url}")

            pdf_bytes = fetch_pdf_in_browser(page, pdf_url)
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
