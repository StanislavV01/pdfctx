from __future__ import annotations

import pytest

from bench.financebench import BENCH_DIR, Passage, Question, load, score
from bench.systems import BaselinePage, PdfctxSystem
from pdfctx.indexer import IndexOptions
from tests import pdfgen


def _q(qid, doc, pages):
    return Question(qid, doc, "q?", "a", {(doc, p) for p in pages}, [])


def test_score_math():
    qs = [_q("1", "A", [3]), _q("2", "A", [5]), _q("3", "B", [1])]
    results = {
        "1": [Passage("A", 3, "x" * 40)],  # hit at rank 1
        "2": [Passage("A", 1, "y" * 8), Passage("A", 2, "y"), Passage("A", 5, "z" * 4)],  # rank 3
        "3": [Passage("A", 1, "w")],  # wrong document → miss
    }
    m = score(qs, results, latencies_ms=[10, 20, 30])
    assert m["page_recall@1"] == pytest.approx(1 / 3)
    assert m["page_recall@3"] == pytest.approx(2 / 3)
    assert m["page_recall@10"] == pytest.approx(2 / 3)
    assert m["mrr@10"] == pytest.approx((1 + 1 / 3) / 3)
    assert m["tokens@5"] == pytest.approx((10 + (2 + 1 + 1) + 1) / 3)
    assert m["latency_p50_ms"] == 20


@pytest.mark.skipif(
    not (BENCH_DIR / "data" / "financebench_open_source.jsonl").exists(), reason="no FinanceBench data"
)
def test_evidence_page_conversion():
    """FinanceBench pages are 0-based; ours are 1-based. A wrong shift would silently zero every metric."""
    import re

    import pypdfium2 as pdfium

    def words(s):
        return set(re.findall(r"[a-z]{4,}", s.lower()))

    qs = load()
    assert len(qs) == 150
    for q in qs[:8]:
        doc, page = sorted(q.evidence)[0]
        pdf = pdfium.PdfDocument(str(BENCH_DIR / "pdfs" / f"{doc}.pdf"))
        page_words = words(pdf[page - 1].get_textpage().get_text_range())
        ev = words(q.evidence_texts[0])
        assert len(ev & page_words) >= 0.5 * len(ev), q.id


def test_baseline_and_pdfctx_on_generated_pdf(report_pdf, tmp_path):
    for system in (BaselinePage(), PdfctxSystem("pdfctx-tables", IndexOptions(), index_dir=tmp_path)):
        system.prepare([report_pdf])
        (top, *_) = system.retrieve("termination notice period", report_pdf.stem, k=3)
        assert (top.doc_name, top.page) == ("report", 4), system.name
        assert pdfgen.TERMINATION_SENTENCE in top.text
