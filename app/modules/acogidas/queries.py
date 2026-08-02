"""SQL builder seam for ``app.modules.acogidas`` per AGENTS.md §22.

The query/service separation: SQL strings and parameter shaping live
here in pure builder functions that return ``(sql, params)`` tuples.
The service module (``app/modules/acogidas/service.py``) imports
these builders, applies domain validation, and talks to the SQL
executor.

Rule §22 — the seam is testable: the shape of the SQL is assertable
in a plain unit test (see ``tests/test_acogidas_queries.py``) without
spinning up transport, InsForge, or HTTP. The service layer stays
focused on dataclasses, mapping, validation, and orchestration.

Rule §1 — routes must never import from this module. The graph is
``routes.py -> service.py -> queries.py``; ``routes.py -> queries.py``
would violate the layer boundary.

Rule §4 — column lists and SQL templates live in exactly one place.
The ``acogidas`` catalog and its FK existence checks are NOT
redefined anywhere else in the module.

Rule §9 — no ``log_safe`` calls here. Query construction is silent;
the service layer emits the audit events when it executes the SQL.
"""

from __future__ import annotations

from functools import partial
from typing import Any, Final

from app.core.forms import optional_text, required_text

# The Spanish error template is part of the SQL parameter contract —
# the route layer formats the rejection with the operator-facing
# Spanish message. The previous ``service.py`` partial-wrapped
# ``required_text`` with this template; the wrapping now lives here
# because this is the only module that calls ``required_text`` after
# the §22 seam extraction.
_required_text = partial(
    required_text, error_template="{field} es obligatorio y no puede estar vacio"
)


# --- column tuples (single source of truth per §4) ----------------------


ACOGIDA_WRITE_COLUMNS: Final[tuple[str, ...]] = (
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


ACOGIDA_SELECT_COLUMNS: Final[tuple[str, ...]] = (
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
    "updated_at",
    "activo",
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


# --- catalog SQL constants ----------------------------------------------


_ACOGIDA_INSERT_SQL: Final[str] = (
    f"INSERT INTO acogidas ({', '.join(ACOGIDA_WRITE_COLUMNS)}) "
    f"VALUES ({', '.join(['%s'] * len(ACOGIDA_WRITE_COLUMNS))}) "
    f"RETURNING {', '.join(ACOGIDA_SELECT_COLUMNS)}"
)


_ACOGIDA_GET_BY_ID_SQL: Final[str] = (
    f"SELECT {', '.join(ACOGIDA_SELECT_COLUMNS)} "
    "FROM acogidas WHERE id = $1"
)


_ACOGIDA_LIST_ALL_SQL: Final[str] = (
    f"SELECT {', '.join(ACOGIDA_SELECT_COLUMNS)} "
    "FROM acogidas "
    "ORDER BY fecha_inicio DESC"
)


_ACOGIDA_LIST_ACTIVAS_SQL: Final[str] = (
    f"SELECT {', '.join(ACOGIDA_SELECT_COLUMNS)} "
    "FROM acogidas "
    "WHERE fecha_final IS NULL "
    "ORDER BY fecha_inicio DESC"
)


# D-EST-04: close_acogida is a lifecycle event, NOT a soft-delete. It
# sets fecha_final to today and keeps activo=true. Pattern: no activo
# filter, since we want to be able to close an already-soft-deleted
# stay in data-cleanup scenarios (defensive: real flow only closes
# active stays).
_ACOGIDA_CLOSE_SQL: Final[str] = (
    f"UPDATE acogidas SET fecha_final = CURRENT_DATE, "
    f"updated_at = now() "
    f"WHERE id = $1 "
    f"RETURNING {', '.join(ACOGIDA_SELECT_COLUMNS)}"
)


# Atomic soft-delete: existence check + deactivation in one statement
# under PostgreSQL's row lock. Pattern matches casas_acogida and
# entradas.
_ACOGIDA_DELETE_SQL: Final[str] = """
UPDATE acogidas
SET activo = false,
    fecha_baja = now(),
    updated_at = now()
WHERE id = $1 AND activo = true
RETURNING id
"""


# --- FK existence checks (read-only, no writes) -------------------------


_ACOGIDA_CHECK_ANIMAL_SQL: Final[str] = (
    "SELECT id, activo FROM animales WHERE id = $1"
)


_ACOGIDA_CHECK_CASA_SQL: Final[str] = (
    "SELECT id, activo FROM casas_acogida WHERE id = $1 AND activo = true"
)


# Same pattern as entradas service: only ACTIVE voluntarios are valid
# for new FK references (VOL-05). Soft-deleted voluntarios are
# rejected.
_ACOGIDA_CHECK_VOLUNTARIO_SQL: Final[str] = (
    "SELECT id, activo FROM voluntarios WHERE id = $1 AND activo = true"
)


# Entrada existence check (no active filter — legacy entries may be
# soft-deleted, but the FK still resolves).
_ACOGIDA_CHECK_ENTRADA_SQL: Final[str] = (
    "SELECT id FROM entradas WHERE id = $1"
)


# --- foster_capacity_overrides link (issue #142) ------------------------


# Linkage UPDATE from ``create_acogida`` to
# ``foster_capacity_overrides.estancia_id``. The ``AND estancia_id IS
# NULL`` guard prevents linking twice. The
# ``AND casa_acogida_id = $3 AND animal_id = $4`` guards
# (judgment-day CRITICAL §1.2 + HIGH §3.2 follow-up to PR #155)
# scope the link to the override's recorded casa+animal — a forged
# ``override_id`` from another operator's session cannot link to a
# different stay because the form's casa+animal pair will not match
# the override row. Empty ``override_id`` (from a missing form field
# that serializes as ``""``) is treated the same as absent — no
# UPDATE.
_ACOGIDA_LINK_OVERRIDE_SQL: Final[str] = """
UPDATE foster_capacity_overrides
SET estancia_id = $1
WHERE id = $2
  AND casa_acogida_id = $3
  AND animal_id = $4
  AND estancia_id IS NULL
"""


# --- parameter shaping helpers ------------------------------------------


def _extract_write_value(col: str, params: dict[str, Any]) -> Any:
    """Dispatch a single column to its typed extractor.

    Mirrors the previous ``_build_write_params`` per-column dispatch:

    - ``animal_id`` and ``fecha_inicio`` are required (text/UUID).
    - The optional UUID FK columns use ``optional_text`` so blank
      inputs normalize to ``None``.
    - ``fecha_final`` and the three free-text legacy denormalizations
      (``direccion``, ``telefono``, ``observaciones``) use
      ``optional_text`` directly.
    """
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
        return optional_text(params, col)
    # fecha_final + the free-text legacy denormalizations.
    return optional_text(params, col)


def _extract_write_params(
    params: dict[str, Any],
    columns: tuple[str, ...] = ACOGIDA_WRITE_COLUMNS,
) -> list[Any]:
    """Build the SET values list in declaration order.

    Defaults to ``ACOGIDA_WRITE_COLUMNS`` (used by the INSERT path);
    the UPDATE path passes a different ``columns`` tuple (the partial
    set actually present in ``params``).
    """
    return [_extract_write_value(col, params) for col in columns]


# --- catalog builders ----------------------------------------------------


def build_acogida_insert(params: dict[str, Any]) -> tuple[str, list[Any]]:
    """Pure builder for the catalog INSERT.

    Validation runs BEFORE the SQL is emitted so a blank submission
    raises ``ValueError`` at the build step (the same contract the
    previous ``_build_write_params`` enforced — the service used to
    call it inline before passing the params to the executor). Uses
    the Spanish error template so the operator sees the friendlier
    message via the route layer.
    """
    return _ACOGIDA_INSERT_SQL, _extract_write_params(params)


def build_acogida_get_by_id(acogida_id: str) -> tuple[str, list[Any]]:
    return _ACOGIDA_GET_BY_ID_SQL, [acogida_id]


def build_acogida_list(activas_solo: bool) -> tuple[str, list[Any]]:
    """Catalog SELECT. No params — the active filter is in the SQL.

    ``activas_solo=True`` returns stays where ``fecha_final IS NULL``
    (open stays). ``activas_solo=False`` returns every stay (open +
    closed) ordered by ``fecha_inicio DESC``.
    """
    if activas_solo:
        return _ACOGIDA_LIST_ACTIVAS_SQL, []
    return _ACOGIDA_LIST_ALL_SQL, []


def build_acogida_update(
    acogida_id: str, params: dict[str, Any]
) -> tuple[str, list[Any]]:
    """Partial-update builder for the catalog.

    Every column in ``ACOGIDA_WRITE_COLUMNS`` is included EXCEPT those
    in ``_UPDATE_PATCH_ONLY_COLUMNS`` whose key is absent from
    ``params``. That carve-out makes ``fecha_final`` behave
    defensively: a partial-update caller that does not include the
    key gets a SQL UPDATE that does NOT touch the column (so a
    previously closed stay stays closed). The form always sends the
    field, so the live route path is unaffected — operators who want
    to reopen send ``fecha_final=""`` (which ``optional_text``
    normalizes to ``None``) and operators who want to keep the
    previous value simply omit the key. Issue #141.

    Returns ``(sql, params_for_sql)`` ready to be passed to
    ``client.execute_sql``. ``$1`` is reserved for the id; the SET
    placeholders start at ``$2``.
    """
    set_columns = tuple(
        col
        for col in ACOGIDA_WRITE_COLUMNS
        if col in params or col not in _UPDATE_PATCH_ONLY_COLUMNS
    )
    # psycopg3 uses $N positional placeholders. SET columns come first
    # in the params list; id comes LAST so WHERE id = $N+1.
    n_set = len(set_columns)
    sql = (
        "UPDATE acogidas "
        + "SET " + ", ".join(f"{col} = ${i + 1}" for i, col in enumerate(set_columns))
        + ", updated_at = now() "
        + f"WHERE id = ${n_set + 1} "
        + "RETURNING " + ", ".join(ACOGIDA_SELECT_COLUMNS)
    )
    write_params = _extract_write_params(params, columns=set_columns)
    return sql, [*write_params, acogida_id]


def build_acogida_close(acogida_id: str) -> tuple[str, list[Any]]:
    """Close: ``fecha_final = CURRENT_DATE``, ``activo`` stays true.

    D-EST-04: closing is a lifecycle event, NOT a soft-delete.
    """
    return _ACOGIDA_CLOSE_SQL, [acogida_id]


def build_acogida_delete(acogida_id: str) -> tuple[str, list[Any]]:
    """Atomic soft-delete: ``activo = false`` + ``fecha_baja = now()``.

    The ``WHERE id = $1 AND activo = true`` filter folds the existence
    check into the same statement under PostgreSQL's row lock; two
    concurrent calls produce exactly one ``True`` and one ``False``.
    """
    return _ACOGIDA_DELETE_SQL, [acogida_id]


# --- FK check builders ---------------------------------------------------


def build_acogida_check_animal(animal_id: str) -> tuple[str, list[Any]]:
    """SELECT for the FK check used by ``_validate_animal_exists_and_active``."""
    return _ACOGIDA_CHECK_ANIMAL_SQL, [animal_id]


def build_acogida_check_casa(casa_id: str) -> tuple[str, list[Any]]:
    """SELECT for the FK check used by ``_validate_casa_acogida_active``."""
    return _ACOGIDA_CHECK_CASA_SQL, [casa_id]


def build_acogida_check_voluntario(voluntario_id: str) -> tuple[str, list[Any]]:
    """SELECT for the FK check used by ``_validate_voluntario_activo``.

    VOL-05 pattern: only ACTIVE voluntarios are valid for new FK
    references. The DB-side ``AND activo = true`` is defense in
    depth; the service also checks ``activo`` explicitly so the
    validation works against test mocks that don't simulate the
    WHERE clause.
    """
    return _ACOGIDA_CHECK_VOLUNTARIO_SQL, [voluntario_id]


def build_acogida_check_entrada(entrada_id: str) -> tuple[str, list[Any]]:
    """SELECT for the FK check used by ``_validate_entrada_exists_if_present``.

    No ``activo`` filter — legacy entries can be soft-deleted, but the
    FK should still resolve.
    """
    return _ACOGIDA_CHECK_ENTRADA_SQL, [entrada_id]


# --- foster_capacity_overrides link builder (issue #142) ----------------


def build_acogida_link_override(
    estancia_id: str,
    override_id: str,
    casa_acogida_id: str | None,
    animal_id: str,
) -> tuple[str, list[Any]]:
    """Link the foster_capacity_overrides row to the new estancia.

    Issue #142: after the INSERT succeeds, update the
    ``foster_capacity_overrides.estancia_id`` column so the audit log
    row is no longer orphaned. The ``AND estancia_id IS NULL`` guard
    prevents double-linking. The ``AND casa_acogida_id = $3 AND
    animal_id = $4`` guards (judgment-day CRITICAL §1.2 + HIGH §3.2
    follow-up to PR #155) scope the link to the override's recorded
    casa+animal — a forged ``override_id`` from another operator's
    session cannot link to a different stay because the form's
    casa+animal pair will not match. Empty ``override_id`` (from a
    missing form field that serializes as ``""``) is treated the
    same as absent — no UPDATE.

    Params are: ``estancia_id``, ``override_id``, ``casa_acogida_id``
    (nullable for legacy stays without a casa), ``animal_id``.
    """
    return _ACOGIDA_LINK_OVERRIDE_SQL, [
        estancia_id,
        override_id,
        casa_acogida_id,
        animal_id,
    ]
