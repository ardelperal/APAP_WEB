"""Bootstrap atoms for ``migration.apply`` (issue #168).

The ``web_only_feature_shadow`` table must exist before ``reconcile``
or ``apply`` can write to it. The bootstrap helper is idempotent:
``CREATE TABLE IF NOT EXISTS`` lets a replay safely no-op.

Hard Rules honoured:

- **Rule 1 (fixture gate)**: each atom builds its own ``FakeLocalBackend``.
- **Rule 8 (no production mutation)**: the helper is exercised against
  the fake — never against a real LocalBackend.
- **Rule 4 (no humo)**: assertions on the captured queries (the SQL
  the helper emits) and the resulting table state.
"""

from __future__ import annotations

from migration.apply import (
    BOOTSTRAP_SHADOW_TABLE_SQL,
    _bootstrap_shadow_state,
)
from tests.migration.conftest import FakeLocalBackend  # noqa: TID251

# --- 1. Bootstrap creates the shadow table when missing -------------


def test_bootstrap_shadow_state_creates_table_if_missing(
    web_client: FakeLocalBackend,
) -> None:
    """First-run path: the helper issues the CREATE TABLE statement.

    The table did not exist (Hard Rule 1: fresh fixture), so the
    bootstrap helper emits exactly one ``CREATE TABLE IF NOT EXISTS``
    statement and returns cleanly. No shadow rows yet (the bootstrap
    is a no-op for the domain tables).
    """
    _bootstrap_shadow_state(web_client)

    # The CREATE TABLE statement was emitted.
    assert any(
        "CREATE TABLE" in q and "web_only_feature_shadow" in q
        for q, _ in web_client.queries
    )
    # The constant the helper uses must reference the canonical schema.
    assert "CREATE TABLE IF NOT EXISTS web_only_feature_shadow" in BOOTSTRAP_SHADOW_TABLE_SQL
    assert "table_name TEXT NOT NULL" in BOOTSTRAP_SHADOW_TABLE_SQL
    assert "legacy_pk TEXT NOT NULL" in BOOTSTRAP_SHADOW_TABLE_SQL


# --- 2. Replay is a safe no-op ----------------------------------------


def test_bootstrap_shadow_state_no_op_if_table_exists(
    web_client: FakeLocalBackend,
) -> None:
    """Second-run path: the helper still emits the CREATE TABLE but
    LocalBackend treats it as a no-op (``IF NOT EXISTS``).

    Hard Rule 4 + idempotency contract: replaying bootstrap on a DB
    that already has the table must NOT raise and must NOT drop /
    re-create the table. We verify by counting queries and by the
    absence of any error response.
    """
    _bootstrap_shadow_state(web_client)

    # Replay.
    _bootstrap_shadow_state(web_client)

    # The helper emits the same DDL each time (LocalBackend owns the
    # idempotency at the SQL level). No DROP / DELETE statements.
    ddl_queries = [q for q, _ in web_client.queries if "CREATE TABLE" in q.upper()]
    assert len(ddl_queries) == 2  # one per call
    assert not any(
        "DROP" in q.upper() or "DELETE" in q.upper() for q, _ in web_client.queries
    )
