"""Lines → headings, paragraphs and table blocks in reading order."""

from __future__ import annotations

import re
from collections import Counter
from itertools import pairwise

from .model import Line, RawBlock, union
from .tables import TableRegion, to_markdown

_NUMBERED = re.compile(r"^(\d+(\.\d+)*\.?\s+\S|(item|article|part|section|chapter)\s+[\w.]+|§\s*\d)", re.I)


def body_size(lines: list[Line]) -> float:
    """The most common font size, weighted by text length."""
    weights: Counter[float] = Counter()
    for ln in lines:
        weights[round(ln.size * 2) / 2] += len(ln.text)
    return weights.most_common(1)[0][0] if weights else 10.0


def is_heading(line: Line, body: float, standalone: bool) -> bool:
    text = line.text.strip()
    words = text.split()
    if not words or len(words) > 14 or (text.endswith((".", ",", ";")) and not _NUMBERED.match(text)):
        return False
    if not any(c.isalpha() for c in text):
        return False
    if line.size >= 1.15 * body:
        return True
    if not standalone:
        return False
    if line.bold and len(words) <= 12:
        return True
    return bool(_NUMBERED.match(text)) and len(words) <= 12 and line.bold


def _join(lines: list[Line]) -> str:
    out = ""
    for ln in lines:
        t = ln.text.strip()
        out = out[:-1] + t if out.endswith("-") and t[:1].islower() else f"{out} {t}".strip()
    return out


def group_blocks(lines: list[Line], body: float, tables: list[TableRegion]) -> list[RawBlock]:
    """Blocks for one page. `lines` are in reading order; table lines are replaced by table blocks."""
    owner: dict[int, TableRegion] = {}
    for t in tables:
        for k in t.line_idx:
            owner[k] = t
    gaps = [b.top - a.bottom for a, b in pairwise(lines) if 0 <= b.top - a.bottom < 3 * body]
    gaps.sort()
    usual_gap = gaps[len(gaps) // 2] if gaps else body * 0.35

    blocks: list[RawBlock] = []
    para: list[Line] = []
    emitted: set[int] = set()

    def flush() -> None:
        if para:
            blocks.append(
                RawBlock(
                    "paragraph",
                    para[0].page,
                    union([ln.bbox for ln in para]),
                    _join(para),
                    size=para[0].size,
                    bold=all(ln.bold for ln in para),
                )
            )
            para.clear()

    for k, ln in enumerate(lines):
        table = owner.get(k)
        if table is not None:
            flush()
            if id(table) not in emitted:
                emitted.add(id(table))
                blocks.append(
                    RawBlock(
                        "table",
                        table.page,
                        union([x.bbox for x in table.lines]),
                        to_markdown(table.header, table.rows),
                        size=body,
                        header=table.header,
                        rows=table.rows,
                        caption=table.caption,
                        lead_in=table.lead_in,
                    )
                )
            continue
        prev = lines[k - 1] if k else None
        nxt = lines[k + 1] if k + 1 < len(lines) else None
        gap_before = ln.top - prev.bottom if prev else 99.0
        gap_after = nxt.top - ln.bottom if nxt else 99.0
        new_column = prev is not None and (
            ln.top < prev.top - body or abs(ln.words[0].x0 - prev.words[0].x0) > 150
        )
        standalone = (gap_before > usual_gap * 1.3 or new_column) and (
            gap_after > usual_gap * 1.3 or nxt is None or (nxt.size < ln.size * 0.9) or (nxt.bold != ln.bold)
        )
        if is_heading(ln, body, standalone):
            flush()
            blocks.append(RawBlock("heading", ln.page, ln.bbox, ln.text.strip(), size=ln.size, bold=ln.bold))
            continue
        if para:
            last = para[-1]
            if (
                ln.top - last.bottom > max(usual_gap * 1.5, 2.0)
                or new_column
                or abs(ln.size - last.size) > 1.5
            ):
                flush()
        para.append(ln)
    flush()
    return blocks
