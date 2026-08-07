"""
Extracts Google Drive links from the index PDFs.

The index PDFs render link titles as plain text (e.g. "Working with Your
Spirit Animal") with the actual URL attached as a clickable link
annotation, not as visible text. A plain text scrape of the PDF will
therefore miss almost every link. This module uses PyMuPDF to read the
real link annotations on every page, and additionally regex-scans the
visible text as a fallback in case a URL was ever pasted in as plain text.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import pymupdf as fitz  # PyMuPDF (the "fitz" import name is a deprecated alias)

import config

log = logging.getLogger("belief_coding_importer.pdf_parser")

# Matches drive.google.com / docs.google.com URLs of every shape we've seen
# Belief Coding use: folders, files, native Docs/Sheets/Slides/Forms, and
# the various id-in-querystring variants.
_URL_RE = re.compile(
    r"https?://(?:drive|docs)\.google\.com/[^\s\"'<>)\]]+",
    re.IGNORECASE,
)

_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"/drive/folders/([a-zA-Z0-9_-]+)"), "folder"),
    (re.compile(r"/drive/u/\d+/folders/([a-zA-Z0-9_-]+)"), "folder"),
    (re.compile(r"/folderview\?id=([a-zA-Z0-9_-]+)"), "folder"),
    (re.compile(r"/file/d/([a-zA-Z0-9_-]+)"), "file"),
    (re.compile(r"/document/d/([a-zA-Z0-9_-]+)"), "file"),
    (re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]+)"), "file"),
    (re.compile(r"/presentation/d/([a-zA-Z0-9_-]+)"), "file"),
    (re.compile(r"/forms/d/([a-zA-Z0-9_-]+)"), "file"),
    (re.compile(r"[?&]id=([a-zA-Z0-9_-]+)"), "file"),  # open?id=, uc?id=
]


@dataclass(frozen=True)
class DriveLink:
    url: str
    kind: str          # 'file' or 'folder'
    drive_id: str
    source_pdf: str
    page_number: int
    label: str          # best-effort nearby text, for logging/debugging only


def parse_drive_url(url: str) -> Optional[Tuple[str, str]]:
    """Return (kind, drive_id) for a Google Drive URL, or None if the URL
    isn't a recognisable Drive link (e.g. it's some other website)."""
    if "drive.google.com" not in url and "docs.google.com" not in url:
        return None
    for pattern, kind in _PATTERNS:
        match = pattern.search(url)
        if match:
            return kind, match.group(1)
    return None


def _label_near_link(page: "fitz.Page", rect: "fitz.Rect") -> str:
    """Best-effort text label for a link, used only for readable logging."""
    try:
        text = page.get_textbox(rect).strip()
        if text:
            return " ".join(text.split())
        # Some PDFs anchor the link to a thin arrow icon rather than the
        # text itself - widen the search to the full line.
        expanded = fitz.Rect(0, rect.y0 - 2, page.rect.width, rect.y1 + 2)
        text = page.get_textbox(expanded).strip()
        return " ".join(text.split())[:120]
    except Exception:
        return ""


def extract_links_from_pdf(pdf_path: Path) -> List[DriveLink]:
    """Extract every Google Drive link (via link annotations and, as a
    fallback, raw URLs visible in the page text) from a single PDF."""
    links: List[DriveLink] = []
    seen_urls = set()

    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        log.error("Could not open PDF %s: %s", pdf_path, exc)
        return links

    with doc:
        for page_index, page in enumerate(doc, start=1):
            # 1) Real clickable link annotations (the primary source).
            for link in page.get_links():
                url = link.get("uri")
                if not url:
                    continue
                parsed = parse_drive_url(url)
                if not parsed:
                    continue
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                kind, drive_id = parsed
                rect = fitz.Rect(link.get("from")) if link.get("from") else None
                label = _label_near_link(page, rect) if rect else ""
                links.append(DriveLink(url, kind, drive_id, pdf_path.name, page_index, label))

            # 2) Fallback: any raw URL typed directly into the page text.
            text = page.get_text()
            for match in _URL_RE.finditer(text):
                url = match.group(0).rstrip(").,;")
                if url in seen_urls:
                    continue
                parsed = parse_drive_url(url)
                if not parsed:
                    continue
                seen_urls.add(url)
                kind, drive_id = parsed
                links.append(DriveLink(url, kind, drive_id, pdf_path.name, page_index, ""))

    log.info("Parsed %s: found %d Drive link(s)", pdf_path.name, len(links))
    return links


def index_pdf_filenames(pdf_folder: Path = config.PDF_FOLDER) -> set:
    """Filenames (lowercased) of every index PDF supplied by the user.
    These must never be uploaded, even if the same file is also found
    while crawling Drive (e.g. duplicated into a wrapper folder there)."""
    return {p.name.lower() for p in Path(pdf_folder).glob("*.pdf")}


def collect_all_links(pdf_folder: Path = config.PDF_FOLDER) -> List[DriveLink]:
    """Parse every PDF in pdf_folder and return the de-duplicated union of
    all Drive links found across all of them."""
    pdf_folder = Path(pdf_folder)
    pdf_paths = sorted(pdf_folder.glob("*.pdf"))
    if not pdf_paths:
        log.warning("No PDFs found in %s", pdf_folder)

    all_links: List[DriveLink] = []
    seen_urls = set()
    for pdf_path in pdf_paths:
        for link in extract_links_from_pdf(pdf_path):
            if link.url in seen_urls:
                continue
            seen_urls.add(link.url)
            all_links.append(link)

    return all_links
