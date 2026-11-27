from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from pdfctx.api import MAX_UPLOAD_BYTES, create_app
from pdfctx.errors import PdfctxError
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


def test_audit_route(client):
    client.get("/v1/search", params={"q": "revenue"})
    entries = client.get("/v1/audit", params={"limit": 5}).json()["entries"]
    assert entries[0]["tool"] == "search" and entries[0]["args"]["query"] == "revenue"


def test_errors_are_json(client):
    r = client.get("/v1/sections/nope:s1")
    assert r.status_code == 404 and r.json() == {"error": "unknown section 'nope:s1'"}
    r = client.get("/v1/search", params={"q": "x", "k": 0})
    assert r.status_code == 400 and "k must be" in r.json()["error"]


PDF = {"content-type": "application/pdf"}


def test_upload_limits(client, report_pdf):
    assert client.post("/v1/documents", content=b"hello", headers=PDF).status_code == 400
    big = b"%PDF-" + b"0" * (MAX_UPLOAD_BYTES + 1)
    assert client.post("/v1/documents", content=big, headers=PDF).status_code == 413
    r = client.post(
        "/v1/documents", content=report_pdf.read_bytes(), headers={**PDF, "x-filename": "../evil name.pdf"}
    )
    assert r.status_code == 201 and r.json()["pages"] == 4
    files = [d["file"] for d in client.get("/v1/documents").json()["documents"]]
    (up,) = [Path(f) for f in files if f.endswith("_evil name.pdf")]
    assert up.parent.name == "uploads"  # the "../" did not escape the upload folder


def test_upload_needs_pdf_content_type(client, report_pdf):
    # A text/plain POST is a "simple" request that browsers send cross-site without a preflight.
    r = client.post("/v1/documents", content=report_pdf.read_bytes(), headers={"content-type": "text/plain"})
    assert r.status_code == 415


def test_upload_same_name_does_not_overwrite(client, tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    pdfgen.make_report(a)
    pdfgen.make_two_column(b)
    for f in (a, b):
        r = client.post("/v1/documents", content=f.read_bytes(), headers={**PDF, "x-filename": "report.pdf"})
        assert r.status_code == 201
    assert len(list((tmp_path / "uploads").glob("*-report.pdf"))) == 2


def test_upload_name_is_url_decoded(client, report_pdf):
    r = client.post(
        "/v1/documents",
        content=report_pdf.read_bytes(),
        headers={**PDF, "x-filename": "%D0%B7%D0%B2%D1%96%D1%82.pdf"},
    )
    assert r.status_code == 201
    assert any(
        f.endswith("-звіт.pdf") for f in (d["file"] for d in client.get("/v1/documents").json()["documents"])
    )


def test_rest_rejects_foreign_host_and_origin(client):
    assert client.get("/v1/documents", headers={"host": "evil.example"}).status_code == 421
    assert client.get("/v1/documents", headers={"origin": "https://evil.example"}).status_code == 403
    assert client.get("/v1/documents", headers={"origin": "http://localhost:3000"}).status_code == 200


def test_public_bind_requires_allowed_hosts(tmp_path, report_pdf, monkeypatch):
    monkeypatch.delenv("PDFCTX_ALLOWED_HOSTS", raising=False)
    lib = Library(tmp_path / "i.db", roots=[report_pdf])
    with pytest.raises(PdfctxError, match="PDFCTX_ALLOWED_HOSTS"):
        create_app(lib, host="0.0.0.0")
    monkeypatch.setenv("PDFCTX_ALLOWED_HOSTS", "pdfctx.example.com")
    with TestClient(create_app(lib, host="0.0.0.0"), base_url="https://pdfctx.example.com") as c:
        assert c.get("/healthz").status_code == 200
    lib.close()


def test_upload_dir_inside_root_is_refused(tmp_path, report_pdf):
    lib = Library(tmp_path / "i.db", roots=[tmp_path])
    with pytest.raises(PdfctxError, match="must not be inside"):
        create_app(lib, upload_dir=tmp_path / "uploads")
    lib.close()


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
