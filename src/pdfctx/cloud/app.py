"""The hosted app: sign-in, one index per workspace, plans and billing, REST and MCP per workspace.

    create_cloud_app(data_dir, public_url) → FastAPI

Browser calls go through the web app's /api proxy (same origin, session cookie). Agents call REST or MCP
with `Authorization: Bearer pk_live_…`. A workspace is always chosen from the caller's credentials,
never from an id in the request, so one customer cannot reach another's index.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import threading
import time
from collections import OrderedDict
from pathlib import Path

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from mcp.server.mcpserver import Context
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .. import __version__
from ..api import HttpError, _check_bind, _transport_security, install_guard, rest_router, save_and_index
from ..embed import get_embedder
from ..errors import PdfctxError
from ..indexer import IndexOptions
from ..library import Library
from ..mcp_server import build_server
from .accounts import PLANS, Accounts, User, Workspace
from .billing import BillingError, checkout_url, handle_event, portal_url, verify
from .mail import send_magic_link

COOKIE = "pdfctx_session"
SIGNIN_COOKIE = "pdfctx_signin"  # binds an emailed link to the browser that asked for it
SIGNIN_PER_IP_HOUR = 20
SIGNIN_PER_HOUR = 500
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class Tenants:
    """Open Libraries per workspace. Idle ones beyond `size` are closed, least recently used first.

    A Library with requests in flight, or used in the last `grace_s` seconds (MCP calls), is never closed."""

    def __init__(self, data_dir: Path, size: int = 32, grace_s: float = 120.0):
        self.data_dir = data_dir
        self.size = size
        self.grace_s = grace_s
        self._libs: OrderedDict[str, Library] = OrderedDict()
        self._refs: dict[str, int] = {}
        self._used: dict[str, float] = {}
        self._opening: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()
        embed = os.environ.get("PDFCTX_EMBED")
        self.options = IndexOptions(embedder=get_embedder(embed)) if embed else IndexOptions()

    def files(self, ws_id: str) -> Path:
        return self.data_dir / "ws" / ws_id / "files"

    def _open(self, ws_id: str) -> Library:
        files = self.files(ws_id)
        files.mkdir(parents=True, exist_ok=True)
        lib = Library(
            self.data_dir / "ws" / ws_id / "index.db", roots=[files], options=self.options, client="cloud"
        )
        lib.hide_paths = True
        return lib

    def get(self, ws_id: str) -> Library:
        """The workspace's Library, marked as used now (see `lease` for request-scoped use)."""
        with self._lock:
            lib = self._libs.get(ws_id)
            if lib is not None:
                self._libs.move_to_end(ws_id)
                self._used[ws_id] = time.monotonic()
                return lib
            opening = self._opening.setdefault(ws_id, threading.Lock())
        # Opening re-checks the workspace's files; do it outside the global lock so others are not blocked.
        with opening:
            with self._lock:
                lib = self._libs.get(ws_id)
            if lib is None:
                lib = self._open(ws_id)
                with self._lock:
                    self._libs[ws_id] = lib
                    self._evict()
            with self._lock:
                self._used[ws_id] = time.monotonic()
        return lib

    def _evict(self) -> None:
        now = time.monotonic()
        for ws_id in list(self._libs):
            if len(self._libs) <= self.size:
                return
            if self._refs.get(ws_id, 0) == 0 and now - self._used.get(ws_id, 0) > self.grace_s:
                self._libs.pop(ws_id).close()
                self._used.pop(ws_id, None)

    @contextlib.contextmanager
    def lease(self, ws_id: str):
        lib = self.get(ws_id)
        with self._lock:
            self._refs[ws_id] = self._refs.get(ws_id, 0) + 1
        try:
            yield lib
        finally:
            with self._lock:
                self._refs[ws_id] -= 1
                self._used[ws_id] = time.monotonic()

    def close(self) -> None:
        with self._lock:
            for lib in self._libs.values():
                lib.close()
            self._libs.clear()


class EmailRequest(BaseModel):
    email: str


class TokenRequest(BaseModel):
    token: str


class KeyRequest(BaseModel):
    name: str = "agent"


class CheckoutRequest(BaseModel):
    plan: str


def create_cloud_app(data_dir: Path | str, public_url: str, host: str = "127.0.0.1") -> FastAPI:
    _check_bind(host)
    data_dir = Path(data_dir)
    public_url = public_url.rstrip("/")
    secure_cookie = public_url.startswith("https://")
    if (
        secure_cookie
        and not os.environ.get("RESEND_API_KEY")
        and os.environ.get("PDFCTX_LOG_SIGNIN_LINKS") != "1"
    ):
        raise PdfctxError(
            "RESEND_API_KEY is not set: sign-in links would only go to the log, where anyone who reads it "
            "could sign in as any user. Set it, or PDFCTX_LOG_SIGNIN_LINKS=1 for a private test server."
        )
    signin_times: dict[str, list[float]] = {}
    acc = Accounts(data_dir / "accounts.db")
    tenants = Tenants(data_dir)

    # -- who is calling --------------------------------------------------------------------------

    def bearer(request_headers) -> str | None:
        auth = (request_headers.get("authorization") or "").strip()
        return auth[7:].strip() if auth.lower().startswith("bearer ") else None

    def session_user(request: Request) -> User:
        user = acc.user_for_session(request.cookies.get(COOKIE))
        if user is None:
            raise HttpError(401, "sign in first")
        if request.method not in SAFE_METHODS and request.headers.get("x-pdfctx") != "1":
            # A cross-site form cannot set custom headers: this stops CSRF with the session cookie.
            raise HttpError(403, "missing x-pdfctx header")
        return user

    def caller(request: Request) -> Workspace:
        key = bearer(request.headers)
        if key is not None:
            ws = acc.workspace_for_key(key)
            if ws is None:
                raise HttpError(401, "invalid or revoked API key")
            return ws
        return acc.workspace_for_user(session_user(request))

    def caller_lib(ws: Workspace = Depends(caller)):  # noqa: B008
        with tenants.lease(ws.id) as lib:  # held until the response is sent
            yield lib

    def uploader(lib: Library, name: str, data: bytes, pages: int) -> dict:
        ws_id = lib.store.path.parent.name
        ws = acc.workspace(ws_id)
        assert ws is not None
        files = tenants.files(ws_id)
        if lib.store.document_by_path(str((files / name).resolve())) is not None:
            return save_and_index(
                lib, files, name, data
            )  # already indexed: the same file costs nothing again
        acc.reserve(ws, pages)
        try:
            return save_and_index(lib, files, name, data)
        except Exception:
            acc.add_usage(ws, -pages)  # refund: nothing was indexed
            (files / name).unlink(missing_ok=True)
            raise

    # -- MCP: one server, the library comes from the API key on each request --------------------

    def mcp_lib(ctx: Context) -> Library:
        ws = acc.workspace_for_key(bearer(ctx.headers or {}) or "")
        if ws is None:
            raise PdfctxError("invalid or revoked API key")
        return tenants.get(ws.id)

    mcp = build_server(mcp_lib)
    mcp_app = mcp.streamable_http_app(
        streamable_http_path="/mcp", host=host, transport_security=_transport_security()
    )

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with mcp.session_manager.run():
            yield
        tenants.close()
        acc.close()

    app = FastAPI(title="pdfctx cloud", version=__version__, lifespan=lifespan)
    install_guard(app)

    @app.middleware("http")
    async def _mcp_needs_a_key(request: Request, call_next):
        if (
            request.url.path.startswith("/mcp")
            and (await run_in_threadpool(acc.workspace_for_key, bearer(request.headers) or "")) is None
        ):
            return JSONResponse(
                {"error": "MCP needs Authorization: Bearer <API key>"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)

    # -- sign-in ---------------------------------------------------------------------------------

    def limit_signins(ip: str) -> None:
        now = time.monotonic()
        for key, cap in ((ip, SIGNIN_PER_IP_HOUR), ("*", SIGNIN_PER_HOUR)):
            times = [t for t in signin_times.get(key, []) if now - t < 3600]
            if len(times) >= cap:
                raise HttpError(429, "too many sign-in requests; try again later")
            times.append(now)
            signin_times[key] = times

    @app.post("/auth/request")
    def auth_request(request: Request, body: EmailRequest, response: Response) -> dict:
        limit_signins(request.client.host if request.client else "?")
        nonce = secrets.token_urlsafe(24)
        token = acc.request_magic(body.email, nonce)
        # The emailed link opens a confirm page (link scanners only GET it, so they cannot use it up).
        send_magic_link(body.email.strip().lower(), f"{public_url}/signin/confirm?token={token}")
        response.set_cookie(
            SIGNIN_COOKIE,
            nonce,
            max_age=15 * 60,
            httponly=True,
            samesite="lax",
            secure=secure_cookie,
            path="/",
        )
        return {"sent": True}

    @app.post("/auth/verify")
    def auth_verify(request: Request, body: TokenRequest) -> Response:
        if request.headers.get("x-pdfctx") != "1":
            raise HttpError(403, "missing x-pdfctx header")
        user = acc.verify_magic(body.token, request.cookies.get(SIGNIN_COOKIE))
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(SIGNIN_COOKIE, path="/")
        resp.set_cookie(
            COOKIE,
            acc.create_session(user),
            max_age=30 * 24 * 3600,
            httponly=True,
            samesite="lax",
            secure=secure_cookie,
            path="/",
        )
        return resp

    @app.post("/auth/logout")
    def auth_logout(request: Request, response: Response) -> dict:
        if request.headers.get("x-pdfctx") != "1":
            raise HttpError(403, "missing x-pdfctx header")
        token = request.cookies.get(COOKIE)
        if token:
            acc.end_session(token)
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.get("/me")
    def me(request: Request) -> dict:
        user = session_user(request)
        ws = acc.workspace_for_user(user)
        plan = PLANS[ws.plan]
        return {
            "email": user.email,
            "workspace": {
                "id": ws.id,
                "plan": plan.id,
                "plan_name": plan.name,
                "pages_used": acc.pages_used(ws),
                "pages_limit": plan.pages,
                "period": "month" if plan.monthly else "total",
                "billing": ws.stripe_customer is not None,
            },
        }

    @app.get("/plans")
    def plans() -> dict:
        return {
            "plans": [
                {
                    "id": p.id,
                    "name": p.name,
                    "pages": p.pages,
                    "period": "month" if p.monthly else "total",
                    "price_usd": p.price_usd,
                }
                for p in PLANS.values()
            ]
        }

    # -- API keys (session only: a key cannot mint keys) ----------------------------------------

    @app.get("/keys")
    def keys(request: Request) -> dict:
        return {"keys": acc.list_keys(acc.workspace_for_user(session_user(request)).id)}

    @app.post("/keys", status_code=201)
    def create_key(request: Request, body: KeyRequest) -> dict:
        raw, rec = acc.create_key(acc.workspace_for_user(session_user(request)).id, body.name)
        return {**rec, "key": raw}

    @app.delete("/keys/{key_id}")
    def revoke_key(request: Request, key_id: str) -> dict:
        if not acc.revoke_key(acc.workspace_for_user(session_user(request)).id, key_id):
            raise HttpError(404, f"unknown key '{key_id}'")
        return {"revoked": key_id}

    # -- billing ---------------------------------------------------------------------------------

    @app.post("/billing/checkout")
    def checkout(request: Request, body: CheckoutRequest) -> dict:
        user = session_user(request)
        return {"url": checkout_url(acc.workspace_for_user(user), user.email, body.plan, public_url)}

    @app.post("/billing/portal")
    def portal(request: Request) -> dict:
        return {"url": portal_url(acc.workspace_for_user(session_user(request)), public_url)}

    @app.post("/billing/webhook")
    async def webhook(request: Request) -> dict:
        secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
        if not secret:
            raise HttpError(503, "billing is not configured on this server")
        payload = await request.body()
        try:
            event = verify(payload, request.headers.get("stripe-signature", ""), secret)
        except BillingError as e:
            raise HttpError(400, str(e)) from e
        return {"result": handle_event(acc, event)}

    # -- the workspace's documents ---------------------------------------------------------------

    app.include_router(rest_router(caller_lib, uploader, allow_delete=True), prefix="/v1")
    app.mount("/", mcp_app)
    app.state.accounts = acc
    app.state.tenants = tenants
    return app
