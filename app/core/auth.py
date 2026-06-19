"""Usuarios autorizados: schema, bootstrap seed y helpers de CRUD.

La tabla ``usuarios_autorizados`` es la unica fuente de verdad de quien
puede acceder a APAP_WEB. El schema, el seed bootstrap y los helpers
de CRUD viven aqui para que el schema este en un solo lugar; las rutas
HTTP en ``app.main`` y el panel admin en ``app.modules.admin`` delegan
en estas funciones y nunca ejecutan SQL crudo.

Nombres en espanol (consistente con el resto de tablas del dominio,
que son el target de la migracion del Access legacy). Las columnas
``id`` y ``email`` se mantienen en su forma universal; el resto se
traduce para alinear con el resto del schema.

Roles (segun ``docs/decisiones-proyecto.md`` seccion "Usuarios
autorizados y roles"):

- ``developer`` -- acceso total, puede gestionar otros usuarios
- ``admin``     -- acceso de configuracion
- ``key_user``  -- acceso estandar (default para nuevos usuarios)
- ``reader``    -- acceso de solo lectura
"""

from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.core.insforge import InsForgeClient

VALID_ROLES = frozenset({"developer", "admin", "key_user", "reader"})

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS usuarios_autorizados (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    rol TEXT NOT NULL CHECK (rol IN ('developer', 'admin', 'key_user', 'reader')),
    anadido_por UUID,
    activo BOOLEAN NOT NULL DEFAULT true,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now()
)
"""

SEED_ADMIN_SQL = """
INSERT INTO usuarios_autorizados (email, rol, activo)
SELECT $1, 'developer', true
WHERE NOT EXISTS (
    SELECT 1 FROM usuarios_autorizados WHERE rol = 'developer'
)
RETURNING id, email, rol
"""

GET_USER_BY_EMAIL_SQL = """
SELECT id, email, rol, activo
FROM usuarios_autorizados
WHERE email = $1
  AND activo = true
"""

LIST_USERS_SQL = """
SELECT id, email, rol, activo, fecha_alta
FROM usuarios_autorizados
ORDER BY fecha_alta DESC
"""

ADD_USER_SQL = """
INSERT INTO usuarios_autorizados (email, rol, anadido_por, activo)
VALUES ($1, $2, $3, true)
RETURNING id, email, rol, activo, fecha_alta
"""

DEACTIVATE_USER_SQL = """
UPDATE usuarios_autorizados
SET activo = false
WHERE id = $1
RETURNING id, email, rol, activo
"""


def ensure_schema_and_seed(client: InsForgeClient, settings: Settings) -> None:
    """Create the table (idempotent) and seed the bootstrap admin if configured.

    The seed is gated on:

    1. ``settings.initial_admin_email`` being non-empty, AND
    2. no row with ``rol = 'developer'`` already existing.

    This makes the function safe to call on every startup: the table
    is created if missing, and the admin is seeded at most once.
    """
    client.execute_sql(CREATE_TABLE_SQL)
    if settings.initial_admin_email:
        client.execute_sql(SEED_ADMIN_SQL, [settings.initial_admin_email])


def get_user_by_email(
    client: InsForgeClient,
    email: str,
) -> dict[str, Any] | None:
    """Return the active user with this email, or None."""
    rows = client.execute_sql(GET_USER_BY_EMAIL_SQL, [email])
    return rows[0] if rows else None


def list_authorized_users(client: InsForgeClient) -> list[dict[str, Any]]:
    """Return all users (active and inactive) for the admin panel."""
    return client.execute_sql(LIST_USERS_SQL)


def add_authorized_user(
    client: InsForgeClient,
    email: str,
    role: str,
    added_by: str,
) -> dict[str, Any]:
    """Insert a new authorized user. ``role`` must be in :data:`VALID_ROLES`.

    Returns the inserted row.
    """
    if role not in VALID_ROLES:
        raise ValueError(f"invalid role: {role!r}; must be one of {sorted(VALID_ROLES)}")
    rows = client.execute_sql(ADD_USER_SQL, [email, role, added_by])
    return rows[0]


def deactivate_authorized_user(
    client: InsForgeClient,
    user_id: str,
) -> dict[str, Any] | None:
    """Mark the user as inactive. Returns the row, or None if not found."""
    rows = client.execute_sql(DEACTIVATE_USER_SQL, [user_id])
    return rows[0] if rows else None
