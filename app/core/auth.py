"""Authorized users: schema, bootstrap seed and CRUD helpers.

The ``authorized_users`` table is the single source of truth for who
can access APAP_WEB. The schema, the bootstrap seed and the CRUD
helpers are kept here so the schema stays in one place; the HTTP
routes in ``app.main`` and the panel admin in ``app.modules.admin``
delegate to these functions and never run raw SQL directly.

Roles (per ``docs/decisiones-proyecto.md`` § "Usuarios autorizados y
roles"):

- ``developer`` — full access, can manage other users
- ``admin``     — configuration access
- ``key_user``  — standard access (default for new users)
- ``reader``    — read-only access
"""

from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.core.insforge import InsForgeClient

VALID_ROLES = frozenset({"developer", "admin", "key_user", "reader"})

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS authorized_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('developer', 'admin', 'key_user', 'reader')),
    added_by UUID,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT now()
)
"""

SEED_ADMIN_SQL = """
INSERT INTO authorized_users (email, role, is_active)
SELECT $1, 'developer', true
WHERE NOT EXISTS (
    SELECT 1 FROM authorized_users WHERE role = 'developer'
)
RETURNING id, email, role
"""

GET_USER_BY_EMAIL_SQL = """
SELECT id, email, role, is_active
FROM authorized_users
WHERE email = $1
  AND is_active = true
"""

LIST_USERS_SQL = """
SELECT id, email, role, is_active, created_at
FROM authorized_users
ORDER BY created_at DESC
"""

ADD_USER_SQL = """
INSERT INTO authorized_users (email, role, added_by, is_active)
VALUES ($1, $2, $3, true)
RETURNING id, email, role, is_active, created_at
"""

DEACTIVATE_USER_SQL = """
UPDATE authorized_users
SET is_active = false
WHERE id = $1
RETURNING id, email, role, is_active
"""


def ensure_schema_and_seed(client: InsForgeClient, settings: Settings) -> None:
    """Create the table (idempotent) and seed the bootstrap admin if configured.

    The seed is gated on:

    1. ``settings.initial_admin_email`` being non-empty, AND
    2. no row with ``role = 'developer'`` already existing.

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
