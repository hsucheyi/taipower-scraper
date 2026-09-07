from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, unquote, urljoin, urlparse, parse_qs

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


PAGE_URL = (
    "https://www.taipower.com.tw/"
    "2289/2363/2373/2375/10359/normalPost"
)

BASE_DIR = Path("data/generation_cost_pdf")
ARCHIVE_DIR = BASE_DIR / "archive"
LATEST_PDF = BASE_DIR / "latest.pdf"
METADATA_FILE = BASE_DIR / "metadata.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

PDF_KEYWORD = "各種發電方式之發電成本"


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
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                print("WARNING: metadata.json 無法解析，視為空資料")

    return {}


def save_metadata(data: dict) -> None:
    METADATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def extract_pdf_info_from_html(html: str) -> tuple[str, str]:
    """
    從台電公告頁 HTML 中找 PDF URL。
    支援：
    /media/xxx.pdf
    https://xxx.taipower.com.tw/media/xxx.pdf
    """

    decoded_html = html_lib.unescape(html)

    patterns = [
        r'https?://[^"\'>\s]+\.pdf(?:\?[^"\'>\s]*)?',
        r'/media/[^"\'>\s]+\.pdf(?:\?[^"\'>\s]*)?',
    ]

    candidates: list[str] = []

    for pattern in patterns:
        matches = re.findall(
            pattern,
            decoded_html,
            flags=re.IGNORECASE,
        )

        for match in matches:
            candidate = match.strip()

            if PDF_KEYWORD in unquote(candidate):
                candidates.append(candidate)

    if not candidates:
        raise RuntimeError("HTML 中找不到發電成本 PDF URL")

    pdf_url = candidates[0]

    if pdf_url.startswith("/"):
        pdf_url = urljoin(PAGE_URL, pdf_url)

    title_match = re.search(
        r'(各種發電方式之發電成本[^<"\']*(?:\(PDF\))?)',
        decoded_html,
        flags=re.IGNORECASE,
    )

    if title_match:
        title = title_match.group(1).strip()
    else:
        title = extract_title_from_pdf_url(pdf_url)

    return pdf_url, title


def extract_title_from_pdf_url(pdf_url: str) -> str:
    path = urlparse(pdf_url).path
    filename = unquote(Path(path).name)

    filename = re.sub(
        r"\.pdf$",
        "",
        filename,
        flags=re.IGNORECASE,
    )

    if filename:
        return f"{filename}(PDF)"

    return "各種發電方式之發電成本(PDF)"


def extract_period_from_title(text: str) -> tuple[int, int]:
    """
    將：
    各種發電方式之發電成本-115年5月底止

    轉成：
    (115, 5)

    找不到時回傳 (0, 0)
    """

    text = unquote(text)

    match = re.search(
        r"(\d{3})年\s*(\d{1,2})月",
        text,
    )

    if not match:
        return 0, 0

    roc_year = int(match.group(1))
    month = int(match.group(2))

    return roc_year, month


def normalize_search_result_url(url: str) -> str | None:
    """
    將搜尋引擎可能包裝過的 URL 還原。

    同時只允許台電網域的 PDF。
    """

    url = html_lib.unescape(url)
    url = unquote(url)

    # Google redirect:
    # /url?q=https://...
    if url.startswith("/url?"):
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        if "q" in query:
            url = query["q"][0]

    if url.startswith("//"):
        url = "https:" + url

    if not url.startswith("http"):
        return None

    parsed = urlparse(url)

    hostname = (parsed.hostname or "").lower()

    if not (
        hostname == "taipower.com.tw"
        or hostname.endswith(".taipower.com.tw")
    ):
        return None

    if ".pdf" not in parsed.path.lower():
        return None

    if PDF_KEYWORD not in unquote(url):
        return None

    return url


def extract_pdf_urls_from_search_html(html: str) -> list[str]:
    """
    從搜尋結果 HTML 找出候選 PDF。
    """

    decoded_html = html_lib.unescape(html)

    raw_urls = re.findall(
        r'href=["\']([^"\']+)["\']',
        decoded_html,
        flags=re.IGNORECASE,
    )

    results: list[str] = []

    for raw_url in raw_urls:
        url = normalize_search_result_url(raw_url)

        if not url:
            continue

        if url not in results:
            results.append(url)

    # 有些搜尋結果網址可能直接出現在 HTML，不一定在 href
    direct_urls = re.findall(
        r'https?://[^"\'>\s]+\.pdf(?:\?[^"\'>\s]*)?',
        decoded_html,
        flags=re.IGNORECASE,
    )

    for raw_url in direct_urls:
        url = normalize_search_result_url(raw_url)

        if not url:
            continue

        if url not in results:
            results.append(url)

    return results


def choose_latest_pdf(urls: list[str]) -> str:
    if not urls:
        raise RuntimeError("Fallback 搜尋不到任何台電發電成本 PDF")

    ranked = []

    for url in urls:
        period = extract_period_from_title(url)

        ranked.append(
            (
                period[0],
                period[1],
                url,
            )
        )

    ranked.sort(
        key=lambda x: (x[0], x[1]),
        reverse=True,
    )

    print("PDF_CANDIDATES=")

    for year, month, url in ranked[:10]:
        print(f"  {year}/{month}: {url}")

    latest_url = ranked[0][2]

    print(f"SELECTED_FALLBACK_PDF={latest_url}")

    return latest_url


def search_latest_pdf(page) -> tuple[str, str]:
    """
    normalPost 被 CloudFront 403 時，
    改用搜尋引擎搜尋已被索引的台電 PDF。

    依序嘗試 Bing 與 Google。
    """

    query = (
        'site:taipower.com.tw '
        '"各種發電方式之發電成本" filetype:pdf'
    )

    search_urls = [
        f"https://www.google.com/search?q={quote_plus(query)}",
        f"https://www.bing.com/search?q={quote_plus(query)}",
    ]

    candidates: list[str] = []

    for search_url in search_urls:
        try:
            print(f"SEARCH_URL={search_url}")

            response = page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            if response is None:
                print("SEARCH_RESPONSE=None")
                continue

            print(f"SEARCH_STATUS={response.status}")

            try:
                page.wait_for_load_state(
                    "networkidle",
                    timeout=5000,
                )
            except PlaywrightTimeoutError:
                pass

            search_html = page.content()

            found = extract_pdf_urls_from_search_html(
                search_html
            )

            print(
                f"SEARCH_FOUND_PDFS={len(found)}"
            )

            for url in found:
                if url not in candidates:
                    candidates.append(url)

        except Exception as exc:
            print(
                f"SEARCH_WARNING={type(exc).__name__}: {exc}"
            )

    if not candidates:
        raise RuntimeError(
            "台電 normalPost 被阻擋，"
            "而搜尋引擎 fallback 也找不到 PDF"
        )

    pdf_url = choose_latest_pdf(candidates)
    title = extract_title_from_pdf_url(pdf_url)

    return pdf_url, title


def download_pdf(context, pdf_url: str) -> bytes:
    """
    嘗試直接透過 Playwright request context 下載 PDF。
    """

    print(f"DOWNLOAD_URL={pdf_url}")

    response = context.request.get(
        pdf_url,
        timeout=60000,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "application/pdf,"
                "application/octet-stream;q=0.9,"
                "*/*;q=0.8"
            ),
            "Referer": PAGE_URL,
        },
    )

    print(f"PDF_STATUS={response.status}")

    if not response.ok:
        raise RuntimeError(
            f"PDF 下載失敗: HTTP {response.status}"
        )

    pdf_bytes = response.body()

    if not pdf_bytes:
        raise RuntimeError("PDF 內容為空")

    # PDF 正常應該以 %PDF 開頭
    if not pdf_bytes.startswith(b"%PDF"):
        preview = pdf_bytes[:200]

        raise RuntimeError(
            "下載結果不是 PDF。"
            f"前 200 bytes={preview!r}"
        )

    print(f"PDF_SIZE={len(pdf_bytes)}")

    return pdf_bytes


def fetch_html_and_pdf() -> tuple[bytes, str, str]:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
        )

        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="zh-TW",
            viewport={
                "width": 1366,
                "height": 768,
            },
        )

        page = context.new_page()

        try:
            pdf_url: str | None = None
            title: str | None = None

            print("TRY_NORMAL_POST=true")

            try:
                response = page.goto(
                    PAGE_URL,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )

                if response is None:
                    raise RuntimeError(
                        "page.goto 沒有取得 HTTP response"
                    )

                print(
                    f"PAGE_STATUS={response.status}"
                )
                print(
                    f"FINAL_URL={page.url}"
                )

                try:
                    page.wait_for_load_state(
                        "networkidle",
                        timeout=10000,
                    )
                except PlaywrightTimeoutError:
                    pass

                page_html = page.content()

                print(
                    f"HTML_LENGTH={len(page_html)}"
                )

                if response.status >= 400:
                    print(
                        "NORMAL_POST_FAILED="
                        f"HTTP {response.status}"
                    )

                    print(
                        "PAGE_HTML_PREVIEW="
                        f"{page_html[:1000]}"
                    )

                    raise RuntimeError(
                        f"台電 normalPost HTTP "
                        f"{response.status}"
                    )

                pdf_url, title = (
                    extract_pdf_info_from_html(
                        page_html
                    )
                )

                print(
                    "NORMAL_POST_SUCCESS=true"
                )

            except Exception as exc:
                print(
                    "NORMAL_POST_WARNING="
                    f"{type(exc).__name__}: {exc}"
                )

                print(
                    "USING_SEARCH_FALLBACK=true"
                )

                pdf_url, title = (
                    search_latest_pdf(page)
                )

            if not pdf_url:
                raise RuntimeError(
                    "最終仍找不到 PDF URL"
                )

            if not title:
                title = (
                    extract_title_from_pdf_url(
                        pdf_url
                    )
                )

            print(f"FOUND_TITLE={title}")
            print(f"FOUND_PDF_URL={pdf_url}")

            pdf_bytes = download_pdf(
                context,
                pdf_url,
            )

            return (
                pdf_bytes,
                title,
                pdf_url,
            )

        finally:
            browser.close()


def main() -> int:
    BASE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    ARCHIVE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    pdf_bytes, title, pdf_url = (
        fetch_html_and_pdf()
    )

    new_sha = sha256_bytes(pdf_bytes)

    old_metadata = load_metadata()
    old_sha = old_metadata.get("sha256")

    print(f"NEW_SHA256={new_sha}")
    print(f"OLD_SHA256={old_sha}")

    if new_sha == old_sha:
        print("UPDATED=false")
        print("No change detected.")
        print(f"TITLE={title}")
        print(f"PDF_URL={pdf_url}")

        return 0

    LATEST_PDF.write_bytes(
        pdf_bytes
    )

    timestamp = (
        datetime.now(timezone.utc)
        .strftime("%Y%m%dT%H%M%SZ")
    )

    archive_name = (
        f"{timestamp}_"
        f"{sanitize_filename(title)}.pdf"
    )

    archive_path = (
        ARCHIVE_DIR / archive_name
    )

    archive_path.write_bytes(
        pdf_bytes
    )

    metadata = {
        "page_url": PAGE_URL,
        "pdf_url": pdf_url,
        "title": title,
        "sha256": new_sha,
        "latest_file": str(LATEST_PDF),
        "archived_file": str(archive_path),
        "fetched_at_utc": (
            datetime.now(timezone.utc)
            .isoformat()
        ),
    }

    save_metadata(metadata)

    print("UPDATED=true")
    print(f"TITLE={title}")
    print(f"PDF_URL={pdf_url}")
    print(
        f"ARCHIVED_FILE={archive_path}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
