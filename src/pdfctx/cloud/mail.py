"""Sign-in emails through the Resend HTTP API. Without RESEND_API_KEY the link is logged instead (dev)."""

from __future__ import annotations

import json
import logging
import os
import urllib.request

log = logging.getLogger("pdfctx.cloud")


def send_magic_link(email: str, link: str) -> None:
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        log.warning("sign-in link for %s: %s", email, link)
        return
    body = {
        "from": os.environ.get("PDFCTX_MAIL_FROM", "pdfctx <signin@pdfctx.dev>"),
        "to": [email],
        "subject": "Your pdfctx sign-in link",
        "text": f"Sign in to pdfctx:\n\n{link}\n\nThe link works once and expires in 15 minutes. "
        "If you did not ask for it, ignore this email.",
    }
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()
