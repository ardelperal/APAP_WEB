"""Real-Postgres coverage for the health scheduling query seam."""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.sanidad.queries import (
    build_batch_insert,
    build_get_animal_nchip,
    build_proximas_pruebas_sql,
    build_resumen_sanitario,
)
from tests.integration.conftest import _EphemeralPostgres


@pytest.mark.integration
def test_build_proximas_pruebas_sql(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """The generated report query executes against the canonical schema."""
    sql, params = build_proximas_pruebas_sql(
        date(2026, 1, 1),
        date(2026, 1, 31),
    )

    rows = ephemeral_postgres.execute(sql, params)

    assert rows == []


@pytest.mark.integration
def test_build_get_animal_nchip(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """The active-animal lookup executes and returns no unknown animal."""
    sql, params = build_get_animal_nchip("00000000-0000-0000-0000-000000000000")

    assert ephemeral_postgres.execute(sql, params) == []


@pytest.mark.integration
def test_build_resumen_sanitario(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """The health summary executes and returns no unknown animal."""
    sql, params = build_resumen_sanitario(
        "00000000-0000-0000-0000-000000000000"
    )

    assert ephemeral_postgres.execute(sql, params) == []


@pytest.mark.integration
def test_build_batch_insert(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """Dry-run validation rejects an empty record without persisting it."""
    sql, params = build_batch_insert([{}], dry_run=True)

    rows = ephemeral_postgres.execute(sql, params)

    assert len(rows) == 1
    assert rows[0]["kind"] == "validation_error"
