"""Composition tests for the magic-link feature flag (issue #1005).

``Settings.auth_enable_magic_link`` (default ``False``, AGENTS §6
default-deny) gates the magic-link login surface:

- OFF: ``app.main.create_app`` does NOT register the magic-link router
  and probes to ``/auth/magic/*`` receive a fail-closed 404 — the auth
  middleware short-circuits the paths with the same 404 shape FastAPI
  emits for an unknown route (issue #1005 acceptance criterion 1).
- ON: behaviour is identical to the pre-flag app — the router is
  registered and the deep round-trip contract remains anchored by
  ``tests/integration/test_magic_link_routes.py`` (standalone local
  backend) and ``tests/integration/test_magic_link_real_app.py``
  (real ``app.main`` app with Postgres).

Env-var note (mirrors ``tests/test_e2e_auth.py``): the flag is forced
via ``monkeypatch.setenv`` with an explicit value (never ``delenv``)
because ``Settings`` reads ``env_file='.env'`` and pydantic-settings
gives the process env precedence — deterministic regardless of a
developer-local ``.env`` entry (issue #904 fix round 1, JD-A-006).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings

FLAG_ENV_VAR = "APAP_AUTH_ENABLE_MAGIC_LINK"

MAGIC_LINK_PATHS = ("/auth/magic/start", "/auth/magic/verify")


def _registered_paths(app: object) -> set[str]:
    """Return every route path registered on ``app``, recursively.

    FastAPI 0.141 represents ``include_router`` calls as
    ``_IncludedRouter`` wrappers instead of flattening the routes into
    ``app.routes``, so the walk recurses into the wrapped routers via
    the attributes the wrapper exposes (``original_router``).
    """
    paths: set[str] = set()
    stack = list(app.routes)  # type: ignore[attr-defined]
    while stack:
        route = stack.pop()
        path = getattr(route, "path", None)
        if isinstance(path, str):
            paths.add(path)
        for attr in ("original_router", "router", "app"):
            inner = getattr(route, attr, None)
            if inner is not None and hasattr(inner, "routes"):
                stack.extend(inner.routes)
    return paths


def _build_app_with_flag(monkeypatch: object, value: str) -> object:
    """Build a fresh ``create_app()`` with the flag forced to ``value``.

    Forces the env var explicitly (never deletes it) and clears the
    ``get_settings`` cache so the factory observes the forced value.
    The cache is cleared again afterwards; the conftest autouse fixture
    also clears it per test as a safety net.
    """
    from app.main import create_app

    monkeypatch.setenv(FLAG_ENV_VAR, value)  # type: ignore[attr-defined]
    get_settings.cache_clear()
    try:
        return create_app()
    finally:
        get_settings.cache_clear()


# --- Settings parsing -----------------------------------------------------


def test_settings_auth_enable_magic_link_defaults_false() -> None:
    """Default-deny (§6): the flag defaults to ``False``.

    The env var is deleted explicitly: tests/conftest.py setdefaults it
    to ``true`` for the shared module app, and pydantic-settings reads
    the process env — the field DEFAULT is the contract under test here.
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv(FLAG_ENV_VAR, raising=False)
        settings = Settings(_env_file=None)

    assert settings.auth_enable_magic_link is False


def test_settings_reads_auth_enable_magic_link_from_env() -> None:
    """``APAP_AUTH_ENABLE_MAGIC_LINK=true`` parses to ``True``."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv(FLAG_ENV_VAR, "true")
        settings = Settings(_env_file=None)

    assert settings.auth_enable_magic_link is True


def test_settings_reads_auth_enable_magic_link_false_from_env() -> None:
    """``APAP_AUTH_ENABLE_MAGIC_LINK=false`` parses to ``False``.

    The explicit-false pin mirrors ``test_e2e_auth.py``: env vars take
    precedence over a developer-local ``.env``, so this is deterministic.
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv(FLAG_ENV_VAR, "false")
        settings = Settings(_env_file=None)

    assert settings.auth_enable_magic_link is False


# --- flag OFF (default): fail-closed --------------------------------------


def test_flag_off_router_not_registered(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """With the flag off, ``create_app`` does NOT register the router."""
    app = _build_app_with_flag(monkeypatch, "false")
    paths = _registered_paths(app)

    for path in MAGIC_LINK_PATHS:
        assert path not in paths, (
            f"{path!r} is registered with "
            f"{FLAG_ENV_VAR}=false; the router must be gated "
            f"(issue #1005, fail-closed default-deny)"
        )


def test_flag_off_probes_receive_fail_closed_404(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """With the flag off, ``/auth/magic/*`` probes receive a 404.

    Acceptance criterion 1 (issue #1005): the probe must fail closed,
    never redirect to /login (that would suggest a live auth gate) and
    never reach a handler (the router is not registered).
    """
    from app.main import create_app

    monkeypatch.setenv(FLAG_ENV_VAR, "false")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        start_response = client.post(
            "/auth/magic/start", json={"email": "ana@test.com"}
        )
        empty_start_response = client.post("/auth/magic/start", json={})
        verify_response = client.get(
            "/auth/magic/verify?" + "token=" + "0" * 64,
            follow_redirects=False,
        )
    finally:
        get_settings.cache_clear()

    assert start_response.status_code == 404, (
        f"POST /auth/magic/start returned {start_response.status_code} "
        f"with the flag off; expected the fail-closed 404"
    )
    assert empty_start_response.status_code == 404, (
        f"POST /auth/magic/start (empty body) returned "
        f"{empty_start_response.status_code} with the flag off; "
        f"expected the fail-closed 404"
    )
    assert verify_response.status_code == 404, (
        f"GET /auth/magic/verify returned {verify_response.status_code} "
        f"with the flag off; expected the fail-closed 404"
    )


# --- middleware gate unit atom (JD-A-003, fix round 1) --------------------


def test_flag_off_gate_short_circuits_before_routing() -> None:
    """The middleware gate itself answers the 404 — not just the outcome.

    JD-A-003 (fix round 1): ``test_flag_off_probes_receive_fail_closed_404``
    passes identically with the gate deleted (router absent +
    ``PUBLIC_PATHS`` passthrough produce the same unknown-route 404).
    This atom exercises the gate directly: a router that WOULD answer
    ``/auth/magic/start`` is registered on the app, so if the gate in
    ``install_auth_middleware`` were removed the request would fall
    through ``PUBLIC_PATHS`` and reach the stub handler (200). The gate
    must short-circuit with the fail-closed 404 BEFORE routing, and the
    stub must never run. Deleting the gate block in
    ``app/core/middleware.py`` turns this atom RED.
    """
    from fastapi import FastAPI

    from app.core.config import Settings
    from app.core.middleware import install_auth_middleware

    stub_hits: list[str] = []

    probe_app = FastAPI()

    @probe_app.post("/auth/magic/start")
    def _stub_start() -> dict[str, str]:  # pragma: no cover - gate must prevent this
        stub_hits.append("start")
        return {"detail": "stub-reached"}

    settings = Settings(
        _env_file=None,
        auth_enable_magic_link=False,
        csrf_enabled=False,
    )
    install_auth_middleware(probe_app, settings)

    client = TestClient(probe_app)
    response = client.post("/auth/magic/start", json={"email": "ana@test.com"})

    assert response.status_code == 404, (
        f"POST /auth/magic/start with the flag off returned "
        f"{response.status_code}; the middleware gate must answer the "
        f"fail-closed 404 even when a handler is registered"
    )
    assert response.json() == {"detail": "Not Found"}, (
        "the gate must emit the same 404 body FastAPI uses for an "
        "unknown route"
    )
    assert stub_hits == [], (
        "the stub handler ran: the middleware gate did NOT short-circuit "
        "the request before routing"
    )


# --- fail-closed 404 observability (JD-B-005, fix round 1) ----------------


def test_flag_off_404_logs_magic_link_disabled(
    monkeypatch, caplog  # type: ignore[no-untyped-def]
) -> None:
    """The flag-off 404 logs ``auth.magic_link_disabled`` with the path.

    JD-B-005 (fix round 1): a silent fail-closed 404 is indistinguishable
    from a mis-deploy that dropped the router. The middleware must emit
    the structured event (mirroring the ``csrf.disabled`` naming style)
    with the probe path — and NOTHING else: no tokens, no emails.
    """
    from app.main import create_app

    monkeypatch.setenv(FLAG_ENV_VAR, "false")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        with caplog.at_level("INFO", logger="app"):
            response = client.post(
                "/auth/magic/start", json={"email": "ana@test.com"}
            )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 404
    records = [
        rec
        for rec in caplog.records
        if rec._caller_fields.get("event") == "auth.magic_link_disabled"
    ]
    assert records, (
        "expected an auth.magic_link_disabled log record for the "
        "fail-closed 404; got events: "
        f"{[r._caller_fields.get('event') for r in caplog.records]}"
    )
    assert records[0]._caller_fields.get("path") == "/auth/magic/start", (
        "the event must carry the probed path so an operator can "
        "diagnose a mis-deploy"
    )


# --- flag ON: behaviour identical to the pre-flag app ---------------------


def test_flag_on_router_registered(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """With the flag on, the router is registered (pre-#1005 parity)."""
    app = _build_app_with_flag(monkeypatch, "true")
    paths = _registered_paths(app)

    for path in MAGIC_LINK_PATHS:
        assert path in paths, (
            f"{path!r} is NOT registered with "
            f"{FLAG_ENV_VAR}=true; the flag-on behaviour must be "
            f"identical to the pre-#1005 app"
        )


def test_flag_on_start_endpoint_runs_handler(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """With the flag on, the start endpoint is live end-to-end.

    A POST with an empty body must reach the handler's validation
    (400 ``invalid_email``), proving the route is registered AND
    dispatched — not short-circuited by the flag gate. The deep
    round-trip contract (token minting, SMTP, session cookie) stays
    anchored by the magic-link integration suites.
    """
    from app.main import create_app

    monkeypatch.setenv(FLAG_ENV_VAR, "true")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        response = client.post("/auth/magic/start", json={})
    finally:
        get_settings.cache_clear()

    assert response.status_code == 400, (
        f"POST /auth/magic/start (empty body) returned "
        f"{response.status_code} with the flag on; expected the "
        f"handler's 400 invalid_email (route must be live)"
    )
