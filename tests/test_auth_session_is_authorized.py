"""Regression tests para el flag ``is_authorized`` en la sesion (P0 VOL-01).

Code review VOL-01 detecto un bug bloqueante: el handler de
``/auth/callback`` no escribia el flag ``is_authorized`` en el payload
de la sesion, pero ``require_authorized_user`` (duplicado en
``app/modules/animals/routes.py`` y ``app/modules/voluntarios/routes.py``)
lo leia con default ``True``. Resultado: la desactivacion de un usuario
via ``/admin/users/{id}/deactivate`` no tomaba efecto hasta que la cookie
de sesion expiraba (max_age = 7 dias).

Este archivo fija el contrato:

- ``/auth/callback`` escribe ``is_authorized`` en el payload de la sesion,
  tomado del campo ``activo`` del registro de ``usuarios_autorizados``.
- ``require_authorized_user`` rechaza (HTTPException 302 a /unauthorized)
  las sesiones con ``is_authorized=False``.
- ``require_authorized_user`` acepta las sesiones con ``is_authorized=True``.

Decisiones de diseno del test:

- El test de callback (test 1) es un route test contra ``/auth/callback``
  porque es la unica ruta donde se observa el bug P0. El override
  ``app.dependency_overrides[get_local_backend_client]`` se aplica aqui
  porque la ruta vive en ``app.main`` y usa ``Depends(get_local_backend_client)``
  directamente.
- Los tests 2-4 son unit tests de la funcion ``require_authorized_user``
  (importada desde ``app.modules.animals.routes``, donde vive el codigo
  que sera extraido a ``app.core.auth_dependencies``). Se llaman como
  funciones puras con un ``payload`` explicito, no como route tests,
  porque las rutas protegidas (``/animales``, ``/voluntarios``)
  instancian un ``LocalPostgresExecutor`` real via la dep local ``_client_dep``
  (que no pasa por ``Depends(get_local_backend_client)``); invocarla como
  unitaria mantiene el test enfocado en la guarda de auth y evita
  ruido de red en CI.

Patron: ``app.dependency_overrides[get_local_backend_client]`` con un
``LocalPostgresExecutor`` falso, igual que ``tests/test_auth_flow.py``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.responses import RedirectResponse

from app.core.domain.auth.user import AuthorizedUser
from app.core.roles import Rol

# LocalPostgresExecutor removed - we use _FakeLocalBackend directly
from app.core.session import session_cookie_name, write_session
from app.main import app, get_local_backend_client
from app.modules.animals.routes import require_authorized_user


class _FakeAuthUsersPort:
    """Minimal fake AuthUsersPort for the callback test.

    Delegates get_user_by_email_response to the shared _FakeLocalBackend
    so the test only needs to set fake_local_backend.get_user_by_email_response.
    """

    def __init__(self, fake_backend: _FakeLocalBackend | None = None) -> None:
        self._fake_backend = fake_backend

    @property
    def get_user_by_email_response(self) -> dict | None:
        if self._fake_backend is not None:
            return self._fake_backend.get_user_by_email_response
        return None

    @get_user_by_email_response.setter
    def get_user_by_email_response(self, value: dict | None) -> None:
        if self._fake_backend is not None:
            self._fake_backend.get_user_by_email_response = value

    def _build_user(self, row: dict) -> AuthorizedUser:
        return AuthorizedUser(
            id=row["id"],
            email=row["email"],
            rol=Rol(row["rol"]),
            active=row["activo"],
        )

    def get_user_by_email(self, email: str) -> AuthorizedUser | None:
        row = self.get_user_by_email_response
        if row is None:
            return None
        if row.get("email") != email:
            return None
        return self._build_user(row)

    def check_email_taken(self, email: str) -> bool:
        raise NotImplementedError

    def list_authorized_users(self) -> list[AuthorizedUser]:
        raise NotImplementedError




class _FakeOAuthPort:
    """Minimal fake OAuthPort for the callback test.

    Delegates exchange result to the shared _FakeLocalBackend
    so the test only needs to set ``fake_local_backend.get_user_by_email_response``.
    """

    def __init__(self, fake_backend: _FakeLocalBackend | None = None) -> None:
        self._fake_backend = fake_backend

    def _build_user(self) -> object:
        from app.core.ports.oauth_port import OAuthUser
        row = self._fake_backend.get_user_by_email_response if self._fake_backend else None
        email = row.get("email", "unknown") if row else "unknown"
        user_id = row.get("id", "u-x") if row else "u-x"
        return OAuthUser(id=user_id, email=email)

    def start_google_login(self, redirect_uri: str):
        from app.core.domain.oauth import PkcePair
        return "https://fake.google/auth", PkcePair(
            code_verifier="test",
            code_challenge="test",
        )

    def exchange_oauth_code(self, oauth_code: str, code_verifier: str):
        return self._build_user()

    def exchange_google_oauth_code(self, code: str, code_verifier: str, redirect_uri: str):
        return self._build_user()


class _FakeLocalBackend:
    """Stand-in en proceso del cliente LocalBackend para el test de sesion."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[object]]] = []
        self._responses: list[list[dict[str, object]]] = []
        self.get_user_by_email_response: dict[str, object] | None = None

    def set_response(self, rows: list[dict[str, object]]) -> None:
        """Configure the rows execute_sql returns for the user query."""
        self._responses = rows

    def execute_sql(self, query, params=None):
        if (
            "SELECT id, email, rol, activo" in query
            and "FROM usuarios_autorizados" in query
        ):
            if self._responses:
                return self._responses
            row = self.get_user_by_email_response
            return [dict(row)] if row else []
        return []

    def exchange_google_oauth_code(
        self,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ):
        from app.core.local_backend import OAuthExchangeResult, OAuthUser

        row = self.get_user_by_email_response or {}
        return OAuthExchangeResult(
            token="jwt-from-local_backend",
            user=OAuthUser(id=str(row.get("id", "u-x")), email=str(row.get("email", ""))),
        )


@pytest.fixture
def fake_local_backend() -> _FakeLocalBackend:
    """Sustituye ``get_local_backend_client`` y los puertos auth/oauth durante el test."""
    fake = _FakeLocalBackend()
    app.state._auth_users_port = _FakeAuthUsersPort(fake)
    app.state._oauth_port = _FakeOAuthPort(fake)
    app.dependency_overrides[get_local_backend_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_local_backend_client, None)
    app.state._auth_users_port = None  # type: ignore[assignment]
    app.state._oauth_port = None  # type: ignore[assignment]


# --- /auth/callback escribe is_authorized --------------------------------


async def test_callback_escribe_is_authorized_en_sesion(
    client: httpx.AsyncClient, fake_local_backend: _FakeLocalBackend
) -> None:
    """Tras un callback exitoso, el payload de sesion incluye ``is_authorized``
    tomado del campo ``activo`` del registro de ``usuarios_autorizados``.

    Este test reproduce el bug P0: antes del fix el flag nunca se
    escribia, por lo que ``admin/users/{id}/deactivate`` quedaba sin
    efecto durante los 7 dias de vida de la cookie.
    """
    from app.core.config import get_settings
    from app.core.session import read_session

    settings = get_settings()
    pkce_token = write_session({"code_verifier": "verifier-abc"}, secret=settings.session_secret)
    client.cookies.set("apap_pkce", pkce_token)
    fake_local_backend.get_user_by_email_response = {
        "id": "u-1",
        "email": "user@example.com",
        "rol": "key_user",
        "activo": True,
    }

    response = await client.get(
        "/auth/callback", params={"code": "google-code"}, follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/"
    session_cookie = client.cookies.get(session_cookie_name())
    assert session_cookie, "el callback debe emitir la cookie de sesion"
    decoded = read_session(session_cookie, secret=settings.session_secret)
    assert decoded is not None
    assert decoded.get("is_authorized") is True, (
        "el callback debe escribir is_authorized=True cuando el usuario esta activo"
    )
    # Sanity: el resto de los campos del payload no se rompen.
    assert decoded["email"] == "user@example.com"
    assert decoded["rol"] == "key_user"
    assert decoded["user_id"] == "u-1"


# --- require_authorized_user: contrato de la dependencia -----------------


def _invoke_require(payload: dict[str, Any] | None) -> RedirectResponse | dict:
    """Invoca ``require_authorized_user`` como funcion pura con el payload
    ya resuelto (sin pasar por el sistema de Depends de FastAPI).

    Devuelve el payload si la dependencia lo acepta; devuelve un
    ``RedirectResponse`` (no raise) si lo rechaza. Esta es la regla 7
    del code quality: los redirects no son exceptions — son control
    flow via ``Response``, no errores HTTP.

    Issue #143: la dep ahora recibe un ``LocalPostgresExecutor`` y revalida la
    autorizacion contra la DB. Se le pasa un fake que devuelve al usuario
    ACTIVO con el mismo ``rol`` del payload, de modo que el veredicto lo
    decida ``is_authorized`` (el contrato que este archivo fija) y no un
    cambio de rol o una desactivacion inyectada por el fake.
    """
    # ``request`` no se usa cuando el payload ya viene resuelto; pasamos
    # un MagicMock solo para satisfacer la firma.
    fake = _FakeLocalBackend()
    if payload is not None:
        fake.set_response(
            [
                {
                    "id": "u-db",
                    "email": payload.get("email", "u@example.com"),
                    "rol": payload.get("rol", "key_user"),
                    "activo": True,
                }
            ]
        )
    return require_authorized_user(request=MagicMock(), payload=payload, client=fake)


def test_require_authorized_user_rechaza_sesion_con_is_authorized_false() -> None:
    """Una sesion con ``is_authorized=False`` redirige a /unauthorized (302).

    Cubre el caso post-fix: un developer desactiva al usuario via
    /admin/users/{id}/deactivate y la siguiente peticion a una ruta
    protegida (p.ej. /animales) ya no debe pasar. La dep devuelve un
    ``RedirectResponse`` (no raise) — la guarda de auth es control de
    flujo, no un error HTTP.
    """
    result = _invoke_require(
        {
            "email": "u@example.com",
            "rol": "key_user",
            "user_id": "u-1",
            "is_authorized": False,
        }
    )

    assert isinstance(result, RedirectResponse)
    assert result.status_code == 302
    assert result.headers["location"] == "/unauthorized"


def test_require_authorized_user_acepta_sesion_con_is_authorized_true() -> None:
    """Una sesion con ``is_authorized=True`` pasa la guarda y devuelve el payload."""
    # Reset the in-process auth cache so the previous tests' cached
    # verdicts for ``u@example.com`` do not leak into this assertion.
    from app.core import auth_cache

    auth_cache.invalidate_all()

    payload = {
        "email": "u@example.com",
        "rol": "key_user",
        "user_id": "u-1",
        "is_authorized": True,
    }
    result = _invoke_require(payload)
    assert result == payload


def test_require_authorized_user_rechaza_sesion_ausente() -> None:
    """Una sesion ausente (cookie sin firma o sin cookie) redirige a /login (302).

    No es la guarda de ``is_authorized``: es la guarda anterior, que
    existe desde la primera version y se mantiene. La cubrimos para
    dejar claro que ``is_authorized`` no es el unico gate.
    """
    result = _invoke_require(None)

    assert isinstance(result, RedirectResponse)
    assert result.status_code == 302
    assert result.headers["location"] == "/login"
