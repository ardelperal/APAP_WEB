"""Service-layer tests for INTAKE-02 batch entradas.

The ``entradas.batch_service`` module owns:
- per-record validation against ``animales`` and ``voluntarios``
- cross-batch uniqueness of ``(animal_id, fecha_entrada)``
- atomic copy from ``entradas_batch_staging`` to ``entradas``
- staging lifecycle (stage -> preview -> commit -> staging empty;
  stage -> cancel -> staging empty)

The tests use a real ``LocalPostgresExecutor`` with an ``httpx.MockTransport`` so
they can assert SQL shape and params without network I/O, mirroring the
``tests/test_entradas.py`` pattern.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.core.data_access import BackendError
from app.core.local_backend.db import LocalPostgresExecutor
from app.modules.entradas import batch_service
from app.modules.entradas.service import Entrada


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
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=httpx.MockTransport(_recording_handler),
    )
    return client, captured


def _record(idx: int, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "animal_id": f"00000000-0000-0000-0000-{idx:012d}",
        "voluntario_entrada_id": None,
        "fecha_entrada": f"2026-07-{(idx % 28) + 1:02d}",
        "origen": "Albergue",
        "motivo": "Rescate",
        "observaciones": None,
    }
    base.update(overrides)
    return base


def _staging_row(batch_id: str, sequence: int, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "batch_id": batch_id,
        "sequence": sequence,
        "animal_id": f"00000000-0000-0000-0000-{sequence:012d}",
        "voluntario_entrada_id": None,
        "fecha_entrada": f"2026-07-{(sequence % 28) + 1:02d}",
        "origen": "Albergue",
        "motivo": "Rescate",
        "observaciones": None,
        "created_at": "2026-07-04T10:00:00Z",
    }
    base.update(overrides)
    return base


def _staging_handler(
    valid_batch_id: str,
    staging_rows: list[dict[str, Any]],
    insert_response_rows: list[dict[str, Any]] | None = None,
    animals_by_id: dict[str, bool] | None = None,
    volunteers_by_id: dict[str, bool] | None = None,
    fail_on_commit_with: tuple[int, dict[str, Any]] | None = None,
) -> Callable[[httpx.Request, dict[str, Any]], httpx.Response]:
    """Build a flexible handler for batch flow tests.

    - ``valid_batch_id``: the batch_id that staging SELECT returns rows for.
    - ``staging_rows``: rows returned by the staging SELECT.
    - ``insert_response_rows``: rows returned by the COMMIT CTE.
    - ``animals_by_id`` / ``volunteers_by_id``: maps for FK validation.
    - ``fail_on_commit_with``: tuple of (status, body) to return on the
      commit CTE call, simulating a natural-key violation or FK error.
    """
    animals_by_id = animals_by_id or {}
    volunteers_by_id = volunteers_by_id or {}

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        query = body["query"]
        params = body.get("params", [])

        if "FROM animales" in query:
            animal_id = params[0] if params else ""
            exists = animals_by_id.get(animal_id, True)
            if not exists:
                return _json_response(200, [])
            return _json_response(200, [{"id": animal_id, "activo": True}])

        if "FROM voluntarios" in query:
            vol_id = params[0] if params else ""
            exists = volunteers_by_id.get(vol_id, True)
            if not exists:
                return _json_response(200, [])
            return _json_response(200, [{"id": vol_id, "activo": True}])

        if "INSERT INTO entradas_batch_staging" in query:
            return _json_response(200, [])

        if query.strip().upper().startswith("SELECT") and "FROM entradas_batch_staging" in query:
            requested_batch = params[0] if params else ""
            if requested_batch != valid_batch_id:
                return _json_response(200, [])
            return _json_response(200, staging_rows)

        if "WITH inserted AS" in query:
            if fail_on_commit_with is not None:
                status, fail_body = fail_on_commit_with
                return _json_response(status, fail_body)
            return _json_response(200, insert_response_rows or [])

        if "DELETE FROM entradas_batch_staging" in query:
            return _json_response(200, [{"batch_id": params[0] if params else ""}])

        raise AssertionError(f"Unexpected SQL: {query[:200]}")

    return _handler


# --- stage_batch: happy path ----------------------------------------------


def animals_key(idx: int) -> str:
    return f"00000000-0000-0000-0000-{idx:012d}"


def test_stage_batch_writes_staging_rows_and_returns_batch_id() -> None:
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        query = body["query"]
        params = body.get("params", [])
        if "FROM animales" in query:
            return _json_response(200, [{"id": params[0], "activo": True}])
        if "INSERT INTO entradas_batch_staging" in query:
            return _json_response(200, [])
        raise AssertionError(f"Unexpected SQL: {query}")

    client, captured = _client_recording(_handler)

    records = [_record(1, animal_id=animals_key(1)), _record(2, animal_id=animals_key(2))]
    result = batch_service.stage_batch(client, records)
    client.close()

    assert isinstance(result, batch_service.BatchStaging)
    assert isinstance(result.batch_id, str) and len(result.batch_id) == 36
    assert len(result.records) == 2
    assert all(r.status == "valid" for r in result.records)

    insert_calls = [c for c in captured if "INSERT INTO entradas_batch_staging" in c["query"]]
    assert len(insert_calls) == 2
    assert insert_calls[0]["params"][1] == 1  # sequence 1
    assert insert_calls[1]["params"][1] == 2  # sequence 2


# --- stage_batch: cross-batch uniqueness ---------------------------------


def test_stage_batch_rejects_cross_batch_duplicate_before_writing() -> None:
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        raise AssertionError(f"no SQL should run for cross-batch duplicate: {body['query']}")

    client, captured = _client_recording(_handler)

    duplicate_animal = animals_key(99)
    records = [
        _record(1, animal_id=duplicate_animal, fecha_entrada="2026-07-15"),
        _record(2, animal_id=duplicate_animal, fecha_entrada="2026-07-15"),
    ]

    with pytest.raises(batch_service.BatchValidationError, match="Animal duplicado en el lote"):
        batch_service.stage_batch(client, records)
    client.close()

    assert captured == []


def test_stage_batch_rejects_cross_batch_duplicate_inverse_order() -> None:
    """Cross-batch detection runs regardless of the operator's input order."""
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        raise AssertionError("no SQL should run for cross-batch duplicate")

    client, captured = _client_recording(_handler)
    duplicate_animal = animals_key(42)
    records = [
        _record(1, animal_id=duplicate_animal, fecha_entrada="2026-07-15"),
        _record(2, animal_id=animals_key(2), fecha_entrada="2026-07-15"),
        _record(3, animal_id=duplicate_animal, fecha_entrada="2026-07-15"),
    ]

    with pytest.raises(batch_service.BatchValidationError):
        batch_service.stage_batch(client, records)
    client.close()

    assert captured == []


# --- stage_batch: per-record errors are non-fatal ------------------------


def test_stage_batch_records_per_record_validation_errors_without_aborting() -> None:
    valid_animal = animals_key(1)
    invalid_animal = animals_key(999)

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        query = body["query"]
        params = body.get("params", [])
        if "FROM animales" in query:
            if params[0] == invalid_animal:
                return _json_response(200, [])
            return _json_response(200, [{"id": params[0], "activo": True}])
        if "INSERT INTO entradas_batch_staging" in query:
            return _json_response(200, [])
        raise AssertionError(f"Unexpected SQL: {query}")

    client, captured = _client_recording(_handler)

    records = [
        _record(1, animal_id=valid_animal),
        _record(2, animal_id=invalid_animal),
    ]
    result = batch_service.stage_batch(client, records)
    client.close()

    assert len(result.records) == 2
    statuses = {r.params["animal_id"]: (r.status, r.error) for r in result.records}
    assert statuses[valid_animal][0] == "valid"
    assert statuses[valid_animal][1] is None
    assert statuses[invalid_animal][0] == "invalid"
    assert "animal_id" in statuses[invalid_animal][1]


# --- stage_batch: required fields per record -----------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("animal_id", ""),
        ("fecha_entrada", ""),
    ],
)
def test_stage_batch_rejects_required_field_in_record(field: str, value: str) -> None:
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        raise AssertionError("no SQL should run when a required field is empty")

    client, captured = _client_recording(_handler)

    records = [_record(1, **{field: value})]
    result = batch_service.stage_batch(client, records)
    client.close()

    assert len(result.records) == 1
    assert result.records[0].status == "invalid"
    assert field in result.records[0].error
    assert captured == []


# --- commit_batch: atomic copy staging -> entradas -----------------------


def test_commit_batch_copies_staging_to_entradas_atomically_and_clears_staging() -> None:
    batch_id = "11111111-1111-1111-1111-111111111111"
    staging_rows = [
        _staging_row(batch_id, 1, animal_id=animals_key(1), fecha_entrada="2026-07-15"),
        _staging_row(batch_id, 2, animal_id=animals_key(2), fecha_entrada="2026-07-16"),
    ]
    inserted_rows = [
        {
            "id": "ent-1",
            "animal_id": animals_key(1),
            "voluntario_entrada_id": None,
            "fecha_entrada": "2026-07-15",
            "origen": "Albergue",
            "motivo": "Rescate",
            "observaciones": None,
            "fecha_alta": "2026-07-04T10:00:00Z",
            "updated_at": "2026-07-04T10:00:00Z",
            "activo": True,
        },
        {
            "id": "ent-2",
            "animal_id": animals_key(2),
            "voluntario_entrada_id": None,
            "fecha_entrada": "2026-07-16",
            "origen": "Albergue",
            "motivo": "Rescate",
            "observaciones": None,
            "fecha_alta": "2026-07-04T10:00:00Z",
            "updated_at": "2026-07-04T10:00:00Z",
            "activo": True,
        },
    ]

    handler = _staging_handler(
        valid_batch_id=batch_id,
        staging_rows=staging_rows,
        insert_response_rows=inserted_rows,
    )
    client, captured = _client_recording(handler)

    result = batch_service.commit_batch(client, batch_id)
    client.close()

    assert isinstance(result, list)
    assert len(result) == 2
    assert all(isinstance(e, Entrada) for e in result)
    assert [e.id for e in result] == ["ent-1", "ent-2"]

    commit_call = next(c for c in captured if "WITH inserted AS" in c["query"])
    assert commit_call["params"] == [batch_id]
    assert "INSERT INTO entradas" in commit_call["query"]
    assert "FROM entradas_batch_staging" in commit_call["query"]
    assert "DELETE FROM entradas_batch_staging" in commit_call["query"]


def test_commit_batch_raises_conflict_when_db_violates_natural_key() -> None:
    batch_id = "22222222-2222-2222-2222-222222222222"
    staging_rows = [_staging_row(batch_id, 1, animal_id=animals_key(1))]

    handler = _staging_handler(
        valid_batch_id=batch_id,
        staging_rows=staging_rows,
        insert_response_rows=None,
        fail_on_commit_with=(
            409,
            {"error": "duplicate key value violates unique constraint entradas_natural_key"},
        ),
    )
    client, captured = _client_recording(handler)

    with pytest.raises(batch_service.EntradaConflictError, match="entrada duplicada"):
        batch_service.commit_batch(client, batch_id)
    client.close()


def test_commit_batch_propagates_unsupported_insforge_error() -> None:
    batch_id = "33333333-3333-3333-3333-333333333333"
    staging_rows = [_staging_row(batch_id, 1, animal_id=animals_key(1))]

    handler = _staging_handler(
        valid_batch_id=batch_id,
        staging_rows=staging_rows,
        fail_on_commit_with=(500, {"error": "kaboom"}),
    )
    client, captured = _client_recording(handler)

    with pytest.raises(BackendError):
        batch_service.commit_batch(client, batch_id)
    client.close()


def test_commit_batch_returns_empty_when_no_staging_rows() -> None:
    handler = _staging_handler(
        valid_batch_id="any-id",
        staging_rows=[],
        insert_response_rows=[],
    )
    client, captured = _client_recording(handler)

    result = batch_service.commit_batch(client, "any-id")
    client.close()

    assert result == []
    assert not any("WITH inserted AS" in c["query"] for c in captured)


# --- cancel_batch: cleans up staging --------------------------------------


def test_cancel_batch_deletes_staging_rows_for_batch() -> None:
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [{"batch_id": body["params"][0]}])

    client, captured = _client_recording(_handler)

    batch_service.cancel_batch(client, "batch-abc")
    client.close()

    delete_call = captured[-1]
    assert "DELETE FROM entradas_batch_staging" in delete_call["query"]
    assert delete_call["params"] == ["batch-abc"]


# --- get_batch: returns preview or None -----------------------------------


def test_get_batch_returns_preview_with_staged_records() -> None:
    batch_id = "44444444-4444-4444-4444-444444444444"
    staging_rows = [
        _staging_row(batch_id, 1, animal_id=animals_key(1)),
        _staging_row(batch_id, 2, animal_id=animals_key(2)),
    ]

    handler = _staging_handler(
        valid_batch_id=batch_id,
        staging_rows=staging_rows,
    )
    client, captured = _client_recording(handler)

    result = batch_service.get_batch(client, batch_id)
    client.close()

    assert result is not None
    assert result.batch_id == batch_id
    assert len(result.records) == 2
    assert [r.sequence for r in result.records] == [1, 2]
    assert all(r.status == "valid" for r in result.records)


def test_get_batch_returns_none_when_batch_id_unknown() -> None:
    handler = _staging_handler(
        valid_batch_id="other",
        staging_rows=[],
    )
    client, captured = _client_recording(handler)

    result = batch_service.get_batch(client, "missing-batch-id")
    client.close()

    assert result is None
