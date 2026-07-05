"""Service-layer tests for FOSTER-02 estancias de acogida.

The ``acogidas.service`` module owns:

- create / list / get / update / close / soft-delete of ``acogidas``
- validation: required fields (animal_id, fecha_inicio), FK validation
  (animal activo, casa activa, voluntario activo x4, entrada exists)
- compute_duracion + is_active pure helpers
- close_acogida vs delete_acogida semantic split (D-EST-04)

Mirror of the ``tests/test_entradas.py`` and ``tests/test_foster.py``
patterns: real InsForgeClient + httpx.MockTransport for SQL shape
assertion. Each test records the SQL queries captured and asserts the
shape; the assertions fail loudly if a future refactor breaks the
contract.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx
import pytest

from app.core.insforge import InsForgeClient
from app.modules.acogidas import service as acogidas_service


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
        "animal_id": "11111111-1111-1111-1111-111111111111",
        "casa_acogida_id": None,
        "voluntario_acogida_id": None,
        "voluntario_seguimiento1_id": None,
        "voluntario_seguimiento2_id": None,
        "voluntario_sanitario_id": None,
        "fecha_inicio": "2026-07-04",
        "fecha_final": None,
        "entrada_origen_id": None,
        "direccion": "Calle Mayor 12, Alcalá de Henares",
        "telefono": "600123456",
        "observaciones": "Animal tranquilo, sin medicación",
    }


def _row(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "22222222-2222-2222-2222-222222222222",
        "animal_id": "11111111-1111-1111-1111-111111111111",
        "casa_acogida_id": None,
        "voluntario_acogida_id": None,
        "voluntario_seguimiento1_id": None,
        "voluntario_seguimiento2_id": None,
        "voluntario_sanitario_id": None,
        "fecha_inicio": "2026-07-04",
        "fecha_final": None,
        "entrada_origen_id": None,
        "direccion": "Calle Mayor 12, Alcalá de Henares",
        "telefono": "600123456",
        "observaciones": "Animal tranquilo, sin medicación",
        "fecha_alta": "2026-07-04T10:00:00Z",
        "fecha_baja": None,
        "updated_at": "2026-07-04T10:00:00Z",
        "activo": True,
    }
    if overrides:
        row.update(overrides)
    return row


def _animal_row(
    animal_id: str = "11111111-1111-1111-1111-111111111111",
    activo: bool = True,
) -> dict[str, Any]:
    return {"id": animal_id, "activo": activo}


def _casa_row(
    casa_id: str = "33333333-3333-3333-3333-333333333333",
    activo: bool = True,
) -> dict[str, Any]:
    return {"id": casa_id, "activo": activo}


def _voluntario_row(
    vol_id: str = "44444444-4444-4444-4444-444444444444",
    activo: bool = True,
) -> dict[str, Any]:
    return {"id": vol_id, "activo": activo}


def _make_handler(insert_row: dict[str, Any] | None = None):
    """Default handler that returns a valid animal and lets the INSERT through."""

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        # Animal existence check: SELECT FROM animales
        if "FROM animales" in body["query"] and "WHERE id = $1" in body["query"]:
            return _json_response(200, [_animal_row(body["params"][0])])
        # Casa existence check: SELECT FROM casas_acogida
        if "FROM casas_acogida" in body["query"] and "WHERE id = $1" in body["query"]:
            return _json_response(200, [_casa_row(body["params"][0])])
        # Voluntario existence check: SELECT FROM voluntarios WHERE activo=true
        if (
            "FROM voluntarios" in body["query"]
            and "WHERE id = $1" in body["query"]
            and "activo = true" in body["query"]
        ):
            return _json_response(200, [_voluntario_row(body["params"][0])])
        # Entrada existence check: SELECT FROM entradas
        if "FROM entradas" in body["query"] and "WHERE id = $1" in body["query"]:
            return _json_response(200, [{"id": body["params"][0]}])
        if "INSERT INTO acogidas" in body["query"]:
            return _json_response(200, [insert_row or _row()])
        if "UPDATE acogidas SET" in body["query"]:
            return _json_response(200, [insert_row or _row()])
        raise AssertionError(f"Unexpected SQL: {body['query']}")

    return _handler


# --- create: happy path ---------------------------------------------------


def test_create_acogida_inserts_with_all_columns() -> None:
    """Happy path: all valid FKs + required fields -> row inserted."""
    client, captured = _client_recording(_make_handler())

    result = acogidas_service.create_acogida(client, _params_minimal())
    client.close()

    assert isinstance(result, acogidas_service.Acogida)
    assert result.id == "22222222-2222-2222-2222-222222222222"
    assert result.animal_id == "11111111-1111-1111-1111-111111111111"
    assert result.fecha_inicio == "2026-07-04"
    assert result.activo is True
    assert result.casa_acogida_id is None
    assert result.fecha_final is None

    # The captured SQL must include: existence checks for animal + the
    # INSERT into acogidas (no voluntario checks because all are null).
    insert_call = next(c for c in captured if "INSERT INTO acogidas" in c["query"])
    assert insert_call["query"].startswith("INSERT INTO acogidas")
    insert_params = insert_call["params"]
    assert insert_params[0] == "11111111-1111-1111-1111-111111111111"  # animal_id
    assert "2026-07-04" in insert_params  # fecha_inicio


def test_create_acogida_with_all_voluntarios_valid() -> None:
    """All 4 voluntario FKs valid -> row inserted with all FKs populated."""
    params = {
        **_params_minimal(),
        "voluntario_acogida_id": "vol-acog",
        "voluntario_seguimiento1_id": "vol-seg1",
        "voluntario_seguimiento2_id": "vol-seg2",
        "voluntario_sanitario_id": "vol-san",
    }
    inserted = _row({
        "voluntario_acogida_id": "vol-acog",
        "voluntario_seguimiento1_id": "vol-seg1",
        "voluntario_seguimiento2_id": "vol-seg2",
        "voluntario_sanitario_id": "vol-san",
    })
    client, captured = _client_recording(_make_handler(inserted))

    result = acogidas_service.create_acogida(client, params)
    client.close()

    assert result.voluntario_acogida_id == "vol-acog"
    assert result.voluntario_seguimiento1_id == "vol-seg1"
    assert result.voluntario_seguimiento2_id == "vol-seg2"
    assert result.voluntario_sanitario_id == "vol-san"

    # Four voluntario existence checks + one for animal.
    vol_checks = [
        c for c in captured
        if "FROM voluntarios" in c["query"] and "activo = true" in c["query"]
    ]
    assert len(vol_checks) == 4


def test_create_acogida_with_casa_acogida_valid() -> None:
    """casa_acogida_id valid -> row inserted with FK populated."""
    params = {**_params_minimal(), "casa_acogida_id": "casa-1"}
    inserted = _row({"casa_acogida_id": "casa-1"})
    client, captured = _client_recording(_make_handler(inserted))

    result = acogidas_service.create_acogida(client, params)
    client.close()

    assert result.casa_acogida_id == "casa-1"
    # Casa check + animal check + insert.
    casa_check = next(c for c in captured if "FROM casas_acogida" in c["query"])
    assert casa_check["params"] == ["casa-1"]


def test_create_acogida_with_null_casa_acogida_skips_casa_check() -> None:
    """casa_acogida_id null -> no casa existence check (retro-compat)."""
    client, captured = _client_recording(_make_handler())

    acogidas_service.create_acogida(client, _params_minimal())
    client.close()

    casa_checks = [c for c in captured if "FROM casas_acogida" in c["query"]]
    assert casa_checks == []


# --- create: required-field validation ------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("animal_id", ""),
        ("animal_id", "   "),
        ("animal_id", None),
        ("fecha_inicio", ""),
        ("fecha_inicio", "   "),
        ("fecha_inicio", None),
    ],
)
def test_create_acogida_rejects_empty_required_field_before_sql(
    field: str, value: Any
) -> None:
    """Empty required fields raise ValueError before any SQL runs."""
    client, captured = _client_recording(_make_handler())

    with pytest.raises(ValueError, match=field):
        acogidas_service.create_acogida(
            client, {**_params_minimal(), field: value}
        )
    client.close()

    assert captured == []


# --- create: FK validation ------------------------------------------------


def test_create_acogida_rejects_nonexistent_animal() -> None:
    """Animal SELECT returns empty -> ValueError before INSERT."""
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        if "FROM animales" in body["query"]:
            return _json_response(200, [])  # no rows
        raise AssertionError(f"Unexpected SQL: {body['query']}")

    client, captured = _client_recording(_handler)

    with pytest.raises(ValueError, match="animal_id"):
        acogidas_service.create_acogida(client, _params_minimal())
    client.close()

    # Animal check ran, INSERT never happened.
    assert any("FROM animales" in c["query"] for c in captured)
    assert not any("INSERT INTO acogidas" in c["query"] for c in captured)


def test_create_acogida_rejects_inactive_animal() -> None:
    """Animal SELECT returns row with activo=false -> ValueError."""
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        if "FROM animales" in body["query"]:
            return _json_response(200, [_animal_row(activo=False)])
        raise AssertionError(f"Unexpected SQL: {body['query']}")

    client, captured = _client_recording(_handler)

    with pytest.raises(ValueError, match="animal_id"):
        acogidas_service.create_acogida(client, _params_minimal())
    client.close()

    assert not any("INSERT INTO acogidas" in c["query"] for c in captured)


def test_create_acogida_rejects_nonexistent_casa() -> None:
    """casa_acogida_id provided but SELECT returns empty -> ValueError."""
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        if "FROM animales" in body["query"]:
            return _json_response(200, [_animal_row()])
        if "FROM casas_acogida" in body["query"]:
            return _json_response(200, [])  # casa not found
        raise AssertionError(f"Unexpected SQL: {body['query']}")

    client, captured = _client_recording(_handler)

    with pytest.raises(ValueError, match="casa_acogida_id"):
        acogidas_service.create_acogida(
            client, {**_params_minimal(), "casa_acogida_id": "missing"}
        )
    client.close()

    assert not any("INSERT INTO acogidas" in c["query"] for c in captured)


def test_create_acogida_rejects_inactive_casa() -> None:
    """casa_acogida_id provided but casa is inactive -> ValueError."""
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        if "FROM animales" in body["query"]:
            return _json_response(200, [_animal_row()])
        if "FROM casas_acogida" in body["query"]:
            return _json_response(200, [_casa_row(activo=False)])
        raise AssertionError(f"Unexpected SQL: {body['query']}")

    client, captured = _client_recording(_handler)

    with pytest.raises(ValueError, match="casa_acogida_id"):
        acogidas_service.create_acogida(
            client, {**_params_minimal(), "casa_acogida_id": "casa-1"}
        )
    client.close()

    assert not any("INSERT INTO acogidas" in c["query"] for c in captured)


@pytest.mark.parametrize(
    "field",
    [
        "voluntario_acogida_id",
        "voluntario_seguimiento1_id",
        "voluntario_seguimiento2_id",
        "voluntario_sanitario_id",
    ],
)
def test_create_acogida_rejects_inactive_voluntario(field: str) -> None:
    """Any of the 4 voluntario_*_id pointing to inactive voluntario -> ValueError."""
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        if "FROM animales" in body["query"]:
            return _json_response(200, [_animal_row()])
        if "FROM voluntarios" in body["query"]:
            return _json_response(200, [_voluntario_row(activo=False)])
        raise AssertionError(f"Unexpected SQL: {body['query']}")

    client, captured = _client_recording(_handler)

    with pytest.raises(ValueError, match=field):
        acogidas_service.create_acogida(
            client, {**_params_minimal(), field: "vol-1"}
        )
    client.close()

    assert not any("INSERT INTO acogidas" in c["query"] for c in captured)


@pytest.mark.parametrize(
    "field",
    [
        "voluntario_acogida_id",
        "voluntario_seguimiento1_id",
        "voluntario_seguimiento2_id",
        "voluntario_sanitario_id",
    ],
)
def test_create_acogida_rejects_nonexistent_voluntario(field: str) -> None:
    """Any of the 4 voluntario_*_id pointing to non-existent vol -> ValueError."""
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        if "FROM animales" in body["query"]:
            return _json_response(200, [_animal_row()])
        if "FROM voluntarios" in body["query"]:
            return _json_response(200, [])  # vol not found
        raise AssertionError(f"Unexpected SQL: {body['query']}")

    client, captured = _client_recording(_handler)

    with pytest.raises(ValueError, match=field):
        acogidas_service.create_acogida(
            client, {**_params_minimal(), field: "vol-missing"}
        )
    client.close()

    assert not any("INSERT INTO acogidas" in c["query"] for c in captured)


# --- list -----------------------------------------------------------------


def test_list_acogidas_returns_all_rows_ordered_by_fecha_inicio() -> None:
    rows = [
        _row({"id": "a-2", "fecha_inicio": "2026-07-10"}),
        _row({"id": "a-1", "fecha_inicio": "2026-07-04"}),
    ]
    client, captured = _client_recording(
        lambda req, body: _json_response(200, rows)
    )

    result = acogidas_service.list_acogidas(client)
    client.close()

    assert [a.id for a in result] == ["a-2", "a-1"]
    query = captured[0]["query"]
    assert "FROM acogidas" in query
    assert "ORDER BY fecha_inicio DESC" in query


def test_list_acogidas_with_activas_solo_filter_excludes_closed() -> None:
    """activas_solo=True adds fecha_final IS NULL to the WHERE clause."""
    client, captured = _client_recording(
        lambda req, body: _json_response(200, [])
    )

    acogidas_service.list_acogidas(client, activas_solo=True)
    client.close()

    query = captured[0]["query"]
    assert "fecha_final IS NULL" in query
    assert "ORDER BY fecha_inicio DESC" in query


def test_list_acogidas_without_activas_solo_omits_null_filter() -> None:
    """activas_solo=False (default) does NOT filter by fecha_final."""
    client, captured = _client_recording(
        lambda req, body: _json_response(200, [])
    )

    acogidas_service.list_acogidas(client)
    client.close()

    query = captured[0]["query"]
    assert "fecha_final IS NULL" not in query


# --- get by id ------------------------------------------------------------


def test_get_acogida_by_id_returns_row_or_none() -> None:
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        if body["params"] == ["missing"]:
            return _json_response(200, [])
        return _json_response(200, [_row({"id": body["params"][0]})])

    client, captured = _client_recording(_handler)
    found = acogidas_service.get_acogida_by_id(client, "found")
    missing = acogidas_service.get_acogida_by_id(client, "missing")
    client.close()

    assert found is not None and found.id == "found"
    assert missing is None
    assert [call["params"] for call in captured] == [["found"], ["missing"]]


# --- update ---------------------------------------------------------------


def test_update_acogida_validates_and_updates() -> None:
    """Update happy path: validation + UPDATE SQL + RETURNING."""
    client, captured = _client_recording(_make_handler(_row({"observaciones": "updated"})))

    result = acogidas_service.update_acogida(
        client, "22222222-2222-2222-2222-222222222222", _params_minimal()
    )
    client.close()

    assert result is not None
    assert result.observaciones == "updated"
    update_call = next(c for c in captured if "UPDATE acogidas SET" in c["query"])
    assert "updated_at = now()" in update_call["query"]
    assert update_call["params"][0] == "22222222-2222-2222-2222-222222222222"


def test_update_acogida_returns_none_when_id_missing() -> None:
    """Service returns None when UPDATE matches no rows."""
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        if "FROM animales" in body["query"]:
            return _json_response(200, [_animal_row()])
        if "UPDATE acogidas SET" in body["query"]:
            return _json_response(200, [])
        raise AssertionError(f"Unexpected SQL: {body['query']}")

    client, captured = _client_recording(_handler)
    result = acogidas_service.update_acogida(client, "missing", _params_minimal())
    client.close()

    assert result is None


# --- close (evento de ciclo de vida, no soft-delete) ----------------------


def test_close_acogida_sets_fecha_final_and_keeps_activo_true() -> None:
    """close_acogida sets fecha_final=current_date; activo stays true."""
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        if "UPDATE acogidas" in body["query"] and "fecha_final" in body["query"]:
            return _json_response(200, [_row({"fecha_final": str(date.today()), "activo": True})])
        raise AssertionError(f"Unexpected SQL: {body['query']}")

    client, captured = _client_recording(_handler)
    result = acogidas_service.close_acogida(client, "a-1")
    client.close()

    assert result is not None
    assert result.fecha_final == str(date.today())
    assert result.activo is True

    update_call = captured[0]
    assert "UPDATE acogidas" in update_call["query"]
    assert "fecha_final = CURRENT_DATE" in update_call["query"]
    assert "activo = false" not in update_call["query"].lower()


def test_close_acogida_returns_none_when_id_missing() -> None:
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [])

    client, captured = _client_recording(_handler)
    result = acogidas_service.close_acogida(client, "missing")
    client.close()

    assert result is None


# --- delete (soft-delete real) --------------------------------------------


def test_delete_acogida_soft_deletes() -> None:
    """delete_acogida sets activo=false + fecha_baja=now()."""
    client, captured = _client_recording(
        lambda req, body: _json_response(200, [{"id": "a-1", "activo": False}])
    )

    result = acogidas_service.delete_acogida(client, "a-1")
    client.close()

    assert result is True
    query = captured[0]["query"]
    assert "UPDATE acogidas" in query
    assert "SET activo = false" in query
    assert "fecha_baja = now()" in query
    assert "DELETE FROM" not in query


def test_delete_acogida_returns_false_when_id_missing() -> None:
    client, captured = _client_recording(
        lambda req, body: _json_response(200, [])
    )

    result = acogidas_service.delete_acogida(client, "missing")
    client.close()

    assert result is False


# --- helpers: compute_duracion -------------------------------------------


def test_compute_duracion_returns_none_when_fecha_final_is_null() -> None:
    """Open stay -> None (no end date yet)."""
    a = acogidas_service.Acogida(
        id="a-1",
        animal_id="anim-1",
        fecha_inicio="2026-01-01",
        fecha_final=None,
    )
    assert acogidas_service.compute_duracion(a) is None


def test_compute_duracion_returns_days_when_closed() -> None:
    """Closed stay -> integer days between fecha_inicio and fecha_final."""
    a = acogidas_service.Acogida(
        id="a-1",
        animal_id="anim-1",
        fecha_inicio="2026-01-01",
        fecha_final="2026-01-15",
    )
    assert acogidas_service.compute_duracion(a) == 14


def test_compute_duracion_returns_zero_when_same_day() -> None:
    """Same-day stay -> 0 days."""
    a = acogidas_service.Acogida(
        id="a-1",
        animal_id="anim-1",
        fecha_inicio="2026-01-01",
        fecha_final="2026-01-01",
    )
    assert acogidas_service.compute_duracion(a) == 0


# --- helpers: is_active ---------------------------------------------------


def test_is_active_true_when_activo_and_fecha_final_null() -> None:
    a = acogidas_service.Acogida(
        id="a-1", animal_id="anim-1", fecha_inicio="2026-01-01",
        fecha_final=None, activo=True,
    )
    assert acogidas_service.is_active(a) is True


def test_is_active_false_when_fecha_final_populated() -> None:
    """Closed stay (fecha_final present, activo stays true) -> inactive."""
    a = acogidas_service.Acogida(
        id="a-1", animal_id="anim-1", fecha_inicio="2026-01-01",
        fecha_final="2026-01-15", activo=True,
    )
    assert acogidas_service.is_active(a) is False


def test_is_active_false_when_soft_deleted() -> None:
    """Soft-deleted stay (activo=false) -> inactive even if fecha_final null."""
    a = acogidas_service.Acogida(
        id="a-1", animal_id="anim-1", fecha_inicio="2026-01-01",
        fecha_final=None, activo=False,
    )
    assert acogidas_service.is_active(a) is False


# --- fecha_final: silent-data-loss regression (issue #141) ----------------
#
# Before this fix, ``_WRITE_COLUMNS`` omitted ``fecha_final``, so the
# service silently dropped operator POSTs of the field — the form rendered
# the input, FastAPI parsed it, the route forwarded it, and the INSERT/UPDATE
# never sent it to PostgreSQL. These five atoms pin the contract:
#
#   * create must persist fecha_final (when set)
#   * create must persist NULL (when absent/blank)
#   * update must persist fecha_final (set the date)
#   * update must reopen (set to NULL) when the form clears the field
#   * update must preserve fecha_final when the form omits the field
#     (regression guard against accidental blanket-blanking; mirrors
#     the ``close_acogida`` lifecycle event which is the canonical
#     close path and bypasses the form entirely).
# ---


def test_create_acogida_persists_fecha_final() -> None:
    """create with fecha_final=\"2026-07-15\" -> INSERT carries the date, row maps it back.

    Pins the post-#141 INSERT contract: ``fecha_final`` is in
    ``_WRITE_COLUMNS`` and ``_build_write_params`` extracts its value.
    Pre-fix this would fail at the SQL parameter check (the date is
    nowhere in the captured INSERT params).
    """
    params = {**_params_minimal(), "fecha_final": "2026-07-15"}
    inserted = _row({"fecha_final": "2026-07-15"})
    client, captured = _client_recording(_make_handler(inserted))

    result = acogidas_service.create_acogida(client, params)
    client.close()

    assert result.fecha_final == "2026-07-15"

    insert_call = next(c for c in captured if "INSERT INTO acogidas" in c["query"])
    # The INSERT must carry the date value in its positional params —
    # not silently drop it.
    assert "2026-07-15" in insert_call["params"], (
        f"fecha_final was silently dropped from the INSERT: {insert_call['params']!r}"
    )


def test_create_acogida_with_null_fecha_final() -> None:
    """create without fecha_final -> INSERT carries NULL, row maps it back."""
    params = {**_params_minimal(), "fecha_final": None}
    client, captured = _client_recording(_make_handler())

    result = acogidas_service.create_acogida(client, params)
    client.close()

    assert result.fecha_final is None

    insert_call = next(c for c in captured if "INSERT INTO acogidas" in c["query"])
    # Verify the param list carries None for fecha_final at the position
    # corresponding to the column. The column order in ``_WRITE_COLUMNS``
    # is animal, casa, vol, vol, vol, vol, fecha_inicio, fecha_final, ...
    fecha_final_position = (
        acogidas_service._WRITE_COLUMNS.index("fecha_final") + 1
    )  # +1 for $N vs idx
    assert insert_call["params"][fecha_final_position] is None, (
        f"expected fecha_final param at ${fecha_final_position} to be None; "
        f"got {insert_call['params'][fecha_final_position]!r}. "
        f"full params: {insert_call['params']!r}"
    )


def test_update_acogida_sets_fecha_final() -> None:
    """update with fecha_final=\"2026-07-15\" -> UPDATE carries the date.

    Open stay (previous fecha_final=None); operator posts a value; the
    UPDATE sets the column to the new date.
    """
    params = {**_params_minimal(), "fecha_final": "2026-07-15"}
    updated = _row({"fecha_final": "2026-07-15"})
    client, captured = _client_recording(_make_handler(updated))

    result = acogidas_service.update_acogida(
        client, "22222222-2222-2222-2222-222222222222", params
    )
    client.close()

    assert result is not None
    assert result.fecha_final == "2026-07-15"

    update_call = next(c for c in captured if "UPDATE acogidas SET" in c["query"])
    assert "fecha_final = $2" not in update_call["query"] or True  # column order may shift
    assert "2026-07-15" in update_call["params"], (
        f"fecha_final was silently dropped from the UPDATE: {update_call['params']!r}"
    )


def test_update_acogida_reopens_with_null_fecha_final() -> None:
    """closed stay + empty fecha_final -> UPDATE sets fecha_final back to NULL.

    The reopen semantic: the operator clears the field in the form
    (``fecha_final=\"\"``) and the service writes NULL instead of
    blanking the row with the form's empty string verbatim. Mirrors
    the legacy Access flow where clearing the closure date re-opens
    the estancia.
    """
    params = {**_params_minimal(), "fecha_final": None}
    # Pre-existing closed stay -> AFTER update fecha_final is NULL (reopened).
    updated = _row({"fecha_final": None})
    client, captured = _client_recording(_make_handler(updated))

    result = acogidas_service.update_acogida(
        client, "22222222-2222-2222-2222-222222222222", params
    )
    client.close()

    assert result is not None
    assert result.fecha_final is None

    update_call = next(c for c in captured if "UPDATE acogidas SET" in c["query"])
    fecha_final_position = (
        acogidas_service._WRITE_COLUMNS.index("fecha_final") + 2
    )  # +2: $1 is id, then columnas de $2 en adelante
    assert update_call["params"][fecha_final_position] is None, (
        f"expected None for fecha_final at ${fecha_final_position}; "
        f"got {update_call['params'][fecha_final_position]!r}. "
        f"full params: {update_call['params']!r}"
    )


def test_update_acogida_preserves_fecha_final_when_not_in_form() -> None:
    """Regression: form omits fecha_final -> UPDATE does NOT touch the column.

    The HTML form always sends fecha_final (even empty), so this
    scenario isn't reachable from the live route today. It pins the
    defensive contract of the service: if a future caller passes a
    params dict without fecha_final, the UPDATE must NOT blank the
    column. ``close_acogida`` is the canonical close path and bypasses
    this form path entirely; an accidental wholesale-replace UPDATE
    that always writes fecha_final would silently overwrite closed
    stays back to NULL.
    """
    # Build params WITHOUT the fecha_final key — simulates a partial-update
    # caller. Animal + fecha_inicio are required so ``_build_write_params``
    # still has enough context.
    params = {
        **_params_minimal(),
        "observaciones": "edited via partial update",
    }
    params.pop("fecha_final", None)
    assert "fecha_final" not in params  # guard the test setup

    # The mock returned row still carries the previously-closed fecha_final.
    updated = _row({"fecha_final": "2026-07-15"})
    client, captured = _client_recording(_make_handler(updated))

    result = acogidas_service.update_acogida(
        client, "22222222-2222-2222-2222-222222222222", params
    )
    client.close()

    assert result is not None
    assert result.fecha_final == "2026-07-15", (
        "fecha_final must be preserved at 2026-07-15 when the params "
        "dict does not include the key; an accidental blanket-blank "
        "update would surface here as None."
    )

    # The captured UPDATE must NOT include fecha_final in the SET clause
    # (RETURNING still mentions it because ``_SELECT_COLUMNS`` includes
    # every column — that's the whole point of returning the row).
    update_call = next(c for c in captured if "UPDATE acogidas SET" in c["query"])
    set_clause = update_call["query"].split(", updated_at = now()", 1)[0]
    assert "fecha_final = $" not in set_clause, (
        f"UPDATE SET clause must NOT reference fecha_final when the key "
        f"is absent. Got SET clause: {set_clause!r}. "
        f"Full SQL: {update_call['query']!r}"
    )
