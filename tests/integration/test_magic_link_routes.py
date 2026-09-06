"""Integration tests for the magic-link router (M3.4, issue #651).

The router lives at :mod:`app.core.local_backend.magic_link` and is
mounted under ``/api``. Two endpoints:

- ``POST /api/magic/start`` with JSON ``{"email": "..."}`` mints a
  token via ``MagicLinkPortImpl`` and asks ``SMTPMailTransport`` to
  send a verify URL. Returns ``{"status": "queued"}``.
- ``GET /api/magic/verify?token=...`` consumes the token and sets
  the ``apap_session`` cookie; redirects to ``/`` on success or
  ``/login?reason=invalid_or_expired`` on failure.

These tests pin the contract with real Postgres (the integration
conftest's ``self_host_schema`` fixture) and a fake SMTP transport
patched onto ``app.state``. No real SMTP, no real DB outside the
ephemeral schema.

Hard rules (apap-testing HR-2 + web-tdd-philosophy Rule 8):

- Tests run against the same Postgres as the production executor
  (``APAP_TEST_POSTGRES_DSN``). The lifespan binds the executor to
  the ephemeral schema via ``APAP_LOCAL_DB_SCHEMA``.
- The SMTP transport is monkeypatched onto ``app.state.smtp_transport``
  with a fake that records ``send`` calls; no real SMTP server.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx
import pytest

from app.core.local_backend.app import create_app
from app.core.session import read_session

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


# --- fake SMTP transport ----------------------------------------------------


@dataclass
class _FakeSMTPTransport:
    """In-process fake that records ``send`` calls.

    Returns ``True`` to mirror :class:`SMTPMailTransport.send`'s
    "sent" branch. Tests assert on the recorded envelope without
    touching the network.
    """

    sent: list[dict[str, str]] = field(default_factory=list)

    def send(self, to_addr: str, subject: str, body: str) -> bool:
        self.sent.append({"to": to_addr, "subject": subject, "body": body})
        return True


# --- fixture ---------------------------------------------------------------


@pytest.fixture
async def magic_link_client(self_host_schema, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[
    tuple[httpx.AsyncClient, _FakeSMTPTransport, str]
]:
    """Stand up the local backend with a fake SMTP transport.

    Returns ``(client, transport, base_url)`` so tests can assert on
    the recorded SMTP sends and on the public base URL the verify
    link points at.
    """
    monkeypatch.setenv("APAP_LOCAL_DB_URL", os.environ["APAP_TEST_POSTGRES_DSN"])
    monkeypatch.setenv("APAP_LOCAL_DB_SCHEMA", self_host_schema.schema)
    # ``APAP_SESSION_SECRET`` is required by the lifespan (see
    # ``app.core.config._validate_secrets``); 64 chars to clear the
    # 32-char minimum.
    monkeypatch.setenv("APAP_SESSION_SECRET", "integration-test-secret-64-chars-long-padding-x")

    app = create_app()
    fake_smtp = _FakeSMTPTransport()
    async with app.router.lifespan_context(app):
        # Patch the transport onto app.state AFTER the lifespan ran.
        # The lifespan only constructs the executor; the magic-link
        # router reads ``app.state.smtp_transport`` lazily inside the
        # request handler.
        app.state.smtp_transport = fake_smtp
        app.state.public_base_url = "https://apap.romancaba.com"
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        )
        try:
            yield client, fake_smtp, app.state.public_base_url
        finally:
            await client.aclose()


# --- POST /api/magic/start -------------------------------------------------


@pytest.mark.asyncio
async def test_magic_start_creates_token_and_queues_email(
    magic_link_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
    self_host_schema,
) -> None:
    """Happy path: POST /api/magic/start with a valid email mints a
    token in the DB, calls SMTP send with the right envelope, and
    returns ``{"status": "queued"}``."""
    client, fake_smtp, base_url = magic_link_client
    response = await client.post("/api/magic/start", json={"email": "ana@test.com"})
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "queued"}

    # Exactly one SMTP send happened, with the right shape.
    assert len(fake_smtp.sent) == 1
    msg = fake_smtp.sent[0]
    assert msg["to"] == "ana@test.com"
    assert msg["subject"]  # non-empty
    assert f"{base_url}/api/magic/verify?token=" in msg["body"]

    # Token landed in the DB (verify via the integration conftest).
    rows = self_host_schema.execute_sql("SELECT email FROM magic_link_tokens")
    assert len(rows) == 1
    assert rows[0]["email"] == "ana@test.com"


@pytest.mark.asyncio
async def test_magic_start_returns_400_on_missing_email(
    magic_link_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
) -> None:
    client, fake_smtp, _ = magic_link_client
    response = await client.post("/api/magic/start", json={})
    assert response.status_code == 400
    assert fake_smtp.sent == []  # no token minted, no email sent


@pytest.mark.asyncio
async def test_magic_start_returns_400_on_invalid_email_format(
    magic_link_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
) -> None:
    client, fake_smtp, _ = magic_link_client
    response = await client.post(
        "/api/magic/start", json={"email": "not-an-email"}
    )
    assert response.status_code == 400
    assert fake_smtp.sent == []


@pytest.mark.asyncio
async def test_magic_start_normalises_email_to_lowercase(
    magic_link_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
    self_host_schema,
) -> None:
    """``ANA@TEST.COM`` must hit the same DB row as ``ana@test.com``."""
    client, fake_smtp, _ = magic_link_client
    response = await client.post(
        "/api/magic/start", json={"email": "ANA@TEST.COM"}
    )
    assert response.status_code == 200
    rows = self_host_schema.execute_sql("SELECT email FROM magic_link_tokens")
    assert rows[0]["email"] == "ana@test.com"
    assert fake_smtp.sent[0]["to"] == "ANA@TEST.COM"


# --- GET /api/magic/verify ------------------------------------------------


@pytest.mark.asyncio
async def test_magic_verify_consumes_token_and_sets_session_cookie(
    magic_link_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
    self_host_schema,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The happy path: start mints a token, verify consumes it, the
    response carries ``apap_session`` with the canonical payload."""
    client, fake_smtp, base_url = magic_link_client
    # Mint a token via the start endpoint so the test exercises the
    # full path, not a back-door create.
    start = await client.post("/api/magic/start", json={"email": "ana@test.com"})
    assert start.status_code == 200

    # Extract the token from the recorded SMTP body.
    assert len(fake_smtp.sent) == 1
    body = fake_smtp.sent[0]["body"]
    prefix = f"{base_url}/api/magic/verify?token="
    assert prefix in body
    token = body.split(prefix, 1)[1].split()[0]  # strip trailing whitespace

    # Fresh context: the start response may have set cookies; clear
    # them so the verify response is the only cookie source.
    client.cookies.clear()
    response = await client.get(f"/api/magic/verify?token={token}", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/"

    # The cookie has the right flags and a signed payload with the
    # canonical email.
    set_cookie = response.headers.get("set-cookie", "")
    assert "apap_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=strict" in set_cookie

    # Decode the cookie payload via the public session helper.
    cookie_value = next(
        part.split("=", 1)[1].split(";", 1)[0]
        for part in set_cookie.split(", ")
        if part.startswith("apap_session=")
    )
    payload = read_session(
        cookie_value,
        secret=os.environ["APAP_SESSION_SECRET"],
    )
    assert payload is not None
    assert payload["email"] == "ana@test.com"


@pytest.mark.asyncio
async def test_magic_verify_returns_302_to_login_on_invalid_token(
    magic_link_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
) -> None:
    """An unknown token must NOT leak why it failed; we redirect to
    /login with a generic reason."""
    client, _, _ = magic_link_client
    response = await client.get(
        "/api/magic/verify?token=0" * 64, follow_redirects=False
    )
    assert response.status_code == 302
    assert "/login" in response.headers["location"]
    assert "reason" in response.headers["location"]


@pytest.mark.asyncio
async def test_magic_verify_rejects_already_consumed_token(
    magic_link_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
) -> None:
    """One-time use: a second consume of the same token returns the
    same redirect-to-login, never a second session."""
    client, fake_smtp, base_url = magic_link_client
    await client.post("/api/magic/start", json={"email": "ana@test.com"})
    body = fake_smtp.sent[0]["body"]
    prefix = f"{base_url}/api/magic/verify?token="
    token = body.split(prefix, 1)[1].split()[0]

    first = await client.get(f"/api/magic/verify?token={token}", follow_redirects=False)
    assert first.status_code == 302
    assert first.headers["location"] == "/"

    second = await client.get(f"/api/magic/verify?token={token}", follow_redirects=False)
    assert second.status_code == 302
    assert "/login" in second.headers["location"]
    # ``Set-Cookie`` is NOT set the second time — the token was
    # already consumed, no new session is minted.
    assert "apap_session=" not in second.headers.get("set-cookie", "")
