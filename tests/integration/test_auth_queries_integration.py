"""Integration tests for ``app.core.auth`` revalidation against real Postgres.

Closes the P0 gap documented in ``docs/quality/test-audit.md``
§Critical-gaps point 3: the auth revalidation path (issue #143) is
mocked today via ``auth_reval_rows`` in the test suite, so the
end-to-end round-trip cookie + DB revalidation has never been
exercised against a real engine. These atoms assert that:

  1. ``get_user_by_email`` (the DB revalidation step behind
     ``require_authorized_user``) returns the row when the user is
     active in real Postgres.
  2. After flipping ``activo=false`` in the database, the same call
     returns ``None`` — the production code path would then map to
     a 302 redirect to ``/unauthorized`` at the route layer.
  3. The schema column type for ``activo`` is honoured: a real
     ``UPDATE ... SET activo = false`` propagates and the SELECT
     with ``WHERE activo = true`` stops matching.

The unit-test suite (``tests/test_auth.py``) verifies the wire-shape
of the SQL and the ``BackendError`` translation logic. This integration
atom verifies the actual Postgres-side guarantee that a deactivated
user is no longer returned by the revalidation query.

The ``usuarios_autorizados`` table is created in the atom from
``auth_insforge_queries.CREATE TABLE`` rather than relying on the
domain conftest, because ``app.core.auth`` lives in the core layer
(not a domain module) and the integration conftest only provisions
the domain tables. The CREATE is idempotent (IF NOT EXISTS) so the
ephemeral schema can run this atom alongside any other integration
atom without conflicts.
"""

from __future__ import annotations

import pytest

from app.core import auth
from app.core.adapters.insforge.auth_insforge_queries import (
    CREATE_TABLE_SQL,
    DEACTIVATE_USER_SQL,
)
from tests.integration.conftest import _EphemeralPostgres


class _PsycopgSqlExecutor:
    """Adapter that maps the SqlExecutor protocol onto the ephemeral
    Postgres test fixture.

    The fixture exposes ``execute(query, params)`` (the helper used by
    every existing integration atom), but the production
    ``SqlExecutor`` protocol is ``execute_sql(query, params)``. The
    auth adapter (``StubAuthUsersPort.get_user_by_email``) calls
    the latter. This shim bridges the naming gap so we can exercise the
    real production adapter against the real Postgres engine without
    standing up an InsForge HTTP server.
    """

    def __init__(self, ep: _EphemeralPostgres) -> None:
        self._ep = ep

    def execute_sql(self, query: str, params: list | None = None) -> list[dict]:
        return self._ep.execute(query, params)


def _ensure_schema(ep: _EphemeralPostgres) -> None:
    """Idempotently create ``usuarios_autorizados`` in the ephemeral schema.

    The domain conftest provisions only the domain module tables
    (``animales``, ``entradas``, ``cesiones_propietario``, ...). The
    auth core table is created here so the atom is self-contained.
    """
    with ep.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)


def _insert_user(
    ep: _EphemeralPostgres,
    email: str,
    rol: str = "reader",
) -> None:
    """INSERT an active user with the given email/rol.

    Bypasses ``_EphemeralPostgres.execute()`` (which always calls
    ``fetchall()``) and opens a raw connection — same pattern as the
    staging insert in ``test_entradas_queries_integration.py``.
    """
    with ep.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO usuarios_autorizados (email, rol, activo) "
                "VALUES (%s, %s, true)",
                [email, rol],
            )


@pytest.mark.integration
def test_get_user_by_email_returns_user_when_active(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """Active user in the DB must be returned by the revalidation query.

    This is the happy path the production revalidation depends on: every
    request, the cookie's email is looked up against ``usuarios_autorizados``
    and the result gates whether the user keeps the session.
    """
    ep = ephemeral_postgres
    _ensure_schema(ep)
    _insert_user(ep, "ana@test.com", rol="reader")

    user = auth.get_user_by_email(_PsycopgSqlExecutor(ep), "ana@test.com")
    assert user is not None
    assert user["email"] == "ana@test.com"
    assert user["rol"] == "reader"


@pytest.mark.integration
def test_get_user_by_email_returns_none_after_deactivation(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """Deactivating the user in the DB must make the revalidation
    query return ``None``.

    This is the audit's P0 atom: the cookie + DB round-trip must agree.
    The revalidation path in production is
    ``require_authorized_user → get_user_by_email → if None: redirect
    /unauthorized``. A None return here, against real Postgres, closes
    the gap.
    """
    ep = ephemeral_postgres
    _ensure_schema(ep)
    _insert_user(ep, "berta@test.com", rol="reader")

    # Sanity: the active row is fetchable.
    assert auth.get_user_by_email(_PsycopgSqlExecutor(ep), "berta@test.com") is not None

    # Operator deactivates the user.
    ep.execute(
        DEACTIVATE_USER_SQL,
        [None],  # body of DEACTIVATE_USER_SQL filters by id; we use direct UPDATE
    )
    # ``DEACTIVATE_USER_SQL`` filters by ``id = $N``; since we just inserted
    # the row without capturing the id, the above is a no-op. Do the
    # deactivation by direct UPDATE on email to keep the atom focused on
    # the constraint, not the deactivation use case (which has its own
    # unit tests in ``tests/test_auth.py``).
    with ep.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE usuarios_autorizados SET activo = false WHERE email = %s",
                ["berta@test.com"],
            )

    # Now the revalidation query must return None. The production path
    # would redirect to /unauthorized.
    assert auth.get_user_by_email(_PsycopgSqlExecutor(ep), "berta@test.com") is None


@pytest.mark.integration
def test_get_user_by_email_normalises_case(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """Email lookup normalises to canonical form (issue #278).

    Two requests for the same email but with different case must
    resolve to the same row. The canonical form is lowercased +
    stripped; the ``auth_helpers.normalize_email`` helper handles the
    case folding. The integration atom pins that the SQL itself, plus
    the normalisation, agree on a single canonical row.
    """
    ep = ephemeral_postgres
    _ensure_schema(ep)
    _insert_user(ep, "carla@test.com", rol="reader")

    # Mixed-case request resolves to the canonical row.
    upper = auth.get_user_by_email(_PsycopgSqlExecutor(ep), "  CARLA@Test.COM  ")
    assert upper is not None
    assert upper["email"] == "carla@test.com"


@pytest.mark.integration
def test_get_user_by_email_returns_none_for_missing_user(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """A request for an email that has no row in the DB must return None.

    Companion to the deactivation atom: covers the case where the
    cookie is forged or the user was deleted. Production revalidation
    redirects to /login in that case.
    """
    ep = ephemeral_postgres
    _ensure_schema(ep)

    assert auth.get_user_by_email(_PsycopgSqlExecutor(ep), "ghost@test.com") is None
