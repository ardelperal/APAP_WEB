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

Regla 7 del code quality: los redirects no son exceptions. La guarda
devuelve un ``RedirectResponse`` en lugar de raise ``HTTPException`` —
es control de flujo, no un error HTTP.
"""

from __future__ import annotations

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from starlette.responses import Response

from app.core.config import get_settings
from app.core.insforge import InsForgeClient
from app.core.session import read_session, session_cookie_name


def get_insforge_client_dep():
    """Dependencia de FastAPI: produce un cliente InsForge por peticion.

    Implementado como generador para garantizar que ``close()`` se
    ejecuta al final de cada request, incluso si el handler levanta una
    excepcion. ``InsForgeClient`` envuelve un ``httpx.Client``; sin
    ``close`` explicito, las conexiones HTTP se acumulan (resource
    leak detectado en el code review externo, problema #3).

    FastAPI ejecuta el ``finally`` del generador despues de que el
    handler retorna o propaga una excepcion, por lo que el ciclo de
    vida del cliente queda atado al del request.

    Tests pueden sobreescribirlo con ``app.dependency_overrides[...]``;
    el override debe devolver un objeto que responda a ``close()`` con
    la misma semantica.

    Usar como dependencia de FastAPI:
    ``client: InsForgeClient = Depends(get_insforge_client_dep)``.
    """
    settings = get_settings()
    client = InsForgeClient(settings.insforge_url, settings.insforge_service_key)
    try:
        yield client
    finally:
        client.close()


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


def return_early_if_response(value: object) -> Response | None:
    """Helper regla 7: si ``value`` es un ``Response`` (redirect), lo retorna.

    Los handlers que usan :func:`require_authorized_user` reciben un
    ``Response | dict``. Si la dep devolvio un ``RedirectResponse`` (no
    hay sesion, o ``is_authorized=False``), el handler DEBE retornar
    ese response al cliente sin tocar la logica de negocio:

    .. code-block:: python

        def handler(
            current_user: Response | dict = Depends(require_authorized_user),
        ):
            if (early := return_early_if_response(current_user)) is not None:
                return early
            # current_user es dict; logica de negocio.

    Sin este check, ``current_user.get(...)`` falla con ``AttributeError``
    porque un ``RedirectResponse`` no tiene ``.get``.
    """
    if isinstance(value, Response):
        return value
    return None


def require_authorized_user(
    request: Request,
    payload: dict | None = Depends(get_current_user_optional),
) -> Response | dict:
    """Dependencia de FastAPI: exige una sesion con ``is_authorized=True``.

    Comportamiento:

    - Si no hay sesion, devuelve ``RedirectResponse`` 302 a ``/login``.
    - Si la sesion no tiene ``is_authorized=True`` (e.g. un developer
      desactivo al usuario via ``/admin/users/{id}/deactivate`` despues
      de emitir la cookie), devuelve ``RedirectResponse`` 302 a
      ``/unauthorized``.
    - Si todo OK, devuelve el payload de la sesion al handler.

    Regla 7 del code quality: los redirects no son exceptions. La dep
    devuelve un ``Response`` (no raise ``HTTPException``, que esta
    reservada para errores HTTP reales). FastAPI entrega el
    ``Response`` al cliente sin invocar al handler — pero el handler
    todavia recibe el valor de retorno y DEBE chequear
    ``isinstance(user, Response)`` antes de tratarlo como dict.
    """
    if not payload:
        return RedirectResponse(url="/login", status_code=302)
    if not payload.get("is_authorized", True):
        return RedirectResponse(url="/unauthorized", status_code=302)
    return payload
