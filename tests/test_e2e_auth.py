"""Tests for the E2E OAuth mock route (issue #598).

The mock is registered only when ``Settings.e2e_auth_enabled`` is True;
the production code path keeps returning 503 from ``/login`` and
``/auth/google`` because the route is conditional. These tests
exercise the conditional behaviour and the gated route itself.

The in-process auth cache (``app.core.auth_cache.set_cached_auth``) is
asserted to be pre-populated by the mock — that's what lets the very
next request from the same browser context pass
``require_authorized_user`` without a DB round-trip.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth_cache import (
    get_cached_auth,
    invalidate_all,
)
from app.core.config import (
    Settings,
    get_settings,
)
from app.core.e2e_auth import (
    MOCK_USER_ID,
    MOCK_USER_ROL,
    register_e2e_auth_routes,
)
from app.core.session import (
    read_session,
    session_cookie_name,
)


@pytest.fixture(autouse=True)
def _clean_auth_cache() -> None:
    """Wipe the in-process cache around each test so order does not leak."""
    invalidate_all()
    yield
    invalidate_all()


@pytest.fixture(autouse=True)
def _restore_e2e_get_settings() -> Iterator[None]:
    """Restore the ``e2e_auth.get_settings`` test seam after every test.

    Several tests below replace ``e2e_module.get_settings`` with a lambda
    and never restore it, so the replacement leaked into any later test
    that reads the real settings (issue #904: the composition-level 404
    test saw the flag enabled because of this leak).
    """
    import app.core.e2e_auth as e2e_module

    original = e2e_module.get_settings
    yield
    e2e_module.get_settings = original


def _build_app_disabled() -> FastAPI:
    """Build a FastAPI app with the mock route NOT registered."""


def _build_app_disabled() -> FastAPI:
    """Build a FastAPI app with the mock route NOT registered."""
    # ``register_e2e_auth_routes`` returns early when
    # ``Settings.e2e_auth_enabled`` is False. To exercise that
    # branch without coupling the test to the global settings
    # cache, we patch ``get_settings`` for the duration of the
    # registration call.
    import app.core.e2e_auth as e2e_module

    original = e2e_module.get_settings
    e2e_module.get_settings = lambda: Settings(
        e2e_auth_enabled=False,
    )
    try:
        app = FastAPI()
        register_e2e_auth_routes(app)
        return app
    finally:
        e2e_module.get_settings = original


def test_route_not_registered_when_disabled() -> None:
    """When ``Settings.e2e_auth_enabled`` is False the route is absent."""
    app = _build_app_disabled()
    client = TestClient(app)

    # ``POST /e2e/login`` is not registered → 404 (FastAPI default).
    # ``GET /e2e/login`` is also 404 — only POST was registered.
    response = client.get("/e2e/login")

    assert response.status_code == 404


def test_route_returns_503_when_secret_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Misconfiguration (enabled=True but secret empty) yields 503.

    The route is registered (the env-var is True) but the secret is
    empty — a configuration mistake that must NOT silently grant
    access. The contract: refuse every request, log loudly in the
    response detail.
    """
    import app.core.e2e_auth as e2e_module

    e2e_module.get_settings = lambda: Settings(
        e2e_auth_enabled=True,
        e2e_auth_secret="",
    )
    app = FastAPI()
    register_e2e_auth_routes(app)
    client = TestClient(app)

    response = client.get(
        "/e2e/login",
        headers={"X-E2E-Secret": "anything"},
    )

    assert response.status_code == 503
    assert "e2e_auth_secret is empty" in response.json()["detail"]


def test_route_rejects_missing_secret_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``X-E2E-Secret`` header is mandatory — missing it returns 401."""
    import app.core.e2e_auth as e2e_module

    e2e_module.get_settings = lambda: Settings(
        e2e_auth_enabled=True,
        e2e_auth_secret="test-secret",
    )
    app = FastAPI()
    register_e2e_auth_routes(app)
    client = TestClient(app)

    response = client.get("/e2e/login")

    assert response.status_code == 401
    assert "missing or invalid" in response.json()["detail"]


def test_route_rejects_wrong_secret_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wrong ``X-E2E-Secret`` value is rejected (constant-time compare)."""
    import app.core.e2e_auth as e2e_module

    e2e_module.get_settings = lambda: Settings(
        e2e_auth_enabled=True,
        e2e_auth_secret="test-secret",
    )
    app = FastAPI()
    register_e2e_auth_routes(app)
    client = TestClient(app)

    response = client.get(
        "/e2e/login",
        headers={"X-E2e-Secret": "wrong-secret"},
    )

    assert response.status_code == 401


def test_happy_path_mints_session_and_prepopulates_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid secret + email mints a session cookie AND pre-populates the cache.

    The two halves of the contract: the cookie has the OAuth-shaped
    payload (so the same middleware paths accept it), and the
    in-process auth cache is warm so the very next request from the
    test client is authorised without a DB round-trip.
    """
    import app.core.e2e_auth as e2e_module

    e2e_module.get_settings = lambda: Settings(
        e2e_auth_enabled=True,
        e2e_auth_secret="test-secret",
        session_secret="test-session-secret-for-mock",
    )
    app = FastAPI()
    register_e2e_auth_routes(app)
    client = TestClient(app)

    response = client.get(
        "/e2e/login?email=test@apap.local",
        headers={"X-E2E-Secret": "test-secret"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["authenticated"] is True
    assert payload["email"] == "test@apap.local"
    assert payload["user_id"] == MOCK_USER_ID
    assert payload["rol"] == MOCK_USER_ROL
    assert len(payload["csrf_token"]) >= 32

    # Cookie set with the production-compatible shape.
    cookie_name = session_cookie_name()
    assert cookie_name in response.cookies
    signed = response.cookies[cookie_name]
    decoded = read_session(signed, secret="test-session-secret-for-mock")
    assert decoded is not None
    assert decoded["email"] == "test@apap.local"
    assert decoded["rol"] == MOCK_USER_ROL
    assert decoded["user_id"] == MOCK_USER_ID
    assert decoded["is_authorized"] is True
    assert decoded["csrf_token"] == payload["csrf_token"]

    # Auth cache pre-populated for the email — the very next
    # request from the test client is authorised.
    cached = get_cached_auth("test@apap.local", ttl_seconds=300)
    assert cached is not None
    assert cached.is_authorized is True
    assert cached.rol == MOCK_USER_ROL


def test_debug_e2e_cookie_can_be_sent_over_loopback_http() -> None:
    """The CI-only debug app must not mint a Secure cookie for its HTTP URL."""
    import app.core.e2e_auth as e2e_module

    e2e_module.get_settings = lambda: Settings(
        debug=True,
        e2e_auth_enabled=True,
        e2e_auth_secret="test-secret",
        session_secret="test-session-secret-for-mock",
    )
    app = FastAPI()
    register_e2e_auth_routes(app)

    response = TestClient(app).get(
        "/e2e/login",
        headers={"X-E2E-Secret": "test-secret"},
    )

    assert response.status_code == 200
    assert "secure" not in response.headers["set-cookie"].lower()


def test_default_email_applies_when_query_param_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ``?email=...`` the route falls back to the configured default."""
    import app.core.e2e_auth as e2e_module

    e2e_module.get_settings = lambda: Settings(
        e2e_auth_enabled=True,
        e2e_auth_secret="test-secret",
        e2e_auth_default_email="default@apap.local",
        session_secret="test-session-secret-for-mock",
    )
    app = FastAPI()
    register_e2e_auth_routes(app)
    client = TestClient(app)

    response = client.get(
        "/e2e/login",
        headers={"X-E2E-Secret": "test-secret"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == "default@apap.local"
    assert get_cached_auth("default@apap.local", ttl_seconds=300) is not None


def test_empty_email_with_no_default_returns_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both ``?email=`` and ``e2e_auth_default_email`` empty → 400."""
    import app.core.e2e_auth as e2e_module

    e2e_module.get_settings = lambda: Settings(
        e2e_auth_enabled=True,
        e2e_auth_secret="test-secret",
        e2e_auth_default_email="",
        session_secret="test-session-secret-for-mock",
    )
    app = FastAPI()
    register_e2e_auth_routes(app)
    client = TestClient(app)

    response = client.get(
        "/e2e/login?email= ",
        headers={"X-E2E-Secret": "test-secret"},
    )

    assert response.status_code == 400


def test_audit_log_emitted_on_success(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Issue #904 AC1: every successful attempt emits one audit entry.

    The entry carries ``outcome='ok'``, the target email and the origin
    IP — and never the secret value. Field names deliberately avoid the
    closed redaction list (``email``/``ip_address``) because the issue
    mandates those values in the audit trail (``target_email``/
    ``client_ip``).
    """
    import app.core.e2e_auth as e2e_module

    e2e_module.get_settings = lambda: Settings(  # type: ignore[assignment]
        e2e_auth_enabled=True,
        e2e_auth_secret="test-secret-value",
        session_secret="test-session-secret-for-mock",
    )
    app = FastAPI()
    register_e2e_auth_routes(app)
    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger="app"):
        response = client.get(
            "/e2e/login?email=audit@apap.local",
            headers={"X-E2E-Secret": "test-secret-value"},
        )

    assert response.status_code == 200
    audit_records = [
        record
        for record in caplog.records
        if getattr(record, "_caller_fields", {}).get("event") == "e2e.login"
    ]
    assert len(audit_records) == 1, "expected exactly one audit entry on success"
    record = audit_records[0]
    fields = record._caller_fields
    assert fields["outcome"] == "ok"
    assert fields["target_email"] == "audit@apap.local"
    assert fields["client_ip"]
    # The secret value must never appear in the audit entry.
    assert "test-secret-value" not in record.getMessage()
    assert "test-secret-value" not in str(fields)


def test_audit_log_emitted_on_invalid_secret(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Issue #904 AC1: a failed attempt also emits one audit entry.

    Outcome is ``invalid_secret`` for both a wrong and a missing header;
    the attempted email (raw query param) and origin IP are recorded and
    the secret value never reaches the log.
    """
    import app.core.e2e_auth as e2e_module

    e2e_module.get_settings = lambda: Settings(  # type: ignore[assignment]
        e2e_auth_enabled=True,
        e2e_auth_secret="test-secret-value",
        session_secret="test-session-secret-for-mock",
    )
    app = FastAPI()
    register_e2e_auth_routes(app)
    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger="app"):
        response = client.get(
            "/e2e/login?email=probe@apap.local",
            headers={"X-E2E-Secret": "wrong-secret"},
        )

    assert response.status_code == 401
    audit_records = [
        record
        for record in caplog.records
        if getattr(record, "_caller_fields", {}).get("event") == "e2e.login"
    ]
    assert len(audit_records) == 1, "expected exactly one audit entry on failure"
    record = audit_records[0]
    fields = record._caller_fields
    assert fields["outcome"] == "invalid_secret"
    assert fields["target_email"] == "probe@apap.local"
    assert fields["client_ip"]
    assert "wrong-secret" not in record.getMessage()
    assert "wrong-secret" not in str(fields)


def test_non_ascii_secret_header_lands_on_invalid_secret_with_audit(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A raw non-ASCII byte in ``X-E2E-Secret`` must land on 401, not 500.

    ASGI decodes header bytes with latin-1, so a probe sending a raw
    latin-1 byte (e.g. ``0xE9``) reaches the handler as a non-ASCII str.
    ``hmac.compare_digest`` raises ``TypeError`` for non-ASCII str inputs,
    which produced an unhandled 500 with NO audit entry. The hardened
    handler treats any non-ASCII probe as an invalid secret: 401 plus
    exactly one ``e2e.login`` audit record, and the probe bytes never
    reach the log.
    """
    import app.core.e2e_auth as e2e_module

    e2e_module.get_settings = lambda: Settings(  # type: ignore[assignment]
        e2e_auth_enabled=True,
        e2e_auth_secret="test-secret-value",
        session_secret="test-session-secret-for-mock",
    )
    app = FastAPI()
    register_e2e_auth_routes(app)
    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger="app"):
        response = client.get(
            "/e2e/login?email=probe@apap.local",
            headers={"X-E2E-Secret": b"\xe9"},
        )

    assert response.status_code == 401
    audit_records = [
        record
        for record in caplog.records
        if getattr(record, "_caller_fields", {}).get("event") == "e2e.login"
    ]
    assert len(audit_records) == 1, "expected exactly one audit entry on the probe"
    fields = audit_records[0]._caller_fields
    assert fields["outcome"] == "invalid_secret"
    # The raw probe bytes must never reach the log.
    assert "\xe9" not in audit_records[0].getMessage()
    assert "\xe9" not in str(fields)


def test_audit_log_emitted_on_empty_email_400(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Issue #904 fix round 1 (JD-B-002/JD-A-002): the 400 branch is audited.

    AC1 requires one ``e2e.login`` entry on EVERY attempt — including the
    400 empty-target-email branch (valid secret). Outcome taxonomy:
    ``invalid_request``.
    """
    import app.core.e2e_auth as e2e_module

    e2e_module.get_settings = lambda: Settings(  # type: ignore[assignment]
        e2e_auth_enabled=True,
        e2e_auth_secret="test-secret-value",
        e2e_auth_default_email="",
        session_secret="test-session-secret-for-mock",
    )
    app = FastAPI()
    register_e2e_auth_routes(app)
    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger="app"):
        response = client.get(
            "/e2e/login?email= ",
            headers={"X-E2E-Secret": "test-secret-value"},
        )

    assert response.status_code == 400
    audit_records = [
        record
        for record in caplog.records
        if getattr(record, "_caller_fields", {}).get("event") == "e2e.login"
    ]
    assert len(audit_records) == 1, "expected exactly one audit entry on 400"
    fields = audit_records[0]._caller_fields
    assert fields["outcome"] == "invalid_request"
    assert "test-secret-value" not in str(fields)


def test_audit_log_emitted_on_misconfigured_503(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Issue #904 fix round 1 (JD-B-002/JD-A-002): the 503 branch is audited.

    An enabled flag with an empty configured secret answers 503 — that
    attempt must also leave one ``e2e.login`` entry (outcome
    ``server_misconfigured``) so AC1 holds for every attempt.
    """
    import app.core.e2e_auth as e2e_module

    e2e_module.get_settings = lambda: Settings(  # type: ignore[assignment]
        e2e_auth_enabled=True,
        e2e_auth_secret="",
    )
    app = FastAPI()
    register_e2e_auth_routes(app)
    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger="app"):
        response = client.get(
            "/e2e/login?email=probe@apap.local",
            headers={"X-E2E-Secret": "anything"},
        )

    assert response.status_code == 503
    audit_records = [
        record
        for record in caplog.records
        if getattr(record, "_caller_fields", {}).get("event") == "e2e.login"
    ]
    assert len(audit_records) == 1, "expected exactly one audit entry on 503"
    fields = audit_records[0]._caller_fields
    assert fields["outcome"] == "server_misconfigured"
    assert fields["target_email"] == "probe@apap.local"


def test_audit_target_email_is_capped(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Issue #904 fix round 1 (JD-B-006): the raw email is capped in the audit.

    The unvalidated ``?email=`` query param must be truncated before it
    reaches ``log_safe`` so an unbounded probe value cannot bloat the
    audit trail. Pinned on the rejected path with a 300-char probe.
    """
    import app.core.e2e_auth as e2e_module

    e2e_module.get_settings = lambda: Settings(  # type: ignore[assignment]
        e2e_auth_enabled=True,
        e2e_auth_secret="test-secret-value",
        session_secret="test-session-secret-for-mock",
    )
    app = FastAPI()
    register_e2e_auth_routes(app)
    client = TestClient(app)
    oversized_email = "a" * 300 + "@probe.example"

    with caplog.at_level(logging.INFO, logger="app"):
        response = client.get(
            f"/e2e/login?email={oversized_email}",
            headers={"X-E2E-Secret": "wrong-secret"},
        )

    assert response.status_code == 401
    audit_records = [
        record
        for record in caplog.records
        if getattr(record, "_caller_fields", {}).get("event") == "e2e.login"
    ]
    assert len(audit_records) == 1
    recorded_email = audit_records[0]._caller_fields["target_email"]
    assert len(recorded_email) <= 120


def test_production_app_answers_404_when_flag_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #904 AC3: the real ``create_app`` answers 404 with the flag off.

    Composition-level pin: the existing module-level test covers
    ``register_e2e_auth_routes`` directly; this one proves the production
    factory wiring (issue #904 validation plan step: flag off -> 404 in
    production without the flag).

    The flag is forced to an explicit ``false`` env-var value rather than
    deleted: ``Settings`` reads ``env_file='.env'`` and
    ``monkeypatch.delenv`` cannot clear a developer-local ``.env`` entry,
    which flipped this test red spuriously (issue #904 fix round 1,
    JD-A-006). The env var takes precedence over ``.env`` in
    pydantic-settings, so ``setenv('false')`` is deterministic.
    """
    from app.main import create_app

    monkeypatch.setenv("APAP_E2E_AUTH_ENABLED", "false")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        response = client.get("/e2e/login")
    finally:
        get_settings.cache_clear()

    assert response.status_code == 404


def test_production_app_registers_route_when_flag_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Positive control for AC3: with the flag + secret set the route exists (401).

    The flag and secret are set via ``monkeypatch.setenv`` — env vars take
    precedence over ``Settings.env_file('.env')``, so this composition
    test is deterministic regardless of a developer-local ``.env``
    (issue #904 fix round 1, JD-A-006).
    """
    from app.main import create_app

    monkeypatch.setenv("APAP_E2E_AUTH_ENABLED", "true")
    monkeypatch.setenv("APAP_E2E_AUTH_SECRET", "composition-test-secret")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        response = client.get("/e2e/login")
    finally:
        get_settings.cache_clear()

    assert response.status_code == 401
