from __future__ import annotations

import threading
from pathlib import Path

import pypdfium2 as pdfium

from .blocks import body_size, group_blocks
from .lines import drop_running_lines, page_lines
from .model import ParsedDoc
from .tables import find_tables

# pdfium is not thread-safe: every call into it (parsing, page renders, page counts) holds this lock.
PDFIUM_LOCK = threading.RLock()


def _error(e: Exception) -> str:
    text = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    return text[:200]


def parse_pdf(path: Path) -> ParsedDoc:
    """Parse a PDF into headings, paragraphs and tables. Never raises for a bad file."""
    with PDFIUM_LOCK:
        return _parse_locked(Path(path))


def _parse_locked(path: Path) -> ParsedDoc:
    try:
        pdf = pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as e:
        status = "encrypted" if "password" in str(e).lower() else "failed"
        return ParsedDoc(path, path.stem, 0, status=status, error=_error(e))
    except Exception as e:  # pragma: no cover - defensive: unreadable file
        return ParsedDoc(path, path.stem, 0, status="failed", error=_error(e))
    try:
        return _parse(pdf, path)
    except Exception as e:
        return ParsedDoc(path, path.stem, len(pdf), status="failed", error=_error(e))
    finally:
        pdf.close()


def _parse(pdf: pdfium.PdfDocument, path: Path) -> ParsedDoc:
    n = len(pdf)
    by_page, heights = {}, {}
    for i in range(n):
        page = pdf[i]
        heights[i + 1] = page.get_height()
        by_page[i + 1] = page_lines(page, i + 1)
        page.close()
    by_page = drop_running_lines(by_page, heights)
    all_lines = [ln for lines in by_page.values() for ln in lines]
    if sum(len(ln.text) for ln in all_lines) < 20:
        return ParsedDoc(path, path.stem, n, status="no_text")

    body = body_size(all_lines)
    blocks = []
    for page_no in sorted(by_page):
        lines = by_page[page_no]
        blocks.extend(group_blocks(lines, body, find_tables(lines)))

    bookmarks = []
    for item in pdf.get_toc():
        dest = item.get_dest()
        index = dest.get_index() if dest is not None else None
        title = (item.get_title() or "").strip()
        if index is not None and title:
            bookmarks.append((item.level + 1, title, index + 1))

    meta_title = (pdf.get_metadata_dict().get("Title") or "").strip()
    first_heading = next((b.text for b in blocks if b.kind == "heading"), "")
    title = meta_title or first_heading or path.stem
    return ParsedDoc(path, title, n, blocks=blocks, bookmarks=bookmarks)
