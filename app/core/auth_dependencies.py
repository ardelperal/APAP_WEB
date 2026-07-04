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
- :func:`require_writer_user` -- guarda que ademas exige rol de escritura
  (issue #144); rechaza con 403 a los lectores.

El contrato de :func:`require_authorized_user` lo fija
``tests/test_auth_session_is_authorized.py`` (regression test del P0
de la code review VOL-01) y ``tests/test_auth_dependencies.py``
(default-flip a ``False`` de PR-3 en hardening-2026-q2). El default
``False`` cierra la ventana de hasta 7 dias en la que una sesion
pre-fix (sin el flag ``is_authorized``) seguia pasando; la
remediacion operativa para esas cookies pre-fix es rotar
``APAP_SESSION_SECRET`` segun ``docs/runbooks/cookie-rotation.md``.

Regla 7 del code quality: los redirects no son exceptions. La guarda
devuelve un ``RedirectResponse`` en lugar de raise ``HTTPException`` —
es control de flujo, no un error HTTP.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from starlette.responses import Response

from app.core.auth_cache import get_cached_auth, set_cached_auth
from app.core.config import get_settings
from app.core.insforge import InsForgeClient
from app.core.session import read_session_payload


def get_insforge_client_dep() -> Iterator[InsForgeClient]:
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
    return read_session_payload(request, secret=get_settings().session_secret)


def return_early_if_response(value: Response | dict) -> Response | None:
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
    client: InsForgeClient = Depends(get_insforge_client_dep),
) -> Response | dict:
    """Dependencia de FastAPI: exige una sesion autorizada, revalidada por request.

    La cookie firma la IDENTIDAD (email/user_id), estable durante 7 dias.
    La AUTORIZACION (``is_authorized`` + ``rol``) NO es de confianza desde
    la cookie: se re-valida contra ``usuarios_autorizados`` en CADA request
    (issue #143), con una cache TTL en proceso
    (``Settings.auth_cache_ttl_seconds``, default 300s) para acotar el coste
    a ~una query por usuario cada 5 minutos. Esto hace que la desactivacion
    de un usuario via ``/admin/users/{id}/deactivate`` tome efecto en menos
    del TTL, en vez de esperar a que expire la cookie (hasta 7 dias).

    Comportamiento:

    - Si no hay sesion, devuelve ``RedirectResponse`` 302 a ``/login``.
    - Si la cookie no lleva ``is_authorized=True`` (cookie pre-fix, o
      firmada antes del flag), devuelve 302 a ``/unauthorized`` sin tocar
      la DB — el default-deny de la regla 6 se conserva como primera puerta.
    - Si la cookie afirma estar autorizada, se consulta la cache y, si es
      un miss, la DB: si el usuario ya no esta activo (sin fila en
      ``usuarios_autorizados`` con ``activo=true``) devuelve 302 a
      ``/unauthorized`` y memoiza el deny; si sigue activo devuelve el
      payload con el ``rol`` refrescado desde la DB (asi un cambio de rol
      mid-session se recoge en el siguiente request).

    Regla 6 (defaults deny): el default de ``payload.get("is_authorized",
    ...)`` sigue siendo ``False``. La revalidacion por DB es un endurecimiento
    ADICIONAL, no un reemplazo de esa primera puerta.

    Regla 7 (redirects no son exceptions): la dep devuelve un ``Response``
    (no raise ``HTTPException``); el handler DEBE chequear
    ``isinstance(user, Response)`` (via ``return_early_if_response``) antes
    de tratarlo como dict.

    Regla 1 (cero SQL en routes): la revalidacion consulta la DB a traves
    de ``app.core.auth.get_user_by_email`` (el service), nunca SQL crudo en
    la dep ni en el handler.
    """
    if not payload:
        return RedirectResponse(url="/login", status_code=302)
    if not payload.get("is_authorized", False):
        return RedirectResponse(url="/unauthorized", status_code=302)

    email = payload.get("email")
    if not isinstance(email, str) or not email:
        # Cookie firma identidad; sin email no hay a quien revalidar.
        return RedirectResponse(url="/unauthorized", status_code=302)

    ttl = get_settings().auth_cache_ttl_seconds
    cached = get_cached_auth(email, ttl)
    if cached is None:
        # Import local para evitar un ciclo de import a nivel de modulo
        # (app.core.auth importa app.core.auth_cache, que no depende de
        # esta dep; el service se resuelve perezosamente aqui).
        from app.core.auth import get_user_by_email

        fresh = get_user_by_email(client, email)
        if fresh is None:
            set_cached_auth(email, is_authorized=False, rol=None)
            return RedirectResponse(url="/unauthorized", status_code=302)
        set_cached_auth(email, is_authorized=True, rol=fresh["rol"])
        payload["rol"] = fresh["rol"]
        return payload

    if not cached.is_authorized:
        return RedirectResponse(url="/unauthorized", status_code=302)
    payload["rol"] = cached.rol
    return payload


def require_writer_user(
    user: Response | dict = Depends(require_authorized_user),
) -> Response | dict:
    """Dependencia de FastAPI: rechaza usuarios con rol ``reader``; permite el resto de escritores.

    Compone sobre :func:`require_authorized_user` (issue #143): esa dep
    ya revalida ``is_authorized`` + ``rol`` contra la DB en cada request
    y devuelve ``RedirectResponse`` a ``/login`` (sesion ausente) o
    ``/unauthorized`` (sesion inactiva). :func:`require_writer_user` anade
    una segunda puerta: si el rol del usuario NO esta en
    :attr:`Settings.writer_rols`, levanta ``HTTPException(403)`` con
    ``detail="Permisos insuficientes para escribir."``.

    Aplicada a las write routes (POST/PUT/PATCH/DELETE) de los modulos
    de dominio (animales, acogidas, cesiones, entradas, foster,
    voluntarios). Las rutas GET quedan con :func:`require_authorized_user`
    (lectura sigue permitida a cualquier usuario activo).

    Regla 6 (default-deny): si el payload no trae ``rol`` (caso
    anomalo, no esperado por el flujo de :func:`require_authorized_user`
    pero contemplado para futuras cookies), ``None not in writer_rols``
    y la dep rechaza con 403.

    Regla 7 (redirects no son exceptions): si :func:`require_authorized_user`
    devolvio un ``RedirectResponse`` (sesion ausente o inactiva),
    :func:`return_early_if_response` lo propaga sin tocar logica de
    autorizacion. El handler que use esta dep debe llamar
    ``return_early_if_response(user)`` igual que con
    :func:`require_authorized_user`.

    403 vs redirect a ``/unauthorized``: elegimos 403 (HTTP estandar
    para "Forbidden" — la sesion es valida pero el rol no alcanza)
    en lugar de un redirect, porque ``/unauthorized`` significa "sesion
    no autorizada" (otro contexto: cookie pre-fix o usuario desactivado).
    Mezclar ambos mensajes confundiria a operadores y a Sentry.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    user_rol = user.get("rol") if isinstance(user, dict) else None
    if user_rol not in get_settings().writer_rols:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permisos insuficientes para escribir.",
        )
    return user
