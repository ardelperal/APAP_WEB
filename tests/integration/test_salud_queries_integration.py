"""Integration tests for ``app.modules.salud.queries``.

Executes the exported query builders against the real Postgres fixture
to validate that the generated SQL is valid and returns the expected rows.

Issue #329: SQL is never executed against a real Postgres engine.
HEALTH-04 (#53): terapias CRUD — integration coverage added post-merge.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.modules.salud import queries as q
from tests.integration.conftest import _EphemeralPostgres


def _seed_terapia_related_records(ep: _EphemeralPostgres) -> dict[str, str]:
    """Create minimum related records for terapia tests.

    Returns dict with animal_id, voluntario_id.
    """
    animal_id = str(uuid4())
    ep.execute(
        f"INSERT INTO animales (id, nombreanimal, especie, sexo, fnacimiento, fecha_alta, activo) "
        f"VALUES ('{animal_id}', 'Luna', 'FELINA', 'H', '2022-01-15', now(), true)"
    )

    voluntario_id = str(uuid4())
    ep.execute(
        f"INSERT INTO voluntarios (id, voluntario, email, activo, fecha_alta) "
        f"VALUES ('{voluntario_id}', 'Dra. García', 'garcia@vets.com', true, now())"
    )

    return {
        "animal_id": animal_id,
        "voluntario_id": voluntario_id,
    }


@pytest.mark.integration
def test_build_create_terapia(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_create_terapia inserts a terapia and returns the row."""
    related = _seed_terapia_related_records(ephemeral_postgres)

    params = {
        "animal_id": related["animal_id"],
        "voluntario_id": related["voluntario_id"],
        "fecha": date.today().isoformat(),
        "descripcion": "Fisioterapia post-operatoria",
    }
    sql, p = q.build_create_terapia(params)
    rows = ephemeral_postgres.execute(sql, p)

    assert len(rows) == 1
    assert rows[0]["animal_id"] == related["animal_id"]
    assert rows[0]["descripcion"] == "Fisioterapia post-operatoria"
    assert rows[0]["activo"] is True


@pytest.mark.integration
def test_build_list_terapias(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_list_terapias returns all active terapias."""
    related = _seed_terapia_related_records(ephemeral_postgres)

    params = {
        "animal_id": related["animal_id"],
        "voluntario_id": related["voluntario_id"],
        "fecha": date.today().isoformat(),
        "descripcion": "Consulta inicial",
    }
    create_sql, create_p = q.build_create_terapia(params)
    ephemeral_postgres.execute(create_sql, create_p)

    list_sql, list_p = q.build_list_terapias()
    rows = ephemeral_postgres.execute(list_sql, list_p)

    assert len(rows) >= 1
    assert all(r["activo"] is True for r in rows)


@pytest.mark.integration
def test_build_list_terapias_by_animal(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_list_terapias filters by animal_id."""
    related = _seed_terapia_related_records(ephemeral_postgres)

    params = {
        "animal_id": related["animal_id"],
        "voluntario_id": related["voluntario_id"],
        "fecha": date.today().isoformat(),
        "descripcion": "Terapia de prueba",
    }
    create_sql, create_p = q.build_create_terapia(params)
    ephemeral_postgres.execute(create_sql, create_p)

    list_sql, list_p = q.build_list_terapias(animal_id=related["animal_id"])
    rows = ephemeral_postgres.execute(list_sql, list_p)

    assert len(rows) >= 1
    assert all(r["animal_id"] == related["animal_id"] for r in rows)


@pytest.mark.integration
def test_build_get_terapia(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_get_terapia returns the terapia by id."""
    related = _seed_terapia_related_records(ephemeral_postgres)

    params = {
        "animal_id": related["animal_id"],
        "voluntario_id": related["voluntario_id"],
        "fecha": date.today().isoformat(),
        "descripcion": "Consulta de control",
    }
    create_sql, create_p = q.build_create_terapia(params)
    created = ephemeral_postgres.execute(create_sql, create_p)
    terapia_id = created[0]["id"]

    get_sql, get_p = q.build_get_terapia(terapia_id)
    rows = ephemeral_postgres.execute(get_sql, get_p)

    assert len(rows) == 1
    assert rows[0]["id"] == terapia_id


@pytest.mark.integration
def test_build_update_terapia(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_update_terapia updates and returns the modified row."""
    related = _seed_terapia_related_records(ephemeral_postgres)

    create_params = {
        "animal_id": related["animal_id"],
        "voluntario_id": related["voluntario_id"],
        "fecha": date.today().isoformat(),
        "descripcion": "Original",
    }
    create_sql, create_p = q.build_create_terapia(create_params)
    created = ephemeral_postgres.execute(create_sql, create_p)
    terapia_id = created[0]["id"]

    update_params = {
        "animal_id": related["animal_id"],
        "voluntario_id": related["voluntario_id"],
        "fecha": date.today().isoformat(),
        "descripcion": "Actualizada",
    }
    update_sql, update_p = q.build_update_terapia(terapia_id, update_params)
    rows = ephemeral_postgres.execute(update_sql, update_p)

    assert len(rows) == 1
    assert rows[0]["descripcion"] == "Actualizada"


@pytest.mark.integration
def test_build_delete_terapia(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_delete_terapia soft-deletes the terapia."""
    related = _seed_terapia_related_records(ephemeral_postgres)

    create_params = {
        "animal_id": related["animal_id"],
        "voluntario_id": related["voluntario_id"],
        "fecha": date.today().isoformat(),
        "descripcion": "Para eliminar",
    }
    create_sql, create_p = q.build_create_terapia(create_params)
    created = ephemeral_postgres.execute(create_sql, create_p)
    terapia_id = created[0]["id"]

    del_sql, del_p = q.build_delete_terapia(terapia_id)
    rows = ephemeral_postgres.execute(del_sql, del_p)

    assert len(rows) == 1
    assert rows[0]["id"] == terapia_id

    # Verify it's soft-deleted
    get_sql, get_p = q.build_get_terapia(terapia_id)
    get_rows = ephemeral_postgres.execute(get_sql, get_p)
    assert get_rows[0]["activo"] is False


@pytest.mark.integration
def test_build_delete_terapia_blocks_active_recomendaciones(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """build_delete_terapia returns 0 rows when active recomendaciones exist."""
    related = _seed_terapia_related_records(ephemeral_postgres)

    create_params = {
        "animal_id": related["animal_id"],
        "voluntario_id": related["voluntario_id"],
        "fecha": date.today().isoformat(),
        "descripcion": "Con recomendación",
    }
    create_sql, create_p = q.build_create_terapia(create_params)
    created = ephemeral_postgres.execute(create_sql, create_p)
    terapia_id = created[0]["id"]

    # Add an active incomplete recomendacion
    rec_params = {
        "terapia_id": terapia_id,
        "fecha": date.today().isoformat(),
        "texto": "Reposo 48h",
    }
    rec_sql, rec_p = q.build_create_recomendacion(rec_params)
    ephemeral_postgres.execute(rec_sql, rec_p)

    del_sql, del_p = q.build_delete_terapia(terapia_id)
    rows = ephemeral_postgres.execute(del_sql, del_p)

    # Should be blocked
    assert len(rows) == 0


@pytest.mark.integration
def test_build_check_terapia_exists(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_check_terapia_exists returns the id if the terapia is active."""
    related = _seed_terapia_related_records(ephemeral_postgres)

    create_params = {
        "animal_id": related["animal_id"],
        "voluntario_id": related["voluntario_id"],
        "fecha": date.today().isoformat(),
        "descripcion": "Check exists",
    }
    create_sql, create_p = q.build_create_terapia(create_params)
    created = ephemeral_postgres.execute(create_sql, create_p)
    terapia_id = created[0]["id"]

    check_sql, check_p = q.build_check_terapia_exists(terapia_id)
    rows = ephemeral_postgres.execute(check_sql, check_p)

    assert len(rows) == 1
    assert rows[0]["id"] == terapia_id


@pytest.mark.integration
def test_build_check_terapia_exists_returns_nothing_for_deleted(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """build_check_terapia_exists returns 0 rows for a soft-deleted terapia."""
    related = _seed_terapia_related_records(ephemeral_postgres)

    create_params = {
        "animal_id": related["animal_id"],
        "voluntario_id": related["voluntario_id"],
        "fecha": date.today().isoformat(),
        "descripcion": "Will be deleted",
    }
    create_sql, create_p = q.build_create_terapia(create_params)
    created = ephemeral_postgres.execute(create_sql, create_p)
    terapia_id = created[0]["id"]

    del_sql, del_p = q.build_delete_terapia(terapia_id)
    ephemeral_postgres.execute(del_sql, del_p)

    check_sql, check_p = q.build_check_terapia_exists(terapia_id)
    rows = ephemeral_postgres.execute(check_sql, check_p)

    assert len(rows) == 0


@pytest.mark.integration
def test_build_create_recomendacion(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_create_recomendacion inserts and returns the row."""
    related = _seed_terapia_related_records(ephemeral_postgres)

    terapia_params = {
        "animal_id": related["animal_id"],
        "voluntario_id": related["voluntario_id"],
        "fecha": date.today().isoformat(),
        "descripcion": "Terapia con recomendación",
    }
    terapia_sql, terapia_p = q.build_create_terapia(terapia_params)
    created_terapia = ephemeral_postgres.execute(terapia_sql, terapia_p)
    terapia_id = created_terapia[0]["id"]

    rec_params = {
        "terapia_id": terapia_id,
        "fecha": date.today().isoformat(),
        "texto": "Reposo 48h",
    }
    rec_sql, rec_p = q.build_create_recomendacion(rec_params)
    rows = ephemeral_postgres.execute(rec_sql, rec_p)

    assert len(rows) == 1
    assert rows[0]["terapia_id"] == terapia_id
    assert rows[0]["texto"] == "Reposo 48h"
    assert rows[0]["completada"] is False
    assert rows[0]["activo"] is True


@pytest.mark.integration
def test_build_list_recomendaciones_by_terapia(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """build_list_recomendaciones_by_terapia returns all active recomendaciones."""
    related = _seed_terapia_related_records(ephemeral_postgres)

    terapia_params = {
        "animal_id": related["animal_id"],
        "voluntario_id": related["voluntario_id"],
        "fecha": date.today().isoformat(),
        "descripcion": "Terapia con lista",
    }
    terapia_sql, terapia_p = q.build_create_terapia(terapia_params)
    created_terapia = ephemeral_postgres.execute(terapia_sql, terapia_p)
    terapia_id = created_terapia[0]["id"]

    rec_params = {
        "terapia_id": terapia_id,
        "fecha": date.today().isoformat(),
        "texto": "Primera indicación",
    }
    rec_sql, rec_p = q.build_create_recomendacion(rec_params)
    ephemeral_postgres.execute(rec_sql, rec_p)

    list_sql, list_p = q.build_list_recomendaciones_by_terapia(terapia_id)
    rows = ephemeral_postgres.execute(list_sql, list_p)

    assert len(rows) >= 1
    assert all(r["terapia_id"] == terapia_id and r["activo"] is True for r in rows)


@pytest.mark.integration
def test_build_get_recomendacion(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_get_recomendacion returns the recomendacion by id."""
    related = _seed_terapia_related_records(ephemeral_postgres)

    terapia_params = {
        "animal_id": related["animal_id"],
        "voluntario_id": related["voluntario_id"],
        "fecha": date.today().isoformat(),
        "descripcion": "Terapia para get",
    }
    terapia_sql, terapia_p = q.build_create_terapia(terapia_params)
    created_terapia = ephemeral_postgres.execute(terapia_sql, terapia_p)
    terapia_id = created_terapia[0]["id"]

    rec_params = {
        "terapia_id": terapia_id,
        "fecha": date.today().isoformat(),
        "texto": "Indicación para get",
    }
    rec_sql, rec_p = q.build_create_recomendacion(rec_params)
    created_rec = ephemeral_postgres.execute(rec_sql, rec_p)
    rec_id = created_rec[0]["id"]

    get_sql, get_p = q.build_get_recomendacion(rec_id)
    rows = ephemeral_postgres.execute(get_sql, get_p)

    assert len(rows) == 1
    assert rows[0]["id"] == rec_id


@pytest.mark.integration
def test_build_complete_recomendacion(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_complete_recomendacion sets completada=True and returns the row."""
    related = _seed_terapia_related_records(ephemeral_postgres)

    terapia_params = {
        "animal_id": related["animal_id"],
        "voluntario_id": related["voluntario_id"],
        "fecha": date.today().isoformat(),
        "descripcion": "Terapia para complete",
    }
    terapia_sql, terapia_p = q.build_create_terapia(terapia_params)
    created_terapia = ephemeral_postgres.execute(terapia_sql, terapia_p)
    terapia_id = created_terapia[0]["id"]

    rec_params = {
        "terapia_id": terapia_id,
        "fecha": date.today().isoformat(),
        "texto": "Por completar",
    }
    rec_sql, rec_p = q.build_create_recomendacion(rec_params)
    created_rec = ephemeral_postgres.execute(rec_sql, rec_p)
    rec_id = created_rec[0]["id"]

    complete_sql, complete_p = q.build_complete_recomendacion(rec_id)
    rows = ephemeral_postgres.execute(complete_sql, complete_p)

    assert len(rows) == 1
    assert rows[0]["completada"] is True


@pytest.mark.integration
def test_build_delete_recomendacion(ephemeral_postgres: _EphemeralPostgres) -> None:
    """build_delete_recomendacion soft-deletes and returns the id."""
    related = _seed_terapia_related_records(ephemeral_postgres)

    terapia_params = {
        "animal_id": related["animal_id"],
        "voluntario_id": related["voluntario_id"],
        "fecha": date.today().isoformat(),
        "descripcion": "Terapia para delete",
    }
    terapia_sql, terapia_p = q.build_create_terapia(terapia_params)
    created_terapia = ephemeral_postgres.execute(terapia_sql, terapia_p)
    terapia_id = created_terapia[0]["id"]

    rec_params = {
        "terapia_id": terapia_id,
        "fecha": date.today().isoformat(),
        "texto": "Por eliminar",
    }
    rec_sql, rec_p = q.build_create_recomendacion(rec_params)
    created_rec = ephemeral_postgres.execute(rec_sql, rec_p)
    rec_id = created_rec[0]["id"]

    del_sql, del_p = q.build_delete_recomendacion(rec_id)
    rows = ephemeral_postgres.execute(del_sql, del_p)

    assert len(rows) == 1
    assert rows[0]["id"] == rec_id
