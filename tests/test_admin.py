"""Tests for the developer-only admin panel (/admin)."""

from __future__ import annotations

import re

import httpx
import pytest

from app.core.data_access import BackendError as InsForgeError
from app.core.data_access import SqlExecutor
from app.core.session import session_cookie_name, write_session
from app.main import app, get_insforge_client
from tests.conftest import make_csrf_request


class _FakeInsForge(SqlExecutor):
    def __init__(self) -> None:
        self.list_users_response: list[dict] = []
        self.add_user_response: dict = {
            "id": "u-new",
            "email": "new@example.com",
            "rol": "key_user",
            "activo": True,
            "fecha_alta": "2026-06-17T00:00:00Z",
        }
        self.deactivate_user_response: dict | None = None
        # Issue #143: rol returned by the per-request authorization
        # revalidation SELECT. Defaults to "developer" (most /admin tests
        # log in as developer); the non-developer rejection tests set this
        # to "key_user" so require_authorized_user's role-refresh reflects
        # the same rol the test's cookie carries.
        self.auth_rol: str = "developer"
        # For last-developer guard disambiguation:
        self.deactivate_user_id: str | None = None  # user_id passed to deactivate
        # Separate storage for get_user_by_id so it doesn't pollute list_users_response
        self._user_lookup_response: dict | None = None

    def execute_sql(self, query, params=None):  # type: ignore[override]
        from tests.conftest import auth_reval_rows

        _reval = auth_reval_rows(query, params, rol=self.auth_rol)
        if _reval is not None:
            return _reval
        if "ORDER BY fecha_alta DESC" in query:
            return list(self.list_users_response)
        if "INSERT INTO usuarios_autorizados" in query and "VALUES" in query:
            return [dict(self.add_user_response)]
        if "SET activo = false" in query:
            # Track the user_id being deactivated for disambiguation
            if params:
                self.deactivate_user_id = params[0]
            row = self.deactivate_user_response
            return [dict(row)] if row else []
        # _has_other_active_developers: SELECT EXISTS for last-developer guard
        if "SELECT EXISTS" in query and "developer" in query:
            # If deactivate_user_response is None → last developer guard fires
            # Return True if there IS another developer (deactivate succeeds)
            # Return False if this IS the last developer (guard fires)
            return [{"exists": self.deactivate_user_response is not None}]
        # get_user_by_id for disambiguation — uses separate storage
        # Normalise whitespace so the multi-line SQL matches regardless of
        # leading/trailing whitespace.
        normalised = re.sub(r"\s+", " ", query.strip())
        if "SELECT id, email, rol, activo FROM usuarios_autorizados WHERE id = $1" in normalised:
            return [self._user_lookup_response] if self._user_lookup_response else []
        return []
        return []


@pytest.fixture
def fake_insforge() -> _FakeInsForge:
    fake = _FakeInsForge()
    app.dependency_overrides[get_insforge_client] = lambda: fake
    # Slice 6 (admin handlers): the admin routes now compose AuthUsersPort
    # via the ``get_auth_users_port`` dep, which resolves the client from
    # ``app.state.insforge_client``. Set it here so both the legacy
    # dep override AND the new port dep see the fake.
    app.state.insforge_client = fake
    # Slice 6 (admin template adapter): the admin routes wrap Jinja via
    # ``get_admin_template_adapter`` which reads ``app.state.templates``.
    # In production the lifespan sets it (via ``create_app``); in tests
    # the lifespan is skipped, so set it explicitly with the same
    # context processors as production so ``{% extends base_template %}``
    # resolves.
    from pathlib import Path

    from fastapi.templating import Jinja2Templates

    from app.core.csrf import csrf_token_context_processor
    from app.core.middleware import base_template_context_processor

    _templates_dir = Path(__file__).resolve().parent.parent / "app" / "templates"
    app.state.templates = Jinja2Templates(
        directory=str(_templates_dir),
        context_processors=[
            csrf_token_context_processor,
            base_template_context_processor,
        ],
    )
    yield fake
    app.dependency_overrides.pop(get_insforge_client, None)


def _login_as(
    client: httpx.AsyncClient,
    secret: str,
    *,
    rol: str,
    email: str,
    user_id: str,
    is_authorized: bool = True,
) -> None:
    """Install a session cookie on the client so the route sees a logged-in user.

    ``is_authorized`` defaults to ``True`` para mantener compat con los
    tests existentes (que asumian sesion valida). Los nuevos tests de
    regresion del gap P2-inherited pasan ``is_authorized=False`` para
    verificar que las rutas /admin rechazan al developer desactivado.

    PR-5B2: also writes a ``csrf_token`` into the session payload so
    the CsrfMiddleware can validate POSTs from this test client.
    """
    token = write_session(
        {
            "email": email,
            "rol": rol,
            "user_id": user_id,
            "is_authorized": is_authorized,
            "csrf_token": "test-csrf-token-admin",
        },
        secret=secret,
    )
    client.cookies.set(session_cookie_name(), token)


# --- /admin -----------------------------------------------------------------


async def test_admin_redirects_to_login_when_not_authed(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/admin", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/login"


async def test_admin_redirects_to_unauthorized_when_rol_not_developer(
    client: httpx.AsyncClient, fake_insforge: _FakeInsForge
) -> None:
    from app.core.config import get_settings

    fake_insforge.auth_rol = "key_user"  # issue #143: DB revalidation says key_user
    _login_as(
        client,
        get_settings().session_secret,
        rol="key_user",
        email="ana@example.com",
        user_id="u-ana",
    )

    response = await client.get("/admin", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/unauthorized"


async def test_admin_renders_user_table_for_developer(
    client: httpx.AsyncClient, fake_insforge: _FakeInsForge
) -> None:
    from app.core.config import get_settings

    fake_insforge.list_users_response = [
        {
            "id": "u-1",
            "email": "ana@example.com",
            "rol": "key_user",
            "activo": True,
            "fecha_alta": "2026-06-17T00:00:00Z",
        },
        {
            "id": "u-2",
            "email": "eva@example.com",
            "rol": "reader",
            "activo": False,
            "fecha_alta": "2026-06-16T00:00:00Z",
        },
    ]
    _login_as(
        client,
        get_settings().session_secret,
        rol="developer",
        email="root@example.com",
        user_id="u-root",
    )

    response = await client.get("/admin", follow_redirects=False)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "ana@example.com" in response.text
    assert "eva@example.com" in response.text
    assert "key_user" in response.text


# --- POST /admin/users ------------------------------------------------------


async def test_admin_add_user_inserts_and_renders_admin_page(
    client: httpx.AsyncClient, fake_insforge: _FakeInsForge
) -> None:
    """On success the admin page re-renders with no error message."""
    from app.core.config import get_settings

    _login_as(
        client,
        get_settings().session_secret,
        rol="developer",
        email="root@example.com",
        user_id="u-root",
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/admin/users",
        form_data={"email": "new@example.com", "rol": "key_user"},
    )

    assert response.status_code == 200
    # No error message in the page
    assert "email already authorized" not in response.text


async def test_admin_add_user_with_duplicate_email_shows_error(
    client: httpx.AsyncClient, fake_insforge: _FakeInsForge
) -> None:
    """When the email is already authorized the admin page re-renders with error context."""
    from app.core.config import get_settings

    _login_as(
        client,
        get_settings().session_secret,
        rol="developer",
        email="root@example.com",
        user_id="u-root",
    )
    # Simulate the pre-check returning an existing user
    fake_insforge.add_user_response = None  # not used for pre-check

    def execute_sql(query, params=None):
        from tests.conftest import auth_reval_rows
        _reval = auth_reval_rows(query, params, rol="developer")
        if _reval is not None:
            return _reval
        if "ORDER BY fecha_alta DESC" in query:
            return []
        if "SELECT" in query and "usuarios_autorizados" in query:
            # Pre-check finds existing user
            return [{"id": "u-1", "email": "existing@example.com", "rol": "key_user", "activo": True}]
        return []

    # Override the fake to return duplicate on pre-check
    fake_insforge.execute_sql = execute_sql

    response = await make_csrf_request(
        client,
        "POST",
        "/admin/users",
        form_data={"email": "new@example.com", "rol": "key_user"},
    )

    assert response.status_code == 200
    assert "email already authorized" in response.text


async def test_admin_add_user_with_invalid_role_redirects_without_calling_sql(
    client: httpx.AsyncClient, fake_insforge: _FakeInsForge
) -> None:
    """An invalid rol short-circuits before any SQL is sent."""
    from app.core.config import get_settings

    _login_as(
        client,
        get_settings().session_secret,
        rol="developer",
        email="root@example.com",
        user_id="u-root",
    )
    fake_insforge.add_user_response = {"id": "should-not-be-used"}

    response = await make_csrf_request(
        client,
        "POST",
        "/admin/users",
        form_data={"email": "new@example.com", "rol": "hacker"},
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/admin"


async def test_admin_add_user_rejects_non_developer(
    client: httpx.AsyncClient, fake_insforge: _FakeInsForge
) -> None:
    from app.core.config import get_settings

    fake_insforge.auth_rol = "key_user"  # issue #143: DB revalidation says key_user
    _login_as(
        client,
        get_settings().session_secret,
        rol="key_user",
        email="ana@example.com",
        user_id="u-ana",
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/admin/users",
        form_data={"email": "new@example.com", "rol": "key_user"},
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/unauthorized"


# --- POST /admin/users/{id}/deactivate -------------------------------------


async def test_admin_deactivate_user_updates_and_redirects(
    client: httpx.AsyncClient, fake_insforge: _FakeInsForge
) -> None:
    from app.core.config import get_settings

    fake_insforge.deactivate_user_response = {
        "id": "u-1",
        "email": "a@b.com",
        "rol": "key_user",
        "activo": False,
    }
    _login_as(
        client,
        get_settings().session_secret,
        rol="developer",
        email="root@example.com",
        user_id="u-root",
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/admin/users/u-1/deactivate",
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/admin"


async def test_admin_deactivate_user_rejects_non_developer(
    client: httpx.AsyncClient, fake_insforge: _FakeInsForge
) -> None:
    from app.core.config import get_settings

    fake_insforge.auth_rol = "key_user"  # issue #143: DB revalidation says key_user
    _login_as(
        client,
        get_settings().session_secret,
        rol="key_user",
        email="ana@example.com",
        user_id="u-ana",
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/admin/users/u-1/deactivate",
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/unauthorized"


async def test_admin_deactivate_user_renders_flash_error_when_last_developer(
    client: httpx.AsyncClient, fake_insforge: _FakeInsForge
) -> None:
    """When deactivate_authorized_user raises ValueError, admin.html re-renders with flash.

    REQ-4 scenario: Deactivate last developer renders error flash.
    The route catches ValueError and re-renders admin.html with error_message,
    instead of redirecting to /admin.
    """
    from app.core.config import get_settings

    # Set up: deactivate returns empty (guard fires), list_users is empty.
    # _user_lookup_response has the developer so the ValueError fires.
    fake_insforge.deactivate_user_response = None  # zero rows from UPDATE → guard fires
    fake_insforge.list_users_response = []  # list_users returns empty in error path
    fake_insforge._user_lookup_response = {
        "id": "only-dev",
        "email": "only-dev@example.com",
        "rol": "developer",
        "activo": True,
        "fecha_alta": "2026-06-17T00:00:00Z",
    }
    # Track deactivate_user_id so SELECT EXISTS query uses it
    fake_insforge.deactivate_user_id = "only-dev"

    _login_as(
        client,
        get_settings().session_secret,
        rol="developer",
        email="only-dev@example.com",
        user_id="only-dev",
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/admin/users/only-dev/deactivate",
    )

    # Must re-render admin.html (status 200), NOT redirect (302)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # Error flash must be visible in the page
    assert "cannot deactivate the last active developer" in response.text


# --- P2-inherited: /admin debe rechazar sesiones con is_authorized=False -----
#
# Gap detectado en la primera revision del PR #90 (code-review-expert):
# /admin y /admin/users/{id}/deactivate usaban get_current_user_optional
# y solo chequeaban rol == "developer", sin pasar por require_authorized_user.
# Resultado: un developer con cookie <7d que fue desactivado desde /admin
# (p. ej. por otro developer) podia seguir entrando y mutando usuarios.
#
# Contrato: require_authorized_user redirige a /unauthorized cuando
# is_authorized=False. Las 3 rutas siguientes deben heredar esa guarda.


async def test_admin_redirects_to_unauthorized_when_is_authorized_false(
    client: httpx.AsyncClient, fake_insforge: _FakeInsForge
) -> None:
    from app.core.config import get_settings

    _login_as(
        client,
        get_settings().session_secret,
        rol="developer",
        email="root@example.com",
        user_id="u-root",
        is_authorized=False,
    )

    response = await client.get("/admin", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/unauthorized"


async def test_admin_add_user_redirects_when_is_authorized_false(
    client: httpx.AsyncClient, fake_insforge: _FakeInsForge
) -> None:
    from app.core.config import get_settings

    _login_as(
        client,
        get_settings().session_secret,
        rol="developer",
        email="root@example.com",
        user_id="u-root",
        is_authorized=False,
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/admin/users",
        form_data={"email": "new@example.com", "rol": "key_user"},
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/unauthorized"


async def test_admin_deactivate_user_redirects_when_is_authorized_false(
    client: httpx.AsyncClient, fake_insforge: _FakeInsForge
) -> None:
    from app.core.config import get_settings

    _login_as(
        client,
        get_settings().session_secret,
        rol="developer",
        email="root@example.com",
        user_id="u-root",
        is_authorized=False,
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/admin/users/u-1/deactivate",
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/unauthorized"


# --- §32.P4 (issues #277, #278): global InsForgeError handler ----------------
#
# The admin ``_add_user_or_error`` helper only catches ``ValueError`` from
# ``add_authorized_user`` (the duplicate-email path translates
# InsForgeError → ValueError inside the service). Any OTHER InsForgeError —
# transport failure, upstream 5xx, timeout — propagates uncaught and
# would produce a generic 500 page. This class covers the global handler
# that converts those into a 502 Bad Gateway with a non-leaking message.


class TestInsForgeErrorGlobalHandler:
    """AGENTS.md §32.P4: any route calling a service that reaches InsForge
    must handle both the domain error AND InsForgeError, OR a global
    handler must exist and be exercised by tests."""

    async def test_admin_add_user_returns_502_on_non_duplicate_insforge_error(
        self, client: httpx.AsyncClient, fake_insforge: _FakeInsForge
    ) -> None:
        """A non-duplicate InsForgeError (e.g. 5xx from upstream) returns
        502, not 500, per the §32.P4 anti-pattern fix."""
        from app.core.config import get_settings

        _login_as(
            client,
            get_settings().session_secret,
            rol="developer",
            email="root@example.com",
            user_id="u-root",
        )

        def execute_sql(query, params=None):
            from tests.conftest import auth_reval_rows

            _reval = auth_reval_rows(query, params, rol="developer")
            if _reval is not None:
                return _reval
            if "ORDER BY fecha_alta DESC" in query:
                return []
            if (
                "SELECT" in query
                and "usuarios_autorizados" in query
                and "activo = true" in query
            ):
                # add_authorized_user's pre-insert duplicate-check
                # returns no rows so we fall through to the INSERT branch.
                return []
            if "INSERT INTO usuarios_autorizados" in query and "VALUES" in query:
                # Simulate a transport-level 5xx from InsForge. The
                # service-layer translator only recognises "duplicate" /
                # "unique" substrings; every other InsForgeError re-raises
                # verbatim, which the global handler must convert to 502.
                raise InsForgeError(503, "service unavailable")
            return []

        fake_insforge.execute_sql = execute_sql

        response = await make_csrf_request(
            client,
            "POST",
            "/admin/users",
            form_data={"email": "new@example.com", "rol": "key_user"},
        )

        assert response.status_code == 502
        body = response.json()
        assert "Upstream database error" in body["detail"]
        # The raw InsForgeError repr must NOT leak to the client
        # (anti-pattern §32.P4: backend detail that does not belong in
        # the response body). InsForgeError.__str__ formats as
        # ``"InsForge {status_code}: {body!r}"`` so any leak would
        # surface the ``"InsForge 503"`` substring.
        assert "InsForge 503" not in response.text
        assert "service unavailable" not in response.text
