"""Tests para el endpoint GET /animales/search (issue #30).

TDD RED: estos tests definen el contrato del search API antes de la
implementacion. Cubren los 9 criterios de aceptacion del spec.

El test runner es httpx.MockTransport (mismo patron que
``test_animals.py``) para capturar SQL y params sin red.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.insforge import InsForgeClient
from app.modules.animals.service import search_animals

# --- helpers --------------------------------------------------------------


def _json_response(status_code: int, body: Any) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _client_recording(handler) -> tuple[InsForgeClient, list[dict[str, Any]]]:
    """Cliente cuyo MockTransport registra cada body JSON enviado."""
    captured: list[dict[str, Any]] = []

    def _recording_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization", "").startswith("Bearer ")
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        captured.append(body)
        return handler(request, body)

    client = InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=httpx.MockTransport(_recording_handler),
    )
    return client, captured


# --- acceptance criteria tests ---------------------------------------------


def test_search_by_chip_exact_match() -> None:
    """AC-1: ?chip=123 devuelve solo animales con chip exacto."""
    returned_rows = [
        {
            "id": "aaa",
            "NCHIP": "123456789012345",
            "NombreAnimal": "Luna",
            "Especie": "CANINA",
            "Sexo": "H",
            "FNacimiento": "2023-04-12",
            "activo": True,
            "fecha_alta": "2024-01-15",
            "current_state": "Albergue",
        },
    ]

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        # Distinguish data query from count query by checking SQL content
        sql = body.get("query", "")
        if "COUNT" in sql.upper() or "count" in sql.lower():
            return _json_response(200, [{"total": 1}])
        return _json_response(200, returned_rows)

    client, captured = _client_recording(_handler)
    result = search_animals(client, chip="123456789012345")
    client.close()

    assert len(result.data) == 1
    assert result.data[0].chip == "123456789012345"
    assert result.total == 1
    assert len(captured) == 2  # data + count


def test_search_by_name_substring_case_insensitive() -> None:
    """AC-2: ?q=luna devuelve animales con 'luna' en el nombre (case-insensitive)."""
    returned_rows = [
        {
            "id": "aaa",
            "NCHIP": "1",
            "NombreAnimal": "Luna",
            "Especie": "CANINA",
            "Sexo": "H",
            "FNacimiento": "2023-04-12",
            "activo": True,
            "fecha_alta": "2024-01-15",
            "current_state": "Albergue",
        },
        {
            "id": "bbb",
            "NCHIP": "2",
            "NombreAnimal": "Lunares",
            "Especie": "FELINA",
            "Sexo": "M",
            "FNacimiento": "2024-01-01",
            "activo": True,
            "fecha_alta": "2024-02-01",
            "current_state": "Acogida",
        },
    ]

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        sql = body.get("query", "")
        if "COUNT" in sql.upper() or "count" in sql.lower():
            return _json_response(200, [{"total": 2}])
        return _json_response(200, returned_rows)

    client, captured = _client_recording(_handler)
    result = search_animals(client, q="luna")
    client.close()

    assert len(result.data) == 2
    assert len(captured) == 2
    query = captured[0]["query"]
    assert "ILIKE" in query or "ilike" in query.lower()


def test_search_by_especie_canina() -> None:
    """AC-3: ?especie=CANINA devuelve solo perros."""
    returned_rows = [
        {
            "id": "aaa",
            "NCHIP": "1",
            "NombreAnimal": "Luna",
            "Especie": "CANINA",
            "Sexo": "H",
            "FNacimiento": "2023-04-12",
            "activo": True,
            "fecha_alta": "2024-01-15",
            "current_state": "Albergue",
        },
    ]

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        sql = body.get("query", "")
        if "COUNT" in sql.upper() or "count" in sql.lower():
            return _json_response(200, [{"total": 1}])
        return _json_response(200, returned_rows)

    client, captured = _client_recording(_handler)
    result = search_animals(client, especie="CANINA")
    client.close()

    assert len(result.data) == 1
    assert result.data[0].especie == "CANINA"


def test_search_by_estado_albergue() -> None:
    """AC-4: ?estado=albergue devuelve animales en estado Albergue."""
    returned_rows = [
        {
            "id": "aaa",
            "NCHIP": "1",
            "NombreAnimal": "Luna",
            "Especie": "CANINA",
            "Sexo": "H",
            "FNacimiento": "2023-04-12",
            "activo": True,
            "fecha_alta": "2024-01-15",
            "current_state": "Albergue",
        },
    ]

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        sql = body.get("query", "")
        if "COUNT" in sql.upper() or "count" in sql.lower():
            return _json_response(200, [{"total": 1}])
        return _json_response(200, returned_rows)

    client, captured = _client_recording(_handler)
    result = search_animals(client, estado="albergue")
    client.close()

    assert len(result.data) == 1
    assert result.data[0].estado == "albergue"


def test_search_by_fecha_alta_range() -> None:
    """AC-5: filtra por rango fecha_alta."""
    returned_rows = [
        {
            "id": "aaa",
            "NCHIP": "1",
            "NombreAnimal": "Luna",
            "Especie": "CANINA",
            "Sexo": "H",
            "FNacimiento": "2023-04-12",
            "activo": True,
            "fecha_alta": "2024-06-15",
            "current_state": "Albergue",
        },
    ]

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        sql = body.get("query", "")
        if "COUNT" in sql.upper() or "count" in sql.lower():
            return _json_response(200, [{"total": 1}])
        return _json_response(200, returned_rows)

    client, captured = _client_recording(_handler)
    result = search_animals(
        client,
        fecha_alta_since="2024-01-01",
        fecha_alta_until="2024-12-31",
    )
    client.close()

    assert len(result.data) == 1
    query = captured[0]["query"]
    # Debe tener condiciones de rango en fecha_alta
    assert ">=" in query or "BETWEEN" in query.upper()


def test_search_combined_filters_are_AND() -> None:
    """AC-6: la combinacion de filtros es AND."""
    returned_rows = [
        {
            "id": "aaa",
            "NCHIP": "1",
            "NombreAnimal": "Luna",
            "Especie": "CANINA",
            "Sexo": "H",
            "FNacimiento": "2023-04-12",
            "activo": True,
            "fecha_alta": "2024-03-01",
            "current_state": "Albergue",
        },
    ]

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        sql = body.get("query", "")
        if "COUNT" in sql.upper() or "count" in sql.lower():
            return _json_response(200, [{"total": 1}])
        return _json_response(200, returned_rows)

    client, captured = _client_recording(_handler)
    result = search_animals(
        client,
        especie="CANINA",
        sexo="H",
        fecha_alta_since="2024-01-01",
    )
    client.close()

    assert len(result.data) == 1


def test_search_response_includes_total() -> None:
    """AC-7: la respuesta incluye `total` (sin paginar) para UI de resultados."""
    returned_rows = [
        {
            "id": "aaa",
            "NCHIP": "1",
            "NombreAnimal": "Luna",
            "Especie": "CANINA",
            "Sexo": "H",
            "FNacimiento": "2023-04-12",
            "activo": True,
            "fecha_alta": "2024-01-15",
            "current_state": "Albergue",
        },
    ]

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        sql = body.get("query", "")
        if "COUNT" in sql.upper() or "count" in sql.lower():
            return _json_response(200, [{"total": 1}])
        return _json_response(200, returned_rows)

    client, captured = _client_recording(_handler)
    result = search_animals(client, especie="CANINA")
    client.close()

    assert result.total == 1
    assert hasattr(result, "data")
    assert hasattr(result, "limit")
    assert hasattr(result, "offset")


def test_search_limit_zero_returns_only_total() -> None:
    """AC-8: limit=0 devuelve solo total sin data (count sin fetch)."""
    count_returned = [{"total": 42}]
    data_returned: list[dict[str, Any]] = []

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        sql = body.get("query", "")
        if "COUNT" in sql.upper() or "count" in sql.lower():
            return _json_response(200, count_returned)
        return _json_response(200, data_returned)

    client, captured = _client_recording(_handler)
    result = search_animals(client, limit=0)
    client.close()

    # Si limit=0 y la logica es correcta, solo se ejecuta la query de count
    assert result.total == 42
    assert result.data == []
    assert result.limit == 0


def test_search_default_ordering_fecha_alta_desc() -> None:
    """Orden por defecto: fecha_alta DESC (mas recientes primero)."""
    returned_rows = [
        {
            "id": "aaa",
            "NCHIP": "1",
            "NombreAnimal": "Luna",
            "Especie": "CANINA",
            "Sexo": "H",
            "FNacimiento": "2023-04-12",
            "activo": True,
            "fecha_alta": "2024-01-15",
            "current_state": "Albergue",
        },
    ]

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        sql = body.get("query", "")
        if "COUNT" in sql.upper() or "count" in sql.lower():
            return _json_response(200, [{"total": 1}])
        return _json_response(200, returned_rows)

    client, captured = _client_recording(_handler)
    _ = search_animals(client)
    client.close()

    assert len(captured) == 2
    query = captured[0]["query"]
    assert "ORDER BY" in query
    assert "fecha_alta" in query
    assert "DESC" in query.upper()


def test_search_chip_exact_ignores_q() -> None:
    """Spec: si chip esta presente, ignora q."""
    returned_rows = [
        {
            "id": "aaa",
            "NCHIP": "999",
            "NombreAnimal": "Luna",
            "Especie": "CANINA",
            "Sexo": "H",
            "FNacimiento": "2023-04-12",
            "activo": True,
            "fecha_alta": "2024-01-15",
            "current_state": "Albergue",
        },
    ]

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        sql = body.get("query", "")
        if "COUNT" in sql.upper() or "count" in sql.lower():
            return _json_response(200, [{"total": 1}])
        return _json_response(200, returned_rows)

    client, captured = _client_recording(_handler)
    # Proporcionar ambos: chip y q — chip debe ganar
    result = search_animals(client, chip="999", q="luna")
    client.close()

    assert len(result.data) == 1
    query = captured[0]["query"]
    # El query debe tener filtrado por chip exacto (NCHIP = ...)
    assert "NCHIP" in query
    # Y NO debe tener ILIKE para nombre (q fue ignorado por presencia de chip)
    assert "ILIKE" not in query


def test_search_limit_capped_at_200() -> None:
    """Spec: limit default 50, max 200."""
    returned_rows = []

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        sql = body.get("query", "")
        if "COUNT" in sql.upper() or "count" in sql.lower():
            return _json_response(200, [{"total": 0}])
        return _json_response(200, returned_rows)

    client, captured = _client_recording(_handler)
    # Pide 500, debe limitarse a 200
    result = search_animals(client, limit=500)
    client.close()

    assert result.limit == 200


def test_search_default_limit_50() -> None:
    """Spec: limit default 50."""
    returned_rows = []

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        sql = body.get("query", "")
        if "COUNT" in sql.upper() or "count" in sql.lower():
            return _json_response(200, [{"total": 0}])
        return _json_response(200, returned_rows)

    client, captured = _client_recording(_handler)
    result = search_animals(client)
    client.close()

    assert result.limit == 50


def test_search_estado_incoherente_maps_to_incoherente() -> None:
    """Estado 'incoherente' en la DB se normaliza a 'incoherente' en la respuesta."""
    returned_rows = [
        {
            "id": "aaa",
            "NCHIP": "1",
            "NombreAnimal": "Luna",
            "Especie": "CANINA",
            "Sexo": "H",
            "FNacimiento": "2023-04-12",
            "activo": True,
            "fecha_alta": "2024-01-15",
            "current_state": "Incoherente",
        },
    ]

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        sql = body.get("query", "")
        if "COUNT" in sql.upper() or "count" in sql.lower():
            return _json_response(200, [{"total": 1}])
        return _json_response(200, returned_rows)

    client, captured = _client_recording(_handler)
    result = search_animals(client, estado="incoherente")
    client.close()

    assert len(result.data) == 1
    assert result.data[0].estado == "incoherente"


def test_search_pagination_offset() -> None:
    """Offset permite paginar resultados."""
    returned_rows = [
        {
            "id": "bbb",
            "NCHIP": "2",
            "NombreAnimal": "Mishi",
            "Especie": "FELINA",
            "Sexo": "M",
            "FNacimiento": "2024-01-01",
            "activo": True,
            "fecha_alta": "2024-02-01",
            "current_state": "Acogida",
        },
    ]

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        sql = body.get("query", "")
        if "COUNT" in sql.upper() or "count" in sql.lower():
            return _json_response(200, [{"total": 15}])
        return _json_response(200, returned_rows)

    client, captured = _client_recording(_handler)
    result = search_animals(client, offset=10, limit=5)
    client.close()

    assert result.offset == 10
    assert result.limit == 5
    assert result.total == 15


def test_search_JOIN_with_animal_current_state() -> None:
    """El query de estado hace LEFT JOIN con animal_current_state."""
    returned_rows = [
        {
            "id": "aaa",
            "NCHIP": "1",
            "NombreAnimal": "Luna",
            "Especie": "CANINA",
            "Sexo": "H",
            "FNacimiento": "2023-04-12",
            "activo": True,
            "fecha_alta": "2024-01-15",
            "current_state": "Albergue",
        },
    ]

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        sql = body.get("query", "")
        if "COUNT" in sql.upper() or "count" in sql.lower():
            return _json_response(200, [{"total": 1}])
        return _json_response(200, returned_rows)

    client, captured = _client_recording(_handler)
    _ = search_animals(client, estado="albergue")
    client.close()

    assert len(captured) == 2
    data_query = captured[0]["query"]
    assert "animal_current_state" in data_query.lower().replace(" ", "")
    assert "LEFT JOIN" in data_query
