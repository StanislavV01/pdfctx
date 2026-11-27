"""FastAPI app: REST under /v1, MCP (streamable HTTP) at /mcp, page images for citation highlights."""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pypdfium2 as pdfium
from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import __version__
from .errors import NotFound, PdfctxError
from .library import Library
from .mcp_server import build_server
from .metrics import to_csv
from .parse.pdf import PDFIUM_LOCK

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_UPLOAD_PAGES = 300
MAX_RENDER_PIXELS = 40_000_000  # about a 6300 × 6300 bitmap
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


class MetricsRequest(BaseModel):
    metrics: list[str]
    years: list[int] | None = None
    doc_ids: list[str] | None = None


class ContextRequest(BaseModel):
    query: str
    budget_tokens: int = Field(4000)
    doc_ids: list[str] | None = None


class HttpError(PdfctxError):
    """An error with its own HTTP status (401, 402, 403, 413, 415 …)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _status(e: PdfctxError) -> int:
    status = getattr(e, "status", None)  # HttpError, QuotaExceeded (402) …
    if isinstance(status, int):
        return status
    return 404 if isinstance(e, NotFound) else 400


def _extra_hosts() -> list[str]:
    return [h.strip().lower() for h in os.environ.get("PDFCTX_ALLOWED_HOSTS", "").split(",") if h.strip()]


def _check_bind(host: str) -> None:
    if host not in LOCAL_HOSTS and not _extra_hosts():
        raise PdfctxError(
            f"binding to {host} needs PDFCTX_ALLOWED_HOSTS (the public host names clients will use); "
            "without it any site could reach this server through DNS rebinding"
        )


def _host_name(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("["):
        return value[1 : value.find("]")] if "]" in value else value
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def _allowed_host(value: str) -> bool:
    return _host_name(value) in (*LOCAL_HOSTS, *(_host_name(h) for h in _extra_hosts()))


def _allowed_origin(origin: str) -> bool:
    web = os.environ.get("PDFCTX_WEB_ORIGIN", "").rstrip("/").lower()
    if web and origin.rstrip("/").lower() == web:
        return True
    parts = urlsplit(origin)
    return bool(parts.hostname) and _allowed_host(parts.hostname or "")


def _transport_security() -> TransportSecuritySettings:
    """DNS-rebinding protection for /mcp. Local hosts are always allowed; for a public deployment list the
    public host names in PDFCTX_ALLOWED_HOSTS (comma-separated, e.g. "pdfctx.example.com,pdfctx.fly.dev")."""
    extra = _extra_hosts()
    local = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    hosts = local + [h if ":" in h else f"{h}:*" for h in extra] + extra
    origins = [f"http://{h}" for h in local] + [f"https://{h}" for h in extra]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins
    )


def _upload_name(raw: str, body: bytes) -> str:
    name = re.sub(r"[^\w.\- ]+", "_", unquote(raw))[:100] or "upload.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    # The content hash keeps two different uploads with one name apart; the same file maps to the same path.
    return f"{hashlib.sha256(body).hexdigest()[:12]}-{name}"


def install_guard(app: FastAPI) -> None:
    """Host/Origin checks on every route, JSON errors, and CORS for PDFCTX_WEB_ORIGIN."""

    @app.middleware("http")
    async def _rebinding_guard(request: Request, call_next):
        # Applies to every route, not only /mcp: a page that rebinds its domain to 127.0.0.1 must not read
        # the documents, and another site's page must not upload into them.
        if not _allowed_host(request.headers.get("host", "")):
            return JSONResponse({"error": "host not allowed"}, status_code=421)
        origin = request.headers.get("origin")
        if origin and not _allowed_origin(origin):
            return JSONResponse({"error": "origin not allowed"}, status_code=403)
        return await call_next(request)

    origin = os.environ.get("PDFCTX_WEB_ORIGIN")
    if origin:  # added after the guard, so it runs first and answers preflights
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[origin],
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=True,
        )

    @app.exception_handler(PdfctxError)
    async def _pdfctx_error(_request: Request, exc: PdfctxError) -> JSONResponse:
        return JSONResponse({"error": str(exc)}, status_code=_status(exc))

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True, "version": __version__}


async def read_upload(request: Request) -> tuple[str, bytes, int]:
    """(file name, bytes, page count) of a raw PDF request body, within the size and page limits."""
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/pdf":
        # Also forces a CORS preflight, so other sites cannot post here from a browser.
        raise HttpError(415, "send the PDF with content-type: application/pdf")
    try:
        length = int(request.headers.get("content-length") or 0)
    except ValueError as e:
        raise HttpError(400, "invalid content-length") from e
    if length > MAX_UPLOAD_BYTES:
        raise HttpError(413, "file is larger than 20 MB")
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_UPLOAD_BYTES:
            raise HttpError(413, "file is larger than 20 MB")
    if bytes(body[:5]) != b"%PDF-":
        raise HttpError(400, "not a PDF file")
    data = bytes(body)
    try:
        with PDFIUM_LOCK:
            pdf = pdfium.PdfDocument(data)
            pages = len(pdf)
            pdf.close()
    except pdfium.PdfiumError as e:
        raise HttpError(400, "the PDF cannot be opened") from e
    if pages > MAX_UPLOAD_PAGES:
        raise HttpError(413, f"PDF has {pages} pages; the limit is {MAX_UPLOAD_PAGES}")
    return _upload_name(request.headers.get("x-filename", "upload.pdf"), data), data, pages


def save_and_index(lib: Library, folder: Path, name: str, data: bytes) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    if not path.exists():
        with open(path, "xb") as f:
            f.write(data)
    lib.index([path])
    doc = lib.store.document_by_path(str(path.resolve()))
    assert doc is not None
    return {"id": doc.id, "title": doc.title, "pages": doc.pages, "status": doc.status}


Uploader = Callable[[Library, str, bytes, int], dict]


def rest_router(
    get_lib: Callable[..., Library], uploader: Uploader | None, allow_delete: bool = False
) -> APIRouter:
    """The REST API over one Library, chosen per request by the `get_lib` dependency."""
    r = APIRouter()
    # A default, not Annotated[...]: with postponed annotations FastAPI resolves names from module globals.
    dep = Depends(get_lib)

    @r.get("/documents")
    def documents(lib: Library = dep) -> dict:
        return lib.list_documents()

    @r.get("/documents/{doc_id}/outline")
    def outline(doc_id: str, max_depth: int = 3, lib: Library = dep) -> dict:
        return lib.outline(doc_id, max_depth)

    @r.get("/sections/{section_id}")
    def section(section_id: str, max_tokens: int = 2000, lib: Library = dep) -> dict:
        return lib.read_section(section_id, max_tokens)

    @r.get("/search")
    def search(q: str, k: int = 8, doc_id: list[str] | None = Query(None), lib: Library = dep) -> dict:  # noqa: B008
        return lib.search(q, doc_id, k)

    @r.get("/tables/{table_id}")
    def table(table_id: str, format: str = "markdown", lib: Library = dep) -> dict:
        return lib.get_table(table_id, format)

    @r.get("/blocks/{block_id}/cite")
    def cite(block_id: str, lib: Library = dep) -> dict:
        return lib.cite(block_id)

    @r.get("/audit")
    def audit(limit: int = 100, lib: Library = dep) -> dict:
        return {"entries": lib.audit(limit)}

    @r.post("/metrics", response_model=None)
    def metrics(body: MetricsRequest, format: str = "json", lib: Library = dep) -> dict | Response:
        out = lib.extract_metrics(body.metrics, body.years, body.doc_ids)
        if format == "csv":
            return Response(
                to_csv(out),
                media_type="text/csv",
                headers={"Content-Disposition": 'attachment; filename="metrics.csv"'},
            )
        return out

    @r.post("/context")
    def context(body: ContextRequest, lib: Library = dep) -> dict:
        return lib.context_pack(body.query, body.budget_tokens, body.doc_ids)

    @r.get("/documents/{doc_id}/pages/{page}.png")
    def page_png(doc_id: str, page: int, scale: float = 1.5, lib: Library = dep) -> Response:
        doc = lib.store.get_document(doc_id)
        if not 0.25 <= scale <= 4:
            raise PdfctxError("scale must be between 0.25 and 4")
        if not 1 <= page <= doc.pages:
            raise PdfctxError(f"page must be between 1 and {doc.pages}")
        with PDFIUM_LOCK:
            pdf = pdfium.PdfDocument(doc.path)
            try:
                p = pdf[page - 1]
                w, h = p.get_size()
                if w * h * scale * scale > MAX_RENDER_PIXELS:
                    raise PdfctxError("page is too large to render at this scale")
                image = p.render(scale=scale).to_pil()
            finally:
                pdf.close()
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return Response(
            buf.getvalue(), media_type="image/png", headers={"Cache-Control": "private, max-age=3600"}
        )

    @r.post("/documents")
    async def upload(request: Request, lib: Library = dep) -> JSONResponse:
        if uploader is None:
            raise HttpError(403, "uploads are disabled on this server")
        name, data, pages = await read_upload(request)
        return JSONResponse(await run_in_threadpool(uploader, lib, name, data, pages), status_code=201)

    if allow_delete:

        @r.delete("/documents/{doc_id}")
        def delete(doc_id: str, lib: Library = dep) -> dict:
            doc = lib.store.get_document(doc_id)
            Path(doc.path).unlink(missing_ok=True)
            lib.refresh(force=True)
            return {"deleted": doc_id}

    return r


def create_app(lib: Library, upload_dir: Path | None = None, host: str = "127.0.0.1") -> FastAPI:
    _check_bind(host)
    if upload_dir is not None:
        up = Path(upload_dir).resolve()
        for root in lib.roots:
            rt = Path(root).resolve()
            if up == rt or rt in up.parents:
                raise PdfctxError(f"the upload folder {up} must not be inside an indexed folder ({rt})")
    lib.hide_paths = True
    if upload_dir is not None:
        lib.display_roots.append(Path(upload_dir))
    mcp = build_server(lib)
    mcp_app = mcp.streamable_http_app(
        streamable_http_path="/mcp", host=host, transport_security=_transport_security()
    )

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="pdfctx", version=__version__, lifespan=lifespan)
    install_guard(app)

    def uploader(lib: Library, name: str, data: bytes, pages: int) -> dict:
        assert upload_dir is not None
        return save_and_index(lib, Path(upload_dir), name, data)

    app.include_router(rest_router(lambda: lib, uploader if upload_dir is not None else None), prefix="/v1")
    app.mount("/", mcp_app)  # after the REST routes, so /mcp is the only path it serves
    return app
