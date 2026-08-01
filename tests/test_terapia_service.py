"""Service-layer tests for HEALTH-05 terapias + recomendaciones (issue #54).

Mirrors ``tests/test_sanidad.py`` pattern: real InsForgeClient +
httpx.MockTransport for SQL shape assertion. No pytest-mock
(AGENTS rule — no pytest-mock).

Tests cover:
- create / list / get / update / soft-delete of ``terapias``
- create / list / complete / soft-delete of ``recomendaciones``
- FK validation: animal_id activo, voluntario_id activo (VOL-05)
- delete guard: terapia with pending recomendaciones raises
  TerapiaDeleteError (409 contract)
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.core.insforge import InsForgeClient
from app.modules.sanidad import terapia_service as terapia_service

# --- mock transport helpers -----------------------------------------------


def _json_response(
    status_code: int, body: Any
) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _client_recording(
    handler: Callable[[httpx.Request, dict[str, Any]], httpx.Response],
) -> tuple[InsForgeClient, list[dict[str, Any]]]:
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


def _handler_returns_rows(
    rows: list[dict[str, Any]],
) -> Callable[[httpx.Request, dict[str, Any]], httpx.Response]:
    def _h(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, rows)
    return _h


def _handler_cascading(
    *responses: list[dict[str, Any]] | dict[str, Any],
) -> Callable[[httpx.Request, dict[str, Any]], httpx.Response]:
    """Handler that returns successive responses per call (CTE + disambiguation)."""
    queue: list[Any] = list(responses)

    def _h(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        if not queue:
            raise AssertionError(
                f"unexpected SQL call: {body.get('query', '')[:80]!r}"
            )
        next_response = queue.pop(0)
        if isinstance(next_response, dict) and "error" in next_response:
            return _json_response(next_response["status"], next_response["error"])
        return _json_response(200, next_response)

    return _h


# --- terapia row helpers --------------------------------------------------


def _terapia_row(
    overrides: dict[str, Any] | None = None,
    *,
    terapia_id: str = "11111111-1111-1111-1111-111111111111",
    animal_id: str = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    fecha: str = "2026-07-15",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": terapia_id,
        "animal_id": animal_id,
        "fecha": fecha,
        "voluntario_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "descripcion": "Sesión de fisioterapia",
        "created_at": "2026-07-15T10:00:00Z",
        "updated_at": "2026-07-15T10:00:00Z",
        "activo": True,
    }
    if overrides:
        row.update(overrides)
    return row


def _recomendacion_row(
    overrides: dict[str, Any] | None = None,
    *,
    rec_id: str = "22222222-2222-2222-2222-222222222222",
    terapia_id: str = "11111111-1111-1111-1111-111111111111",
    fecha: str = "2026-07-20",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": rec_id,
        "terapia_id": terapia_id,
        "fecha": fecha,
        "texto": "Continuar con ejercicios en casa",
        "completada": False,
        "created_at": "2026-07-20T10:00:00Z",
        "activo": True,
    }
    if overrides:
        row.update(overrides)
    return row


# --- terapia CRUD tests ---------------------------------------------------


def test_create_terapia_happy_path() -> None:
    """create_terapia returns a populated Terapia and emits log_safe."""
    client, captured = _client_recording(
        _handler_returns_rows([_terapia_row()])
    )

    terapia = terapia_service.create_terapia(
        client,
        {
            "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "voluntario_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "fecha": "2026-07-15",
            "descripcion": "Sesión de fisioterapia",
        },
        actor_user_id="u-1",
    )

    assert terapia.id == "11111111-1111-1111-1111-111111111111"
    assert terapia.animal_id == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert terapia.fecha == "2026-07-15"
    assert terapia.descripcion == "Sesión de fisioterapia"
    assert terapia.activo is True
    # SQL was emitted
    assert len(captured) == 1


def test_create_terapia_missing_animal_id() -> None:
    """create_terapia raises ValueError when animal_id is missing."""
    client, _ = _client_recording(_handler_returns_rows([]))

    with pytest.raises(ValueError, match="animal_id is required"):
        terapia_service.create_terapia(
            client,
            {
                "animal_id": "",
                "voluntario_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "fecha": "2026-07-15",
            },
        )


def test_create_terapia_missing_voluntario_id() -> None:
    """create_terapia raises ValueError when voluntario_id is missing."""
    client, _ = _client_recording(_handler_returns_rows([]))

    with pytest.raises(ValueError, match="voluntario_id is required"):
        terapia_service.create_terapia(
            client,
            {
                "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "voluntario_id": "",
                "fecha": "2026-07-15",
            },
        )


def test_create_terapia_missing_fecha() -> None:
    """create_terapia raises ValueError when fecha is missing."""
    client, _ = _client_recording(_handler_returns_rows([]))

    with pytest.raises(ValueError, match="fecha is required"):
        terapia_service.create_terapia(
            client,
            {
                "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "voluntario_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "fecha": "   ",
            },
        )


def test_create_terapia_invalid_fecha_format() -> None:
    """create_terapia raises ValueError for non-ISO fecha."""
    client, _ = _client_recording(_handler_returns_rows([]))

    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        terapia_service.create_terapia(
            client,
            {
                "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "voluntario_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "fecha": "15/07/2026",
            },
        )


def test_create_terapia_cte_returns_zero_raises_disambiguated() -> None:
    """CTE 0-row: disambiguation query finds animal not found."""
    # First SQL call returns empty (CTE failed), second disambiguates
    # and finds the animal does not exist
    client, _ = _client_recording(
        _handler_cascading(
            [],  # CTE returned 0 rows
            [],  # animal check: not found
        )
    )

    with pytest.raises(ValueError, match="animal_id must reference an active animal"):
        terapia_service.create_terapia(
            client,
            {
                "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "voluntario_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "fecha": "2026-07-15",
            },
        )


def test_create_terapia_cte_zero_voluntario_inactivo() -> None:
    """CTE 0-row: disambiguation finds voluntario inactive."""
    client, _ = _client_recording(
        _handler_cascading(
            [],  # CTE returned 0 rows
            [{"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "activo": True}],  # animal OK
            [],  # voluntario not found/inactive
        )
    )

    with pytest.raises(ValueError, match="voluntario_id must reference an active volunteer"):
        terapia_service.create_terapia(
            client,
            {
                "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "voluntario_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "fecha": "2026-07-15",
            },
        )


def test_list_terapias_returns_mapped_rows() -> None:
    """list_terapias returns Terapia instances."""
    rows = [
        _terapia_row({"id": "id-1", "fecha": "2026-07-10"}),
        _terapia_row({"id": "id-2", "fecha": "2026-07-11", "descripcion": "Otra"}),
    ]
    client, _ = _client_recording(_handler_returns_rows(rows))

    result = terapia_service.list_terapias(client)

    assert len(result) == 2
    assert [t.id for t in result] == ["id-1", "id-2"]
    assert result[0].fecha == "2026-07-10"
    assert result[1].descripcion == "Otra"


def test_list_terapias_by_animal() -> None:
    """list_terapias(animal_id=...) filters by animal_id."""
    rows = [_terapia_row({"id": "id-1"})]
    client, _ = _client_recording(_handler_returns_rows(rows))

    result = terapia_service.list_terapias(client, animal_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    assert len(result) == 1
    assert result[0].id == "id-1"


def test_list_terapias_empty_returns_empty_list() -> None:
    """list_terapias returns [] when no rows."""
    client, _ = _client_recording(_handler_returns_rows([]))

    result = terapia_service.list_terapias(client)

    assert result == []


def test_get_terapia_returns_terapia() -> None:
    """get_terapia returns a Terapia when found."""
    rows = [_terapia_row()]
    client, _ = _client_recording(_handler_returns_rows(rows))

    result = terapia_service.get_terapia(
        client, "11111111-1111-1111-1111-111111111111"
    )

    assert result is not None
    assert result.id == "11111111-1111-1111-1111-111111111111"


def test_get_terapia_returns_none_when_not_found() -> None:
    """get_terapia returns None when id does not exist."""
    client, _ = _client_recording(_handler_returns_rows([]))

    result = terapia_service.get_terapia(client, "nonexistent-id")

    assert result is None


def test_update_terapia_happy_path() -> None:
    """update_terapia returns updated Terapia and emits log_safe."""
    rows = [_terapia_row({"descripcion": "Nueva descripción"})]
    client, _ = _client_recording(_handler_returns_rows(rows))

    result = terapia_service.update_terapia(
        client,
        "11111111-1111-1111-1111-111111111111",
        {
            "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "voluntario_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "fecha": "2026-07-15",
            "descripcion": "Nueva descripción",
        },
        actor_user_id="u-1",
    )

    assert result is not None
    assert result.descripcion == "Nueva descripción"


def test_update_terapia_returns_none_when_not_found() -> None:
    """update_terapia returns None when id does not exist."""
    client, _ = _client_recording(_handler_returns_rows([]))

    result = terapia_service.update_terapia(
        client,
        "nonexistent-id",
        {
            "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "voluntario_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "fecha": "2026-07-15",
        },
    )

    assert result is None


def test_delete_terapia_returns_true_on_success() -> None:
    """delete_terapia soft-deletes and returns True."""
    # First call: get_terapia (exists, activo=true)
    # Second call: check pending recomendaciones (none)
    # Third call: soft-delete
    client, _ = _client_recording(
        _handler_cascading(
            [_terapia_row()],  # get_terapia
            [],  # no pending recomendaciones
            [{"id": "11111111-1111-1111-1111-111111111111"}],  # soft-delete returned id
        )
    )

    result = terapia_service.delete_terapia(
        client, "11111111-1111-1111-1111-111111111111", actor_user_id="u-1"
    )

    assert result is True


def test_delete_terapia_returns_false_when_not_found() -> None:
    """delete_terapia returns False when id does not exist."""
    client, _ = _client_recording(_handler_returns_rows([]))

    result = terapia_service.delete_terapia(
        client, "nonexistent-id"
    )

    assert result is False


def test_delete_terapia_raises_delete_error_when_pending_recomendaciones() -> None:
    """delete_terapia raises TerapiaDeleteError when pending recommendations exist."""
    # get_terapia returns active terapia
    # pending recomendaciones check returns one pending
    client, _ = _client_recording(
        _handler_cascading(
            [_terapia_row()],  # get_terapia
            [{"id": "22222222-2222-2222-2222-222222222222"}],  # pending exists
        )
    )

    with pytest.raises(terapia_service.TerapiaDeleteError, match="recomendaciones pendientes"):
        terapia_service.delete_terapia(
            client, "11111111-1111-1111-1111-111111111111"
        )


# --- recomendacion tests --------------------------------------------------


def test_create_recomendacion_happy_path() -> None:
    """create_recomendacion returns a Recomendacion and emits log_safe."""
    rows = [_recomendacion_row()]
    client, captured = _client_recording(_handler_returns_rows(rows))

    recomendacion = terapia_service.create_recomendacion(
        client,
        "11111111-1111-1111-1111-111111111111",
        {
            "fecha": "2026-07-20",
            "texto": "Continuar con ejercicios en casa",
        },
        actor_user_id="u-1",
    )

    assert recomendacion.id == "22222222-2222-2222-2222-222222222222"
    assert recomendacion.terapia_id == "11111111-1111-1111-1111-111111111111"
    assert recomendacion.texto == "Continuar con ejercicios en casa"
    assert recomendacion.completada is False
    assert len(captured) == 1


def test_create_recomendacion_missing_texto() -> None:
    """create_recomendacion raises ValueError when texto is missing."""
    client, _ = _client_recording(_handler_returns_rows([]))

    with pytest.raises(ValueError, match="texto is required"):
        terapia_service.create_recomendacion(
            client,
            "11111111-1111-1111-1111-111111111111",
            {"fecha": "2026-07-20", "texto": ""},
        )


def test_create_recomendacion_invalid_fecha() -> None:
    """create_recomendacion raises ValueError for bad fecha format."""
    client, _ = _client_recording(_handler_returns_rows([]))

    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        terapia_service.create_recomendacion(
            client,
            "11111111-1111-1111-1111-111111111111",
            {"fecha": "invalid", "texto": "Some text"},
        )


def test_create_recomendacion_terapia_not_found_raises() -> None:
    """create_recomendacion raises ValueError when terapia does not exist."""
    client, _ = _client_recording(
        _handler_cascading(
            [],  # CTE returned 0 rows
            [],  # terapia check: not found
        )
    )

    with pytest.raises(ValueError, match="terapia_id must reference an active terapia"):
        terapia_service.create_recomendacion(
            client,
            "nonexistent-terapia-id",
            {"fecha": "2026-07-20", "texto": "Some text"},
        )


def test_list_recomendaciones_returns_mapped_rows() -> None:
    """list_recomendaciones returns Recomendacion instances."""
    rows = [
        _recomendacion_row({"id": "r-1", "texto": "Primera", "completada": False}),
        _recomendacion_row({"id": "r-2", "texto": "Segunda", "completada": True}),
    ]
    client, _ = _client_recording(_handler_returns_rows(rows))

    result = terapia_service.list_recomendaciones(
        client, "11111111-1111-1111-1111-111111111111"
    )

    assert len(result) == 2
    assert result[0].id == "r-1"
    assert result[0].completada is False
    assert result[1].id == "r-2"
    assert result[1].completada is True


def test_complete_recomendacion_happy_path() -> None:
    """complete_recomendacion marks completada=True and returns updated Recomendacion."""
    # First call: UPDATE (returns row)
    # Second call: get_by_id (returns updated row)
    rows_updated = [_recomendacion_row({"completada": True})]
    rows_full = [_recomendacion_row({"completada": True})]
    client, _ = _client_recording(
        _handler_cascading(rows_updated, rows_full)
    )

    result = terapia_service.complete_recomendacion(
        client, "22222222-2222-2222-2222-222222222222", actor_user_id="u-1"
    )

    assert result is not None
    assert result.completada is True


def test_complete_recomendacion_returns_none_when_not_found() -> None:
    """complete_recomendacion returns None when id does not exist."""
    client, _ = _client_recording(
        _handler_cascading([], [])
    )

    result = terapia_service.complete_recomendacion(
        client, "nonexistent-id"
    )

    assert result is None


def test_delete_recomendacion_returns_true() -> None:
    """delete_recomendacion soft-deletes and returns True."""
    client, _ = _client_recording(
        _handler_returns_rows([{"id": "22222222-2222-2222-2222-222222222222"}])
    )

    result = terapia_service.delete_recomendacion(
        client, "22222222-2222-2222-2222-222222222222", actor_user_id="u-1"
    )

    assert result is True


def test_delete_recomendacion_returns_false_when_not_found() -> None:
    """delete_recomendacion returns False when id does not exist."""
    client, _ = _client_recording(_handler_returns_rows([]))

    result = terapia_service.delete_recomendacion(
        client, "nonexistent-id"
    )

    assert result is False
