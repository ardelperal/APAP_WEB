"""Service layer for HEALTH-02 batch ``actuacion_sanitaria`` (issue #51).

Accepts an N-tuple of actucacion records, validates each one per the
D-24 fecha rule + FK checks (mirrors the single-record
``create_actuacion_sanitaria`` from HEALTH-01, #50), and commits them
ATOMICALLY through a single PostgreSQL CTE statement.

Why CTE-driven atomicity instead of an explicit ``BEGIN/COMMIT``:

    InsForge is reached over HTTP from Python via the
    ``/api/database/advance/rawsql`` endpoint; the client has NO
    transactional primitive (``execute_sql`` issues one POST per
    call). The atomicity guarantee therefore comes from PostgreSQL's
    own statement-level snapshot: every check + the INSERT run inside
    a single CTE, and ``bool_and(is_valid)`` gates the INSERT through
    ``WHERE all_valid.ok = true``. Either every valid row is committed
    in the same statement, or none is. A partial-batch scenario is
    structurally impossible.

    The single-record CRUD (``sanidad.service.create_actuacion_sanitaria``)
    uses the same CTE pattern; this service is the same idea
    generalised across ``unnest()`` arrays.

D-24 inheritance:
    The batch endpoint inherits the D-24 fecha rule from HEALTH-01
    (reglas 1+2+3). The pre-flight validation pipeline
    (``sanidad.service._validate_fecha_d24`` for reglas 1+2 +
    ``build_batch_insert`` CTE for regla 3 + FK active checks) is the
    SAME one used for single-record creates. The reason-code
    vocabulary in the CTE mirrors
    ``sanidad.service._raise_validation_error`` so the operator sees
    the same Spanish copy whether the failure is a single-record
    POST or one row in a batch.

Staging preview (dry_run):
    ``dry_run=true`` runs the SAME CTE with the ``$8::boolean = false``
    filter inverted, so the INSERT inserts zero rows. The service
    walks the CTE's ``kind='validation_error'`` rows and returns a
    ``BatchPreview`` envelope; no record is ever committed during
    preview. This is the "staging preview before commit" acceptance
    criterion from issue #51.

CRITICAL-1 (atomicity): see the CTE in ``queries.py`` —
``build_batch_insert``. The contract is enforced via the ``bool_and``
gate.

CRITICAL-2 (TOCTOU-safe writes): the FK joins in the CTE evaluate under
the same statement snapshot as the INSERT, closing the window between
the FK SELECTs and the write. The Python pre-flight
``_validate_fecha_d24`` for reglas 1+2 is no-DB (the format-check +
future-date rule) and runs BEFORE the CTE — it does not need a snapshot.

Framework-agnostic: routes are thin HTTP glue; SQL, validation,
mapping, and the batch orchestration all live here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.core.data_access import SqlExecutor
from app.core.logging import log_safe
from app.modules.sanidad import queries
from app.modules.sanidad.service import ActuacionSanitaria, _validate_fecha_d24

# --- public data classes --------------------------------------------------


@dataclass(frozen=True, slots=True)
class BatchItem:
    """One row in a ``BatchPreview`` (staging preview envelope).

    ``status='ok'`` when the row passed the validation pipeline,
    ``status='error'`` when the CTE surfaced a per-record failure
    reason. ``index`` is the 0-based position from the input list, so
    the route layer can address the corresponding form-row.
    """

    index: int
    status: Literal["ok", "error"]
    reason: str | None


@dataclass(frozen=True, slots=True)
class BatchPreview:
    """Per-record envelope returned by ``preview_batch`` (``dry_run=true``)."""

    dry_run: bool
    ok_count: int
    error_count: int
    items: tuple[BatchItem, ...]


@dataclass(frozen=True, slots=True)
class BatchResult:
    """The success result of ``commit_batch``.

    ``inserted`` carries the ``ActuacionSanitaria`` rows the CTE
    returned (``kind='inserted'`` branch only). When the CTE surfaces
    any ``validation_error`` rows, ``commit_batch`` raises
    :class:`BatchValidationError` instead and ``inserted`` is empty.
    """

    inserted: tuple[ActuacionSanitaria, ...]


class BatchValidationError(ValueError):
    """Raised by ``commit_batch`` when any row in the batch failed validation.

    The integrity contract: ``failed_indices`` lists every record that
    did NOT pass, and ``reasons`` is a dict keyed by the same index
    set. The CTE guarantees zero inserts in this branch (the
    ``bool_and`` gate short-circuits the INSERT), so the operator's
    DB is unchanged.
    """

    def __init__(
        self, failed_indices: tuple[int, ...], reasons: dict[int, str]
    ) -> None:
        self.failed_indices: tuple[int, ...] = failed_indices
        self.reasons: dict[int, str] = reasons
        if len(failed_indices) == 1:
            summary = f"registro {failed_indices[0]}: {reasons[failed_indices[0]]}"
        else:
            summary = (
                f"{len(failed_indices)} registros fallaron la validación: "
                + ", ".join(
                    f"#{idx}({reasons[idx]})" for idx in failed_indices
                )
            )
        super().__init__(summary)


# --- public API -----------------------------------------------------------


def commit_batch(
    client: SqlExecutor,
    records: list[dict[str, Any]],
    *,
    actor_user_id: str | None = None,
) -> BatchResult:
    """Validate + atomic-insert the entire batch as one CTE statement.

    Steps:

    1. Per-record ``_validate_fecha_d24`` (reglas 1+2): the pure
       date-format + future-date rule. Runs BEFORE the CTE so the
       common form-validation failure short-circuits without a DB
       round-trip.
    2. Single CTE: ``build_batch_insert(records, dry_run=False)``.
       PostgreSQL evaluates the FK joins + D-24 regla 3 + INSERT under
       the same statement snapshot. ``bool_and(is_valid)`` gates the
       INSERT: either every valid row commits or none does.
    3. Walk the response. ``kind='inserted'`` rows become the
       ``BatchResult.inserted`` tuple; ``kind='validation_error'`` rows
       populate a :class:`BatchValidationError` that surfaces the
       ``failed_indices`` + ``reasons`` for the operator.

    Raises
    ------
    BatchValidationError
        When any record in the batch fails validation. Zero rows are
        inserted in this branch (atomicity contract).
    ValueError
        When ``records`` is empty (defense in depth; the route layer
        also 422s on this).
    """
    if not records:
        raise ValueError(
            "commit_batch requires at least one record (got empty list)"
        )

    pre_flight_failures = _validate_records_pre_flight(records)
    if pre_flight_failures:
        raise BatchValidationError(
            failed_indices=tuple(sorted(pre_flight_failures.keys())),
            reasons=pre_flight_failures,
        )

    sql, params = queries.build_batch_insert(records, dry_run=False)
    rows = client.execute_sql(sql, params)

    inserted: list[ActuacionSanitaria] = []
    failures: dict[int, str] = {}
    for row in rows:
        kind = row.get("kind")
        idx = int(row.get("batch_index", 0))
        if kind == "inserted":
            inserted.append(_row_to_actuacion_sanitaria(row))
        elif kind == "validation_error":
            reason = row.get("reason")
            if reason:
                failures[idx] = str(reason)

    if failures:
        # Raise the per-record error envelope. The CTE guarantees that
        # the INSERT inserted 0 rows when ``all_valid.ok = false``.
        raise BatchValidationError(
            failed_indices=tuple(sorted(failures.keys())), reasons=failures
        )

    _audit_log_committed(len(inserted), records, actor_user_id=actor_user_id)
    return BatchResult(inserted=tuple(inserted))


def preview_batch(
    client: SqlExecutor,
    records: list[dict[str, Any]],
) -> BatchPreview:
    """Validate every record and return per-row status WITHOUT inserting.

    Same validation pipeline as :func:`commit_batch`. The CTE runs with
    ``dry_run=true`` so the INSERT filter (``$8::boolean = false``)
    short-circuits, leaving the per-record ``validation_error`` rows as
    the only output. The service wraps those into a
    :class:`BatchPreview` with ``ok_count`` + ``error_count`` + per-row
    ``BatchItem`` envelope.

    Unlike :func:`commit_batch`, this NEVER raises
    :class:`BatchValidationError` — the operator-facing UI needs the
    per-row reasons to surface them as inline form errors, not a
    top-of-page exception.
    """
    if not records:
        return BatchPreview(
            dry_run=True, ok_count=0, error_count=0, items=tuple()
        )

    pre_flight_failures = _validate_records_pre_flight(records)
    sql, params = queries.build_batch_insert(records, dry_run=True)
    rows = client.execute_sql(sql, params)

    failures_by_index: dict[int, str] = {}
    for row in rows:
        if row.get("kind") != "validation_error":
            continue
        idx = int(row.get("batch_index", 0))
        reason = row.get("reason")
        if reason:
            failures_by_index[idx] = str(reason)

    # Pre-flight failures take precedence over CTE failures for the
    # same index (the same record failed earlier in the pipeline).
    merged: dict[int, str] = {**failures_by_index, **pre_flight_failures}

    items: list[BatchItem] = []
    ok_count = 0
    error_count = 0
    for idx in range(len(records)):
        if idx in merged:
            items.append(
                BatchItem(index=idx, status="error", reason=merged[idx])
            )
            error_count += 1
        else:
            items.append(BatchItem(index=idx, status="ok", reason=None))
            ok_count += 1

    return BatchPreview(
        dry_run=True,
        ok_count=ok_count,
        error_count=error_count,
        items=tuple(items),
    )


# --- internal helpers -----------------------------------------------------


def _row_to_actuacion_sanitaria(row: dict[str, Any]) -> ActuacionSanitaria:
    """Map a CTE ``inserted`` row to the service's domain dataclass.

    Mirrors ``sanidad.service._row_to_actuacion_sanitaria`` so the
    batch endpoint surfaces identical ``ActuacionSanitaria`` instances
    to the operator. Kept local (not imported) because the CTE row has
    an extra ``kind`` + ``batch_index`` + ``reason`` prefix that the
    single-record mapper does not handle.
    """
    return ActuacionSanitaria(
        id=str(row["id"]),
        animal_id=str(row["animal_id"]),
        fecha=str(row["fecha"]),
        tipo_actuacion_id=(
            str(row["tipo_actuacion_id"])
            if row.get("tipo_actuacion_id")
            else None
        ),
        veterinario=row.get("veterinario"),
        observaciones=row.get("observaciones"),
        voluntario_id=(
            str(row["voluntario_id"]) if row.get("voluntario_id") else None
        ),
        material_utilizado=row.get("material_utilizado"),
        fecha_alta=str(row["fecha_alta"]) if row.get("fecha_alta") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
        activo=bool(row.get("activo", True)),
    )


def _validate_records_pre_flight(
    records: list[dict[str, Any]],
) -> dict[int, str]:
    """D-24 reglas 1+2 per-record check, run BEFORE the CTE.

    Rules 1+2 are pure (no DB round-trip) so they run for every record
    before the SQL executor is touched. Rule 3 (fecha_anterior_alta)
    needs the animal row, so it lives inside the CTE — the JOIN to
    ``animales`` resolves it under the same statement snapshot as the
    INSERT.

    Returns a dict ``{record_index: error_message}`` for every record
    that failed; empty dict when every record passed.

    Reuses :func:`sanidad.service._validate_fecha_d24` so the operator-
    facing Spanish copy matches the single-record endpoint exactly.
    """
    failures: dict[int, str] = {}
    for idx, record in enumerate(records):
        if not record.get("animal_id") or not str(record.get("animal_id")).strip():
            failures[idx] = "animal_id es obligatorio y no puede estar vacio"
            continue
        fecha_raw = record.get("fecha")
        if not fecha_raw or not str(fecha_raw).strip():
            failures[idx] = "fecha es obligatorio y no puede estar vacio"
            continue
        fecha_error = _validate_fecha_d24(str(fecha_raw).strip())
        if fecha_error is not None:
            failures[idx] = fecha_error
    return failures


def _audit_log_committed(
    inserted_count: int,
    records: list[dict[str, Any]],
    *,
    actor_user_id: str | None,
) -> None:
    """Emit the batch-level audit event after a successful commit.

    Uses ``log_safe`` per AGENTS.md §9 so the redaction list scrubs
    any PII slipped into the audit fields (the operator's email,
    session token, etc. live in ``actor_user_id`` payloads).
    """
    log_safe(
        "sanidad.batch_committed",
        batch_size=inserted_count,
        record_count=len(records),
        animal_ids=[
            str(record.get("animal_id")) for record in records
        ],
        actor_user_id=actor_user_id,
    )
