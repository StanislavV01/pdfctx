from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pdfctx.cloud.accounts import PLANS, Accounts, QuotaExceeded
from pdfctx.errors import PdfctxError


class Clock:
    def __init__(self):
        self.t = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)

    def __call__(self):
        return self.t


@pytest.fixture
def acc(tmp_path):
    clock = Clock()
    a = Accounts(tmp_path / "accounts.db", now=clock)
    a.clock = clock
    yield a
    a.close()


def test_magic_link_is_single_use_and_creates_one_workspace(acc):
    token = acc.request_magic("Ana@Example.com ")
    user = acc.verify_magic(token)
    assert user.email == "ana@example.com"
    with pytest.raises(PdfctxError, match="invalid or has expired"):
        acc.verify_magic(token)
    again = acc.verify_magic(acc.request_magic("ana@example.com"))
    assert again == user
    ws = acc.workspace_for_user(user)
    assert ws.plan == "free" and ws.owner_id == user.id


def test_magic_link_expires_and_is_rate_limited(acc):
    token = acc.request_magic("a@b.co")
    acc.clock.t += timedelta(minutes=16)
    with pytest.raises(PdfctxError):
        acc.verify_magic(token)
    for _ in range(4):
        acc.request_magic("a@b.co")
    with pytest.raises(PdfctxError, match="too many"):
        acc.request_magic("a@b.co")
    with pytest.raises(PdfctxError, match="valid email"):
        acc.request_magic("not-an-email")


def test_secrets_are_stored_hashed(acc):
    token = acc.request_magic("a@b.co")
    user = acc.verify_magic(token)
    session = acc.create_session(user)
    raw, _ = acc.create_key(acc.workspace_for_user(user).id, "agent")
    dump = "\n".join(acc.db.iterdump())
    for secret in (token, session, raw):
        assert secret not in dump


def test_sessions(acc):
    user = acc.verify_magic(acc.request_magic("a@b.co"))
    s = acc.create_session(user)
    assert acc.user_for_session(s) == user
    assert acc.user_for_session("forged") is None and acc.user_for_session(None) is None
    acc.end_session(s)
    assert acc.user_for_session(s) is None


def test_api_keys_resolve_to_their_workspace_until_revoked(acc):
    a = acc.workspace_for_user(acc.verify_magic(acc.request_magic("a@b.co")))
    b = acc.workspace_for_user(acc.verify_magic(acc.request_magic("b@b.co")))
    raw, rec = acc.create_key(a.id, "claude")
    assert raw.startswith("pk_live_") and rec["hint"] == "…" + raw[-4:]
    assert acc.workspace_for_key(raw).id == a.id
    assert acc.workspace_for_key("pk_live_nope") is None and acc.workspace_for_key("Bearer x") is None
    assert not acc.revoke_key(b.id, rec["id"])  # another workspace cannot revoke it
    assert acc.revoke_key(a.id, rec["id"])
    assert acc.workspace_for_key(raw) is None and acc.list_keys(a.id) == []


def test_quota_free_is_lifetime_paid_is_monthly(acc):
    ws = acc.workspace_for_user(acc.verify_magic(acc.request_magic("a@b.co")))
    acc.add_usage(ws, 40)
    acc.check_quota(ws, 10)
    with pytest.raises(QuotaExceeded, match="40 of 50"):
        acc.check_quota(ws, 11)
    acc.clock.t += timedelta(days=40)  # a new month does not reset the free allowance
    with pytest.raises(QuotaExceeded):
        acc.check_quota(ws, 11)
    acc.set_plan(ws.id, "pro", customer="cus_1", subscription="sub_1")
    pro = acc.workspace(ws.id)
    assert pro.plan == "pro" and acc.workspace_by_customer("cus_1").id == ws.id
    acc.add_usage(pro, PLANS["pro"].pages)
    with pytest.raises(QuotaExceeded):
        acc.check_quota(pro, 1)
    acc.clock.t += timedelta(days=31)
    acc.check_quota(pro, 1)  # monthly allowance renews


def test_stripe_events_are_processed_once(acc):
    assert acc.first_time_event("evt_1") and not acc.first_time_event("evt_1")
