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
from tests.integration.test_magic_link_routes import _seed_active_user

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
            base_url="http://test",
        )
        try:
            yield client, fake_smtp, app.state.public_base_url
        finally:
            await client.aclose()

_USER = "ana@test.com"


def _extract_token_and_state(body: str, base_url: str) -> tuple[str, str]:
    """Parse ``(token, state)`` from the emailed verify URL.

    Fails the test when the link does not carry the ``state`` query
    parameter — the parameter IS the fix under test.
    """
    prefix = f"{base_url}/auth/magic/verify?token="
    assert prefix in body, "email body must contain the verify URL"
    query = body.split(prefix, 1)[1].split()[0]
    token, sep, state = query.partition("&state=")
    assert sep and state, "verify URL must carry a non-empty state parameter"
    return token, state


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


# --- attacker scenario: verify without / with wrong state ---------------------


@pytest.mark.asyncio
async def test_verify_without_state_mints_no_session_and_preserves_token(
    ml_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
    self_host_schema,
) -> None:
    """A verify URL stripped of its ``state`` (the attacker-crafted
    shape) must NOT mint a session and must NOT consume the token —
    the legit URL with the correct state still works afterwards."""
    client, fake_smtp, base_url = ml_client
    _seed_active_user(self_host_schema, _USER)
    token, state = await _start(client, fake_smtp, base_url)

    client.cookies.clear()
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
    """A verify URL with a mismatched state fails closed with the
    no-oracle redirect and keeps the token usable for the legit link."""
    client, fake_smtp, base_url = ml_client
    _seed_active_user(self_host_schema, _USER)
    token, state = await _start(client, fake_smtp, base_url)

    client.cookies.clear()
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
    (token + state) still mints the session cookie."""
    client, fake_smtp, base_url = ml_client
    _seed_active_user(self_host_schema, _USER)
    token, state = await _start(client, fake_smtp, base_url)

    client.cookies.clear()
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


# --- single-use state ----------------------------------------------------------


@pytest.mark.asyncio
async def test_state_is_single_use_replay_fails_closed(
    ml_client: tuple[httpx.AsyncClient, _FakeSMTPTransport, str],
    self_host_schema,
) -> None:
    """A consumed state cannot be replayed: the second verify of the
    same (token, state) pair gets the no-oracle redirect, no cookie."""
    client, fake_smtp, base_url = ml_client
    _seed_active_user(self_host_schema, _USER)
    token, state = await _start(client, fake_smtp, base_url)

    client.cookies.clear()
    first = await client.get(
        f"/auth/magic/verify?token={token}&state={state}",
        follow_redirects=False,
    )
    assert first.status_code == 302
    assert first.headers["location"] == "/"

    second = await client.get(
        f"/auth/magic/verify?token={token}&state={state}",
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

    client.cookies.clear()
    response = await client.get(
        f"/auth/magic/verify?token={token}&state={state}",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/login?reason=invalid_or_expired"
    assert "apap_session=" not in response.headers.get("set-cookie", "")
