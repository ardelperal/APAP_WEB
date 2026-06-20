"""Tests del service layer de animales (TDD estricto).

El service es la unica capa que habla con ``InsForgeClient`` para
animales. Lo ejercitamos con un ``InsForgeClient`` real conectado a
``httpx.MockTransport`` para capturar SQL y params sin red.

El contrato es: ``create_animal`` valida campos antes de SQL y devuelve
``Animal``; ``list_animals`` devuelve activos ordenados por fecha_alta
DESC; ``get_animal_by_id`` devuelve el animal o ``None``. NCHIP
duplicado propaga el ``InsForgeError`` de InsForge sin cambios.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.core.insforge import InsForgeClient, InsForgeError
from app.modules.animals.service import (
    Especie,
    Sexo,
    create_animal,
    get_animal_by_id,
    list_animals,
)

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


def _params_minimal() -> dict[str, Any]:
    """Parametros validos para el happy path (solo los 5 obligatorios)."""
    return {
        "NCHIP": "985112004409871",
        "NombreAnimal": "Luna",
        "Especie": "CANINA",
        "Sexo": "H",
        "FNacimiento": "2023-04-12",
    }


# --- create_animal --------------------------------------------------------


def test_create_animal_ejecuta_insert_con_parametros_esperados() -> None:
    """El INSERT contiene los 5 campos obligatorios en el orden correcto."""
    returned = {
        "id": "11111111-1111-1111-1111-111111111111",
        "NCHIP": "985112004409871",
        "NombreAnimal": "Luna",
        "Especie": "CANINA",
        "Sexo": "H",
        "FNacimiento": "2023-04-12",
        "activo": True,
    }

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [returned])

    client, captured = _client_recording(_handler)
    result = create_animal(client, _params_minimal())
    client.close()

    assert result.id == returned["id"]
    assert result.NCHIP == "985112004409871"
    assert result.NombreAnimal == "Luna"
    assert result.Especie is Especie.CANINA
    assert result.Sexo is Sexo.H

    assert len(captured) == 1
    query = captured[0]["query"]
    assert "INSERT INTO animales" in query
    assert "RETURNING" in query
    params = captured[0]["params"]
    assert params[0] == "985112004409871"
    assert params[1] == "Luna"
    assert params[2] == "CANINA"
    assert params[3] == "H"
    assert params[4] == "2023-04-12"


def test_create_animal_rechaza_Especie_invalida_antes_de_sql() -> None:
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    with pytest.raises(ValueError, match="Especie"):
        create_animal(client, {**_params_minimal(), "Especie": "REPTIL"})
    client.close()

    assert captured == [], "no se debe emitir SQL si la validacion falla"


def test_create_animal_rechaza_Sexo_invalido_antes_de_sql() -> None:
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    with pytest.raises(ValueError, match="Sexo"):
        create_animal(client, {**_params_minimal(), "Sexo": "X"})
    client.close()

    assert captured == []


def test_create_animal_rechaza_NCHIP_vacio() -> None:
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    with pytest.raises(ValueError, match="NCHIP"):
        create_animal(client, {**_params_minimal(), "NCHIP": "   "})
    client.close()

    assert captured == []


def test_create_animal_rechaza_NombreAnimal_vacio() -> None:
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    with pytest.raises(ValueError, match="NombreAnimal"):
        create_animal(client, {**_params_minimal(), "NombreAnimal": ""})
    client.close()

    assert captured == []


def test_create_animal_rechaza_FNacimiento_vacio() -> None:
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    with pytest.raises(ValueError, match="FNacimiento"):
        create_animal(client, {**_params_minimal(), "FNacimiento": ""})
    client.close()

    assert captured == []


def test_create_animal_propag_InsForgeError_en_NCHIP_duplicado() -> None:
    """Un 409 de InsForge (NCHIP duplicado) propaga el InsForgeError tal cual."""

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(
            409, {"error": "duplicate key value violates unique constraint"}
        )

    client, _ = _client_recording(_handler)

    with pytest.raises(InsForgeError) as exc:
        create_animal(client, _params_minimal())
    client.close()

    assert exc.value.status_code == 409


def test_create_animal_acepta_todos_los_campos_opcionales() -> None:
    """El INSERT incluye los 19 campos opcionales, con NULL para los no provistos."""
    returned = {
        "id": "22222222-2222-2222-2222-222222222222",
        "NCHIP": "985112004409999",
        "NombreAnimal": "Mishi",
        "Especie": "FELINA",
        "Sexo": "M",
        "FNacimiento": "2024-01-15",
        "activo": True,
    }

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [returned])

    client, captured = _client_recording(_handler)
    create_animal(
        client,
        {
            **_params_minimal(),
            "NCHIP": "985112004409999",
            "NombreAnimal": "Mishi",
            "Especie": "FELINA",
            "Sexo": "M",
            "FNacimiento": "2024-01-15",
            "TraeNChip": "Si",
            "FIMPLANTACIONCHIP": "2024-01-20",
            "Raza": "Comun europeo",
            "Color": "Negro",
            "Pelo": "Corto",
            "Tamano": "Mediano",
            "Caracter": "Tranquilo",
            "FDefuncion": None,
            "Terapia": None,
            "Observaciones": "Sin observaciones",
            "NombreFoto": "mishi.jpg",
            "Cartilla": "Si",
            "Eutanasia": "No",
            "RazaPPP": "No",
            "Mestizo": "Si",
            "EutanasiaOtrasCausas": None,
            "EutanasiaEnfermedad": None,
            "UltimoEstadoAntesDeFallecido": None,
            "ComunicacionARIAC": "No",
        },
    )
    client.close()

    assert len(captured) == 1
    query = captured[0]["query"]
    # El INSERT debe listar los 24 campos de insercion (5 obligatorios + 19 opcionales)
    for col in (
        "NCHIP",
        "NombreAnimal",
        "Especie",
        "Sexo",
        "FNacimiento",
        "TraeNChip",
        "FIMPLANTACIONCHIP",
        "Raza",
        "Color",
        "Pelo",
        "Tamano",
        "Caracter",
        "FDefuncion",
        "Terapia",
        "Observaciones",
        "NombreFoto",
        "Cartilla",
        "Eutanasia",
        "RazaPPP",
        "Mestizo",
        "EutanasiaOtrasCausas",
        "EutanasiaEnfermedad",
        "UltimoEstadoAntesDeFallecido",
        "ComunicacionARIAC",
    ):
        assert col in query, f"falta columna {col} en el INSERT"
    params = captured[0]["params"]
    assert params[0] == "985112004409999"  # NCHIP
    assert params[5] == "Si"               # TraeNChip
    assert params[6] == "2024-01-20"       # FIMPLANTACIONCHIP
    assert params[7] == "Comun europeo"   # Raza


# --- list_animals ---------------------------------------------------------


def test_list_animals_ejecuta_select_y_devuelve_filas() -> None:
    rows = [
        {
            "id": "aaa",
            "NCHIP": "1",
            "NombreAnimal": "Luna",
            "Especie": "CANINA",
            "Sexo": "H",
            "FNacimiento": "2023-04-12",
            "activo": True,
        },
        {
            "id": "bbb",
            "NCHIP": "2",
            "NombreAnimal": "Mishi",
            "Especie": "FELINA",
            "Sexo": "M",
            "FNacimiento": "2024-01-15",
            "activo": True,
        },
    ]

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, rows)

    client, captured = _client_recording(_handler)
    result = list_animals(client)
    client.close()

    assert [r.id for r in result] == ["aaa", "bbb"]
    assert [r.NombreAnimal for r in result] == ["Luna", "Mishi"]

    assert len(captured) == 1
    query = captured[0]["query"]
    assert "SELECT" in query
    assert "FROM animales" in query
    assert "ORDER BY fecha_alta DESC" in query
    assert "WHERE activo = true" in query


def test_list_animals_devuelve_lista_vacia_sin_filas() -> None:
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [])

    client, _ = _client_recording(_handler)
    result = list_animals(client)
    client.close()

    assert result == []


# --- get_animal_by_id -----------------------------------------------------


def test_get_animal_by_id_devuelve_fila_cuando_existe() -> None:
    row = {
        "id": "abc-123",
        "NCHIP": "1",
        "NombreAnimal": "Luna",
        "Especie": "CANINA",
        "Sexo": "H",
        "FNacimiento": "2023-04-12",
        "activo": True,
    }

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [row])

    client, captured = _client_recording(_handler)
    result = get_animal_by_id(client, "abc-123")
    client.close()

    assert result is not None
    assert result.id == "abc-123"
    assert result.NCHIP == "1"
    assert captured[0]["params"] == ["abc-123"]
    assert "WHERE id = $1" in captured[0]["query"]


def test_get_animal_by_id_devuelve_None_si_no_existe() -> None:
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [])

    client, _ = _client_recording(_handler)
    result = get_animal_by_id(client, "no-such-id")
    client.close()

    assert result is None
