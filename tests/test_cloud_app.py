from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from pdfctx.cloud import app as cloud_app
from pdfctx.cloud.app import create_cloud_app

BASE = "http://127.0.0.1:8000"
PDF = {"content-type": "application/pdf", "x-pdfctx": "1"}
W = {"x-pdfctx": "1"}


@pytest.fixture
def links(monkeypatch):
    sent: dict[str, str] = {}
    monkeypatch.setattr(cloud_app, "send_magic_link", lambda email, link: sent.__setitem__(email, link))
    return sent


@pytest.fixture
def server(tmp_path, links, monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_t")
    monkeypatch.setenv("STRIPE_PRICE_PRO", "price_pro")
    app = create_cloud_app(tmp_path / "data", "http://localhost:3000")
    with TestClient(app, base_url=BASE) as c:
        c.links = links
        yield c


def sign_in(server, email: str) -> TestClient:
    """A separate client (own cookie jar) signed in as `email` through the emailed link."""
    c = TestClient(server.app, base_url=BASE)
    assert c.post("/auth/request", json={"email": email}).json() == {"sent": True}
    link = server.links[email]
    assert link.startswith("http://localhost:3000/api/auth/verify?token=")
    r = c.get("/auth/verify", params={"token": link.split("token=")[1]}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "http://localhost:3000/app"
    assert "httponly" in r.headers["set-cookie"].lower()
    return c


def test_sign_in_and_me(server):
    c = sign_in(server, "ana@fund.com")
    me = c.get("/me").json()
    assert me["email"] == "ana@fund.com" and me["workspace"]["plan"] == "free"
    assert me["workspace"]["pages_limit"] == 50
    assert TestClient(server.app, base_url=BASE).get("/me").status_code == 401
    r = c.get("/auth/verify", params={"token": "used-or-wrong"}, follow_redirects=False)
    assert r.headers["location"].endswith("/signin?error=expired")


def test_workspaces_are_isolated(server, report_pdf):
    a, b = sign_in(server, "a@fund.com"), sign_in(server, "b@fund.com")
    doc = a.post(
        "/v1/documents", content=report_pdf.read_bytes(), headers={**PDF, "x-filename": "r.pdf"}
    ).json()
    assert [d["id"] for d in a.get("/v1/documents").json()["documents"]] == [doc["id"]]
    assert b.get("/v1/documents").json()["documents"] == []
    assert b.get(f"/v1/documents/{doc['id']}/outline").status_code == 404
    assert b.get(f"/v1/documents/{doc['id']}/pages/1.png").status_code == 404
    assert b.post("/v1/metrics", json={"metrics": ["Total"]}, headers=W).json()["values"] == []
    assert a.post("/v1/metrics", json={"metrics": ["Total"], "years": [2025]}, headers=W).json()["values"]


def test_csrf_header_required_for_cookie_writes(server, report_pdf):
    c = sign_in(server, "a@fund.com")
    r = c.post("/v1/documents", content=report_pdf.read_bytes(), headers={"content-type": "application/pdf"})
    assert r.status_code == 403 and "x-pdfctx" in r.json()["error"]
    assert c.post("/keys", json={"name": "x"}).status_code == 403


def test_api_keys_for_agents(server, report_pdf):
    c = sign_in(server, "a@fund.com")
    created = c.post("/keys", json={"name": "claude"}, headers=W).json()
    key = created["key"]
    agent = TestClient(server.app, base_url=BASE, headers={"authorization": f"Bearer {key}"})
    up = agent.post(
        "/v1/documents", content=report_pdf.read_bytes(), headers={"content-type": "application/pdf"}
    )
    assert up.status_code == 201  # keys need no CSRF header: they are not ambient credentials
    assert agent.get("/v1/search", params={"q": "termination notice"}).json()["results"]
    assert agent.get("/keys").status_code == 401  # a key cannot manage keys
    assert c.get("/keys").json()["keys"][0]["hint"] == "…" + key[-4:]
    assert c.delete(f"/keys/{created['id']}", headers=W).json() == {"revoked": created["id"]}
    assert agent.get("/v1/documents").status_code == 401


def test_mcp_needs_a_key_and_sees_only_its_workspace(server, report_pdf):
    hdrs = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "t", "version": "1"},
        },
    }
    assert server.post("/mcp", json=init, headers=hdrs).status_code == 401
    c = sign_in(server, "a@fund.com")
    key = c.post("/keys", json={}, headers=W).json()["key"]
    r = server.post("/mcp", json=init, headers={**hdrs, "authorization": f"Bearer {key}"})
    assert r.status_code == 200


def test_free_plan_quota_is_402(server, report_pdf, tmp_path):
    c = sign_in(server, "a@fund.com")
    ws_id = c.get("/me").json()["workspace"]["id"]
    acc = server.app.state.accounts
    acc.add_usage(acc.workspace(ws_id), 48)  # 2 pages left; the report has 4
    r = c.post("/v1/documents", content=report_pdf.read_bytes(), headers=PDF)
    assert r.status_code == 402 and "48 of 50" in r.json()["error"]


def test_delete_document(server, report_pdf):
    c = sign_in(server, "a@fund.com")
    doc = c.post("/v1/documents", content=report_pdf.read_bytes(), headers=PDF).json()
    assert c.delete(f"/v1/documents/{doc['id']}", headers=W).json() == {"deleted": doc["id"]}
    assert c.get("/v1/documents").json()["documents"] == []


def test_stripe_webhook_upgrades_the_plan(server):
    c = sign_in(server, "a@fund.com")
    ws_id = c.get("/me").json()["workspace"]["id"]
    event = {
        "id": "evt_1",
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_1",
                "customer": "cus_1",
                "status": "active",
                "metadata": {"workspace_id": ws_id},
                "items": {"data": [{"price": {"id": "price_pro"}}]},
            }
        },
    }
    payload = json.dumps(event).encode()
    t = int(time.time())
    sig = hmac.new(b"whsec_t", f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    bad = server.post("/billing/webhook", content=payload, headers={"stripe-signature": f"t={t},v1=00"})
    assert bad.status_code == 400
    ok = server.post("/billing/webhook", content=payload, headers={"stripe-signature": f"t={t},v1={sig}"})
    assert ok.json() == {"result": "plan pro"}
    assert c.get("/me").json()["workspace"]["pages_limit"] == 2000


def test_plans_are_public(server):
    assert [p["id"] for p in server.get("/plans").json()["plans"]] == ["free", "pro", "team"]
