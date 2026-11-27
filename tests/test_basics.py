from pypdf import PdfReader

from pdfctx import __version__
from pdfctx.cli import main
from tests import pdfgen


def test_version(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == __version__ == "0.1.0"


def test_generated_report_contains_sentence(report_pdf):
    reader = PdfReader(report_pdf)
    assert len(reader.pages) == 4
    assert pdfgen.TERMINATION_SENTENCE.split()[-1].rstrip(".") in reader.pages[3].extract_text()
    assert len(reader.outline) >= 3
