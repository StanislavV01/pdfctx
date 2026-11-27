"""Retrieval units: what the index searches over.

A unit is a block (heading or paragraph), a whole table, or one table row rendered with its column
headers. Units can carry a context prefix (document title + section path) that helps retrieval but is
never shown to the agent as body text.
"""

from __future__ import annotations

from dataclasses import dataclass

from .outline import Section, section_path
from .parse.model import BBox, ParsedDoc


@dataclass
class Unit:
    kind: str  # "block" | "table" | "row"
    block_idx: int
    text: str
    context: str
    page: int
    bbox: BBox


def row_text(label: str, header: list[str], values: list[str], group: str = "") -> str:
    cells = [f"{h or f'col{n + 1}'}: {v}" for n, (h, v) in enumerate(zip(header, values, strict=False)) if v]
    head = f"{group} › {label}" if group and label else (label or group)
    return " | ".join([head, *cells]) if head else " | ".join(cells)


def make_units(
    doc: ParsedDoc,
    sections: list[Section],
    assign: list[int | None],
    *,
    contextual: bool,
    table_rows: bool,
) -> list[Unit]:
    units: list[Unit] = []
    for i, block in enumerate(doc.blocks):
        path = section_path(sections, assign[i])
        context = " › ".join([doc.title, *path]) if contextual else ""
        if block.kind != "table":
            units.append(Unit("block", i, block.text, context, block.page, block.bbox))
            continue
        lead = " ".join(x for x in (block.lead_in, block.caption) if x)
        units.append(Unit("table", i, f"{lead}\n{block.text}".strip(), context, block.page, block.bbox))
        if not table_rows:
            continue
        # Rows always know their table's lead-in and caption: a row without them is meaningless.
        row_ctx = " › ".join(x for x in (context, lead) if x)
        group = ""
        for row in block.rows or []:
            label, values = row[0], row[1:]
            if not any(values):
                group = label
                continue
            units.append(
                Unit(
                    "row",
                    i,
                    row_text(label, block.header or [], values, group),
                    row_ctx,
                    block.page,
                    block.bbox,
                )
            )
    return units
