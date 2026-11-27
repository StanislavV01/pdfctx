"""FastAPI app: REST under /v1, MCP (streamable HTTP) at /mcp, page images for citation highlights."""

from __future__ import annotations

import contextlib
import io
import os
import re
from pathlib import Path

import pypdfium2 as pdfium
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field

from . import __version__
from .errors import PdfctxError
from .library import Library
from .mcp_server import build_server

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_UPLOAD_PAGES = 300


class ContextRequest(BaseModel):
    query: str
    budget_tokens: int = Field(4000)
    doc_ids: list[str] | None = None


def _status(e: PdfctxError) -> int:
    return 404 if str(e).startswith("unknown ") else 400


def _transport_security(host: str) -> TransportSecuritySettings | None:
    """DNS-rebinding protection for /mcp. Local hosts are allowed by default; for a public deployment list the
    public host names in PDFCTX_ALLOWED_HOSTS (comma-separated, e.g. "pdfctx.example.com,pdfctx.fly.dev")."""
    extra = [h.strip() for h in os.environ.get("PDFCTX_ALLOWED_HOSTS", "").split(",") if h.strip()]
    local = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    if not extra and host not in ("127.0.0.1", "localhost", "::1"):
        return None  # SDK default for non-local binds; set PDFCTX_ALLOWED_HOSTS to lock it down
    hosts = local + [h if ":" in h else f"{h}:*" for h in extra] + extra
    origins = [f"http://{h}" for h in local] + [f"https://{h}" for h in extra]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins
    )


def create_app(lib: Library, upload_dir: Path | None = None, host: str = "127.0.0.1") -> FastAPI:
    mcp = build_server(lib)
    mcp_app = mcp.streamable_http_app(
        streamable_http_path="/mcp", host=host, transport_security=_transport_security(host)
    )

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="pdfctx", version=__version__, lifespan=lifespan)
    origin = os.environ.get("PDFCTX_WEB_ORIGIN")
    if origin:
        app.add_middleware(CORSMiddleware, allow_origins=[origin], allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(PdfctxError)
    async def _pdfctx_error(_request: Request, exc: PdfctxError) -> JSONResponse:
        return JSONResponse({"error": str(exc)}, status_code=_status(exc))

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True, "version": __version__}

    @app.get("/v1/documents")
    def documents() -> dict:
        return lib.list_documents()

    @app.get("/v1/documents/{doc_id}/outline")
    def outline(doc_id: str, max_depth: int = 3) -> dict:
        return lib.outline(doc_id, max_depth)

    @app.get("/v1/sections/{section_id}")
    def section(section_id: str, max_tokens: int = 2000) -> dict:
        return lib.read_section(section_id, max_tokens)

    @app.get("/v1/search")
    def search(q: str, k: int = 8, doc_id: list[str] | None = Query(None)) -> dict:  # noqa: B008
        return lib.search(q, doc_id, k)

    @app.get("/v1/tables/{table_id}")
    def table(table_id: str, format: str = "markdown") -> dict:
        return lib.get_table(table_id, format)

    @app.get("/v1/blocks/{block_id}/cite")
    def cite(block_id: str) -> dict:
        return lib.cite(block_id)

    @app.post("/v1/context")
    def context(body: ContextRequest) -> dict:
        return lib.context_pack(body.query, body.budget_tokens, body.doc_ids)

    @app.get("/v1/documents/{doc_id}/pages/{page}.png")
    def page_png(doc_id: str, page: int, scale: float = 1.5) -> Response:
        doc = lib.store.get_document(doc_id)
        if not 0.25 <= scale <= 4:
            raise PdfctxError("scale must be between 0.25 and 4")
        if not 1 <= page <= doc.pages:
            raise PdfctxError(f"page must be between 1 and {doc.pages}")
        pdf = pdfium.PdfDocument(doc.path)
        try:
            image = pdf[page - 1].render(scale=scale).to_pil()
            buf = io.BytesIO()
            image.save(buf, format="PNG")
        finally:
            pdf.close()
        return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "max-age=3600"})

    @app.post("/v1/documents")
    async def upload(request: Request) -> JSONResponse:
        if upload_dir is None:
            return JSONResponse({"error": "uploads are disabled on this server"}, status_code=403)
        length = int(request.headers.get("content-length") or 0)
        if length > MAX_UPLOAD_BYTES:
            return JSONResponse({"error": "file is larger than 20 MB"}, status_code=413)
        body = bytearray()
        async for chunk in request.stream():
            body += chunk
            if len(body) > MAX_UPLOAD_BYTES:
                return JSONResponse({"error": "file is larger than 20 MB"}, status_code=413)
        if bytes(body[:5]) != b"%PDF-":
            return JSONResponse({"error": "not a PDF file"}, status_code=400)
        name = re.sub(r"[^\w.\- ]+", "_", request.headers.get("x-filename", "upload.pdf"))[:120]
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        try:
            pages = len(pdfium.PdfDocument(bytes(body)))
        except pdfium.PdfiumError:
            return JSONResponse({"error": "the PDF cannot be opened"}, status_code=400)
        if pages > MAX_UPLOAD_PAGES:
            return JSONResponse(
                {"error": f"PDF has {pages} pages; the limit is {MAX_UPLOAD_PAGES}"}, status_code=413
            )
        upload_dir.mkdir(parents=True, exist_ok=True)
        path = upload_dir / name
        path.write_bytes(bytes(body))
        lib.index([path])
        doc = lib.store.document_by_path(str(path.resolve()))
        assert doc is not None
        return JSONResponse(
            {"id": doc.id, "title": doc.title, "pages": doc.pages, "status": doc.status}, status_code=201
        )

    app.mount("/", mcp_app)  # after the REST routes, so /mcp is the only path it serves
    return app
