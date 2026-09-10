"""RBAC model for APAP_WEB (issue #66).

Roles defined: admin, voluntario, staff (extensible).
Permissions at API level. No legacy password migration.

Matrix policy:
- ADMIN: all permissions
- STAFF: read/write animales, read/write adopciones, read/write acogidas,
         read/write salud, read reportes (no manage:users)
- VOLUNTARIO: read/write animales, read/write voluntarios, read entradas/materiales
              (no write adopciones/acogidas/salud/reportes, no manage:users)

The ``require_permission`` dependency composes on ``require_authorized_user``:
it first resolves the session (redirect to /login if unauthenticated), then
checks the role-permission matrix.  Both failures are distinguishable at the
client (302 vs 403) and in the ``auth.denied`` audit log (reason codes).

Coexistence with legacy: the web RBAC model is completely independent from
the Access/VBA legacy auth model.  They never share sessions or user tables.
Web login is Google OAuth; legacy auth is its own separate system.

Backward compatibility: legacy roles (DEVELOPER, KEY_USER, READER from
``app.core.roles.Rol``) are handled by a fallback that preserves the
pre-RBAC auth behaviour (issue #66 coexists with the existing auth
infrastructure, not replacing it).  New roles use the PERMISSIONS matrix.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from enum import StrEnum

from fastapi import Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from starlette.responses import Response

from app.core.auth_dependencies import (
    AuthenticatedUser,
    require_authorized_user,
    return_early_if_response,
)
from app.core.logging import log_safe


class Role(StrEnum):
    """Roles supported by the web RBAC model (issue #66).

    Extensible: add a new member here and assign permissions in
    :data:`PERMISSIONS`.  The database column ``usuarios_autorizados.rol``
    stores the string value of these members.
    """

    ADMIN = "admin"
    VOLUNTARIO = "voluntario"
    STAFF = "staff"


#: Legacy roles from ``app.core.roles.Rol`` that are handled by the
#: backward-compatibility fallback in ``require_permission``.
#: These roles predate the issue #66 RBAC model and are preserved so
#: existing users (DEVELOPER, KEY_USER) and the reader role (READER)
#: continue to work during the coexistence period.
_LEGACY_WRITER_ROLES: frozenset[str] = frozenset({
    "developer",
    "admin",  # admin is also in new Role; handled by new matrix first
    "key_user",
})


class Permission(StrEnum):
    """Granular permissions for API-level access control (issue #66).

    Naming convention: ``<action>:<resource>`` (lowercase, colon separator).
    Extend as features land.  Each permission is a fine-grained gate on a
    specific API operation (read / write / delete / manage).
    """

    # Animales
    READ_ANIMALES = "read:animales"
    WRITE_ANIMALES = "write:animales"
    DELETE_ANIMALES = "delete:animales"

    # Voluntarios
    READ_VOLUNTARIOS = "read:voluntarios"
    WRITE_VOLUNTARIOS = "write:voluntarios"

    # Adopciones
    READ_ADOPCIONES = "read:adopciones"
    WRITE_ADOPCIONES = "write:adopciones"

    # Acogidas (FOSTER-02: estancias de acogida)
    READ_ACOGIDAS = "read:acogidas"
    WRITE_ACOGIDAS = "write:acogidas"

    # Casas de acogida (FOSTER-01: casas de acogida)
    READ_CASAS_ACOGIDA = "read:casas_acogida"
    WRITE_CASAS_ACOGIDA = "write:casas_acogida"

    # Entradas (intake records)
    READ_ENTRADAS = "read:entradas"
    WRITE_ENTRADAS = "write:entradas"

    # Cesiones (surrender by owner)
    READ_CESIONES = "read:cesiones"
    WRITE_CESIONES = "write:cesiones"

    # Materiales: catalog resource
    READ_MATERIALES = "read:materiales"
    WRITE_MATERIALES = "write:materiales"

    # Salud / sanidad
    READ_SALUD = "read:salud"
    WRITE_SALUD = "write:salud"

    # Reportes
    READ_REPORTES = "read:reportes"
    WRITE_REPORTES = "write:reportes"

    # User management (admin-only)
    MANAGE_USERS = "manage:users"


#: Permission matrix: which permissions each role has.
#: ADMIN has all permissions (is a superset of every other role).
#: STAFF has broad domain access but no user management.
#: VOLUNTARIO has the narrowest access (animals + voluntarios read/write).
PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(Permission),
    Role.STAFF: frozenset({
        Permission.READ_ANIMALES,
        Permission.WRITE_ANIMALES,
        Permission.READ_VOLUNTARIOS,
        Permission.WRITE_VOLUNTARIOS,
        Permission.READ_ADOPCIONES,
        Permission.WRITE_ADOPCIONES,
        Permission.READ_ACOGIDAS,
        Permission.WRITE_ACOGIDAS,
        Permission.READ_CASAS_ACOGIDA,
        Permission.WRITE_CASAS_ACOGIDA,
        Permission.READ_ENTRADAS,
        Permission.WRITE_ENTRADAS,
        Permission.READ_CESIONES,
        Permission.WRITE_CESIONES,
        Permission.READ_MATERIALES,
        Permission.WRITE_MATERIALES,
        Permission.READ_SALUD,
        Permission.WRITE_SALUD,
        Permission.READ_REPORTES,
    }),
    Role.VOLUNTARIO: frozenset({
        Permission.READ_ANIMALES,
        Permission.WRITE_ANIMALES,
        Permission.READ_VOLUNTARIOS,
        Permission.WRITE_VOLUNTARIOS,
        Permission.READ_ENTRADAS,
        Permission.READ_MATERIALES,
    }),
}


def require_permission(
    permission: Permission,
) -> Callable[[], AuthenticatedUser | Response]:
    """Return a FastAPI dependency that enforces ``permission`` for the current user.

    Composes on ``get_current_user_optional`` (session resolution).  Both
    ``require_authorized_user`` and this dep share the same session-revalidation
    logic; callers that only need permission checks (no writer guard) use this
    directly.

    Flow:
    1. Resolve session cookie via ``get_current_user_optional``.
       - No session → 302 redirect to /login (propagated via
         ``return_early_if_response``).
    2. Look up ``user["rol"]`` in :data:`PERMISSIONS`.
       - Role in new ``Role`` enum and has ``permission`` → return user.
       - Role NOT in new ``Role`` enum (legacy role):
         * For read permissions (``read:*``): allow any authenticated legacy role.
         * For write/delete permissions (``write:*``, ``delete:*``):
           allow only legacy writer roles (DEVELOPER, KEY_USER).
           ADMIN is handled by the new matrix (above).
       - Role lacks ``permission`` → raise HTTPException(403).

    Args:
        permission: The permission required to reach the decorated handler.

    Returns:
        A FastAPI ``Depends()`` callable that returns :class:`AuthenticatedUser`
        or raises.

    Example:
        @router.get("/animales")
        def list_animales(
            user: AuthenticatedUser = Depends(require_permission(Permission.READ_ANIMALES)),
        ):
            ...
    """
    def checker(
        payload: Response | dict = Depends(require_authorized_user),
    ) -> AuthenticatedUser | Response:
        # Propagate redirect if session returned a Response (early exit)
        if (early := return_early_if_response(payload)) is not None:
            return early
        if not isinstance(payload, dict):
            log_safe("auth.denied", reason="no_session", user_id=None)
            return RedirectResponse(url="/login", status_code=302)

        rol_str = payload.get("rol")
        user_id = payload.get("user_id")

        # Try to resolve as a new RBAC role
        role: Role | None = None
        if rol_str:
            with contextlib.suppress(ValueError):
                role = Role(rol_str)

        if role is not None:
            # New RBAC role: use the permissions matrix
            allowed = PERMISSIONS.get(role, frozenset())
            if permission in allowed:
                return payload  # type: ignore[return-value]
            log_safe(
                "auth.denied",
                reason="permission_denied",
                user_id=user_id,
                permission=permission.value,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permisos insuficientes",
            )

        # Legacy role fallback (backward compatibility):
        # - Read permissions (read:*): any authenticated legacy role allowed
        # - Write/delete permissions: only legacy writer roles allowed
        #   (DEVELOPER, KEY_USER — not ADMIN, which is in new Role enum)
        if rol_str is None:
            # Unauthenticated / no role
            log_safe(
                "auth.denied",
                reason="permission_denied",
                user_id=user_id,
                permission=permission.value,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permisos insuficientes",
            )

        permission_value = permission.value
        is_read = permission_value.startswith("read:")
        is_write_or_delete = permission_value.startswith("write:") or permission_value.startswith("delete:")

        if is_read:
            # Any authenticated role can read (pre-RBAC behaviour)
            return payload  # type: ignore[return-value]

        if is_write_or_delete:
            # Only legacy writer roles can write/delete
            if rol_str in _LEGACY_WRITER_ROLES:
                return payload  # type: ignore[return-value]
            # Legacy reader or unknown role: raise with the old writer-rejection message
            log_safe(
                "auth.denied",
                reason="permission_denied",
                user_id=user_id,
                permission=permission.value,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permisos insuficientes para escribir.",
            )

        # Role not in new model and lacks required legacy permission
        log_safe(
            "auth.denied",
            reason="permission_denied",
            user_id=user_id,
            permission=permission.value,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permisos insuficientes",
        )

    return checker
