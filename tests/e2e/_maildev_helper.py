"""MailDev HTTP API client for the M3.1 E2E test.

MailDev >=3.0 exposes a JSON HTTP API at ``/api/email`` returning a
list of messages (each with the ``text`` field inlined). The docker
container's port 1080 is mapped to host port 8025 in our dev compose.

The M3.1 test uses this to read the most recent magic-link message
without parsing SMTP envelopes.
"""
from __future__ import annotations

import re
import time
from typing import Any

import httpx

VERIFY_URL_RE = re.compile(r"(?:https?://[^\s/]+)?/auth/magic/verify\?token=[A-Za-z0-9_\-]+")


def read_latest_verify_url(mailbox_url: str, *, timeout_seconds: float = 10.0) -> str:
    """Return the verify URL from the most recent message in MailDev.

    Polls up to ``timeout_seconds`` for the message to arrive (MailDev is
    fast but the SMTP send is async; the lifespan logs the transport call
    AFTER returning from ``send_magic_link``).
    """
    deadline = time.monotonic() + timeout_seconds
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            # MailDev >=3.0 (rc.3) uses /api/email (with the message body
            # inlined in the list response, under `text`). Older versions
            # used /api/v2/messages which only returned metadata.
            resp = httpx.get(f"{mailbox_url}/api/email", timeout=2.0)
            resp.raise_for_status()
            emails: list[dict[str, Any]] = resp.json()
            if emails:
                email = emails[-1]
                text = (
                    email.get("text")
                    or email.get("Text")
                    or email.get("body")
                    or email.get("Body")
                    or ""
                )
                if isinstance(text, dict):
                    text = text.get("plain") or text.get("Body") or ""
                m = VERIFY_URL_RE.search(str(text))
                if m:
                    return m.group(0)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
        time.sleep(0.5)
    raise AssertionError(
        f"no magic-link message arrived in MailDev at {mailbox_url} within {timeout_seconds}s"
        + (f" (last error: {last_err!r})" if last_err else "")
    )
