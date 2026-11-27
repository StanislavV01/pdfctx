"""Reading tools: sections, citations and budgeted context packs."""

from __future__ import annotations

import math

from .errors import PdfctxError
from .search import Hit
from .store import BlockRow, SectionRow, Store


def tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def block_dict(b: BlockRow) -> dict:
    d = {
        "block_id": b.id,
        "kind": b.kind,
        "page": b.page,
        "bbox": list(b.bbox),
        "text": b.text,
        "tokens": b.tokens,
    }
    if b.kind == "table":
        d.update(header=b.header, rows=b.rows, caption=b.caption, lead_in=b.lead_in)
    return d


def section_path(store: Store, section_id: str | None) -> list[str]:
    path: list[str] = []
    while section_id:
        s = store.get_section(section_id)
        path.append(s.title)
        section_id = s.parent_id
    return path[::-1]


def _descendants(sections: list[SectionRow], root: str) -> list[str]:
    children: dict[str | None, list[str]] = {}
    for s in sections:
        children.setdefault(s.parent_id, []).append(s.id)
    out, stack = [], [root]
    while stack:
        sid = stack.pop()
        out.append(sid)
        stack.extend(reversed(children.get(sid, [])))
    return out


def render_section(store: Store, section_id: str, max_tokens: int) -> dict:
    section = store.get_section(section_id)
    ids = _descendants(store.sections_for(section.doc_id), section_id)
    blocks = store.blocks_in_sections(ids)
    out, used, next_id = [], 0, None
    for b in blocks:
        if used + b.tokens > max_tokens:
            next_id = b.id
            break
        out.append(block_dict(b))
        used += b.tokens
    return {
        "section": {
            "id": section.id,
            "doc_id": section.doc_id,
            "title": section.title,
            "level": section.level,
        },
        "path": section_path(store, section_id),
        "blocks": out,
        "used_tokens": used,
        "truncated": next_id is not None,
        "next_block_id": next_id,
    }


def cite(store: Store, block_id: str) -> dict:
    b = store.get_block(block_id)
    doc = store.get_document(b.doc_id)
    return {
        "block_id": b.id,
        "document": doc.title,
        "doc_id": doc.id,
        "file": doc.path,
        "page": b.page,
        "bbox": list(b.bbox),
        "bbox_units": "PDF points, origin top-left",
        "section_path": section_path(store, b.section_id),
        "text": b.text,
    }


def hit_text(store: Store, hit: Hit, block: BlockRow) -> str:
    """What an agent should read for a hit: the row with its headers for row hits, else the block."""
    if hit.unit_kind == "row":
        unit = store.get_unit(hit.unit_id)
        return "\n".join(x for x in (block.caption, unit.text) if x)
    return block.text


def context_pack(store: Store, hits: list[Hit], budget_tokens: int) -> dict:
    """The best evidence for a query that fits the budget, in document order, grouped by section."""
    blocks = store.blocks_by_ids({h.block_id for h in hits})
    chosen: list[tuple[BlockRow, dict]] = []
    seen: set[str] = set()
    used, dropped = 0, 0

    def add(b: BlockRow, item: dict) -> bool:
        nonlocal used
        key = item["block_id"] + item.get("unit_id", "")
        if key in seen:
            return True
        cost = tokens(item["text"])
        if used + cost > budget_tokens:
            return False
        seen.add(key)
        chosen.append((b, item))
        used += cost
        return True

    for h in hits:
        b = blocks.get(h.block_id)
        if b is None:
            continue
        if h.unit_kind == "row":
            item = {
                "block_id": b.id,
                "unit_id": h.unit_id,
                "kind": "row",
                "page": b.page,
                "text": hit_text(store, h, b),
            }
        else:
            item = {"block_id": b.id, "kind": b.kind, "page": b.page, "text": b.text}
            # A short hit (a heading or one-line paragraph) is easier to use with the paragraph before it.
            if b.kind == "paragraph" and b.tokens < 40 and b.idx > 0:
                try:
                    prev = store.get_block(f"{b.doc_id}:b{b.idx - 1}")
                except PdfctxError:
                    prev = None
                if prev and prev.section_id == b.section_id and prev.kind == "paragraph":
                    add(prev, {"block_id": prev.id, "kind": prev.kind, "page": prev.page, "text": prev.text})
        if not add(b, item):
            dropped += 1

    chosen.sort(key=lambda x: (x[0].doc_id, x[0].idx))
    sections: list[dict] = []
    for b, item in chosen:
        path = section_path(store, b.section_id)
        if not sections or sections[-1]["path"] != path or sections[-1]["doc_id"] != b.doc_id:
            sections.append({"doc_id": b.doc_id, "path": path, "blocks": []})
        sections[-1]["blocks"].append(item)
    return {"sections": sections, "used_tokens": used, "budget_tokens": budget_tokens, "dropped": dropped}
