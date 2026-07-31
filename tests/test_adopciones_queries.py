"""Golden contract tests for adopciones SQL query builders."""

from __future__ import annotations

import pytest

from app.modules.adopciones import queries

_FULL_PARAMS = {
    "animal_id": " animal-1 ",
    "voluntario_seguimiento_id": " vol-1 ",
    "fecha_adopcion": "2026-07-27",
    "fecha_devolucion": "",
    "donativo_preadopcion": "12.50",
    "donativo_adopcion": 25,
    "nombre_adoptante": " Ada ",
    "dni_adoptante": " DNI ",
    "telefono_adoptante": " 600 ",
    "email_adoptante": " ada@example.com ",
    "entrada_origen_id": " ent-1 ",
    "observaciones": " notes ",
    "tipo_adopcion": " judicial ",
    "responsable_adopcion_id": " resp-1 ",  # VOL-04 #37
}

_EXPECTED_WRITE_PARAMS = [
    "animal-1",
    "vol-1",
    "2026-07-27",
    None,
    12.5,
    25.0,
    "Ada",
    "DNI",
    "600",
    "ada@example.com",
    "ent-1",
    "notes",
    "judicial",
    "resp-1",  # responsable_adopcion_id (VOL-04 #37)
]


def test_build_adopcion_insert_exact_sql_and_params() -> None:
    sql, params = queries.build_adopcion_insert(_FULL_PARAMS)

    assert sql == queries._INSERT_ADOPCION_SQL
    assert params == _EXPECTED_WRITE_PARAMS


def test_build_adopcion_update_exact_sql_and_params() -> None:
    sql, params = queries.build_adopcion_update("adop-1", _FULL_PARAMS)

    assert sql == queries._UPDATE_ADOPCION_SQL
    assert params == ["adop-1", *_EXPECTED_WRITE_PARAMS]


@pytest.mark.parametrize(
    ("builder", "argument", "expected_sql", "expected_params"),
    [
        (
            queries.build_adopcion_get_by_id,
            "adop-1",
            queries._GET_ADOPCION_BY_ID_SQL,
            ["adop-1"],
        ),
        (
            queries.build_adopcion_delete,
            "adop-1",
            queries._DELETE_ADOPCION_SQL,
            ["adop-1"],
        ),
        (
            queries.build_adopcion_search,
            r"Ada\%",
            queries._LIST_ADOPCIONES_BY_ADOPTANTE_SQL,
            [r"Ada\%"],
        ),
        (
            queries.build_adopcion_check_animal,
            "animal-1",
            queries._CHECK_ANIMAL_SQL,
            ["animal-1"],
        ),
        (
            queries.build_adopcion_check_voluntario,
            "vol-1",
            queries._CHECK_VOLUNTARIO_SQL,
            ["vol-1"],
        ),
        (
            queries.build_adopcion_check_entrada,
            "ent-1",
            queries._CHECK_ENTRADA_SQL,
            ["ent-1"],
        ),
        (
            queries.build_adopcion_check_responsable,
            "vol-1",
            queries._CHECK_RESPONSABLE_SQL,
            ["vol-1"],
        ),
    ],
)
def test_single_argument_builders_exact_sql_and_params(
    builder: object,
    argument: str,
    expected_sql: str,
    expected_params: list[str],
) -> None:
    sql, params = builder(argument)  # type: ignore[operator]

    assert sql == expected_sql
    assert params == expected_params


def test_build_adopcion_list_exact_sql_and_params() -> None:
    assert queries.build_adopcion_list() == (queries._LIST_ADOPCIONES_SQL, [])


def test_write_builders_preserve_validation_and_defaults() -> None:
    sql, params = queries.build_adopcion_insert(
        {
            "animal_id": "animal-1",
            "fecha_adopcion": "2026-07-27",
            "nombre_adoptante": "Ada",
        }
    )

    assert sql == queries._INSERT_ADOPCION_SQL
    assert params == [
        "animal-1",   # 0  animal_id
        None,         # 1  voluntario_seguimiento_id
        "2026-07-27", # 2  fecha_adopcion
        None,         # 3  fecha_devolucion
        None,         # 4  donativo_preadopcion
        None,         # 5  donativo_adopcion
        "Ada",        # 6  nombre_adoptante
        None,         # 7  dni_adoptante
        None,         # 8  telefono_adoptante
        None,         # 9  email_adoptante
        None,         # 10 entrada_origen_id
        None,         # 11 observaciones
        "regular",    # 12 tipo_adopcion
        None,         # 13 responsable_adopcion_id (VOL-04 #37)
    ]


@pytest.mark.parametrize(
    "params",
    [
        {"fecha_adopcion": "2026-07-27", "nombre_adoptante": "Ada"},
        {"animal_id": "animal-1", "nombre_adoptante": "Ada"},
        {"animal_id": "animal-1", "fecha_adopcion": "2026-07-27"},
        {
            "animal_id": "animal-1",
            "fecha_adopcion": "2026-07-27",
            "nombre_adoptante": "Ada",
            "donativo_adopcion": True,
        },
    ],
)
def test_write_builders_preserve_validation_errors(params: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        queries.build_adopcion_insert(params)
