from __future__ import annotations

import hashlib
import hmac
import time

import pytest

from pdfctx.cloud.accounts import Accounts
from pdfctx.cloud.billing import BillingError, handle_event, verify

SECRET = "whsec_test"


def sign(payload: bytes, t: int | None = None, secret: str = SECRET) -> str:
    t = int(time.time()) if t is None else t
    mac = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


@pytest.fixture
def acc(tmp_path, monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_PRO", "price_pro")
    monkeypatch.setenv("STRIPE_PRICE_TEAM", "price_team")
    a = Accounts(tmp_path / "a.db")
    yield a
    a.close()


def test_signature_checks():
    payload = b'{"id":"evt_1"}'
    assert verify(payload, sign(payload), SECRET)["id"] == "evt_1"
    with pytest.raises(BillingError, match="does not match"):
        verify(payload, sign(payload, secret="other"), SECRET)
    with pytest.raises(BillingError, match="does not match"):
        verify(b'{"id":"evt_2"}', sign(payload), SECRET)  # body changed after signing
    with pytest.raises(BillingError, match="tolerance"):
        verify(payload, sign(payload, t=int(time.time()) - 3600), SECRET)  # replayed
    with pytest.raises(BillingError, match="bad signature"):
        verify(payload, "garbage", SECRET)


def sub_event(eid, kind, ws_id, price="price_pro", status="active"):
    return {
        "id": eid,
        "type": kind,
        "data": {
            "object": {
                "id": "sub_1",
                "customer": "cus_1",
                "status": status,
                "metadata": {"workspace_id": ws_id},
                "items": {"data": [{"price": {"id": price}}]},
            }
        },
    }


def test_subscription_lifecycle(acc):
    ws = acc.workspace_for_user(acc.verify_magic(acc.request_magic("a@b.co")))
    done = handle_event(
        acc,
        {
            "id": "evt_c",
            "type": "checkout.session.completed",
            "data": {"object": {"client_reference_id": ws.id, "customer": "cus_1", "subscription": "sub_1"}},
        },
    )
    assert done == "linked customer" and acc.workspace(ws.id).stripe_customer == "cus_1"
    assert handle_event(acc, sub_event("evt_1", "customer.subscription.created", ws.id)) == "plan pro"
    assert acc.workspace(ws.id).plan == "pro"
    assert handle_event(acc, sub_event("evt_1", "customer.subscription.created", ws.id)) == "duplicate"
    handle_event(acc, sub_event("evt_2", "customer.subscription.updated", ws.id, price="price_team"))
    assert acc.workspace(ws.id).plan == "team"
    handle_event(acc, sub_event("evt_3", "customer.subscription.updated", ws.id, status="canceled"))
    assert acc.workspace(ws.id).plan == "free"
    handle_event(
        acc, sub_event("evt_4", "customer.subscription.updated", "", price="price_pro")
    )  # by customer
    assert acc.workspace(ws.id).plan == "pro"
    handle_event(acc, sub_event("evt_5", "customer.subscription.deleted", ws.id))
    assert acc.workspace(ws.id).plan == "free"


def test_unknown_price_and_events(acc):
    ws = acc.workspace_for_user(acc.verify_magic(acc.request_magic("a@b.co")))
    handle_event(acc, sub_event("evt_1", "customer.subscription.created", ws.id, price="price_other"))
    assert acc.workspace(ws.id).plan == "free"  # a price we do not sell grants nothing
    assert handle_event(acc, {"id": "evt_x", "type": "invoice.paid", "data": {"object": {}}}) == "ignored"
