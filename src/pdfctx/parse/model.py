from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

BBox = tuple[float, float, float, float]  # x0, top, x1, bottom — points, top-left origin


def union(boxes: list[BBox]) -> BBox:
    return (
        round(min(b[0] for b in boxes), 1),
        round(min(b[1] for b in boxes), 1),
        round(max(b[2] for b in boxes), 1),
        round(max(b[3] for b in boxes), 1),
    )


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    size: float
    bold: bool


@dataclass
class Line:
    page: int
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def bbox(self) -> BBox:
        return union([(w.x0, w.top, w.x1, w.bottom) for w in self.words])

    @property
    def top(self) -> float:
        return min(w.top for w in self.words)

    @property
    def bottom(self) -> float:
        return max(w.bottom for w in self.words)

    @property
    def size(self) -> float:
        sizes = sorted(w.size for w in self.words)
        return sizes[len(sizes) // 2]

    @property
    def bold(self) -> bool:
        chars = sum(len(w.text) for w in self.words)
        return sum(len(w.text) for w in self.words if w.bold) * 2 > chars


@dataclass
class RawBlock:
    kind: str  # "heading" | "paragraph" | "table"
    page: int
    bbox: BBox
    text: str
    size: float = 0.0
    bold: bool = False
    header: list[str] | None = None  # table column labels (excluding the row-label column)
    rows: list[list[str]] | None = None  # table data rows: [label, v1, v2, ...]
    caption: str = ""  # table title/units lines above the header
    lead_in: str = ""  # sentence right above the table


@dataclass
class ParsedDoc:
    path: Path
    title: str
    pages: int
    blocks: list[RawBlock] = field(default_factory=list)
    bookmarks: list[tuple[int, str, int]] = field(default_factory=list)  # (level 1-based, title, page)
    status: str = "ok"  # ok | no_text | encrypted | failed
    error: str | None = None
    ocr_pages: list[int] = field(default_factory=list)  # pages whose text came from OCR
