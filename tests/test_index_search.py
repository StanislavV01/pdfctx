from __future__ import annotations

import shutil

import pytest

from pdfctx.embed import HashEmbedder
from pdfctx.errors import PdfctxError
from pdfctx.indexer import IndexOptions, index_paths
from pdfctx.search import SearchConfig, fts_query, search
from pdfctx.store import Store
from tests import pdfgen


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "index.db")
    yield s
    s.close()


def _top_text(store, hits):
    return store.get_block(hits[0].block_id).text


def test_index_and_read_back(store, report_pdf):
    report = index_paths(store, [report_pdf])
    assert len(report.added) == 1 and not report.problems
    (doc,) = store.list_documents()
    assert doc.status == "ok" and doc.pages == 4 and doc.title == pdfgen.REPORT_TITLE
    tables = [b for b in store.blocks_for(doc.id) if b.kind == "table"]
    assert tables[0].rows[0] == ["North", "1,200", "1,050"] and tables[0].header == ["2025", "2024"]
    assert len(store.sections_for(doc.id)) == 5


def test_index_folder_with_bad_files(store, pdf_dir):
    report = index_paths(store, [pdf_dir])
    statuses = {d.path.split("/")[-1]: d.status for d in store.list_documents()}
    assert statuses["encrypted.pdf"] == "encrypted"
    assert statuses["image_only.pdf"] == "no_text"
    assert statuses["not_a_pdf.pdf"] == "failed"
    assert statuses["report.pdf"] == "ok"
    assert {p for p, _ in report.problems} >= {
        str(pdf_dir / "encrypted.pdf"),
        str(pdf_dir / "image_only.pdf"),
        str(pdf_dir / "not_a_pdf.pdf"),
    }


def test_reindex_on_change_and_delete(store, tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    pdf = pdfgen.make_text_report(folder / "notes.pdf", "The warranty lasts two years.")
    index_paths(store, [folder])
    old = search(store, "warranty")[0].block_id

    pdfgen.make_text_report(pdf, "The warranty lasts five years.")
    report = index_paths(store, [folder])
    assert len(report.updated) == 1
    assert "five years" in _top_text(store, search(store, "warranty"))
    if old != search(store, "warranty")[0].block_id:
        with pytest.raises(PdfctxError, match="unknown block"):
            store.get_block(old)

    pdf.unlink()
    report = index_paths(store, [folder])
    assert len(report.removed) == 1 and store.list_documents() == []
    assert search(store, "warranty") == []


def test_unchanged_files_are_skipped(store, report_pdf, tmp_path):
    index_paths(store, [report_pdf])
    report = index_paths(store, [report_pdf])
    assert report.unchanged == [str(report_pdf)] and not report.added and not report.updated
    # changing options re-indexes even when the file is the same
    report = index_paths(store, [report_pdf], IndexOptions(contextual=False))
    assert len(report.updated) == 1


@pytest.mark.parametrize("q", ['"', "notice - period", "AND", "NEAR(", "a*", "x:y", "((", "", "!!!", "OR OR"])
def test_fts_query_is_injection_safe(store, report_pdf, q):
    index_paths(store, [report_pdf])
    assert isinstance(search(store, q), list)
    out = fts_query(q)
    assert out is None or all(part.startswith('"') and part.endswith('"') for part in out.split(" OR "))


def test_search_finds_known_sentence(store, report_pdf):
    index_paths(store, [report_pdf])
    assert pdfgen.TERMINATION_SENTENCE in _top_text(store, search(store, "termination notice period"))


def test_search_diacritics_and_cyrillic(store, polish_pdf):
    index_paths(store, [polish_pdf])
    assert search(store, "zazolc gesla")
    assert search(store, "оренди")


def test_row_unit_wins_for_line_item_query(store, report_pdf):
    index_paths(store, [report_pdf], IndexOptions(table_rows=True))
    hits = search(store, "South region revenue 2024")
    top = store.get_block(hits[0].block_id)
    assert top.kind == "table"
    assert hits[0].unit_kind == "row" and "South" in store.get_unit(hits[0].unit_id).text


def test_doc_scope(store, report_pdf, polish_pdf):
    index_paths(store, [report_pdf, polish_pdf])
    polish_id = next(d.id for d in store.list_documents() if d.path.endswith("polish.pdf"))
    assert search(store, "termination", doc_ids=[polish_id]) == []


def test_hybrid_with_hash_embedder(store, report_pdf):
    emb = HashEmbedder(dim=128)
    index_paths(store, [report_pdf], IndexOptions(embedder=emb))
    cfg = SearchConfig(vectors=True)
    hits = search(store, "termination notice period", config=cfg, embedder=emb)
    assert pdfgen.TERMINATION_SENTENCE in _top_text(store, hits)
    with pytest.raises(PdfctxError, match="embedder"):
        search(store, "x", config=cfg, embedder=None)


def test_store_unknown_ids(store):
    for fn in (store.get_block, store.get_section, store.get_unit, store.get_document):
        with pytest.raises(PdfctxError, match="unknown"):
            fn("nope:b1")


def test_folder_walk_skips_hidden_and_index_dirs(store, tmp_path, report_pdf):
    (tmp_path / "a").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".pdfctx").mkdir()
    shutil.copy(report_pdf, tmp_path / "a" / "Report.PDF")
    shutil.copy(report_pdf, tmp_path / ".hidden" / "x.pdf")
    shutil.copy(report_pdf, tmp_path / ".pdfctx" / "y.pdf")
    index_paths(store, [tmp_path])
    assert [d.path.split("/")[-1] for d in store.list_documents()] == ["Report.PDF"]


def test_per_page_cap_spreads_results_across_pages(store, report_pdf):
    index_paths(store, [report_pdf])
    capped = search(store, "revenue region company year", k=6, config=SearchConfig(per_page_cap=1))
    pages = [store.get_block(h.block_id).page for h in capped]
    assert len(pages) == len(set(pages))


def test_page_boost_prefers_pages_with_more_evidence(store, report_pdf):
    index_paths(store, [report_pdf])
    plain = search(store, "revenue", k=10, config=SearchConfig(page_boost=0.0, per_page_cap=None))
    boosted = search(store, "revenue", k=10, config=SearchConfig(page_boost=1.0, per_page_cap=None))
    assert {h.block_id for h in plain} == {h.block_id for h in boosted}
    assert all(h.score > 0 for h in boosted)


def test_boilerplate_page_does_not_beat_a_strong_match(store, report_pdf):
    # page 1 has several weak "period" matches; the real answer is one strong match on page 4
    index_paths(store, [report_pdf])
    assert pdfgen.TERMINATION_SENTENCE in _top_text(store, search(store, "termination notice period"))


def test_parser_upgrade_reindexes(store, report_pdf, monkeypatch):
    import pdfctx.indexer as indexer

    index_paths(store, [report_pdf])
    monkeypatch.setattr(indexer, "INDEX_VERSION", indexer.INDEX_VERSION + 1)
    assert len(index_paths(store, [report_pdf]).updated) == 1
