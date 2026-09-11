"""Service-layer tests for FOSTER-01 casas_acogida.

The ``foster.service`` module owns:
- create / list / get / update / soft-delete of ``casas_acogida``
- validation: required fields, coche enum, especie_preferente enum,
  capacidad positive int
- search by especie_preferente (NULL counts as match)

Mirror of the ``tests/test_acogidas.py`` pattern: _FakeSqlExecutor for SQL
shape assertion without httpx.MockTransport.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from app.core.data_access import BackendError
from app.modules.foster import service as foster_service


class _ErrorResponse:
    """Marker returned by a fake handler to signal a backend error."""

    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self.body = body


class _FakeSqlExecutor:
    """Minimal ``SqlExecutor`` Protocol implementation for unit tests.

    Records every ``execute_sql`` call (query + params) so callers can
    assert on the SQL shape without standing up a Postgres instance.
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
    """Build a fake executor that delegates every ``execute_sql`` to ``handler``."""
    fake = _FakeSqlExecutor()
    fake.set_handler(handler)
    return fake, fake.calls


def _params_minimal() -> dict[str, Any]:
    return {
        "nombre": "María",
        "apellidos": "García López",
        "dni_acogedor": "12345678A",
        "calle": "Calle Mayor",
        "numero": "12",
        "piso": "3",
        "letra": "A",
        "localidad": "Alcalá de Henares",
        "provincia": "Madrid",
        "cp": "28801",
        "telefono": "600123456",
        "telefono2": None,
        "email": "maria@example.com",
        "vinculacion": "Socia",
        "caracteristicas": "Piso con patio",
        "coche": "Sí",
        "especie_preferente": "CANINA",
        "observaciones": "Disponible fines de semana",
        "capacidad": 3,
    }


def _row(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "11111111-1111-1111-1111-111111111111",
        "nombre": "María",
        "apellidos": "García López",
        "dni_acogedor": "12345678A",
        "calle": "Calle Mayor",
        "numero": "12",
        "piso": "3",
        "letra": "A",
        "localidad": "Alcalá de Henares",
        "provincia": "Madrid",
        "cp": "28801",
        "telefono": "600123456",
        "telefono2": None,
        "email": "maria@example.com",
        "vinculacion": "Socia",
        "caracteristicas": "Piso con patio",
        "coche": "Sí",
        "especie_preferente": "CANINA",
        "observaciones": "Disponible fines de semana",
        "capacidad": 3,
        "fecha_alta": "2026-07-04T10:00:00Z",
        "fecha_baja": None,
        "updated_at": "2026-07-04T10:00:00Z",
        "activo": True,
    }
    if overrides:
        row.update(overrides)
    return row


def _insert_handler(
    insert_row: dict[str, Any] | None = None,
) -> Callable[[str, list[object]], list[dict[str, object]]]:
    def _h(
        query: str, _params: list[object]
    ) -> list[dict[str, object]]:
        if "INSERT INTO casas_acogida" in query:
            return [insert_row or _row()]
        if "UPDATE casas_acogida SET" in query:
            return [insert_row or _row()]
        raise AssertionError(f"Unexpected SQL: {query}")

    return _h


# --- create: happy path -------------------------------------------------------


def test_create_casa_acogida_inserts_with_all_columns() -> None:
    client, captured = _make_client(_insert_handler())

    result = foster_service.create_casa_acogida(client, _params_minimal())
    client.close()

    assert isinstance(result, foster_service.CasaAcogida)
    assert result.id == "11111111-1111-1111-1111-111111111111"
    assert result.nombre == "María"
    assert result.coche == "Sí"
    assert result.especie_preferente == "CANINA"
    assert result.capacidad == 3
    assert result.activo is True

    assert len(captured) == 1
    query, params = captured[0]
    assert "INSERT INTO casas_acogida" in query
    # Public Spanish copy never appears in SQL — snake_case columns
    # in the ORDER written by the service.
    assert "voluntario_entrada_id" not in query
    assert params[:6] == [
        "María",  # nombre
        "García López",  # apellidos
        "12345678A",  # dni_acogedor
        "Calle Mayor",  # calle
        "12",  # numero
        "3",  # piso
    ]


def test_create_casa_acogida_with_no_especie_preferente_is_allowed() -> None:
    params = {**_params_minimal(), "especie_preferente": None}
    client, captured = _make_client(
        _insert_handler(_row({"especie_preferente": None}))
    )

    result = foster_service.create_casa_acogida(client, params)
    client.close()

    assert result.especie_preferente is None
    # None → NULL parameter in the INSERT
    _, params = captured[0]
    assert None in params


# --- create: required-field validation ------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("nombre", ""),
        ("nombre", "   "),
        ("apellidos", ""),
        ("calle", ""),
        ("telefono", ""),
    ],
)
def test_create_casa_acogida_rejects_empty_required_field_before_sql(
    field: str, value: str
) -> None:
    client, captured = _make_client(lambda _q, _p: [_row()])

    with pytest.raises(ValueError, match=field):
        foster_service.create_casa_acogida(
            client, {**_params_minimal(), field: value}
        )
    client.close()

    assert captured == []


# --- create: coche enum ----------------------------------------------------


@pytest.mark.parametrize("value", ["Si", "yes", "1", ""])
def test_create_casa_acogida_rejects_invalid_coche(value: str) -> None:
    client, captured = _make_client(lambda _q, _p: [_row()])

    with pytest.raises(ValueError, match="coche"):
        foster_service.create_casa_acogida(
            client, {**_params_minimal(), "coche": value}
        )
    client.close()

    assert captured == []


def test_create_casa_acogida_accepts_coche_no() -> None:
    client, captured = _make_client(
        _insert_handler(_row({"coche": "No"}))
    )

    result = foster_service.create_casa_acogida(
        client, {**_params_minimal(), "coche": "No"}
    )
    client.close()

    assert result.coche == "No"


# --- create: especie_preferente enum --------------------------------------


@pytest.mark.parametrize("value", ["AVES", "canina", "Perro"])
def test_create_casa_acogida_rejects_invalid_especie_preferente(value: str) -> None:
    client, captured = _make_client(lambda _q, _p: [_row()])

    with pytest.raises(ValueError, match="especie_preferente"):
        foster_service.create_casa_acogida(
            client, {**_params_minimal(), "especie_preferente": value}
        )
    client.close()

    assert captured == []


def test_create_casa_acogida_accepts_felina() -> None:
    client, captured = _make_client(
        _insert_handler(_row({"especie_preferente": "FELINA"}))
    )

    result = foster_service.create_casa_acogida(
        client, {**_params_minimal(), "especie_preferente": "FELINA"}
    )
    client.close()

    assert result.especie_preferente == "FELINA"


# --- create: capacidad validation -----------------------------------------


@pytest.mark.parametrize("value", [0, -1, "three", None, ""])
def test_create_casa_acogida_rejects_invalid_capacidad(value: Any) -> None:
    client, captured = _make_client(lambda _q, _p: [_row()])

    with pytest.raises(ValueError, match="capacidad"):
        foster_service.create_casa_acogida(
            client, {**_params_minimal(), "capacidad": value}
        )
    client.close()

    assert captured == []


def test_create_casa_acogida_accepts_capacidad_one() -> None:
    client, captured = _make_client(_insert_handler(_row({"capacidad": 1})))

    result = foster_service.create_casa_acogida(
        client, {**_params_minimal(), "capacidad": 1}
    )
    client.close()

    assert result.capacidad == 1


# --- list -----------------------------------------------------------------


def test_list_casas_acogida_returns_active_rows_ordered_by_fecha_alta() -> None:
    rows = [
        _row({"id": "casa-2", "fecha_alta": "2026-07-04T12:00:00Z"}),
        _row({"id": "casa-1", "fecha_alta": "2026-07-04T10:00:00Z"}),
    ]
    client, captured = _make_client(lambda _q, _p: rows)

    result = foster_service.list_casas_acogida(client)
    client.close()

    assert [c.id for c in result] == ["casa-2", "casa-1"]
    query, _params = captured[0]
    assert "FROM casas_acogida" in query
    assert "WHERE activo = true" in query
    assert "ORDER BY fecha_alta DESC" in query


def test_list_casas_acogida_with_especie_filter_includes_null_preference() -> None:
    """A casa with especie_preferente IS NULL counts as match for any especie
    (the operator's "cualquier especie" pattern)."""
    client, captured = _make_client(lambda _q, _p: [_row()])

    foster_service.list_casas_acogida(client, especie="FELINA")
    client.close()

    query, params = captured[0]
    assert "especie_preferente = $1" in query
    assert "OR especie_preferente IS NULL" in query
    assert params == ["FELINA"]


def test_list_casas_acogida_with_no_especie_omits_filter() -> None:
    client, captured = _make_client(lambda _q, _p: [])

    foster_service.list_casas_acogida(client, especie=None)
    client.close()

    query, _params = captured[0]
    assert "especie_preferente = $1" not in query
    assert "OR especie_preferente IS NULL" not in query


# --- get by id ------------------------------------------------------------


def test_get_casa_acogida_by_id_returns_row_or_none() -> None:
    def _handler(query: str, params: list[object]) -> list[dict[str, object]]:
        if params == ["missing"]:
            return []
        return [_row({"id": str(params[0])})]

    client, captured = _make_client(_handler)
    found = foster_service.get_casa_acogida_by_id(client, "found")
    missing = foster_service.get_casa_acogida_by_id(client, "missing")
    client.close()

    assert found is not None and found.id == "found"
    assert missing is None
    assert [p for _, p in captured] == [["found"], ["missing"]]


# --- update ----------------------------------------------------------------


def test_update_casa_acogida_validates_and_updates_minimal_fields() -> None:
    client, captured = _make_client(
        _insert_handler(_row({"capacidad": 5}))
    )

    result = foster_service.update_casa_acogida(
        client, "11111111-1111-1111-1111-111111111111",
        {**_params_minimal(), "capacidad": 5},
    )
    client.close()

    assert result is not None
    assert result.capacidad == 5
    query, params = captured[0]
    assert "UPDATE casas_acogida SET" in query
    assert "updated_at = now()" in query
    assert params[0] == "11111111-1111-1111-1111-111111111111"


def test_update_casa_acogida_returns_none_when_id_missing() -> None:
    def _handler(query: str, _params: list[object]) -> list[dict[str, object]]:
        if "UPDATE casas_acogida SET" in query:
            return []
        raise AssertionError(f"Unexpected SQL: {query}")

    client, captured = _make_client(_handler)
    result = foster_service.update_casa_acogida(
        client, "missing", _params_minimal()
    )
    client.close()

    assert result is None


# --- soft delete ----------------------------------------------------------


def test_delete_casa_acogida_soft_deletes_without_physical_delete() -> None:
    client, captured = _make_client(
        lambda _q, _p: [{"id": "casa-1", "activo": False}]
    )
    result = foster_service.delete_casa_acogida(client, "casa-1")
    client.close()

    assert result is True
    assert len(captured) == 1
    query, _params = captured[0]
    assert "UPDATE casas_acogida" in query
    assert "SET activo = false" in query
    assert "fecha_baja = now()" in query
    assert "DELETE FROM" not in query


def test_delete_casa_acogida_returns_false_when_id_missing() -> None:
    client, captured = _make_client(lambda _q, _p: [])
    result = foster_service.delete_casa_acogida(client, "missing")
    client.close()

    assert result is False
    assert len(captured) == 1
