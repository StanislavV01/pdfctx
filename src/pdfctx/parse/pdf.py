from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

from . import ocr
from .blocks import body_size, group_blocks
from .lines import drop_running_lines, lines_from_words, page_words
from .model import ParsedDoc, Word
from .tables import find_tables

# pdfium is not thread-safe: every call into it (parsing, page renders, page counts) holds this lock.
PDFIUM_LOCK = threading.RLock()


def _error(e: Exception) -> str:
    text = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    return text[:200]


def parse_pdf(path: Path) -> ParsedDoc:
    """Parse a PDF into headings, paragraphs and tables. Never raises for a bad file.

    pdfium work happens under PDFIUM_LOCK; OCR of image-only pages and the layout analysis run outside it,
    so a long scan does not block page renders for everyone else.
    """
    path = Path(path)
    with PDFIUM_LOCK:
        raw = _extract(path)
    if isinstance(raw, ParsedDoc):
        return raw
    try:
        return _assemble(raw, path)
    except Exception as e:
        return ParsedDoc(path, path.stem, raw.pages, status="failed", error=_error(e))


@dataclass
class _Raw:
    pages: int
    words: dict[int, list[Word]]
    widths: dict[int, float]
    heights: dict[int, float]
    ocr_wanted: list[int]  # pages without a text layer
    bookmarks: list[tuple[int, str, int]]
    meta_title: str


def _extract(path: Path) -> _Raw | ParsedDoc:
    try:
        pdf = pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as e:
        status = "encrypted" if "password" in str(e).lower() else "failed"
        return ParsedDoc(path, path.stem, 0, status=status, error=_error(e))
    except Exception as e:  # pragma: no cover - defensive: unreadable file
        return ParsedDoc(path, path.stem, 0, status="failed", error=_error(e))
    try:
        n = len(pdf)
        raw = _Raw(n, {}, {}, {}, [], [], "")
        do_ocr = ocr.available()
        for i in range(n):
            page = pdf[i]
            no = i + 1
            raw.widths[no], raw.heights[no] = page.get_width(), page.get_height()
            raw.words[no] = page_words(page)
            if do_ocr and sum(len(w.text) for w in raw.words[no]) < 5:
                raw.ocr_wanted.append(no)  # rendered one at a time later, never all at once
            page.close()
        for item in pdf.get_toc():
            dest = item.get_dest()
            index = dest.get_index() if dest is not None else None
            title = (item.get_title() or "").strip()
            if index is not None and title:
                raw.bookmarks.append((item.level + 1, title, index + 1))
        raw.meta_title = (pdf.get_metadata_dict().get("Title") or "").strip()
        return raw
    except Exception as e:
        return ParsedDoc(path, path.stem, len(pdf), status="failed", error=_error(e))
    finally:
        pdf.close()


def _render_for_ocr(path: Path, no: int) -> tuple[Image.Image, float] | None:
    """One page at OCR resolution, scaled to stay under ocr.MAX_PIXELS; the lock is held only here."""
    with PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(str(path))
        try:
            page = pdf[no - 1]
            w, h = page.get_size()
            scale = min(ocr.DPI / 72, (ocr.MAX_PIXELS / max(w * h, 1.0)) ** 0.5)
            if scale < 1.0:  # under 72 dpi OCR is useless: a huge page, skip it
                return None
            return page.render(scale=scale).to_pil(), scale
        finally:
            pdf.close()


def _assemble(raw: _Raw, path: Path) -> ParsedDoc:
    ocr_pages = []
    deadline = time.monotonic() + ocr.budget_s()
    for no in raw.ocr_wanted[: ocr.max_pages()]:
        if time.monotonic() > deadline:
            break
        rendered = _render_for_ocr(path, no)
        if rendered is None:
            continue
        words = ocr.ocr_image(*rendered)
        if words:
            raw.words[no] = words
            ocr_pages.append(no)
    by_page = {no: lines_from_words(raw.words[no], raw.widths[no], no) for no in range(1, raw.pages + 1)}
    by_page = drop_running_lines(by_page, raw.heights)
    all_lines = [ln for lines in by_page.values() for ln in lines]
    if sum(len(ln.text) for ln in all_lines) < 20:
        return ParsedDoc(path, path.stem, raw.pages, status="no_text")

    body = body_size(all_lines)
    blocks = []
    for page_no in sorted(by_page):
        lines = by_page[page_no]
        blocks.extend(group_blocks(lines, body, find_tables(lines)))

    first_heading = next((b.text for b in blocks if b.kind == "heading"), "")
    title = raw.meta_title or first_heading or path.stem
    return ParsedDoc(path, title, raw.pages, blocks=blocks, bookmarks=raw.bookmarks, ocr_pages=ocr_pages)
