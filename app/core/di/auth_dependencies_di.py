"""FastAPI dependencies for the auth flow (slice #420-7).

Composition root of the auth-dependencies slice. Holds the 9 public
symbols and one private helper that ``app/core/auth_dependencies.py``
previously defined whole. The legacy path is now a shim that re-exports
from this module (see ``app/core/auth_dependencies.py``).

Why this split exists (epic #420, §33.3)
----------------------------------------

:class:`app.core.auth_dependencies` historically owned both the
FastAPI dependency factories AND the import of ``app.core.auth``. Per
the hexagonal architecture, the composition root of a slice lives in
``app/core/di/<slice>_di.py``; the new home is this file. The
business-layer ``app/core/auth.py`` stays where it is — the di module
imports it, never the other way around.

Slice contracts
---------------

The 9 public symbols preserve byte-identical signatures with the
pre-slice form. The 19 consumer modules (see proposal §3) import via
``from app.core.auth_dependencies import <name>`` and keep working
through the shim. ``app.dependency_overrides[<name>]`` in the test
suite works the same way — the override key is the function object
itself, and the shim re-exports the same object (identity, not just
equality).

The §32.P4 fix (Variant A) lives inside :func:`require_authorized_user`
and only wraps the single ``get_user_by_email`` call. It does NOT
wrap cache reads (in-process, cannot raise ``InsForgeError``) and does
NOT wrap dict-internal mutations.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TypeGuard

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from starlette.responses import Response
from typing_extensions import TypedDict

# ``_shim`` is the legacy ``app.core.auth_dependencies`` module (the shim).
# The di module reads ``log_safe`` and ``read_session_payload`` through
# ``_shim`` so test monkeypatches on ``app.core.auth_dependencies.log_safe``
# / ``read_session_payload`` propagate to the di module's function calls.
# The import is module-level (no ``lazy-import:` marker needed) because the
# shim is fully loaded by the time any function here is invoked; the
# lookup is dynamic at call time. Doc: see the shim's module docstring.
from app.core import auth_dependencies as _shim
from app.core.auth import get_user_by_email
from app.core.auth_cache import get_cached_auth, set_cached_auth
from app.core.config import get_settings
from app.core.data_access import InsForgeError
from app.core.insforge import InsForgeClient
from app.core.roles import Rol


class AuthenticatedUser(TypedDict):
    """Shape of the authenticated-user dict returned by auth dependencies.

    All fields are non-optional: a dict that passes :func:`is_authenticated_user`
    has passed the structural check and is guaranteed to have these four keys.
    """

    user_id: str
    email: str
    rol: str
    is_authorized: bool


def is_authenticated_user(obj: object) -> TypeGuard[AuthenticatedUser]:
    """TypeGuard: narrows ``object`` to :class:`AuthenticatedUser` when the
    object is a dict with the required keys.

    Use after :func:`return_early_if_response` to narrow the resolved-user
    branch to the authenticated-user shape::

        if (early := return_early_if_response(user)) is not None:
            return early
        # After return_early_if_response, 'user' is a dict.
        # is_authenticated_user narrows it further to AuthenticatedUser.
        assert is_authenticated_user(user)
    """
    if not isinstance(obj, dict):
        return False
    return (
        isinstance(obj.get("user_id"), str)
        and isinstance(obj.get("email"), str)
        and isinstance(obj.get("rol"), str)
        and isinstance(obj.get("is_authorized"), bool)
    )


def get_insforge_client_dep(request: Request) -> Iterator[InsForgeClient]:
    """Yield the pooled InsForge client owned by the application lifespan.

    The lifespan creates the client once and stores it on ``app.state`` so
    its underlying ``httpx.Client`` can reuse connections across requests.
    Shutdown closes the pooled client; this dependency deliberately does not
    own or close it per request.

    Tests can override this dependency with ``app.dependency_overrides``;
    FastAPI still resolves those overrides before calling this provider.
    """
    try:
        client = request.app.state.insforge_client
    except AttributeError:
        # Some lightweight ASGI test transports do not run lifespan events.
        # Keep their app usable by creating the same app-scoped client lazily;
        # production startup always initializes this state in ``lifespan``.
        settings = get_settings()
        client = InsForgeClient(settings.insforge_url, settings.insforge_service_key)
        request.app.state.insforge_client = client
    yield client


def get_current_user_optional(request: Request) -> dict | None:
    """Dependencia de FastAPI: devuelve el payload de la sesion, o None.

    Lee la cookie de sesion firmada y devuelve el payload como dict,
    o ``None`` si la cookie no existe o la firma no es valida. Usar
    en handlers que quieran render condicional (mostrar el nombre de
    usuario si esta logueado) pero que no requieren auth.
    """
    return _shim.read_session_payload(request, secret=get_settings().session_secret)


def return_early_if_response(value: Response | AuthenticatedUser | dict) -> Response | None:
    """Helper regla 7: si ``value`` es un ``Response`` (redirect), lo retorna.

    Los handlers que usan :func:`require_authorized_user` reciben un
    ``AuthenticatedUser`` (TypedDict) cuando la sesion es valida, o un
    ``Response`` (RedirectResponse) cuando no lo es. Si la dep devolvio un
    ``RedirectResponse``, el handler DEBE retornar ese response al cliente
    sin tocar la logica de negocio:

    .. code-block:: python

        def handler(
            current_user: AuthenticatedUser = Depends(require_authorized_user),
        ):
            if (early := return_early_if_response(current_user)) is not None:
                return early
            # current_user es AuthenticatedUser; logica de negocio.

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
    - Si la revalidacion contra la DB no puede completarse (transport
      falla y ``get_user_by_email`` levanta ``InsForgeError``), devuelve
      302 a ``/unauthorized`` y emite ``log_safe("auth.denied",
      reason="db_unreachable")`` — la peticion no llega a un 500
      inmanejable (issue #294 §32.P4 fix).

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
        _shim.log_safe(
            "auth.denied",
            reason="no_session",
            user_id=None,
        )
        return RedirectResponse(url="/login", status_code=302)
    if not payload.get("is_authorized", False):
        _shim.log_safe(
            "auth.denied",
            reason="cookie_no_flag",
            user_id=payload.get("user_id") if isinstance(payload, dict) else None,
        )
        return RedirectResponse(url="/unauthorized", status_code=302)

    email = payload.get("email")
    if not isinstance(email, str) or not email:
        # Cookie firma identidad; sin email no hay a quien revalidar.
        _shim.log_safe(
            "auth.denied",
            reason="no_email",
            user_id=payload.get("user_id") if isinstance(payload, dict) else None,
        )
        return RedirectResponse(url="/unauthorized", status_code=302)

    ttl = get_settings().auth_cache_ttl_seconds
    cached = get_cached_auth(email, ttl)
    if cached is None:
        try:
            fresh = get_user_by_email(client, email)
        except InsForgeError:
            # §32.P4 Variant A — transport failure during per-request
            # revalidation is a denial, not a 500. The catch is bare
            # (no ``as exc``) to match the existing code style at the
            # prior line 237. ``set_cached_auth`` is intentionally NOT
            # called here: a transient DB outage does not poison the
            # auth cache with a deny verdict.
            _shim.log_safe(
                "auth.denied",
                reason="db_unreachable",
                user_id=payload.get("user_id") if isinstance(payload, dict) else None,
            )
            return RedirectResponse(url="/unauthorized", status_code=302)
        if fresh is None:
            set_cached_auth(email, is_authorized=False, rol=None)
            _shim.log_safe(
                "auth.denied",
                reason="db_reval_miss",
                user_id=payload.get("user_id") if isinstance(payload, dict) else None,
            )
            return RedirectResponse(url="/unauthorized", status_code=302)
        set_cached_auth(email, is_authorized=True, rol=fresh["rol"])
        payload["rol"] = fresh["rol"]
        return payload

    if not cached.is_authorized:
        _shim.log_safe(
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
        _shim.log_safe(
            "auth.denied",
            reason="writer_required",
            user_id=user.get("user_id") if isinstance(user, dict) else None,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permisos insuficientes para escribir.",
        )
    return user


def _resolve_developer_user(payload: Response | dict) -> Response | dict | None:
    """Return an authorized developer payload/redirect, or ``None`` on role denial."""
    if (early := return_early_if_response(payload)) is not None:
        return early
    user_rol = payload.get("rol") if isinstance(payload, dict) else None
    if user_rol != Rol.DEVELOPER.value:
        _shim.log_safe(
            "auth.denied",
            reason="developer_required",
            user_id=payload.get("user_id") if isinstance(payload, dict) else None,
        )
        return None
    return payload


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
    :class:`app.core.roles.Rol.DEVELOPER` (unica fuente de verdad).

    403 vs redirect a ``/unauthorized``: elegimos 403 (HTTP estandar
    para "Forbidden" — la sesion es valida pero el rol no alcanza)
    en lugar de un redirect, porque ``/unauthorized`` significa "sesion
    no autorizada" (otro contexto: cookie pre-fix o usuario desactivado).
    Mezclar ambos mensajes confundiria a operadores y a Sentry.
    """
    resolved = _resolve_developer_user(payload)
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="requiere rol developer",
        )
    return resolved


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
    :class:`app.core.roles.Rol.DEVELOPER`. NO se hardcodea el literal
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
    resolved = _resolve_developer_user(payload)
    if resolved is None:
        return RedirectResponse(url="/unauthorized", status_code=302)
    return resolved


__all__ = [
    "AuthenticatedUser",
    "is_authenticated_user",
    "get_insforge_client_dep",
    "get_current_user_optional",
    "return_early_if_response",
    "require_authorized_user",
    "require_writer_user",
    "require_developer_user",
    "require_developer_user_redirect",
]
