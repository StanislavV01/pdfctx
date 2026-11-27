from __future__ import annotations

import shutil

import pytest

from pdfctx.library import Library
from pdfctx.parse import parse_pdf
from pdfctx.parse.ocr import parse_tsv
from tests import pdfgen

needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")

TSV = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    "5\t1\t1\t1\t1\t1\t300\t600\t200\t50\t96.1\tRevenue\n"
    "5\t1\t1\t1\t1\t2\t520\t605\t120\t40\t91.0\t2018\n"
    "5\t1\t1\t1\t1\t3\t660\t605\t40\t40\t12.0\t~\n"
    "4\t1\t1\t1\t1\t0\t300\t600\t400\t50\t-1\t\n"
)


def test_parse_tsv_converts_pixels_to_points_and_drops_low_confidence():
    words = parse_tsv(TSV, scale=300 / 72)
    assert [w.text for w in words] == ["Revenue", "2018"]
    r = words[0]
    assert (r.x0, r.top) == (72.0, 144.0)  # 300 px at 300 dpi = 1 inch = 72 pt
    assert r.size == words[1].size  # one size per line


@needs_tesseract
def test_scanned_page_becomes_searchable_with_a_box(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFCTX_OCR", "1")
    pdf = pdfgen.make_scanned(tmp_path / "scan.pdf")
    doc = parse_pdf(pdf)
    assert doc.status == "ok" and doc.ocr_pages == [1]
    lib = Library(tmp_path / "i.db", roots=[pdf])
    hit = lib.search("capital expenditures 2018")["results"][0]
    assert "1,577" in hit["text"]
    x0, top, _x1, _bottom = hit["bbox"]
    assert 60 < x0 < 90 and 100 < top < 200  # one inch in, under the title
    lib.close()


@needs_tesseract
def test_ocr_can_be_turned_off(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFCTX_OCR", "0")
    assert parse_pdf(pdfgen.make_scanned(tmp_path / "scan.pdf")).status == "no_text"


def test_image_without_text_stays_no_text(pdf_dir):
    assert parse_pdf(pdf_dir / "image_only.pdf").status == "no_text"


@needs_tesseract
def test_ocr_page_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFCTX_OCR", "1")
    monkeypatch.setenv("PDFCTX_OCR_MAX_PAGES", "0")
    assert parse_pdf(pdfgen.make_scanned(tmp_path / "scan.pdf")).status == "no_text"


@needs_tesseract
def test_huge_page_is_rendered_within_the_pixel_cap(tmp_path, monkeypatch):
    from reportlab.pdfgen import canvas

    from pdfctx.parse import ocr
    from pdfctx.parse.pdf import _render_for_ocr

    big = tmp_path / "big.pdf"
    c = canvas.Canvas(str(big), pagesize=(3000, 3000))  # 41.7 inches square
    c.rect(10, 10, 100, 100)
    c.save()
    image, scale = _render_for_ocr(big, 1)
    assert image.width * image.height <= ocr.MAX_PIXELS * 1.01 and scale < 300 / 72
