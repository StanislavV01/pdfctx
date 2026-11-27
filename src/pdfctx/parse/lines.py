"""Characters → words → lines, with column splitting and running header/footer removal."""

from __future__ import annotations

import ctypes
import re
from collections import defaultdict

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from .model import Line, Word

_BOLD_NAME = re.compile(r"bold|black|heavy|semibold|demi", re.I)
_NUMERIC = re.compile(r"^[$(\-–—]*[\d,.%]+[)%]*$|^[$—–-]$")


def page_words(page: pdfium.PdfPage) -> list[Word]:
    """All words on a page with loose boxes (top-left origin), font size and boldness."""
    height = page.get_height()
    textpage = page.get_textpage()
    n = textpage.count_chars()
    name_buf = ctypes.create_string_buffer(128)
    flags = ctypes.c_int()
    font_cache: dict[int, bool] = {}

    words: list[Word] = []
    chars: list[str] = []
    box: list[float] = []  # x0, top, x1, bottom
    sizes: list[float] = []
    bolds: list[bool] = []

    def flush() -> None:
        if chars:
            sizes.sort()
            words.append(
                Word(
                    text="".join(chars),
                    x0=box[0],
                    top=box[1],
                    x1=box[2],
                    bottom=box[3],
                    size=round(sizes[len(sizes) // 2], 1),
                    bold=sum(bolds) * 2 > len(bolds),
                )
            )
        chars.clear()
        box.clear()
        sizes.clear()
        bolds.clear()

    for i in range(n):
        code = pdfium_c.FPDFText_GetUnicode(textpage.raw, i)
        ch = chr(code) if code else ""
        if not ch or ch.isspace() or code in (0xFFFE, 0xFFFF) or ord(ch) < 32:
            flush()
            continue
        left, bottom, right, top = textpage.get_charbox(i, loose=True)
        c_top, c_bottom = height - top, height - bottom
        c_size = c_bottom - c_top
        if c_size <= 0:
            continue
        if chars:
            gap = left - box[2]
            if abs(c_top - box[1]) > 0.5 * c_size or gap > 0.25 * c_size or gap < -c_size:
                flush()
        weight = pdfium_c.FPDFText_GetFontWeight(textpage.raw, i)
        bold = font_cache.get(weight)
        if bold is None or weight <= 0:
            pdfium_c.FPDFText_GetFontInfo(textpage.raw, i, name_buf, len(name_buf), ctypes.byref(flags))
            name = name_buf.value.decode("latin-1", "replace")
            bold = weight >= 600 or bool(_BOLD_NAME.search(name))
            if weight > 0 and not _BOLD_NAME.search(name):
                font_cache[weight] = bold
        if chars:
            box[0], box[1] = min(box[0], left), min(box[1], c_top)
            box[2], box[3] = max(box[2], right), max(box[3], c_bottom)
        else:
            box.extend([left, c_top, right, c_bottom])
        chars.append(ch)
        sizes.append(c_size)
        bolds.append(bold)
    flush()
    textpage.close()
    return words


def _gutter(words: list[Word], width: float) -> float | None:
    """x of a vertical gutter splitting the page into two text columns, if there is one."""
    if len(words) < 40:
        return None
    lo, hi = 0.35 * width, 0.65 * width
    step = 2.0
    bins = int((hi - lo) / step)
    covered = [0] * bins
    for w in words:
        a = max(0, int((w.x0 - lo) / step))
        b = min(bins - 1, int((w.x1 - lo) / step))
        for k in range(a, b + 1):
            covered[k] += 1
    best, run, best_end = 0, 0, -1
    for k, c in enumerate(covered):
        run = run + 1 if c <= len(words) * 0.01 else 0
        if run > best:
            best, best_end = run, k
    if best * step < 12:
        return None
    x = lo + (best_end - best / 2 + 0.5) * step
    left = [w for w in words if w.x1 <= x]
    right = [w for w in words if w.x0 >= x]
    if min(len(left), len(right)) < 0.25 * len(words):
        return None
    # A table's label column and number columns also leave a gutter; real text columns are prose.
    for side in (left, right):
        numeric = sum(1 for w in side if _NUMERIC.match(w.text))
        if numeric > 0.3 * len(side):
            return None
    return x


def _group_lines(words: list[Word], page_no: int) -> list[Line]:
    lines: list[Line] = []
    for w in sorted(words, key=lambda w: ((w.top + w.bottom) / 2, w.x0)):
        mid = (w.top + w.bottom) / 2
        if lines:
            last = lines[-1]
            last_mid = (last.top + last.bottom) / 2
            if abs(mid - last_mid) <= 0.4 * min(w.size, last.size):
                last.words.append(w)
                continue
        lines.append(Line(page=page_no, words=[w]))
    for line in lines:
        line.words.sort(key=lambda w: w.x0)
    return lines


def page_lines(page: pdfium.PdfPage, page_no: int) -> list[Line]:
    """Lines in reading order; two-column pages are read left column first."""
    words = page_words(page)
    gutter = _gutter(words, page.get_width())
    if gutter is None:
        return _group_lines(words, page_no)
    left = [w for w in words if (w.x0 + w.x1) / 2 < gutter]
    right = [w for w in words if (w.x0 + w.x1) / 2 >= gutter]
    return _group_lines(left, page_no) + _group_lines(right, page_no)


_DIGITS = re.compile(r"\d+")
_PAGE_NO = re.compile(r"^\s*(page\s+)?(\d{1,4}|[ivxlc]{1,6})(\s+(of|/)\s+\d{1,4})?\s*$", re.I)


def drop_running_lines(by_page: dict[int, list[Line]], heights: dict[int, float]) -> dict[int, list[Line]]:
    """Remove headers/footers: lines in the top/bottom 8% repeating on ≥ 50% of pages (min 3)."""
    pages = len(by_page)
    threshold = max(3, pages * 0.5)

    def key(line: Line) -> str | None:
        h = heights[line.page]
        if line.top > 0.08 * h and line.bottom < 0.92 * h:
            return None
        return _DIGITS.sub("#", line.text.lower()).strip()

    seen: dict[str, set[int]] = defaultdict(set)
    for page, lines in by_page.items():
        for line in lines:
            k = key(line)
            if k:
                seen[k].add(page)
    running = {k for k, ps in seen.items() if len(ps) >= threshold}

    def keep(lines: list[Line], i: int) -> bool:
        line = lines[i]
        if key(line) in running:
            return False
        # A bare page number as the first or last line, wherever the converter placed it.
        return not ((i == 0 or i == len(lines) - 1) and _PAGE_NO.match(line.text))

    return {page: [ln for i, ln in enumerate(lines) if keep(lines, i)] for page, lines in by_page.items()}
