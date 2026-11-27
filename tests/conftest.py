from __future__ import annotations

from pathlib import Path

import pytest

from tests import pdfgen

DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="session")
def pdf_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("pdfs")
    pdfgen.make_report(d / "report.pdf")
    pdfgen.make_report(d / "report_no_bookmarks.pdf", bookmarks=False)
    pdfgen.make_two_column(d / "two_column.pdf")
    pdfgen.make_polish(d / "polish.pdf")
    pdfgen.make_image_only(d / "image_only.pdf")
    pdfgen.make_encrypted(d / "encrypted.pdf")
    (d / "not_a_pdf.pdf").write_text("this is plain text pretending to be a PDF")
    return d


@pytest.fixture(scope="session")
def report_pdf(pdf_dir) -> Path:
    return pdf_dir / "report.pdf"


@pytest.fixture(scope="session")
def report_no_bookmarks_pdf(pdf_dir) -> Path:
    return pdf_dir / "report_no_bookmarks.pdf"


@pytest.fixture(scope="session")
def two_column_pdf(pdf_dir) -> Path:
    return pdf_dir / "two_column.pdf"


@pytest.fixture(scope="session")
def polish_pdf(pdf_dir) -> Path:
    return pdf_dir / "polish.pdf"


@pytest.fixture(scope="session")
def federal_register_pdf() -> Path:
    return DATA / "federal-register-2020-17221.pdf"


@pytest.fixture(scope="session")
def nics_pdf() -> Path:
    return DATA / "nics-background-checks-2015-11.pdf"
