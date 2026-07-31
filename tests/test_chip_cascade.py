"""Tests para el cambio de chip en cascada (issue #29, LIFECYCLE-04).

TDD: RED primero.

El servicio ``change_animal_chip`` es un saga que:
1. Valida que new_chip no este asignado a otro animal.
2. Valida que old_chip coincide con el chip actual del animal.
3. Actualiza las 6 tablas en cascada atomica (BEGIN/COMMIT/ROLLBACK).
4. Inserta el evento ``CHIP_CHANGED`` en ``animal_lifecycle_events``.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from app.core.insforge import InsForgeClient


def _json_response(status: int, body: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


# =============================================================================
# HAPPY PATH — chip cambiado, cascade a 6 tablas
# =============================================================================


def test_chip_change_cascades_to_all_six_tables():
    """Cuando el chip cambia, las 6 tablas se actualizan atomicamente."""
    from app.modules.animals.service import change_animal_chip

    captured_queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_queries.append(request.content.decode("utf-8"))
        body = json.loads(request.content.decode("utf-8"))
        query = body.get("query", "").lower()
        params: list[Any] = body.get("params", [])

        # uniqueness: no other animal has new_chip=222
        if "select id from animals where nchip" in query and params == ["222", "a1"]:
            return _json_response(200, {"rows": [], "rowCount": 0, "fields": []})

        # get current chip: animal exists, chip="111"
        if "select nchip from animals where id" in query and params == ["a1"]:
            return _json_response(200, {"rows": [{"NCHIP": "111"}], "rowCount": 1, "fields": []})

        # UPDATE entradas: 2 rows affected
        if "update entradas set chip" in query and params == ["222", "111"]:
            return _json_response(200, {"rows": [{"id": "e1"}, {"id": "e2"}], "rowCount": 2, "fields": []})

        # UPDATE acogidas: 1 row
        if "update acogidas set chip" in query and params == ["222", "111"]:
            return _json_response(200, {"rows": [{"id": "ac1"}], "rowCount": 1, "fields": []})

        # UPDATE actuaciones_sanitarias: 3 rows
        if "update actuaciones_sanitarias set chip" in query and params == ["222", "111"]:
            return _json_response(200, {"rows": [{"id": "as1"}, {"id": "as2"}, {"id": "as3"}], "rowCount": 3, "fields": []})

        # UPDATE terapias: 1 row
        if "update terapias set chip" in query and params == ["222", "111"]:
            return _json_response(200, {"rows": [{"id": "t1"}], "rowCount": 1, "fields": []})

        # default: empty DML (BEGIN, COMMIT, UPDATE animals, INSERT event, adopciones)
        return _json_response(200, {"rows": [], "rowCount": 0, "fields": []})

    transport = httpx.MockTransport(handler)
    client = InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=transport,
    )

    result = change_animal_chip(
        client,
        animal_id="a1",
        old_chip="111",
        new_chip="222",
        reason="Chip fisico reemplazado",
        operador_user_id="user-1",
    )

    assert result.success is True
    assert result.old_chip == "111"
    assert result.new_chip == "222"
    assert result.updated_tables["animals"] == 0  # empty RETURNING
    assert result.updated_tables["entradas"] == 2
    assert result.updated_tables["acogidas"] == 1
    assert result.updated_tables["adopciones"] == 0
    assert result.updated_tables["actuaciones_sanitarias"] == 3
    assert result.updated_tables["terapias"] == 1

    all_q = " ".join(captured_queries).upper()
    assert "BEGIN" in all_q
    assert "COMMIT" in all_q
    assert "ROLLBACK" not in all_q


def test_chip_change_returns_false_when_new_chip_already_assigned():
    """409-equivalente: si new_chip ya pertenece a otro animal, no se modifica nada."""
    from app.modules.animals.service import change_animal_chip

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        query = body.get("query", "").lower()
        params: list[Any] = body.get("params", [])
        # uniqueness: another animal already has new_chip
        if "select id from animals where nchip" in query and params == ["222", "a1"]:
            return _json_response(200, {"rows": [{"id": "other-animal"}], "rowCount": 1, "fields": []})
        return _json_response(200, {"rows": [], "rowCount": 0, "fields": []})

    transport = httpx.MockTransport(handler)
    client = InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=transport,
    )

    result = change_animal_chip(
        client,
        animal_id="a1",
        old_chip="111",
        new_chip="222",
        reason="Replacement",
        operador_user_id="user-1",
    )

    assert result.success is False
    assert "ya esta asignado" in result.error


def test_chip_change_returns_false_when_old_chip_mismatch():
    """422-equivalente: si old_chip no coincide, no se modifica nada."""
    from app.modules.animals.service import change_animal_chip

    call_count = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        call_count[0] += 1
        body = json.loads(request.content.decode("utf-8"))
        query = body.get("query", "").lower()
        # uniqueness: no conflict
        if "select id from animals where nchip" in query:
            return _json_response(200, {"rows": [], "rowCount": 0, "fields": []})
        # animal exists but chip is "333", not "111"
        if "select nchip from animals where id" in query:
            return _json_response(200, {"rows": [{"NCHIP": "333"}], "rowCount": 1, "fields": []})
        return _json_response(200, {"rows": [], "rowCount": 0, "fields": []})

    transport = httpx.MockTransport(handler)
    client = InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=transport,
    )

    result = change_animal_chip(
        client,
        animal_id="a1",
        old_chip="111",  # mismatched!
        new_chip="222",
        reason="Replacement",
        operador_user_id="user-1",
    )

    assert result.success is False
    assert "333" in result.error or "no coincide" in result.error.lower()
    # Only 2 pre-flight calls — no BEGIN
    assert call_count[0] == 2


def test_chip_change_rollback_on_table_failure():
    """Si una tabla falla, todas las demas se revierten (ROLLBACK)."""
    from app.modules.animals.service import change_animal_chip

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        query = body.get("query", "").lower()
        # uniqueness
        if "select id from animals where nchip" in query:
            return _json_response(200, {"rows": [], "rowCount": 0, "fields": []})
        # get current chip
        if "select nchip from animals where id" in query:
            return _json_response(200, {"rows": [{"NCHIP": "111"}], "rowCount": 1, "fields": []})
        # UPDATE entradas → InsForge error
        if "update entradas set chip" in query:
            return _json_response(409, {"message": "foreign_key_violation"})
        return _json_response(200, {"rows": [], "rowCount": 0, "fields": []})

    transport = httpx.MockTransport(handler)
    client = InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=transport,
    )

    result = change_animal_chip(
        client,
        animal_id="a1",
        old_chip="111",
        new_chip="222",
        reason="Replacement",
        operador_user_id="user-1",
    )

    assert result.success is False
    assert "Error en la transaccion" in result.error


def test_chip_change_validates_empty_fields():
    """new_chip vacio o igual a old_chip levanta ValueError antes de SQL."""
    from app.modules.animals.service import change_animal_chip

    mock_client = MagicMock()

    # empty new_chip
    with pytest.raises(ValueError, match="new_chip"):
        change_animal_chip(
            mock_client,
            animal_id="a1",
            old_chip="111",
            new_chip="",
            reason="Replacement",
            operador_user_id="user-1",
        )

    # same as old
    with pytest.raises(ValueError, match="new_chip"):
        change_animal_chip(
            mock_client,
            animal_id="a1",
            old_chip="111",
            new_chip="111",
            reason="Replacement",
            operador_user_id="user-1",
        )

    # empty reason
    with pytest.raises(ValueError, match="reason"):
        change_animal_chip(
            mock_client,
            animal_id="a1",
            old_chip="111",
            new_chip="222",
            reason="",
            operador_user_id="user-1",
        )
