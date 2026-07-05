"""Service layer for FOSTER-02 estancias de acogida.

Owns SQL, validation, mapping, and lifecycle management for the
``acogidas`` table (legacy ``TbAcogidaAnimal`` mirror, verified via
Dysflow ``projectId=apap`` on 2026-07-04, 15 legacy columns + 1
justified improvement — ``casa_acogida_id`` FK to ``casas_acogida``,
added via ``ACOGIDAS_ADD_CASA_FK_SQL`` ALTER TABLE in
``app/core/domain.py``).

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
mapping all live here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from app.core.logging import log_safe


class AcogidaConflictError(ValueError):
    """Raised when a natural-key conflict occurs on a unique column.

    Currently unused at the service level (no UNIQUE constraint on the
    public CRUD surface beyond the legacy natural-key on
    ``(animal_id, fecha_inicio)`` which PostgreSQL would surface as a
    raw ``InsForgeError``), but kept for future parity and explicit
    signal to routes (mirror of ``CasaAcogidaConflictError`` in
    FOSTER-01).
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


_WRITE_COLUMNS: Final[tuple[str, ...]] = (
    "animal_id",
    "casa_acogida_id",
    "voluntario_acogida_id",
    "voluntario_seguimiento1_id",
    "voluntario_seguimiento2_id",
    "voluntario_sanitario_id",
    "fecha_inicio",
    "fecha_final",
    "entrada_origen_id",
    "direccion",
    "telefono",
    "observaciones",
)

# Columns that the UPDATE writes only when the corresponding key is
# present in the params dict. ``fecha_final`` is patch-only because
# the form may legitimately omit the key (operators who want to
# leave the value untouched should not be required to send an empty
# string and rely on the service to swallow it). ``close_acogida``
# is the canonical close path and bypasses this form flow entirely
# — an accidental blanket-blank UPDATE would silently overwrite
# closed stays. Issue #141.
_UPDATE_PATCH_ONLY_COLUMNS: Final[frozenset[str]] = frozenset({"fecha_final"})


_SELECT_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "animal_id",
    "casa_acogida_id",
    "voluntario_acogida_id",
    "voluntario_seguimiento1_id",
    "voluntario_seguimiento2_id",
    "voluntario_sanitario_id",
    "fecha_inicio",
    "fecha_final",
    "entrada_origen_id",
    "direccion",
    "telefono",
    "observaciones",
    "fecha_alta",
    "fecha_baja",
    "updated_at",
    "activo",
)


# --- FK existence checks (read-only, no writes) ---------------------------

_CHECK_ANIMAL_SQL: Final[str] = (
    "SELECT id, activo FROM animales WHERE id = $1"
)

_CHECK_CASA_SQL: Final[str] = (
    "SELECT id, activo FROM casas_acogida WHERE id = $1 AND activo = true"
)

# Same pattern as entradas service: only ACTIVE voluntarios are valid for
# new FK references (VOL-05). Soft-deleted voluntarios are rejected.
_CHECK_VOLUNTARIO_SQL: Final[str] = (
    "SELECT id, activo FROM voluntarios WHERE id = $1 AND activo = true"
)

# Entrada existence check (no active filter — legacy entries may be
# soft-deleted, but the FK still resolves).
_CHECK_ENTRADA_SQL: Final[str] = (
    "SELECT id FROM entradas WHERE id = $1"
)


# --- CRUD SQL -------------------------------------------------------------

_INSERT_ACOGIDA_SQL: Final[str] = (
    f"INSERT INTO acogidas ({', '.join(_WRITE_COLUMNS)}) "
    f"VALUES ({', '.join(f'${i + 1}' for i in range(len(_WRITE_COLUMNS)))}) "
    f"RETURNING {', '.join(_SELECT_COLUMNS)}"
)


_LIST_ACOGIDAS_SQL: Final[str] = (
    f"SELECT {', '.join(_SELECT_COLUMNS)} "
    "FROM acogidas "
    "ORDER BY fecha_inicio DESC"
)


_LIST_ACOGIDAS_ACTIVAS_SQL: Final[str] = (
    f"SELECT {', '.join(_SELECT_COLUMNS)} "
    "FROM acogidas "
    "WHERE fecha_final IS NULL "
    "ORDER BY fecha_inicio DESC"
)


_GET_ACOGIDA_BY_ID_SQL: Final[str] = (
    f"SELECT {', '.join(_SELECT_COLUMNS)} FROM acogidas WHERE id = $1"
)


# NOTE: the generic UPDATE SQL for create/update is built dynamically
# inside :func:`_build_update_sql_and_params` — ``_WRITE_COLUMNS``
# alone is not enough because ``fecha_final`` follows the
# partial-update contract (issue #141). ``close_acogida`` still has
# its own constant below.


# D-EST-04: close_acogida is a lifecycle event, NOT a soft-delete. It
# sets fecha_final to today and keeps activo=true. Pattern: same
# conditional WHERE as delete (id must exist) but no activo filter,
# since we want to be able to close an already-soft-deleted stay in
# data-cleanup scenarios (defensive: real flow only closes active stays).
_CLOSE_ACOGIDA_SQL: Final[str] = (
    f"UPDATE acogidas SET fecha_final = CURRENT_DATE, "
    f"updated_at = now() "
    f"WHERE id = $1 "
    f"RETURNING {', '.join(_SELECT_COLUMNS)}"
)


# Soft-delete: activo=false + fecha_baja=now(). Pattern matches
# casas_acogida and entradas (atomic existence check via WHERE + activo).
_DELETE_ACOGIDA_SQL: Final[str] = """
UPDATE acogidas
SET activo = false,
    fecha_baja = now(),
    updated_at = now()
WHERE id = $1 AND activo = true
RETURNING id
"""


# --- mapping --------------------------------------------------------------


def _row_to_acogida(row: dict[str, Any]) -> Acogida:
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
    client, animal_id: str
) -> None:
    rows = client.execute_sql(_CHECK_ANIMAL_SQL, [animal_id])
    if not rows:
        raise ValueError(
            f"animal_id debe apuntar a un animal activo (no encontrado: {animal_id})"
        )
    if not rows[0].get("activo", False):
        raise ValueError(
            f"animal_id debe apuntar a un animal activo (inactivo: {animal_id})"
        )


def _validate_casa_acogida_active(client, casa_id: str) -> None:
    """casa_acogida_id, if present, must reference an active casa.

    The DB-side ``AND activo = true`` is defense in depth; the service
    also checks ``activo`` explicitly so the validation works against
    test mocks that don't simulate the WHERE clause.
    """
    rows = client.execute_sql(_CHECK_CASA_SQL, [casa_id])
    if not rows:
        raise ValueError(
            f"casa_acogida_id debe apuntar a una casa activa (no encontrada o inactiva: {casa_id})"
        )
    if not rows[0].get("activo", False):
        raise ValueError(
            f"casa_acogida_id debe apuntar a una casa activa (inactiva: {casa_id})"
        )


def _validate_voluntario_activo(client, vol_id: str, field_name: str) -> None:
    """Any voluntario_*_id, if present, must reference an active voluntario.

    VOL-05 pattern: inactive voluntarios cannot be assigned to new stays.
    The DB-side ``AND activo = true`` is defense in depth; the service
    also checks ``activo`` explicitly so the validation works against
    test mocks that don't simulate the WHERE clause.
    """
    rows = client.execute_sql(_CHECK_VOLUNTARIO_SQL, [vol_id])
    if not rows:
        raise ValueError(
            f"{field_name} debe apuntar a un voluntario activo (no encontrado: {vol_id})"
        )
    if not rows[0].get("activo", False):
        raise ValueError(
            f"{field_name} debe apuntar a un voluntario activo (inactivo: {vol_id})"
        )


def _validate_entrada_exists_if_present(
    client, entrada_id: str | None
) -> None:
    """entrada_origen_id, if present, must reference an existing entrada.

    We do NOT check ``activo`` here — legacy entries can be soft-deleted,
    but the FK should still resolve. The mapping layer (entrada.yaml)
    needs to find the entrada even when it's been deactivated, so the
    relational link stays intact for historical queries.
    """
    if entrada_id is None:
        return
    rows = client.execute_sql(_CHECK_ENTRADA_SQL, [entrada_id])
    if not rows:
        raise ValueError(
            f"entrada_origen_id debe apuntar a una entrada existente (no encontrada: {entrada_id})"
        )


def _validate_references(client, params: dict[str, Any]) -> None:
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


def _build_write_params(
    params: dict[str, Any],
    columns: tuple[str, ...] | None = None,
) -> list[Any]:
    """Order matches ``columns`` (defaults to ``_WRITE_COLUMNS``).

    Each column has a typed extractor: required UUID/text fields use
    the strict validators; optional fields use ``_optional_text`` /
    ``_optional_uuid`` so blank inputs normalize to ``NULL``.
    """
    if columns is None:
        columns = _WRITE_COLUMNS

    def _extract(col: str) -> Any:
        if col in ("animal_id", "fecha_inicio"):
            return _required_text(params, col)
        if col in (
            "casa_acogida_id",
            "voluntario_acogida_id",
            "voluntario_seguimiento1_id",
            "voluntario_seguimiento2_id",
            "voluntario_sanitario_id",
            "entrada_origen_id",
        ):
            return _optional_uuid(params, col)
        # fecha_final + the free-text legacy denormalizations.
        return _optional_text(params, col)

    return [_extract(col) for col in columns]


def _build_update_sql_and_params(
    params: dict[str, Any],
) -> tuple[str, list[Any]]:
    """Build the UPDATE SQL + params based on which keys are present.

    Issue #141 — every column in ``_WRITE_COLUMNS`` is included EXCEPT
    those in ``_UPDATE_PATCH_ONLY_COLUMNS`` whose key is absent from
    ``params``. That carve-out makes ``fecha_final`` behave
    defensively: a partial-update caller that does not include the
    key gets a SQL UPDATE that does NOT touch the column (so a
    previously closed stay stays closed). The form always sends the
    field, so the live route path is unaffected — operators who
    want to reopen send ``fecha_final=\"\"`` (which ``_opt``
    normalizes to ``None``) and operators who want to keep the
    previous value simply omit the key.

    Returns a ``(sql, params_for_sql)`` tuple ready to be passed to
    ``client.execute_sql``. ``$1`` is reserved for the id; the SET
    placeholders start at ``$2``.
    """
    set_columns = tuple(
        col
        for col in _WRITE_COLUMNS
        if col in params or col not in _UPDATE_PATCH_ONLY_COLUMNS
    )
    sql = (
        "UPDATE acogidas SET "
        + ", ".join(f"{col} = ${i + 2}" for i, col in enumerate(set_columns))
        + ", updated_at = now() "
        + "WHERE id = $1 "
        + "RETURNING " + ", ".join(_SELECT_COLUMNS)
    )
    return sql, _build_write_params(params, columns=set_columns)


# --- public CRUD ----------------------------------------------------------


def create_acogida(
    client, params: dict[str, Any]
) -> Acogida:
    """Insert a new estancia de acogida and return the persisted row."""
    # Validation runs BEFORE the INSERT so we never write a row with
    # broken FKs. The required-text helpers raise ValueError before any
    # SQL if fecha_inicio or animal_id is empty.
    _build_write_params(params)
    _validate_references(client, params)

    write_params = _build_write_params(params)
    rows = client.execute_sql(_INSERT_ACOGIDA_SQL, write_params)
    acogida = _row_to_acogida(rows[0])
    log_safe("foster.acogida.created", acogida_id=acogida.id)
    return acogida


def list_acogidas(
    client, activas_solo: bool = False
) -> list[Acogida]:
    """Return all estancias (active + closed), optionally filtered to active only.

    ``activas_solo=True`` adds ``WHERE fecha_final IS NULL`` (the
    closed-stay rows are excluded). Default (``False``) returns both
    active and closed, sorted by ``fecha_inicio DESC``.
    """
    if activas_solo:
        rows = client.execute_sql(_LIST_ACOGIDAS_ACTIVAS_SQL)
    else:
        rows = client.execute_sql(_LIST_ACOGIDAS_SQL)
    return [_row_to_acogida(row) for row in rows]


def get_acogida_by_id(
    client, acogida_id: str
) -> Acogida | None:
    """Return one estancia de acogida by id (active or closed), or None."""
    rows = client.execute_sql(_GET_ACOGIDA_BY_ID_SQL, [acogida_id])
    return _row_to_acogida(rows[0]) if rows else None


def update_acogida(
    client, acogida_id: str, params: dict[str, Any]
) -> Acogida | None:
    """Update an estancia de acogida and return the updated row, or None.

    Same validation contract as create. The UPDATE is filtered by id
    only (not by activo) so operators can edit soft-deleted stays
    during data cleanup. Returns None when no row matches the id.

    Issue #141: ``fecha_final`` follows the partial-update contract —
    the column is included in the UPDATE only when the key is present
    in ``params``. Sending ``\"\"`` or ``None`` writes ``NULL``
    (reopen); omitting the key leaves the column untouched.
    """
    # Validation against the full schema: the form always ships every
    # field, so this is the realistic contract. ``_build_write_params``
    # also raises on missing required text fields BEFORE any SQL.
    _build_write_params(params)
    _validate_references(client, params)

    sql, write_params = _build_update_sql_and_params(params)
    rows = client.execute_sql(sql, [acogida_id, *write_params])
    if not rows:
        return None
    updated = _row_to_acogida(rows[0])
    log_safe("foster.acogida.updated", acogida_id=updated.id)
    return updated


def close_acogida(
    client, acogida_id: str
) -> Acogida | None:
    """Mark the stay as closed: ``fecha_final = CURRENT_DATE``, ``activo`` stays true.

    D-EST-04: closing is a lifecycle event (the animal returns to the
    shelter or moves to adoption), NOT a soft-delete. The row stays
    visible in ``list_acogidas`` with ``fecha_final`` populated. Returns
    None when no row matches the id.
    """
    rows = client.execute_sql(_CLOSE_ACOGIDA_SQL, [acogida_id])
    if not rows:
        return None
    closed = _row_to_acogida(rows[0])
    log_safe("foster.acogida.closed", acogida_id=closed.id)
    return closed


def delete_acogida(
    client, acogida_id: str
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
    rows = client.execute_sql(_DELETE_ACOGIDA_SQL, [acogida_id])
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
    """
    if not acogida.fecha_final:
        return None
    inicio = date.fromisoformat(acogida.fecha_inicio)
    fin = date.fromisoformat(acogida.fecha_final)
    return (fin - inicio).days


def is_active(acogida: Acogida) -> bool:
    """Return whether the stay is currently active.

    Active = ``activo = true`` AND ``fecha_final IS NULL``. A closed
    stay (``fecha_final`` populated) is NOT active even if ``activo``
    is still true (D-EST-04 — close is not soft-delete). A soft-deleted
    stay (``activo = false``) is NOT active regardless of ``fecha_final``.
    """
    return bool(acogida.activo) and acogida.fecha_final is None
