from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

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
        return json.loads(METADATA_FILE.read_text(encoding="utf-8"))
    return {}


def save_metadata(data: dict) -> None:
    METADATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def find_pdf_link(html: str, base_url: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")

    # 優先找 href 直接含 .pdf 的連結
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(" ", strip=True)
        if ".pdf" in href.lower():
            return urljoin(base_url, href), text

    # 備援：找文字含 PDF 的連結
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(" ", strip=True)
        if "pdf" in text.lower():
            return urljoin(base_url, href), text

    raise RuntimeError("找不到 PDF 連結")


def main() -> int:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; GitHubActions Taipower PDF Watcher)"
    })

    page_resp = session.get(PAGE_URL, timeout=30)
    page_resp.raise_for_status()

    pdf_url, title = find_pdf_link(page_resp.text, PAGE_URL)

    pdf_resp = session.get(pdf_url, timeout=60)
    pdf_resp.raise_for_status()
    pdf_bytes = pdf_resp.content

    new_sha = sha256_bytes(pdf_bytes)
    old_metadata = load_metadata()
    old_sha = old_metadata.get("sha256")

    if new_sha == old_sha:
        print("UPDATED=false")
        print("No change detected.")
        return 0

    # 寫 latest
    LATEST_PDF.write_bytes(pdf_bytes)

    # 寫 archive
    archive_name = sanitize_filename(title) + ".pdf"
    archive_path = ARCHIVE_DIR / archive_name
    archive_path.write_bytes(pdf_bytes)

    metadata = {
        "page_url": PAGE_URL,
        "pdf_url": pdf_url,
        "title": title,
        "sha256": new_sha,
        "latest_file": str(LATEST_PDF),
        "archived_file": str(archive_path),
    }
    save_metadata(metadata)

    print("UPDATED=true")
    print(f"TITLE={title}")
    print(f"PDF_URL={pdf_url}")
    print(f"ARCHIVED_FILE={archive_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
