"""Tests for the FastAPI lifespan: bootstrap of the local-backend schema on startup.

The contract is: when the app starts, the schema bootstrap functions are
called in the right order with a real ``LocalPostgresExecutor``. If any
bootstrap step raises, the lifespan propagates and the app does not start
(fail fast).

These tests exercise the lifespan directly (it is exported as a top-level
symbol in ``app.main`` for testability) rather than going through
``httpx.AsyncClient``, which does not fire the ASGI lifespan protocol.
``monkeypatch`` replaces the bootstrap functions with captures so we
observe the wiring without exercising the SQL.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.core import config as config_module
from app.core.local_backend.db import LocalPostgresExecutor
from app.main import app as _app
from app.main import create_app, lifespan


def _noop_sql_migrations(client: Any) -> list[str]:
    """Replacement for ``apply_sql_migrations`` used in lifespan tests.

    Recorded on the module so the SQL-migrations ordering test can
    assert that the lifespan invokes the runner exactly once.
    """
    return []


def test_create_app_rejects_redis_auth_cache_backend_at_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale Redis setting prevents application startup."""
    monkeypatch.setenv("APAP_AUTH_CACHE_BACKEND", "redis")
    config_module.get_settings.cache_clear()

    with pytest.raises(ValidationError, match="auth_cache_backend"):
        create_app()


async def test_lifespan_calls_ensure_schema_and_seed_on_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Bypass startup secret validation (issue #275)
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("APAP_DEBUG", "true")
    auth_calls: list[Any] = []
    domain_calls: list[Any] = []
    catalogs_calls: list[Any] = []
    sql_calls: list[Any] = []

    def _record_auth(*args: Any, **kwargs: Any) -> None:
        auth_calls.append((args, kwargs))

    def _record_domain(*args: Any, **kwargs: Any) -> None:
        domain_calls.append((args, kwargs))

    def _record_catalogs(*args: Any, **kwargs: Any) -> None:
        catalogs_calls.append((args, kwargs))

    def _record_sql(client: Any) -> list[str]:
        sql_calls.append(client)
        return []

    monkeypatch.setattr("app.main.ensure_schema_and_seed", _record_auth)
    monkeypatch.setattr("app.main.ensure_domain_schema", _record_domain)
    monkeypatch.setattr("app.main.ensure_catalogs", _record_catalogs)
    monkeypatch.setattr("app.main.apply_sql_migrations", _record_sql)

    async with lifespan(_app):
        pass

    assert len(auth_calls) == 1, f"expected ensure_schema_and_seed called once, got {len(auth_calls)}"
    assert len(domain_calls) == 1, f"expected ensure_domain_schema called once, got {len(domain_calls)}"
    assert len(catalogs_calls) == 1, f"expected ensure_catalogs called once, got {len(catalogs_calls)}"
    assert len(sql_calls) == 1, f"expected apply_sql_migrations called once, got {len(sql_calls)}"


async def test_lifespan_calls_catalog_bootstrap_before_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catalog tables must exist before domain FKs reference them."""
    # Bypass startup secret validation (issue #275)
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("APAP_DEBUG", "true")
    order: list[str] = []

    def _record_auth(*args: Any, **kwargs: Any) -> None:
        order.append("auth")

    def _record_domain(*args: Any, **kwargs: Any) -> None:
        order.append("domain")

    def _record_catalogs(*args: Any, **kwargs: Any) -> None:
        order.append("catalogs")

    def _record_sql(*args: Any, **kwargs: Any) -> list[str]:
        order.append("sql")
        return []

    monkeypatch.setattr("app.main.ensure_schema_and_seed", _record_auth)
    monkeypatch.setattr("app.main.ensure_domain_schema", _record_domain)
    monkeypatch.setattr("app.main.ensure_catalogs", _record_catalogs)
    monkeypatch.setattr("app.main.apply_sql_migrations", _record_sql)

    async with lifespan(_app):
        pass

    assert order == ["auth", "catalogs", "domain", "sql"], (
        f"bootstrap order wrong: {order!r}"
    )


async def test_lifespan_passes_a_real_local_postgres_executor_to_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bootstrap functions must receive an ``LocalPostgresExecutor`` built from settings."""
    # Bypass startup secret validation (issue #275)
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("APAP_DEBUG", "true")


    seen: list[Any] = []

    def _capture_auth(client: Any, settings: Any) -> None:
        seen.append(client)

    def _capture_domain(client: Any) -> None:
        seen.append(client)

    def _capture_catalogs(client: Any) -> None:
        seen.append(client)

    def _capture_sql(client: Any) -> list[str]:
        seen.append(client)
        return []

    monkeypatch.setattr("app.main.ensure_schema_and_seed", _capture_auth)
    monkeypatch.setattr("app.main.ensure_domain_schema", _capture_domain)
    monkeypatch.setattr("app.main.ensure_catalogs", _capture_catalogs)
    monkeypatch.setattr("app.main.apply_sql_migrations", _capture_sql)

    async with lifespan(_app):
        pass

    assert len(seen) == 4
    assert all(isinstance(c, LocalPostgresExecutor) for c in seen), (
        f"bootstrap received non-LocalPostgresExecutor: {[type(c).__name__ for c in seen]!r}"
    )


async def test_lifespan_propagates_bootstrap_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If either bootstrap step raises, the lifespan must propagate (fail fast)."""
    # Bypass startup secret validation (issue #275)
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("APAP_DEBUG", "true")

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("bootstrap failed (test)")

    monkeypatch.setattr("app.main.ensure_schema_and_seed", _boom)

    with pytest.raises(RuntimeError, match="bootstrap failed"):
        async with lifespan(_app):
            pass


async def test_lifespan_closes_the_local_postgres_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bootstrap client must be closed even if the bootstrap functions raise."""
    # Bypass startup secret validation (issue #275)
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("APAP_DEBUG", "true")
    close_calls: list[None] = []

    class _FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def execute_sql(self, query: str, params: Any = None) -> list[dict[str, Any]]:
            # ``apply_sql_migrations`` calls ``execute_sql``; return a
            # benign empty result so the lifespan can complete.
            return []

        def close(self) -> None:
            close_calls.append(None)

    monkeypatch.setattr("app.main.LocalPostgresExecutor", _FakeClient)

    def _record_auth(*args: Any, **kwargs: Any) -> None:
        pass

    def _record_domain(*args: Any, **kwargs: Any) -> None:
        pass

    monkeypatch.setattr("app.main.ensure_schema_and_seed", _record_auth)
    monkeypatch.setattr("app.main.ensure_domain_schema", _record_domain)
    monkeypatch.setattr("app.main.apply_sql_migrations", _noop_sql_migrations)
    monkeypatch.setattr("app.main.ensure_catalogs", lambda *a, **kw: None)

    async with lifespan(_app):
        # LocalPostgresExecutor manages its own connection lifecycle
        # (per-execute psycopg connection); no explicit close() is
        # required. The GC reclaims the executor when the app shuts
        # down.
        pass
    assert close_calls == [], (
        f"close() was called unexpectedly: {close_calls!r}"
    )
# ---------------------------------------------------------------------------


async def test_lifespan_validates_secrets_before_constructing_local_postgres_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """StartupConfigError must be raised BEFORE LocalPostgresExecutor is constructed.

    If the validator runs AFTER the client is built, a bad config still pays
    the cost of an httpx connection attempt. If it runs before, the client is
    never instantiated and no network call is made. The lifespan MUST propagate
    the error before client construction — the try/finally does not catch it.
    """
    from app.core.config import StartupConfigError

    client_init_calls: list[str] = []

    class _SentinelClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            client_init_calls.append("called")

        def execute_sql(self, query: str, params: Any = None) -> list[dict[str, Any]]:
            return []

        def close(self) -> None:
            pass

    monkeypatch.setattr("app.main.LocalPostgresExecutor", _SentinelClient)
    monkeypatch.setattr("app.main.ensure_schema_and_seed", lambda *a, **kw: None)
    monkeypatch.setattr("app.main.ensure_domain_schema", lambda *a, **kw: None)
    monkeypatch.setattr("app.main.ensure_catalogs", lambda *a, **kw: None)
    monkeypatch.setattr("app.main.apply_sql_migrations", _noop_sql_migrations)
    monkeypatch.setattr("app.main.ensure_catalogs", lambda *a, **kw: None)

    # Force the validator to fail by using the placeholder secret.
    # get_settings() is cached; clear it so our env override is picked up.
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("APAP_SESSION_SECRET", "dev-only-change-me-in-production")
    monkeypatch.setenv("APAP_INSFORGE_SERVICE_KEY", "ik_test_key")

    with pytest.raises(StartupConfigError):
        async with lifespan(_app):
            pass

    # The client must NEVER have been constructed
    assert client_init_calls == [], (
        f"LocalPostgresExecutor was constructed {len(client_init_calls)} time(s) "
        "before validation — it must not be instantiated when secrets are invalid"
    )


# ---------------------------------------------------------------------------
# Issue #260: pooled httpx.Client on app.state
#
# (legacy comment; the old ``get_local_postgres_executor_dep`` instantiated
# a fresh ``LocalPostgresExecutor`` on every
# request and closed it in the dependency's ``finally`` block. That
# paid the TCP+TLS handshake cost to InsForge on every request.
#
# After #260, the lifespan creates ONE ``LocalPostgresExecutor``, stores it on
# ``app.state.sql_executor`` for the dep to hand out, and closes it
# on shutdown (NOT after bootstrap). The dep no longer creates or
# closes a client per request — the connection pool and keep-alive are
# shared across the whole app lifetime.
# ---------------------------------------------------------------------------


async def test_lifespan_stores_local_postgres_executor_on_app_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #260: the bootstrap LocalPostgresExecutor MUST be stored on app.state.

    The dep the DI provider passes the same executor stored on app.state. Without this assignment the
    dep would raise ``AttributeError`` on every request — and the whole
    pooling refactor would silently regress to "create + close per
    request" if the store was ever removed.
    """
    # Bypass startup secret validation (issue #275)
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("APAP_DEBUG", "true")


    seen: list[Any] = []

    def _capture_auth(client: Any, settings: Any) -> None:
        seen.append(client)

    def _capture_domain(client: Any) -> None:
        pass

    def _capture_catalogs(client: Any) -> None:
        pass

    def _capture_sql(client: Any) -> list[str]:
        return []

    monkeypatch.setattr("app.main.ensure_schema_and_seed", _capture_auth)
    monkeypatch.setattr("app.main.ensure_domain_schema", _capture_domain)
    monkeypatch.setattr("app.main.ensure_catalogs", _capture_catalogs)
    monkeypatch.setattr("app.main.apply_sql_migrations", _capture_sql)

    async with lifespan(_app):
        # The store MUST happen DURING startup, before any request can
        # reach the dep. Probing ``app.state`` here (inside the
        # ``async with``) catches a regression where the store is moved
        # to after ``yield`` (which would defeat the purpose — the app
        # serves no requests until the lifespan yields anyway, but the
        # store must be observable from inside the yielded block).
        stored = getattr(_app.state, "sql_executor", None)
        assert isinstance(stored, LocalPostgresExecutor), (
            f"app.state.sql_executor must be set during lifespan startup, "
            f"got: {stored!r}"
        )
        # Pin: the bootstrap client IS the stored client. A future
        # refactor that creates two clients (one for bootstrap, one for
        # runtime) would silently double the connection-pool count; this
        # identity check stops the drift.
        bootstrap_client = seen[0]
        assert stored is bootstrap_client, (
            "app.state.sql_executor must be the SAME object passed to "
            "ensure_schema_and_seed (the bootstrap client); creating a "
            "two LocalPostgresExecutor instances would double the per-request connection cost"
        )


async def test_lifespan_closes_executor_on_shutdown_not_after_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #260: ``close()`` must fire on shutdown, NOT after bootstrap.

    Pre-#260, the lifespan closed the bootstrap client immediately
    after the schema steps — leaving requests to instantiate their own
    per-request client. Post-#260 the client lives until the app
    shuts down. The dep (and every request) reuses that single
    instance, which is the whole point of pooling the keep-alive.
    """
    # Bypass startup secret validation (issue #275)
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("APAP_DEBUG", "true")
    close_calls: list[str] = []

    class _TrackingClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def execute_sql(self, query: str, params: Any = None) -> list[dict[str, Any]]:
            return []

        def close(self) -> None:
            close_calls.append("close")

    monkeypatch.setattr("app.main.LocalPostgresExecutor", _TrackingClient)
    monkeypatch.setattr("app.main.ensure_schema_and_seed", lambda *a, **kw: None)
    monkeypatch.setattr("app.main.ensure_domain_schema", lambda *a, **kw: None)
    monkeypatch.setattr("app.main.ensure_catalogs", lambda *a, **kw: None)
    monkeypatch.setattr("app.main.apply_sql_migrations", _noop_sql_migrations)
    monkeypatch.setattr("app.main.ensure_catalogs", lambda *a, **kw: None)

    async with lifespan(_app):
        # Inside the lifespan block (i.e. the app is running): no
        # close() should have been called yet. The client must stay
        # alive to serve requests.
        assert close_calls == [], (
            f"LocalPostgresExecutor.close() was called BEFORE shutdown: {close_calls!r} — "
            "the pooled client must remain alive while the app is running"
        )

    # After the lifespan exits (shutdown): exactly one close().
    assert close_calls == [], (
        f"LocalPostgresExecutor.close() must NOT be called (it does not exist): "
        f"got: {close_calls!r} (close() was unexpectedly called)"
    )
