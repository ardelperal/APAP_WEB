"""Service layer for FOSTER-02 estancias de acogida.

Owns dataclasses, mapping helpers, validation, and CRUD orchestration
for the ``acogidas`` table (legacy ``TbAcogidaAnimal`` mirror, verified
via Dysflow ``projectId=apap`` on 2026-07-04, 15 legacy columns + 1
justified improvement — ``casa_acogida_id`` FK to ``casas_acogida``,
added via ``ACOGIDAS_ADD_CASA_FK_SQL`` ALTER TABLE in
``app/core/domain.py``).

Per AGENTS.md §22, **all SQL strings and parameter shaping live in
``queries.py``**; this module imports those builders, applies domain
validation, and talks to the client. The seam is testable: the shape
of the SQL is asserted in ``tests/test_acogidas_queries.py`` without
spinning up transport.

Validation contract (mirrors INTAKE-01 / FOSTER-01 style):

- Required: ``animal_id``, ``fecha_inicio``.
- ``animal_id`` MUST reference an active ``animales`` row.
- ``casa_acogida_id`` optional; if present, MUST reference an active
  ``casas_acogida`` row (D-EST-01 — preserves retro-compat with
  historical stays without a house).
- Any ``voluntario_*_id`` (acogida / seguimiento1 / seguimiento2 /
  sanitario) optional; if present, MUST reference an active
  ``voluntarios`` row. Inactive voluntarios are rejected (D-EST-06,
  VOL-05 pattern).
- ``fecha_inicio`` non-empty after ``.strip()``.
- ``entrada_origen_id`` optional; if present, MUST reference an existing
  ``entradas`` row (NOT active-checked: legacy entries can be
  soft-deleted but the FK should still work).
- ``direccion``, ``telefono``, ``observaciones`` optional free-text
  (legacy denormalized fields, preserved 1:1).
- ``fecha_final`` optional (issue #141 — was silently dropped before
  the fix). Editable via create/update: pass an ISO date string to
  set, leave empty (or pass ``None``) to reopen (``NULL``). If the
  caller does not include the key in the params dict at all, the
  service leaves the existing column value untouched (regression
  guard; ``close_acogida`` is the canonical close path).
- Empty strings (after ``.strip()``) count as missing for required fields.
- Soft-delete via ``activo = false`` + ``fecha_baja = now()``. Physical
  deletes are forbidden (project-wide pattern).

Lifecycle split (D-EST-04, three independent axes):

- ``fecha_final`` via create/update — an editable column. Setting
  it (``"YYYY-MM-DD"``) records or edits the end date; leaving it
  blank sets it to ``NULL`` (reopen). Does NOT auto-close and does
  NOT touch ``activo``.
- ``close_acogida`` — the canonical end-of-stay lifecycle event. It
  sets ``fecha_final = current_date`` and keeps ``activo = true``.
  The stay row stays visible in the listing (with ``fecha_final``
  populated). Bypasses the form path entirely.
- ``delete_acogida`` — the real soft-delete. It sets ``activo = false``
  and ``fecha_baja = now()``. The row disappears from the default
  listing. Independent of ``fecha_final``.

Framework-agnostic: routes are thin HTTP glue; SQL, validation, and
mapping all live here and in ``queries.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.core.data_access import SqlExecutor
from app.core.logging import log_safe
from app.modules.acogidas import queries

# Back-compat re-exports — the integration tests
# (``tests/test_acogidas.py``, ``tests/test_acogidas_routes.py``) compute
# the positional index of ``fecha_final`` in the UPDATE parameter list
# from ``_WRITE_COLUMNS`` (the canonical source of truth). The actual
# column tuples live in ``queries.py`` (per AGENTS.md §22 + §4), so we
# re-export them under their original underscore-prefixed names. Do
# NOT add new public surface here — anything new MUST live in
# ``queries.py`` with the public ``ACOGIDA_*_COLUMNS`` names.
_WRITE_COLUMNS = queries.ACOGIDA_WRITE_COLUMNS
_SELECT_COLUMNS = queries.ACOGIDA_SELECT_COLUMNS


class AcogidaConflictError(ValueError):
    """Raised when a natural-key conflict occurs on a unique column.

    Currently unused at the service level (no UNIQUE constraint on the
    public CRUD surface beyond the legacy natural-key on
    ``(animal_id, fecha_inicio)`` which PostgreSQL would surface as a
    raw ``InsForgeError``), but kept for future parity and explicit
    signal to routes (mirror of the *ConflictError(ValueError) family
    across entradas/acogidas/adopciones/cesiones/sanidad).
    """


@dataclass(frozen=True, slots=True)
class Acogida:
    """A public service-row representation for ``acogidas``."""

    id: str
    animal_id: str
    fecha_inicio: str
    activo: bool = True
    casa_acogida_id: str | None = None
    voluntario_acogida_id: str | None = None
    voluntario_seguimiento1_id: str | None = None
    voluntario_seguimiento2_id: str | None = None
    voluntario_sanitario_id: str | None = None
    fecha_final: str | None = None
    entrada_origen_id: str | None = None
    direccion: str | None = None
    telefono: str | None = None
    observaciones: str | None = None
    fecha_alta: str | None = None
    fecha_baja: str | None = None
    updated_at: str | None = None


# --- mapping --------------------------------------------------------------


def _row_to_acogida(row: dict[str, Any]) -> Acogida:
    """Map a ``acogidas`` SELECT result row to an Acogida dataclass.

    Matches the ``_row_to_*`` regex so the CRITICAL_HELPERS coverage
    gate (``scripts/pytest_plugin/coverage_gate.py``) auto-discovers
    this helper and enforces 100% line coverage. Every branch maps
    the 17 columns declared in ``ACOGIDA_SELECT_COLUMNS``.
    """
    def _uuid_or_none(value: Any) -> str | None:
        return str(value) if value else None

    return Acogida(
        id=str(row["id"]),
        animal_id=str(row["animal_id"]),
        casa_acogida_id=_uuid_or_none(row.get("casa_acogida_id")),
        voluntario_acogida_id=_uuid_or_none(row.get("voluntario_acogida_id")),
        voluntario_seguimiento1_id=_uuid_or_none(row.get("voluntario_seguimiento1_id")),
        voluntario_seguimiento2_id=_uuid_or_none(row.get("voluntario_seguimiento2_id")),
        voluntario_sanitario_id=_uuid_or_none(row.get("voluntario_sanitario_id")),
        fecha_inicio=str(row["fecha_inicio"]),
        fecha_final=str(row["fecha_final"]) if row.get("fecha_final") else None,
        entrada_origen_id=_uuid_or_none(row.get("entrada_origen_id")),
        direccion=row.get("direccion"),
        telefono=row.get("telefono"),
        observaciones=row.get("observaciones"),
        fecha_alta=str(row["fecha_alta"]) if row.get("fecha_alta") else None,
        fecha_baja=str(row["fecha_baja"]) if row.get("fecha_baja") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
        activo=bool(row.get("activo", True)),
    )


# --- validation helpers ---------------------------------------------------


def _required_text(params: dict[str, Any], field_name: str) -> str:
    value = str(params.get(field_name) or "").strip()
    if not value:
        raise ValueError(f"{field_name} es obligatorio y no puede estar vacio")
    return value


def _optional_text(params: dict[str, Any], field_name: str) -> str | None:
    value = params.get(field_name)
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _optional_uuid(params: dict[str, Any], field_name: str) -> str | None:
    """Same as ``_optional_text`` but stricter — a UUID-shaped string.

    Used for FK columns that should NOT carry free-text. We don't enforce
    a regex here (the DB column is UUID and the FK target is UUID; the
    DB rejects anything that isn't a valid UUID). We just trim and treat
    empty as None.
    """
    return _optional_text(params, field_name)


def _validate_animal_exists_and_active(
    client: SqlExecutor, animal_id: str
) -> None:
    sql, params = queries.build_acogida_check_animal(animal_id)
    rows = client.execute_sql(sql, params)
    if not rows:
        raise ValueError(
            f"animal_id debe apuntar a un animal activo (no encontrado: {animal_id})"
        )
    if not rows[0].get("activo", False):
        raise ValueError(
            f"animal_id debe apuntar a un animal activo (inactivo: {animal_id})"
        )


def _validate_casa_acogida_active(client: SqlExecutor, casa_id: str) -> None:
    """casa_acogida_id, if present, must reference an active casa.

    The DB-side ``AND activo = true`` is defense in depth; the service
    also checks ``activo`` explicitly so the validation works against
    test mocks that don't simulate the WHERE clause.
    """
    sql, params = queries.build_acogida_check_casa(casa_id)
    rows = client.execute_sql(sql, params)
    if not rows:
        raise ValueError(
            f"casa_acogida_id debe apuntar a una casa activa (no encontrada o inactiva: {casa_id})"
        )
    if not rows[0].get("activo", False):
        raise ValueError(
            f"casa_acogida_id debe apuntar a una casa activa (inactiva: {casa_id})"
        )


def _validate_voluntario_activo(
    client: SqlExecutor, vol_id: str, field_name: str
) -> None:
    """Any voluntario_*_id, if present, must reference an active voluntario.

    VOL-05 pattern: inactive voluntarios cannot be assigned to new stays.
    The DB-side ``AND activo = true`` is defense in depth; the service
    also checks ``activo`` explicitly so the validation works against
    test mocks that don't simulate the WHERE clause.
    """
    sql, params = queries.build_acogida_check_voluntario(vol_id)
    rows = client.execute_sql(sql, params)
    if not rows:
        raise ValueError(
            f"{field_name} debe apuntar a un voluntario activo (no encontrado: {vol_id})"
        )
    if not rows[0].get("activo", False):
        raise ValueError(
            f"{field_name} debe apuntar a un voluntario activo (inactivo: {vol_id})"
        )


def _validate_entrada_exists_if_present(
    client: SqlExecutor, entrada_id: str | None
) -> None:
    """entrada_origen_id, if present, must reference an existing entrada.

    We do NOT check ``activo`` here — legacy entries can be soft-deleted,
    but the FK should still resolve. The mapping layer (entrada.yaml)
    needs to find the entrada even when it's been deactivated, so the
    relational link stays intact for historical queries.
    """
    if entrada_id is None:
        return
    sql, params = queries.build_acogida_check_entrada(entrada_id)
    rows = client.execute_sql(sql, params)
    if not rows:
        raise ValueError(
            f"entrada_origen_id debe apuntar a una entrada existente (no encontrada: {entrada_id})"
        )


def _validate_references(client: SqlExecutor, params: dict[str, Any]) -> None:
    """Run all FK checks in order. Raises ``ValueError`` on first failure.

    Order: animal (required) -> casa (optional) -> voluntarios (4 optional)
    -> entrada (optional). Fail-fast: the first invalid reference stops
    the chain. The captured SQL list in tests proves the order.
    """
    animal_id = _required_text(params, "animal_id")
    _validate_animal_exists_and_active(client, animal_id)

    casa_id = _optional_uuid(params, "casa_acogida_id")
    if casa_id:
        _validate_casa_acogida_active(client, casa_id)

    for field in (
        "voluntario_acogida_id",
        "voluntario_seguimiento1_id",
        "voluntario_seguimiento2_id",
        "voluntario_sanitario_id",
    ):
        vol_id = _optional_uuid(params, field)
        if vol_id:
            _validate_voluntario_activo(client, vol_id, field)

    entrada_id = _optional_uuid(params, "entrada_origen_id")
    _validate_entrada_exists_if_present(client, entrada_id)


# --- public CRUD ----------------------------------------------------------


def create_acogida(
    client: SqlExecutor, params: dict[str, Any]
) -> Acogida:
    """Insert a new estancia de acogida and return the persisted row.

    Issue #142: ``params`` may carry an ``override_id`` key (str,
    nullable). When present and non-empty, after the INSERT succeeds
    we UPDATE ``foster_capacity_overrides.estancia_id`` for that
    override row to the new ``acogida.id``. The UPDATE is a no-op
    (0 rows) when the override is already linked, the UUID is
    unknown, or the casa+animal pair from the form does not match
    the override's recorded pair (defense against cross-operator
    ``override_id`` forgery — judgment-day CRITICAL §1.2 + HIGH
    §3.2 follow-up to PR #155). In any of those "no link" cases we
    emit a ``foster.override.unlinked`` warning instead of raising
    so the operator's estancia creation still succeeds.

    The UPDATE filter includes ``casa_acogida_id`` and ``animal_id``
    so a forged ``override_id`` from another operator's session
    cannot link to a different stay — the casa+animal pair from the
    form must match the override's recorded pair.
    """
    # Validation runs BEFORE the INSERT so we never write a row with
    # broken FKs. The builder raises ValueError before any SQL if
    # fecha_inicio or animal_id is empty.
    sql, write_params = queries.build_acogida_insert(params)
    _validate_references(client, params)

    rows = client.execute_sql(sql, write_params)
    acogida = _row_to_acogida(rows[0])
    log_safe("foster.acogida.created", acogida_id=acogida.id)

    # Issue #142: link the foster_capacity_overrides row to the new
    # estancia, when ``override_id`` is present and non-empty.
    override_id_raw = params.get("override_id")
    if isinstance(override_id_raw, str) and override_id_raw.strip():
        # Defense (judgment-day CRITICAL §1.2 / HIGH §3.2 follow-up):
        # scope the link UPDATE to casa+animal so a forged
        # ``override_id`` from another operator's session cannot
        # point at this estancia. Reuse the already-validated casa
        # and animal from ``params``; ``_validate_references`` raised
        # above if either was invalid. ``link_casa_id`` may be None
        # for stays with no casa — in SQL three-valued logic
        # ``casa_acogida_id = NULL`` is NULL/false, so the filter
        # rejects the link (the override was recorded for a SPECIFIC
        # casa, NOT NULL by schema).
        link_casa_id = _optional_uuid(params, "casa_acogida_id")
        link_animal_id = _required_text(params, "animal_id")
        link_sql, link_params = queries.build_acogida_link_override(
            estancia_id=acogida.id,
            override_id=override_id_raw.strip(),
            casa_acogida_id=link_casa_id,
            animal_id=link_animal_id,
        )
        link_rows = client.execute_sql(link_sql, link_params)
        if not link_rows:
            # 0 rows updated: the override row is already linked, the
            # UUID does not exist, or the casa/animal pair from the
            # form does NOT match the override's recorded pair
            # (forgery attempt). Log a warning and do NOT raise —
            # the estancia itself was created successfully and
            # audit-log anomalies must not punish the operator.
            log_safe(
                "foster.override.unlinked",
                override_id=override_id_raw,
                motivo="override row missing, already linked, or casa/animal mismatch",
            )

    return acogida


def list_acogidas(
    client: SqlExecutor, activas_solo: bool = False
) -> list[Acogida]:
    """Return all estancias (active + closed), optionally filtered to active only.

    ``activas_solo=True`` adds ``WHERE fecha_final IS NULL`` (the
    closed-stay rows are excluded). Default (``False``) returns both
    active and closed, sorted by ``fecha_inicio DESC``.
    """
    sql, params = queries.build_acogida_list(activas_solo)
    rows = client.execute_sql(sql, params)
    return [_row_to_acogida(row) for row in rows]


def get_acogida_by_id(
    client: SqlExecutor, acogida_id: str
) -> Acogida | None:
    """Return one estancia de acogida by id (active or closed), or None."""
    sql, params = queries.build_acogida_get_by_id(acogida_id)
    rows = client.execute_sql(sql, params)
    return _row_to_acogida(rows[0]) if rows else None


def update_acogida(
    client: SqlExecutor, acogida_id: str, params: dict[str, Any]
) -> Acogida | None:
    """Update an estancia de acogida and return the updated row, or None.

    Same validation contract as create. The UPDATE is filtered by id
    only (not by activo) so operators can edit soft-deleted stays
    during data cleanup. Returns None when no row matches the id.

    Issue #141: ``fecha_final`` follows the partial-update contract —
    the column is included in the UPDATE only when the key is present
    in ``params``. Sending ``""`` or ``None`` writes ``NULL``
    (reopen); omitting the key leaves the column untouched.
    """
    # Validation against the full schema: the form always ships every
    # field, so this is the realistic contract. The required-text
    # validator in the builder also raises on missing required text
    # fields BEFORE any SQL.
    sql, write_params = queries.build_acogida_update(acogida_id, params)
    _validate_references(client, params)

    rows = client.execute_sql(sql, [acogida_id, *write_params])
    if not rows:
        return None
    updated = _row_to_acogida(rows[0])
    log_safe("foster.acogida.updated", acogida_id=updated.id)
    return updated


def close_acogida(
    client: SqlExecutor, acogida_id: str
) -> Acogida | None:
    """Mark the stay as closed: ``fecha_final = CURRENT_DATE``, ``activo`` stays true.

    D-EST-04: closing is a lifecycle event (the animal returns to the
    shelter or moves to adoption), NOT a soft-delete. The row stays
    visible in ``list_acogidas`` with ``fecha_final`` populated. Returns
    None when no row matches the id.

    Intentionally NOT filtered by ``activo = true`` to support
    data-cleanup workflows where a closed-then-soft-deleted stay needs
    to be re-opened via date correction. Operators who want to close
    only active stays must use ``delete_acogida`` semantics
    separately (``list_acogidas(activas_solo=True)`` first, then
    close).

    Issue #139 P1 #5: this contract is pinned by
    ``test_close_acogida_works_on_soft_deleted_stay``.
    """
    sql, params = queries.build_acogida_close(acogida_id)
    rows = client.execute_sql(sql, params)
    if not rows:
        return None
    closed = _row_to_acogida(rows[0])
    log_safe("foster.acogida.closed", acogida_id=closed.id)
    return closed


def delete_acogida(
    client: SqlExecutor, acogida_id: str
) -> bool:
    """Atomically soft-delete an estancia de acogida.

    Returns ``True`` if the row was active and was deactivated.
    Returns ``False`` if the row does not exist OR was already inactive.

    Pattern mirrors ``app/modules/foster/service.py::delete_casa_acogida``
    and ``app/modules/entradas/service.py::delete_entrada``: the
    ``WHERE id = $1 AND activo = true`` filter folds the existence check
    into the same statement under PostgreSQL's row lock; two concurrent
    calls produce exactly one ``True`` and one ``False``.
    """
    sql, params = queries.build_acogida_delete(acogida_id)
    rows = client.execute_sql(sql, params)
    deleted = bool(rows)
    if deleted:
        log_safe("foster.acogida.deleted", acogida_id=acogida_id)
    return deleted


# --- pure helpers (no DB) ------------------------------------------------


def compute_duracion(acogida: Acogida) -> int | None:
    """Return the integer number of days between ``fecha_inicio`` and ``fecha_final``.

    Returns ``None`` when the stay is still open (``fecha_final IS NULL``).
    Returns ``0`` when both dates fall on the same day. Both inputs are
    ISO-8601 date strings (``YYYY-MM-DD``).

    Raises ``ValueError`` when:

      * ``fecha_final`` is earlier than ``fecha_inicio``. Per the
        legacy semantic, a stay cannot end before it begins — this is
        a data-entry error (operator typed the dates in the wrong
        order). Returning a negative number would silently corrupt the
        operator-facing duration display, so we raise loudly instead.
        The form layer surfaces this as a 422 with the operator's
        input preserved.
      * ``fecha_inicio`` or ``fecha_final`` is not a valid ISO-8601
        date string. ``date.fromisoformat`` raises ``ValueError`` on
        malformed input; we let it propagate (no silent swallow, no
        ``None`` fallback).
    """
    if not acogida.fecha_final:
        return None
    inicio = date.fromisoformat(acogida.fecha_inicio)
    fin = date.fromisoformat(acogida.fecha_final)
    if fin < inicio:
        raise ValueError(
            f"fecha_final ({fin}) debe ser >= fecha_inicio ({inicio}) "
            f"para estancia {acogida.id}"
        )
    return (fin - inicio).days


def is_active(acogida: Acogida) -> bool:
    """Return whether the stay is currently active.

    Active = ``activo = true`` AND ``fecha_final IS NULL``. A closed
    stay (``fecha_final`` populated) is NOT active even if ``activo``
    is still true (D-EST-04 — close is not soft-delete). A soft-deleted
    stay (``activo = false``) is NOT active regardless of ``fecha_final``.
    """
    return bool(acogida.activo) and acogida.fecha_final is None
