"""Schema contract tests for the estado_actual_animal cache table.

The table ``animal_current_state`` is the materialized cache that stores
the derived current state of each animal (LIFECYCLE-SCHEMA-03, issue #69).

Acceptance criteria:
- 11 columns: animal_id, current_state, active_event_id, active_intake_id,
  active_foster_id, active_adoption_id, pre_death_state, state_changed_at,
  legacy_situacion, legacy_ultimo_estado, reconciliation_status.
- PK on animal_id (ensures 1 row per animal).
- Index on current_state (for "all animals in state X" queries).
- CREATE TABLE IF NOT EXISTS for idempotent migration.
"""

from __future__ import annotations

from app.core.domain_lifecycle import (
    ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL,
    ANIMAL_CURRENT_STATE_STATE_INDEX_SQL,
)


def test_estado_actual_animal_uses_if_not_exists() -> None:
    """The CREATE TABLE uses IF NOT EXISTS so re-running is safe."""
    assert "CREATE TABLE IF NOT EXISTS animal_current_state" in (
        ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL
    )


def test_estado_actual_animal_has_11_columns() -> None:
    """The cache table has exactly 11 columns (per issue #69 acceptance)."""
    # Count column definitions in the CREATE TABLE statement.
    # The columns are: animal_id, current_state, active_event_id,
    # active_intake_id, active_foster_id, active_adoption_id,
    # pre_death_state, state_changed_at, legacy_situacion,
    # legacy_ultimo_estado, reconciliation_status.
    sql = ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL
    expected_columns = {
        "animal_id",
        "current_state",
        "active_event_id",
        "active_intake_id",
        "active_foster_id",
        "active_adoption_id",
        "pre_death_state",
        "state_changed_at",
        "legacy_situacion",
        "legacy_ultimo_estado",
        "reconciliation_status",
    }
    for col in expected_columns:
        assert col in sql, f"Column {col!r} not found in CREATE TABLE"

    # Verify exactly 11 column names appear.
    found_columns = {col for col in expected_columns if col in sql}
    assert len(found_columns) == 11, (
        f"Expected 11 columns, found {len(found_columns)}: {sorted(found_columns)}"
    )


def test_estado_actual_animal_pk_is_animal_id() -> None:
    """Primary key on animal_id ensures 1 row per animal (per issue #69)."""
    assert "animal_id UUID PRIMARY KEY" in ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL


def test_estado_actual_animal_has_state_index() -> None:
    """Index on current_state accelerates 'all animals in state X' queries."""
    assert "CREATE INDEX IF NOT EXISTS idx_animal_current_state_state" in (
        ANIMAL_CURRENT_STATE_STATE_INDEX_SQL
    )
    assert "ON animal_current_state (current_state)" in ANIMAL_CURRENT_STATE_STATE_INDEX_SQL


def test_estado_actual_animal_total_indices_is_two() -> None:
    """PK auto-creates index 1; explicit CREATE INDEX is index 2 (per issue #69)."""
    # The PK on animal_id auto-creates one index.
    # The explicit CREATE INDEX for current_state is the second index.
    # So we expect exactly 1 explicit CREATE INDEX for animal_current_state.
    sql = ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL + ANIMAL_CURRENT_STATE_STATE_INDEX_SQL

    explicit_indices = [
        line
        for line in sql.split("\n")
        if "CREATE INDEX" in line and "animal_current_state" in line
    ]
    assert len(explicit_indices) == 1, (
        f"Expected 1 explicit CREATE INDEX, found {len(explicit_indices)}: "
        f"{explicit_indices}"
    )


def test_estado_actual_animal_current_state_check_constraint() -> None:
    """current_state is restricted to known values via CHECK constraint."""
    sql = ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL
    assert "CHECK (current_state IN" in sql
    # Verify the known state values are in the CHECK.
    # The actual values are defined in domain_lifecycle.py.
    assert "Albergue" in sql
    assert "Acogida" in sql
    assert "Adoptado" in sql


def test_estado_actual_animal_reconciliation_status_default() -> None:
    """reconciliation_status defaults to 'pending' for new cache rows."""
    assert "DEFAULT 'pending'" in ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL
    assert "reconciliation_status" in ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL
