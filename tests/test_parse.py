from __future__ import annotations

import os
from pathlib import Path

import pytest

from pdfctx.parse import parse_pdf
from tests import pdfgen

BENCH = Path(os.environ.get("PDFCTX_BENCH_DIR", Path.home() / ".cache" / "pdfctx-bench"))


def _blocks(doc, kind):
    return [b for b in doc.blocks if b.kind == kind]


def test_report_blocks(report_pdf):
    doc = parse_pdf(report_pdf)
    assert doc.status == "ok"
    assert doc.pages == 4
    headings = [b.text for b in _blocks(doc, "heading")]
    assert headings == [pdfgen.REPORT_TITLE, *pdfgen.HEADINGS]

    (table,) = _blocks(doc, "table")
    assert table.page == 3
    assert table.header == ["2025", "2024"]
    assert table.rows == [row for row in pdfgen.TABLE[1:]]
    assert table.lead_in == pdfgen.TABLE_LEAD_IN

    texts = [b.text for b in doc.blocks]
    assert not any(t == "ACME Annual Report" or t.startswith("Page ") for t in texts)
    hits = [b for b in _blocks(doc, "paragraph") if pdfgen.TERMINATION_SENTENCE in b.text]
    assert len(hits) == 1 and hits[0].page == 4


def test_title_and_bookmarks(report_pdf, report_no_bookmarks_pdf):
    doc = parse_pdf(report_pdf)
    assert doc.title == pdfgen.REPORT_TITLE
    assert [(lvl, title) for lvl, title, _ in doc.bookmarks] == [
        (1, "1 Introduction"),
        (2, "1.1 Scope"),
        (1, "2 Results"),
        (2, "2.1 Revenue"),
        (1, "3 Risks"),
    ]
    assert dict((t, p) for _, t, p in doc.bookmarks)["3 Risks"] == 4
    assert parse_pdf(report_no_bookmarks_pdf).bookmarks == []


def test_bbox_is_top_left_and_on_page(report_pdf):
    doc = parse_pdf(report_pdf)
    title = doc.blocks[0]
    x0, top, x1, bottom = title.bbox
    assert 0 <= x0 < x1 <= 612 and 0 <= top < bottom <= 792
    assert top < 150  # the title sits near the top of the page


def test_two_column_reading_order(two_column_pdf):
    doc = parse_pdf(two_column_pdf)
    paras = [b.text for b in _blocks(doc, "paragraph")]
    order = [next(i for i, t in enumerate(paras) if t.startswith(p)) for p in pdfgen.LEFT + pdfgen.RIGHT]
    assert order == sorted(order), paras
    assert all("Right column" not in t for t in paras if t.startswith("Left column"))


def test_bad_files_status(pdf_dir):
    assert parse_pdf(pdf_dir / "encrypted.pdf").status == "encrypted"
    assert parse_pdf(pdf_dir / "image_only.pdf").status == "no_text"
    failed = parse_pdf(pdf_dir / "not_a_pdf.pdf")
    assert failed.status == "failed" and failed.error and "\n" not in failed.error


def test_polish_and_cyrillic_text(polish_pdf):
    doc = parse_pdf(polish_pdf)
    text = " ".join(b.text for b in doc.blocks)
    assert "Zażółć gęślą jaźń." in text and "Договір оренди" in text


def test_real_pdfs_parse(federal_register_pdf, nics_pdf):
    fr = parse_pdf(federal_register_pdf)
    assert fr.status == "ok" and len(_blocks(fr, "heading")) >= 5
    nics = parse_pdf(nics_pdf)
    assert any(len(t.rows) >= 10 for t in _blocks(nics, "table"))


@pytest.mark.skipif(
    not (BENCH / "pdfs" / "3M_2018_10K.pdf").exists(), reason="FinanceBench data not downloaded"
)
def test_borderless_sec_table():
    doc = parse_pdf(BENCH / "pdfs" / "3M_2018_10K.pdf")
    cash_flow = [t for t in _blocks(doc, "table") if t.page == 60]
    rows = {r[0]: r[1:] for t in cash_flow for r in t.rows}
    capex = next(v for k, v in rows.items() if k.startswith("Purchases of property, plant and equipment"))
    header = next(t.header for t in cash_flow if any(r[0] in rows for r in t.rows))
    assert header[:3] == ["2018", "2017", "2016"]
    assert capex[0] == "(1,577)"


def test_inline_page_numbers_dropped(tmp_path):
    doc = parse_pdf(pdfgen.make_inline_page_numbers(tmp_path / "numbers.pdf"))
    assert [b.text for b in doc.blocks if b.text.strip().isdigit()] == []
    assert not any(b.text.rstrip()[-2:] in {" 1", " 2", " 3"} for b in doc.blocks)
    assert sum("Body text of page" in b.text for b in doc.blocks) == 3


def test_numeric_header_rows_are_not_headings():
    from pdfctx.parse.blocks import is_heading
    from pdfctx.parse.model import Line, Word

    line = Line(
        1,
        [
            Word(t, i * 40, 0, i * 40 + 30, 10, 8.6, True)
            for i, t in enumerate(["2018", "2017", "%", "change"])
        ],
    )
    assert not is_heading(line, 8.6, standalone=True)
