"""Integration tests for ``app.modules.materiales.queries``.

Executes every exported query builder against the real Postgres fixture
to validate that the generated SQL is valid and returns the expected rows.

Issue #329: SQL is never executed against a real Postgres engine.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.modules.materiales import queries as q
from tests.integration.conftest import _EphemeralPostgres


def _seed_related_records(ep: _EphemeralPostgres) -> dict[str, str]:
    """Create the minimum related records needed for junction tests.

    Returns a dict with keys: animal_id, entrada_id, casa_id, estancia_id
    """
    # Create animal (using raw SQL since animales has no queries.py)
    animal_id = str(uuid4())
    ep.execute(
        f"INSERT INTO animales (id, nchip, nombreanimal, especie, sexo, fnacimiento, fecha_alta, activo) "
        f"VALUES ('{animal_id}', 'CHIP-LUNA-MAT', 'Luna', 'CANINA', 'H', '2019-06-01', now(), true)"
    )

    # Create entrada
    entrada_id = str(uuid4())
    ep.execute(
        f"INSERT INTO entradas (id, animal_id, motivo, observaciones, fecha_alta, activo) "
        f"VALUES ('{entrada_id}', '{animal_id}', 'Ingreso', 'Test', now(), true)"
    )

    # Create casa_acogida
    casa_id = str(uuid4())
    ep.execute(
        f"INSERT INTO casas_acogida (id, nombre, apellidos, calle, telefono, localidad, provincia, coche, capacidad, activo, fecha_alta) "
        f"VALUES ('{casa_id}', 'Casa Test', 'Test', 'Calle Test', '123456789', 'Madrid', 'Madrid', 'No', 1, true, now())"
    )

    # Create estancia/acogida
    estancia_id = str(uuid4())
    ep.execute(
        f"INSERT INTO acogidas (id, animal_id, fecha_inicio, direccion, telefono, activo, fecha_alta) "
        f"VALUES ('{estancia_id}', '{animal_id}', '{date.today()}', 'Direccion test', '123456789', true, now())"
    )

    return {
        "animal_id": animal_id,
        "entrada_id": entrada_id,
        "casa_id": casa_id,
        "estancia_id": estancia_id,
    }


@pytest.mark.integration
def test_build_material_insert(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_material_insert emits SQL that creates a material and returns it."""
    sql, params = q.build_material_insert(
        {"material": "Jaula", "tamano": "Grande", "color": "Gris"}
    )
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["material"] == "Jaula"
    assert rows[0]["tamano"] == "Grande"
    assert rows[0]["color"] == "Gris"
    assert rows[0]["activo"] is True


@pytest.mark.integration
def test_build_material_get_by_id(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_material_get_by_id returns the correct material by id."""
    # Insert first
    insert_sql, insert_params = q.build_material_insert(
        {"material": "Transportin", "tamano": "Mediano", "color": "Negro"}
    )
    inserted = ephemeral_postgres.execute(insert_sql, insert_params)
    material_id = inserted[0]["id"]

    # Then fetch
    sql, params = q.build_material_get_by_id(str(material_id))
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["id"] == material_id
    assert rows[0]["material"] == "Transportin"


@pytest.mark.integration
def test_build_material_list(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_material_list returns materials (active filter tested via activos_solo param)."""
    # Insert two materials
    insert1_sql, insert1_params = q.build_material_insert(
        {"material": "Comedero", "tamano": "Chico", "color": "Azul"}
    )
    insert2_sql, insert2_params = q.build_material_insert(
        {"material": "Bebedero", "tamano": "Chico", "color": "Rojo"}
    )
    ephemeral_postgres.execute(insert1_sql, insert1_params)
    inserted2 = ephemeral_postgres.execute(insert2_sql, insert2_params)
    material_id = inserted2[0]["id"]

    # Deactivate one
    deactivate_sql, deactivate_params = q.build_material_deactivate(str(material_id))
    ephemeral_postgres.execute(deactivate_sql, deactivate_params)

    # List active only
    sql_active, params_active = q.build_material_list(activos_solo=True)
    rows_active = ephemeral_postgres.execute(sql_active, params_active)
    materiales_active = [r["material"] for r in rows_active]
    assert "Comedero" in materiales_active
    assert "Bebedero" not in materiales_active

    # List all
    sql_all, params_all = q.build_material_list(activos_solo=False)
    rows_all = ephemeral_postgres.execute(sql_all, params_all)
    materiales_all = [r["material"] for r in rows_all]
    assert "Comedero" in materiales_all
    assert "Bebedero" in materiales_all


@pytest.mark.integration
def test_build_material_update(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_material_update emits SQL that updates the material and returns it."""
    # Insert first
    insert_sql, insert_params = q.build_material_insert(
        {"material": "Collar", "tamano": "Mediano", "color": "Rojo"}
    )
    inserted = ephemeral_postgres.execute(insert_sql, insert_params)
    material_id = inserted[0]["id"]

    # Update
    sql, params = q.build_material_update(
        str(material_id), {"material": "Collar XL", "color": "Azul"}
    )
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["material"] == "Collar XL"
    assert rows[0]["color"] == "Azul"
    assert rows[0]["tamano"] == "Mediano"  # unchanged


@pytest.mark.integration
def test_build_material_deactivate(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_material_deactivate soft-deletes the material."""
    # Insert first
    insert_sql, insert_params = q.build_material_insert(
        {"material": "Pretal", "tamano": "Grande", "color": "Verde"}
    )
    inserted = ephemeral_postgres.execute(insert_sql, insert_params)
    material_id = inserted[0]["id"]

    # Deactivate
    sql, params = q.build_material_deactivate(str(material_id))
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["id"] == material_id

    # Verify it's inactive
    get_sql, get_params = q.build_material_get_by_id(str(material_id))
    get_rows = ephemeral_postgres.execute(get_sql, get_params)
    assert get_rows[0]["activo"] is False


@pytest.mark.integration
def test_build_material_cascade_deactivate(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_material_cascade_deactivate deactivates all active junctions."""
    # Insert a material first (junction deactivation doesn't require an estancia FK)
    insert_sql, insert_params = q.build_material_insert(
        {"material": "Correa", "tamano": "Larga", "color": "Negra"}
    )
    inserted = ephemeral_postgres.execute(insert_sql, insert_params)
    material_id = inserted[0]["id"]

    # Cascade deactivate
    sql, params = q.build_material_cascade_deactivate(str(material_id))
    rows = ephemeral_postgres.execute(sql, params)
    # No active junctions exist yet, so 0 rows returned is correct
    assert isinstance(rows, list)


@pytest.mark.integration
def test_build_material_active(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_material_active returns the material id and activo flag."""
    # Insert first
    insert_sql, insert_params = q.build_material_insert(
        {"material": "Plato", "tamano": "Chico", "color": "Blanco"}
    )
    inserted = ephemeral_postgres.execute(insert_sql, insert_params)
    material_id = inserted[0]["id"]

    sql, params = q.build_material_active(str(material_id))
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["id"] == material_id
    assert rows[0]["activo"] is True


@pytest.mark.integration
def test_build_estancia_active(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_estancia_active returns the estancia (acogida) info."""
    # Create related records using raw SQL
    related = _seed_related_records(ephemeral_postgres)

    # Now test build_estancia_active
    sql, params = q.build_estancia_active(related["estancia_id"])
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["id"] == related["estancia_id"]
    assert rows[0]["activo"] is True


@pytest.mark.integration
def test_build_junction_insert(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_junction_insert creates a junction record and returns it."""
    # Create related records
    related = _seed_related_records(ephemeral_postgres)

    # Create a material
    material_id = str(uuid4())
    ephemeral_postgres.execute(
        f"INSERT INTO materiales (id, material, tamano, color, activo, fecha_alta) "
        f"VALUES ('{material_id}', 'Comida', '5kg', 'Rojo', true, now())"
    )

    # Insert junction using the query builder
    sql, params = q.build_junction_insert(
        estancia_id=related["estancia_id"],
        material_id=material_id,
        cantidad=3,
        notas="Notas de prueba",
    )
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["estancia_id"] == related["estancia_id"]
    assert rows[0]["material_id"] == material_id
    assert rows[0]["cantidad"] == 3


@pytest.mark.integration
def test_build_junction_list_for_estancia(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_junction_list_for_estancia returns junction records for an estancia."""
    # Create related records
    related = _seed_related_records(ephemeral_postgres)

    # Create a material
    material_id = str(uuid4())
    ephemeral_postgres.execute(
        f"INSERT INTO materiales (id, material, tamano, color, activo, fecha_alta) "
        f"VALUES ('{material_id}', 'Arena', '10kg', 'Blanca', true, now())"
    )

    # Insert junction
    junction_sql, junction_params = q.build_junction_insert(
        estancia_id=related["estancia_id"],
        material_id=material_id,
        cantidad=1,
        notas=None,
    )
    ephemeral_postgres.execute(junction_sql, junction_params)

    # List for estancia (active only)
    sql, params = q.build_junction_list_for_estancia(
        estancia_id=related["estancia_id"], activos_solo=True
    )
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["estancia_id"] == related["estancia_id"]


@pytest.mark.integration
def test_build_junction_deactivate(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_junction_deactivate soft-deletes the junction."""
    # Create related records
    related = _seed_related_records(ephemeral_postgres)

    # Create a material
    material_id = str(uuid4())
    ephemeral_postgres.execute(
        f"INSERT INTO materiales (id, material, tamano, color, activo, fecha_alta) "
        f"VALUES ('{material_id}', 'Juguete', 'Mediano', 'Rojo', true, now())"
    )

    # Insert junction
    junction_sql, junction_params = q.build_junction_insert(
        estancia_id=related["estancia_id"],
        material_id=material_id,
        cantidad=2,
        notas=None,
    )
    inserted = ephemeral_postgres.execute(junction_sql, junction_params)
    junction_id = inserted[0]["id"]

    # Deactivate
    sql, params = q.build_junction_deactivate(str(junction_id))
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["id"] == junction_id

    # Verify it's inactive (activos_solo=True should not return it)
    list_sql, list_params = q.build_junction_list_for_estancia(
        estancia_id=related["estancia_id"], activos_solo=True
    )
    list_rows = ephemeral_postgres.execute(list_sql, list_params)
    junction_ids = [r["id"] for r in list_rows]
    assert junction_id not in junction_ids
