"""PostgreSQL contracts for the animals LocalBackend adapter."""

from __future__ import annotations

import pytest

from app.modules.animals.adapters.local_backend.animals_local_backend_queries import (
    get_animal_by_nchip_sql,
)
from app.modules.animals.adapters.local_backend.animals_local_backend_write_queries import (
    create_animal_sql,
    delete_animal_sql,
    update_animal_sql,
)
from tests.integration.conftest import _EphemeralPostgres

pytestmark = pytest.mark.integration


def test_animals_crud_maps_legacy_domain_names_to_lowercase_schema(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """Reads and writes preserve domain keys without mixed-case DB columns."""
    create_sql, create_params = create_animal_sql(
        nchip="CHIP-ADAPTER-001",
        nombre="Luna",
        especie="CANINA",
        sexo="H",
        fnacimiento="2020-01-02",
    )
    created = ephemeral_postgres.execute(create_sql, create_params)

    assert created[0]["NCHIP"] == "CHIP-ADAPTER-001"
    assert created[0]["NombreAnimal"] == "Luna"

    get_sql, get_params = get_animal_by_nchip_sql("CHIP-ADAPTER-001")
    fetched = ephemeral_postgres.execute(get_sql, get_params)
    assert fetched[0]["Especie"] == "CANINA"

    update = update_animal_sql(
        animal_id=str(created[0]["id"]),
        nombre="Luna II",
        especie=None,
        sexo=None,
        fnacimiento=None,
    )
    assert update is not None
    updated = ephemeral_postgres.execute(*update)
    assert updated[0]["NombreAnimal"] == "Luna II"

    delete_sql, delete_params = delete_animal_sql(str(created[0]["id"]))
    deleted = ephemeral_postgres.execute(delete_sql, delete_params)
    assert deleted[0]["activo"] is False
