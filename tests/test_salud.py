"""Service-layer tests for HEALTH-04 salud (CRUD).

The ``salud.service`` module owns:
- create / list / get / update / soft-delete of ``terapias``
- create / list / complete / soft-delete of ``recomendaciones``
- VOL-05 validation: voluntario must be activo
- Delete restriction: cannot delete terapia with pending recommendations

Mirror of ``tests/test_sanidad.py``: real InsForgeClient
+ httpx.MockTransport for SQL shape assertion.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.core.insforge import InsForgeClient
from app.modules.salud import service as salud_service


def _json_response(status_code: int, body: Any) -> httpx.Response:
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


def _terapia_row(
    overrides: dict[str, Any] | None = None,
    *,
    terapia_id: str = "11111111-1111-1111-1111-111111111111",
    animal_id: str = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    vol_id: str = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    fecha: str = "2026-07-04",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": terapia_id,
        "animal_id": animal_id,
        "voluntario_id": vol_id,
        "fecha": fecha,
        "descripcion": "Sesión de fisioterapia",
        "created_at": "2026-07-04T10:00:00Z",
        "updated_at": "2026-07-04T10:00:00Z",
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
    fecha: str = "2026-07-04",
    completada: bool = False,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": rec_id,
        "terapia_id": terapia_id,
        "fecha": fecha,
        "texto": "Aplicar hielo 20 min/día",
        "completada": completada,
        "created_at": "2026-07-04T10:00:00Z",
        "activo": True,
    }
    if overrides:
        row.update(overrides)
    return row


# --- Terapia happy path -----------------------------------------------------


def test_create_terapia_happy_path() -> None:
    """create_terapia returns a Terapia and emits log_safe."""
    client, captured = _client_recording(
        _handler_returns_rows([_terapia_row()])
    )
    params = {
        "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "voluntario_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "fecha": "2026-07-04",
        "descripcion": "Sesión de fisioterapia",
    }
    terapia = salud_service.create_terapia(client, params, actor_user_id="u-1")
    assert terapia.id == "11111111-1111-1111-1111-111111111111"
    assert terapia.animal_id == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert terapia.voluntario_id == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert terapia.fecha == "2026-07-04"
    assert terapia.descripcion == "Sesión de fisioterapia"
    assert terapia.activo is True
    # SQL was emitted with correct params
    assert len(captured) == 1
    params_sent = captured[0]["params"]
    assert params_sent[0] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # animal_id
    assert params_sent[1] == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # vol_id
    assert params_sent[2] == "2026-07-04"  # fecha


def test_create_terapia_minimal() -> None:
    """create_terapia works with only required fields."""
    client, _ = _client_recording(
        _handler_returns_rows([_terapia_row({"descripcion": None})])
    )
    params = {
        "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "voluntario_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "fecha": "2026-07-04",
    }
    terapia = salud_service.create_terapia(client, params)
    assert terapia.descripcion is None


def test_create_terapia_missing_animal_id_raises() -> None:
    """create_terapia raises ValueError when animal_id is missing."""
    client, _ = _client_recording(_handler_returns_rows([]))
    params = {
        "animal_id": "",
        "voluntario_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "fecha": "2026-07-04",
    }
    with pytest.raises(ValueError, match="animal_id is required"):
        salud_service.create_terapia(client, params)


def test_create_terapia_missing_voluntario_id_raises() -> None:
    """create_terapia raises ValueError when voluntario_id is missing."""
    client, _ = _client_recording(_handler_returns_rows([]))
    params = {
        "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "voluntario_id": "",
        "fecha": "2026-07-04",
    }
    with pytest.raises(ValueError, match="voluntario_id is required"):
        salud_service.create_terapia(client, params)


def test_create_terapia_missing_fecha_raises() -> None:
    """create_terapia raises ValueError when fecha is missing."""
    client, _ = _client_recording(_handler_returns_rows([]))
    params = {
        "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "voluntario_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "fecha": "",
    }
    with pytest.raises(ValueError, match="fecha is required"):
        salud_service.create_terapia(client, params)


def test_create_terapia_cte_failure_disambiguates_animal_not_found() -> None:
    """CTE 0-row: service runs disambiguation and raises animal not found."""
    # CTE returns [] → disambiguation runs: animal not found
    client, _ = _client_recording(_handler_cascading(
        [],  # CTE returns nothing
        [],  # disambiguation: animal SELECT returns nothing
    ))
    params = {
        "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "voluntario_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "fecha": "2026-07-04",
    }
    with pytest.raises(ValueError, match="animal_id debe apuntar"):
        salud_service.create_terapia(client, params)


def test_create_terapia_cte_failure_disambiguates_voluntario_inactivo() -> None:
    """CTE 0-row: service runs disambiguation and raises voluntario inactivo."""
    # CTE → [], disambiguation: animal found but vol not activo
    client, _ = _client_recording(_handler_cascading(
        [],
        [{"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "activo": True}],  # animal
        [],  # vol SELECT → not found
    ))
    params = {
        "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "voluntario_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "fecha": "2026-07-04",
    }
    with pytest.raises(ValueError, match="voluntario_id debe apuntar"):
        salud_service.create_terapia(client, params)


def test_create_terapia_cte_failure_disambiguates_voluntario_inactivo_v2() -> None:
    """CTE 0-row: disambiguation finds vol exists but is activo=false."""
    client, _ = _client_recording(_handler_cascading(
        [],
        [{"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "activo": True}],
        [{"id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "activo": False}],
    ))
    params = {
        "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "voluntario_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "fecha": "2026-07-04",
    }
    with pytest.raises(ValueError, match="voluntario_id debe apuntar"):
        salud_service.create_terapia(client, params)


def test_list_terapias_returns_mapped() -> None:
    """list_terapias returns list of Terapia instances."""
    rows = [
        _terapia_row({"id": "id-1", "fecha": "2026-07-01"}),
        _terapia_row({"id": "id-2", "fecha": "2026-07-02"}),
    ]
    client, _ = _client_recording(_handler_returns_rows(rows))
    result = salud_service.list_terapias(client)
    assert len(result) == 2
    assert [t.id for t in result] == ["id-1", "id-2"]
    assert [t.fecha for t in result] == ["2026-07-01", "2026-07-02"]


def test_list_terapias_by_animal() -> None:
    """list_terapias with animal_id filters correctly."""
    rows = [_terapia_row({"id": "id-1", "animal_id": "ccccccccc-cccc-cccc-cccc-cccccccccc"})]
    client, _ = _client_recording(_handler_returns_rows(rows))
    result = salud_service.list_terapias(client, animal_id="ccccccccc-cccc-cccc-cccc-cccccccccc")
    assert len(result) == 1
    assert result[0].id == "id-1"


def test_get_terapia_by_id_found() -> None:
    """get_terapia_by_id returns Terapia when found."""
    client, _ = _client_recording(_handler_returns_rows([_terapia_row()]))
    result = salud_service.get_terapia_by_id(client, "11111111-1111-1111-1111-111111111111")
    assert result is not None
    assert result.id == "11111111-1111-1111-1111-111111111111"


def test_get_terapia_by_id_not_found() -> None:
    """get_terapia_by_id returns None when not found."""
    client, _ = _client_recording(_handler_returns_rows([]))
    result = salud_service.get_terapia_by_id(client, "not-found")
    assert result is None


def test_update_terapia_happy_path() -> None:
    """update_terapia returns updated Terapia."""
    client, captured = _client_recording(
        _handler_returns_rows([_terapia_row({"descripcion": "Nueva descripción"})])
    )
    params = {
        "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "voluntario_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "fecha": "2026-07-05",
        "descripcion": "Nueva descripción",
    }
    terapia = salud_service.update_terapia(
        client, "11111111-1111-1111-1111-111111111111", params, actor_user_id="u-1"
    )
    assert terapia is not None
    assert terapia.descripcion == "Nueva descripción"
    assert len(captured) == 1
    params_sent = captured[0]["params"]
    assert params_sent[0] == "11111111-1111-1111-1111-111111111111"  # terapia_id


def test_update_terapia_not_found_returns_none() -> None:
    """update_terapia returns None when id does not exist."""
    # CTE returns [], disambiguation SELECT returns [] → None
    client, _ = _client_recording(_handler_cascading([], []))
    params = {
        "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "voluntario_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "fecha": "2026-07-05",
    }
    result = salud_service.update_terapia(client, "not-found", params)
    assert result is None


def test_delete_terapia_success() -> None:
    """delete_terapia returns True on success."""
    client, _ = _client_recording(
        _handler_returns_rows([{"id": "11111111-1111-1111-1111-111111111111"}])
    )
    result = salud_service.delete_terapia(client, "11111111-1111-1111-1111-111111111111")
    assert result is True


def test_delete_terapia_not_found_returns_false() -> None:
    """delete_terapia returns False when not found."""
    # CTE returns [], disambiguation: terapia doesn't exist → False
    client, _ = _client_recording(_handler_cascading([], []))
    result = salud_service.delete_terapia(client, "not-found")
    assert result is False


def test_delete_terapia_has_pending_recommendations_raises() -> None:
    """delete_terapia raises TerapiaHasPendingRecomendaciones when blocked."""
    # CTE returns [] (delete blocked by subquery), then get_terapia returns
    # the terapia row, then list_recomendaciones returns one pending
    client, _ = _client_recording(_handler_cascading(
        [],  # delete CTE 0 rows
        [_terapia_row()],  # get_terapia_by_id finds it
        [_recomendacion_row({"completada": False})],  # has pending
    ))
    with pytest.raises(salud_service.TerapiaHasPendingRecomendaciones):
        salud_service.delete_terapia(client, "11111111-1111-1111-1111-111111111111")


# --- Recomendacion tests ----------------------------------------------------


def test_create_recomendacion_happy_path() -> None:
    """create_recomendacion returns a Recomendacion and emits log_safe."""
    client, captured = _client_recording(
        _handler_returns_rows([_recomendacion_row()])
    )
    params = {
        "terapia_id": "11111111-1111-1111-1111-111111111111",
        "fecha": "2026-07-04",
        "texto": "Aplicar hielo 20 min/día",
    }
    rec = salud_service.create_recomendacion(client, params, actor_user_id="u-1")
    assert rec.id == "22222222-2222-2222-2222-222222222222"
    assert rec.terapia_id == "11111111-1111-1111-1111-111111111111"
    assert rec.texto == "Aplicar hielo 20 min/día"
    assert rec.completada is False
    assert len(captured) == 1


def test_create_recomendacion_missing_terapia_id_raises() -> None:
    """create_recomendacion raises ValueError when terapia_id is missing."""
    client, _ = _client_recording(_handler_returns_rows([]))
    params = {
        "terapia_id": "",
        "fecha": "2026-07-04",
        "texto": "texto",
    }
    with pytest.raises(ValueError, match="terapia_id is required"):
        salud_service.create_recomendacion(client, params)


def test_create_recomendacion_missing_texto_raises() -> None:
    """create_recomendacion raises ValueError when texto is missing."""
    client, _ = _client_recording(_handler_returns_rows([]))
    params = {
        "terapia_id": "11111111-1111-1111-1111-111111111111",
        "fecha": "2026-07-04",
        "texto": "",
    }
    with pytest.raises(ValueError, match="texto is required"):
        salud_service.create_recomendacion(client, params)


def test_create_recomendacion_cte_failure_terapia_not_found() -> None:
    """CTE 0-row: disambiguation raises terapia not found."""
    client, _ = _client_recording(_handler_cascading(
        [],
        [],  # disambiguation: terapia SELECT returns nothing
    ))
    params = {
        "terapia_id": "11111111-1111-1111-1111-111111111111",
        "fecha": "2026-07-04",
        "texto": "texto",
    }
    with pytest.raises(ValueError, match="terapia_id no existe"):
        salud_service.create_recomendacion(client, params)


def test_create_recomendacion_cte_failure_terapia_inactiva() -> None:
    """CTE 0-row: disambiguation raises terapia inactiva."""
    client, _ = _client_recording(_handler_cascading(
        [],
        [{"id": "11111111-1111-1111-1111-111111111111", "activo": False}],
    ))
    params = {
        "terapia_id": "11111111-1111-1111-1111-111111111111",
        "fecha": "2026-07-04",
        "texto": "texto",
    }
    with pytest.raises(ValueError, match="terapia_id no está activa"):
        salud_service.create_recomendacion(client, params)


def test_list_recomendaciones_returns_mapped() -> None:
    """list_recomendaciones returns list of Recomendacion."""
    rows = [
        _recomendacion_row({"id": "r-1", "texto": "Texto 1"}),
        _recomendacion_row({"id": "r-2", "completada": True}),
    ]
    client, _ = _client_recording(_handler_returns_rows(rows))
    result = salud_service.list_recomendaciones(
        client, "11111111-1111-1111-1111-111111111111"
    )
    assert len(result) == 2
    assert [r.id for r in result] == ["r-1", "r-2"]
    assert result[0].completada is False
    assert result[1].completada is True


def test_complete_recomendacion_happy_path() -> None:
    """complete_recomendacion returns updated Recomendacion with completada=True."""
    client, _ = _client_recording(
        _handler_returns_rows([_recomendacion_row({"completada": True})])
    )
    rec = salud_service.complete_recomendacion(
        client, "22222222-2222-2222-2222-222222222222", actor_user_id="u-1"
    )
    assert rec.completada is True


def test_complete_recomendacion_not_found_raises() -> None:
    """complete_recomendacion raises RecomendacionNotFoundError when not found."""
    client, _ = _client_recording(_handler_returns_rows([]))
    with pytest.raises(salud_service.RecomendacionNotFoundError):
        salud_service.complete_recomendacion(client, "not-found")


def test_delete_recomendacion_success() -> None:
    """delete_recomendacion returns True on success."""
    client, _ = _client_recording(
        _handler_returns_rows([{"id": "22222222-2222-2222-2222-222222222222"}])
    )
    result = salud_service.delete_recomendacion(
        client, "22222222-2222-2222-2222-222222222222"
    )
    assert result is True


def test_delete_recomendacion_not_found_returns_false() -> None:
    """delete_recomendacion returns False when not found."""
    client, _ = _client_recording(_handler_returns_rows([]))
    result = salud_service.delete_recomendacion(client, "not-found")
    assert result is False
