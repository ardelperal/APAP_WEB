"""Public composition root for the auth-dependencies slice.

The session and backend revalidation dependencies live in
:mod:`app.core.di.auth_dependencies_session_di`. This module preserves the
nine-symbol public API consumed by :mod:`app.core.auth_dependencies` and direct
DI callers.
"""

from __future__ import annotations

from typing import TypeGuard

from fastapi import Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from starlette.responses import Response
from typing_extensions import TypedDict

from app.core.config import get_settings
from app.core.di.auth_dependencies_session_di import (
    get_current_user_optional,
    get_local_backend_client_dep,
    require_authorized_user,
)
from app.core.roles import Rol


def _shim():
    """Return the legacy ``app.core.auth_dependencies`` shim module.

    The lookup is deferred to function-call time. Without the deferral,
    a fresh process that imports the di module FIRST triggers a
    partial-module shim load; the shim's
    ``from app.core.di.auth_dependencies_di import *`` then runs
    against the PARTIAL di module (the 9 public symbols are defined
    AFTER the di module's module-level shim import) and the shim
    ends up with NO re-exports. Consumers
    (``from app.core.auth_dependencies import require_authorized_user``)
    then fail with ImportError.

    Test monkeypatches on the shim's ``log_safe`` /
    ``read_session_payload`` still propagate: the lookup returns the
    same module object, and Python attribute access sees the patched
    value at every call.

    Returns:
        The ``app.core.auth_dependencies`` module object.
    """
    # lazy-import: deferred to call time — avoids the order-dependent module-load cycle with the shim's ``import *`` of this module (full rationale in the docstring above).
    from app.core import auth_dependencies

    return auth_dependencies


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
        _shim().log_safe(
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
        _shim().log_safe(
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
    "get_local_backend_client_dep",
    "get_current_user_optional",
    "return_early_if_response",
    "require_authorized_user",
    "require_writer_user",
    "require_developer_user",
    "require_developer_user_redirect",
]
