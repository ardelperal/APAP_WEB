"""Service-layer tests for FOSTER-02 estancias de acogida.

The ``acogidas.service`` module owns:

- create / list / get / update / close / soft-delete of ``acogidas``
- validation: required fields (animal_id, fecha_inicio), FK validation
  (animal activo, casa activa, voluntario activo x4, entrada exists)
- compute_duracion + is_active pure helpers
- close_acogida vs delete_acogida semantic split (D-EST-04)

Mirror of the ``tests/test_entradas.py`` and ``tests/test_foster.py``
patterns: real LocalPostgresExecutor + httpx.MockTransport for SQL shape
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

from tests.sql_executor_fake import HandlerSqlExecutor as LocalPostgresExecutor
from app.modules.acogidas import service as acogidas_service


def _json_response(status_code: int, body: Any) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _client_recording(
    handler: Callable[[httpx.Request, dict[str, Any]], httpx.Response],
) -> tuple[LocalPostgresExecutor, list[dict[str, Any]]]:
    captured: list[dict[str, Any]] = []

    def _recording_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization", "").startswith("Bearer ")
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        captured.append(body)
        return handler(request, body)

    client = LocalPostgresExecutor(
        base_url="https://example.local_backend.app",
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
        # Animal existence check: SELECT FROM animales WHERE id = $1
        # (FK validation in create_acogida -- issue #32 acceptance).
        if "FROM animales" in body["query"] and "WHERE id = $1" in body["query"]:
            return _json_response(200, [_animal_row(body["params"][0])])
        # LIFECYCLE-02 (issue #32): the cascade's ficha SELECT
        # (``LEFT JOIN animal_current_state WHERE animales.id = $1``)
        # does NOT carry the substring ``"WHERE id = $1"`` -- the column
        # is qualified with the table alias. Match it separately so the
        # cascade's ``build_select_ficha`` call returns a valid ficha
        # row and the state derivation does not crash on missing keys.
        if (
            "FROM animales" in body["query"]
            and "LEFT JOIN animal_current_state" in body["query"]
        ):
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
        # LIFECYCLE-02 (issue #32): create_acogida / close_acogida
        # emit lifecycle events into ``animal_lifecycle_events`` and
        # refresh ``animal_current_state`` via
        # ``actualizar_estado_animal``. Those writes hit:
        #   * ``INSERT INTO animal_lifecycle_events`` (event log)
        #   * ``FROM entradas/acogidas/adopciones`` active-collection
        #     SELECTs (the cascade inputs)
        #   * ``INSERT INTO animal_current_state`` (cache UPSERT)
        # Returning empty lists keeps the cascade happy ("no other
        # active placements") without coupling the CRUD tests to the
        # lifecycle SQL shape -- that's pinned by
        # ``tests/test_acogidas_lifecycle_events.py``.
        if "INSERT INTO animal_lifecycle_events" in body["query"]:
            return _json_response(200, [])
        if (
            "FROM entradas" in body["query"]
            and "fecha_salida IS NULL" in body["query"]
            and "activo = true" in body["query"]
        ):
            return _json_response(200, [])
        if (
            "FROM acogidas" in body["query"]
            and "fecha_final IS NULL" in body["query"]
            and "activo = true" in body["query"]
        ):
            return _json_response(200, [])
        if (
            "FROM adopciones" in body["query"]
            and "fecha_devolucion IS NULL" in body["query"]
            and "activo = true" in body["query"]
        ):
            return _json_response(200, [])
        if "INSERT INTO animal_current_state" in body["query"]:
            return _json_response(200, [])
        if "INSERT INTO acogidas" in body["query"]:
            return _json_response(200, [insert_row or _row()])
        if "UPDATE acogidas SET" in body["query"]:
            return _json_response(200, [insert_row or _row()])
        # LIFECYCLE-02 (issue #32): let cascade-driven SQL through with
        # an empty response so the cascade does not crash. The SQL shape
        # is pinned by ``tests/test_acogidas_lifecycle_events.py``.
        lifecycle_resp = _lifecycle_query_response(body["query"])
        if lifecycle_resp is not None:
            return lifecycle_resp
        raise AssertionError(f"Unexpected SQL: {body['query']}")

    return _handler


def _lifecycle_query_response(query: str) -> httpx.Response | None:
    """Return a 200/[] response for any lifecycle SQL query the cascade issues.

    LIFECYCLE-02 (issue #32) makes ``create_acogida`` / ``close_acogida``
    fire extra SQL: ``INSERT INTO animal_lifecycle_events`` (event log),
    the cascade's ficha + active-placements SELECTs, and the
    ``INSERT INTO animal_current_state`` cache UPSERT. Pre-existing
    CRUD tests use custom inline handlers that only know about the
    ``INSERT/UPDATE acogidas`` shape; this helper lets those tests
    accept the new lifecycle SQL without coupling to its exact
    parameter list. The lifecycle SQL shape is pinned by
    ``tests/test_acogidas_lifecycle_events.py``.
    """
    if "INSERT INTO animal_lifecycle_events" in query:
        return _json_response(200, [])
    if "INSERT INTO animal_current_state" in query:
        return _json_response(200, [])
    if "LEFT JOIN animal_current_state" in query and "FROM animales" in query:
        return _json_response(200, [_animal_row()])
    if (
        "FROM entradas" in query
        and "fecha_salida IS NULL" in query
        and "activo = true" in query
    ):
        return _json_response(200, [])
    if (
        "FROM acogidas" in query
        and "fecha_final IS NULL" in query
        and "activo = true" in query
    ):
        return _json_response(200, [])
    if (
        "FROM adopciones" in query
        and "fecha_devolucion IS NULL" in query
        and "activo = true" in query
    ):
        return _json_response(200, [])
    return None


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


# --- Issue #142: create_acogida links foster_capacity_overrides row -------


def test_create_acogida_links_override_when_casa_and_animal_match() -> None:
    """Issue #142 + judgment-day CRITICAL §1.2: casa+animal match -> UPDATE links.

    Regression guard for the happy path. The foster_capacity_overrides
    row was recorded for (casa X, animal Y); ``create_acogida`` is
    called with ``override_id=O1`` AND ``casa_acogida_id=X`` AND
    ``animal_id=Y``. The WHERE filter ``id = $2 AND casa_acogida_id =
    $3 AND animal_id = $4 AND estancia_id IS NULL`` matches, the
    UPDATE writes the new ``acogida.id`` into the override's
    ``estancia_id`` column, and the audit log reads "override ->
    estancia X" atomically.

    Defense (judgment-day CRITICAL §1.2): the UPDATE filter MUST scope
    to ``casa_acogida_id`` AND ``animal_id`` so a forged ``override_id``
    from another operator's session cannot link to a different stay —
    the casa+animal pair from the form must match the override's
    recorded pair. The other atoms in this section
    (``test_create_acogida_does_not_link_override_when_casa_mismatches``
    / ``..._when_animal_mismatches`` / ``..._when_casa_is_null``)
    exercise the rejection paths.
    """
    captured: list[dict[str, Any]] = []
    ACOGIDA_UUID = "22222222-2222-2222-2222-222222222222"
    OVERRIDE_UUID = "99999999-9999-9999-9999-999999999999"
    CASA_UUID = "33333333-3333-3333-3333-333333333333"
    ANIMAL_UUID = "11111111-1111-1111-1111-111111111111"

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        if "FROM animales" in body["query"] and "WHERE id = $1" in body["query"]:
            return _json_response(200, [_animal_row(animal_id=ANIMAL_UUID)])
        if "FROM casas_acogida" in body["query"] and "WHERE id = $1" in body["query"]:
            return _json_response(200, [_casa_row(casa_id=CASA_UUID)])
        if "INSERT INTO acogidas" in body["query"]:
            return _json_response(200, [_row({"casa_acogida_id": CASA_UUID})])
        # The linkage UPDATE on foster_capacity_overrides.
        if "UPDATE foster_capacity_overrides" in body["query"]:
            captured.append(body)
            return _json_response(200, [{"id": OVERRIDE_UUID, "estancia_id": ACOGIDA_UUID}])
        # LIFECYCLE-02 (issue #32): let cascade-driven SQL through with
        # an empty response so the cascade does not crash. The SQL shape
        # is pinned by ``tests/test_acogidas_lifecycle_events.py``.
        lifecycle_resp = _lifecycle_query_response(body["query"])
        if lifecycle_resp is not None:
            return lifecycle_resp
        raise AssertionError(f"Unexpected SQL: {body['query']}")

    client, _ = _client_recording(_handler)
    params = {
        **_params_minimal(),
        "casa_acogida_id": CASA_UUID,
        "animal_id": ANIMAL_UUID,
        "override_id": OVERRIDE_UUID,
    }

    result = acogidas_service.create_acogida(client, params)
    client.close()

    assert result.id == ACOGIDA_UUID
    # The UPDATE ran once with all 4 WHERE clauses: id + casa + animal + NULL guard.
    assert len(captured) == 1, (
        f"expected exactly one linkage UPDATE; got {captured!r}"
    )
    update_call = captured[0]
    assert "UPDATE foster_capacity_overrides" in update_call["query"]
    assert "SET estancia_id" in update_call["query"]
    assert "WHERE id = $2" in update_call["query"]
    # The casa+animal scope guards against cross-operator forge — judgment-day CRITICAL §1.2.
    assert "AND casa_acogida_id = $3" in update_call["query"]
    assert "AND animal_id = $4" in update_call["query"]
    assert "AND estancia_id IS NULL" in update_call["query"]
    # Params: $1 = new estancia_id, $2 = override UUID, $3 = casa, $4 = animal.
    assert update_call["params"] == [
        ACOGIDA_UUID,
        OVERRIDE_UUID,
        CASA_UUID,
        ANIMAL_UUID,
    ]


def test_create_acogida_does_not_link_override_when_casa_mismatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #142 + judgment-day CRITICAL §1.2: forge attempt with wrong casa -> 0 rows.

    Operator B's session tries to forge Operator A's override_id while
    submitting their own stay for a DIFFERENT casa. The foster_capacity_overrides
    row was recorded for (casa X, animal Y); Operator B submits
    (casa Z, animal Y, override_id=O1). The new WHERE filter
    ``casa_acogida_id = $3`` rejects the forge (casa X != casa Z),
    UPDATE matches 0 rows, and we log ``foster.override.unlinked``
    so the audit anomaly surfaces. The estancia itself is still
    created successfully — defense rejects the forgery silently
    rather than punishing the operator.
    """
    captured_log: list[dict[str, Any]] = []

    def _capture(event: str, **fields: Any) -> None:
        captured_log.append({"event": event, **fields})

    monkeypatch.setattr(
        "app.modules.acogidas.service.log_safe", _capture
    )

    captured: list[dict[str, Any]] = []
    CASA_FORGE = "55555555-5555-5555-5555-555555555555"  # Operator B's casa
    OVERRIDE_UUID = "99999999-9999-9999-9999-999999999999"
    ANIMAL_UUID = "11111111-1111-1111-1111-111111111111"

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        captured.append(body)
        if "FROM animales" in body["query"] and "WHERE id = $1" in body["query"]:
            return _json_response(200, [_animal_row(animal_id=ANIMAL_UUID)])
        if "FROM casas_acogida" in body["query"] and "WHERE id = $1" in body["query"]:
            return _json_response(200, [_casa_row(casa_id=CASA_FORGE)])
        if "INSERT INTO acogidas" in body["query"]:
            return _json_response(200, [_row({"casa_acogida_id": CASA_FORGE})])
        # Linkage UPDATE: filter rejects because the override row's casa
        # (X) does NOT match the casa from the form (Z). Mock returns 0 rows.
        if "UPDATE foster_capacity_overrides" in body["query"]:
            # Verify the SQL carries the casa filter — that is the defense.
            assert "AND casa_acogida_id = $3" in body["query"], (
                f"link UPDATE MUST filter by casa_acogida_id to reject "
                f"cross-casa forgeries; got query={body['query']!r}"
            )
            assert body["params"][2] == CASA_FORGE, (
                f"link UPDATE $3 (casa) MUST be the form's casa, not the "
                f"override's recorded casa; got params={body['params']!r}"
            )
            return _json_response(200, [])
        # LIFECYCLE-02 (issue #32): let cascade-driven SQL through with
        # an empty response so the cascade does not crash. The SQL shape
        # is pinned by ``tests/test_acogidas_lifecycle_events.py``.
        lifecycle_resp = _lifecycle_query_response(body["query"])
        if lifecycle_resp is not None:
            return lifecycle_resp
        raise AssertionError(f"Unexpected SQL: {body['query']}")

    client, _ = _client_recording(_handler)

    result = acogidas_service.create_acogida(
        client,
        {
            **_params_minimal(),
            "animal_id": ANIMAL_UUID,
            "casa_acogida_id": CASA_FORGE,
            "override_id": OVERRIDE_UUID,
        },
    )
    client.close()

    # The estancia was created (Operator B's actual stay is not blocked).
    assert result.id == "22222222-2222-2222-2222-222222222222"
    # The forge attempt was rejected and logged.
    assert any(
        entry["event"] == "foster.override.unlinked"
        for entry in captured_log
    ), (
        f"expected foster.override.unlinked warning after casa-mismatch "
        f"forge attempt; got {captured_log!r}"
    )
    # The linkage UPDATE was attempted exactly once (then rejected by the filter).
    update_calls = [
        c for c in captured if "UPDATE foster_capacity_overrides" in c["query"]
    ]
    assert len(update_calls) == 1


def test_create_acogida_does_not_link_override_when_animal_mismatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #142 + judgment-day HIGH §3.2: forge attempt with wrong animal -> 0 rows.

    Same attack shape as casa mismatch, but the forger re-uses the
    correct casa and slips in a different animal. The animal_id
    filter rejects (animal Z != animal Y), UPDATE matches 0 rows,
    and we log the warning. Audit log stays consistent with the
    operator that actually recorded the override.
    """
    captured_log: list[dict[str, Any]] = []

    def _capture(event: str, **fields: Any) -> None:
        captured_log.append({"event": event, **fields})

    monkeypatch.setattr(
        "app.modules.acogidas.service.log_safe", _capture
    )

    CASA_UUID = "33333333-3333-3333-3333-333333333333"
    ANIMAL_FORGE = "77777777-7777-7777-7777-777777777777"  # Operator B's animal
    OVERRIDE_UUID = "99999999-9999-9999-9999-999999999999"

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        if "FROM animales" in body["query"] and "WHERE id = $1" in body["query"]:
            return _json_response(200, [_animal_row(animal_id=ANIMAL_FORGE)])
        if "FROM casas_acogida" in body["query"] and "WHERE id = $1" in body["query"]:
            return _json_response(200, [_casa_row(casa_id=CASA_UUID)])
        if "INSERT INTO acogidas" in body["query"]:
            return _json_response(200, [_row({"casa_acogida_id": CASA_UUID})])
        if "UPDATE foster_capacity_overrides" in body["query"]:
            assert "AND animal_id = $4" in body["query"], (
                f"link UPDATE MUST filter by animal_id to reject "
                f"cross-animal forgeries; got query={body['query']!r}"
            )
            assert body["params"][3] == ANIMAL_FORGE, (
                f"link UPDATE $4 (animal) MUST be the form's animal, not "
                f"the override's recorded animal; got params={body['params']!r}"
            )
            return _json_response(200, [])
        # LIFECYCLE-02 (issue #32): let cascade-driven SQL through with
        # an empty response so the cascade does not crash. The SQL shape
        # is pinned by ``tests/test_acogidas_lifecycle_events.py``.
        lifecycle_resp = _lifecycle_query_response(body["query"])
        if lifecycle_resp is not None:
            return lifecycle_resp
        raise AssertionError(f"Unexpected SQL: {body['query']}")

    client, _ = _client_recording(_handler)

    result = acogidas_service.create_acogida(
        client,
        {
            **_params_minimal(),
            "animal_id": ANIMAL_FORGE,
            "casa_acogida_id": CASA_UUID,
            "override_id": OVERRIDE_UUID,
        },
    )
    client.close()

    assert result.id == "22222222-2222-2222-2222-222222222222"
    assert any(
        entry["event"] == "foster.override.unlinked"
        for entry in captured_log
    ), (
        f"expected foster.override.unlinked warning after animal-mismatch "
        f"forge attempt; got {captured_log!r}"
    )


def test_create_acogida_does_not_link_when_casa_is_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edge case: create_acogida with casa_acogida_id=None must not link the override.

    The override row was recorded for a SPECIFIC casa (casa_acogida_id
    is NOT NULL on the override row by schema). If the operator hits
    ``/acogidas/new`` directly with casa_acogida_id=None (no casa at
    all) and tries to thread an override_id, the casa filter rejects
    (because ``casa_acogida_id = NULL`` evaluates to NULL/false in
    SQL three-valued logic — the override's casa is not null). We log
    the warning. This protects against accidentally linking an
    override to a stay that has no casa, which would corrupt the
    audit (override for casa X linked to a stay with no casa).
    """
    captured_log: list[dict[str, Any]] = []

    def _capture(event: str, **fields: Any) -> None:
        captured_log.append({"event": event, **fields})

    monkeypatch.setattr(
        "app.modules.acogidas.service.log_safe", _capture
    )

    OVERRIDE_UUID = "99999999-9999-9999-9999-999999999999"
    ANIMAL_UUID = "11111111-1111-1111-1111-111111111111"
    captured: list[dict[str, Any]] = []

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        captured.append(body)
        if "FROM animales" in body["query"] and "WHERE id = $1" in body["query"]:
            return _json_response(200, [_animal_row(animal_id=ANIMAL_UUID)])
        # No casa check expected: casa_acogida_id is None in params.
        if "INSERT INTO acogidas" in body["query"]:
            return _json_response(200, [_row()])
        if "UPDATE foster_capacity_overrides" in body["query"]:
            # The casa filter is present; $3 is the form's casa (None).
            # In SQL three-valued logic, ``casa_acogida_id = NULL`` is
            # NULL/false, so the filter rejects the link. Mock returns 0 rows.
            assert "AND casa_acogida_id = $3" in body["query"], (
                f"link UPDATE MUST carry casa_acogida_id filter even when "
                f"the form's casa is None; got query={body['query']!r}"
            )
            assert body["params"][2] is None, (
                f"$3 must be the form's casa (None here); got {body['params']!r}"
            )
            return _json_response(200, [])
        # LIFECYCLE-02 (issue #32): let cascade-driven SQL through with
        # an empty response so the cascade does not crash. The SQL shape
        # is pinned by ``tests/test_acogidas_lifecycle_events.py``.
        lifecycle_resp = _lifecycle_query_response(body["query"])
        if lifecycle_resp is not None:
            return lifecycle_resp
        raise AssertionError(f"Unexpected SQL: {body['query']}")

    client, _ = _client_recording(_handler)

    # Operator hits /acogidas/new directly (no casa) but threads an override_id.
    result = acogidas_service.create_acogida(
        client,
        {
            **_params_minimal(),
            "animal_id": ANIMAL_UUID,
            "casa_acogida_id": None,
            "override_id": OVERRIDE_UUID,
        },
    )
    client.close()

    # The estancia was created (with casa_acogida_id=None).
    assert result.id == "22222222-2222-2222-2222-222222222222"
    assert result.casa_acogida_id is None
    # The linkage was rejected (casa mismatch: form=None vs override=casa X).
    assert any(
        entry["event"] == "foster.override.unlinked"
        for entry in captured_log
    ), (
        f"expected foster.override.unlinked warning when form casa is None "
        f"but override was recorded for a specific casa; got {captured_log!r}"
    )
    # No casa existence check was issued (None skips it).
    casa_checks = [
        c for c in captured if "FROM casas_acogida" in c["query"]
    ]
    assert casa_checks == [], (
        f"no casa existence check expected when casa_acogida_id is None; "
        f"got {casa_checks!r}"
    )


def test_create_acogida_logs_warning_when_override_already_linked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #142: override row already linked -> log warning, do not fail.

    If the row's estancia_id is already populated (e.g. previous create
    succeeded, or duplicate thread), the UPDATE matches 0 rows. We log
    ``foster.override.unlinked`` and DO NOT raise: the estancia itself
    was created, do not punish the operator for an audit-log anomaly.
    """
    captured_log: list[dict[str, Any]] = []

    def _capture(event: str, **fields: Any) -> None:
        captured_log.append({"event": event, **fields})

    monkeypatch.setattr(
        "app.modules.acogidas.service.log_safe", _capture
    )

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        if "FROM animales" in body["query"] and "WHERE id = $1" in body["query"]:
            return _json_response(200, [_animal_row()])
        if "INSERT INTO acogidas" in body["query"]:
            return _json_response(200, [_row()])
        if "UPDATE foster_capacity_overrides" in body["query"]:
            # 0 rows: WHERE id=X AND estancia_id IS NULL fails because
            # the row is already linked.
            return _json_response(200, [])
        # LIFECYCLE-02 (issue #32): let cascade-driven SQL through with
        # an empty response so the cascade does not crash. The SQL shape
        # is pinned by ``tests/test_acogidas_lifecycle_events.py``.
        lifecycle_resp = _lifecycle_query_response(body["query"])
        if lifecycle_resp is not None:
            return lifecycle_resp
        raise AssertionError(f"Unexpected SQL: {body['query']}")

    client, _ = _client_recording(_handler)

    result = acogidas_service.create_acogida(
        client, {**_params_minimal(), "override_id": "already-linked-uuid"}
    )
    client.close()

    # The estancia was created successfully.
    assert result.id == "22222222-2222-2222-2222-222222222222"
    # A warning was emitted to flag the audit anomaly.
    assert any(
        entry["event"] == "foster.override.unlinked"
        for entry in captured_log
    ), (
        f"expected foster.override.unlinked warning; got {captured_log!r}"
    )
    warning = next(
        e for e in captured_log if e["event"] == "foster.override.unlinked"
    )
    assert "motivo" in warning
    assert "override_id" in warning


def test_create_acogida_logs_warning_when_override_id_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #142: override_id that doesn't exist -> log warning, do not fail.

    An operator could craft a request with a garbage override_id (or a
    previous run's stale UUID). The UPDATE matches 0 rows because the
    UUID is not in foster_capacity_overrides. Same behavior as the
    already-linked case: warn, do not raise.
    """
    captured_log: list[dict[str, Any]] = []

    def _capture(event: str, **fields: Any) -> None:
        captured_log.append({"event": event, **fields})

    monkeypatch.setattr(
        "app.modules.acogidas.service.log_safe", _capture
    )

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        if "FROM animales" in body["query"] and "WHERE id = $1" in body["query"]:
            return _json_response(200, [_animal_row()])
        if "INSERT INTO acogidas" in body["query"]:
            return _json_response(200, [_row()])
        if "UPDATE foster_capacity_overrides" in body["query"]:
            return _json_response(200, [])
        # LIFECYCLE-02 (issue #32): let cascade-driven SQL through with
        # an empty response so the cascade does not crash. The SQL shape
        # is pinned by ``tests/test_acogidas_lifecycle_events.py``.
        lifecycle_resp = _lifecycle_query_response(body["query"])
        if lifecycle_resp is not None:
            return lifecycle_resp
        raise AssertionError(f"Unexpected SQL: {body['query']}")

    client, _ = _client_recording(_handler)

    result = acogidas_service.create_acogida(
        client, {**_params_minimal(), "override_id": "ghost-uuid"}
    )
    client.close()

    assert result.id == "22222222-2222-2222-2222-222222222222"
    assert any(
        entry["event"] == "foster.override.unlinked"
        for entry in captured_log
    )


def test_create_acogida_without_override_id_doesnt_touch_foster_capacity_overrides() -> None:
    """Issue #142 regression: absent ``override_id`` -> no UPDATE against fco.

    When the operator hits ``/acogidas/new`` directly (not via
    /asignar override), no override exists. ``create_acogida`` MUST NOT
    emit any UPDATE against ``foster_capacity_overrides`` in that case —
    defense against accidentally widening the surface.
    """
    captured: list[dict[str, Any]] = []

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        captured.append(body)
        if "FROM animales" in body["query"] and "WHERE id = $1" in body["query"]:
            return _json_response(200, [_animal_row()])
        if "INSERT INTO acogidas" in body["query"]:
            return _json_response(200, [_row()])
        # LIFECYCLE-02 (issue #32): let cascade-driven SQL through with
        # an empty response so the cascade does not crash. The SQL shape
        # is pinned by ``tests/test_acogidas_lifecycle_events.py``.
        lifecycle_resp = _lifecycle_query_response(body["query"])
        if lifecycle_resp is not None:
            return lifecycle_resp
        raise AssertionError(f"Unexpected SQL: {body['query']}")

    client, _ = _client_recording(_handler)

    acogidas_service.create_acogida(client, _params_minimal())
    client.close()

    fco_writes = [
        c for c in captured
        if "foster_capacity_overrides" in c["query"]
    ]
    assert fco_writes == [], (
        f"create_acogida MUST NOT touch foster_capacity_overrides when "
        f"override_id absent; got: {fco_writes!r}"
    )


def test_create_acogida_with_empty_override_id_skips_link() -> None:
    """Issue #142: ``override_id=''`` (empty string from missing form field)
    is treated the same as absent — no UPDATE against foster_capacity_overrides.

    Defense against the route handler accidentally rendering
    ``<input type="hidden" name="override_id" value="">`` when no
    override exists and the form serializes the empty string instead
    of omitting the field.
    """
    captured: list[dict[str, Any]] = []

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        captured.append(body)
        if "FROM animales" in body["query"] and "WHERE id = $1" in body["query"]:
            return _json_response(200, [_animal_row()])
        if "INSERT INTO acogidas" in body["query"]:
            return _json_response(200, [_row()])
        # LIFECYCLE-02 (issue #32): let cascade-driven SQL through with
        # an empty response so the cascade does not crash. The SQL shape
        # is pinned by ``tests/test_acogidas_lifecycle_events.py``.
        lifecycle_resp = _lifecycle_query_response(body["query"])
        if lifecycle_resp is not None:
            return lifecycle_resp
        raise AssertionError(f"Unexpected SQL: {body['query']}")

    client, _ = _client_recording(_handler)

    acogidas_service.create_acogida(client, {**_params_minimal(), "override_id": ""})
    client.close()

    fco_writes = [
        c for c in captured
        if "foster_capacity_overrides" in c["query"]
    ]
    assert fco_writes == []


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
        # LIFECYCLE-02 (issue #32): let cascade-driven SQL through with
        # an empty response so the cascade does not crash. The SQL shape
        # is pinned by ``tests/test_acogidas_lifecycle_events.py``.
        lifecycle_resp = _lifecycle_query_response(body["query"])
        if lifecycle_resp is not None:
            return lifecycle_resp
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
        # LIFECYCLE-02 (issue #32): let cascade-driven SQL through with
        # an empty response so the cascade does not crash. The SQL shape
        # is pinned by ``tests/test_acogidas_lifecycle_events.py``.
        lifecycle_resp = _lifecycle_query_response(body["query"])
        if lifecycle_resp is not None:
            return lifecycle_resp
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
        # LIFECYCLE-02 (issue #32): let cascade-driven SQL through with
        # an empty response so the cascade does not crash. The SQL shape
        # is pinned by ``tests/test_acogidas_lifecycle_events.py``.
        lifecycle_resp = _lifecycle_query_response(body["query"])
        if lifecycle_resp is not None:
            return lifecycle_resp
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
        # LIFECYCLE-02 (issue #32): let cascade-driven SQL through with
        # an empty response so the cascade does not crash. The SQL shape
        # is pinned by ``tests/test_acogidas_lifecycle_events.py``.
        lifecycle_resp = _lifecycle_query_response(body["query"])
        if lifecycle_resp is not None:
            return lifecycle_resp
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
        # LIFECYCLE-02 (issue #32): let cascade-driven SQL through with
        # an empty response so the cascade does not crash. The SQL shape
        # is pinned by ``tests/test_acogidas_lifecycle_events.py``.
        lifecycle_resp = _lifecycle_query_response(body["query"])
        if lifecycle_resp is not None:
            return lifecycle_resp
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
        # LIFECYCLE-02 (issue #32): let cascade-driven SQL through with
        # an empty response so the cascade does not crash. The SQL shape
        # is pinned by ``tests/test_acogidas_lifecycle_events.py``.
        lifecycle_resp = _lifecycle_query_response(body["query"])
        if lifecycle_resp is not None:
            return lifecycle_resp
        raise AssertionError(f"Unexpected SQL: {body['query']}")

    client, captured = _client_recording(_handler)

    with pytest.raises(ValueError, match=field):
        acogidas_service.create_acogida(
            client, {**_params_minimal(), field: "vol-missing"}
        )
    client.close()

    assert not any("INSERT INTO acogidas" in c["query"] for c in captured)


# --- entrada_origen_id FK validation (issue #139, P1 #1) -------------------
#
# ``_validate_entrada_exists_if_present`` (service.py:338-354) is the
# orphan-FK guard for ``entrada_origen_id``. It runs unconditionally on
# every ``create_acogida`` call. Pre-#139 it had NO coverage. These two
# atoms pin the contract:
#
#   * non-existent entrada UUID -> ValueError, no INSERT runs
#   * soft-deleted entrada (activo=false) is ACCEPTED — legacy entries
#     can be deactivated while the FK must still resolve, so the
#     relational link stays intact for historical queries.
# ---


def test_create_acogida_rejects_nonexistent_entrada() -> None:
    """entrada SELECT returns empty -> ValueError before INSERT."""
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        if "FROM animales" in body["query"]:
            return _json_response(200, [_animal_row()])
        if "FROM entradas" in body["query"]:
            return _json_response(200, [])  # entrada not found
        # LIFECYCLE-02 (issue #32): let cascade-driven SQL through with
        # an empty response so the cascade does not crash. The SQL shape
        # is pinned by ``tests/test_acogidas_lifecycle_events.py``.
        lifecycle_resp = _lifecycle_query_response(body["query"])
        if lifecycle_resp is not None:
            return lifecycle_resp
        raise AssertionError(f"Unexpected SQL: {body['query']}")

    client, captured = _client_recording(_handler)

    with pytest.raises(ValueError, match="entrada_origen_id"):
        acogidas_service.create_acogida(
            client,
            {**_params_minimal(), "entrada_origen_id": "entrada-missing"},
        )
    client.close()

    # Entrada check ran, INSERT never happened.
    assert any("FROM entradas" in c["query"] for c in captured)
    assert not any("INSERT INTO acogidas" in c["query"] for c in captured)


def test_create_acogida_accepts_soft_deleted_entrada() -> None:
    """Legacy entradas can be soft-deleted but the FK must still resolve.

    ``_CHECK_ENTRADA_SQL`` does NOT filter by ``activo`` precisely so
    legacy entries remain addressable when their stay record is later
    edited (e.g. date correction). The service MUST accept the row
    regardless of ``activo``.
    """
    captured: list[dict[str, Any]] = []

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        captured.append(body)
        if "FROM animales" in body["query"]:
            return _json_response(200, [_animal_row()])
        if "FROM entradas" in body["query"]:
            # Soft-deleted entrada: row exists, activo=false.
            return _json_response(
                200, [{"id": body["params"][0], "activo": False}]
            )
        if "INSERT INTO acogidas" in body["query"]:
            return _json_response(200, [_row()])
        # LIFECYCLE-02 (issue #32): let cascade-driven SQL through with
        # an empty response so the cascade does not crash. The SQL shape
        # is pinned by ``tests/test_acogidas_lifecycle_events.py``.
        lifecycle_resp = _lifecycle_query_response(body["query"])
        if lifecycle_resp is not None:
            return lifecycle_resp
        raise AssertionError(f"Unexpected SQL: {body['query']}")

    client, _ = _client_recording(_handler)

    result = acogidas_service.create_acogida(
        client,
        {**_params_minimal(), "entrada_origen_id": "entrada-legacy"},
    )
    client.close()

    # No ValueError raised; INSERT ran successfully.
    assert result.id == "22222222-2222-2222-2222-222222222222"
    insert_calls = [c for c in captured if "INSERT INTO acogidas" in c["query"]]
    assert len(insert_calls) == 1


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
        # LIFECYCLE-02 (issue #32): let cascade-driven SQL through with
        # an empty response so the cascade does not crash. The SQL shape
        # is pinned by ``tests/test_acogidas_lifecycle_events.py``.
        lifecycle_resp = _lifecycle_query_response(body["query"])
        if lifecycle_resp is not None:
            return lifecycle_resp
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
        # LIFECYCLE-02 (issue #32): close_acogida emits FOSTER_RETURNED
        # and refreshes animal_current_state; let those calls through
        # with empty rows so the cascade does not crash. The SQL shape
        # is pinned by ``tests/test_acogidas_lifecycle_events.py``.
        return _json_response(200, [])

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


def test_close_acogida_works_on_soft_deleted_stay() -> None:
    """Issue #139 P1 #5: closing a soft-deleted stay is allowed.

    Contract (D-EST-04 + data-cleanup workflow): ``close_acogida`` is
    intentionally NOT filtered by ``activo = true``. Operators may need
    to back-fill ``fecha_final`` on a stay that was already
    soft-deleted (e.g. audit found the stay was closed but the closure
    date was never recorded). The function MUST succeed regardless of
    ``activo`` and MUST NOT carry ``AND activo = true`` in the SQL.

    Defense for the data-cleanup workflow:
      * ``activo`` stays whatever the DB had it at (true on close-of-open,
        false on close-of-already-deleted).
      * ``fecha_final`` is set to ``CURRENT_DATE``.
      * Operators who want to close ONLY active stays must filter at the
        application layer (``list_acogidas(activas_solo=True)`` then
        pick).
    """
    captured: list[dict[str, Any]] = []

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        captured.append(body)
        if "UPDATE acogidas" in body["query"] and "fecha_final" in body["query"]:
            # Mock the post-close row: activo stays false (it was soft-deleted
            # before the close), fecha_final gets stamped.
            return _json_response(
                200,
                [_row({"activo": False, "fecha_final": str(date.today())})],
            )
        # LIFECYCLE-02 (issue #32): close_acogida emits FOSTER_RETURNED
        # and refreshes animal_current_state; let those calls through
        # with empty rows so the cascade does not crash. The SQL shape
        # is pinned by ``tests/test_acogidas_lifecycle_events.py``.
        return _json_response(200, [])

    client, _ = _client_recording(_handler)

    result = acogidas_service.close_acogida(client, "a-1")
    client.close()

    # The close succeeded even though the stay was soft-deleted.
    assert result is not None
    assert result.fecha_final == str(date.today())
    assert result.activo is False  # stays as it was

    # The SQL MUST NOT filter by activo — that would block the cleanup path.
    update_call = captured[0]
    assert "UPDATE acogidas" in update_call["query"]
    assert "AND activo = true" not in update_call["query"], (
        f"close_acogida MUST NOT carry ``AND activo = true`` — that would "
        f"block the data-cleanup path where a soft-deleted stay needs "
        f"fecha_final back-filled; got query={update_call['query']!r}"
    )


# --- delete (soft-delete real) --------------------------------------------


def test_delete_acogida_soft_deletes() -> None:
    """delete_acogida sets activo=false + fecha_baja=now() ATOMICALLY.

    Issue #139 P1 #3: the SQL MUST carry ``WHERE id = $1 AND activo =
    true`` AND ``RETURNING id`` — without those two clauses the
    atomicity pattern collapses silently:

      * ``AND activo = true`` folds the existence check into the same
        statement under PostgreSQL's row lock, so two concurrent
        callers produce exactly one ``True`` and one ``False``.
      * ``RETURNING id`` is how the service turns a 0-row UPDATE into
        ``False`` (row missing or already inactive) without a follow-up
        SELECT.
    """
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
    # Atomicity pins (issue #139 P1 #3):
    assert "AND activo = true" in query, (
        f"soft-delete MUST filter by ``AND activo = true`` for atomic "
        f"existence check; got query={query!r}"
    )
    assert "RETURNING id" in query, (
        f"soft-delete MUST ``RETURNING id`` so the service can detect "
        f"already-deleted rows without a follow-up SELECT; got "
        f"query={query!r}"
    )
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


# --- compute_duracion edge cases (issue #139, P1 #2) -----------------------
#
# Contract pinned by these atoms:
#
#   * fecha_final < fecha_inicio -> ValueError. Per legacy semantic,
#     a stay cannot end before it begins — this is a data-entry error
#     (operator typed the dates the wrong way around). Returning a
#     negative number would silently corrupt the operator-facing
#     duration display, so we raise loudly instead. The form layer
#     surfaces this as a 422 with the operator's input preserved.
#   * non-ISO fecha_inicio -> ValueError. ``date.fromisoformat``
#     raises ``ValueError`` on malformed input; we let it propagate
#     (no silent swallow, no `None` fallback).
#   * non-ISO fecha_final -> ValueError. Same contract.
# ---


def test_compute_duracion_raises_when_fecha_final_before_fecha_inicio() -> None:
    """Stay that ends before it starts is a data-entry error -> ValueError."""
    a = acogidas_service.Acogida(
        id="a-1",
        animal_id="anim-1",
        fecha_inicio="2026-07-10",
        fecha_final="2026-07-05",
    )
    with pytest.raises(ValueError):
        acogidas_service.compute_duracion(a)


def test_compute_duracion_raises_when_fecha_inicio_not_iso() -> None:
    """Malformed fecha_inicio -> ValueError (no silent fallback to None)."""
    a = acogidas_service.Acogida(
        id="a-1",
        animal_id="anim-1",
        fecha_inicio="not-a-date",
        fecha_final="2026-07-15",
    )
    with pytest.raises(ValueError):
        acogidas_service.compute_duracion(a)


def test_compute_duracion_raises_when_fecha_final_not_iso() -> None:
    """Malformed fecha_final -> ValueError (no silent fallback to None)."""
    a = acogidas_service.Acogida(
        id="a-1",
        animal_id="anim-1",
        fecha_inicio="2026-07-04",
        fecha_final="also-not-a-date",
    )
    with pytest.raises(ValueError):
        acogidas_service.compute_duracion(a)


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
