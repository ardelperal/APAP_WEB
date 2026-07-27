"""Tests for the developer-only admin panel (/admin)."""

from __future__ import annotations

import httpx
import pytest

from app.core.insforge import InsForgeClient, InsForgeError
from app.core.session import session_cookie_name, write_session
from app.main import app, get_insforge_client
from tests.conftest import make_csrf_request


class _FakeInsForge(InsForgeClient):
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
            row = self.deactivate_user_response
            return [dict(row)] if row else []
        return []


@pytest.fixture
def fake_insforge() -> _FakeInsForge:
    fake = _FakeInsForge()
    app.dependency_overrides[get_insforge_client] = lambda: fake
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
