"""Integration tests: magic-link session parity on the REAL app (issue #917).

The magic-link login previously minted a session payload with only
``{"email", "is_authorized"}`` — no ``csrf_token``, no ``user_id``, no
``rol``. ``CsrfMiddleware`` compares the posted token against
``payload.get("csrf_token")`` which was ``None``, so EVERY form write
from a magic-link user got 403 for the whole 7-day session. Without
``user_id`` the audit events (``auth.denied``) logged those users as
anonymous and the per-user ``write_user`` rate-limit bucket did not
apply.

These tests run against ``app.main.create_app()`` — the real
application with the full middleware chain (CsrfMiddleware included;
the standalone local-backend app does NOT mount CSRF) — against real
Postgres via ``LocalPostgresExecutor`` provisioned by the real
lifespan. The fixture creates its OWN ephemeral schema so the app's
lifespan provisions every table it owns (usuarios_autorizados,
catalogos, tarea, magic_link_tokens) exactly as in production, without
clashing with the integration conftest's inline catalog provisioning.

E2E exemption (issue #917): the deployed Playwright harness is NOT
mutated by this slice. The write-after-login coverage that an E2E
flow would normally provide is fulfilled here by
``test_magic_link_login_then_authenticated_form_post_succeeds``,
which exercises the same middleware chain (UADetection → auth gate →
CsrfMiddleware → route) with a real Postgres and the real session
cookie jar. A follow-up issue should track migrating this flow into
the E2E harness when the deployed user seeding supports it.

Hard rules (apap-security HR-4/HR-5, apap-testing HR-15):
- POST /auth/magic/start and GET /auth/magic/verify stay CSRF-exempt.
- The session payload must match the OAuth callback contract
  (``app.core.auth_flow`` lines ~258-268): ``issue_csrf_to_session``
  over ``{email, user_id, rol, is_authorized}``.
- Unknown email fails closed: 302 to /unauthorized, no session cookie
  (same generic no-oracle posture as an invalid token).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx
import pytest
from psycopg import sql
from starlette.requests import Request as StarletteRequest

from app.core.local_backend.db import LocalPostgresExecutor
from app.core.rate_limit import _extract_identity
from app.core.session import read_session
from tests.integration.conftest import _require_postgres_dsn

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from app.core.config import Settings


_EMAIL = "magic-real-app@test.com"


# --- fake SMTP transport -----------------------------------------------------


@dataclass
class _FakeSMTPTransport:
    """In-process fake recording ``send`` calls (mirrors integration pattern)."""

    sent: list[dict[str, str]] = field(default_factory=list)

    def send(self, to_addr: str, subject: str, body: str) -> bool:
        self.sent.append({"to": to_addr, "subject": subject, "body": body})
        return True


@dataclass
class _RealAppHarness:
    """Bundle of everything a magic-link real-app test needs."""

    client: httpx.AsyncClient
    smtp: _FakeSMTPTransport
    secret: str
    executor: LocalPostgresExecutor


# --- fixtures / helpers ------------------------------------------------------


@pytest.fixture
async def real_app_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[_RealAppHarness]:
    """Stand up ``app.main.create_app()`` on its own ephemeral schema.

    The REAL lifespan provisions the full schema (schema bootstrap +
    catalogs + domain + SQL migrations) against the ephemeral Postgres,
    exactly like a production cold start. ``APAP_AUTH_CACHE_TTL_SECONDS=0``
    disables the in-process auth cache so the per-request DB
    revalidation observes deactivations immediately (the deactivation
    test relies on it). The SMTP transport is swapped for the fake
    AFTER the lifespan so no real email is sent.
    """
    import psycopg

    dsn = _require_postgres_dsn()
    schema = f"magic_real_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    monkeypatch.setenv("APAP_LOCAL_DB_URL", dsn)
    monkeypatch.setenv("APAP_LOCAL_DB_SCHEMA", schema)
    monkeypatch.setenv(
        "APAP_SESSION_SECRET",
        "integration-test-secret-64-chars-long-padding-x",
    )
    monkeypatch.setenv("APAP_AUTH_CACHE_TTL_SECONDS", "0")

    from app.main import create_app

    app = create_app()
    fake_smtp = _FakeSMTPTransport()
    try:
        async with app.router.lifespan_context(app):
            app.state.smtp_transport = fake_smtp
            app.state.public_base_url = "https://apap.romancaba.com"
            client = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                # https so httpx's cookie jar stores and replays the
                # ``Secure`` session cookie like a real browser would.
                base_url="https://testserver",
                follow_redirects=False,
            )
            try:
                executor: LocalPostgresExecutor = app.state.sql_executor
                yield _RealAppHarness(
                    client=client,
                    smtp=fake_smtp,
                    secret=app.state.session_secret,
                    executor=executor,
                )
            finally:
                await client.aclose()
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema)
                )
            )


def _seed_user(executor: LocalPostgresExecutor, email: str, rol: str) -> str:
    """Insert an active user and return the DB-minted ``id`` (UUID)."""
    rows = executor.execute_sql(
        "INSERT INTO usuarios_autorizados (email, rol, activo) "
        "VALUES ($1, $2, true) RETURNING id",
        [email, rol],
    )
    assert len(rows) == 1
    return str(rows[0]["id"])


async def _magic_link_login(
    harness: _RealAppHarness,
    email: str,
) -> httpx.Response:
    """Run start → extract token from the SMTP body → GET verify."""
    start = await harness.client.post("/auth/magic/start", json={"email": email})
    assert start.status_code == 200, start.text
    assert len(harness.smtp.sent) == 1
    body = harness.smtp.sent[0]["body"]
    prefix = "https://apap.romancaba.com/auth/magic/verify?token="
    assert prefix in body
    token = body.split(prefix, 1)[1].split()[0]
    harness.client.cookies.clear()
    return await harness.client.get(f"/auth/magic/verify?token={token}")


def _session_cookie(harness: _RealAppHarness) -> dict[str, object]:
    """Decode the session cookie the client currently carries."""
    cookie = harness.client.cookies.get("apap_session")
    assert cookie is not None, "no apap_session cookie on the client"
    payload = read_session(cookie, secret=harness.secret)
    assert payload is not None, "apap_session cookie did not decode"
    return payload


# --- the RED→GREEN contract tests --------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_magic_link_login_then_authenticated_form_post_succeeds(
    real_app_harness: _RealAppHarness,
) -> None:
    """After a magic-link login, an authenticated form POST carrying the
    session cookie + the ``csrf_token`` issued to that session must reach
    the route (redirect), NOT be rejected with 403 by
    ``CsrfMiddleware`` (issue #917, finding A-05)."""
    harness = real_app_harness
    user_id = _seed_user(harness.executor, _EMAIL, "key_user")

    verify = await _magic_link_login(harness, _EMAIL)
    assert verify.status_code == 302
    assert verify.headers["location"] == "/"

    payload = _session_cookie(harness)
    csrf_token = payload.get("csrf_token")
    # issue #917 RED: pre-fix the payload carries NO csrf_token, so the
    # POST below is rejected 403 by CsrfMiddleware (missing_session).
    # Authenticated form POST (hidden csrf_token field, like the real
    # templates render). POST /tareas is require_authorized_user-guarded
    # and redirects back to the list on success.
    response = await harness.client.post(
        "/tareas",
        data={"tipo": "manual", "csrf_token": csrf_token or ""},
    )
    assert response.status_code == 302, (
        f"expected 302 redirect to /tareas, got {response.status_code}: "
        f"{response.text!r}"
    )
    assert response.headers["location"] == "/tareas"

    # Post-fix guard: the session must actually carry a token for
    # CsrfMiddleware to have accepted the POST above.
    assert isinstance(csrf_token, str) and csrf_token

    # The write really landed in Postgres under the real session identity.
    rows = harness.executor.execute_sql("SELECT tipo FROM tarea")
    assert len(rows) == 1
    assert rows[0]["tipo"] == "manual"

    # user_id is bound for the audit trail / rate-limit bucket (below).
    assert payload.get("user_id") == user_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_magic_link_session_payload_matches_oauth_contract(
    real_app_harness: _RealAppHarness,
) -> None:
    """Shared contract: the magic-link session payload carries the SAME
    keys as the OAuth callback session (app/core/auth_flow.py ~258-268:
    ``issue_csrf_to_session({email, rol, user_id, is_authorized})``)."""
    harness = real_app_harness
    _seed_user(harness.executor, _EMAIL, "key_user")

    verify = await _magic_link_login(harness, _EMAIL)
    assert verify.status_code == 302

    payload = _session_cookie(harness)
    assert set(payload.keys()) == {
        "email",
        "user_id",
        "rol",
        "is_authorized",
        "csrf_token",
    }
    assert payload["email"] == _EMAIL
    assert payload["is_authorized"] is True
    assert payload["rol"] == "key_user"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_magic_link_verify_unknown_email_fails_closed(
    real_app_harness: _RealAppHarness,
) -> None:
    """A valid token whose email is NOT in ``usuarios_autorizados`` must
    NOT mint a session: 302 to /unauthorized, no ``apap_session`` cookie.
    Fail-closed, generic redirect (no oracle about WHY)."""
    harness = real_app_harness
    # NOTE: _EMAIL is never seeded in this test.
    verify = await _magic_link_login(harness, _EMAIL)
    assert verify.status_code == 302
    assert verify.headers["location"] == "/unauthorized"
    assert "apap_session=" not in verify.headers.get("set-cookie", "")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_magic_link_verify_inactive_user_fails_closed(
    real_app_harness: _RealAppHarness,
) -> None:
    """A DEACTIVATED user (``activo = false``) must NOT get a session.

    Judgment-day JD-B-005: pins the ``activo = true`` predicate in
    ``GET_USER_BY_EMAIL_SQL`` (``app/core/local_backend/auth_queries.py``).
    The row EXISTS in ``usuarios_autorizados`` — only the ``activo``
    flag differs — so a regression that drops the predicate from the
    SELECT flips this atom red (a cookie would be minted for a
    deactivated user). Fail-closed contract identical to the
    unknown-email case: 302 to /unauthorized, no ``apap_session``
    cookie; with no session the browser's next hop lands on /login via
    the auth gate.
    """
    harness = real_app_harness
    harness.executor.execute_sql(
        "INSERT INTO usuarios_autorizados (email, rol, activo) "
        "VALUES ($1, 'key_user', false)",
        [_EMAIL],
    )

    verify = await _magic_link_login(harness, _EMAIL)
    assert verify.status_code == 302
    assert verify.headers["location"] == "/unauthorized"
    assert "apap_session=" not in verify.headers.get("set-cookie", "")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_auth_denied_event_carries_real_user_id(
    real_app_harness: _RealAppHarness,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A deactivated magic-link user hitting a protected route triggers
    the ``auth.denied`` audit event WITH the real DB ``user_id`` (not
    ``None`` / anonymous) — the session payload now carries it."""
    harness = real_app_harness
    user_id = _seed_user(harness.executor, _EMAIL, "key_user")

    verify = await _magic_link_login(harness, _EMAIL)
    assert verify.status_code == 302

    # Deactivate AFTER the session was minted; auth cache TTL is 0 so
    # the per-request revalidation sees it immediately.
    harness.executor.execute_sql(
        "UPDATE usuarios_autorizados SET activo = false WHERE email = $1",
        [_EMAIL],
    )

    with caplog.at_level(logging.INFO, logger="app"):
        await harness.client.get("/tareas")

    # NOTE: the audit event is the contract under test here. The
    # redirect propagation from ``require_authorized_user`` in the
    # GET /tareas handler is a pre-existing, out-of-scope gap (the
    # handler renders without ``return_early_if_response``) — it is
    # NOT part of issue #917.
    denied = [r for r in caplog.records if r.msg == "auth.denied"]
    assert denied, "expected an auth.denied audit event"
    caller_fields = getattr(denied[0], "_caller_fields", {})
    assert caller_fields.get("user_id") == user_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rate_limit_write_user_bucket_indexes_by_session_user_id(
    real_app_harness: _RealAppHarness,
) -> None:
    """The ``write_user`` rate-limit bucket keys on the ``user_id`` from
    the signed session cookie (``_extract_identity`` feeds the bucket
    key in ``RateLimitMiddleware``). A magic-link session must resolve
    the real DB user id — not ``None`` (anonymous / IP-only bucket)."""
    harness = real_app_harness
    user_id = _seed_user(harness.executor, _EMAIL, "key_user")

    verify = await _magic_link_login(harness, _EMAIL)
    assert verify.status_code == 302

    session_cookie = harness.client.cookies.get("apap_session")
    assert session_cookie is not None
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": "POST",
        "path": "/tareas",
        "query_string": b"",
        "headers": [(b"cookie", f"apap_session={session_cookie}".encode())],
        "client": ("10.0.0.1", 12345),
    }
    request = StarletteRequest(scope)

    from app.core.config import get_settings

    settings: Settings = get_settings()
    identity = _extract_identity(request, settings)
    assert identity.user_id == user_id
