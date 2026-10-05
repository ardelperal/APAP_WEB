"""Unit-pure tests for the contratos queries seam (issue #1109).

Classification (apap-testing-strategy Gate A): unit pure — the SQL
owner is exercised through a fake ``SqlExecutor`` that records calls
and returns canned rows, so the SQL shape, parameter order and row
mapping are pinned without standing up Postgres. Per AGENTS.md §11
``_row_to_record`` is a CRITICAL_HELPER and must stay at 100%
coverage from its own segment onward.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from app.core.data_access import BackendError
from app.modules.contratos.contratos_queries import (
    ContratoConflictError,
    ContratoInsertInput,
    entity_column,
    get_contrato_for_entity,
    insert_contrato,
)


class _FakeSqlExecutor:
    """Minimal ``SqlExecutor`` Protocol implementation (see
    tests/test_acogidas.py for the canonical pattern)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[object]]] = []
        self._responses: list[list[dict[str, object]]] = []
        self._handler: Callable[[str, list[object]], Any] | None = None
        self._error: BackendError | None = None

    def set_response(self, rows: list[dict[str, object]]) -> None:
        self._responses = [rows]

    def set_handler(self, handler: Callable[[str, list[object]], Any]) -> None:
        self._handler = handler

    def set_error(self, error: BackendError) -> None:
        self._error = error

    def execute_sql(self, query: str, params: list[object]) -> list[dict[str, object]]:
        self.calls.append((query, params))
        if self._error is not None:
            raise self._error
        if self._handler is not None:
            return self._handler(query, params)
        if self._responses:
            return self._responses.pop(0)
        return []


_ENTITY_ROW: dict[str, object] = {
    "id": "c1a7f0e2-0000-4000-8000-000000000001",
    "tipo_contrato_id": "b2b8e1f3-0000-4000-8000-000000000002",
    "numero_contrato": "ENT-0001",
    "fecha": "2026-10-04",
}


# --- entity_column ---------------------------------------------------------


@pytest.mark.parametrize(
    ("entity_type", "expected"),
    [
        ("entrada", "entrada_id"),
        ("adopcion", "adopcion_id"),
        ("acogida", "acogida_id"),
        ("cesion", "cesion_id"),
    ],
)
def test_entity_column_maps_every_fk_target(entity_type: str, expected: str) -> None:
    assert entity_column(entity_type) == expected


def test_entity_column_rejects_unknown_entity_type() -> None:
    with pytest.raises(ValueError, match="entity_type"):
        entity_column("voluntario")


# --- insert_contrato --------------------------------------------------------


def _handler_lookup_then_insert(
    lookup_row: dict[str, object],
    insert_rows: list[dict[str, object]],
    insert_error: BackendError | None = None,
) -> Callable[[str, list[object]], Any]:
    """Return a fake handler: SELECT resolves the tipo FK; INSERT either
    returns rows or raises ``insert_error``."""

    def handler(query: str, params: list[object]) -> Any:
        if "INSERT INTO contratos" in query:
            if insert_error is not None:
                raise insert_error
            return insert_rows
        return [lookup_row]

    return handler


def test_insert_contrato_pins_sql_shape_and_parameter_order() -> None:
    fake = _FakeSqlExecutor()
    lookup_row = {"id": "b2b8e1f3-0000-4000-8000-000000000002", "codigo": "Entrada"}
    fake.set_handler(
        _handler_lookup_then_insert(lookup_row, [dict(_ENTITY_ROW)])
    )
    insert = ContratoInsertInput(
        tipo="Entrada",
        entity_type="entrada",
        entity_id="11111111-1111-4111-8111-111111111111",
        numero_contrato="ENT-0001",
        fecha="2026-10-04",
    )
    record = insert_contrato(fake, insert=insert)
    assert len(fake.calls) == 2
    lookup_query, lookup_params = fake.calls[0]
    assert "catalogos_tipos_contrato" in lookup_query
    assert lookup_params == ["Entrada"]
    insert_query, insert_params = fake.calls[1]
    assert "INSERT INTO contratos" in insert_query
    assert "entrada_id" in insert_query
    assert "RETURNING id, tipo_contrato_id, numero_contrato, fecha" in insert_query
    assert insert_params == [
        "b2b8e1f3-0000-4000-8000-000000000002",
        "ENT-0001",
        "2026-10-04",
        "11111111-1111-4111-8111-111111111111",
    ]
    assert record.tipo_codigo == "Entrada"
    assert record.entity_type == "entrada"
    assert record.entity_id == "11111111-1111-4111-8111-111111111111"


def test_insert_contrato_translates_unique_violation_to_conflict() -> None:
    fake = _FakeSqlExecutor()
    fake.set_handler(
        _handler_lookup_then_insert(
            {"id": "t", "codigo": "Entrada"},
            [],
            BackendError(409, {"message": "duplicate key on contratos"}),
        )
    )
    insert = ContratoInsertInput(
        tipo="Entrada",
        entity_type="entrada",
        entity_id="e",
        numero_contrato="ENT-0002",
        fecha=None,
    )
    with pytest.raises(ContratoConflictError, match="ya existe un contrato"):
        insert_contrato(fake, insert=insert)


def test_insert_contrato_propagates_non_duplicate_backend_errors() -> None:
    fake = _FakeSqlExecutor()
    fake.set_handler(
        _handler_lookup_then_insert(
            {"id": "t", "codigo": "Entrada"},
            [],
            BackendError(500, {"message": "boom"}),
        )
    )
    insert = ContratoInsertInput(
        tipo="Entrada",
        entity_type="entrada",
        entity_id="e",
        numero_contrato="ENT-0003",
        fecha=None,
    )
    with pytest.raises(BackendError):
        insert_contrato(fake, insert=insert)


def test_insert_contrato_rejects_insert_returning_no_rows() -> None:
    fake = _FakeSqlExecutor()
    fake.set_handler(_handler_lookup_then_insert({"id": "t", "codigo": "Entrada"}, []))
    insert = ContratoInsertInput(
        tipo="Entrada",
        entity_type="entrada",
        entity_id="e",
        numero_contrato="ENT-0004",
        fecha=None,
    )
    with pytest.raises(RuntimeError, match="returned no rows"):
        insert_contrato(fake, insert=insert)


# --- get_contrato_for_entity -----------------------------------------------


def test_get_contrato_for_entity_maps_row_and_composes_slice_fields() -> None:
    fake = _FakeSqlExecutor()
    fake.set_response([dict(_ENTITY_ROW)])
    record = get_contrato_for_entity(
        fake, tipo="Entrada", entity_type="entrada", entity_id="e1"
    )
    assert record is not None
    assert record.id == _ENTITY_ROW["id"]
    assert record.tipo_codigo == "Entrada"
    assert record.entity_type == "entrada"
    assert record.entity_id == "e1"
    query, params = fake.calls[0]
    assert "entrada_id" in query
    assert "catalogos_tipos_contrato" in query
    assert params == ["Entrada", "e1"]


def test_get_contrato_for_entity_returns_none_when_absent() -> None:
    fake = _FakeSqlExecutor()
    fake.set_response([])
    assert (
        get_contrato_for_entity(fake, tipo="Entrada", entity_type="entrada", entity_id="x")
        is None
    )


# --- duplicate heuristic ----------------------------------------------------


@pytest.mark.parametrize(
    ("status_code", "body", "expected"),
    [
        (409, {"message": "duplicate key value violates unique constraint"}, True),
        (409, {"message": "relation contratos: duplicate"}, True),
        (409, {"message": "unique constraint violated"}, True),
        (409, {"message": "some other 409"}, False),
        (500, {"message": "duplicate"}, False),
    ],
)
def test_duplicate_heuristic_is_scoped_to_contratos_unique(
    status_code: int, body: Any, expected: bool
) -> None:
    fake = _FakeSqlExecutor()
    fake.set_handler(
        _handler_lookup_then_insert(
            {"id": "t", "codigo": "Entrada"},
            [],
            BackendError(status_code, body),
        )
    )
    insert = ContratoInsertInput(
        tipo="Entrada",
        entity_type="entrada",
        entity_id="e",
        numero_contrato="n",
        fecha=None,
    )
    if expected:
        with pytest.raises(ContratoConflictError):
            insert_contrato(fake, insert=insert)
    else:
        with pytest.raises(BackendError) as excinfo:
            insert_contrato(fake, insert=insert)
        assert not isinstance(excinfo.value, ContratoConflictError)
