from __future__ import annotations

from pathlib import Path

import pytest

from pdfctx.errors import NotFound, PdfctxError
from pdfctx.library import Library
from pdfctx.metrics import _match, norm, parse_number, to_csv

FILING_3M = Path.home() / ".cache" / "pdfctx-bench" / "pdfs" / "3M_2018_10K.pdf"


@pytest.mark.parametrize(
    ("cell", "value"),
    [
        ("$(1,577)", -1577.0),
        ("(1,577)", -1577.0),
        ("1,577", 1577.0),
        ("$ 6,439", 6439.0),
        ("8.89", 8.89),
        ("22.2 %", 22.2),
        ("—", None),
        ("$—", None),
        ("", None),
        ("n/a", None),
        ("see note", None),
    ],
)
def test_parse_number(cell, value):
    assert parse_number(cell) == value


def test_label_matching():
    names = ["net income attributable to", "net income"]
    assert _match("Net income attributable to 3M", names)[0] == 2.0
    assert _match("Net income attributable to 3M", names) > _match("Net income including NCI", names)
    assert _match("Net income per share", names)[0] == 0.0  # per-share rows are not totals
    assert _match("Cost of sales", ["sales"])[0] == 0.0
    assert (
        _match(
            "Purchases of property, plant and equipment (PP&E)",
            ["purchases of property, plant and equipment"],
        )[0]
        == 3.0
    )
    eps = ["earnings per share*diluted"]
    assert _match("Earnings per share attributable to 3M common shareholders — diluted", eps)[0] == 2.0
    assert _match("Diluted", eps, group="Earnings per share:")[0] == 2.0
    assert _match("Diluted", eps, group="Weighted average shares:")[0] == 0.0
    assert norm("Total revenues (1)") == "total revenues"


def test_extracts_a_value_with_its_source(tmp_path, report_pdf):
    lib = Library(tmp_path / "i.db", roots=[report_pdf])
    out = lib.extract_metrics(["Total", "revenue"], [2025, 2024])
    by = {(v["metric"], v["year"]): v for v in out["values"]}
    total = by[("Total", 2025)]
    assert total["value"] == 2000.0 and total["raw"] == "2,000" and total["unit"] == "thousands"
    assert total["page"] >= 1 and len(total["bbox"]) == 4 and total["label"] == "Total"
    assert by[("Total", 2024)]["value"] == 1810.0
    # Nothing is invented: the report has no row called revenue.
    assert {(m["metric"], m["year"]) for m in out["missing"]} == {("revenue", 2025), ("revenue", 2024)}
    assert lib.audit(1)[0]["tool"] == "extract_metrics"
    csv_text = to_csv(out)
    assert csv_text.splitlines()[0].startswith("document,metric,year,value,unit")
    assert "not found" in csv_text
    lib.close()


def test_argument_errors(tmp_path, report_pdf):
    lib = Library(tmp_path / "i.db", roots=[report_pdf])
    with pytest.raises(PdfctxError):
        lib.extract_metrics([])
    with pytest.raises(NotFound):
        lib.extract_metrics(["revenue"], doc_ids=["nope"])
    lib.close()


@pytest.mark.skipif(not FILING_3M.exists(), reason="3M 2018 10-K not downloaded (bench cache)")
def test_golden_3m_2018(tmp_path):
    lib = Library(tmp_path / "i.db", roots=[FILING_3M])
    out = lib.extract_metrics(["revenue", "net_income", "capex", "eps_diluted", "total_assets"], [2018])
    got = {v["metric"]: (v["value"], v["unit"]) for v in out["values"]}
    assert got == {
        "revenue": (32765.0, "millions"),
        "net_income": (5349.0, "millions"),
        "capex": (-1577.0, "millions"),  # the FinanceBench answer: $1,577M of PP&E purchases
        "eps_diluted": (8.89, "per share"),
        "total_assets": (36500.0, "millions"),
    }
    lib.close()
