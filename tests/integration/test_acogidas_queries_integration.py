"""Integration tests for ``app.modules.acogidas.queries``.

Executes every exported query builder against the real Postgres fixture
to validate that the generated SQL is valid and returns the expected rows.

Issue #329: SQL is never executed against a real Postgres engine.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.modules.acogidas import queries as q
from tests.integration.conftest import _EphemeralPostgres


def _seed_acogida_related_records(ep: _EphemeralPostgres) -> dict[str, str]:
    """Create minimum related records for acogidas tests.

    Returns dict with animal_id, voluntario_id, entrada_id, casa_id.
    """
    animal_id = str(uuid4())
    ep.execute(
        f"INSERT INTO animales (id, nchip, nombreanimal, especie, sexo, fnacimiento, fecha_alta, activo) "
        f"VALUES ('{animal_id}', 'CHIP-LUNA-001', 'Luna', 'CANINA', 'H', '2019-06-01', now(), true)"
    )

    voluntario_id = str(uuid4())
    ep.execute(
        f"INSERT INTO voluntarios (id, voluntario, email, activo, fecha_alta) "
        f"VALUES ('{voluntario_id}', 'Ana Lopez', 'ana@test.com', true, now())"
    )

    entrada_id = str(uuid4())
    ep.execute(
        f"INSERT INTO entradas (id, animal_id, fecha_entrada, motivo, observaciones, fecha_alta, activo) "
        f"VALUES ('{entrada_id}', '{animal_id}', '2024-01-15', 'Ingreso', 'Test', now(), true)"
    )

    casa_id = str(uuid4())
    ep.execute(
        f"INSERT INTO casas_acogida (id, nombre, apellidos, calle, telefono, localidad, provincia, coche, capacidad, activo, fecha_alta) "
        f"VALUES ('{casa_id}', 'Casa Luna', 'Test', 'Calle Sol 1', '600111222', 'Madrid', 'Madrid', 'No', 1, true, now())"
    )

    return {
        "animal_id": animal_id,
        "voluntario_id": voluntario_id,
        "entrada_id": entrada_id,
        "casa_id": casa_id,
    }


@pytest.mark.integration
def test_build_acogida_insert(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """build_acogida_insert creates an acogida and returns it."""
    related = _seed_acogida_related_records(ephemeral_postgres)

    sql, params = q.build_acogida_insert(
        {
            "animal_id": related["animal_id"],
            "casa_acogida_id": related["casa_id"],
            "fecha_inicio": date.today().isoformat(),
            "direccion": "Calle test",
            "telefono": "600123456",
        }
    )
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["animal_id"] == related["animal_id"]
    assert rows[0]["casa_acogida_id"] == related["casa_id"]
    assert rows[0]["activo"] is True


@pytest.mark.integration
def test_build_acogida_get_by_id(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """build_acogida_get_by_id returns the correct acogida."""
    related = _seed_acogida_related_records(ephemeral_postgres)

    # Insert first
    insert_sql, insert_params = q.build_acogida_insert(
        {
            "animal_id": related["animal_id"],
            "casa_acogida_id": related["casa_id"],
            "fecha_inicio": date.today().isoformat(),
            "direccion": "Calle test 2",
            "telefono": "600654321",
        }
    )
    inserted = ephemeral_postgres.execute(insert_sql, insert_params)
    acoge_id = inserted[0]["id"]

    # Fetch
    sql, params = q.build_acogida_get_by_id(str(acoge_id))
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["id"] == acoge_id


@pytest.mark.integration
def test_build_acogida_list(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """build_acogida_list returns acogidas (both active-only and all)."""
    related = _seed_acogida_related_records(ephemeral_postgres)

    # Insert
    insert_sql, insert_params = q.build_acogida_insert(
        {
            "animal_id": related["animal_id"],
            "casa_acogida_id": related["casa_id"],
            "fecha_inicio": date.today().isoformat(),
            "direccion": "Calle test 3",
            "telefono": "600111222",
        }
    )
    inserted = ephemeral_postgres.execute(insert_sql, insert_params)
    acoge_id = inserted[0]["id"]

    # List all
    sql_all, params_all = q.build_acogida_list(activas_solo=False)
    rows_all = ephemeral_postgres.execute(sql_all, params_all)
    assert len(rows_all) >= 1

    # List active only
    sql_active, params_active = q.build_acogida_list(activas_solo=True)
    rows_active = ephemeral_postgres.execute(sql_active, params_active)
    ids = [r["id"] for r in rows_active]
    assert acoge_id in ids


@pytest.mark.integration
def test_build_acogida_update(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """build_acogida_update modifies an acogida and returns it."""
    related = _seed_acogida_related_records(ephemeral_postgres)

    # Insert first
    insert_sql, insert_params = q.build_acogida_insert(
        {
            "animal_id": related["animal_id"],
            "casa_acogida_id": related["casa_id"],
            "fecha_inicio": date.today().isoformat(),
            "direccion": "Calle original",
            "telefono": "600000000",
        }
    )
    inserted = ephemeral_postgres.execute(insert_sql, insert_params)
    acogida_id = inserted[0]["id"]

    # Update
    sql, params = q.build_acogida_update(
        str(acogida_id), {"direccion": "Calle actualizada", "telefono": "600999999"}
    )
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["direccion"] == "Calle actualizada"
    assert rows[0]["telefono"] == "600999999"


@pytest.mark.integration
def test_build_acogida_close(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """build_acogida_close sets fecha_final but keeps activo=true."""
    related = _seed_acogida_related_records(ephemeral_postgres)

    # Insert first
    insert_sql, insert_params = q.build_acogida_insert(
        {
            "animal_id": related["animal_id"],
            "casa_acogida_id": related["casa_id"],
            "fecha_inicio": date.today().isoformat(),
            "direccion": "Calle close",
            "telefono": "600777777",
        }
    )
    inserted = ephemeral_postgres.execute(insert_sql, insert_params)
    acoge_id = inserted[0]["id"]

    # Close
    sql, params = q.build_acogida_close(str(acoge_id))
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["id"] == acoge_id
    assert rows[0]["fecha_final"] is not None
    assert rows[0]["activo"] is True


@pytest.mark.integration
def test_build_acogida_delete(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """build_acogida_delete soft-deletes the acogida."""
    related = _seed_acogida_related_records(ephemeral_postgres)

    # Insert first
    insert_sql, insert_params = q.build_acogida_insert(
        {
            "animal_id": related["animal_id"],
            "casa_acogida_id": related["casa_id"],
            "fecha_inicio": date.today().isoformat(),
            "direccion": "Calle delete",
            "telefono": "600888888",
        }
    )
    inserted = ephemeral_postgres.execute(insert_sql, insert_params)
    acoge_id = inserted[0]["id"]

    # Delete
    sql, params = q.build_acogida_delete(str(acoge_id))
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["id"] == acoge_id

    # Verify inactive
    get_sql, get_params = q.build_acogida_get_by_id(str(acoge_id))
    get_rows = ephemeral_postgres.execute(get_sql, get_params)
    assert get_rows[0]["activo"] is False


@pytest.mark.integration
def test_build_acogida_check_animal(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """build_acogida_check_animal returns the animal id and activo."""
    related = _seed_acogida_related_records(ephemeral_postgres)

    sql, params = q.build_acogida_check_animal(related["animal_id"])
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["id"] == related["animal_id"]


@pytest.mark.integration
def test_build_acogida_check_casa(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """build_acogida_check_casa returns the casa id if active."""
    related = _seed_acogida_related_records(ephemeral_postgres)

    sql, params = q.build_acogida_check_casa(related["casa_id"])
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["id"] == related["casa_id"]


@pytest.mark.integration
def test_build_acogida_check_voluntario(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """build_acogida_check_voluntario returns the voluntario id if active."""
    related = _seed_acogida_related_records(ephemeral_postgres)

    sql, params = q.build_acogida_check_voluntario(related["voluntario_id"])
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["id"] == related["voluntario_id"]


@pytest.mark.integration
def test_build_acogida_check_entrada(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """build_acogida_check_entrada returns the entrada id."""
    related = _seed_acogida_related_records(ephemeral_postgres)

    sql, params = q.build_acogida_check_entrada(related["entrada_id"])
    rows = ephemeral_postgres.execute(sql, params)
    assert len(rows) == 1
    assert rows[0]["id"] == related["entrada_id"]


@pytest.mark.integration
def test_build_acogida_link_override(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """build_acogida_link_override links a foster_capacity_overrides row."""
    related = _seed_acogida_related_records(ephemeral_postgres)

    # Create the override row first
    override_id = str(uuid4())
    ephemeral_postgres.execute(
        f"INSERT INTO foster_capacity_overrides "
        f"(id, casa_acogida_id, animal_id, operador_user_id, motivo) "
        f"VALUES ('{override_id}', '{related['casa_id']}', '{related['animal_id']}', '{related['voluntario_id']}', 'test override')"
    )

    # Create an acogida
    insert_sql, insert_params = q.build_acogida_insert(
        {
            "animal_id": related["animal_id"],
            "casa_acogida_id": related["casa_id"],
            "fecha_inicio": date.today().isoformat(),
            "direccion": "Calle link",
            "telefono": "600666666",
        }
    )
    inserted = ephemeral_postgres.execute(insert_sql, insert_params)
    estancia_id = inserted[0]["id"]

    # Link the override
    sql, params = q.build_acogida_link_override(
        estancia_id=estancia_id,
        override_id=override_id,
        casa_acogida_id=related["casa_id"],
        animal_id=related["animal_id"],
    )
    rows = ephemeral_postgres.execute(sql, params)
    # The UPDATE returns no rows (RETURNING not in the SQL)
    assert isinstance(rows, list)
