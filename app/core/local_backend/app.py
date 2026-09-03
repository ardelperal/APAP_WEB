"""FastAPI composition root for the local backend."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.auth_magic.mail_transports import ConsoleMailTransport
from app.core.auth_magic.postgres_adapter import PostgresMagicLinkAdapter
from app.core.local_backend.db import LocalPostgresExecutor
from app.core.local_backend.healthz import healthz_router
from app.core.local_backend.oauth_google import oauth_router
from app.core.local_backend.rawsql import router as rawsql_router
from app.core.local_backend.storage import storage_router
from app.core.local_backend.stub_auth_port import StubAuthPort

# Spec M1 R7 — operators flip the magic-link channel without a redeploy
# by reading the env at request time; the lifespan reads the same env
# once at startup to decide whether to attach the magic-link adapters.
_MAGIC_LINK_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _magic_link_enabled() -> bool:
    """Return ``True`` iff ``APAP_AUTH_ENABLE_MAGIC_LINK`` is truthy.

    Mirrors :func:`app.core.auth_magic.routes._magic_link_enabled`'s
    truthy set so the lifespan matches the route gate. Centralised
    here (instead of imported from the route module) to avoid a
    circular import — the routes module imports nothing from
    ``local_backend``, but the lifespan imports both the routes and
    the local-backend internals; pulling the predicate keeps the
    edge direction single-source-of-truth (lifespan owns the env
    parsing; routes own the per-request parsing).
    """
    return (
        os.environ.get("APAP_AUTH_ENABLE_MAGIC_LINK", "").strip().lower()
        in _MAGIC_LINK_TRUTHY
    )


class _BaseUrlAwareConsoleTransport(ConsoleMailTransport):
    """Console transport that injects ``APAP_APP_BASE_URL`` as the base.

    The local FastAPI backend is spawned on a kernel-allocated port
    (see :mod:`tests.migration._local_backend_fixture`); the verify
    URL the magic-link transport emits must point at the same loopback
    so the F3 round-trip gate can ``GET`` it back. The default
    :class:`ConsoleMailTransport` uses whatever ``base_url`` the
    caller passed in, and the F1 adapter hard-codes ``""`` (see
    :mod:`app.core.auth_magic.postgres_adapter`); F3 closes the gap
    by overriding :meth:`send_magic_link` to read
    ``APAP_APP_BASE_URL`` from the spawned subprocess's env.

    The class lives in this module (not under ``app.core.auth_magic``)
    because it is F3-local-backend-only behaviour: production wiring
    would either inject ``settings.app_base_url`` at the route layer
    or have the M1.1 ``SMTPMailTransport`` build the URL itself. This
    subclass is the loopback-specific shim.
    """

    async def send_magic_link(
        self, email: str, raw_token: str, base_url: str
    ) -> None:
        """Append a JSON line whose ``verify_url`` carries the env-injected base.

        The caller-supplied ``base_url`` argument is ignored; the
        subprocess env (``APAP_APP_BASE_URL``) is authoritative for
        the loopback. Falling back to the caller's value when the env
        is empty keeps the transport usable in the integration-test
        path (``test_magic_link_routes.py``) where ``APAP_APP_BASE_URL``
        is unset and the test asserts the URL shape with the
        ``http://test`` httpx base.
        """
        effective_base = os.environ.get("APAP_APP_BASE_URL", "").strip()
        if not effective_base:
            effective_base = base_url
        await super().send_magic_link(email, raw_token, effective_base)


def create_app(*, db_dsn: str = "", oauth_configured: bool = False) -> FastAPI:
    """Build the local FastAPI application and mount its routers."""
    if not db_dsn or not db_dsn.strip():
        raise RuntimeError("db_dsn is required for the local backend")

    magic_enabled = _magic_link_enabled()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        executor = LocalPostgresExecutor(
            db_dsn,
            search_path=os.environ.get("APAP_LOCAL_DB_SCHEMA") or None,
        )
        application.state.local_postgres_executor = executor
        application.state.oauth_configured = oauth_configured
        if magic_enabled:
            # F3 (spec M1 T3.1) — wire the three magic-link ports onto
            # ``app.state`` so the F2 routes can resolve them via
            # :mod:`app.core.auth_magic.app_state`. The lifespan is the
            # sole owner; tests that need a fresh state rebuild the
            # app via :func:`tests.migration._local_backend_fixture.allocate_local_backend`.
            schema = os.environ.get("APAP_LOCAL_DB_SCHEMA") or None
            application.state.magic_link_port = PostgresMagicLinkAdapter(
                db_dsn, search_path=schema
            )
            application.state.mail_transport = _BaseUrlAwareConsoleTransport()
            application.state.auth_port = StubAuthPort()
        try:
            yield
        finally:
            executor.close()

    application = FastAPI(title="APAP local backend", lifespan=lifespan)
    application.include_router(healthz_router)
    application.include_router(rawsql_router, prefix="/api")
    application.include_router(storage_router, prefix="/api")
    application.include_router(oauth_router, prefix="/api")
    if magic_enabled:
        # F3 (spec M1 T3.1) — mount the magic-link routes onto the same
        # ``application`` so the lifespan-attached ``app.state`` ports
        # are visible to them via :mod:`app.core.auth_magic.app_state`.
        # The import is local (not module-level) so the production
        # factory (no magic-link flag) does not pull the route module's
        # graph into its import tree.
        from app.core.auth_magic.routes import router as magic_router

        application.include_router(magic_router)

        # F3 debug-only route (spec M1 T3.4) — seed a known user so the
        # round-trip gate can plant ``magic-link-test@apap.local``
        # without provisioning a real ``usuarios_autorizados`` table.
        # The route is registered ONLY when ``APAP_AUTH_ENABLE_MAGIC_LINK``
        # is truthy; production factories (without the flag) do not
        # expose ``/_test/seed_user`` at all. The route calls the
        # :class:`StubAuthPort.add` helper (the F2 test-stub shape),
        # not the Protocol-level ``add_authorized_user`` (the use-case
        # shape), because the stub implements the former and not the
        # latter.
        @application.post("/_test/seed_user")
        async def test_seed_user(request: Request) -> JSONResponse:
            body: Any = await request.json()
            if not isinstance(body, dict):
                return JSONResponse(
                    {"error": "invalid_request", "detail": "body must be a JSON object"},
                    status_code=400,
                )
            email_raw = body.get("email")
            if not isinstance(email_raw, str) or not email_raw.strip():
                return JSONResponse(
                    {"error": "invalid_request", "detail": "email is required"},
                    status_code=400,
                )
            rol_raw = body.get("rol", "developer")
            if not isinstance(rol_raw, str):
                rol_raw = "developer"
            auth_port = application.state.auth_port
            user = auth_port.add(email_raw, rol_raw)
            return JSONResponse(
                {
                    "id": user.id,
                    "email": user.email,
                    "rol": user.rol.value,
                    "active": user.active,
                }
            )

    return application


__all__ = ["create_app", "healthz_router", "oauth_router", "rawsql_router", "storage_router"]
