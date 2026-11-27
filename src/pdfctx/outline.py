"""Section tree from PDF bookmarks, or from detected headings when a PDF has none."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .parse.model import ParsedDoc

_NUMBERING = re.compile(r"^(\d{1,2}(?:\.\d{1,3})*)\.?\s")  # 1, 2.1, 10.3 — not years
_LABELED = re.compile(r"^(item|article|part|chapter|section)\s+[\w.]+", re.I)


@dataclass
class Section:
    idx: int
    parent: int | None
    level: int
    title: str
    page: int


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _with_parents(items: list[tuple[int, str, int]]) -> list[Section]:
    sections: list[Section] = []
    stack: list[Section] = []
    for level, title, page in items:
        while stack and stack[-1].level >= level:
            stack.pop()
        s = Section(len(sections), stack[-1].idx if stack else None, level, title, page)
        sections.append(s)
        stack.append(s)
    return sections


def _from_bookmarks(doc: ParsedDoc) -> tuple[list[Section], list[int | None]]:
    sections = _with_parents(doc.bookmarks)
    assign: list[int | None] = []
    current: int | None = None
    nxt = 0
    for block in doc.blocks:
        # Bookmarks whose page we have passed without seeing their heading still take effect.
        while nxt < len(sections) and sections[nxt].page < block.page:
            current, nxt = nxt, nxt + 1
        if (
            nxt < len(sections)
            and block.kind == "heading"
            and block.page == sections[nxt].page
            and _norm(block.text).startswith(_norm(sections[nxt].title)[:40])
        ):
            current, nxt = nxt, nxt + 1
        assign.append(current)
    return sections, assign


def _heading_level(text: str, size: float, size_rank: dict[float, int]) -> int:
    m = _NUMBERING.match(text)
    if m:
        return m.group(1).count(".") + 1
    if _LABELED.match(text):
        return 1
    if text.rstrip().endswith(":"):
        return len(size_rank) + 1  # run-in labels ("Cash Flow Hedges:") sit under the current section
    return size_rank[round(size * 2) / 2]


def _from_headings(doc: ParsedDoc) -> tuple[list[Section], list[int | None]]:
    heads = [b for b in doc.blocks if b.kind == "heading"]
    sizes = sorted({round(b.size * 2) / 2 for b in heads}, reverse=True)
    size_rank = {s: i + 1 for i, s in enumerate(sizes)}
    items = [(_heading_level(b.text, b.size, size_rank), b.text, b.page) for b in heads]
    sections = _with_parents(items)
    assign: list[int | None] = []
    current: int | None = None
    k = 0
    for block in doc.blocks:
        if block.kind == "heading":
            current = k
            k += 1
        assign.append(current)
    return sections, assign


def build_outline(doc: ParsedDoc) -> tuple[list[Section], list[int | None]]:
    """Sections plus, for each block in `doc.blocks`, the index of the section it belongs to."""
    if doc.bookmarks:
        return _from_bookmarks(doc)
    return _from_headings(doc)


def section_path(sections: list[Section], idx: int | None) -> list[str]:
    path: list[str] = []
    while idx is not None:
        path.append(sections[idx].title)
        idx = sections[idx].parent
    return path[::-1]
