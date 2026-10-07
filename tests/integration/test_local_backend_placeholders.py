"""Integration tests for ``$N`` placeholder translation (issue #944, A-12).

``LocalPostgresExecutor`` used to rewrite every ``$N`` to ``%s`` by
position and pass the params unchanged. Any query that repeats or
reorders ``$N`` then either failed ("21 placeholders but 14 parameters")
or silently bound each value to the wrong column. These atoms run real
statements through the production executor against Postgres and assert
which row and which column changed.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.core.local_backend.db import LocalPostgresExecutor
from app.modules.adopciones import queries as adopciones_queries
from tests.integration.conftest import _EphemeralPostgres

pytestmark = pytest.mark.integration


def _executor(ep: _EphemeralPostgres) -> LocalPostgresExecutor:
    return LocalPostgresExecutor(ep.dsn, search_path=ep.schema)


def _seed_animal(ep: _EphemeralPostgres, nchip: str, nombre: str) -> str:
    animal_id = str(uuid4())
    ep.execute(
        "INSERT INTO animales (id, nchip, nombreanimal, especie, sexo, fnacimiento, fecha_alta, activo) "
        "VALUES (%s, %s, %s, 'CANINA', 'M', '2018-03-15', now(), true) RETURNING id",
        [animal_id, nchip, nombre],
    )
    return animal_id


def _nombre(ep: _EphemeralPostgres, animal_id: str) -> str:
    return ep.execute("SELECT nombreanimal FROM animales WHERE id = %s", [animal_id])[0][
        "nombreanimal"
    ]


def test_reordered_placeholders_update_the_right_row_and_column(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    ep = ephemeral_postgres
    target = _seed_animal(ep, "CHIP-944-A", "Antes")
    other = _seed_animal(ep, "CHIP-944-B", "Intacto")

    _executor(ep).execute_sql(
        "UPDATE animales SET nombreanimal = $2 WHERE id = $1", [target, "Despues"]
    )

    assert _nombre(ep, target) == "Despues"
    assert _nombre(ep, other) == "Intacto"


def test_repeated_placeholder_binds_the_same_value_twice(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    ep = ephemeral_postgres
    animal_id = _seed_animal(ep, "CHIP-944-C", "CHIP-944-C")

    rows = _executor(ep).execute_sql(
        "SELECT id FROM animales WHERE nchip = $1 AND nombreanimal = $1", ["CHIP-944-C"]
    )

    assert [str(r["id"]) for r in rows] == [animal_id]


def test_adopcion_production_insert_binds_values_to_their_columns(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """The real ``_INSERT_ADOPCION_SQL`` repeats ``$1``, ``$2``, ``$11`` and ``$14``.

    Runs the production statement directly (not ``create_adopcion``) so the
    assertion isolates placeholder translation from the lifecycle-event
    writes that follow the INSERT.
    """
    ep = ephemeral_postgres
    animal_id = _seed_animal(ep, "CHIP-944-D", "Bobby")
    sql, params = adopciones_queries.build_adopcion_insert(
        {
            "animal_id": animal_id,
            "fecha_adopcion": date.today().isoformat(),
            "nombre_adoptante": "Maria Lopez",
            "tipo_adopcion": "regular",
        }
    )

    rows = _executor(ep).execute_sql(sql, params)

    assert len(rows) == 1
    stored = ep.execute(
        "SELECT animal_id, nombre_adoptante, tipo_adopcion FROM adopciones WHERE id = %s",
        [rows[0]["id"]],
    )[0]
    assert str(stored["animal_id"]) == animal_id
    assert stored["nombre_adoptante"] == "Maria Lopez"
    assert stored["tipo_adopcion"] == "regular"
