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
            "/auth/magic/verify?token=0" * 64, follow_redirects=False
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
