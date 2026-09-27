"""Integration tests: login-CSRF state binding on the magic-link flow
(issue #1004).

``/auth/magic/verify`` is a CSRF-exempt GET that set-cookies the
session (``SameSite=lax``), so a verify URL is a bearer capability:
an attacker holding a verify URL for their OWN account could lure a
victim into visiting it and force the victim's browser into the
attacker's session (login CSRF, JD-B-010 of #917).

The fix binds every issued token to a random single-use ``state``
value minted at ``/auth/magic/start``, stored server-side (in-memory,
same TTL pattern as the token) and embedded in the emailed verify URL.
Verify requires the exact ``state``:

- Missing / wrong / expired / already-used state → the same no-oracle
  ``/login?reason=invalid_or_expired`` redirect, NO session cookie,
  and the token is NOT consumed (a user who clicks a truncated link
  can retry with the full URL).
- The legit link (state included, straight from the email client)
  keeps working with no extra user step.

These tests run against real Postgres (``self_host_schema``) with the
same fake-SMTP harness as ``test_magic_link_routes.py``; the fixture
is imported so both files exercise one harness definition.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx
import pytest

from app.core.local_backend.app import create_app
from tests.integration.test_magic_link_routes import (
    _extract_token_and_state,
    _seed_active_user,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.integration

_USER = "ana@test.com"


@dataclass
class _FakeSMTPTransport:
    """Same in-process fake as ``test_magic_link_routes`` (records sends)."""

    sent: list[dict[str, str]] = field(default_factory=list)

    def send(self, to_addr: str, subject: str, body: str) -> bool:
        self.sent.append({"to": to_addr, "subject": subject, "body": body})
        return True


@pytest.fixture
async def ml_client(
    self_host_schema,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[httpx.AsyncClient, _FakeSMTPTransport, str]]:
    """Stand up the local backend with a fake SMTP transport.

    Same harness shape as ``test_magic_link_routes.magic_link_client``
    (env, lifespan, fake transport, public base URL); duplicated rather
    than imported because a pytest fixture only resolves inside its own
    module and re-wrapping the imported fixture function fails.
    """
    monkeypatch.setenv("APAP_LOCAL_DB_URL", os.environ["APAP_TEST_POSTGRES_DSN"])
    monkeypatch.setenv("APAP_LOCAL_DB_SCHEMA", self_host_schema.schema)
    monkeypatch.setenv("APAP_SESSION_SECRET", "integration-test-secret-64-chars-long-padding-x")
    monkeypatch.setenv(
        "APAP_RAWSQL_AUTH_TOKEN",
        "integration-test-rawsql-token-64-chars-padding-xyz-aaaaaa",
    )

    app = create_app()
    fake_smtp = _FakeSMTPTransport()
    async with app.router.lifespan_context(app):
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


async def _start(client: httpx.AsyncClient, smtp: _FakeSMTPTransport, base_url: str) -> tuple[str, str]:
    """POST /auth/magic/start and return the emailed (token, state)."""
    start = await client.post("/auth/magic/start", json={"email": _USER})
    assert start.status_code == 200, start.text
    assert len(smtp.sent) == 1
    return _extract_token_and_state(smtp.sent[0]["body"], base_url)


# --- start embeds the state ---------------------------------------------------


@pytest.mark.asyncio
async def test_magic_start_embeds_state_in_verify_url(
    ml_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
) -> None:
    """The emailed verify URL must carry a ``state`` query parameter."""
    client, fake_smtp, base_url = ml_client
    token, state = await _start(client, fake_smtp, base_url)

    assert token
    # 256 bits of URL-safe entropy (secrets.token_urlsafe(32) shape).
    assert len(state) >= 32
    assert all(c.isalnum() or c in "-_" for c in state)


@pytest.mark.asyncio
async def test_start_sets_browser_binding_state_cookie(
    ml_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
) -> None:
    """POST /start set-cookies ``apap_magic_state`` in the initiating
    browser: HttpOnly, Secure, SameSite=lax, scoped to /auth/magic and
    with the state-binding TTL as Max-Age (issue #1004 round-1 fix)."""
    client, fake_smtp, base_url = ml_client
    start = await client.post("/auth/magic/start", json={"email": _USER})
    assert start.status_code == 200
    set_cookie = start.headers.get("set-cookie", "")
    assert "apap_magic_state=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Path=/auth/magic" in set_cookie
    assert "Max-Age=1800" in set_cookie
    # The cookie value is the same state that travels in the emailed
    # URL — verify compares them for equality.
    _, state = _extract_token_and_state(fake_smtp.sent[0]["body"], base_url)
    assert client.cookies.get("apap_magic_state") == state


# --- attacker scenario: verify without / with wrong state ---------------------


@pytest.mark.asyncio
async def test_verify_without_state_mints_no_session_and_preserves_token(
    ml_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
    self_host_schema,
) -> None:
    """A verify URL stripped of its ``state`` must NOT mint a session and
    must NOT consume the token — even when the browser presents its
    legitimate state cookie (the URL half of the binding is missing).
    The legit full URL still works afterwards."""
    client, fake_smtp, base_url = ml_client
    _seed_active_user(self_host_schema, _USER)
    token, state = await _start(client, fake_smtp, base_url)

    # The initiating browser keeps its state cookie (set by /start);
    # only the URL half is missing.
    assert client.cookies.get("apap_magic_state") == state
    attack = await client.get(
        f"/auth/magic/verify?token={token}", follow_redirects=False
    )
    assert attack.status_code == 302
    assert attack.headers["location"] == "/login?reason=invalid_or_expired"
    assert "apap_session=" not in attack.headers.get("set-cookie", "")

    # The token was NOT consumed: the legit URL still mints the session.
    legit = await client.get(
        f"/auth/magic/verify?token={token}&state={state}",
        follow_redirects=False,
    )
    assert legit.status_code == 302
    assert legit.headers["location"] == "/"
    assert "apap_session=" in legit.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_verify_with_wrong_state_fails_closed_and_preserves_token(
    ml_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
    self_host_schema,
) -> None:
    """A verify URL with a state that does not match the browser's state
    cookie fails closed with the no-oracle redirect and keeps the
    token usable for the legit link."""
    client, fake_smtp, base_url = ml_client
    _seed_active_user(self_host_schema, _USER)
    token, state = await _start(client, fake_smtp, base_url)

    # The browser presents its real cookie; the URL carries a foreign
    # state. compare_digest must reject the mismatch.
    assert client.cookies.get("apap_magic_state") == state
    attack = await client.get(
        f"/auth/magic/verify?token={token}&state={'A' * 43}",
        follow_redirects=False,
    )
    assert attack.status_code == 302
    assert attack.headers["location"] == "/login?reason=invalid_or_expired"
    assert "apap_session=" not in attack.headers.get("set-cookie", "")

    legit = await client.get(
        f"/auth/magic/verify?token={token}&state={state}",
        follow_redirects=False,
    )
    assert legit.status_code == 302
    assert legit.headers["location"] == "/"
    assert "apap_session=" in legit.headers.get("set-cookie", "")


# --- legit flow ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_with_correct_state_mints_session(
    ml_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
    self_host_schema,
) -> None:
    """The one-click legit flow: the link straight from the email
    (token + state) in the browser that requested it (holding the
    state cookie) mints the session cookie and EXPIRES the state
    cookie (Set-Cookie with Max-Age=0)."""
    client, fake_smtp, base_url = ml_client
    _seed_active_user(self_host_schema, _USER)
    token, state = await _start(client, fake_smtp, base_url)

    response = await client.get(
        f"/auth/magic/verify?token={token}&state={state}",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/"
    set_cookie = response.headers.get("set-cookie", "")
    assert "apap_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    # The spent state cookie is expired in the same response (the
    # delete_cookie header uses ``apap_magic_state=""`` with Max-Age=0;
    # the expires date's comma makes per-attribute parsing brittle, so
    # assert on the whole header).
    assert 'apap_magic_state=""' in set_cookie
    assert "Max-Age=0" in set_cookie


# --- single-use state ----------------------------------------------------------


@pytest.mark.asyncio
async def test_state_is_single_use_replay_fails_closed(
    ml_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
    self_host_schema,
) -> None:
    """A consumed state cannot be replayed: the second verify of the
    same (token, state) pair gets the no-oracle redirect, no cookie.

    Deliberate choice (issue #1004 round-1, task item 3): the state
    cookie captured from /start is RE-SENT explicitly on the second
    request (the successful verify expired it in the browser jar), so
    the replay failure is provably the server-side single-use state
    binding, NOT the missing-cookie gate."""
    client, fake_smtp, base_url = ml_client
    _seed_active_user(self_host_schema, _USER)
    token, state = await _start(client, fake_smtp, base_url)
    state_cookie = client.cookies.get("apap_magic_state")
    assert state_cookie == state
    cookie_header = {"Cookie": f"apap_magic_state={state_cookie}"}

    first = await client.get(
        f"/auth/magic/verify?token={token}&state={state}",
        follow_redirects=False,
    )
    assert first.status_code == 302
    assert first.headers["location"] == "/"

    second = await client.get(
        f"/auth/magic/verify?token={token}&state={state}",
        headers=cookie_header,
        follow_redirects=False,
    )
    assert second.status_code == 302
    assert second.headers["location"] == "/login?reason=invalid_or_expired"
    assert "apap_session=" not in second.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_expired_state_fails_closed(
    ml_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
    self_host_schema,
) -> None:
    """A state past its TTL fails closed even though the token itself
    is still within its TTL. The store entry is expired in place (the
    same TTL shape the port uses for tokens)."""
    client, fake_smtp, base_url = ml_client
    _seed_active_user(self_host_schema, _USER)
    token, state = await _start(client, fake_smtp, base_url)

    # Force-expire the single outstanding state binding.
    app = client._transport.app  # noqa: SLF001 - test seam, same process
    store = app.state._magic_link_states
    assert set(store.keys()) == {state}
    store[state] = store[state]._replace(expires_at=0.0)

    # The browser still presents its state cookie, so the failure is
    # provably the expired server-side binding, not the cookie gate.
    assert client.cookies.get("apap_magic_state") == state
    response = await client.get(
        f"/auth/magic/verify?token={token}&state={state}",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/login?reason=invalid_or_expired"
    assert "apap_session=" not in response.headers.get("set-cookie", "")


# --- AC1: the emailed URL is not a bearer capability across browsers --------


@pytest.fixture
async def ml_two_clients(
    self_host_schema,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[httpx.AsyncClient, httpx.AsyncClient, _FakeSMTPTransport, str]]:
    """One app, two ASGI clients with INDEPENDENT cookie jars.

    Models two distinct browsers: client A (the initiator, which holds
    the ``apap_magic_state`` cookie set by ``/auth/magic/start``) and
    client B (the victim, which only ever sees the URL the attacker
    forwards). Each ``httpx.AsyncClient`` keeps its own cookie jar, so
    this is the exact browser-boundary shape of acceptance criterion 1
    of issue #1004.
    """
    monkeypatch.setenv("APAP_LOCAL_DB_URL", os.environ["APAP_TEST_POSTGRES_DSN"])
    monkeypatch.setenv("APAP_LOCAL_DB_SCHEMA", self_host_schema.schema)
    monkeypatch.setenv("APAP_SESSION_SECRET", "integration-test-secret-64-chars-long-padding-x")
    monkeypatch.setenv(
        "APAP_RAWSQL_AUTH_TOKEN",
        "integration-test-rawsql-token-64-chars-padding-xyz-aaaaaa",
    )

    app = create_app()
    fake_smtp = _FakeSMTPTransport()
    async with app.router.lifespan_context(app):
        app.state.smtp_transport = fake_smtp
        app.state.public_base_url = "https://apap.romancaba.com"
        client_a = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://test"
        )
        client_b = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://test"
        )
        try:
            yield client_a, client_b, fake_smtp, app.state.public_base_url
        finally:
            await client_a.aclose()
            await client_b.aclose()


@pytest.mark.asyncio
async def test_emailed_url_forwarded_to_another_browser_mints_no_session(
    ml_two_clients: tuple[httpx.AsyncClient, httpx.AsyncClient, _FakeSMTPTransport, str],
    self_host_schema,
) -> None:
    """AC1 (issue #1004): the full emailed URL — token AND state — is NOT
    a bearer capability.

    An attacker requests a link for their OWN account and forwards the
    complete URL (both secrets it carries) to the victim. The victim's
    browser (client B) has no ``apap_magic_state`` cookie, so the URL
    must fail closed with NO session minted. The initiator's browser
    (client A), which holds the cookie from ``/auth/magic/start``, can
    still complete the login with the same URL.
    """
    client_a, client_b, fake_smtp, base_url = ml_two_clients
    _seed_active_user(self_host_schema, _USER)

    start = await client_a.post("/auth/magic/start", json={"email": _USER})
    assert start.status_code == 200, start.text
    assert len(fake_smtp.sent) == 1
    token, state = _extract_token_and_state(fake_smtp.sent[0]["body"], base_url)
    full_url = f"/auth/magic/verify?token={token}&state={state}"

    # Victim's browser: has the full URL but not the initiating
    # browser's state cookie. Must get the fail-closed redirect and NO
    # session cookie.
    victim = await client_b.get(full_url, follow_redirects=False)
    assert victim.status_code == 302
    assert victim.headers["location"] == "/login?reason=invalid_or_expired"
    assert "apap_session=" not in victim.headers.get("set-cookie", ""), (
        "client B (no state cookie) must NOT mint a session from the "
        "forwarded full URL — login CSRF is still open"
    )

    # Initiator's browser: same URL, holds the state cookie from the
    # POST that started the flow → session minted.
    initiator = await client_a.get(full_url, follow_redirects=False)
    assert initiator.status_code == 302
    assert initiator.headers["location"] == "/"
    assert "apap_session=" in initiator.headers.get("set-cookie", "")
