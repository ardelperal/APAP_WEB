"""Builder-contract tests for ``app.modules.materiales.queries``.

Per AGENTS.md §22, the SQL/service separation seam requires SQL strings
and parameter shaping to live in a dedicated ``queries.py`` per feature
module. The builder contract is the testable surface — these tests
prove the builders return well-formed ``(sql, params)`` tuples without
needing transport, InsForge, or HTTP.

The seam is symmetric with the existing tests in ``test_materiales.py``
(captured SQL strings from the httpx mock client). The tests here
exercise the builders directly so a typo in the SQL template fails
FAST, before the integration tests fail more opaquely.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.materiales import queries

# --- catalog insert ------------------------------------------------------


def test_build_material_insert_returns_insert_sql_and_ordered_params() -> None:
    sql, params = queries.build_material_insert(
        {
            "material": "Cama",
            "tamano": "Grande",
            "color": "Azul",
            "observaciones": "Para gato grande",
        }
    )

    assert "INSERT INTO materiales" in sql
    assert "VALUES ($1, $2, $3, $4)" in sql
    # Required-text fields are the first 3 params, observaciones last.
    assert params == ["Cama", "Grande", "Azul", "Para gato grande"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("material", ""),
        ("material", "   "),
        ("material", None),
        ("tamano", ""),
        ("tamano", "   "),
        ("color", ""),
        ("color", None),
    ],
)
def test_build_material_insert_rejects_blank_required_field(
    field: str, value: Any
) -> None:
    """Builders raise ValueError on blank required text BEFORE returning.

    Mirrors the contract that ``_build_material_write_params`` had in
    ``service.py`` — the rejection must happen at the SQL-build step,
    not after the INSERT runs (otherwise the operator would see a
    silent rejection deep in the data layer).
    """
    base = {
        "material": "Cama",
        "tamano": "Grande",
        "color": "Azul",
        "observaciones": "X",
    }
    base[field] = value
    with pytest.raises(ValueError, match=field):
        queries.build_material_insert(base)


def test_build_material_insert_uses_spanish_error_template() -> None:
    """The required-text rejection message is in Spanish.

    The route layer wraps the rejection in
    ``f"No se pudo guardar el material: {exc}"``; the operator must
    see the friendly Spanish wording
    (``material es obligatorio y no puede estar vacio``), not the
    default English template from ``app.core.forms``. This test
    locks the partial-wrapping in queries.py so a future refactor
    cannot regress the UX without flagging it.
    """
    with pytest.raises(
        ValueError, match=r"material es obligatorio y no puede estar vacio"
    ):
        queries.build_material_insert(
            {"material": "", "tamano": "G", "color": "Azul", "observaciones": None}
        )


def test_build_material_insert_normalizes_blank_observaciones_to_none() -> None:
    sql, params = queries.build_material_insert(
        {
            "material": "Cama",
            "tamano": "Grande",
            "color": "Azul",
            "observaciones": "",
        }
    )
    assert "INSERT INTO materiales" in sql
    # Blank optional observation collapses to None (NULL in the DB).
    assert params[3] is None


# --- catalog get by id ---------------------------------------------------


def test_build_material_get_by_id_uses_id_placeholder() -> None:
    sql, params = queries.build_material_get_by_id("mat-uuid-1")
    assert "FROM materiales" in sql
    assert "WHERE id = $1" in sql
    assert params == ["mat-uuid-1"]


# --- catalog list --------------------------------------------------------


def test_build_material_list_activos_solo_filters_active() -> None:
    sql, params = queries.build_material_list(activos_solo=True)
    assert "FROM materiales" in sql
    assert "WHERE activo = true" in sql
    assert "ORDER BY fecha_alta DESC" in sql
    assert params == []


def test_build_material_list_all_rows_omits_active_filter() -> None:
    sql, params = queries.build_material_list(activos_solo=False)
    assert "FROM materiales" in sql
    assert "ORDER BY fecha_alta DESC" in sql
    assert "WHERE activo = true" not in sql
    assert params == []


# --- catalog update ------------------------------------------------------


def test_build_material_update_emits_dynamic_set_clause() -> None:
    sql, params = queries.build_material_update(
        "mat-uuid-1",
        {"material": "Cama XL", "tamano": "Extra Grande"},
    )

    assert "UPDATE materiales SET" in sql
    assert "updated_at = now()" in sql
    assert "WHERE id = $1" in sql
    # Both fields in the SET clause — the partial update picks the
    # columns actually present in the params dict.
    assert "material = $2" in sql
    assert "tamano = $3" in sql
    # The builder returns ONLY the SET values in declaration order;
    # the service prepends the id (the WHERE clause value) before
    # calling the executor. This mirrors the previous
    # ``_build_material_update_sql`` contract so the captured-SQL
    # integration tests keep asserting the same shape.
    assert params == ["Cama XL", "Extra Grande"]


def test_build_material_update_raises_when_no_writable_fields() -> None:
    """An update with no writable fields is a no-op and must raise."""
    with pytest.raises(ValueError, match="writable"):
        queries.build_material_update("mat-uuid-1", {})


def test_build_material_update_normalizes_blank_optional_to_none() -> None:
    sql, params = queries.build_material_update(
        "mat-uuid-1",
        {"observaciones": "   "},
    )
    assert "observaciones = $2" in sql
    # Blank optional collapses to None (NULL in the DB).
    # Builder returns ONLY the SET values, so the collapse is at index 0.
    assert params[0] is None


# --- catalog deactivate + cascade ----------------------------------------


def test_build_material_deactivate_flips_activo_and_bumps_fecha_baja() -> None:
    sql, params = queries.build_material_deactivate("mat-uuid-1")
    assert "UPDATE materiales" in sql
    assert "activo = false" in sql
    assert "fecha_baja = now()" in sql
    assert "WHERE id = $1" in sql
    assert "RETURNING id" in sql
    assert params == ["mat-uuid-1"]


def test_build_material_cascade_deactivate_targets_material_id() -> None:
    sql, params = queries.build_material_cascade_deactivate("mat-uuid-1")
    assert "UPDATE estancia_materiales" in sql
    assert "activo = false" in sql
    assert "WHERE material_id = $1" in sql
    assert "activo = true" in sql
    assert params == ["mat-uuid-1"]


# --- FK checks -----------------------------------------------------------


def test_build_material_active_returns_select_for_material_id() -> None:
    sql, params = queries.build_material_active("mat-uuid-1")
    assert "FROM materiales" in sql
    assert "WHERE id = $1" in sql
    assert params == ["mat-uuid-1"]


def test_build_estancia_active_returns_select_for_estancia_id() -> None:
    sql, params = queries.build_estancia_active("est-uuid-1")
    assert "FROM acogidas" in sql
    assert "WHERE id = $1" in sql
    assert params == ["est-uuid-1"]


# --- junction insert -----------------------------------------------------


def test_build_junction_insert_orders_params_for_write_columns() -> None:
    sql, params = queries.build_junction_insert(
        estancia_id="est-uuid-1",
        material_id="mat-uuid-1",
        cantidad=2,
        notas="Para el gato nuevo",
    )
    assert "INSERT INTO estancia_materiales" in sql
    # Order matches _JUNCTION_WRITE_COLUMNS (estancia_id, material_id,
    # cantidad, notas).
    assert params == ["est-uuid-1", "mat-uuid-1", 2, "Para el gato nuevo"]


@pytest.mark.parametrize(
    "cantidad",
    [0, -1, -100],
)
def test_build_junction_insert_rejects_non_positive_cantidad(cantidad: int) -> None:
    """Cantidad must be int > 0; off-spec calls raise ValueError."""
    with pytest.raises(ValueError, match="cantidad"):
        queries.build_junction_insert(
            estancia_id="est-uuid-1",
            material_id="mat-uuid-1",
            cantidad=cantidad,
            notas=None,
        )


def test_build_junction_insert_rejects_bool_cantidad() -> None:
    """Python ``bool`` is an ``int`` subclass — rejection must be explicit."""
    with pytest.raises(ValueError, match="cantidad"):
        queries.build_junction_insert(
            estancia_id="est-uuid-1",
            material_id="mat-uuid-1",
            cantidad=True,
            notas=None,
        )


# --- junction list -------------------------------------------------------


def test_build_junction_list_for_estancia_activos_solo_filters_active() -> None:
    sql, params = queries.build_junction_list_for_estancia(
        "est-uuid-1", activos_solo=True
    )
    assert "FROM estancia_materiales" in sql
    assert "WHERE estancia_id = $1" in sql
    assert "activo = true" in sql
    assert "ORDER BY fecha_alta DESC" in sql
    assert params == ["est-uuid-1"]


def test_build_junction_list_for_estancia_all_omits_active_filter() -> None:
    sql, params = queries.build_junction_list_for_estancia(
        "est-uuid-1", activos_solo=False
    )
    assert "FROM estancia_materiales" in sql
    assert "WHERE estancia_id = $1" in sql
    assert "ORDER BY fecha_alta DESC" in sql
    assert "activo = true" not in sql
    assert params == ["est-uuid-1"]


# --- junction deactivate -------------------------------------------------


def test_build_junction_deactivate_flips_activo_for_id() -> None:
    sql, params = queries.build_junction_deactivate("jun-uuid-1")
    assert "UPDATE estancia_materiales" in sql
    assert "activo = false" in sql
    assert "WHERE id = $1" in sql
    assert "activo = true" in sql
    assert params == ["jun-uuid-1"]
