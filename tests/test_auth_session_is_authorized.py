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
  ``app.state._auth_users_port`` / ``app.state._oauth_port`` (Phase 3
  pattern) se aplica aqui porque la ruta vive en ``app.main`` y usa
  ``Depends(get_auth_users_port)`` + ``Depends(get_oauth_port)``
  directamente.
- Los tests 2-4 son unit tests de la funcion ``require_authorized_user``
  (importada desde ``app.modules.animals.routes``, donde vive el codigo
  que sera extraido a ``app.core.auth_dependencies``). Se llaman como
  funciones puras con un ``payload`` explicito, no como route tests,
  porque las rutas protegidas (``/animales``, ``/voluntarios``)
  instancian un :class:`SqlExecutor` real via la dep local
  ``_client_dep`` (que no pasa por ``Depends(get_insforge_client_dep)``);
  invocarla como unitaria mantiene el test enfocado en la guarda de auth
  y evita ruido de red en CI.

Patron: ``app.state._auth_users_port`` + ``app.state._oauth_port`` con
fakes que implementan ``SqlExecutor`` (Protocol) y ``OAuthPort``
(Protocol), igual que ``tests/test_auth_flow.py``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.responses import RedirectResponse

from app.core.local_backend.auth_adapter import LocalBackendAuthUsersAdapter
from app.core.ports.oauth_port import OAuthUser
from app.core.session import session_cookie_name, write_session
from app.main import app
from app.modules.animals.routes import require_authorized_user


class _FakeSqlExecutor:
    """Minimal ``SqlExecutor`` Protocol implementation for these tests.

    Mirrors the same-named class in ``tests/test_auth.py`` — the
    queue-based response strategy is enough for the auth-revalidation
    SELECTs that :func:`require_authorized_user` issues (no need for the
    ``set_handler`` strategy used by the schema / CRUD tests).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[object]]] = []
        self._responses: list[list[dict[str, object]]] = []

    def set_response(self, rows: list[dict[str, object]]) -> None:
        self._responses = [rows]

    def execute_sql(
        self, query: str, params: list[object] | None = None
    ) -> list[dict[str, object]]:
        self.calls.append((query, list(params or [])))
        if self._responses:
            return self._responses.pop(0)
        return []


class _FakeOAuthPort:
    """Fake :class:`OAuthPort` that returns a configured :class:`OAuthUser`.

    Used to inject the OAuth port via ``app.state._oauth_port`` so the
    :func:`get_oauth_port` DI provider yields this fake instead of
    constructing the real :class:`LocalBackendOAuthAdapter` (which would
    issue a real HTTP call we cannot let go through CI).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.exchange_user = OAuthUser(id="u-1", email="user@example.com")

    def _set_exchange_user(self, *, user_id: str, email: str) -> None:
        """Configure the OAuthUser the next exchange call returns."""
        self.exchange_user = OAuthUser(id=user_id, email=email)

    def start_google_login(self, redirect_uri: str) -> tuple[str, Any]:
        from app.core.domain.oauth import PkcePair

        self.calls.append(("start_google_login", (redirect_uri,)))
        return (
            "https://accounts.google.com/o/oauth2/v2/auth",
            PkcePair(code_verifier="v", code_challenge="c"),
        )

    def exchange_insforge_oauth_code(self, insforge_code: str, code_verifier: str) -> OAuthUser:
        self.calls.append(("exchange_insforge_oauth_code", (insforge_code, code_verifier)))
        return self.exchange_user

    def exchange_google_oauth_code(
        self, code: str, code_verifier: str, redirect_uri: str
    ) -> OAuthUser:
        self.calls.append(("exchange_google_oauth_code", (code, code_verifier, redirect_uri)))
        return self.exchange_user


class _FakeAuthSession:
    """Bundle of fake SQL executor + OAuth port for auth session tests.

    The original test fixture exposed a single ``_FakeInsForge`` object
    that handled both the SQL executor and the OAuth exchange. With the
    Phase 3 split each concern has its own port (and therefore its own
    fake), so this thin wrapper keeps the ``fake_insforge`` ergonomic API
    — callers mutate the user row via ``set_user_by_email(row)`` and
    the OAuth exchange result via ``set_oauth_user(id, email)``.
    """

    def __init__(self) -> None:
        self.executor = _FakeSqlExecutor()
        self.oauth_port = _FakeOAuthPort()
        self.auth_port = LocalBackendAuthUsersAdapter(self.executor)
        # Default: an active developer so the /auth/callback happy-path
        # test succeeds without first having to populate the fixture.
        self.set_user_by_email(
            {
                "id": "u-db",
                "email": "ardelperal@gmail.com",
                "rol": "developer",
                "activo": True,
            }
        )

    def set_user_by_email(self, row: dict[str, object] | None) -> None:
        """Configure the row :func:`get_user_by_email` returns."""
        self.executor.set_response([dict(row)] if row else [])

    def set_oauth_user(self, *, user_id: str, email: str) -> None:
        """Configure the :class:`OAuthUser` returned by the OAuth exchange."""
        self.oauth_port._set_exchange_user(user_id=user_id, email=email)


@pytest.fixture
def fake_insforge() -> _FakeAuthSession:
    """Sustituye ``get_auth_users_port`` + ``get_oauth_port`` por fakes."""
    fake = _FakeAuthSession()

    # Phase 3 pattern: inject via app.state; the DI providers check
    # these first before constructing the production adapters.
    app.state._auth_users_port = fake.auth_port
    app.state._oauth_port = fake.oauth_port

    yield fake

    # Cleanup so the next test that does not declare the fixture gets
    # the conftest autouse default state instead of a leaked override.
    if hasattr(app.state, "_auth_users_port"):
        delattr(app.state, "_auth_users_port")
    if hasattr(app.state, "_oauth_port"):
        delattr(app.state, "_oauth_port")


# --- /auth/callback escribe is_authorized --------------------------------


async def test_callback_escribe_is_authorized_en_sesion(
    client: httpx.AsyncClient, fake_insforge: _FakeAuthSession
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
    fake_insforge.set_user_by_email(
        {
            "id": "u-1",
            "email": "user@example.com",
            "rol": "key_user",
            "activo": True,
        }
    )
    fake_insforge.set_oauth_user(user_id="u-1", email="user@example.com")

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

    Issue #143: la dep ahora recibe un ``SqlExecutor`` y revalida la
    autorizacion contra la DB. Se le pasa un fake que devuelve al usuario
    ACTIVO con el mismo ``rol`` del payload, de modo que el veredicto lo
    decida ``is_authorized`` (el contrato que este archivo fija) y no un
    cambio de rol o una desactivacion inyectada por el fake.
    """
    # ``request`` no se usa cuando el payload ya viene resuelto; pasamos
    # un MagicMock solo para satisfacer la firma.
    fake = _FakeSqlExecutor()
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
