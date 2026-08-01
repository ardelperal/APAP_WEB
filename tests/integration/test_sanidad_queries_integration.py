"""Integration tests for ``app.modules.sanidad.queries``.

Executes the exported query builder against the real Postgres fixture
to validate that the generated SQL is valid and returns the expected rows.

Issue #329: SQL is never executed against a real Postgres engine.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.modules.sanidad import queries as q
from tests.integration.conftest import _EphemeralPostgres


def _seed_sanidad_related_records(ep: _EphemeralPostgres) -> dict[str, str]:
    """Create minimum related records for sanidad batch tests.

    Returns dict with animal_id, voluntario_id, tipo_actuacion_id.
    """
    animal_id = str(uuid4())
    ep.execute(
        f"INSERT INTO animales (id, nchip, nombreanimal, especie, sexo, fnacimiento, fecha_alta, activo) "
        f"VALUES ('{animal_id}', 'CHIP-TEST-NUBE', 'Nube', 'FELINA', 'H', '2019-01-01', now(), true) "
        f"RETURNING id"
    )

    voluntario_id = str(uuid4())
    ep.execute(
        f"INSERT INTO voluntarios (id, voluntario, email, activo, fecha_alta) "
        f"VALUES ('{voluntario_id}', 'Dr. Garcia', 'garcia@test.com', true, now()) "
        f"RETURNING id"
    )

    tipo_id = str(uuid4())
    ep.execute(
        f"INSERT INTO catalogos_pruebas (id, codigo, nombre, especie, observaciones, activo) "
        f"VALUES ('{tipo_id}', 'sanidad-vacuna', 'Vacuna', 'ambos', 'sanidad', true) "
        f"RETURNING id"
    )

    return {
        "animal_id": animal_id,
        "voluntario_id": voluntario_id,
        "tipo_actuacion_id": tipo_id,
    }


@pytest.mark.integration
def test_build_batch_insert(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """build_batch_insert runs the full CTE: FK checks + validation + INSERT.

    The builder returns a single SQL statement that validates all FKs
    and inserts only if all records pass.
    """
    related = _seed_sanidad_related_records(ephemeral_postgres)

    records = [
        {
            "animal_id": related["animal_id"],
            "voluntario_id": related["voluntario_id"],
            "fecha": date.today().isoformat(),
            "tipo_actuacion_id": related["tipo_actuacion_id"],
            "veterinario": "Dr. Smith",
            "observaciones": "Primera dosis",
            "material_utilizado": "Vacuna 1ml",
        },
    ]

    sql, params = q.build_batch_insert(records, dry_run=False)
    rows = ephemeral_postgres.execute(sql, params)

    # The CTE returns inserted rows (kind='inserted') and validation error rows
    inserted = [r for r in rows if r.get("kind") == "inserted"]
    assert len(inserted) == 1
    assert inserted[0]["animal_id"] == related["animal_id"]
    assert inserted[0]["veterinario"] == "Dr. Smith"


@pytest.mark.integration
def test_build_resumen_sanitario(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_resumen_sanitario returns one row per tipo with the latest actuation."""
    related = _seed_sanidad_related_records(ephemeral_postgres)

    # Insert an actuacion so there's data to return
    actuacion_id = str(uuid4())
    ephemeral_postgres.execute(
        f"INSERT INTO actuaciones (id, animal_id, voluntario_id, tipo_actuacion_id, "
        f"fecha, veterinario, observaciones, material_utilizado, activo, fecha_alta) "
        f"VALUES ('{actuacion_id}', '{related['animal_id']}', "
        f"'{related['voluntario_id']}', '{related['tipo_actuacion_id']}', "
        f"now(), 'Dr. Smith', 'Primera dosis', 'Vacuna 1ml', true, now())"
    )

    sql, params = q.build_resumen_sanitario(related["animal_id"])
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) >= 1
    # Check the row has the expected columns from the resumen sanitario query
    assert rows[0]["animal_id"] == related["animal_id"]


@pytest.mark.integration
def test_build_get_animal_nchip(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_get_animal_nchip returns the nchip for an active animal."""
    related = _seed_sanidad_related_records(ephemeral_postgres)

    # Insert an nchip for the animal
    nchip_value = "ABC123456"
    ephemeral_postgres.execute(
        f"UPDATE animales SET nchip = '{nchip_value}' WHERE id = '{related['animal_id']}'"
    )

    sql, params = q.build_get_animal_nchip(related["animal_id"])
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["nchip"] == nchip_value
