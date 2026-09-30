"""MailDev HTTP API client for the M3.1 E2E test.

MailDev exposes a JSON HTTP API on port 8025 at /api/v2/messages.
The M3.1 test uses this to read the most recent magic-link message
without parsing SMTP envelopes.

Issue #1004 (JD-A-003): the verify URL now carries ``token`` AND
``state`` query parameters. The original ``VERIFY_URL_RE`` stopped at
the first ``&`` and silently dropped the state, so the E2E browser
navigated a state-less URL — a shape the fixed verify endpoint
rejects. The regex therefore captures the full URL (both parameters)
and :func:`read_latest_verify_token_and_state` returns the parsed
``(token, state)`` pair explicitly.
"""
from __future__ import annotations

import re
import time
from typing import Any

import httpx

VERIFY_URL_RE = re.compile(
    r"https?://[^\s/]+/auth/magic/verify\?token=[A-Za-z0-9_\-]+&state=[A-Za-z0-9_\-]+"
)
"""Full verify URL: ``token`` AND ``state`` (issue #1004). The state
segment is mandatory — a URL without it cannot complete a login any
more, and navigating one would silently pin the fail-closed path."""


def _poll_verify_url(mailbox_url: str, *, timeout_seconds: float) -> str:
    """Poll MailDev until a message with a full verify URL arrives."""
    deadline = time.monotonic() + timeout_seconds
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{mailbox_url}/api/v2/messages", timeout=2.0)
            resp.raise_for_status()
            messages: list[dict[str, Any]] = resp.json()
            if messages:
                content = messages[0].get("Content", {}) or {}
                text = content.get("Body", "") or messages[0].get("Text", "")
                m = VERIFY_URL_RE.search(text)
                if m:
                    return m.group(0)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
        time.sleep(0.5)
    raise AssertionError(
        f"no magic-link message arrived in MailDev at {mailbox_url} within {timeout_seconds}s"
        + (f" (last error: {last_err!r})" if last_err else "")
    )


def read_latest_verify_url(mailbox_url: str, *, timeout_seconds: float = 5.0) -> str:
    """Return the verify URL (token AND state) from the most recent
    message in MailDev.

    Polls up to ``timeout_seconds`` for the message to arrive (MailDev is
    fast but the SMTP send is async; the lifespan logs the transport call
    AFTER returning from ``send_magic_link``).
    """
    return _poll_verify_url(mailbox_url, timeout_seconds=timeout_seconds)


def read_latest_verify_token_and_state(
    mailbox_url: str, *, timeout_seconds: float = 5.0
) -> tuple[str, str]:
    """Return the ``(token, state)`` pair from the most recent message.

    Explicit parsing (issue #1004, JD-A-003): callers that need the
    halves separately (assertions, re-built URLs) must not re-split the
    URL themselves and risk dropping ``&state=`` again.
    """
    url = _poll_verify_url(mailbox_url, timeout_seconds=timeout_seconds)
    query = url.split("?", 1)[1]
    params = dict(part.split("=", 1) for part in query.split("&"))
    return params["token"], params["state"]
