"""Builder-contract tests for ``app.modules.acogidas.queries``.

Per AGENTS.md §22, the SQL/service separation seam requires SQL strings
and parameter shaping to live in a dedicated ``queries.py`` per feature
module. The builder contract is the testable surface — these tests
prove the builders return well-formed ``(sql, params)`` tuples without
needing transport, LocalBackend, or HTTP.

The seam is symmetric with the existing tests in ``test_acogidas.py``
(captured SQL strings from the httpx mock client). The tests here
exercise the builders directly so a typo in the SQL template fails
FAST, before the integration tests fail more opaquely.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.acogidas import queries

# --- catalog insert ------------------------------------------------------


def test_build_acogida_insert_returns_insert_sql_and_ordered_params() -> None:
    """Happy path: required + optional fields flow into the INSERT in
    declaration order matching ``ACOGIDA_WRITE_COLUMNS``."""
    sql, params = queries.build_acogida_insert(
        {
            "animal_id": "11111111-1111-1111-1111-111111111111",
            "casa_acogida_id": None,
            "voluntario_acogida_id": None,
            "voluntario_seguimiento1_id": None,
            "voluntario_seguimiento2_id": None,
            "voluntario_sanitario_id": None,
            "fecha_inicio": "2026-07-04",
            "fecha_final": None,
            "entrada_origen_id": None,
            "direccion": "Calle Mayor 12",
            "telefono": "600123456",
            "observaciones": "Animal tranquilo",
        }
    )

    assert "INSERT INTO acogidas" in sql
    assert "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)" in sql
    assert "RETURNING" in sql
    # Required fields are the first 2 params in declaration order.
    assert params[0] == "11111111-1111-1111-1111-111111111111"
    assert params[6] == "2026-07-04"
    # Optional FK + text fields collapse to None when blank/missing.
    assert params[1] is None  # casa_acogida_id
    assert params[8] is None  # entrada_origen_id
    # Free-text columns carry the operator's value through.
    assert params[9] == "Calle Mayor 12"  # direccion
    assert params[10] == "600123456"  # telefono
    assert params[11] == "Animal tranquilo"  # observaciones


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("animal_id", ""),
        ("animal_id", "   "),
        ("animal_id", None),
        ("fecha_inicio", ""),
        ("fecha_inicio", None),
    ],
)
def test_build_acogida_insert_rejects_blank_required_field(
    field: str, value: Any
) -> None:
    """Builders raise ValueError on blank required text BEFORE returning.

    Mirrors the contract that ``_build_write_params`` had in
    ``service.py`` — the rejection must happen at the SQL-build step,
    not after the INSERT runs (otherwise the operator would see a
    silent rejection deep in the data layer).
    """
    base = {
        "animal_id": "11111111-1111-1111-1111-111111111111",
        "casa_acogida_id": None,
        "voluntario_acogida_id": None,
        "voluntario_seguimiento1_id": None,
        "voluntario_seguimiento2_id": None,
        "voluntario_sanitario_id": None,
        "fecha_inicio": "2026-07-04",
        "fecha_final": None,
        "entrada_origen_id": None,
        "direccion": "Calle Mayor 12",
        "telefono": "600123456",
        "observaciones": "Animal tranquilo",
    }
    base[field] = value
    with pytest.raises(ValueError, match=field):
        queries.build_acogida_insert(base)


def test_build_acogida_insert_uses_spanish_error_template() -> None:
    """The required-text rejection message is in Spanish.

    The route layer formats the rejection with the operator-facing
    Spanish message; the rejection must surface
    ``animal_id es obligatorio y no puede estar vacio`` (not the
    default English ``app.core.forms`` template). This test locks the
    partial-wrapping in queries.py so a future refactor cannot regress
    the UX without flagging it.
    """
    base = {
        "animal_id": "",
        "casa_acogida_id": None,
        "voluntario_acogida_id": None,
        "voluntario_seguimiento1_id": None,
        "voluntario_seguimiento2_id": None,
        "voluntario_sanitario_id": None,
        "fecha_inicio": "2026-07-04",
        "fecha_final": None,
        "entrada_origen_id": None,
        "direccion": "Calle Mayor 12",
        "telefono": "600123456",
        "observaciones": "Animal tranquilo",
    }
    with pytest.raises(
        ValueError,
        match=r"animal_id es obligatorio y no puede estar vacio",
    ):
        queries.build_acogida_insert(base)


def test_build_acogida_insert_normalizes_blank_optional_to_none() -> None:
    """Blank optional UUID fields collapse to None (NULL in the DB)."""
    sql, params = queries.build_acogida_insert(
        {
            "animal_id": "11111111-1111-1111-1111-111111111111",
            "casa_acogida_id": "   ",
            "voluntario_acogida_id": None,
            "voluntario_seguimiento1_id": None,
            "voluntario_seguimiento2_id": None,
            "voluntario_sanitario_id": None,
            "fecha_inicio": "2026-07-04",
            "fecha_final": None,
            "entrada_origen_id": None,
            "direccion": "  ",
            "telefono": None,
            "observaciones": "",
        }
    )
    assert "INSERT INTO acogidas" in sql
    # Blank optional collapses to None (NULL in the DB).
    assert params[1] is None  # casa_acogida_id
    assert params[9] is None  # direccion
    assert params[11] is None  # observaciones


# --- catalog get by id ---------------------------------------------------


def test_build_acogida_get_by_id_uses_id_placeholder() -> None:
    sql, params = queries.build_acogida_get_by_id("acog-uuid-1")
    assert "FROM acogidas" in sql
    assert "WHERE id = $1" in sql
    assert params == ["acog-uuid-1"]


# --- catalog list -------------------------------------------------------


def test_build_acogida_list_all_omits_active_filter() -> None:
    sql, params = queries.build_acogida_list(activas_solo=False)
    assert "FROM acogidas" in sql
    assert "ORDER BY fecha_inicio DESC" in sql
    assert "WHERE fecha_final IS NULL" not in sql
    assert params == []


def test_build_acogida_list_activas_solo_filters_open_stays() -> None:
    sql, params = queries.build_acogida_list(activas_solo=True)
    assert "FROM acogidas" in sql
    assert "WHERE fecha_final IS NULL" in sql
    assert "ORDER BY fecha_inicio DESC" in sql
    assert params == []


# --- catalog update -----------------------------------------------------


def test_build_acogida_update_emits_dynamic_set_clause() -> None:
    """Partial-update builder picks the columns actually present in params.

    Mirrors the previous ``_build_update_sql_and_params`` contract from
    ``service.py`` — the SQL is rebuilt from the keys present in the
    params dict. The id is placed at $1 and the SET placeholders start
    at $2. The required fields (``animal_id``, ``fecha_inicio``) are
    always present in the form-scoped payload; ``fecha_final`` is the
    patch-only column.
    """
    sql, params = queries.build_acogida_update(
        "acog-uuid-1",
        {
            "animal_id": "11111111-1111-1111-1111-111111111111",
            "fecha_inicio": "2026-07-04",
            "direccion": "Calle Nueva 5",
        },
    )

    assert "UPDATE acogidas SET" in sql
    assert "updated_at = now()" in sql
    assert "WHERE id = $1" in sql
    assert "RETURNING" in sql
    # The present fields appear in the SET clause. Exact placeholder
    # indexes depend on the partial-set order; we assert the column
    # names appear, not the exact $N (the integration tests cover
    # that contract).
    assert "animal_id = $2" in sql
    assert "fecha_inicio = $8" in sql
    assert "direccion = $10" in sql
    # The builder returns the SET values in declaration order — one
    # value per SET column, even for columns not present in ``params``
    # (they collapse to None). The service prepends the id before
    # calling the executor. This mirrors the previous
    # ``_build_update_sql_and_params`` contract so the captured-SQL
    # integration tests keep asserting the same shape.
    # Declaration order: animal_id, casa_acogida_id, ...,
    # voluntario_sanitario_id, fecha_inicio, entrada_origen_id,
    # direccion, telefono, observaciones.
    assert params[0] == "11111111-1111-1111-1111-111111111111"  # animal_id
    assert params[6] == "2026-07-04"  # fecha_inicio
    assert params[8] == "Calle Nueva 5"  # direccion
    # The not-in-params columns collapse to None.
    assert params[1] is None  # casa_acogida_id
    assert params[9] is None  # telefono
    assert params[10] is None  # observaciones


def test_build_acogida_update_skips_omitted_fecha_final() -> None:
    """Issue #141: ``fecha_final`` follows the partial-update contract.

    When the key is absent from ``params``, the column is excluded from
    the SET clause so a previously closed stay stays closed. The form
    path always sends the field, so the live route is unaffected; the
    blank-key omission is for callers that want to leave the value
    untouched.
    """
    sql, params = queries.build_acogida_update(
        "acog-uuid-1",
        {
            "animal_id": "11111111-1111-1111-1111-111111111111",
            "fecha_inicio": "2026-07-04",
            "direccion": "Calle Nueva 5",
            # fecha_final deliberately omitted
        },
    )

    # fecha_final MUST NOT appear in the SET clause (it is in the
    # RETURNING list because the SELECT_COLUMNS mirror ends with
    # ``... updated_at, activo`` — so we check the SET clause is
    # silent on it by looking for ``fecha_final = $``).
    assert "fecha_final = $" not in sql
    # The three present fields flow through in declaration order.
    assert "animal_id = $2" in sql
    assert "fecha_inicio = $8" in sql
    assert "direccion = $10" in sql
    # Same params shape as the basic update — fecha_final was excluded
    # from the SET clause, not from the params list.
    assert params[0] == "11111111-1111-1111-1111-111111111111"
    assert params[6] == "2026-07-04"
    assert params[8] == "Calle Nueva 5"


def test_build_acogida_update_includes_present_fecha_final() -> None:
    """When the key is present (even empty string), fecha_final is in the SET.

    Empty string is normalized to NULL (reopen).
    """
    sql, params = queries.build_acogida_update(
        "acog-uuid-1",
        {
            "animal_id": "11111111-1111-1111-1111-111111111111",
            "fecha_inicio": "2026-07-04",
            "fecha_final": "",
        },
    )

    assert "fecha_final = $9" in sql
    assert params[7] is None  # empty string -> None


def test_build_acogida_update_rejects_blank_animal_id() -> None:
    """Required-text validation runs BEFORE the SQL is emitted."""
    with pytest.raises(ValueError, match=r"animal_id"):
        queries.build_acogida_update(
            "acog-uuid-1",
            {"animal_id": "", "fecha_inicio": "2026-07-04"},
        )


# --- catalog close ------------------------------------------------------


def test_build_acogida_close_sets_fecha_final_to_current_date() -> None:
    """Close is a lifecycle event: ``fecha_final = CURRENT_DATE``,
    ``activo`` stays true."""
    sql, params = queries.build_acogida_close("acog-uuid-1")
    assert "UPDATE acogidas" in sql
    assert "fecha_final = CURRENT_DATE" in sql
    assert "updated_at = now()" in sql
    assert "WHERE id = $1" in sql
    assert "RETURNING" in sql
    assert params == ["acog-uuid-1"]


# --- catalog delete -----------------------------------------------------


def test_build_acogida_delete_flips_activo_and_bumps_updated_at() -> None:
    """Soft-delete: ``activo = false`` + ``fecha_baja = now()`` +
    ``updated_at = now()``; the WHERE clause folds the existence check
    into the same statement under PostgreSQL's row lock. ``acogidas``
    has a ``fecha_baja`` column (audit-2026-07-30, VOL-04 follow-up)
    that captures when the row was soft-deleted.
    """
    sql, params = queries.build_acogida_delete("acog-uuid-1")
    assert "UPDATE acogidas" in sql
    assert "activo = false" in sql
    assert "fecha_baja = now()" in sql
    assert "updated_at = now()" in sql
    assert "WHERE id = $1" in sql
    assert "activo = true" in sql
    assert "RETURNING id" in sql
    assert params == ["acog-uuid-1"]


# --- FK checks ----------------------------------------------------------


def test_build_acogida_check_animal_returns_select_for_id() -> None:
    sql, params = queries.build_acogida_check_animal("animal-uuid-1")
    assert "FROM animales" in sql
    assert "WHERE id = $1" in sql
    assert params == ["animal-uuid-1"]


def test_build_acogida_check_casa_returns_select_for_id() -> None:
    sql, params = queries.build_acogida_check_casa("casa-uuid-1")
    assert "FROM casas_acogida" in sql
    assert "WHERE id = $1" in sql
    assert "activo = true" in sql
    assert params == ["casa-uuid-1"]


def test_build_acogida_check_voluntario_returns_select_for_id() -> None:
    sql, params = queries.build_acogida_check_voluntario("vol-uuid-1")
    assert "FROM voluntarios" in sql
    assert "WHERE id = $1" in sql
    assert "activo = true" in sql
    assert params == ["vol-uuid-1"]


def test_build_acogida_check_entrada_returns_select_for_id() -> None:
    """Entrada check has NO activo filter — legacy entries can be
    soft-deleted but the FK should still resolve."""
    sql, params = queries.build_acogida_check_entrada("entrada-uuid-1")
    assert "FROM entradas" in sql
    assert "WHERE id = $1" in sql
    assert "activo = true" not in sql
    assert params == ["entrada-uuid-1"]


# --- foster_capacity_overrides link ------------------------------------


def test_build_acogida_link_override_targets_override_id() -> None:
    """Issue #142: link the foster_capacity_overrides row to the new
    estancia after the INSERT succeeds. The WHERE clause includes
    ``casa_acogida_id`` + ``animal_id`` (defense against forged
    ``override_id`` from another operator's session — see
    judgment-day CRITICAL §1.2 + HIGH §3.2) and the
    ``AND estancia_id IS NULL`` guard prevents double-linking.
    """
    sql, params = queries.build_acogida_link_override(
        estancia_id="acog-uuid-1",
        override_id="override-uuid-1",
        casa_acogida_id="casa-uuid-1",
        animal_id="animal-uuid-1",
    )
    assert "UPDATE foster_capacity_overrides" in sql
    assert "estancia_id = $1" in sql
    assert "WHERE id = $2" in sql
    assert "AND casa_acogida_id = $3" in sql
    assert "AND animal_id = $4" in sql
    assert "AND estancia_id IS NULL" in sql
    assert params == [
        "acog-uuid-1",
        "override-uuid-1",
        "casa-uuid-1",
        "animal-uuid-1",
    ]


def test_build_acogida_link_override_accepts_null_casa_for_legacy_stays() -> None:
    """Legacy stays without a casa pass ``casa_acogida_id=None`` —
    the SQL filter uses ``casa_acogida_id = $3`` which is NULL/false
    in three-valued logic, so the link is rejected at the DB level
    (the override was recorded for a SPECIFIC casa, not NULL). The
    builder still has to emit the None parameter unchanged."""
    sql, params = queries.build_acogida_link_override(
        estancia_id="acog-uuid-1",
        override_id="override-uuid-1",
        casa_acogida_id=None,
        animal_id="animal-uuid-1",
    )
    assert "AND casa_acogida_id = $3" in sql
    assert params == [
        "acog-uuid-1",
        "override-uuid-1",
        None,
        "animal-uuid-1",
    ]
