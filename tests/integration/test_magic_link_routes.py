"""Integration tests for the M1 magic-link routes (F2 acceptance).

The seven atoms below cover the F2 contract (acceptance scenarios AS1,
AS2, AS3, AS4, AS5, AS6, AS8). The setup wires a fresh FastAPI app
with only the magic-router included and the three app.state attributes
the F3 lifespan will own (magic_link_port / mail_transport /
auth_port). The auth_port is an in-memory stub -- it only needs the
get_user_by_email method the route calls; the rest of the Protocol
is left as NotImplementedError stubs that no route ever invokes.

Cookie compat (T2.5): AS3 decodes the apap_session cookie with
app.core.session.read_session and asserts the payload carries the four
keys the OAuth callback writes (email, rol, user_id, is_authorized).
The sign+verify uses the same itsdangerous URLSafeTimedSerializer
already used by /auth/callback -- NO new cookie name, NO new signing.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.core import config as config_module
from app.core.auth_magic.mail_transports import ConsoleMailTransport
from app.core.auth_magic.postgres_adapter import PostgresMagicLinkAdapter
from app.core.auth_magic.routes import router as magic_router
from app.core.domain.auth.user import AuthorizedUser
from app.core.roles import Rol
from app.core.session import read_session
from tests.integration.conftest import _EphemeralPostgres

pytestmark = pytest.mark.integration


# F2: HTTP route handlers (POST /auth/magic/start, GET/POST /auth/magic/verify)
# ---------------------------------------------------------------------------
#
# The seven atoms below cover the F2 contract (acceptance scenarios AS1,
# AS2, AS3, AS4, AS5, AS6, AS8). The setup wires a fresh FastAPI app
# with only the magic-router included and the three app.state attributes
# the F3 lifespan will own (``magic_link_port`` / ``mail_transport`` /
# ``auth_port``). The auth_port is an in-memory stub — it only needs the
# ``get_user_by_email`` method the route calls; the rest of the Protocol
# is left as ``NotImplementedError`` stubs that no route ever invokes.
#
# Cookie compat (T2.5): AS3 decodes the ``apap_session`` cookie with
# :func:`app.core.session.read_session` and asserts the payload carries
# the four keys the OAuth callback writes (``email``, ``rol``,
# ``user_id``, ``is_authorized``) plus the ``csrf_token`` injected by
# :func:`app.core.csrf.issue_csrf_to_session`.


class _StubAuthPort:
    """In-memory :class:`AuthUsersPort` for F2 route tests.

    The route layer only calls :meth:`get_user_by_email`. The other
    Protocol methods raise ``NotImplementedError`` so an accidental
    call surfaces as a clear error instead of a silent no-op (mirrors
    the ``_RecordingAuthPort`` shape in ``tests/test_oauth_slice.py``).
    """

    def __init__(self) -> None:
        self._users: dict[str, AuthorizedUser] = {}
        self.get_user_by_email_calls: list[str] = []

    def add(self, email: str, rol: Rol = Rol.DEVELOPER) -> AuthorizedUser:
        """Seed an active user with a deterministic UUID."""
        user = AuthorizedUser(
            id=f"u-{len(self._users) + 1}",
            email=email,
            rol=rol,
            active=True,
            added_by=None,
            added_at=None,
        )
        self._users[email] = user
        return user

    def get_user_by_email(self, email: str) -> AuthorizedUser | None:
        self.get_user_by_email_calls.append(email)
        return self._users.get(email)

    # --- unused port methods (no-op stubs) ------------------------------

    def ensure_schema_and_seed(self, initial_admin_email: str) -> None:  # noqa: ARG002
        raise NotImplementedError

    def check_email_taken(self, email: str) -> bool:  # noqa: ARG002
        raise NotImplementedError

    def list_authorized_users(self) -> list[AuthorizedUser]:
        raise NotImplementedError

    def add_authorized_user(  # noqa: PLR0913
        self,
        email: str,
        rol: Rol,
        added_by: str,
    ) -> AuthorizedUser:
        raise NotImplementedError

    def get_user_by_id(self, user_id: str) -> AuthorizedUser | None:  # noqa: ARG002
        raise NotImplementedError

    def deactivate_authorized_user(self, user_id: str) -> AuthorizedUser:  # noqa: ARG002
        raise NotImplementedError


def _build_magic_test_app(
    *,
    dsn: str,
    schema: str,
    mailbox_path: Path,
    auth_port: _StubAuthPort,
) -> tuple[FastAPI, PostgresMagicLinkAdapter]:
    """Build a minimal FastAPI app with only the magic-router registered.

    Returns the app and the :class:`PostgresMagicLinkAdapter` it
    references (returned so tests can introspect the DSN / transport
    wiring). The :class:`ConsoleMailTransport` is passed to the adapter
    constructor AND attached to ``app.state.mail_transport`` (the F3
    lifespan owns both — F2 only asserts the wiring shape).
    """
    test_app = FastAPI()
    test_app.include_router(magic_router)
    mail_transport = ConsoleMailTransport(mailbox_path=mailbox_path)
    magic_link_port = PostgresMagicLinkAdapter(
        dsn,
        search_path=schema,
        transport=mail_transport,
    )
    test_app.state.magic_link_port = magic_link_port
    test_app.state.mail_transport = mail_transport
    test_app.state.auth_port = auth_port
    return test_app, magic_link_port


def _mailbox_lines(mailbox_path: Path) -> list[dict[str, object]]:
    """Return the JSONL lines from ``mailbox_path`` as parsed dicts.

    Returns an empty list when the file does not exist (the console
    transport creates the parent directory but never the file until the
    first send, so AS2 + AS6 must tolerate a missing file).
    """
    if not mailbox_path.exists():
        return []
    return [json.loads(line) for line in mailbox_path.read_text(encoding="utf-8").splitlines() if line]


# ---------------------------------------------------------------------------
# AS1: authorised email persists row and emails transport
# ---------------------------------------------------------------------------


async def test_as1_authorized_email_persists_row_and_emails_transport(
    ephemeral_postgres: _EphemeralPostgres,
    tmp_path: Path,
) -> None:
    """AS1: POST /auth/magic/start for an authorised user persists + emails."""
    mailbox_path = tmp_path / "mailbox.jsonl"
    auth_port = _StubAuthPort()
    auth_port.add("a@apap.local")
    test_app, _ = _build_magic_test_app(
        dsn=ephemeral_postgres.dsn,
        schema=ephemeral_postgres.schema,
        mailbox_path=mailbox_path,
        auth_port=auth_port,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/auth/magic/start", json={"email": "a@apap.local"}
        )

    # Response shape: constant-time 200 + queued regardless of branch.
    assert response.status_code == 200
    assert response.json() == {"status": "queued"}

    # Row persisted in the database.
    rows = ephemeral_postgres.execute(
        "SELECT email, consumed_at FROM magic_link_tokens"
    )
    assert len(rows) == 1
    assert rows[0]["email"] == "a@apap.local"
    assert rows[0]["consumed_at"] is None

    # Transport observed the send with a non-empty verify_url.
    lines = _mailbox_lines(mailbox_path)
    assert len(lines) == 1
    assert lines[0]["email"] == "a@apap.local"
    assert isinstance(lines[0]["verify_url"], str)
    assert "/auth/magic/verify?token=" in lines[0]["verify_url"]


# ---------------------------------------------------------------------------
# AS2: unknown email returns 200 without persisting
# ---------------------------------------------------------------------------


async def test_as2_unknown_email_returns_200_without_persisting(
    ephemeral_postgres: _EphemeralPostgres,
    tmp_path: Path,
) -> None:
    """AS2: POST /auth/magic/start for an unknown email is a no-op."""
    mailbox_path = tmp_path / "mailbox.jsonl"
    auth_port = _StubAuthPort()  # empty: no user added
    test_app, _ = _build_magic_test_app(
        dsn=ephemeral_postgres.dsn,
        schema=ephemeral_postgres.schema,
        mailbox_path=mailbox_path,
        auth_port=auth_port,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/auth/magic/start", json={"email": "nope@apap.local"}
        )

    assert response.status_code == 200
    assert response.json() == {"status": "queued"}

    # No row, no mail — the route must not have touched the DB or the
    # transport for an unknown email (constant-time includes no I/O on
    # the negative path).
    rows = ephemeral_postgres.execute(
        "SELECT email FROM magic_link_tokens"
    )
    assert rows == []
    assert _mailbox_lines(mailbox_path) == []


# ---------------------------------------------------------------------------
# AS3: consuming a valid token issues a session cookie
# ---------------------------------------------------------------------------


async def test_as3_consume_valid_token_issues_session_cookie(
    ephemeral_postgres: _EphemeralPostgres,
    tmp_path: Path,
) -> None:
    """AS3: GET /auth/magic/verify sets an ``apap_session`` cookie.

    The cookie is decoded with :func:`app.core.session.read_session`
    (the same helper the OAuth callback uses to read its own cookie)
    and asserted to carry the four OAuth-callback keys plus the CSRF
    token injected by :func:`app.core.csrf.issue_csrf_to_session`.
    That is the byte-compat contract (T2.5).
    """
    mailbox_path = tmp_path / "mailbox.jsonl"
    auth_port = _StubAuthPort()
    auth_port.add("a@apap.local", rol=Rol.DEVELOPER)
    test_app, _ = _build_magic_test_app(
        dsn=ephemeral_postgres.dsn,
        schema=ephemeral_postgres.schema,
        mailbox_path=mailbox_path,
        auth_port=auth_port,
    )

    settings = config_module.get_settings()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        # Drive the request.
        start_response = await client.post(
            "/auth/magic/start", json={"email": "a@apap.local"}
        )
        assert start_response.status_code == 200

        # Extract the raw_token the transport captured.
        lines = _mailbox_lines(mailbox_path)
        raw_token = lines[0]["raw_token"]
        assert isinstance(raw_token, str) and raw_token

        # Drive the verify GET.
        verify_response = await client.get(
            "/auth/magic/verify", params={"token": raw_token}
        )

    # The success path is a 302 to ``/`` with the session cookie set.
    assert verify_response.status_code == 302
    assert verify_response.headers["location"] == "/"
    set_cookie = verify_response.headers["set-cookie"]
    assert "apap_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert "Path=/" in set_cookie

    # Decode the cookie value with the SAME helper the OAuth callback
    # relies on — proves the magic-link cookie is byte-compat with the
    # cookie-shape the rest of the app expects.
    cookie_value = set_cookie.split("apap_session=", 1)[1].split(";", 1)[0]
    payload = read_session(cookie_value, secret=settings.session_secret)
    assert payload is not None
    assert payload["email"] == "a@apap.local"
    assert payload["rol"] == "developer"
    assert payload["user_id"] == "u-1"
    assert payload["is_authorized"] is True
    assert isinstance(payload["csrf_token"], str) and payload["csrf_token"]

    # The consumed_at must now be set (the row went from open to closed).
    rows = ephemeral_postgres.execute(
        "SELECT consumed_at FROM magic_link_tokens"
    )
    assert len(rows) == 1
    assert rows[0]["consumed_at"] is not None


# ---------------------------------------------------------------------------
# AS4: consuming the same token twice redirects to /login
# ---------------------------------------------------------------------------


async def test_as4_consume_same_token_twice_returns_302_to_login(
    ephemeral_postgres: _EphemeralPostgres,
    tmp_path: Path,
) -> None:
    """AS4: replaying a consumed token returns 302 ``/login`` (no cookie)."""
    mailbox_path = tmp_path / "mailbox.jsonl"
    auth_port = _StubAuthPort()
    auth_port.add("a@apap.local")
    test_app, _ = _build_magic_test_app(
        dsn=ephemeral_postgres.dsn,
        schema=ephemeral_postgres.schema,
        mailbox_path=mailbox_path,
        auth_port=auth_port,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        await client.post("/auth/magic/start", json={"email": "a@apap.local"})
        raw_token = _mailbox_lines(mailbox_path)[0]["raw_token"]

        # First consume: succeeds, sets the cookie.
        first = await client.get(
            "/auth/magic/verify", params={"token": raw_token}
        )
        assert first.status_code == 302
        assert "apap_session=" in first.headers["set-cookie"]

        # Second consume (same token): must NOT issue a session cookie.
        second = await client.get(
            "/auth/magic/verify", params={"token": raw_token}
        )

    assert second.status_code == 302
    assert second.headers["location"] == "/login"
    # A redirect that does NOT set ``apap_session`` — the spec R5 contract
    # ("On any error path the endpoint MUST NOT issue a session cookie").
    set_cookie_header = second.headers.get("set-cookie", "")
    assert "apap_session=" not in set_cookie_header


# ---------------------------------------------------------------------------
# AS5: expired tokens redirect to /login
# ---------------------------------------------------------------------------


async def test_as5_consume_expired_token_returns_302_to_login(
    ephemeral_postgres: _EphemeralPostgres,
    tmp_path: Path,
) -> None:
    """AS5: GET /auth/magic/verify with an expired token redirects to /login.

    The token is minted via the F1 adapter with ``ttl_seconds=0`` so the
    row's ``expires_at`` equals ``requested_at`` (server ``now()``).
    The consume query requires ``expires_at > now()`` so the call
    returns ``None`` immediately — exactly the same shape as the F1
    ``test_consume_magic_link_returns_none_after_expiry`` atom.
    """
    mailbox_path = tmp_path / "mailbox.jsonl"
    auth_port = _StubAuthPort()
    auth_port.add("a@apap.local")
    test_app, magic_link_port = _build_magic_test_app(
        dsn=ephemeral_postgres.dsn,
        schema=ephemeral_postgres.schema,
        mailbox_path=mailbox_path,
        auth_port=auth_port,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        # Mint an already-expired token directly via the adapter (the
        # route always uses ``ttl_seconds=86400``; for AS5 we exercise
        # the consume path with a row whose ``expires_at = now()``).
        request = await magic_link_port.request_magic_link(
            "a@apap.local", ttl_seconds=0
        )
        # Sanity: the row is in the table.
        rows = ephemeral_postgres.execute(
            "SELECT expires_at, consumed_at FROM magic_link_tokens "
            "WHERE token_hash = %s",
            [request.token_hash],
        )
        assert len(rows) == 1
        assert rows[0]["consumed_at"] is None

        response = await client.get(
            "/auth/magic/verify",
            params={"token": request.transport_payload["raw_token"]},
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/login"
    assert "apap_session=" not in response.headers.get("set-cookie", "")


# ---------------------------------------------------------------------------
# AS6: feature flag off makes endpoints no-op
# ---------------------------------------------------------------------------


async def test_as6_feature_flag_off_makes_endpoints_noop(
    ephemeral_postgres: _EphemeralPostgres,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AS6: ``APAP_AUTH_ENABLE_MAGIC_LINK=0`` short-circuits both endpoints."""
    mailbox_path = tmp_path / "mailbox.jsonl"
    auth_port = _StubAuthPort()
    auth_port.add("a@apap.local")
    test_app, _ = _build_magic_test_app(
        dsn=ephemeral_postgres.dsn,
        schema=ephemeral_postgres.schema,
        mailbox_path=mailbox_path,
        auth_port=auth_port,
    )

    monkeypatch.setenv("APAP_AUTH_ENABLE_MAGIC_LINK", "0")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        # Start endpoint: 200 queued, no DB write, no transport call.
        start_response = await client.post(
            "/auth/magic/start", json={"email": "a@apap.local"}
        )
        assert start_response.status_code == 200
        assert start_response.json() == {"status": "queued"}

        # Verify endpoint: 302 to /login with no session cookie.
        verify_response = await client.get(
            "/auth/magic/verify", params={"token": "anything"}
        )

    assert verify_response.status_code == 302
    assert verify_response.headers["location"] == "/login"
    assert "apap_session=" not in verify_response.headers.get("set-cookie", "")

    # No row, no mail — the route MUST short-circuit before any I/O.
    rows = ephemeral_postgres.execute(
        "SELECT email FROM magic_link_tokens"
    )
    assert rows == []
    assert _mailbox_lines(mailbox_path) == []


# ---------------------------------------------------------------------------
# AS8: constant-time response on unknown email
# ---------------------------------------------------------------------------


async def test_as8_unknown_email_response_time_within_50ms_of_known(
    ephemeral_postgres: _EphemeralPostgres,
    tmp_path: Path,
) -> None:
    """AS8: the timing delta between known + unknown emails is <=50ms.

    Both paths run back-to-back under the same ephemeral Postgres
    schema so any DB-side variance is shared. The known path is
    typically SLOWER (mail transport + DB write); the spec requires the
    delta to be at most 50ms because the unknown path pads to a 50ms
    floor.
    """
    mailbox_path = tmp_path / "mailbox.jsonl"
    auth_port = _StubAuthPort()
    auth_port.add("realuser@apap.local")
    test_app, _ = _build_magic_test_app(
        dsn=ephemeral_postgres.dsn,
        schema=ephemeral_postgres.schema,
        mailbox_path=mailbox_path,
        auth_port=auth_port,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        # Warm-up: drive one request first so the first DB connection
        # setup cost doesn't leak into the timing measurement.
        await client.post(
            "/auth/magic/start", json={"email": "realuser@apap.local"}
        )

        # Time the known path.
        t0 = time.monotonic()
        known = await client.post(
            "/auth/magic/start", json={"email": "realuser@apap.local"}
        )
        known_elapsed = time.monotonic() - t0

        # Time the unknown path.
        t0 = time.monotonic()
        unknown = await client.post(
            "/auth/magic/start", json={"email": "nope@apap.local"}
        )
        unknown_elapsed = time.monotonic() - t0

    assert known.status_code == 200
    assert unknown.status_code == 200

    # Both paths must be at least 50ms (the route pads the unknown path
    # to the floor; the known path pays for the DB write + transport
    # call which usually exceeds the floor).
    assert known_elapsed >= 0.045, (
        f"known path completed in {known_elapsed * 1000:.1f}ms -- expected >=45ms"
    )
    assert unknown_elapsed >= 0.045, (
        f"unknown path completed in {unknown_elapsed * 1000:.1f}ms -- "
        "constant-time padding missing"
    )
    # The spec contract: the difference between the two is <=50ms.
    delta_ms = abs(known_elapsed - unknown_elapsed) * 1000
    assert delta_ms <= 50.0, (
        f"timing delta {delta_ms:.1f}ms exceeds the 50ms budget "
        f"(known={known_elapsed * 1000:.1f}ms, unknown={unknown_elapsed * 1000:.1f}ms)"
    )
