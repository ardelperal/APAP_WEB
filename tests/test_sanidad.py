"""Service-layer tests for HEALTH-01 sanidad (CRUD).

The ``sanidad.service`` module owns:
- create / list / get / update / soft-delete of ``actuacion_sanitaria``
- validation: required fields (animal_id, fecha), FK checks (animal
  activo, voluntario activo per VOL-05), D-24 fecha validation
  (reglas 1+2 pure + regla 3 atomic via CTE)
- search by ``animal_id`` (D-HEALTH-04)
- CTE TOCTOU-safe writes (D-HEALTH-05)

Mirror of the ``tests/test_adopciones.py`` pattern: real InsForgeClient
+ httpx.MockTransport for SQL shape assertion. The mock handler answers
CTE queries with a single round-trip; on a 0-row CTE the service runs
targeted disambiguation SELECTs which the handler also answers.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import httpx
import pytest

from app.core.insforge import InsForgeClient
from app.modules.sanidad import service as sanidad_service


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
        "voluntario_id": None,
        "fecha": "2026-07-04",
        "tipo_actuacion_id": None,
        "veterinario": "Dra. Pérez",
        "observaciones": "Vacuna anual",
        "material_utilizado": "Nobivac Rabia",
    }


def _row(
    overrides: dict[str, Any] | None = None,
    *,
    fecha: str | None = None,
) -> dict[str, Any]:
    """Build a mock ``actuacion_sanitaria`` row for tests.

    Backward compatible: callers may pass an ``overrides`` dict
    (the historical API) OR use the ``fecha`` keyword shortcut.
    The keyword shortcut lets date-coupling tests inject the
    fecha they want the mock to echo back, decoupling the test
    from the calendar (issue: CI broke 2026-07-05 UTC because
    the hardcoded default ``fecha: '2026-07-04'`` no longer
    matched ``date.today()`` once midnight passed).
    """
    row: dict[str, Any] = {
        "id": "11111111-1111-1111-1111-111111111111",
        "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "voluntario_id": None,
        "fecha": "2026-07-04",
        "tipo_actuacion_id": None,
        "veterinario": "Dra. Pérez",
        "observaciones": "Vacuna anual",
        "material_utilizado": "Nobivac Rabia",
        "fecha_alta": "2026-07-04T10:00:00Z",
        "updated_at": "2026-07-04T10:00:00Z",
        "activo": True,
    }
    if fecha is not None:
        row["fecha"] = fecha
    if overrides:
        row.update(overrides)
    return row


def _handler_returns_rows(
    rows: list[dict[str, Any]], call_log: list[int] | None = None
) -> Callable[[httpx.Request, dict[str, Any]], httpx.Response]:
    """Handler that returns ``rows`` for every SQL call (single-statement)."""

    def _h(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        if call_log is not None:
            call_log.append(1)
        return _json_response(200, rows)

    return _h


def _handler_cascading(
    *responses: list[dict[str, Any]] | dict[str, Any],
) -> Callable[[httpx.Request, dict[str, Any]], httpx.Response]:
    """Handler that returns successive responses per call (for CTE + disambiguation)."""
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


# --- 1. Happy path ---------------------------------------------------------


def test_create_actuacion_happy_path() -> None:
    """create returns a populated ActuacionSanitaria and emits log_safe."""
    client, captured = _client_recording(
        _handler_returns_rows([_row()])
    )

    actuacion = sanidad_service.create_actuacion_sanitaria(
        client, _params_minimal(), actor_user_id="u-1"
    )

    assert actuacion.id == "11111111-1111-1111-1111-111111111111"
    assert actuacion.animal_id == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert actuacion.fecha == "2026-07-04"
    assert actuacion.veterinario == "Dra. Pérez"
    assert actuacion.material_utilizado == "Nobivac Rabia"
    assert actuacion.activo is True
    assert actuacion.voluntario_id is None
    assert actuacion.tipo_actuacion_id is None
    # The CTE INSERT was emitted with positional params matching
    # _WRITE_COLUMNS order.
    assert len(captured) == 1
    params = captured[0]["params"]
    assert params[0] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # animal_id
    assert params[2] == "2026-07-04"  # fecha
    assert params[4] == "Dra. Pérez"  # veterinario


def test_list_actuaciones_returns_mapped_rows() -> None:
    """list_actuaciones_sanitarias returns ActuacionSanitaria instances."""
    rows = [
        _row({"id": "id-1", "fecha": "2026-07-01"}),
        _row({"id": "id-2", "fecha": "2026-07-02", "veterinario": "Dr. Gómez"}),
    ]
    client, _ = _client_recording(_handler_returns_rows(rows))

    result = sanidad_service.list_actuaciones_sanitarias(client)

    assert len(result) == 2
    assert [a.id for a in result] == ["id-1", "id-2"]
    assert result[1].veterinario == "Dr. Gómez"


def test_update_actuacion_happy_path() -> None:
    """update returns the updated row and emits log_safe."""
    client, captured = _client_recording(
        _handler_returns_rows([_row({"observaciones": "Refuerzo"})])
    )

    actuacion = sanidad_service.update_actuacion_sanitaria(
        client,
        "11111111-1111-1111-1111-111111111111",
        {**_params_minimal(), "observaciones": "Refuerzo"},
        actor_user_id="u-1",
    )

    assert actuacion is not None
    assert actuacion.observaciones == "Refuerzo"
    # The UPDATE CTE was emitted with id first, then FK placeholders
    # (shifted by +1 vs INSERT).
    assert len(captured) == 1
    params = captured[0]["params"]
    assert params[0] == "11111111-1111-1111-1111-111111111111"  # id
    assert params[1] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # animal_id
    assert params[3] == "2026-07-04"  # fecha (shifted by 1 vs INSERT)
    query = captured[0]["query"]
    assert "animal_id = $2" in query
    assert "voluntario_id = $3" in query
    assert "fecha = $4" in query
    assert "material_utilizado = $8" in query
    assert "FROM checked_animal" in query
    assert "checked_animal.fecha_alta" in query


def test_update_sql_qualifies_returning_columns_to_avoid_ambiguous_id() -> None:
    """UPDATE has a FROM source with id, so RETURNING must qualify target columns."""
    query = sanidad_service._UPDATE_ACTUACION_SANITARIA_SQL
    returning = re.search(r"RETURNING (?P<columns>.+?)\n\)", query, re.DOTALL)

    assert returning is not None
    returning_columns = returning.group("columns")
    assert "FROM checked_animal" in query
    assert "SELECT id, fecha_alta FROM animales" in query
    assert "target_actuacion.id" in returning_columns
    assert re.search(r"(?<!\.)\bid\b", returning_columns) is None


# --- 2. Required-field validation ----------------------------------------


def test_create_rejects_empty_animal_id() -> None:
    """animal_id empty raises ValueError BEFORE any DB call."""
    client, captured = _client_recording(_handler_returns_rows([]))

    with pytest.raises(ValueError, match="animal_id is required"):
        sanidad_service.create_actuacion_sanitaria(
            client, {**_params_minimal(), "animal_id": ""}
        )
    assert captured == []  # no DB roundtrip


def test_create_rejects_whitespace_animal_id() -> None:
    """animal_id whitespace-only is treated as empty (per _required_text)."""
    client, captured = _client_recording(_handler_returns_rows([]))

    with pytest.raises(ValueError, match="animal_id is required"):
        sanidad_service.create_actuacion_sanitaria(
            client, {**_params_minimal(), "animal_id": "   "}
        )
    assert captured == []


def test_create_rejects_empty_fecha() -> None:
    """fecha empty raises ValueError BEFORE any DB call."""
    client, captured = _client_recording(_handler_returns_rows([]))

    with pytest.raises(ValueError, match="fecha is required"):
        sanidad_service.create_actuacion_sanitaria(
            client, {**_params_minimal(), "fecha": ""}
        )
    assert captured == []


# --- 3. FK validation (animal / voluntario) -------------------------------


def test_create_rejects_nonexistent_animal_via_disambiguation() -> None:
    """CTE returns 0 rows; disambiguation finds no animal — raises."""
    client, _ = _client_recording(
        _handler_cascading(
            # 1st call: CTE INSERT — 0 rows
            [],
            # 2nd call: animal disambiguation — no row
            [],
        )
    )

    with pytest.raises(ValueError, match="animal_id debe apuntar"):
        sanidad_service.create_actuacion_sanitaria(
            client, _params_minimal()
        )


def test_create_rejects_inactive_animal_via_disambiguation() -> None:
    """CTE returns 0 rows; animal exists but activo=false — raises."""
    client, _ = _client_recording(
        _handler_cascading(
            # 1st: CTE INSERT — 0 rows
            [],
            # 2nd: animal disambiguation — exists but inactive
            [{"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "activo": False, "fecha_alta": None}],
        )
    )

    with pytest.raises(ValueError, match="animal_id debe apuntar"):
        sanidad_service.create_actuacion_sanitaria(
            client, _params_minimal()
        )


def test_create_rejects_inactive_voluntario_via_disambiguation() -> None:
    """Animal OK + fecha OK + voluntario inactivo (VOL-05) — raises."""
    client, _ = _client_recording(
        _handler_cascading(
            # 1st: CTE INSERT — 0 rows
            [],
            # 2nd: animal disambiguation — exists, active, fecha_alta NULL (legacy)
            [{"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "activo": True, "fecha_alta": None}],
            # 3rd: voluntario disambiguation — 0 rows (inactive or missing)
            [],
        )
    )

    with pytest.raises(ValueError, match="voluntario_id debe apuntar"):
        sanidad_service.create_actuacion_sanitaria(
            client,
            {**_params_minimal(), "voluntario_id": "v-1"},
        )


def test_create_accepts_null_voluntario_id() -> None:
    """voluntario_id None is allowed (no FK check fires)."""
    client, captured = _client_recording(_handler_returns_rows([_row()]))

    actuacion = sanidad_service.create_actuacion_sanitaria(
        client, _params_minimal()
    )

    assert actuacion.voluntario_id is None
    # The bound param is the None we sent.
    params = captured[0]["params"]
    assert params[1] is None


# --- 4. D-24 reglas 1+2 (pure validation) ----------------------------------


def test_create_rejects_malformed_fecha() -> None:
    """fecha malformada raises BEFORE any DB call (D-24 regla 1)."""
    client, captured = _client_recording(_handler_returns_rows([]))

    with pytest.raises(ValueError, match="fecha debe tener formato YYYY-MM-DD"):
        sanidad_service.create_actuacion_sanitaria(
            client, {**_params_minimal(), "fecha": "ayer"}
        )
    assert captured == []  # no DB roundtrip


def test_create_rejects_future_fecha() -> None:
    """fecha futura raises BEFORE any DB call (D-24 regla 2)."""
    client, captured = _client_recording(_handler_returns_rows([]))
    future = (date.today() + timedelta(days=365)).isoformat()

    with pytest.raises(ValueError, match="fecha no puede ser futura"):
        sanidad_service.create_actuacion_sanitaria(
            client, {**_params_minimal(), "fecha": future}
        )
    assert captured == []


def test_create_accepts_today_fecha() -> None:
    """fecha == today is accepted (sanity, no future rejection)."""
    today = date.today().isoformat()
    # Inject the test fecha into the mock so the round-trip holds
    # independently of the calendar (issue: CI broke 2026-07-05 UTC
    # when the mock's hardcoded fecha no longer matched today).
    client, _ = _client_recording(
        _handler_returns_rows([_row(fecha=today)])
    )

    actuacion = sanidad_service.create_actuacion_sanitaria(
        client, {**_params_minimal(), "fecha": today}
    )

    assert actuacion.fecha == today


# --- 5. D-24 regla 3 (atomic CTE check) ------------------------------------


def test_create_rejects_fecha_before_animal_fecha_alta() -> None:
    """CTE returns 0 rows because fecha_alta > fecha; disambiguation raises."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    client, _ = _client_recording(
        _handler_cascading(
            # 1st: CTE INSERT — 0 rows (fecha_alta filter rejects)
            [],
            # 2nd: animal disambiguation — exists, active, fecha_alta > fecha
            [
                {
                    "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "activo": True,
                    "fecha_alta": "2030-01-01T00:00:00Z",
                }
            ],
        )
    )

    with pytest.raises(
        ValueError,
        match="fecha es anterior al alta del animal",
    ):
        sanidad_service.create_actuacion_sanitaria(
            client,
            {**_params_minimal(), "fecha": yesterday},
        )


def test_create_accepts_fecha_before_null_fecha_alta() -> None:
    """Animal legacy with fecha_alta=NULL: D-24 regla 3 is skipped."""
    client, _ = _client_recording(
        _handler_returns_rows(
            [_row({"fecha": "2020-01-01"})]
        )
    )

    actuacion = sanidad_service.create_actuacion_sanitaria(
        client, {**_params_minimal(), "fecha": "2020-01-01"}
    )

    assert actuacion.fecha == "2020-01-01"


def test_create_accepts_fecha_equal_animal_fecha_alta() -> None:
    """Boundary: fecha == animal.fecha_alta is accepted (D-24 regla 3 uses <=)."""
    today_str = date.today().isoformat()
    # Inject the test fecha into the mock so the round-trip holds
    # independently of the calendar (same regression as
    # test_create_accepts_today_fecha; this is the D-24 regla 3
    # boundary case).
    client, _ = _client_recording(
        _handler_returns_rows([_row(fecha=today_str)])
    )

    actuacion = sanidad_service.create_actuacion_sanitaria(
        client, {**_params_minimal(), "fecha": today_str}
    )

    assert actuacion.fecha == today_str


# --- 6. Soft-delete (D-HEALTH-03) ------------------------------------------


def test_delete_returns_true_and_emits_log_for_active_row() -> None:
    """delete returns True when the row was active and was deactivated."""
    client, captured = _client_recording(_handler_returns_rows([{"id": "id-1"}]))

    deleted = sanidad_service.delete_actuacion_sanitaria(
        client, "id-1", actor_user_id="u-1"
    )

    assert deleted is True
    # The DELETE was emitted with id as the only param.
    assert len(captured) == 1
    assert captured[0]["params"] == ["id-1"]


def test_delete_returns_false_for_inactive_or_missing_row() -> None:
    """delete returns False when the row does not exist OR was inactive."""
    client, _ = _client_recording(_handler_returns_rows([]))

    deleted = sanidad_service.delete_actuacion_sanitaria(client, "missing-id")

    assert deleted is False


# --- 7. Update 404 path ---------------------------------------------------


def test_update_returns_none_for_missing_id() -> None:
    """update returns None when the id does not exist (UPDATE 0 rows + get empty)."""
    client, _ = _client_recording(
        _handler_cascading(
            # 1st: CTE UPDATE — 0 rows
            [],
            # 2nd: get_actuacion_sanitaria_by_id disambiguation — empty
            [],
        )
    )

    result = sanidad_service.update_actuacion_sanitaria(
        client, "missing-id", _params_minimal()
    )

    assert result is None


def test_update_raises_validation_error_when_animal_inactive() -> None:
    """update: id exists, but the new FK / D-24 check fails → specific ValueError."""
    client, _ = _client_recording(
        _handler_cascading(
            # 1st: CTE UPDATE — 0 rows (animal inactive)
            [],
            # 2nd: get_actuacion_sanitaria_by_id — exists
            [_row()],
            # 3rd: animal disambiguation (called by _raise_validation_error)
            [{"id": "a", "activo": False, "fecha_alta": None}],
        )
    )

    with pytest.raises(ValueError, match="animal_id debe apuntar"):
        sanidad_service.update_actuacion_sanitaria(
            client, "existing-id", _params_minimal()
        )


def test_update_rejects_fecha_before_animal_fecha_alta() -> None:
    """Update preserves D-24 regla 3 through the executable CTE shape."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    client, captured = _client_recording(
        _handler_cascading(
            # 1st: CTE UPDATE — 0 rows (fecha_alta filter rejects)
            [],
            # 2nd: get_actuacion_sanitaria_by_id — id exists
            [_row()],
            # 3rd: animal disambiguation — exists, active, fecha_alta > fecha
            [
                {
                    "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "activo": True,
                    "fecha_alta": "2030-01-01T00:00:00Z",
                }
            ],
        )
    )

    with pytest.raises(ValueError, match="fecha es anterior al alta del animal"):
        sanidad_service.update_actuacion_sanitaria(
            client,
            "existing-id",
            {**_params_minimal(), "fecha": yesterday},
        )

    update_query = captured[0]["query"]
    assert "FROM checked_animal" in update_query
    assert "checked_animal.fecha_alta::date <= $4::date" in update_query


# --- 8. List + filter (D-HEALTH-04) ----------------------------------------


def test_list_without_animal_id_uses_default_query() -> None:
    """list without animal_id runs the global list query."""
    client, captured = _client_recording(
        _handler_returns_rows([_row({"id": "id-1"})])
    )

    result = sanidad_service.list_actuaciones_sanitarias(client)

    assert len(result) == 1
    assert result[0].id == "id-1"


def test_list_with_animal_id_delegates_to_search_by_animal() -> None:
    """list with animal_id delegates to search_actuaciones_by_animal."""
    client, captured = _client_recording(
        _handler_returns_rows(
            [_row({"animal_id": "animal-X"}), _row({"id": "id-2", "animal_id": "animal-X"})]
        )
    )

    result = sanidad_service.list_actuaciones_sanitarias(
        client, animal_id="animal-X"
    )

    assert len(result) == 2
    assert all(a.animal_id == "animal-X" for a in result)


def test_search_by_animal_empty_id_returns_empty_without_db() -> None:
    """search_actuaciones_by_animal with empty id returns [] without hitting DB."""
    client, captured = _client_recording(_handler_returns_rows([]))

    assert sanidad_service.search_actuaciones_by_animal(client, "") == []
    assert sanidad_service.search_actuaciones_by_animal(client, "   ") == []
    assert sanidad_service.search_actuaciones_by_animal(client, None) == []
    assert captured == []  # no DB roundtrips


# --- 9. Mapping (CRITICAL coverage for CRITICAL_HELPERS rule) -------------


def test_row_to_actuacion_sanitaria_handles_optional_fields() -> None:
    """_row_to_actuacion_sanitaria coerces nullable + numeric/boolean fields."""
    row: dict[str, Any] = {
        "id": "id-1",
        "animal_id": "animal-1",
        "fecha": "2026-07-04",
        "voluntario_id": None,
        "tipo_actuacion_id": None,
        "veterinario": None,
        "observaciones": None,
        "material_utilizado": None,
        "fecha_alta": "2026-07-04T10:00:00Z",
        "updated_at": "2026-07-04T10:00:00Z",
        "activo": True,
    }

    actuacion = sanidad_service._row_to_actuacion_sanitaria(row)

    assert actuacion.id == "id-1"
    assert actuacion.voluntario_id is None
    assert actuacion.tipo_actuacion_id is None
    assert actuacion.veterinario is None
    assert actuacion.observaciones is None
    assert actuacion.material_utilizado is None
    assert actuacion.fecha_alta == "2026-07-04T10:00:00Z"
    assert actuacion.activo is True


def test_row_to_actuacion_sanitaria_coerces_string_uuid_fields() -> None:
    """UUID-typed columns are coerced to str even when DB returns UUID objects."""
    import uuid

    row: dict[str, Any] = {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "animal_id": uuid.UUID("22222222-2222-2222-2222-222222222222"),
        "fecha": "2026-07-04",
        "voluntario_id": uuid.UUID("33333333-3333-3333-3333-333333333333"),
        "tipo_actuacion_id": uuid.UUID("44444444-4444-4444-4444-444444444444"),
        "veterinario": "Dra. Pérez",
        "observaciones": "Vacuna",
        "material_utilizado": "Nobivac",
        "fecha_alta": "2026-07-04T10:00:00Z",
        "updated_at": "2026-07-04T10:00:00Z",
        "activo": True,
    }

    actuacion = sanidad_service._row_to_actuacion_sanitaria(row)

    assert actuacion.id == "11111111-1111-1111-1111-111111111111"
    assert actuacion.voluntario_id == "33333333-3333-3333-3333-333333333333"
    assert actuacion.tipo_actuacion_id == "44444444-4444-4444-4444-444444444444"


# --- 10. Mock helpers: fecha override (date-coupling regression) ---------
#
# CI broke on 2026-07-05 UTC because ``test_create_accepts_today_fecha`` and
# ``test_create_accepts_fecha_equal_animal_fecha_alta`` used ``date.today()``
# while the mock row hardcoded ``fecha: '2026-07-04'``. The two only happened
# to match on 2026-07-04 UTC. The fix is to make ``_row()`` parameterizable
# on ``fecha`` so date-coupling tests can inject the date they want to
# round-trip, instead of trusting the calendar. This test pins the contract
# so a future refactor cannot silently re-couple the helper to wall-clock.
#
# The test date "2020-01-01" is chosen because it is:
#  - In the past (D-24 regla 2 accepts it; "2099-12-31" would not).
#  - Far from any plausible UTC today (so it cannot accidentally match).
#  - Already used by test_create_accepts_fecha_before_null_fecha_alta,
#    so the convention is consistent across the file.


def test_sanidad_mock_helpers_let_caller_override_fecha() -> None:
    """_row() must accept a fecha override so date-coupling tests do not break
    when CI runs past UTC midnight.

    The contract: a caller can pass ``fecha="YYYY-MM-DD"`` and the mock row
    will echo it back. ``create_actuacion_sanitaria`` returns a row built
    from the mock, so the service-side fecha == caller fecha == mock fecha.
    """
    row = _row(fecha="2020-01-01")
    assert row["fecha"] == "2020-01-01"

    # Full create round-trip: the service must echo the input fecha, which
    # only holds when the mock and the input agree. This is the regression
    # the helper exists to prevent.
    client, _ = _client_recording(
        _handler_returns_rows([_row(fecha="2020-01-01")])
    )

    actuacion = sanidad_service.create_actuacion_sanitaria(
        client, {**_params_minimal(), "fecha": "2020-01-01"}
    )

    assert actuacion.fecha == "2020-01-01"
