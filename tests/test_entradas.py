"""Service-layer tests for minimal intake entries.

The ``entradas`` service owns SQL, validation, duplicate handling, mapping,
and soft-delete behavior. These tests use a ``_FakeSqlExecutor`` so they
can assert SQL and params without network I/O (issue #732 Arc B).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from app.core.data_access import BackendError
from app.modules.entradas.service import (
    Entrada,
    EntradaConflictError,
    create_entrada,
    delete_entrada,
    get_entrada_by_id,
    list_entradas,
    update_entrada,
)


class _ErrorResponse:
    """Marker returned by a fake handler to signal a backend error."""

    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self.body = body


class _FakeSqlExecutor:
    """Minimal ``SqlExecutor`` Protocol implementation for unit tests.

    Supports ``set_handler`` so per-call inspection of (query, params)
    can return rows, an ``_ErrorResponse``, or ``None`` (fall through
    to empty list).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[object]]] = []
        self._responses: list[list[dict[str, object]]] = []
        self._handler: Callable[[str, list[object]], Any] | None = None

    def set_response(self, rows: list[dict[str, object]]) -> None:
        self._responses = [rows]

    def set_responses(self, *responses: list[dict[str, object]]) -> None:
        self._responses = list(responses)

    def set_handler(
        self, handler: Callable[[str, list[object]], Any]
    ) -> None:
        self._handler = handler

    def execute_sql(
        self, query: str, params: list[object] | None = None
    ) -> list[dict[str, object]]:
        self.calls.append((query, list(params or [])))
        bound_params = list(params or [])
        if self._handler is not None:
            result = self._handler(query, bound_params)
            if isinstance(result, _ErrorResponse):
                raise BackendError(result.status_code, result.body)
            if result is not None:
                return result  # type: ignore[no-any-return]
        if self._responses:
            return self._responses.pop(0)
        return []

    def close(self) -> None:
        pass  # no-op for fake


def _make_client(
    handler: Callable[[str, list[object]], Any],
) -> tuple[_FakeSqlExecutor, list[tuple[str, list[object]]]]:
    fake = _FakeSqlExecutor()
    fake.set_handler(handler)
    return fake, fake.calls


def _params_minimal() -> dict[str, Any]:
    return {
        "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "voluntario_entrada_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "fecha_entrada": "2026-06-25",
        "origen": "Albergue",
        "motivo": "Rescate",
        "observaciones": "Entrada inicial",
    }


def _row(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "11111111-1111-1111-1111-111111111111",
        "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "voluntario_entrada_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "fecha_entrada": "2026-06-25",
        "origen": "Albergue",
        "motivo": "Rescate",
        "observaciones": "Entrada inicial",
        "activo": True,
        "fecha_alta": "2026-06-25T10:00:00Z",
        "updated_at": "2026-06-25T10:00:00Z",
    }
    if overrides:
        row.update(overrides)
    return row


def _validation_handler(insert_row: dict[str, Any] | None = None):
    def _handler(query: str, params: list[object]) -> Any:
        if "FROM animales" in query:
            return [{"id": params[0], "activo": True}]
        if "FROM voluntarios" in query:
            return [{"id": params[0], "activo": True}]
        if "INSERT INTO entradas" in query or "UPDATE entradas SET" in query:
            return [insert_row or _row()]
        raise AssertionError(f"Unexpected SQL: {query}")

    return _handler


def test_create_entrada_validates_references_inserts_minimal_public_fields() -> None:
    client, captured = _make_client(_validation_handler())

    result = create_entrada(client, _params_minimal())

    assert isinstance(result, Entrada)
    assert result.id == "11111111-1111-1111-1111-111111111111"
    assert result.animal_id == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert result.voluntario_entrada_id == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert result.fecha_entrada == "2026-06-25"

    assert len(captured) == 3
    assert "FROM animales" in captured[0][0]
    volunteer_lookup = captured[1][0]
    assert "FROM voluntarios" in volunteer_lookup
    assert "activo = true" in volunteer_lookup
    assert "tipo_rol" not in volunteer_lookup

    insert = captured[2]
    query = insert[0]
    assert "INSERT INTO entradas" in query
    assert "voluntario_salida_id" not in query
    assert "fecha_salida" not in query
    assert "fecha_entrega_propietario" not in query
    assert "donativo_entregador" not in query
    assert insert[1] == [
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "2026-06-25",
        "Albergue",
        "Rescate",
        "Entrada inicial",
    ]


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("animal_id", "", "animal_id"),
        ("fecha_entrada", "   ", "fecha_entrada"),
    ],
)
def test_create_entrada_rejects_required_fields_before_sql(
    field: str,
    value: str,
    match: str,
) -> None:
    client, captured = _make_client(lambda q, p: [])

    with pytest.raises(ValueError, match=match):
        create_entrada(client, {**_params_minimal(), field: value})

    assert captured == []


def test_create_entrada_rejects_inactive_volunteer_before_insert() -> None:
    def _handler(query: str, params: list[object]) -> Any:
        if "FROM animales" in query:
            return [{"id": params[0], "activo": True}]
        if "FROM voluntarios" in query:
            return []
        raise AssertionError(f"Unexpected SQL: {query}")

    client, captured = _make_client(_handler)

    with pytest.raises(ValueError, match="voluntario_entrada_id"):
        create_entrada(client, _params_minimal())

    assert len(captured) == 2
    assert all("INSERT INTO entradas" not in call[0] for call in captured)


def test_create_entrada_rejects_duplicate_natural_key_as_conflict() -> None:
    def _handler(query: str, params: list[object]) -> Any:
        if "FROM animales" in query:
            return [{"id": params[0], "activo": True}]
        if "FROM voluntarios" in query:
            return [{"id": params[0], "activo": True}]
        if "INSERT INTO entradas" in query:
            return _ErrorResponse(
                409,
                {"error": "duplicate key value violates unique constraint entradas_natural_key"},
            )
        raise AssertionError(f"Unexpected SQL: {query}")

    client, captured = _make_client(_handler)

    with pytest.raises(EntradaConflictError, match="entrada duplicada"):
        create_entrada(client, _params_minimal())

    assert len(captured) == 3


def test_create_entrada_allows_null_volunteer_without_lookup() -> None:
    params = {**_params_minimal(), "voluntario_entrada_id": None}

    client, captured = _make_client(_validation_handler(_row({"voluntario_entrada_id": None})))
    result = create_entrada(client, params)

    assert result.voluntario_entrada_id is None
    assert len(captured) == 2
    assert "FROM animales" in captured[0][0]
    assert "INSERT INTO entradas" in captured[1][0]
    assert "FROM voluntarios" not in "\n".join(call[0] for call in captured)


def test_list_entradas_returns_active_rows_ordered_by_created_date() -> None:
    rows = [
        _row({"id": "entry-2", "fecha_entrada": "2026-06-26"}),
        _row({"id": "entry-1", "fecha_entrada": "2026-06-25"}),
    ]

    client, captured = _make_client(lambda q, p: rows)
    result = list_entradas(client)

    assert [entry.id for entry in result] == ["entry-2", "entry-1"]
    query = captured[0][0]
    assert "SELECT" in query
    assert "FROM entradas" in query
    assert "WHERE activo = true" in query
    assert "ORDER BY fecha_alta DESC" in query


def test_get_entrada_by_id_returns_entry_or_none() -> None:
    def _handler(query: str, params: list[object]) -> list[dict[str, object]]:
        if params == ["missing"]:
            return []
        return [_row({"id": params[0]})]

    client, captured = _make_client(_handler)
    found = get_entrada_by_id(client, "found")
    missing = get_entrada_by_id(client, "missing")

    assert found is not None
    assert found.id == "found"
    assert missing is None
    assert [call[1] for call in captured] == [["found"], ["missing"]]
    assert all("WHERE id = $1" in call[0] for call in captured)


def test_update_entrada_validates_and_updates_minimal_public_fields() -> None:
    client, captured = _make_client(
        _validation_handler(_row({"motivo": "Correccion", "updated_at": "2026-06-25T12:00:00Z"}))
    )

    result = update_entrada(
        client,
        "11111111-1111-1111-1111-111111111111",
        {**_params_minimal(), "motivo": "Correccion"},
    )

    assert result is not None
    assert result.motivo == "Correccion"
    assert result.updated_at == "2026-06-25T12:00:00Z"
    query = captured[2][0]
    assert "UPDATE entradas SET" in query
    assert "updated_at = now()" in query
    assert "WHERE id = $1" in query
    assert "RETURNING" in query
    assert "voluntario_salida_id" not in query
    assert captured[2][1][0] == "11111111-1111-1111-1111-111111111111"
    assert captured[2][1][1:] == [
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "2026-06-25",
        "Albergue",
        "Correccion",
        "Entrada inicial",
    ]


def test_update_entrada_returns_none_when_id_is_missing() -> None:
    def _handler(query: str, params: list[object]) -> Any:
        if "FROM animales" in query:
            return [{"id": params[0], "activo": True}]
        if "FROM voluntarios" in query:
            return [{"id": params[0], "activo": True}]
        if "UPDATE entradas SET" in query:
            return []
        raise AssertionError(f"Unexpected SQL: {query}")

    client, captured = _make_client(_handler)
    result = update_entrada(client, "missing", _params_minimal())

    assert result is None
    assert captured[-1][1][0] == "missing"


def test_delete_entrada_soft_deletes_without_physical_delete() -> None:
    client, captured = _make_client(lambda q, p: [{"id": "entry", "activo": False}])
    result = delete_entrada(client, "entry")

    assert result is True
    assert len(captured) == 1
    query = captured[0][0]
    assert "UPDATE entradas" in query
    assert "SET activo = false" in query
    assert "DELETE FROM" not in query
    assert captured[0][1] == ["entry"]


def test_delete_entrada_returns_false_when_id_is_missing() -> None:
    client, captured = _make_client(lambda q, p: [])
    result = delete_entrada(client, "missing")

    assert result is False
    assert len(captured) == 1
