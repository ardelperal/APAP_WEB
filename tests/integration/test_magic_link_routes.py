"""Integration tests for the magic-link router (M3.4, issue #651).

The router lives at :mod:`app.core.local_backend.magic_link` and is
mounted under ``/api``. Two endpoints:

- ``POST /auth/magic/start`` with JSON ``{"email": "..."}`` mints a
  token via ``MagicLinkPortImpl`` and asks ``SMTPMailTransport`` to
  send a verify URL. Returns ``{"status": "queued"}``.
- ``GET /auth/magic/verify?token=...`` consumes the token, resolves the
  ACTIVE user for the email via the ``AuthUsersPort`` seam (issue #917)
  and sets the ``apap_session`` cookie with the OAuth-parity payload;
  redirects to ``/`` on success, ``/unauthorized`` (no cookie) when the
  email is not an active user, or ``/login?reason=invalid_or_expired``
  on token failure.

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

import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx
import pytest

from app.core.local_backend import magic_link
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
    # The ``create_app`` factory validates ``APAP_RAWSQL_AUTH_TOKEN``
    # at lifespan startup (the rawsql router is mounted in
    # ``local_backend/app.py`` alongside the magic-link router).
    # Use a 64-character deterministic value that the validator
    # accepts; the token gate rejects the real request unless the
    # caller presents the exact same value, which the magic-link
    # round-trip never does.
    monkeypatch.setenv(
        "APAP_RAWSQL_AUTH_TOKEN",
        "integration-test-rawsql-token-64-chars-padding-xyz-aaaaaa",
    )

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
            base_url="https://test",
        )
        try:
            yield client, fake_smtp, app.state.public_base_url
        finally:
            await client.aclose()


def _seed_active_user(self_host_schema, email: str) -> None:
    """Insert an active ``usuarios_autorizados`` row for ``email``.

    Issue #917: the verify endpoint resolves the user from the auth
    table before minting a session (fail closed on unknown email), so
    every happy-path verify test needs its email seeded.
    """
    self_host_schema.execute_sql(
        "INSERT INTO usuarios_autorizados (email, rol, activo) "
        "VALUES ($1, 'key_user', true)",
        [email],
    )


# --- shared email-body parser ------------------------------------------------


def _extract_token_and_state(body: str, base_url: str) -> tuple[str, str]:
    """Parse ``(token, state)`` from the emailed verify URL.

    Explicit parsing (issue #1004, JD-B-002/JD-A-002): the previous
    ``body.split(prefix)[1].split()[0]`` cut swallowed ``&state=...``
    into the token, so verify URLs were mangled and the state gate was
    exercised only by accident. Both magic-link test modules import
    this helper (the canonical definition lives here; the state tests
    import it alongside ``_seed_active_user``).

    Fails the test when the link does not carry the ``state`` query
    parameter — the parameter IS the fix under test.
    """
    prefix = f"{base_url}/auth/magic/verify?token="
    assert prefix in body, "email body must contain the verify URL"
    query = body.split(prefix, 1)[1].split()[0]
    token, sep, state = query.partition("&state=")
    assert sep and state, "verify URL must carry a non-empty state parameter"
    return token, state


# --- POST /auth/magic/start -------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_magic_start_creates_token_and_queues_email(
    magic_link_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
    self_host_schema,
) -> None:
    """Happy path: POST /auth/magic/start with a valid email mints a
    token in the DB, calls SMTP send with the right envelope, and
    returns ``{"status": "queued"}``."""
    client, fake_smtp, base_url = magic_link_client
    response = await client.post("/auth/magic/start", json={"email": "ana@test.com"})
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "queued"}

    # Exactly one SMTP send happened, with the right shape.
    assert len(fake_smtp.sent) == 1
    msg = fake_smtp.sent[0]
    assert msg["to"] == "ana@test.com"
    assert msg["subject"]  # non-empty
    assert f"{base_url}/auth/magic/verify?token=" in msg["body"]

    # Token landed in the DB (verify via the integration conftest).
    rows = self_host_schema.execute_sql("SELECT email FROM magic_link_tokens")
    assert len(rows) == 1
    assert rows[0]["email"] == "ana@test.com"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_magic_start_returns_400_on_missing_email(
    magic_link_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
) -> None:
    client, fake_smtp, _ = magic_link_client
    response = await client.post("/auth/magic/start", json={})
    assert response.status_code == 400
    assert fake_smtp.sent == []  # no token minted, no email sent


@pytest.mark.integration
@pytest.mark.asyncio
async def test_magic_start_returns_400_on_invalid_email_format(
    magic_link_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
) -> None:
    client, fake_smtp, _ = magic_link_client
    response = await client.post(
        "/auth/magic/start", json={"email": "not-an-email"}
    )
    assert response.status_code == 400
    assert fake_smtp.sent == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_magic_start_normalises_email_to_lowercase(
    magic_link_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
    self_host_schema,
) -> None:
    """``ANA@TEST.COM`` must hit the same DB row as ``ana@test.com``."""
    client, fake_smtp, _ = magic_link_client
    response = await client.post(
        "/auth/magic/start", json={"email": "ANA@TEST.COM"}
    )
    assert response.status_code == 200
    rows = self_host_schema.execute_sql("SELECT email FROM magic_link_tokens")
    assert rows[0]["email"] == "ana@test.com"
    # The handler normalises the canonical email before sending the
    # verify envelope, so the SMTP transport receives the lowercase
    # form even though the request body was uppercase.
    assert fake_smtp.sent[0]["to"] == "ana@test.com"


# --- ReDoS-safe email gate (CodeQL py/polynomial-redos, alert #115) ---------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_magic_start_accepts_padded_email_via_strip(
    magic_link_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
) -> None:
    """The caller strips the raw email, so surrounding whitespace is
    still accepted (``.strip()`` behaviour preserved by the gate)."""
    client, fake_smtp, _ = magic_link_client
    response = await client.post(
        "/auth/magic/start", json={"email": "  ana@test.com\t"}
    )
    assert response.status_code == 200, response.text


def test_email_gate_matches_legacy_regex_accept_set() -> None:
    r"""``_looks_like_email`` accepts exactly what the retired
    ``^[^@\s]+@[^@\s]+\.[^@\s]+$`` pattern accepted (fail-closed on
    the unreachable trailing-newline artifact of ``$``)."""
    accepted = [
        "ana@test.com",
        "ñ@galicia.es",  # unicode local part
        "a@b.c.d",  # multi-dot domain
        ".dot@start.local",  # local part may contain dots
        "a@..b",  # [^@\s] admits dots in the domain halves
        "a@b..c",
    ]
    for value in accepted:
        assert magic_link._looks_like_email(value), value

    rejected = [
        "",
        "no-at-sign",
        "a@@b.com",  # multiple @
        "a@b@c.com",  # multiple @
        "a b@c.com",  # whitespace in the local half
        "a@b .com",  # whitespace in the domain half
        "a@bcom",  # missing dot in the domain
        "@b.com",  # empty local part
        "a@",  # empty domain
        "a@.com",  # dot at the domain start
        "a@b.",  # dot at the domain end
        "a@.",  # single-dot domain
        "ana@test.com\n",  # ``$`` artifact: helper is strictly fail-closed
    ]
    for value in rejected:
        assert not magic_link._looks_like_email(value), value


def test_email_gate_rejects_pathological_shapes() -> None:
    """Pathological lengths are rejected on form alone (functional
    assertion only — the gate is O(n), no polynomial backtracking)."""
    assert not magic_link._looks_like_email("a" * 5000 + "@" + "b" * 5000)
    assert not magic_link._looks_like_email("a" * 5000 + "@" + "b" * 5000 + ".")
    assert magic_link._looks_like_email("a" * 5000 + "@" + "b" * 5000 + ".com")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_magic_start_rejects_pathological_email(
    magic_link_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
) -> None:
    """A 5000-char dotless address must still be rejected on shape."""
    client, fake_smtp, _ = magic_link_client
    response = await client.post(
        "/auth/magic/start",
        json={"email": "a" * 5000 + "@" + "b" * 5000},
    )
    assert response.status_code == 400
    assert fake_smtp.sent == []


# --- GET /auth/magic/verify ------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_magic_verify_consumes_token_and_sets_session_cookie(
    magic_link_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
    self_host_schema,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The happy path: start mints a token, verify consumes it, the
    response carries ``apap_session`` with the canonical payload."""
    client, fake_smtp, base_url = magic_link_client
    _seed_active_user(self_host_schema, "ana@test.com")
    # Mint a token via the start endpoint so the test exercises the
    # full path, not a back-door create.
    start = await client.post("/auth/magic/start", json={"email": "ana@test.com"})
    assert start.status_code == 200

    # Extract token AND state explicitly from the recorded SMTP body
    # (JD-B-002: the old split swallowed ``&state=``).
    assert len(fake_smtp.sent) == 1
    token, state = _extract_token_and_state(
        fake_smtp.sent[0]["body"], base_url
    )

    # Fresh context: the start response may have set cookies; clear
    # them so the verify response is the only cookie source. The state
    # cookie is deliberately RE-SENT as an explicit Cookie header: the
    # browser binding requires it, and this test pins the whole
    # binding (URL state + cookie) on the happy path.
    state_cookie = client.cookies.get("apap_magic_state")
    assert state_cookie == state, "start must cookie-bind the URL state"
    client.cookies.clear()
    verify_headers = {"Cookie": f"apap_magic_state={state_cookie}"}
    with caplog.at_level(logging.INFO, logger="app"):
        response = await client.get(
            f"/auth/magic/verify?token={token}&state={state}",
            headers=verify_headers,
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert response.headers["location"] == "/"

    # Judgment-day JD-B-003: a successful verify emits the SAME
    # ``auth.login`` audit event as the OAuth callback
    # (app/core.auth_flow), so magic-link logins land in one stream.
    logins = [r for r in caplog.records if r.msg == "auth.login"]
    assert logins, "expected an auth.login audit event on successful verify"
    caller_fields = getattr(logins[0], "_caller_fields", {})
    # ``email`` is on log_safe's closed PII redaction list: the event
    # must carry the redacted marker, never the raw address.
    assert caller_fields.get("email") == "[REDACTED]"
    assert caller_fields.get("user_id")

    # The cookie has the right flags and a signed payload with the
    # canonical email.
    set_cookie = response.headers.get("set-cookie", "")
    assert "apap_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    # ``SameSite=lax`` is required so cross-site top-level redirects
    # from the email client (Gmail) carry the cookie. Strict was
    # blocking the magic-link flow end-to-end (issue #651, PR #860).
    assert "SameSite=lax" in set_cookie

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
    # ``is_authorized=True`` must be in the cookie payload so the
    # auth layer's ``require_authorized_user`` accepts the first
    # request after the redirect without a DB round-trip. The DB
    # revalidation still runs on subsequent requests.
    assert payload.get("is_authorized") is True
    # Issue #917: the payload now carries the OAuth-parity identity
    # (user_id / rol from the auth_users row) plus the session-bound
    # csrf_token CsrfMiddleware compares against.
    assert payload.get("csrf_token")
    assert payload.get("user_id")
    assert payload.get("rol") == "key_user"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_magic_verify_unknown_email_fails_closed(
    magic_link_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
) -> None:
    """A valid token whose email is NOT an active user must NOT mint a
    session: 302 to /unauthorized, no ``apap_session`` cookie (issue
    #917, fail-closed with the same no-oracle generic redirect)."""
    client, fake_smtp, base_url = magic_link_client
    # NOTE: ana@test.com is NOT seeded in this test.
    await client.post("/auth/magic/start", json={"email": "ana@test.com"})
    token, state = _extract_token_and_state(
        fake_smtp.sent[0]["body"], base_url
    )

    state_cookie = client.cookies.get("apap_magic_state")
    client.cookies.clear()
    response = await client.get(
        f"/auth/magic/verify?token={token}&state={state}",
        headers={"Cookie": f"apap_magic_state={state_cookie}"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/unauthorized"
    assert "apap_session=" not in response.headers.get("set-cookie", "")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_magic_verify_returns_302_to_login_on_invalid_token(
    magic_link_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
) -> None:
    """An unknown token must NOT leak why it failed; we redirect to
    /login with a generic reason.

    The state/cookie gate is deliberately SATISFIED (self-consistent
    garbage state in both the URL and the cookie) so the failure is
    provably the TOKEN gate — the no-oracle redirect is the same either
    way, but this keeps the test honest about what it exercises.
    """
    client, _, _ = magic_link_client
    garbage_state = "A" * 43
    response = await client.get(
        f"/auth/magic/verify?token={'0' * 64}&state={garbage_state}",
        headers={"Cookie": f"apap_magic_state={garbage_state}"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/login" in response.headers["location"]
    assert "reason" in response.headers["location"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_magic_verify_rejects_already_consumed_token(
    magic_link_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
    self_host_schema,
) -> None:
    """One-time use: a second consume of the same token returns the
    same redirect-to-login, never a second session.

    The state/cookie halves are deliberately PRESERVED across both
    requests (state in the URL, cookie via an explicit Cookie header —
    the first verify expired it in the client jar), so the second
    failure is provably the TOKEN gate, not the state gate (JD-B-002).
    """
    client, fake_smtp, base_url = magic_link_client
    _seed_active_user(self_host_schema, "ana@test.com")
    await client.post("/auth/magic/start", json={"email": "ana@test.com"})
    token, state = _extract_token_and_state(
        fake_smtp.sent[0]["body"], base_url
    )
    state_cookie = client.cookies.get("apap_magic_state")
    verify_headers = {"Cookie": f"apap_magic_state={state_cookie}"}

    first = await client.get(
        f"/auth/magic/verify?token={token}&state={state}",
        headers=verify_headers,
        follow_redirects=False,
    )
    assert first.status_code == 302
    assert first.headers["location"] == "/"

    second = await client.get(
        f"/auth/magic/verify?token={token}&state={state}",
        headers=verify_headers,
        follow_redirects=False,
    )
    assert second.status_code == 302
    assert "/login" in second.headers["location"]
    # ``Set-Cookie`` is NOT set the second time — the token was
    # already consumed, no new session is minted.
    assert "apap_session=" not in second.headers.get("set-cookie", "")
