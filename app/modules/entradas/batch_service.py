"""Service layer for INTAKE-02 batch entradas (Entradas Múltiples).

Mirrors the legacy ``TbEntradasMultiplesAuxIniciales`` pre-commit staging
pattern (discovery 2.1, ``docs/discovery/feature-02-intake-foster-adoption.md``).
The flow is:

1. ``stage_batch(client, records)`` — validates per-record FKs against
   ``animales`` / ``voluntarios`` and cross-batch uniqueness of
   ``(animal_id, fecha_entrada)``. Per-record errors are surfaced as
   ``BatchRecord(status="invalid", error=...)`` without aborting the
   rest of the batch. Cross-batch duplicates raise ``BatchValidationError``
   BEFORE any DB write.
2. ``get_batch(client, batch_id)`` — preview of staged records.
3. ``commit_batch(client, batch_id)`` — atomic copy of staging rows
   into ``entradas`` via a single CTE statement. PostgreSQL runs the
   CTE as one logical operation, so any failure (FK violation,
   ``entradas_natural_key`` violation) rollback the entire copy AND
   leaves staging intact. The same statement DELETEs the staging rows
   on success.
4. ``cancel_batch(client, batch_id)`` — explicit cleanup of staging
   without committing.

The service is deliberately framework-agnostic: routes parse HTTP and
render templates; SQL, validation, mapping, and the staging lifecycle
all live here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from app.core.data_access import SqlExecutor
from app.core.data_access import BackendError
from app.modules.entradas.service import (
    Entrada,
    EntradaConflictError,
    is_duplicate_error,
    row_to_entrada,
)


@dataclass(frozen=True, slots=True)
class BatchRecord:
    """One record in a batch staging preview."""

    sequence: int
    params: dict[str, Any]
    status: Literal["valid", "invalid"]
    error: str | None = None


@dataclass(frozen=True, slots=True)
class BatchStaging:
    """A staged batch with its preview rows."""

    batch_id: str
    created_at: str | None
    records: tuple[BatchRecord, ...]


class BatchValidationError(ValueError):
    """Raised when the entire batch is rejected before staging.

    The single canonical case today is cross-batch duplication of
    ``(animal_id, fecha_entrada)`` — the operator must fix the input
    before any DB write happens.
    """


_INSERT_STAGING_SQL = """
INSERT INTO entradas_batch_staging (
    batch_id, sequence, animal_id, voluntario_entrada_id,
    fecha_entrada, origen, motivo, observaciones
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
"""

_GET_STAGING_SQL = """
SELECT
    batch_id, sequence, animal_id, voluntario_entrada_id,
    fecha_entrada, origen, motivo, observaciones, created_at
FROM entradas_batch_staging
WHERE batch_id = $1
ORDER BY sequence
"""

# Atomic commit: copy staging rows into ``entradas`` and DELETE the
# staging rows in the same statement. PostgreSQL runs the CTE as one
# logical operation, so any FK violation / ``entradas_natural_key``
# violation aborts the copy AND leaves staging rows intact for the
# operator to inspect via ``get_batch``.
_COMMIT_BATCH_SQL = """
WITH inserted AS (
    INSERT INTO entradas (
        animal_id, voluntario_entrada_id, fecha_entrada,
        origen, motivo, observaciones
    )
    SELECT
        animal_id, voluntario_entrada_id, fecha_entrada,
        origen, motivo, observaciones
    FROM entradas_batch_staging
    WHERE batch_id = $1
    ORDER BY sequence
    RETURNING
        id, animal_id, voluntario_entrada_id, fecha_entrada,
        origen, motivo, observaciones, fecha_alta, updated_at, activo
),
deleted AS (
    DELETE FROM entradas_batch_staging
    WHERE batch_id = $1
    RETURNING batch_id
)
SELECT
    i.id, i.animal_id, i.voluntario_entrada_id, i.fecha_entrada,
    i.origen, i.motivo, i.observaciones, i.fecha_alta, i.updated_at, i.activo
FROM inserted i
ORDER BY i.fecha_alta, i.id
"""

_CANCEL_BATCH_SQL = """
DELETE FROM entradas_batch_staging WHERE batch_id = $1
"""

_CHECK_ANIMAL_SQL = """
SELECT id, activo FROM animales WHERE id = $1
"""

_CHECK_ACTIVE_VOLUNTEER_SQL = """
SELECT id, activo FROM voluntarios WHERE id = $1 AND activo = true
"""


def _required_text(params: dict[str, Any], field_name: str) -> str:
    value = str(params.get(field_name) or "").strip()
    if not value:
        raise ValueError(f"{field_name} is required and cannot be empty")
    return value


def _optional_text(params: dict[str, Any], field_name: str) -> str | None:
    value = params.get(field_name)
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _validate_references(client: SqlExecutor, params: dict[str, Any]) -> str | None:
    """Return an error message if FK validation fails, else None."""
    animal_id = _required_text(params, "animal_id")
    if not client.execute_sql(_CHECK_ANIMAL_SQL, [animal_id]):
        return "animal_id no existe"

    voluntario_id = _optional_text(params, "voluntario_entrada_id")
    if voluntario_id and not client.execute_sql(
        _CHECK_ACTIVE_VOLUNTEER_SQL, [voluntario_id]
    ):
        return "voluntario no está activo"
    return None


def _check_cross_batch_uniqueness(records: list[dict[str, Any]]) -> None:
    """Reject the whole batch if two records share the same natural key.

    Records with empty ``animal_id`` or ``fecha_entrada`` are skipped —
    those errors surface as per-record validation messages in the
    preview. Operative batches are <100 records so the O(N) check is
    negligible.
    """
    seen: set[tuple[str, str]] = set()
    for record in records:
        animal_id_raw = record.get("animal_id")
        fecha_raw = record.get("fecha_entrada")
        if not animal_id_raw or not fecha_raw:
            continue
        animal_id = str(animal_id_raw).strip()
        fecha_entrada = str(fecha_raw).strip()
        if not animal_id or not fecha_entrada:
            continue
        key = (animal_id, fecha_entrada)
        if key in seen:
            raise BatchValidationError(
                "Animal duplicado en el lote: "
                f"animal_id={animal_id} fecha_entrada={fecha_entrada}"
            )
        seen.add(key)


def stage_batch(client: SqlExecutor, records: list[dict[str, Any]]) -> BatchStaging:
    """Stage a batch of entrada records.

    - Cross-batch uniqueness is checked FIRST (in-memory) — duplicates
      raise ``BatchValidationError`` and NO DB write happens.
    - Per-record required-field and FK validation runs against the DB;
      failures populate ``BatchRecord.error`` and ``status="invalid"``
      without aborting the rest of the batch.
    - Each valid record is INSERTed into ``entradas_batch_staging`` with
      a fresh ``batch_id`` and a sequence number preserving operator
      input order.
    """
    _check_cross_batch_uniqueness(records)

    batch_id = str(uuid.uuid4())
    staged: list[BatchRecord] = []
    for sequence, record in enumerate(records, start=1):
        params = {
            "animal_id": _optional_text(record, "animal_id"),
            "voluntario_entrada_id": _optional_text(record, "voluntario_entrada_id"),
            "fecha_entrada": _optional_text(record, "fecha_entrada"),
            "origen": _optional_text(record, "origen"),
            "motivo": _optional_text(record, "motivo"),
            "observaciones": _optional_text(record, "observaciones"),
        }

        try:
            animal_id = _required_text(params, "animal_id")
            fecha_entrada = _required_text(params, "fecha_entrada")
        except ValueError as exc:
            staged.append(
                BatchRecord(
                    sequence=sequence,
                    params=params,
                    status="invalid",
                    error=str(exc),
                )
            )
            continue

        error = _validate_references(client, params)
        if error is not None:
            staged.append(
                BatchRecord(
                    sequence=sequence,
                    params=params,
                    status="invalid",
                    error=error,
                )
            )
            continue

        client.execute_sql(
            _INSERT_STAGING_SQL,
            [
                batch_id,
                sequence,
                animal_id,
                _optional_text(params, "voluntario_entrada_id"),
                fecha_entrada,
                _optional_text(params, "origen"),
                _optional_text(params, "motivo"),
                _optional_text(params, "observaciones"),
            ],
        )
        staged.append(
            BatchRecord(
                sequence=sequence,
                params=params,
                status="valid",
                error=None,
            )
        )

    return BatchStaging(
        batch_id=batch_id,
        created_at=None,
        records=tuple(staged),
    )


def get_batch(client: SqlExecutor, batch_id: str) -> BatchStaging | None:
    """Return the preview of a staged batch, or None when not found."""
    rows = client.execute_sql(_GET_STAGING_SQL, [batch_id])
    if not rows:
        return None

    records = tuple(
        BatchRecord(
            sequence=int(row["sequence"]),
            params={
                "animal_id": str(row["animal_id"]),
                "voluntario_entrada_id": row.get("voluntario_entrada_id"),
                "fecha_entrada": str(row["fecha_entrada"]),
                "origen": row.get("origen"),
                "motivo": row.get("motivo"),
                "observaciones": row.get("observaciones"),
            },
            status="valid",
            error=None,
        )
        for row in rows
    )
    return BatchStaging(
        batch_id=batch_id,
        created_at=str(rows[0].get("created_at")) if rows[0].get("created_at") else None,
        records=records,
    )


def commit_batch(client: SqlExecutor, batch_id: str) -> list[Entrada]:
    """Atomically copy staged rows into ``entradas`` and clear staging.

    Uses a single CTE statement so PostgreSQL executes the INSERT and
    the staging DELETE as one logical operation. Any FK violation or
    ``entradas_natural_key`` violation aborts the whole statement,
    leaving staging rows intact (the operator can inspect via
    ``get_batch`` and decide whether to retry or cancel).
    """
    if get_batch(client, batch_id) is None:
        return []

    try:
        rows = client.execute_sql(_COMMIT_BATCH_SQL, [batch_id])
    except BackendError as exc:
        if is_duplicate_error(exc):
            raise EntradaConflictError(
                "entrada duplicada durante el commit del lote"
            ) from exc
        raise
    return [row_to_entrada(row) for row in rows]


def cancel_batch(client: SqlExecutor, batch_id: str) -> None:
    """Delete staging rows for a batch without committing."""
    client.execute_sql(_CANCEL_BATCH_SQL, [batch_id])
