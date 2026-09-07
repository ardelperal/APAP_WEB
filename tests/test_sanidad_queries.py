"""Builder-contract tests for ``app.modules.sanidad.queries``.

Per AGENTS.md §22, the SQL/service separation seam requires SQL strings
and parameter shaping to live in a dedicated ``queries.py`` per feature
module. The builder contract is the testable surface — these tests
prove the builder returns a well-formed ``(sql, params)`` tuple without
needing transport, LocalBackend, or HTTP.

The HEALTH-02 batch endpoint accepts an N-tuple of actucacion records
and commits them atomically. The CTE pattern is the same one used for
the single-record CRUD (HEALTH-01, #50) but generalised across N rows
through PostgreSQL's ``unnest()``. The CTE:

1. fans the N records into a virtual ``input_data`` rowset via
   ``unnest($1::text[], ..., $7::text[]) AS t(...)``;
2. joins against ``animales`` (FK + activo + fecha_alta per D-24 regla
   3), ``voluntarios`` (FK + activo per VOL-05), and
   ``catalogos_pruebas`` (FK existence);
3. classifies each row as valid OR surfaces a per-row error reason
   (mirrors HEALTH-01's disambiguation vocabulary);
4. computes an overall ``all_valid`` boolean via ``bool_and``;
5. inserts only when (a) every row is valid, (b) ``dry_run`` is false,
   evaluated as a single CTE statement so PostgreSQL rolls back the
   whole batch on any failure (CRITICAL: atomic commit).

The shape is asserted here so a typo in the SQL template fails FAST,
before the integration tests in ``test_sanidad_batch.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.sanidad import queries


def _records(n: int = 5) -> list[dict[str, Any]]:
    """Build N minimal valid records for the builder."""
    return [
        {
            "animal_id": f"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa{i}",
            "voluntario_id": None,
            "fecha": "2026-07-04",
            "tipo_actuacion_id": None,
            "veterinario": f"Dr. {i}",
            "observaciones": f"Vacuna #{i}",
            "material_utilizado": None,
        }
        for i in range(n)
    ]


# --- builder happy path ---------------------------------------------------


def test_build_batch_insert_returns_atomic_cte_with_unnest() -> None:
    """The SQL is a single CTE that fans records through ``unnest``.

    The atomicity guarantee comes from running every check + the INSERT
    inside the SAME PostgreSQL statement — the statement snapshot is what
    closes the TOCTOU window between the FK lookups and the writes. A
    half-batch (some rows inserted, others not) is structurally
    impossible: ``bool_and(is_valid)`` gates the INSERT through a
    ``WHERE all_valid.ok = true`` filter, so either every valid row
    goes in or none do.
    """
    sql, params = queries.build_batch_insert(_records(5), dry_run=False)

    assert "WITH input_data AS" in sql
    assert "unnest(" in sql
    assert "$1::text[]" in sql
    assert "$2::text[]" in sql
    assert "$3::date[]" in sql
    assert "$7::text[]" in sql
    # The atomic INSERT gate.
    assert "INSERT INTO actuacion_sanitaria" in sql
    assert "bool_and" in sql
    assert "RETURNING" in sql
    # dry_run flag is the 8th positional param.
    assert "$8::boolean" in sql


def test_build_batch_insert_params_are_seven_parallel_arrays() -> None:
    """Params are 7 lists of N values + 1 dry_run boolean.

    Per the CTE contract, each param position corresponds to one column
    of the batch — order matters. ``dry_run`` is the 8th positional so
    the service can flip it without rebuilding the arrays.
    """
    records = _records(5)
    sql, params = queries.build_batch_insert(records, dry_run=False)

    assert len(params) == 8
    assert params[7] is False  # dry_run = false → real insert
    # Each positional param 0..6 is a list of length N == 5.
    for i in range(7):
        assert isinstance(params[i], list), (
            f"param {i} should be a list (column-array), got {type(params[i])}"
        )
        assert len(params[i]) == 5, (
            f"param {i} should have N=5 elements, got {len(params[i])}"
        )
    # Cross-check: animal_id column has the right values.
    assert params[0] == [r["animal_id"] for r in records]
    # Cross-check: fecha column has the right values.
    assert params[2] == [r["fecha"] for r in records]
    # None values flow through verbatim (the CTE handles nulls).
    assert all(params[1][i] is None for i in range(5)), (
        "voluntario_id column should carry the None values through"
    )


def test_build_batch_insert_dry_run_true_sets_param_eight() -> None:
    """``dry_run=True`` short-circuits the INSERT via $8::boolean = false."""
    _sql, params = queries.build_batch_insert(_records(3), dry_run=True)

    assert params[7] is True


# --- builder raises when input is wrong ----------------------------------


def test_build_batch_insert_rejects_empty_records() -> None:
    """An empty batch fails fast at the builder, not at INSERT time.

    The route layer already 422s on empty input, but the builder must
    refuse to build an empty CTE so a misguided caller can't trick the
    DB into ``unnest(ARRAY[]::text[], ARRAY[]::text[]) = 0 rows`` and
    silently succeed.
    """
    with pytest.raises(ValueError, match="(?i)at least one"):
        queries.build_batch_insert([], dry_run=False)


def test_build_batch_insert_rejects_non_dict_records() -> None:
    """Each record must be a dict so the column unpacking is unambiguous.

    The previous signature (positional tuples) was tempting because
    the INSERT order is fixed, but a dict form is what keeps the
    service contract close to ``create_actuacion_sanitaria`` (which
    already accepts a ``dict[str, Any]``) and avoids silent column
    reordering bugs from refactors.
    """
    records: list[dict[str, Any] | tuple[str, str]] = [
        ("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "2026-07-04"),
    ]
    with pytest.raises((ValueError, TypeError)):
        queries.build_batch_insert(records, dry_run=False)  # type: ignore[arg-type]  # noqa: E501


# --- CTE shape -----------------------------------------------------------


def test_build_batch_insert_cte_joins_all_fk_tables() -> None:
    """The CTE joins animales + voluntarios + catalogos_pruebas.

    Without all three joins the predicate cannot honour D-24 regla 3
    AND the FK active check AND the catalog existence — any of those
    silently absent would return a partially-checked batch.
    """
    sql, _params = queries.build_batch_insert(_records(2), dry_run=False)

    assert "JOIN checked_animals ca" in sql
    assert "JOIN checked_voluntarios cv" in sql
    assert "JOIN checked_tipos ct" in sql


def test_build_batch_insert_cte_indexes_each_record() -> None:
    """``ROW_NUMBER() OVER () - 1`` produces a 0-indexed batch_index.

    The downstream preview response uses ``batch_index`` to address a
    specific record back to the operator (the form's row N). Zero-based
    is the convention because the form template renders records starting
    at index 0.
    """
    sql, _params = queries.build_batch_insert(_records(2), dry_run=False)

    assert "ROW_NUMBER() OVER () - 1 AS batch_index" in sql


def test_build_batch_insert_returns_unioned_inserted_and_failed_rows() -> None:
    """The CTE main query unions ``inserted`` + ``validation_error``.

    The service walks the result set: rows with ``kind='inserted'`` go
    to the success list, rows with ``kind='validation_error'`` go to
    the error list. The ``all_valid`` boolean is computed inside the
    CTE so the service does not need a second round trip to know
    whether to commit or to raise ``BatchValidationError``.
    """
    sql, _params = queries.build_batch_insert(_records(2), dry_run=False)

    assert "'inserted'::text" in sql
    assert "'validation_error'::text" in sql
    assert "UNION ALL" in sql
    assert "ORDER BY kind, batch_index" in sql


def test_build_batch_insert_preserves_per_record_reason_vocabulary() -> None:
    """The reason code vocabulary mirrors HEALTH-01's disambiguation.

    The same Spanish strings used by ``sanidad/service.py`` for
    single-record failures must surface verbatim here so the route
    layer formats them consistently. Mirroring the vocabulary (rather
    than introducing new tokens) keeps the operator-facing error
    copy uniform.
    """
    sql, _params = queries.build_batch_insert(_records(2), dry_run=False)

    assert "animal_no_activo" in sql
    assert "fecha_anterior_alta" in sql
    assert "voluntario_inactivo" in sql
    assert "tipo_prueba_inexistente" in sql
