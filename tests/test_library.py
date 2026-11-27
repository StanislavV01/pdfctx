from __future__ import annotations

import pytest

from pdfctx.errors import PdfctxError
from pdfctx.library import Library
from tests import pdfgen


@pytest.fixture
def lib(tmp_path, report_pdf):
    lib = Library(tmp_path / "index.db", roots=[report_pdf], client="test-agent")
    yield lib
    lib.close()


def test_tools_end_to_end(lib):
    (doc,) = lib.list_documents()["documents"]
    assert doc["title"] == pdfgen.REPORT_TITLE and doc["status"] == "ok"
    outline = lib.outline(doc["id"])
    titles = [s["title"] for s in outline["sections"]]
    assert titles == ["1 Introduction", "2 Results", "3 Risks"]
    results = next(s for s in outline["sections"] if s["title"] == "2 Results")
    assert [c["title"] for c in results["children"]] == ["2.1 Revenue"]
    assert lib.outline(doc["id"], max_depth=1)["sections"][0]["children"] == []

    section = lib.read_section(results["id"])
    texts = [b["text"] for b in section["blocks"]]
    assert any(pdfgen.REVENUE_SENTENCE in t for t in texts)  # child section included
    assert section["path"] == ["2 Results"]

    hit = lib.search("termination notice period")["results"][0]
    assert pdfgen.TERMINATION_SENTENCE in hit["text"] and hit["page"] == 4
    assert hit["section_path"] == ["3 Risks"]
    cite = lib.cite(hit["block_id"])
    assert cite["page"] == 4 and cite["file"].endswith("report.pdf")
    x0, top, x1, bottom = cite["bbox"]
    assert 0 <= x0 < x1 <= 612 and 0 <= top < bottom <= 792


def test_read_section_respects_budget(lib):
    (doc,) = lib.list_documents()["documents"]
    first = lib.outline(doc["id"])["sections"][0]
    small = lib.read_section(first["id"], max_tokens=100)
    assert small["truncated"] is True and small["next_block_id"]
    assert sum(b["tokens"] for b in small["blocks"]) <= 100


def test_context_pack_uses_row_not_whole_table(lib):
    pack = lib.context_pack("South region revenue 2024", budget_tokens=400)
    assert pack["used_tokens"] <= 400
    rows = [b for s in pack["sections"] for b in s["blocks"] if b["kind"] == "row"]
    assert rows and "South | 2025: 800 | 2024: 760" in rows[0]["text"]
    assert "North" not in rows[0]["text"]
    ids = [b["block_id"] + b.get("unit_id", "") for s in pack["sections"] for b in s["blocks"]]
    assert len(ids) == len(set(ids))


def test_context_pack_tiny_budget_returns_empty_not_error(lib):
    pack = lib.context_pack("termination", budget_tokens=200)
    assert pack["used_tokens"] <= 200


def test_every_tool_call_is_audited(lib):
    (doc,) = lib.list_documents()["documents"]
    sec = lib.outline(doc["id"])["sections"][0]
    lib.read_section(sec["id"])
    hit = lib.search("revenue")["results"][0]
    lib.cite(hit["block_id"])
    table = next(r for r in lib.search("region revenue")["results"] if r["kind"] == "table")
    lib.get_table(table["block_id"])
    pack = lib.context_pack("termination notice")
    rows = lib.audit(limit=20)
    assert [r["tool"] for r in rows][::-1] == [
        "list_documents",
        "outline",
        "read_section",
        "search",
        "cite",
        "search",
        "get_table",
        "context_pack",
    ]
    assert all(r["client"] == "test-agent" for r in rows)
    pack_ids = {b["block_id"] for s in pack["sections"] for b in s["blocks"]}
    assert set(rows[0]["block_ids"]) == pack_ids
    assert rows[0]["args"]["query"] == "termination notice"


def test_argument_validation(lib):
    for call in (
        lambda: lib.search("x", k=0),
        lambda: lib.search("x", k=51),
        lambda: lib.read_section("nope:s0", max_tokens=50),
        lambda: lib.context_pack("x", budget_tokens=10),
        lambda: lib.get_table("nope:b0", format="xml"),
        lambda: lib.cite("nope:b0"),
        lambda: lib.outline("nope"),
    ):
        with pytest.raises(PdfctxError):
            call()


def test_get_table_csv_and_markdown(lib):
    table = next(r for r in lib.search("region revenue")["results"] if r["kind"] == "table")
    csv_text = lib.get_table(table["block_id"], format="csv")["table"]
    assert csv_text.splitlines()[0] == ",2025,2024"
    assert csv_text.splitlines()[2] == "South,800,760"
    md = lib.get_table(table["block_id"])["table"]
    assert md.startswith("| ") and "| South | 800 | 760 |" in md
    with pytest.raises(PdfctxError, match="not a table"):
        lib.get_table(lib.search("termination")["results"][0]["block_id"])


def test_refresh_picks_up_new_files(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    lib = Library(tmp_path / "i.db", roots=[folder], refresh_interval=0)
    assert lib.list_documents()["documents"] == []
    pdfgen.make_text_report(folder / "new.pdf", "The deposit is refundable.")
    assert lib.search("deposit refundable")["results"]
    lib.close()


def test_context_pack_search_allows_several_blocks_per_page(lib):
    lib.refresh()
    one = lib._search("revenue region", None, k=20)
    many = lib._search("revenue region", None, k=20, per_page_cap=3)

    def most_per_page(hits):
        counts: dict = {}
        for h in hits:
            page = lib.store.get_block(h.block_id).page
            counts[page] = counts.get(page, 0) + 1
        return max(counts.values())

    assert most_per_page(one) == 1
    assert most_per_page(many) > 1
