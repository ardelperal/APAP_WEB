"""SQL constants for the :class:`LocalBackendAuthUsersAdapter`.

Per AGENTS.md §22 (query-construction seam): SQL strings and their
parameter shaping live here so the adapter orchestrates without
owning the literal SQL, and so unit tests can assert the shape of
the SQL without spinning up the transport.

The SQL here is the same shape the pre-Phase-1 ``app.core.auth``
module used (issues #143 / #277 / #278 / #279). The admin tests
mock the SQL by substring match — see
``tests/test_admin.py::_FakeInsForge.execute_sql`` (keys on
``"SELECT id, email, rol, activo FROM usuarios_autorizados WHERE id =
$1"``) and ``tests/test_auth.py`` (keys on ``"SELECT EXISTS"``,
``"SET activo = false"``, etc.). Any future change to a SQL string
must preserve those substrings; the comment next to each
projection-affecting query documents the substring contract.
"""

from __future__ import annotations

# El CHECK constraint que duplicaba los valores de ``Rol`` se eliminó
# en PR-2 (Slice 2). La validación de rol pasa a ser 100 % a nivel de
# aplicación vía ``add_authorized_user`` (que compara contra ``Rol``
# y levanta ``ValueError``). Una nueva entrada en ``Rol`` se refleja
# automáticamente; añadir el CHECK reintroduciría la duplicación
# que rompe la regla 4 y requeriría una migración nueva cada vez
# que se agregue un rol (audit engram:14516).
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

# Narrower projection than ``LIST_USERS_SQL`` (no ``fecha_alta``) so the
# auth-revalidation cache test spy (issue #143) can differentiate the
# auth-revalidation call (this one) from the duplicate-check call in
# ``add_authorized_user`` (``_CHECK_DUPLICATE_EMAIL_SQL``). The legacy
# ``app.core.auth.get_user_by_email`` test suite keys on the WHERE
# clause, not the projection.
GET_USER_BY_EMAIL_SQL = """
SELECT id, email, rol, activo
FROM usuarios_autorizados
WHERE email = $1
  AND activo = true
"""

# Distinct from ``GET_USER_BY_EMAIL_SQL`` so the test spy (issue #143)
# can differentiate the auth-revalidation call (needs a fake row) from
# the duplicate-check call (must NOT be intercepted). Uses a narrower
# column set so the WHERE clause is the only thing they share.
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

# The conditional WHERE enforces the last-developer guard at the SQL
# level (issue #279): when deactivating a developer, the UPDATE only
# succeeds if at least one other active developer exists. On zero rows,
# the adapter disambiguates via ``GET_USER_BY_ID_SQL`` plus the private
# ``_has_other_active_developers`` helper.
#
# Substring contract: ``"SET activo = false"`` and ``"RETURNING id,
# email, rol, activo"`` — used by ``tests/test_auth.py`` to route
# fake-SQL responses to the right handler.
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

# Substring contract: ``"SELECT EXISTS"`` — used by
# ``tests/test_auth.py`` to route the last-developer disambiguation
# response (the helper returns ``{"exists": True/False}``).
_CHECK_OTHER_DEVELOPERS_SQL = """
SELECT EXISTS(
    SELECT 1 FROM usuarios_autorizados
     WHERE rol = 'developer' AND activo = true AND id <> $1
)
"""

# Substring contract: ``"SELECT id, email, rol, activo FROM
# usuarios_autorizados WHERE id = $1"`` — used by
# ``tests/test_admin.py::_FakeInsForge.execute_sql`` to route the
# disambiguation query that fires when the conditional UPDATE
# returns zero rows.
GET_USER_BY_ID_SQL = """
SELECT id, email, rol, activo
FROM usuarios_autorizados
WHERE id = $1
"""
