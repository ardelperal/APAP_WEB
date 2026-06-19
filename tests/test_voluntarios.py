"""Tests TDD estrictos del service layer de voluntarios (12 tests).

Cubre:
- ``create_voluntario`` valida campos antes de SQL y devuelve ``Voluntario``.
- ``list_voluntarios`` ejecuta el SELECT y devuelve la lista.
- ``get_voluntario_by_id`` devuelve la fila o ``None``.
- ``list_roles`` devuelve los roles del voluntario.
- Email invalido se rechaza sin SQL.
- Email/DNI duplicado propaga ``InsForgeError``.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.core.insforge import InsForgeClient, InsForgeError
from app.modules.voluntarios.service import (
    Voluntario,
    create_voluntario,
    get_voluntario_by_id,
    list_roles,
    list_voluntarios,
)


def _json_response(status_code: int, body: Any) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _client_recording(handler) -> tuple[InsForgeClient, list[dict[str, Any]]]:
    captured: list[dict[str, Any]] = []

    def _recording_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        captured.append(body)
        return handler(request, body)

    client = InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=httpx.MockTransport(_recording_handler),
    )
    return client, captured


def _params_minimal() -> dict[str, Any]:
    """Parametros validos para el happy path (solo Voluntario obligatorio)."""
    return {"Voluntario": "Ana Garcia"}


def _returned_row() -> dict[str, Any]:
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "Voluntario": "Ana Garcia",
        "activo": True,
    }


# --- create_voluntario ----------------------------------------------------


def test_create_voluntario_ejecuta_insert_con_parametros_esperados() -> None:
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [_returned_row()])

    client, captured = _client_recording(_handler)
    result = create_voluntario(client, _params_minimal())
    client.close()

    assert result.id == "11111111-1111-1111-1111-111111111111"
    assert result.Voluntario == "Ana Garcia"
    assert result.activo is True

    assert len(captured) == 1
    query = captured[0]["query"]
    assert "INSERT INTO voluntarios" in query
    assert "RETURNING" in query
    params = captured[0]["params"]
    assert params[0] == "Ana Garcia"


def test_create_voluntario_acepta_todos_los_campos_opcionales() -> None:
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [{
            "id": "22222222-2222-2222-2222-222222222222",
            "Voluntario": "Eva Lopez",
            "Tel1": "600123456",
            "Tel2": "911234567",
            "Email": "eva@example.com",
            "DNI": "12345678A",
            "activo": True,
        }])

    client, captured = _client_recording(_handler)
    create_voluntario(
        client,
        {
            "Voluntario": "Eva Lopez",
            "Tel1": "600123456",
            "Tel2": "911234567",
            "Email": "eva@example.com",
            "DNI": "12345678A",
        },
    )
    client.close()

    assert len(captured) == 1
    query = captured[0]["query"]
    for col in ("Voluntario", "Tel1", "Tel2", "Email", "DNI"):
        assert col in query, f"falta columna {col} en el INSERT"
    params = captured[0]["params"]
    assert params[0] == "Eva Lopez"
    assert params[1] == "600123456"
    assert params[2] == "911234567"
    assert params[3] == "eva@example.com"
    assert params[4] == "12345678A"


def test_create_voluntario_rechaza_nombre_vacio_antes_de_sql() -> None:
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    with pytest.raises(ValueError, match="Voluntario"):
        create_voluntario(client, {"Voluntario": "   "})
    client.close()

    assert captured == []


def test_create_voluntario_rechaza_email_sin_formato_antes_de_sql() -> None:
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    with pytest.raises(ValueError, match="Email"):
        create_voluntario(client, {"Voluntario": "Ana", "Email": "no-es-email"})
    client.close()

    assert captured == []


def test_create_voluntario_propag_InsForgeError_en_email_duplicado() -> None:
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(409, {"error": "duplicate key value violates unique constraint"})

    client, _ = _client_recording(_handler)

    with pytest.raises(InsForgeError) as exc:
        create_voluntario(client, {"Voluntario": "Ana", "Email": "dup@example.com"})
    client.close()

    assert exc.value.status_code == 409


def test_create_voluntario_email_vacio_se_permite() -> None:
    """Email es opcional. Un string vacio se normaliza a None y se envia como NULL."""

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [{"id": "x", "Voluntario": "Ana", "activo": True}])

    client, captured = _client_recording(_handler)
    create_voluntario(client, {"Voluntario": "Ana", "Email": ""})
    client.close()

    params = captured[0]["params"]
    assert params[3] is None  # Email vacio -> NULL


# --- list_voluntarios -----------------------------------------------------


def test_list_voluntarios_ejecuta_select_y_devuelve_filas() -> None:
    rows = [
        {"id": "aaa", "Voluntario": "Ana", "activo": True},
        {"id": "bbb", "Voluntario": "Eva", "activo": True},
    ]

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, rows)

    client, captured = _client_recording(_handler)
    result = list_voluntarios(client)
    client.close()

    assert [v.id for v in result] == ["aaa", "bbb"]
    assert [v.Voluntario for v in result] == ["Ana", "Eva"]

    assert len(captured) == 1
    query = captured[0]["query"]
    assert "SELECT" in query
    assert "FROM voluntarios" in query
    assert "WHERE activo = true" in query
    assert "ORDER BY Voluntario ASC" in query


def test_list_voluntarios_devuelve_lista_vacia_sin_filas() -> None:
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [])

    client, _ = _client_recording(_handler)
    result = list_voluntarios(client)
    client.close()

    assert result == []


# --- get_voluntario_by_id -------------------------------------------------


def test_get_voluntario_by_id_devuelve_fila_cuando_existe() -> None:
    row = {
        "id": "abc-123",
        "Voluntario": "Ana",
        "Email": "ana@example.com",
        "DNI": "12345678A",
        "activo": True,
    }

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [row])

    client, captured = _client_recording(_handler)
    result = get_voluntario_by_id(client, "abc-123")
    client.close()

    assert result is not None
    assert result.id == "abc-123"
    assert result.Voluntario == "Ana"
    assert result.DNI == "12345678A"
    assert captured[0]["params"] == ["abc-123"]
    assert "WHERE id = $1" in captured[0]["query"]


def test_get_voluntario_by_id_devuelve_None_si_no_existe() -> None:
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [])

    client, _ = _client_recording(_handler)
    result = get_voluntario_by_id(client, "no-such-id")
    client.close()

    assert result is None


# --- list_roles ----------------------------------------------------------


def test_list_roles_devuelve_los_roles_del_voluntario() -> None:
    rows = [
        {"tipo_rol": "intake"},
        {"tipo_rol": "salud"},
        {"tipo_rol": "seguimiento"},
    ]

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, rows)

    client, captured = _client_recording(_handler)
    result = list_roles(client, "abc-123")
    client.close()

    assert result == ["intake", "salud", "seguimiento"]
    assert captured[0]["params"] == ["abc-123"]
    assert "FROM roles_voluntario" in captured[0]["query"]


def test_list_roles_devuelve_lista_vacia_sin_roles() -> None:
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [])

    client, _ = _client_recording(_handler)
    result = list_roles(client, "abc-123")
    client.close()

    assert result == []
