from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, unquote, urljoin, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


# ============================================================
# 基本設定
# ============================================================

PAGE_URL = (
    "https://www.taipower.com.tw/"
    "2289/2363/2373/2375/10359/normalPost"
)

BASE_DIR = Path("data/generation_cost_pdf")
ARCHIVE_DIR = BASE_DIR / "archive"
LATEST_PDF = BASE_DIR / "latest.pdf"
METADATA_FILE = BASE_DIR / "metadata.json"

PDF_KEYWORD = "各種發電方式之發電成本"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ============================================================
# 基本工具
# ============================================================

def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", "_", name).strip("_")

    return name or "taipower_generation_cost"


def load_metadata() -> dict:
    if not METADATA_FILE.exists():
        return {}

    text = METADATA_FILE.read_text(
        encoding="utf-8"
    ).strip()

    if not text:
        return {}

    try:
        return json.loads(text)

    except json.JSONDecodeError:
        print(
            "WARNING: metadata.json 無法解析，"
            "本次視為沒有舊 metadata"
        )

        return {}


def save_metadata(data: dict) -> None:
    METADATA_FILE.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


# ============================================================
# PDF title / 年月判斷
# ============================================================

def extract_title_from_pdf_url(
    pdf_url: str,
) -> str:

    path = urlparse(pdf_url).path

    filename = unquote(
        Path(path).name
    )

    filename = re.sub(
        r"\.pdf$",
        "",
        filename,
        flags=re.IGNORECASE,
    )

    if filename:
        return f"{filename}(PDF)"

    return (
        "各種發電方式之發電成本(PDF)"
    )


def extract_period(
    text: str,
) -> tuple[int, int]:

    """
    範例：

    各種發電方式之發電成本-115年5月底止.pdf

    回傳：

    (115, 5)
    """

    text = unquote(
        html_lib.unescape(text)
    )

    match = re.search(
        r"(\d{3})年\s*(\d{1,2})月",
        text,
    )

    if not match:
        return 0, 0

    roc_year = int(
        match.group(1)
    )

    month = int(
        match.group(2)
    )

    return roc_year, month


# ============================================================
# 台電正常 normalPost 頁面解析
# ============================================================

def extract_pdf_info_from_html(
    html: str,
) -> tuple[str, str]:

    decoded_html = html_lib.unescape(
        html
    )

    patterns = [
        (
            r'https?://[^"\'>\s]+'
            r'\.pdf(?:\?[^"\'>\s]*)?'
        ),
        (
            r'/media/[^"\'>\s]+'
            r'\.pdf(?:\?[^"\'>\s]*)?'
        ),
    ]

    candidates: list[str] = []

    for pattern in patterns:

        matches = re.findall(
            pattern,
            decoded_html,
            flags=re.IGNORECASE,
        )

        for match in matches:

            decoded_url = unquote(
                match
            )

            if PDF_KEYWORD not in decoded_url:
                continue

            url = match

            if url.startswith("/"):
                url = urljoin(
                    PAGE_URL,
                    url,
                )

            if url not in candidates:
                candidates.append(url)

    if not candidates:

        raise RuntimeError(
            "HTML 中找不到發電成本 PDF URL"
        )

    # 如果同頁面出現多個 PDF，
    # 用 ROC 年 / 月找最新
    candidates.sort(
        key=extract_period,
        reverse=True,
    )

    pdf_url = candidates[0]

    title = extract_title_from_pdf_url(
        pdf_url
    )

    return pdf_url, title


# ============================================================
# 搜尋結果 URL 驗證
# ============================================================

def is_taipower_pdf(
    url: str,
) -> bool:

    if not url:
        return False

    url = html_lib.unescape(
        url
    ).strip()

    try:
        parsed = urlparse(url)
    except Exception:
        return False

    hostname = (
        parsed.hostname or ""
    ).lower()

    # 接受：
    # www.taipower.com.tw
    # hc1.taipower.com.tw
    # hc2.taipower.com.tw
    # 以及其他台電子網域

    if not (
        hostname == "taipower.com.tw"
        or hostname.endswith(
            ".taipower.com.tw"
        )
    ):
        return False

    decoded = unquote(url)

    if ".pdf" not in decoded.lower():
        return False

    if PDF_KEYWORD not in decoded:
        return False

    return True


# ============================================================
# Bing RSS fallback
# ============================================================

def search_bing_rss(
    context,
    query: str,
) -> list[str]:

    search_url = (
        "https://www.bing.com/search"
        "?format=rss"
        "&q="
        + quote_plus(query)
    )

    print(
        f"BING_RSS_QUERY={query}"
    )

    print(
        f"BING_RSS_URL={search_url}"
    )

    try:

        response = context.request.get(
            search_url,
            timeout=60000,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": (
                    "application/rss+xml,"
                    "application/xml,"
                    "text/xml,"
                    "*/*"
                ),
            },
        )

    except Exception as exc:

        print(
            "BING_RSS_REQUEST_WARNING="
            f"{type(exc).__name__}: {exc}"
        )

        return []

    print(
        f"BING_RSS_STATUS={response.status}"
    )

    if not response.ok:
        return []

    body = response.body()

    if not body:
        return []

    try:

        text = body.decode(
            "utf-8",
            errors="replace",
        )

        root = ET.fromstring(text)

    except Exception as exc:

        print(
            "BING_RSS_PARSE_WARNING="
            f"{type(exc).__name__}: {exc}"
        )

        print(
            "BING_RSS_PREVIEW="
            f"{body[:1000]!r}"
        )

        return []

    urls: list[str] = []

    for item in root.findall(
        ".//item"
    ):

        link = item.findtext(
            "link"
        )

        title = item.findtext(
            "title"
        ) or ""

        if not link:
            continue

        link = html_lib.unescape(
            link
        ).strip()

        if is_taipower_pdf(link):

            if link not in urls:
                urls.append(link)

                print(
                    "BING_RSS_FOUND="
                    f"{title} | {link}"
                )

    print(
        f"BING_RSS_FOUND_COUNT="
        f"{len(urls)}"
    )

    return urls


# ============================================================
# Bing RSS 多組查詢
# ============================================================

def search_latest_pdf(
    context,
) -> tuple[str, str]:

    """
    normalPost 被 CloudFront 403 時，
    透過 Bing RSS 找台電已公開索引的 PDF。
    """

    current_year = datetime.now(
        timezone.utc
    ).year

    roc_year = (
        current_year - 1911
    )

    queries = [
        (
            f'site:taipower.com.tw '
            f'"{PDF_KEYWORD}" '
            f'"{roc_year}年" '
            f'filetype:pdf'
        ),
        (
            f'site:taipower.com.tw '
            f'"{PDF_KEYWORD}" '
            f'filetype:pdf'
        ),
        (
            f'"{PDF_KEYWORD}" '
            f'"{roc_year}年" '
            f'taipower pdf'
        ),
        (
            f'"{PDF_KEYWORD}" '
            f'taipower pdf'
        ),
    ]

    all_candidates: list[str] = []

    for query in queries:

        found = search_bing_rss(
            context,
            query,
        )

        for url in found:

            if url not in all_candidates:
                all_candidates.append(
                    url
                )

    if not all_candidates:

        raise RuntimeError(
            "台電 normalPost 被阻擋，"
            "而 Bing RSS fallback "
            "也找不到發電成本 PDF"
        )

    print(
        "==== PDF CANDIDATES ===="
    )

    ranked: list[
        tuple[int, int, str]
    ] = []

    for url in all_candidates:

        year, month = extract_period(
            url
        )

        ranked.append(
            (
                year,
                month,
                url,
            )
        )

    ranked.sort(
        key=lambda item: (
            item[0],
            item[1],
        ),
        reverse=True,
    )

    for (
        year,
        month,
        url,
    ) in ranked:

        print(
            f"CANDIDATE="
            f"{year}/{month} "
            f"{url}"
        )

    latest_url = ranked[0][2]

    latest_title = (
        extract_title_from_pdf_url(
            latest_url
        )
    )

    print(
        f"SELECTED_PDF="
        f"{latest_url}"
    )

    return (
        latest_url,
        latest_title,
    )


# ============================================================
# PDF 下載
# ============================================================

def download_pdf(
    context,
    pdf_url: str,
) -> bytes:

    print(
        f"DOWNLOAD_URL={pdf_url}"
    )

    response = context.request.get(
        pdf_url,
        timeout=60000,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "application/pdf,"
                "application/octet-stream,"
                "*/*;q=0.8"
            ),
            "Referer": PAGE_URL,
        },
    )

    print(
        f"PDF_STATUS={response.status}"
    )

    if not response.ok:

        raise RuntimeError(
            "PDF 下載失敗: "
            f"HTTP {response.status}"
        )

    pdf_bytes = response.body()

    if not pdf_bytes:

        raise RuntimeError(
            "PDF 內容為空"
        )

    print(
        f"PDF_SIZE={len(pdf_bytes)}"
    )

    # 防止把 CloudFront 403 HTML
    # 誤存成 latest.pdf

    if not pdf_bytes.startswith(
        b"%PDF"
    ):

        preview = pdf_bytes[
            :500
        ]

        raise RuntimeError(
            "下載結果不是 PDF。"
            "可能又被 CloudFront 阻擋。"
            "\n"
            f"CONTENT_PREVIEW="
            f"{preview!r}"
        )

    return pdf_bytes


# ============================================================
# 主抓取流程
# ============================================================

def fetch_html_and_pdf(
) -> tuple[
    bytes,
    str,
    str,
]:

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
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

            # =================================================
            # 方法 1：
            # 台電 normalPost
            # =================================================

            print(
                "TRY_NORMAL_POST=true"
            )

            try:

                response = page.goto(
                    PAGE_URL,
                    wait_until=(
                        "domcontentloaded"
                    ),
                    timeout=60000,
                )

                if response is None:

                    raise RuntimeError(
                        "page.goto "
                        "沒有取得 HTTP response"
                    )

                print(
                    f"PAGE_STATUS="
                    f"{response.status}"
                )

                print(
                    f"FINAL_URL="
                    f"{page.url}"
                )

                try:

                    page.wait_for_load_state(
                        "networkidle",
                        timeout=10000,
                    )

                except (
                    PlaywrightTimeoutError
                ):

                    pass

                page_html = (
                    page.content()
                )

                print(
                    f"HTML_LENGTH="
                    f"{len(page_html)}"
                )

                if response.status >= 400:

                    print(
                        "NORMAL_POST_FAILED="
                        f"HTTP "
                        f"{response.status}"
                    )

                    print(
                        "PAGE_HTML_PREVIEW="
                        f"{page_html[:1000]}"
                    )

                    raise RuntimeError(
                        "台電 normalPost "
                        f"HTTP "
                        f"{response.status}"
                    )

                (
                    pdf_url,
                    title,
                ) = (
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
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

                # =============================================
                # 方法 2：
                # Bing RSS
                # =============================================

                print(
                    "USING_BING_RSS_FALLBACK="
                    "true"
                )

                (
                    pdf_url,
                    title,
                ) = search_latest_pdf(
                    context
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

            print(
                f"FOUND_TITLE={title}"
            )

            print(
                f"FOUND_PDF_URL="
                f"{pdf_url}"
            )

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


# ============================================================
# main
# ============================================================

def main() -> int:

    BASE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    ARCHIVE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        pdf_bytes,
        title,
        pdf_url,
    ) = fetch_html_and_pdf()

    # ========================================================
    # SHA256
    # ========================================================

    new_sha = sha256_bytes(
        pdf_bytes
    )

    old_metadata = (
        load_metadata()
    )

    old_sha = old_metadata.get(
        "sha256"
    )

    print(
        f"NEW_SHA256={new_sha}"
    )

    print(
        f"OLD_SHA256={old_sha}"
    )

    # ========================================================
    # 沒更新
    # ========================================================

    if new_sha == old_sha:

        print(
            "UPDATED=false"
        )

        print(
            "No change detected."
        )

        print(
            f"TITLE={title}"
        )

        print(
            f"PDF_URL={pdf_url}"
        )

        return 0

    # ========================================================
    # 有更新
    # ========================================================

    LATEST_PDF.write_bytes(
        pdf_bytes
    )

    timestamp = (
        datetime.now(
            timezone.utc
        )
        .strftime(
            "%Y%m%dT%H%M%SZ"
        )
    )

    archive_name = (
        f"{timestamp}_"
        f"{sanitize_filename(title)}"
        f".pdf"
    )

    archive_path = (
        ARCHIVE_DIR
        / archive_name
    )

    archive_path.write_bytes(
        pdf_bytes
    )

    metadata = {
        "page_url": PAGE_URL,
        "pdf_url": pdf_url,
        "title": title,
        "sha256": new_sha,
        "latest_file": str(
            LATEST_PDF
        ),
        "archived_file": str(
            archive_path
        ),
        "fetched_at_utc": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
    }

    save_metadata(
        metadata
    )

    print(
        "UPDATED=true"
    )

    print(
        f"TITLE={title}"
    )

    print(
        f"PDF_URL={pdf_url}"
    )

    print(
        f"ARCHIVED_FILE="
        f"{archive_path}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
