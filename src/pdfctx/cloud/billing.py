"""Stripe Checkout and webhooks over plain HTTPS (no SDK).

Configuration: STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_PRO, STRIPE_PRICE_TEAM.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request

from ..errors import PdfctxError
from .accounts import Accounts, Workspace

TOLERANCE_S = 300


class BillingError(PdfctxError):
    pass


def price_for(plan: str) -> str:
    env = {"pro": "STRIPE_PRICE_PRO", "team": "STRIPE_PRICE_TEAM"}.get(plan)
    price = os.environ.get(env or "")
    if not env:
        raise BillingError(f"plan '{plan}' cannot be bought")
    if not price:
        raise BillingError("billing is not configured on this server")
    return price


def plan_for_price(price: str) -> str | None:
    for plan, env in (("pro", "STRIPE_PRICE_PRO"), ("team", "STRIPE_PRICE_TEAM")):
        if price and os.environ.get(env) == price:
            return plan
    return None


def _stripe(path: str, form: dict[str, str]) -> dict:
    key = os.environ.get("STRIPE_SECRET_KEY")
    if not key:
        raise BillingError("billing is not configured on this server")
    req = urllib.request.Request(
        f"https://api.stripe.com/v1/{path}",
        data=urllib.parse.urlencode(form).encode(),
        headers={"Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def checkout_url(ws: Workspace, email: str, plan: str, base_url: str) -> str:
    form = {
        "mode": "subscription",
        "line_items[0][price]": price_for(plan),
        "line_items[0][quantity]": "1",
        "client_reference_id": ws.id,
        "metadata[workspace_id]": ws.id,
        "subscription_data[metadata][workspace_id]": ws.id,
        "success_url": f"{base_url}/app?upgraded=1",
        "cancel_url": f"{base_url}/pricing",
        "allow_promotion_codes": "true",
    }
    if ws.stripe_customer:
        form["customer"] = ws.stripe_customer
    else:
        form["customer_email"] = email
    return _stripe("checkout/sessions", form)["url"]


def portal_url(ws: Workspace, base_url: str) -> str:
    if not ws.stripe_customer:
        raise BillingError("this workspace has no subscription yet")
    return _stripe(
        "billing_portal/sessions", {"customer": ws.stripe_customer, "return_url": f"{base_url}/app"}
    )["url"]


def verify(payload: bytes, header: str, secret: str, now: float | None = None) -> dict:
    """Check a Stripe-Signature header (v1 = HMAC-SHA256 of "t.payload") and return the event."""
    parts: dict[str, list[str]] = {}
    for item in (header or "").split(","):
        k, _, v = item.strip().partition("=")
        parts.setdefault(k, []).append(v)
    try:
        t = int(parts["t"][0])
    except (KeyError, ValueError) as e:
        raise BillingError("bad signature header") from e
    if abs((now or time.time()) - t) > TOLERANCE_S:
        raise BillingError("signature timestamp outside tolerance")
    expected = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, sig) for sig in parts.get("v1", [])):
        raise BillingError("signature does not match")
    return json.loads(payload)


def handle_event(acc: Accounts, event: dict) -> str:
    """Apply a verified event once. It is recorded only after it was applied, so a failure is retried."""
    if acc.seen_event(event.get("id", "")):
        return "duplicate"
    result = _apply(acc, event)
    acc.first_time_event(event.get("id", ""))
    return result


def _apply(acc: Accounts, event: dict) -> str:
    kind = event.get("type", "")
    obj = event.get("data", {}).get("object", {})
    if kind == "checkout.session.completed":
        ws = acc.workspace(obj.get("client_reference_id") or obj.get("metadata", {}).get("workspace_id", ""))
        if ws is None:
            return "unknown workspace"
        # The plan itself comes with the subscription event; remember the customer now.
        acc.set_plan(ws.id, ws.plan, customer=obj.get("customer"), subscription=obj.get("subscription"))
        return "linked customer"
    if kind in (
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ):
        ws = acc.workspace(obj.get("metadata", {}).get("workspace_id", "")) or acc.workspace_by_customer(
            obj.get("customer", "")
        )
        if ws is None:
            return "unknown workspace"
        active = kind != "customer.subscription.deleted" and obj.get("status") in (
            "active",
            "trialing",
            "past_due",
        )
        if ws.stripe_subscription and obj.get("id") != ws.stripe_subscription and not active:
            # A late event about an older or abandoned subscription must not downgrade the current one.
            return "ignored stale subscription"
        items = obj.get("items", {}).get("data", [])
        plan = plan_for_price(items[0]["price"]["id"]) if items else None
        acc.set_plan(
            ws.id,
            plan if active and plan else "free",
            customer=obj.get("customer"),
            subscription=obj.get("id") if active else None,
        )
        return f"plan {plan if active and plan else 'free'}"
    return "ignored"
