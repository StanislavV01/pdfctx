from __future__ import annotations

import anyio
import pytest
from mcp import Client

from pdfctx.library import Library
from pdfctx.mcp_server import TOOLS, build_server
from tests import pdfgen


@pytest.fixture
def server(tmp_path, report_pdf):
    lib = Library(tmp_path / "i.db", roots=[report_pdf], client="mcp-test")
    yield build_server(lib)
    lib.close()


def run(coro_fn):
    return anyio.run(coro_fn)


def test_mcp_lists_seven_read_only_tools(server):
    async def go():
        async with Client(server) as c:
            return (await c.list_tools()).tools

    tools = run(go)
    assert sorted(t.name for t in tools) == sorted(TOOLS)
    assert all(t.annotations and t.annotations.read_only_hint for t in tools)
    assert all(len(t.description or "") > 40 for t in tools)


def test_mcp_outline_then_read(server):
    async def go():
        async with Client(server) as c:
            docs = (await c.call_tool("list_documents", {})).structured_content
            doc_id = docs["documents"][0]["id"]
            outline = (await c.call_tool("outline", {"doc_id": doc_id})).structured_content
            risks = next(s for s in outline["sections"] if s["title"] == "3 Risks")
            return (await c.call_tool("read_section", {"section_id": risks["id"]})).structured_content

    section = run(go)
    assert any(pdfgen.TERMINATION_SENTENCE in b["text"] for b in section["blocks"])


def test_mcp_error_is_tool_error(server):
    async def go():
        async with Client(server) as c:
            return await c.call_tool("read_section", {"section_id": "nope:s9"})

    res = run(go)
    assert res.is_error
    assert "unknown section 'nope:s9'" in res.content[0].text
