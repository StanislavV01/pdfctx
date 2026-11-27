from __future__ import annotations

from pdfctx.outline import build_outline
from pdfctx.parse import parse_pdf
from pdfctx.units import make_units
from tests import pdfgen


def _tree(sections):
    by_idx = {s.idx: s for s in sections}
    return [(s.title, by_idx[s.parent].title if s.parent is not None else None) for s in sections]


def _section_of(doc, sections, assign, needle):
    i = next(i for i, b in enumerate(doc.blocks) if needle in b.text)
    return sections[assign[i]].title if assign[i] is not None else None


def test_outline_from_bookmarks(report_pdf):
    doc = parse_pdf(report_pdf)
    sections, assign = build_outline(doc)
    assert _tree(sections) == [
        ("1 Introduction", None),
        ("1.1 Scope", "1 Introduction"),
        ("2 Results", None),
        ("2.1 Revenue", "2 Results"),
        ("3 Risks", None),
    ]
    assert len(assign) == len(doc.blocks)
    assert _section_of(doc, sections, assign, pdfgen.REVENUE_SENTENCE) == "2.1 Revenue"
    assert _section_of(doc, sections, assign, pdfgen.TERMINATION_SENTENCE) == "3 Risks"
    assert _section_of(doc, sections, assign, pdfgen.TABLE_LEAD_IN) == "2.1 Revenue"
    assert assign[0] is None  # the title comes before the first bookmark


def test_outline_from_headings(report_no_bookmarks_pdf):
    doc = parse_pdf(report_no_bookmarks_pdf)
    sections, assign = build_outline(doc)
    tree = _tree(sections)
    assert tree[0] == (pdfgen.REPORT_TITLE, None)
    assert ("1.1 Scope", "1 Introduction") in tree
    assert ("2.1 Revenue", "2 Results") in tree
    assert ("3 Risks", None) in tree
    assert _section_of(doc, sections, assign, pdfgen.TERMINATION_SENTENCE) == "3 Risks"


def test_row_units_carry_headers_and_caption(report_pdf):
    doc = parse_pdf(report_pdf)
    sections, assign = build_outline(doc)
    units = make_units(doc, sections, assign, contextual=True, table_rows=True)
    rows = [u for u in units if u.kind == "row"]
    assert [u.text for u in rows][:2] == [
        "North | 2025: 1,200 | 2024: 1,050",
        "South | 2025: 800 | 2024: 760",
    ]
    table = next(u for u in units if u.kind == "table")
    assert pdfgen.TABLE_LEAD_IN in table.text and "North" in table.text
    assert all(u.block_idx == table.block_idx for u in rows)
    assert "Revenue by region" in rows[0].context


def test_context_prefix_and_ablation_switches(report_pdf):
    doc = parse_pdf(report_pdf)
    sections, assign = build_outline(doc)
    with_ctx = make_units(doc, sections, assign, contextual=True, table_rows=False)
    para = next(u for u in with_ctx if pdfgen.REVENUE_SENTENCE in u.text)
    assert para.context == f"{doc.title} › 2 Results › 2.1 Revenue"
    assert pdfgen.REVENUE_SENTENCE in para.text and "›" not in para.text
    assert not any(u.kind == "row" for u in with_ctx)
    plain = make_units(doc, sections, assign, contextual=False, table_rows=False)
    assert all(u.context == "" for u in plain if u.kind != "table")
