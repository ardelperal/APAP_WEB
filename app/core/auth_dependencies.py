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
- :func:`require_developer_user` -- guarda que ademas exige
  ``rol == "developer"`` (FOSTER-03 #45); rechaza con 403 a cualquier
  otro rol. Usada por endpoints que exponen PII o historial de auditoria
  (audit log ``foster_capacity_overrides.motivo``).
- :func:`require_developer_user_redirect` -- variante de
  :func:`require_developer_user` que redirige a ``/unauthorized`` (302) en
  lugar de raise 403. Usada por las rutas ``/admin`` historicas para
  preservar el comportamiento de redirect pre-#146.

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
es control de flujo, no un error HTTP. Excepcion deliberada:
:func:`require_developer_user` devuelve 403 (raise HTTPException) cuando
hay sesion valida pero el rol no es developer — son ROLES DIFERENTES,
no un estado de sesion invalido. ``require_developer_user_redirect``
es la variante que respeta el contrato de redirect para callers que
historicamente redirigian en lugar de elevar.

Issue #146 — toda denegacion emite un evento ``log_safe("auth.denied",
...)`` con un ``reason`` enum (no_session / cookie_no_flag / no_email /
db_reval_miss / writer_required / developer_required) y ``user_id``
(non-PII). Los PII (email, etc.) quedan en la lista cerrada de 12
campos que ``log_safe`` redacta — el codigo pasa solo ``user_id``.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from starlette.responses import Response

from app.core.auth import Rol
from app.core.auth_cache import get_cached_auth, set_cached_auth
from app.core.config import get_settings
from app.core.insforge import InsForgeClient
from app.core.logging import log_safe
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
        log_safe(
            "auth.denied",
            reason="no_session",
            user_id=None,
        )
        return RedirectResponse(url="/login", status_code=302)
    if not payload.get("is_authorized", False):
        log_safe(
            "auth.denied",
            reason="cookie_no_flag",
            user_id=payload.get("user_id") if isinstance(payload, dict) else None,
        )
        return RedirectResponse(url="/unauthorized", status_code=302)

    email = payload.get("email")
    if not isinstance(email, str) or not email:
        # Cookie firma identidad; sin email no hay a quien revalidar.
        log_safe(
            "auth.denied",
            reason="no_email",
            user_id=payload.get("user_id") if isinstance(payload, dict) else None,
        )
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
            log_safe(
                "auth.denied",
                reason="db_reval_miss",
                user_id=payload.get("user_id") if isinstance(payload, dict) else None,
            )
            return RedirectResponse(url="/unauthorized", status_code=302)
        set_cached_auth(email, is_authorized=True, rol=fresh["rol"])
        payload["rol"] = fresh["rol"]
        return payload

    if not cached.is_authorized:
        log_safe(
            "auth.denied",
            reason="db_reval_miss",
            user_id=payload.get("user_id") if isinstance(payload, dict) else None,
        )
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
        # Issue #146: audit trail. The reason enum distinguishes a
        # missing-rol rejection from a deactivated-session redirect that
        # the upstream dep propagated — operators grep auth.denied by
        # reason to spot a non-writer trying to mutate domain state.
        log_safe(
            "auth.denied",
            reason="writer_required",
            user_id=user.get("user_id") if isinstance(user, dict) else None,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permisos insuficientes para escribir.",
        )
    return user


def require_developer_user(
    payload: Response | dict = Depends(require_authorized_user),
) -> Response | dict:
    """Dependencia de FastAPI: exige sesion con ``is_authorized=True`` Y ``rol == "developer"``.

    Compone sobre :func:`require_authorized_user` (issue #143): esa dep
    ya revalida ``is_authorized`` + ``rol`` contra la DB en cada request
    y devuelve ``RedirectResponse`` a ``/login`` (sesion ausente) o
    ``/unauthorized`` (sesion inactiva). :func:`require_developer_user`
    anade una segunda puerta: si el rol del usuario NO es
    :attr:`Rol.DEVELOPER`, levanta ``HTTPException(403)``.

    FOSTER-03 (#45) P1 risk-review fix: el audit log
    ``foster_capacity_overrides`` lleva campos con potencial PII
    (``motivo`` libre del operador). Solo developers deben ver el
    historial via ``GET /casas-acogida/{id}/overrides`` y la seccion
    "Historico de overrides" en ``detail.html``. Los operadores siguen
    pudiendo disparar overrides via ``POST /asignar`` (el flujo
    FOSTER-03 explicito) — solo el audit listing esta bloqueado.

    Regla 6 (default-deny): si el payload no trae ``rol`` (caso
    anomalo, no esperado por el flujo de :func:`require_authorized_user`
    pero contemplado para futuras cookies), ``None != Rol.DEVELOPER.value``
    y la dep rechaza con 403.

    Regla 7 (redirects no son exceptions): si :func:`require_authorized_user`
    devolvio un ``RedirectResponse`` (sesion ausente o inactiva),
    :func:`return_early_if_response` lo propaga sin tocar logica de
    autorizacion. El handler que use esta dep debe llamar
    ``return_early_if_response(user)`` igual que con
    :func:`require_authorized_user`.

    Regla 4 del code quality: el valor ``"developer"`` viene de
    :class:`app.core.auth.Rol.DEVELOPER` (unica fuente de verdad).

    403 vs redirect a ``/unauthorized``: elegimos 403 (HTTP estandar
    para "Forbidden" — la sesion es valida pero el rol no alcanza)
    en lugar de un redirect, porque ``/unauthorized`` significa "sesion
    no autorizada" (otro contexto: cookie pre-fix o usuario desactivado).
    Mezclar ambos mensajes confundiria a operadores y a Sentry.
    """
    if (early := return_early_if_response(payload)) is not None:
        return early
    user_rol = payload.get("rol") if isinstance(payload, dict) else None
    if user_rol != Rol.DEVELOPER.value:
        # Issue #146: audit trail. ``developer_required`` is the
        # non-redirect variant of the denegation signal — the redirect
        # variant emits the same event under ``require_developer_user_redirect``.
        log_safe(
            "auth.denied",
            reason="developer_required",
            user_id=payload.get("user_id") if isinstance(payload, dict) else None,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="requiere rol developer",
        )
    return payload


def require_developer_user_redirect(
    payload: Response | dict = Depends(require_authorized_user),
) -> Response | dict:
    """Variante de :func:`require_developer_user` que redirige en lugar de raise 403.

    Issue #146 — las tres rutas admin (``/admin``, ``/admin/users``,
    ``/admin/users/{id}/deactivate``) dependian de
    :func:`require_authorized_user` y luego hacian inline
    ``current_user.get("rol") != "developer"`` para devolver un redirect
    a ``/unauthorized``. Esa duplicacion divergia del resto del modelo
    de auth y dejaba el audit trail fuera del path. Esta dep:

    - Compone sobre :func:`require_authorized_user` (revalidacion por
      request + cache TTL del issue #143).
    - Devuelve el payload intacto si el rol es :attr:`Rol.DEVELOPER`.
    - Devuelve ``RedirectResponse("/unauthorized", 302)`` para cualquier
      otro rol — preservando el comportamiento historico de las rutas
      admin para no introducir un 403 donde antes habia un redirect.
    - Propaga sin tocar el redirect que ``require_authorized_user``
      pudo haber devuelto (misma composicion que
      :func:`require_writer_user` y :func:`require_developer_user`).

    Regla 4 (source of truth): el valor ``"developer"`` viene de
    :class:`app.core.auth.Rol.DEVELOPER`. NO se hardcodea el literal
    aqui. Regla 6 (default-deny): si el payload no trae ``rol``, se
    redirige (no se asume el developer).

    Cuándo usar :func:`require_developer_user` vs esta variante:

    - :func:`require_developer_user` → raise 403, recomendado para
      callers NUEVOS que prefieren el estandar HTTP "Forbidden" cuando
      hay sesion valida pero rol insuficiente.
    - :func:`require_developer_user_redirect` → redirect a
      ``/unauthorized``, recomendado para preservar el comportamiento
      pre-#146 en callers que ya redirigian (panel admin historico).
    """
    if (early := return_early_if_response(payload)) is not None:
        return early
    user_rol = payload.get("rol") if isinstance(payload, dict) else None
    if user_rol != Rol.DEVELOPER.value:
        return RedirectResponse(url="/unauthorized", status_code=302)
    return payload
