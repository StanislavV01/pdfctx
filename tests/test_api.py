from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from pdfctx.api import MAX_UPLOAD_BYTES, create_app
from pdfctx.library import Library
from tests import pdfgen


@pytest.fixture
def client(tmp_path, report_pdf):
    lib = Library(tmp_path / "i.db", roots=[report_pdf])
    with TestClient(create_app(lib, upload_dir=tmp_path / "uploads"), base_url="http://127.0.0.1:8000") as c:
        yield c
    lib.close()


def test_healthz(client):
    assert client.get("/healthz").json()["ok"] is True


def test_rest_mirrors_tools(client):
    (doc,) = client.get("/v1/documents").json()["documents"]
    outline = client.get(f"/v1/documents/{doc['id']}/outline").json()
    assert [s["title"] for s in outline["sections"]] == ["1 Introduction", "2 Results", "3 Risks"]
    hit = client.get("/v1/search", params={"q": "termination notice"}).json()["results"][0]
    assert pdfgen.TERMINATION_SENTENCE in hit["text"]
    cite = client.get(f"/v1/blocks/{hit['block_id']}/cite").json()
    assert cite["page"] == 4
    pack = client.post("/v1/context", json={"query": "South revenue 2024", "budget_tokens": 300}).json()
    assert pack["used_tokens"] <= 300


def test_errors_are_json(client):
    r = client.get("/v1/sections/nope:s1")
    assert r.status_code == 404 and r.json() == {"error": "unknown section 'nope:s1'"}
    r = client.get("/v1/search", params={"q": "x", "k": 0})
    assert r.status_code == 400 and "k must be" in r.json()["error"]


def test_upload_limits(client, report_pdf):
    assert client.post("/v1/documents", content=b"hello").status_code == 400
    big = b"%PDF-" + b"0" * (MAX_UPLOAD_BYTES + 1)
    assert client.post("/v1/documents", content=big).status_code == 413
    r = client.post(
        "/v1/documents", content=report_pdf.read_bytes(), headers={"x-filename": "../evil name.pdf"}
    )
    assert r.status_code == 201 and r.json()["pages"] == 4
    assert any(d["file"].endswith("_evil name.pdf") for d in client.get("/v1/documents").json()["documents"])


def test_page_png_route(client):
    (doc,) = client.get("/v1/documents").json()["documents"]
    small = client.get(f"/v1/documents/{doc['id']}/pages/1.png", params={"scale": 0.5})
    big = client.get(f"/v1/documents/{doc['id']}/pages/1.png", params={"scale": 1.0})
    assert small.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(big.content) > len(small.content)
    assert client.get(f"/v1/documents/{doc['id']}/pages/99.png").status_code == 400


def test_mcp_mounted(client):
    r = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        },
        headers={"accept": "application/json, text/event-stream"},
    )
    assert r.status_code == 200 and "pdfctx" in r.text


def test_mcp_rejects_foreign_host(client):
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"accept": "application/json, text/event-stream", "host": "evil.example"},
    )
    assert r.status_code == 421
