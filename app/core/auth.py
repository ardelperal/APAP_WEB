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

from app.core.auth_cache import invalidate_auth
from app.core.auth_helpers import normalize_email, validate_email_format
from app.core.config import Settings
from app.core.data_access import DuplicateKeyError, SqlExecutor
from app.core.roles import Rol
from app.core.schema_bootstrap import SqlStatement, run_idempotent_sql

# Derivado del enum (regla 4 del code quality: una sola fuente de verdad
# por concepto de dominio). NO hardcodear; cualquier nuevo rol se agrega
# a ``Rol`` y se refleja automáticamente.
VALID_ROLES: frozenset[str] = frozenset(r.value for r in Rol)

# El CHECK constraint que duplicaba los valores de ``Rol`` se eliminó
# en PR-2 (Slice 2). La validación de rol pasa a ser 100 % a nivel de
# aplicación vía ``add_authorized_user`` (que compara contra
# ``VALID_ROLES`` y levanta ``ValueError``). Una nueva entrada en
# ``Rol`` se refleja automáticamente; añadir el CHECK reintroduciría
# la duplicación que rompe la regla 4 y requeriría una migración
# nueva cada vez que se agregue un rol (audit engram:14516).
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS usuarios_autorizados (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    rol TEXT NOT NULL,
    anadido_por UUID,
    activo BOOLEAN NOT NULL DEFAULT true,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now()
)
"""

SEED_ADMIN_SQL = """
INSERT INTO usuarios_autorizados (email, rol, activo)
SELECT $1, 'developer', true
WHERE NOT EXISTS (
    SELECT 1 FROM usuarios_autorizados WHERE rol = 'developer' AND activo = true
)
RETURNING id, email, rol
"""

GET_USER_BY_EMAIL_SQL = """
SELECT id, email, rol, activo
FROM usuarios_autorizados
WHERE email = $1
  AND activo = true
"""

# Distinct from GET_USER_BY_EMAIL_SQL so the test spy (issue #143) can
# differentiate the auth-revalidation call (needs a fake row) from the
# duplicate-check call (must NOT be intercepted).  Uses a narrower column
# set so the WHERE clause is the only thing they share.
_CHECK_DUPLICATE_EMAIL_SQL = """
SELECT id FROM usuarios_autorizados WHERE email = $1 AND activo = true
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
  AND (
      rol <> 'developer'
      OR (
          SELECT count(*) FROM (
              SELECT 1 FROM usuarios_autorizados
               WHERE rol = 'developer' AND activo = true AND id <> $1
          ) sub
      ) >= 1
  )
RETURNING id, email, rol, activo
"""

_CHECK_OTHER_DEVELOPERS_SQL = """
SELECT EXISTS(
    SELECT 1 FROM usuarios_autorizados
     WHERE rol = 'developer' AND activo = true AND id <> $1
)
"""

GET_USER_BY_ID_SQL = """
SELECT id, email, rol, activo
FROM usuarios_autorizados
WHERE id = $1
"""


def ensure_schema_and_seed(client: SqlExecutor, settings: Settings) -> None:
    """Create the table (idempotent) and seed the bootstrap admin if configured.

    The seed is gated on:

    1. ``settings.initial_admin_email`` being non-empty, AND
    2. no row with ``rol = 'developer'`` already existing.

    This makes the function safe to call on every startup: the table
    is created if missing, and the admin is seeded at most once.
    """
    statements = [SqlStatement(CREATE_TABLE_SQL)]
    if settings.initial_admin_email:
        statements.append(SqlStatement(SEED_ADMIN_SQL, [settings.initial_admin_email]))
    run_idempotent_sql(client, statements, step_name="auth")


def get_user_by_email(
    client: SqlExecutor,
    email: str,
) -> dict[str, Any] | None:
    """Return the active user with this email, or None.

    The email is normalized (stripped + lowercased) before lookup so that
    mixed-case variants resolve to the same canonical row (issue #278).
    """
    email = normalize_email(email)
    rows = client.execute_sql(GET_USER_BY_EMAIL_SQL, [email])
    return rows[0] if rows else None


def list_authorized_users(client: SqlExecutor) -> list[dict[str, Any]]:
    """Return all users (active and inactive) for the admin panel."""
    return client.execute_sql(LIST_USERS_SQL)


def add_authorized_user(
    client: SqlExecutor,
    email: str,
    role: str,
    added_by: str,
) -> dict[str, Any]:
    """Insert a new authorized user. ``role`` must be in :data:`VALID_ROLES`.

    Rol validation is **application-level** (rule 4 — one source of
    truth per domain concept). The DB has no CHECK constraint on
    ``rol``; this helper is the sole gate. The set of accepted roles
    is derived from :class:`Rol` (``VALID_ROLES = frozenset(r.value
    for r in Rol)``), so adding a new enum member opens the door
    automatically without any DDL change.

    The email is normalized (stripped + lowercased) before storage and
    validation. A pre-insert SELECT detects canonical duplicates; a
    defense-in-depth :class:`~app.core.data_access.DuplicateKeyError`
    catch covers the race where two parallel INSERTs slip past the
    pre-check (issues #277, #278).

    Returns the inserted row.
    """
    normalized = normalize_email(email)
    validate_email_format(normalized)
    if role not in VALID_ROLES:
        raise ValueError(f"invalid role: {role!r}; must be one of {sorted(VALID_ROLES)}")
    # Pre-insert duplicate check (cheap path — avoids a unique-violation race).
    # Uses _CHECK_DUPLICATE_EMAIL_SQL (narrow SELECT) so the test spy can
    # distinguish this call from the auth-revalidation call in
    # require_authorized_user, which uses GET_USER_BY_EMAIL_SQL (full SELECT).
    existing = client.execute_sql(_CHECK_DUPLICATE_EMAIL_SQL, [normalized])
    if existing:
        raise ValueError(f"email already authorized: {normalized!r}")
    try:
        rows = client.execute_sql(ADD_USER_SQL, [normalized, role, added_by])
    except DuplicateKeyError as exc:
        # Defense in depth — the adapter translates 23505 / duplicate-key
        # bodies to DuplicateKeyError before this layer sees them; any
        # other envelope shape is a genuine transport failure that the
        # global InsForgeError handler still owns.
        raise ValueError(f"email already authorized: {normalized!r}") from exc
    # Issue #143: a prior deactivate may have cached a deny for this email;
    # re-adding must take effect on the next request, not after the TTL.
    invalidate_auth(normalized)
    return rows[0]


def _has_other_active_developers(
    client: SqlExecutor,
    exclude_user_id: str,
) -> bool:
    """Return True if at least one other active developer exists (excluding exclude_user_id).

    Used to guard against deactivating the last active developer.
    """
    rows = client.execute_sql(_CHECK_OTHER_DEVELOPERS_SQL, [exclude_user_id])
    return bool(rows and rows[0].get("exists"))


def get_user_by_id(
    client: SqlExecutor,
    user_id: str,
) -> dict[str, Any] | None:
    """Return the user with this id, or None if not found."""
    rows = client.execute_sql(GET_USER_BY_ID_SQL, [user_id])
    return rows[0] if rows else None


def deactivate_authorized_user(
    client: SqlExecutor,
    user_id: str,
) -> dict[str, Any] | None:
    """Mark the user as inactive. Returns the row, or None if not found.

    Raises ValueError when deactivating the last active developer
    (would leave no active developer to access /admin).

    Issue #143: the per-request authorization cache is invalidated for the
    deactivated email (taken from the ``RETURNING`` row) so the revocation
    takes effect on the user's next request rather than after the cache
    TTL. Deactivation is keyed by ``id``, but the cache is keyed by
    ``email``; the ``RETURNING email`` bridges the two without a second
    query.

    Issue #279: the atomic conditional UPDATE prevents deactivating the
    last active developer. On zero rows we disambiguate via get_user_by_id.
    """
    rows = client.execute_sql(DEACTIVATE_USER_SQL, [user_id])
    if not rows:
        # Zero rows: either user not found, OR last-developer guard fired.
        # Disambiguate with a targeted SELECT.
        user = get_user_by_id(client, user_id)
        if user is None:
            raise ValueError(f"user not found: {user_id!r}")
        if user.get("rol") == "developer" and not _has_other_active_developers(
            client, exclude_user_id=user_id
        ):
            raise ValueError("cannot deactivate the last active developer")
        # Edge: row updated but RETURNING didn't yield (shouldn't happen)
        raise ValueError(f"deactivate failed unexpectedly for user {user_id!r}")
    invalidate_auth(rows[0]["email"])
    return rows[0]
