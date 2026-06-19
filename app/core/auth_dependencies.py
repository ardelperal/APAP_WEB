"""Dependencias de auth compartidas entre ``app.main`` y los routers de modulos.

Estas dependencias se comparten entre ``app.main`` (rutas de auth/admin
y el ``/auth/callback`` que emite la sesion) y los routers de modulos
(``app.modules.animals.routes``, ``app.modules.voluntarios.routes``, y
los que vendran) para evitar el copy-paste y mantener una unica fuente
de verdad de la inyeccion de dependencias relacionadas con la sesion.

Las firmas publicas son:

- :func:`get_insforge_client_dep`  -- cliente InsForge por peticion.
- :func:`get_current_user_optional` -- payload de sesion o ``None``.
- :func:`require_authorized_user` -- guarda que exige ``is_authorized``.

El contrato de :func:`require_authorized_user` lo fija
``tests/test_auth_session_is_authorized.py`` (regression test del P0
de la code review VOL-01). El default ``True`` en
``payload.get(\"is_authorized\", True)`` se mantiene por compatibilidad
con sesiones emitidas antes del fix; el fix vive en escribir el flag
en ``/auth/callback``, no en cambiar el default.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from app.core.config import get_settings
from app.core.insforge import InsForgeClient
from app.core.session import read_session, session_cookie_name


def get_insforge_client_dep() -> InsForgeClient:
    """Dependencia de FastAPI: produce un cliente InsForge por peticion.

    Lee la configuracion del state de la app y construye un cliente
    InsForge nuevo para cada peticion. Tests pueden sobreescribirlo
    con ``app.dependency_overrides[...]``.

    Usar como dependencia de FastAPI:
    ``client: InsForgeClient = Depends(get_insforge_client_dep)``.
    """
    settings = get_settings()
    return InsForgeClient(settings.insforge_url, settings.insforge_service_key)


def get_current_user_optional(request: Request) -> dict | None:
    """Dependencia de FastAPI: devuelve el payload de la sesion, o None.

    Lee la cookie de sesion firmada y devuelve el payload como dict,
    o ``None`` si la cookie no existe o la firma no es valida. Usar
    en handlers que quieran render condicional (mostrar el nombre de
    usuario si esta logueado) pero que no requieren auth.
    """
    settings = get_settings()
    token = request.cookies.get(session_cookie_name())
    if not token:
        return None
    return read_session(token, secret=settings.session_secret)


def require_authorized_user(
    request: Request,
    payload: dict | None = Depends(get_current_user_optional),
) -> dict:
    """Dependencia de FastAPI: exige una sesion con ``is_authorized=True``.

    Comportamiento:

    - Si no hay sesion, levanta ``HTTPException`` 302 con ``Location: /login``.
    - Si la sesion no tiene ``is_authorized=True`` (e.g. un developer
      desactivo al usuario via ``/admin/users/{id}/deactivate`` despues
      de emitir la cookie), levanta ``HTTPException`` 302 con
      ``Location: /unauthorized``.
    - Si todo OK, devuelve el payload de la sesion al handler.
    """
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND, headers={"location": "/login"}
        )
    if not payload.get("is_authorized", True):
        raise HTTPException(
            status_code=status.HTTP_302_FOUND, headers={"location": "/unauthorized"}
        )
    return payload
