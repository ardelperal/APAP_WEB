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
        f"INSERT INTO animales (id, nombre, especie, fecha_alta, activo) "
        f"VALUES ('{animal_id}', 'Nube', 'Gato', now(), true)"
    )

    voluntario_id = str(uuid4())
    ep.execute(
        f"INSERT INTO voluntarios (id, nombre, email, rol, activo, fecha_alta) "
        f"VALUES ('{voluntario_id}', 'Dr. Garcia', 'garcia@ vets.com', 'sanitario', true, now())"
    )

    tipo_id = str(uuid4())
    ep.execute(
        f"INSERT INTO catalogos_pruebas (id, nombre, tipo, activo) "
        f"VALUES ('{tipo_id}', 'Vacuna', 'sanidad', true)"
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
