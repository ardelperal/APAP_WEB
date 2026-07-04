"""Service-layer tests for ADOPT-01 adopciones.

The ``adopciones.service`` module owns:
- create / list / get / update / soft-delete of ``adopciones``
- validation: required fields (animal_id, fecha_adopcion, nombre_adoptante)
- FK checks: animal activo, voluntario_seguimiento_id activo per VOL-05
- search by nombre_adoptante (ILIKE case-insensitive, D-ADOPT-04)
- ``is_active`` derived from fecha_devolucion (D-ADOPT-05)

Mirror of the ``tests/test_entradas.py`` and ``tests/test_foster.py``
patterns: real InsForgeClient + httpx.MockTransport for SQL shape
assertion. The FK validation tests piggyback on the same handler
infrastructure: a SELECT to ``animales`` or ``voluntarios`` is mocked
to return either an active row (success) or nothing (validation
failure).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.core.insforge import InsForgeClient
from app.modules.adopciones import service as adopciones_service


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


def _params_minimal() -> dict[str, Any]:
    return {
        "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "voluntario_seguimiento_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "fecha_adopcion": "2026-07-04",
        "fecha_devolucion": None,
        "donativo_preadopcion": None,
        "donativo_adopcion": None,
        "nombre_adoptante": "María García López",
        "dni_adoptante": "12345678A",
        "telefono_adoptante": "600123456",
        "email_adoptante": "maria@example.com",
        "entrada_origen_id": None,
        "observaciones": "Adopción responsable",
        "tipo_adopcion": "regular",
    }


def _row(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "11111111-1111-1111-1111-111111111111",
        "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "voluntario_seguimiento_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "fecha_adopcion": "2026-07-04",
        "fecha_devolucion": None,
        "donativo_preadopcion": None,
        "donativo_adopcion": None,
        "nombre_adoptante": "María García López",
        "dni_adoptante": "12345678A",
        "telefono_adoptante": "600123456",
        "email_adoptante": "maria@example.com",
        "entrada_origen_id": None,
        "observaciones": "Adopción responsable",
        "tipo_adopcion": "regular",
        "fecha_alta": "2026-07-04T10:00:00Z",
        "updated_at": "2026-07-04T10:00:00Z",
        "activo": True,
    }
    if overrides:
        row.update(overrides)
    return row


def _validation_handler(
    *,
    animal_exists: bool = True,
    voluntario_exists: bool = True,
    insert_row: dict[str, Any] | None = None,
    update_row: dict[str, Any] | None = None,
):
    """Build a handler that answers FK lookups + INSERT/UPDATE for adopciones.

    The FK SELECTs are matched by their FROM clause (``animales`` /
    ``voluntarios``); the adopciones INSERT/UPDATE match on their own
    ``INSERT INTO adopciones`` / ``UPDATE adopciones SET`` prefix.
    """

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        query = body["query"]
        if "FROM animales" in query:
            return _json_response(
                200, [{"id": body["params"][0]}] if animal_exists else []
            )
        if "FROM voluntarios" in query:
            return _json_response(
                200, [{"id": body["params"][0]}] if voluntario_exists else []
            )
        if "INSERT INTO adopciones" in query:
            return _json_response(200, [insert_row or _row()])
        if "UPDATE adopciones SET" in query:
            return _json_response(200, [update_row or _row()])
        raise AssertionError(f"Unexpected SQL: {query!r}")

    return _handler


# --- create: happy path ---------------------------------------------------


def test_create_adopcion_inserts_with_all_columns() -> None:
    client, captured = _client_recording(_validation_handler())

    result = adopciones_service.create_adopcion(client, _params_minimal())
    client.close()

    assert isinstance(result, adopciones_service.Adopcion)
    assert result.id == "11111111-1111-1111-1111-111111111111"
    assert result.animal_id == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert result.nombre_adoptante == "María García López"
    assert result.tipo_adopcion == "regular"
    assert result.activo is True
    assert result.is_active is True  # fecha_devolucion is None → vigente

    # 1 FK check (animales) + 1 FK check (voluntarios) + 1 INSERT = 3
    assert len(captured) == 3
    assert any("FROM animales" in c["query"] for c in captured)
    assert any("FROM voluntarios" in c["query"] for c in captured)
    insert = next(c for c in captured if "INSERT INTO adopciones" in c["query"])
    assert "tipo_adopcion" in insert["query"]
    # The first INSERT param is animal_id (per _WRITE_COLUMNS order).
    assert insert["params"][0] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    # nombre_adoptante is the 7th param per _WRITE_COLUMNS order.
    assert insert["params"][6] == "María García López"


def test_create_adopcion_with_null_voluntario_skips_voluntario_fk_check() -> None:
    """When ``voluntario_seguimiento_id`` is None, the voluntarios SELECT is skipped."""
    params = {**_params_minimal(), "voluntario_seguimiento_id": None}
    client, captured = _client_recording(_validation_handler())

    adopciones_service.create_adopcion(client, params)
    client.close()

    # 1 animales SELECT + 1 INSERT = 2 calls (no voluntarios SELECT).
    assert len(captured) == 2
    assert not any("FROM voluntarios" in c["query"] for c in captured)


def test_create_adopcion_with_donativos_numeric_coerces_to_float() -> None:
    params = {
        **_params_minimal(),
        "donativo_preadopcion": "50.00",
        "donativo_adopcion": "150.50",
    }
    insert_row = _row(
        {"donativo_preadopcion": 50.0, "donativo_adopcion": 150.5}
    )
    client, captured = _client_recording(_validation_handler(insert_row=insert_row))

    result = adopciones_service.create_adopcion(client, params)
    client.close()

    assert result.donativo_preadopcion == 50.0
    assert result.donativo_adopcion == 150.5
    insert = next(c for c in captured if "INSERT INTO adopciones" in c["query"])
    # donativo_preadopcion is the 5th param (per _WRITE_COLUMNS order).
    assert insert["params"][4] == 50.0
    assert insert["params"][5] == 150.5


def test_create_adopcion_default_tipo_adopcion_is_regular() -> None:
    """Omitting ``tipo_adopcion`` defaults to 'regular'."""
    params = {k: v for k, v in _params_minimal().items() if k != "tipo_adopcion"}
    client, captured = _client_recording(_validation_handler())

    result = adopciones_service.create_adopcion(client, params)
    client.close()

    assert result.tipo_adopcion == "regular"
    insert = next(c for c in captured if "INSERT INTO adopciones" in c["query"])
    # tipo_adopcion is the 13th param.
    assert insert["params"][12] == "regular"


# --- create: required-field validation ------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("animal_id", ""),
        ("animal_id", "   "),
        ("fecha_adopcion", ""),
        ("fecha_adopcion", None),
        ("nombre_adoptante", ""),
        ("nombre_adoptante", "   "),
    ],
)
def test_create_adopcion_rejects_empty_required_field_before_sql(
    field: str, value: Any
) -> None:
    client, captured = _client_recording(_validation_handler())

    with pytest.raises(ValueError, match=field):
        adopciones_service.create_adopcion(
            client, {**_params_minimal(), field: value}
        )
    client.close()

    assert captured == []


# --- create: FK validation (VOL-05, D-ADOPT-02) ----------------------------


def test_create_adopcion_rejects_inactive_animal() -> None:
    """animal_id that exists but activo=false → ValueError, no INSERT."""
    client, captured = _client_recording(_validation_handler(animal_exists=False))

    with pytest.raises(ValueError, match="animal_id"):
        adopciones_service.create_adopcion(client, _params_minimal())
    client.close()

    # Only the animales SELECT ran; no INSERT, no voluntario SELECT (the
    # active check short-circuits because the validation order is
    # animales → voluntarios → INSERT).
    assert any("FROM animales" in c["query"] for c in captured)
    assert not any("INSERT INTO adopciones" in c["query"] for c in captured)


def test_create_adopcion_rejects_inactive_voluntario_per_vol_05() -> None:
    """VOL-05: voluntario_seguimiento_id with activo=false must be rejected.

    The animales check passes (the animal is active), but the voluntario
    SELECT returns no rows → ValueError matching ``voluntario_seguimiento_id``
    and no INSERT is emitted.
    """
    client, captured = _client_recording(
        _validation_handler(voluntario_exists=False)
    )

    with pytest.raises(ValueError, match="voluntario_seguimiento_id"):
        adopciones_service.create_adopcion(client, _params_minimal())
    client.close()

    # animales check ran, voluntario check ran, no INSERT.
    assert any("FROM animales" in c["query"] for c in captured)
    assert any("FROM voluntarios" in c["query"] for c in captured)
    assert not any("INSERT INTO adopciones" in c["query"] for c in captured)


# --- create: numeric validation -------------------------------------------


def test_create_adopcion_rejects_non_numeric_donativo() -> None:
    params = {**_params_minimal(), "donativo_preadopcion": "no-es-numero"}
    client, captured = _client_recording(_validation_handler())

    with pytest.raises(ValueError, match="donativo_preadopcion"):
        adopciones_service.create_adopcion(client, params)
    client.close()

    assert captured == []


def test_create_adopcion_rejects_boolean_donativo() -> None:
    """bool is a subclass of int in Python; reject it explicitly."""
    params = {**_params_minimal(), "donativo_adopcion": True}
    client, captured = _client_recording(_validation_handler())

    with pytest.raises(ValueError, match="donativo_adopcion"):
        adopciones_service.create_adopcion(client, params)
    client.close()

    assert captured == []


# --- list -----------------------------------------------------------------


def test_list_adopciones_returns_active_rows_ordered_by_fecha_alta() -> None:
    rows = [
        _row({"id": "adop-2", "fecha_alta": "2026-07-04T12:00:00Z"}),
        _row({"id": "adop-1", "fecha_alta": "2026-07-04T10:00:00Z"}),
    ]
    client, captured = _client_recording(
        lambda req, body: _json_response(200, rows)
    )

    result = adopciones_service.list_adopciones(client)
    client.close()

    assert [a.id for a in result] == ["adop-2", "adop-1"]
    query = captured[0]["query"]
    assert "FROM adopciones" in query
    assert "WHERE activo = true" in query
    assert "ORDER BY fecha_alta DESC" in query


# --- get by id ------------------------------------------------------------


def test_get_adopcion_by_id_returns_row_or_none() -> None:
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        if body["params"] == ["missing"]:
            return _json_response(200, [])
        return _json_response(200, [_row({"id": body["params"][0]})])

    client, captured = _client_recording(_handler)
    found = adopciones_service.get_adopcion_by_id(client, "found")
    missing = adopciones_service.get_adopcion_by_id(client, "missing")
    client.close()

    assert found is not None and found.id == "found"
    assert missing is None
    assert [call["params"] for call in captured] == [["found"], ["missing"]]


# --- update ---------------------------------------------------------------


def test_update_adopcion_validates_and_updates_minimal_fields() -> None:
    client, captured = _client_recording(
        _validation_handler(update_row=_row({"nombre_adoptante": "María Editada"}))
    )

    result = adopciones_service.update_adopcion(
        client,
        "11111111-1111-1111-1111-111111111111",
        {**_params_minimal(), "nombre_adoptante": "María Editada"},
    )
    client.close()

    assert result is not None
    assert result.nombre_adoptante == "María Editada"
    update_call = next(c for c in captured if "UPDATE adopciones SET" in c["query"])
    assert "updated_at = now()" in update_call["query"]
    assert update_call["params"][0] == "11111111-1111-1111-1111-111111111111"


def test_update_adopcion_returns_none_when_id_missing() -> None:
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        if "FROM animales" in body["query"]:
            return _json_response(200, [{"id": body["params"][0]}])
        if "FROM voluntarios" in body["query"]:
            return _json_response(200, [{"id": body["params"][0]}])
        if "UPDATE adopciones SET" in body["query"]:
            return _json_response(200, [])
        raise AssertionError(f"Unexpected SQL: {body['query']}")

    client, _captured = _client_recording(_handler)
    result = adopciones_service.update_adopcion(
        client, "missing", _params_minimal()
    )
    client.close()

    assert result is None


def test_update_adopcion_revalidates_voluntario_activo() -> None:
    """VOL-05: editing a row to an inactive voluntario must be rejected."""
    client, captured = _client_recording(
        _validation_handler(voluntario_exists=False)
    )

    with pytest.raises(ValueError, match="voluntario_seguimiento_id"):
        adopciones_service.update_adopcion(
            client,
            "11111111-1111-1111-1111-111111111111",
            _params_minimal(),
        )
    client.close()

    assert not any("UPDATE adopciones SET" in c["query"] for c in captured)


# --- soft delete ---------------------------------------------------------


def test_delete_adopcion_soft_deletes_without_physical_delete() -> None:
    client, captured = _client_recording(
        lambda req, body: _json_response(200, [{"id": "adop-1"}])
    )
    result = adopciones_service.delete_adopcion(client, "adop-1")
    client.close()

    assert result is True
    assert len(captured) == 1
    query = captured[0]["query"]
    assert "UPDATE adopciones" in query
    assert "SET activo = false" in query
    assert "WHERE id = $1 AND activo = true" in query
    assert "DELETE FROM" not in query


def test_delete_adopcion_returns_false_when_already_inactive() -> None:
    """The ``WHERE activo = true`` filter returns 0 rows → service False."""
    client, captured = _client_recording(
        lambda req, body: _json_response(200, [])
    )
    result = adopciones_service.delete_adopcion(client, "missing")
    client.close()

    assert result is False
    assert len(captured) == 1


# --- search by adoptante (D-ADOPT-04) -------------------------------------


def test_search_adopciones_by_adoptante_uses_ilike() -> None:
    client, captured = _client_recording(
        lambda req, body: _json_response(200, [_row()])
    )

    result = adopciones_service.search_adopciones_by_adoptante(client, "garcia")
    client.close()

    assert len(result) == 1
    query = captured[0]["query"]
    assert "ILIKE" in query
    assert "nombre_adoptante ILIKE" in query
    assert captured[0]["params"] == ["garcia"]


def test_search_adopciones_by_adoptante_empty_returns_empty_list() -> None:
    """Empty / whitespace filters skip the SQL roundtrip (D-ADOPT-04)."""
    client, captured = _client_recording(
        lambda req, body: _json_response(200, [_row()])
    )

    result = adopciones_service.search_adopciones_by_adoptante(client, "   ")
    client.close()

    assert result == []
    assert captured == []


def test_search_adopciones_by_adoptante_trims_whitespace() -> None:
    client, captured = _client_recording(
        lambda req, body: _json_response(200, [])
    )

    adopciones_service.search_adopciones_by_adoptante(client, "  Maria  ")
    client.close()

    assert captured[0]["params"] == ["Maria"]


# --- is_active derived (D-ADOPT-05) ---------------------------------------


def test_is_active_true_when_fecha_devolucion_is_null() -> None:
    row = _row({"fecha_devolucion": None})
    adopcion = adopciones_service._row_to_adopcion(row)

    assert adopcion.is_active is True


def test_is_active_false_when_fecha_devolucion_is_set() -> None:
    row = _row({"fecha_devolucion": "2026-08-15"})
    adopcion = adopciones_service._row_to_adopcion(row)

    assert adopcion.is_active is False


def test_is_active_survives_soft_delete_independently() -> None:
    """A row with activo=false AND fecha_devolucion set is still !is_active.

    The operator can read both signals: ``activo`` is the DB-level
    soft-delete (filter lists); ``is_active`` is the domain semantic
    (is the animal still with the family?). They can diverge when a
    family returns the animal AND the operator later soft-deletes the
    adoption row. Both correctly read False from the perspective the
    caller cares about.
    """
    row = _row({"activo": False, "fecha_devolucion": "2026-08-15"})
    adopcion = adopciones_service._row_to_adopcion(row)

    assert adopcion.is_active is False
    assert adopcion.activo is False


# --- default tipo_adopcion via row mapping --------------------------------


def test_row_to_adopcion_defaults_tipo_adopcion_to_regular() -> None:
    """A row that predates the migration has no ``tipo_adopcion`` col."""
    row = _row()
    row.pop("tipo_adopcion")

    adopcion = adopciones_service._row_to_adopcion(row)

    assert adopcion.tipo_adopcion == "regular"


def test_row_to_adopcion_coerces_donativos_to_float() -> None:
    """Decimal/numeric values come back as strings in some responses."""
    row = _row({"donativo_preadopcion": "50.00", "donativo_adopcion": "150.50"})

    adopcion = adopciones_service._row_to_adopcion(row)

    assert adopcion.donativo_preadopcion == 50.0
    assert adopcion.donativo_adopcion == 150.5
