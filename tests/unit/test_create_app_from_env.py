"""Unit tests for ``app.core.local_backend.app::create_app_from_env``.

F1 §T1.2 — env-driven factory for the local backend.

These tests do NOT touch Postgres (the lifespan only runs when a real
ASGI client connects; the factory itself reads env vars and builds the
router tree). M0's 15 acceptance scenarios in
``tests/integration/test_local_backend.py`` cover the lifespan /
Postgres paths.
"""

from __future__ import annotations

import pytest

from app.core.local_backend.app import create_app_from_env


def test_raises_runtimeerror_when_dsn_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """F1 §T1.2.AS1 — missing DSN → RuntimeError with the documented message."""
    monkeypatch.delenv("APAP_LOCAL_BACKEND_DSN", raising=False)
    with pytest.raises(RuntimeError, match="APAP_LOCAL_BACKEND_DSN is required"):
        create_app_from_env()


def test_raises_when_dsn_is_only_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty-after-strip DSN is rejected (defensive: copy/paste footgun)."""
    monkeypatch.setenv("APAP_LOCAL_BACKEND_DSN", "   ")
    with pytest.raises(RuntimeError, match="APAP_LOCAL_BACKEND_DSN is required"):
        create_app_from_env()


def test_returns_fastapi_instance_when_dsn_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """F1 §T1.2.AS2 — happy path returns a FastAPI instance with lifespan wired."""
    monkeypatch.setenv(
        "APAP_LOCAL_BACKEND_DSN",
        "postgresql://postgres:postgres@localhost:5432/postgres",
    )
    monkeypatch.setenv("APAP_LOCAL_BACKEND_OAUTH_CONFIGURED", "false")
    application = create_app_from_env()
    assert application is not None
    assert application.title == "APAP local backend"
    # Lifespan is wired (FastAPI exposes it as a router-level attribute).
    assert application.router.lifespan_context is not None


@pytest.mark.parametrize("truthy", ["1", "true", "yes", "on", "TRUE", "On"])
def test_oauth_truthy_values_dont_raise(
    monkeypatch: pytest.MonkeyPatch, truthy: str
) -> None:
    """F1 §T1.2.AS3 — truthy env values are accepted (case-insensitive)."""
    monkeypatch.setenv("APAP_LOCAL_BACKEND_DSN", "postgresql://x@y/z")
    monkeypatch.setenv("APAP_LOCAL_BACKEND_OAUTH_CONFIGURED", truthy)
    application = create_app_from_env()
    assert application is not None


def test_oauth_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default oauth_configured when env is unset, empty, or '0'."""
    monkeypatch.delenv("APAP_LOCAL_BACKEND_OAUTH_CONFIGURED", raising=False)
    monkeypatch.setenv("APAP_LOCAL_BACKEND_DSN", "postgresql://x@y/z")
    application = create_app_from_env()
    assert application is not None


def test_oauth_explicit_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit APAP_LOCAL_BACKEND_OAUTH_CONFIGURED=false is accepted."""
    monkeypatch.setenv("APAP_LOCAL_BACKEND_DSN", "postgresql://x@y/z")
    monkeypatch.setenv("APAP_LOCAL_BACKEND_OAUTH_CONFIGURED", "false")
    application = create_app_from_env()
    assert application is not None


__all__ = [
    "test_raises_runtimeerror_when_dsn_missing",
    "test_raises_when_dsn_is_only_whitespace",
    "test_returns_fastapi_instance_when_dsn_set",
    "test_oauth_truthy_values_dont_raise",
    "test_oauth_default_when_unset",
    "test_oauth_explicit_false",
]
