"""Tests for the developer-only admin panel (/admin)."""

from __future__ import annotations

import httpx
import pytest

from app.core.insforge import InsForgeClient
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


async def test_admin_add_user_inserts_and_redirects(
    client: httpx.AsyncClient, fake_insforge: _FakeInsForge
) -> None:
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
        form_data={"email": "new@example.com", "role": "key_user"},
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/admin"


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
        form_data={"email": "new@example.com", "role": "key_user"},
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
