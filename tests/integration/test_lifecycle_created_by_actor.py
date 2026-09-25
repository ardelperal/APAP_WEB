"""Integration tests: lifecycle events record the acting user (issue #945, A-13).

``animal_lifecycle_events.created_by`` is ``UUID NOT NULL``. Four flows
passed a text label (``"adopciones.create_adopcion"``, …) instead, so the
event INSERT always failed against real Postgres. Decision (maintainer,
option a): ``created_by`` is the acting user's UUID, and a call without an
actor is rejected before any write.

This module covers the adopciones flows (#945, part 1/2: create_adopcion,
update_adopcion). The acogidas flows (create_acogida, close_acogida) are
covered by #945 part 2/2, added to this same file.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.core.local_backend.db import LocalPostgresExecutor
from app.modules.adopciones import service as adopciones_service
from app.modules.animals import ActorRequiredError
from tests.integration.conftest import _EphemeralPostgres

pytestmark = pytest.mark.integration

ACTOR = str(uuid4())


def _executor(ep: _EphemeralPostgres) -> LocalPostgresExecutor:
    return LocalPostgresExecutor(ep.dsn, search_path=ep.schema)


def _seed_animal(ep: _EphemeralPostgres) -> str:
    animal_id = str(uuid4())
    ep.execute(
        "INSERT INTO animales (id, nchip, nombreanimal, especie, sexo, fnacimiento, fecha_alta, activo) "
        "VALUES (%s, %s, 'Luna', 'CANINA', 'H', '2019-06-01', now(), true) RETURNING id",
        [animal_id, f"CHIP-945-{animal_id[:8]}"],
    )
    return animal_id


def _event_creators(ep: _EphemeralPostgres, animal_id: str, event_type: str) -> list[str]:
    rows = ep.execute(
        "SELECT created_by FROM animal_lifecycle_events WHERE animal_id = %s AND event_type = %s",
        [animal_id, event_type],
    )
    return [str(r["created_by"]) for r in rows]


def _count(ep: _EphemeralPostgres, table: str, animal_id: str) -> int:
    return ep.execute(f"SELECT count(*) AS n FROM {table} WHERE animal_id = %s", [animal_id])[0][
        "n"
    ]


def _adopcion_params(animal_id: str) -> dict[str, str]:
    return {
        "animal_id": animal_id,
        "fecha_adopcion": date.today().isoformat(),
        "nombre_adoptante": "Maria Lopez",
        "tipo_adopcion": "regular",
    }


def test_create_adopcion_records_its_event_with_the_actor(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    ep = ephemeral_postgres
    animal_id = _seed_animal(ep)

    adopciones_service.create_adopcion(
        _executor(ep), _adopcion_params(animal_id), actor_user_id=ACTOR
    )

    assert _event_creators(ep, animal_id, "ADOPTION_STARTED") == [ACTOR]


def test_create_adopcion_without_actor_is_rejected_before_any_write(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    ep = ephemeral_postgres
    animal_id = _seed_animal(ep)

    with pytest.raises(ActorRequiredError):
        adopciones_service.create_adopcion(_executor(ep), _adopcion_params(animal_id))

    assert _count(ep, "adopciones", animal_id) == 0


def test_update_adopcion_return_records_its_event_with_the_actor(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    ep = ephemeral_postgres
    animal_id = _seed_animal(ep)
    executor = _executor(ep)
    adopcion = adopciones_service.create_adopcion(
        executor, _adopcion_params(animal_id), actor_user_id=ACTOR
    )

    adopciones_service.update_adopcion(
        executor,
        adopcion.id,
        {**_adopcion_params(animal_id), "fecha_devolucion": date.today().isoformat()},
        actor_user_id=ACTOR,
    )

    assert _event_creators(ep, animal_id, "ADOPTION_RETURNED") == [ACTOR]
