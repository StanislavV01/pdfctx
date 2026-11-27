import pypdfium2 as pdfium

from pdfctx import __version__


def test_version_constant():
    assert __version__ == "0.1.0"


def test_generated_report_contains_sentence(report_pdf):
    pdf = pdfium.PdfDocument(report_pdf)
    assert len(pdf) == 4
    assert "ninety days" in pdf[3].get_textpage().get_text_range()
    assert len(list(pdf.get_toc())) == 5
