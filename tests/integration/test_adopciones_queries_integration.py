"""Integration tests for ``app.modules.adopciones.queries``.

Executes every exported query builder against the real Postgres fixture
to validate that the generated SQL is valid and returns the expected rows.

Issue #329: SQL is never executed against a real Postgres engine.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.modules.adopciones import queries as q
from tests.integration.conftest import _EphemeralPostgres


def _seed_adopcion_related_records(ep: _EphemeralPostgres) -> dict[str, str]:
    """Create minimum related records for adopcion tests.

    Returns dict with animal_id, voluntario_id, entrada_id.
    """
    animal_id = str(uuid4())
    ep.execute(
        f"INSERT INTO animales (id, nombre, especie, fecha_alta, activo) "
        f"VALUES ('{animal_id}', 'Bobby', 'Perro', now(), true)"
    )

    voluntario_id = str(uuid4())
    ep.execute(
        f"INSERT INTO voluntarios (id, nombre, email, rol, activo, fecha_alta) "
        f"VALUES ('{voluntario_id}', 'Juan Perez', 'juan@test.com', 'voluntario', true, now())"
    )

    entrada_id = str(uuid4())
    ep.execute(
        f"INSERT INTO entradas (id, animal_id, motivo, observaciones, fecha_alta, activo) "
        f"VALUES ('{entrada_id}', '{animal_id}', 'Ingreso', 'Test', now(), true)"
    )

    return {
        "animal_id": animal_id,
        "voluntario_id": voluntario_id,
        "entrada_id": entrada_id,
    }


@pytest.mark.integration
def test_build_adopcion_insert(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_adopcion_insert creates an adopcion and returns it."""
    related = _seed_adopcion_related_records(ephemeral_postgres)

    sql, params = q.build_adopcion_insert(
        {
            "animal_id": related["animal_id"],
            "voluntario_seguimiento_id": related["voluntario_id"],
            "fecha_adopcion": date.today().isoformat(),
            "nombre_adoptante": "Maria Lopez",
            "dni_adoptante": "12345678A",
            "telefono_adoptante": "600123456",
            "email_adoptante": "maria@test.com",
            "entrada_origen_id": related["entrada_id"],
            "tipo_adopcion": "regular",
        }
    )
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["animal_id"] == related["animal_id"]
    assert rows[0]["nombre_adoptante"] == "Maria Lopez"
    assert rows[0]["activo"] is True


@pytest.mark.integration
def test_build_adopcion_list(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_adopcion_list returns active adopciones."""
    related = _seed_adopcion_related_records(ephemeral_postgres)

    # Insert adopciones
    sql1, params1 = q.build_adopcion_insert(
        {
            "animal_id": related["animal_id"],
            "fecha_adopcion": date.today().isoformat(),
            "nombre_adoptante": "Carlos Garcia",
            "tipo_adopcion": "regular",
        }
    )
    ephemeral_postgres.execute(sql1, params1)

    # List
    sql, params = q.build_adopcion_list()
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) >= 1
    adoptantes = [r["nombre_adoptante"] for r in rows]
    assert "Carlos Garcia" in adoptantes


@pytest.mark.integration
def test_build_adopcion_get_by_id(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_adopcion_get_by_id returns the correct adopcion."""
    related = _seed_adopcion_related_records(ephemeral_postgres)

    # Insert first
    insert_sql, insert_params = q.build_adopcion_insert(
        {
            "animal_id": related["animal_id"],
            "fecha_adopcion": date.today().isoformat(),
            "nombre_adoptante": "Ana Martinez",
            "tipo_adopcion": "regular",
        }
    )
    inserted = ephemeral_postgres.execute(insert_sql, insert_params)
    adopcion_id = inserted[0]["id"]

    # Fetch
    sql, params = q.build_adopcion_get_by_id(str(adopcion_id))
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["id"] == adopcion_id
    assert rows[0]["nombre_adoptante"] == "Ana Martinez"


@pytest.mark.integration
def test_build_adopcion_update(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_adopcion_update modifies an adopcion and returns it."""
    related = _seed_adopcion_related_records(ephemeral_postgres)

    # Insert first
    insert_sql, insert_params = q.build_adopcion_insert(
        {
            "animal_id": related["animal_id"],
            "fecha_adopcion": date.today().isoformat(),
            "nombre_adoptante": "Pedro Sanchez",
            "tipo_adopcion": "regular",
        }
    )
    inserted = ephemeral_postgres.execute(insert_sql, insert_params)
    adopcion_id = inserted[0]["id"]

    # Update
    sql, params = q.build_adopcion_update(
        str(adopcion_id),
        {"nombre_adoptante": "Pedro Sanchez Actualizado", "telefono_adoptante": "600654321"},
    )
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["nombre_adoptante"] == "Pedro Sanchez Actualizado"
    assert rows[0]["telefono_adoptante"] == "600654321"


@pytest.mark.integration
def test_build_adopcion_delete(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_adopcion_delete soft-deletes the adopcion."""
    related = _seed_adopcion_related_records(ephemeral_postgres)

    # Insert first
    insert_sql, insert_params = q.build_adopcion_insert(
        {
            "animal_id": related["animal_id"],
            "fecha_adopcion": date.today().isoformat(),
            "nombre_adoptante": "Laura Rodriguez",
            "tipo_adopcion": "regular",
        }
    )
    inserted = ephemeral_postgres.execute(insert_sql, insert_params)
    adopcion_id = inserted[0]["id"]

    # Delete
    sql, params = q.build_adopcion_delete(str(adopcion_id))
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["id"] == adopcion_id

    # Verify inactive
    get_sql, get_params = q.build_adopcion_get_by_id(str(adopcion_id))
    get_rows = ephemeral_postgres.execute(get_sql, get_params)
    assert get_rows[0]["activo"] is False


@pytest.mark.integration
def test_build_adopcion_search(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_adopcion_search finds adopciones by adoptante name partial match."""
    related = _seed_adopcion_related_records(ephemeral_postgres)

    # Insert
    insert_sql, insert_params = q.build_adopcion_insert(
        {
            "animal_id": related["animal_id"],
            "fecha_adopcion": date.today().isoformat(),
            "nombre_adoptante": "Sofia Hernandez",
            "tipo_adopcion": "regular",
        }
    )
    ephemeral_postgres.execute(insert_sql, insert_params)

    # Search
    sql, params = q.build_adopcion_search("Sofia")
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) >= 1
    nombres = [r["nombre_adoptante"] for r in rows]
    assert "Sofia Hernandez" in nombres


@pytest.mark.integration
def test_build_adopcion_check_animal(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_adopcion_check_animal returns the animal id if active."""
    related = _seed_adopcion_related_records(ephemeral_postgres)

    sql, params = q.build_adopcion_check_animal(related["animal_id"])
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["id"] == related["animal_id"]


@pytest.mark.integration
def test_build_adopcion_check_voluntario(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_adopcion_check_voluntario returns the voluntario id if active."""
    related = _seed_adopcion_related_records(ephemeral_postgres)

    sql, params = q.build_adopcion_check_voluntario(related["voluntario_id"])
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["id"] == related["voluntario_id"]


@pytest.mark.integration
def test_build_adopcion_check_entrada(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_adopcion_check_entrada returns the entrada id."""
    related = _seed_adopcion_related_records(ephemeral_postgres)

    sql, params = q.build_adopcion_check_entrada(related["entrada_id"])
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["id"] == related["entrada_id"]
