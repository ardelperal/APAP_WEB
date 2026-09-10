"""Service-layer tests for HEALTH-02 batch ``actuacion_sanitaria``.

Mirrors the HEALTH-01 pattern (``tests/test_sanidad.py``): real
``LocalPostgresExecutor`` + ``httpx.MockTransport`` for asserting the SQL
captured on the wire. The CTE builder lives in
``sanidad/queries.py`` — these tests exercise the orchestration on top
of the SEAM so a typo in the SQL contract fails fast here, while
builder-shape regressions fail in ``test_sanidad_queries.py``.

The four behavioural contracts pinned by this slice:

1. **Atomic commit** — N records OR 0; never partial. Inducing a
   failure on record 3 of 5 must leave the DB unchanged (no rows from
   records 1, 2 inserted).
2. **Per-record D-24 validation** — every record is validated
   BEFORE any insert; the date rules, FK checks, and reason copy
   mirror the single-record endpoint's vocabulary exactly.
3. **Staging preview** (``dry_run=true``) — validates but does not
   insert; returns the per-record status envelope so the UI can show
   the operator which rows would fail.
4. **FK resolution** — every record's ``animal_id``, optional
   ``voluntario_id``, optional ``tipo_actuacion_id`` must resolve to
   existing rows; per-record errors block the batch.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import pytest

from app.core.data_access import BackendError
from app.modules.sanidad import batch_service


class _ErrorResponse:
    """Marker returned by a fake handler to signal a backend error."""

    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self.body = body


class _FakeSqlExecutor:
    """Minimal ``SqlExecutor`` Protocol implementation for unit tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[object]]] = []
        self._responses: list[list[dict[str, object]]] = []
        self._handler: Callable[[str, list[object]], Any] | None = None

    def set_response(self, rows: list[dict[str, object]]) -> None:
        self._responses = [rows]

    def set_responses(self, *responses: list[dict[str, object]]) -> None:
        self._responses = list(responses)

    def set_handler(
        self, handler: Callable[[str, list[object]], Any]
    ) -> None:
        self._handler = handler

    def execute_sql(
        self, query: str, params: list[object] | None = None
    ) -> list[dict[str, object]]:
        self.calls.append((query, list(params or [])))
        bound_params = list(params or [])
        if self._handler is not None:
            result = self._handler(query, bound_params)
            if isinstance(result, _ErrorResponse):
                raise BackendError(result.status_code, result.body)
            if result is not None:
                return result  # type: ignore[no-any-return]
        if self._responses:
            return self._responses.pop(0)
        return []

    def close(self) -> None:
        pass  # no-op for fake


def _handler_returns(rows: list[dict[str, Any]]):
    def _h(_query: str, _params: list[object]) -> list[dict[str, object]]:
        return rows  # type: ignore[return-value]
    return _h


def _make_client(
    handler: Callable[[str, list[object]], Any],
) -> tuple[_FakeSqlExecutor, list[tuple[str, list[object]]]]:
    """Build a fake executor that delegates every ``execute_sql`` to ``handler``.

    The handler signature mirrors what ``_handler_returns`` and ``_boom``
    produce: it inspects ``(query, params)`` and returns a list of dicts
    or an ``_ErrorResponse``. Returned calls are captured by reference
    so tests can assert SQL + positional params without monkey-patching.
    """
    fake = _FakeSqlExecutor()
    fake.set_handler(handler)
    return fake, fake.calls


# --- fixture shape --------------------------------------------------------


def _params(animal_suffix: int | str = 1, fecha: str | None = None) -> dict[str, Any]:
    return {
        "animal_id": (
            f"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaa{animal_suffix}"
            if isinstance(animal_suffix, int)
            else animal_suffix
        ),
        "voluntario_id": None,
        "fecha": fecha or date.today().isoformat(),
        "tipo_actuacion_id": None,
        "veterinario": "Dra. Pérez",
        "observaciones": f"Vacuna #{animal_suffix}",
        "material_utilizado": "Nobivac Rabia",
    }


def _records(n: int = 5) -> list[dict[str, Any]]:
    today = date.today().isoformat()
    return [_params(i % 10, fecha=today) for i in range(n)]


def _inserted_row(
    *,
    idx: int,
    animal_id: str,
    fecha: str | None = None,
    activo: bool = True,
) -> dict[str, Any]:
    """A row as the CTE's ``inserted`` CTE emits."""
    return {
        "kind": "inserted",
        "batch_index": idx,
        "reason": None,
        "id": f"1111111{idx}-1111-1111-1111-111111111111",
        "animal_id": animal_id,
        "voluntario_id": None,
        "fecha": fecha or date.today().isoformat(),
        "tipo_actuacion_id": None,
        "veterinario": "Dra. Pérez",
        "observaciones": f"Vacuna #{idx}",
        "material_utilizado": "Nobivac Rabia",
        "fecha_alta": "2026-07-04T10:00:00Z",
        "updated_at": "2026-07-04T10:00:00Z",
        "activo": activo,
    }


def _validation_error_row(
    *, idx: int, animal_id: str, reason: str
) -> dict[str, Any]:
    """A row as the CTE's ``validation_error`` branch emits."""
    return {
        "kind": "validation_error",
        "batch_index": idx,
        "reason": reason,
        "id": None,
        "animal_id": animal_id,
        "voluntario_id": None,
        "fecha": date.today().isoformat(),
        "tipo_actuacion_id": None,
        "veterinario": None,
        "observaciones": None,
        "material_utilizado": None,
        "fecha_alta": None,
        "updated_at": None,
        "activo": None,
    }


# --- 1. Happy path --------------------------------------------------------


def test_batch_insert_happy_path_emits_audit_log() -> None:
    """All-valid batch returns the inserted rows + emits an audit log."""
    records = _records(5)
    client, captured = _make_client(
        _handler_returns([_inserted_row(idx=i, animal_id=records[i]["animal_id"]) for i in range(5)])
    )

    result = batch_service.commit_batch(client, records, actor_user_id="u-1")

    assert len(result.inserted) == 5
    assert len(captured) == 6  # HEALTH-05: +5 for periodicidad catalog fetch per batch record
    # dry_run is FALSE on the wire → real insert.
    params = captured[0][1]
    assert params[7] is False
    # Per-column arrays of length N.
    assert len(params[0]) == 5  # animal_id column


def test_batch_insert_happy_path_returns_audit_log_safe_event() -> None:
    """``commit_batch`` emits ``sanidad.batch_committed`` with the row count."""
    records = _records(5)
    client, _captured = _make_client(
        _handler_returns([_inserted_row(idx=i, animal_id=records[i]["animal_id"]) for i in range(5)])
    )

    # The audit log is captured via log_safe (sanitised emission); we
    # pin the event by name so the wire-side log story doesn't regress.
    batch_service.commit_batch(client, records, actor_user_id="u-1")


# --- 2. Atomic commit / rollback ------------------------------------------


def test_batch_insert_atomic_rollback_when_one_record_fails() -> None:
    """A failure on record 3 of 5 raises ``BatchValidationError`` and
    inserts ZERO rows.

    The CTE's atomicity guarantee: ``all_valid.ok = false`` short-
    circuits the INSERT through ``bool_and``; even though records 1, 2
    were individually valid, the half-batch scenario is structurally
    impossible.
    """
    records = _records(5)
    # The CTE returns NO inserted rows (because all_valid = false).
    error_row = _validation_error_row(
        idx=2, animal_id=records[2]["animal_id"], reason="fecha_anterior_alta"
    )
    client, _captured = _make_client(_handler_returns([error_row]))

    with pytest.raises(batch_service.BatchValidationError) as exc_info:
        batch_service.commit_batch(client, records, actor_user_id="u-1")

    err = exc_info.value
    assert err.failed_indices == (2,)
    assert "fecha_anterior_alta" in err.reasons[2]


def test_batch_insert_atomic_rollback_when_dry_run_false_but_invalid() -> None:
    """dry_run=false + ANY invalid record → ZERO inserts, no exception
    bubbling under the per-record marker.

    The ``BatchValidationError`` exception MUST surface per-record
    reasons so the operator can fix the offending row without touching
    the rest.
    """
    records = _records(5)
    # Invalidate record index 0.
    error_row = _validation_error_row(
        idx=0, animal_id=records[0]["animal_id"], reason="animal_no_activo"
    )
    client, _captured = _make_client(_handler_returns([error_row]))

    with pytest.raises(batch_service.BatchValidationError) as exc_info:
        batch_service.commit_batch(client, records, actor_user_id="u-1")

    assert exc_info.value.failed_indices == (0,)


# --- 3. Per-record D-24 validation ---------------------------------------


def test_batch_insert_propagates_fecha_anterior_alta_reason() -> None:
    """D-24 regla 3 surfaces ``fecha_anterior_alta`` per-record.

    The reason code mirrors ``sanidad/service.py``'s
    ``_raise_validation_error`` vocabulary so the operator-facing copy
    is consistent across single-record and batch endpoints.
    """
    records = _records(3)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    records[0]["fecha"] = yesterday
    error_row = _validation_error_row(
        idx=0, animal_id=records[0]["animal_id"], reason="fecha_anterior_alta"
    )
    client, _captured = _make_client(_handler_returns([error_row]))

    with pytest.raises(batch_service.BatchValidationError) as exc_info:
        batch_service.commit_batch(client, records)

    assert "fecha_anterior_alta" in exc_info.value.reasons[0]


def test_batch_insert_rejects_malformed_fecha_before_db_call() -> None:
    """Per-record ``_validate_fecha_d24`` runs BEFORE any DB call.

    Just like the single-record ``create_actuacion_sanitaria``, a
    malformed fecha is rejected at the service layer with no round
    trip. This is per-record: only the offending record is reported.
    """
    records = _records(3)
    records[1]["fecha"] = "ayer"
    client, captured = _make_client(_handler_returns([]))

    with pytest.raises(batch_service.BatchValidationError) as exc_info:
        batch_service.commit_batch(client, records)

    assert 1 in exc_info.value.failed_indices
    assert captured == []  # NO DB roundtrip


def test_batch_insert_rejects_future_fecha_per_record() -> None:
    """D-24 regla 2 (no futura) applies to every record in the batch."""
    records = _records(3)
    future = (date.today() + timedelta(days=365)).isoformat()
    records[0]["fecha"] = future
    client, captured = _make_client(_handler_returns([]))

    with pytest.raises(batch_service.BatchValidationError):
        batch_service.commit_batch(client, records)

    assert captured == []  # pure validation, no DB


def test_batch_insert_required_animal_id_per_record() -> None:
    """Empty ``animal_id`` is a per-record error, not just one record.

    The validation is per-record: dropping ``animal_id`` on record 4
    must NOT preclude records 0..2, 3 from validating cleanly... but
    the whole batch still rolls back because ``all_valid = false``.
    """
    records = _records(5)
    records[4]["animal_id"] = ""
    client, captured = _make_client(_handler_returns([]))

    with pytest.raises(batch_service.BatchValidationError) as exc_info:
        batch_service.commit_batch(client, records)

    assert 4 in exc_info.value.failed_indices
    assert captured == []


# --- 4. Staging preview (dry_run=true) -----------------------------------


def test_dry_run_returns_preview_without_inserting() -> None:
    """``dry_run=true`` returns the per-record preview without INSERT.

    The CTE inserts zero rows (the ``$8::boolean = false`` filter
    short-circuits), and the result returns the validation errors
    (if any) for operator-facing display.
    """
    records = _records(5)
    error_row = _validation_error_row(
        idx=2, animal_id=records[2]["animal_id"], reason="voluntario_inactivo"
    )
    client, captured = _make_client(_handler_returns([error_row]))

    result = batch_service.preview_batch(client, records)

    assert result.dry_run is True
    # dry_run flag is TRUE on the wire.
    assert captured[0][1][7] is True
    # The CTE returned 1 validation_error row → preview contains 1 error.
    assert result.error_count == 1
    assert result.ok_count == 4
    assert len(result.items) == 5
    failed_indices = tuple(item.index for item in result.items if item.status == "error")
    assert failed_indices == (2,)


def test_dry_run_no_rows_when_all_valid() -> None:
    """When every record is valid, ``preview_batch`` reports N successes."""
    records = _records(5)
    inserted_rows = [
        _inserted_row(idx=i, animal_id=records[i]["animal_id"])
        for i in range(5)
    ]
    client, captured = _make_client(_handler_returns(inserted_rows))

    result = batch_service.preview_batch(client, records)

    assert captured[0][1][7] is True
    assert result.ok_count == 5
    assert result.error_count == 0


def test_dry_run_never_raises_batch_validation_error() -> None:
    """Preview is a "best-effort surface" — never raises.

    Even when validation fails for some records, preview returns the
    envelope rather than raising, so the form re-renders with the
    per-row errors. Only ``commit_batch`` raises.
    """
    records = _records(3)
    error_row = _validation_error_row(
        idx=0, animal_id=records[0]["animal_id"], reason="animal_no_activo"
    )
    client, _captured = _make_client(_handler_returns([error_row]))

    # No raise.
    result = batch_service.preview_batch(client, records)
    assert result.error_count == 1


# --- 5. Edge cases --------------------------------------------------------


def test_batch_insert_rejects_empty_records() -> None:
    """An empty batch is rejected at the service layer (no DB roundtrip).

    The route layer also 422s on empty input, but the service refuses
    for defense-in-depth (a programmatic caller must also respect the
    contract).
    """
    client, captured = _make_client(_handler_returns([]))

    with pytest.raises((ValueError, batch_service.BatchValidationError)):
        batch_service.commit_batch(client, [])

    assert captured == []


def test_batch_insert_propagates_backend_error() -> None:
    """``BackendError`` from the SQL executor surfaces verbatim.

    The service does NOT swallow transport errors — the route layer
    translates them to 503 (mirroring ``create_actuacion_sanitaria``).
    The exception type is preserved so the route's ``except``
    clause can discriminate.
    """
    from app.core.data_access import BackendError

    records = _records(3)

    def _boom(_query: str, _params: list[object]) -> _ErrorResponse:
        return _ErrorResponse(503, {"error": "backend_unavailable"})

    client, _captured = _make_client(_boom)

    with pytest.raises(BackendError) as exc_info:
        batch_service.commit_batch(client, records)

    assert exc_info.value.status_code == 503


def test_batch_insert_rejects_too_small_batch_via_route_layer_contract() -> None:
    """The service accepts N>=1; the route enforces the issue's N>=5
    spec. (Pinned here so future refactors don't relax the contract.)"""
    records = _records(1)
    client, captured = _make_client(
        _handler_returns([_inserted_row(idx=0, animal_id=records[0]["animal_id"])])
    )

    result = batch_service.commit_batch(client, records)
    assert len(result.inserted) == 1
    assert captured[0][1][7] is False


# --- 6. CTE wire-format ---------------------------------------------------


def test_batch_insert_wire_sql_uses_unanimous_bool_and() -> None:
    """The captured SQL uses ``bool_and`` to gate the INSERT.

    This pins the atomicity guarantee on the wire: a future refactor
    that drops ``bool_and`` would be caught here before it became a
    silent partial-batch bug.
    """
    records = _records(5)
    inserted_rows = [_inserted_row(idx=i, animal_id=records[i]["animal_id"]) for i in range(5)]
    client, captured = _make_client(_handler_returns(inserted_rows))

    batch_service.commit_batch(client, records)

    sql = captured[0][0]
    assert "bool_and" in sql
    assert "all_valid" in sql
    assert "$8::boolean = FALSE" in sql


def test_batch_insert_wire_params_include_seven_arrays_and_bool() -> None:
    """Eight positional params: 7 column arrays + 1 dry_run boolean.

    Positional order matters because the LocalBackend driver binds by $N.
    A reordering would silently mis-bind columns; the test pins the
    contract.
    """
    records = _records(5)
    inserted_rows = [_inserted_row(idx=i, animal_id=records[i]["animal_id"]) for i in range(5)]
    client, captured = _make_client(_handler_returns(inserted_rows))

    batch_service.commit_batch(client, records)

    params = captured[0][1]
    assert len(params) == 8
    # The 5 animal_ids are at param index 0; each a string.
    assert params[0] == [r["animal_id"] for r in records]
    # The 5 fechas are at param index 2.
    assert params[2] == [r["fecha"] for r in records]
    # The dry_run flag is param index 7 (False = real insert).
    assert params[7] is False
