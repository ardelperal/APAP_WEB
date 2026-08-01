"""SQL builder seam for ``app.modules.materiales`` per AGENTS.md §22.

The query/service separation: SQL strings and parameter shaping live
here in pure builder functions that return ``(sql, params)`` tuples.
The service modules (``service.py`` and ``estancia_material_service.py``)
import these builders, apply domain validation, and talk to the SQL
executor.

Rule §22 — the seam is testable: the shape of the SQL is assertable
in a plain unit test (see ``tests/test_materiales_queries.py``) without
spinning up transport, InsForge, or HTTP. The service layer stays
focused on dataclasses, mapping, validation, and orchestration.

Rule §1 — routes must never import from this module. The graph is
``routes.py -> service.py -> queries.py``; ``routes.py -> queries.py``
would violate the layer boundary.

Rule §4 — column lists and SQL templates live in exactly one place.
The Material catalog and EstanciaMaterial junction are NOT redefined
anywhere else in the module.

Rule §9 — no ``log_safe`` calls here. Query construction is silent;
the service layer emits the audit events when it executes the SQL.
"""

from __future__ import annotations

from functools import partial
from typing import Any, Final

from app.core.forms import optional_text, required_text

# The Spanish error template is part of the SQL parameter contract —
# the route layer formats the rejection as
# ``f"No se pudo guardar el material: {exc}"`` so the operator sees
# the Spanish message. The previous ``service.py`` partial-wrapped
# ``required_text`` with this template; the wrapping now lives here
# because this is the only module that calls ``required_text`` after
# the §22 seam extraction.
_required_text = partial(
    required_text, error_template="{field} es obligatorio y no puede estar vacio"
)

# --- column tuples (single source of truth per §4) ----------------------


MATERIAL_WRITE_COLUMNS: Final[tuple[str, ...]] = (
    "material",
    "tamano",
    "color",
    "observaciones",
)


MATERIAL_SELECT_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "material",
    "tamano",
    "color",
    "observaciones",
    "activo",
    "fecha_alta",
    "fecha_baja",
    "updated_at",
)


JUNCTION_WRITE_COLUMNS: Final[tuple[str, ...]] = (
    "estancia_id",
    "material_id",
    "cantidad",
    "notas",
)


JUNCTION_SELECT_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "estancia_id",
    "material_id",
    "cantidad",
    "notas",
    "fecha_alta",
    "activo",
)


# --- catalog SQL constants ----------------------------------------------


_MATERIAL_INSERT_SQL: Final[str] = (
    f"INSERT INTO materiales ({', '.join(MATERIAL_WRITE_COLUMNS)}) "  # noqa: S608 constant col names only; all user values are $N params
    f"VALUES ({', '.join(f'${i + 1}' for i in range(len(MATERIAL_WRITE_COLUMNS)))}) "
    f"RETURNING {', '.join(MATERIAL_SELECT_COLUMNS)}"
)


_MATERIAL_GET_BY_ID_SQL: Final[str] = (
    f"SELECT {', '.join(MATERIAL_SELECT_COLUMNS)} "  # noqa: S608 constant column list only
    "FROM materiales WHERE id = $1"
)


_MATERIAL_LIST_FILTER_ACTIVE_SQL: Final[str] = (
    f"SELECT {', '.join(MATERIAL_SELECT_COLUMNS)} "  # noqa: S608 constant column list only
    "FROM materiales "
    "WHERE activo = true "
    "ORDER BY fecha_alta DESC"
)


_MATERIAL_LIST_ALL_SQL: Final[str] = (
    f"SELECT {', '.join(MATERIAL_SELECT_COLUMNS)} "  # noqa: S608 constant column list only
    "FROM materiales "
    "ORDER BY fecha_alta DESC"
)


# Atomic soft-delete: existence check + deactivation in one statement
# under PostgreSQL's row lock. Mirrors the foster/casa-acogida pattern.
_MATERIAL_DEACTIVATE_SQL: Final[str] = """
UPDATE materiales
SET activo = false,
    fecha_baja = now(),
    updated_at = now()
WHERE id = $1 AND activo = true
RETURNING id
"""


# Cascade: soft-delete every active junction row pointing at this
# material. Runs AFTER the catalog UPDATE so the material row is
# already inactive when the cascade flips the junctions.
_MATERIAL_CASCADE_DEACTIVATE_SQL: Final[str] = """
UPDATE estancia_materiales
SET activo = false
WHERE material_id = $1 AND activo = true
RETURNING id
"""


# --- junction SQL constants ---------------------------------------------


_JUNCTION_INSERT_SQL: Final[str] = (
    f"INSERT INTO estancia_materiales ({', '.join(JUNCTION_WRITE_COLUMNS)}) "  # noqa: S608 constant col names only; all user values are $N params
    f"VALUES ({', '.join(f'${i + 1}' for i in range(len(JUNCTION_WRITE_COLUMNS)))}) "
    f"RETURNING {', '.join(JUNCTION_SELECT_COLUMNS)}"
)


_JUNCTION_LIST_FOR_ESTANCIA_SQL: Final[str] = (
    f"SELECT {', '.join(JUNCTION_SELECT_COLUMNS)} "  # noqa: S608 constant column list only
    "FROM estancia_materiales "
    "WHERE estancia_id = $1 AND activo = true "
    "ORDER BY fecha_alta DESC"
)


_JUNCTION_LIST_FOR_ESTANCIA_ALL_SQL: Final[str] = (
    f"SELECT {', '.join(JUNCTION_SELECT_COLUMNS)} "  # noqa: S608 constant column list only
    "FROM estancia_materiales "
    "WHERE estancia_id = $1 "
    "ORDER BY fecha_alta DESC"
)


# Atomic soft-delete (idempotent).
_JUNCTION_DEACTIVATE_SQL: Final[str] = """
UPDATE estancia_materiales
SET activo = false
WHERE id = $1 AND activo = true
RETURNING id
"""


# --- FK existence checks (read-only, no writes) -------------------------


_ESTANCIA_OPEN_AND_ACTIVE_SQL: Final[str] = (
    "SELECT id, activo, fecha_final FROM acogidas WHERE id = $1"
)


_MATERIAL_ACTIVE_SQL: Final[str] = (
    "SELECT id, activo FROM materiales WHERE id = $1"
)


# --- domain validation embedded in builders -----------------------------


def _validate_cantidad(value: Any) -> int:
    """Validate the ``cantidad`` parameter for the junction.

    Mirrors ``app/modules/foster/service.py::_validate_capacidad``.
    Integer > 0; ``bool`` is rejected explicitly (Python's ``bool`` is
    an ``int`` subclass, so ``True`` would otherwise pass as ``1``).

    Lives in queries.py because the validation is part of the SQL
    parameter contract — the builder must enforce it before the
    SQL is emitted so a bad value never reaches the DB CHECK
    constraint as a 500.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("cantidad debe ser un entero positivo (>= 1)")
    return value


# --- catalog builders ----------------------------------------------------


def build_material_insert(params: dict[str, Any]) -> tuple[str, list[Any]]:
    """Pure builder for the catalog INSERT.

    Validation runs BEFORE the SQL is emitted so a blank submission
    raises ``ValueError`` at the build step (the same contract the
    previous ``_build_material_write_params`` enforced — the service
    used to call it inline before passing the params to the executor).
    Uses the Spanish error template so the operator sees the friendlier
    message via the route layer's ``f"No se pudo guardar el material"``.
    """
    return _MATERIAL_INSERT_SQL, [
        _required_text(params, "material"),
        _required_text(params, "tamano"),
        _required_text(params, "color"),
        optional_text(params, "observaciones"),
    ]


def build_material_get_by_id(material_id: str) -> tuple[str, list[Any]]:
    return _MATERIAL_GET_BY_ID_SQL, [material_id]


def build_material_list(activos_solo: bool) -> tuple[str, list[Any]]:
    """Catalog SELECT. No params — the active filter is in the SQL."""
    if activos_solo:
        return _MATERIAL_LIST_FILTER_ACTIVE_SQL, []
    return _MATERIAL_LIST_ALL_SQL, []


def build_material_update(
    material_id: str, params: dict[str, Any]
) -> tuple[str, list[Any]]:
    """Partial-update builder for the catalog.

    Only the keys actually present in ``params`` are written. The
    catalog's PK + ``updated_at`` bump are unconditional; ``activo``,
    ``fecha_alta``, ``fecha_baja`` are NOT in the write set (those
    are managed by the deactivate flow and the DB defaults).
    """
    set_columns = tuple(col for col in MATERIAL_WRITE_COLUMNS if col in params)
    if not set_columns:
        raise ValueError(
            "update_material requires at least one writable field "
            "(material / tamano / color / observaciones)"
        )
    sql = (
        "UPDATE materiales SET "  # noqa: S608 constant col names only; all user values are $N params
        + ", ".join(f"{col} = ${i + 2}" for i, col in enumerate(set_columns))
        + ", updated_at = now() "
        + "WHERE id = $1 "
        + "RETURNING " + ", ".join(MATERIAL_SELECT_COLUMNS)
    )

    extractors: dict[str, Any] = {
        "material": lambda: _required_text(params, "material"),
        "tamano": lambda: _required_text(params, "tamano"),
        "color": lambda: _required_text(params, "color"),
        "observaciones": lambda: optional_text(params, "observaciones"),
    }
    write_params = [extractors[col]() for col in set_columns]
    return sql, write_params


def build_material_deactivate(material_id: str) -> tuple[str, list[Any]]:
    return _MATERIAL_DEACTIVATE_SQL, [material_id]


def build_material_cascade_deactivate(material_id: str) -> tuple[str, list[Any]]:
    """Cascade UPDATE that flips every active junction row for the material."""
    return _MATERIAL_CASCADE_DEACTIVATE_SQL, [material_id]


# --- FK check builders ---------------------------------------------------


def build_material_active(material_id: str) -> tuple[str, list[Any]]:
    """SELECT for the FK check used by ``_validate_material_active``."""
    return _MATERIAL_ACTIVE_SQL, [material_id]


def build_estancia_active(estancia_id: str) -> tuple[str, list[Any]]:
    """SELECT for the FK check used by ``_validate_estancia_open_and_active``.

    Returns the columns the service needs (``activo``, ``fecha_final``)
    so it can decide reject reasons in Python without complex SQL.
    """
    return _ESTANCIA_OPEN_AND_ACTIVE_SQL, [estancia_id]


# --- junction builders ---------------------------------------------------


def build_junction_insert(
    estancia_id: str,
    material_id: str,
    cantidad: int,
    notas: str | None,
) -> tuple[str, list[Any]]:
    """Pure builder for the junction INSERT.

    The ``cantidad`` column is validated by the builder (int > 0,
    bool rejected) so a bad value never reaches the DB CHECK constraint.
    Order matches ``JUNCTION_WRITE_COLUMNS``.
    """
    return _JUNCTION_INSERT_SQL, [
        estancia_id,
        material_id,
        _validate_cantidad(cantidad),
        notas,
    ]


def build_junction_list_for_estancia(
    estancia_id: str, activos_solo: bool
) -> tuple[str, list[Any]]:
    """Junction SELECT. ``activos_solo`` toggles the active filter."""
    if activos_solo:
        return _JUNCTION_LIST_FOR_ESTANCIA_SQL, [estancia_id]
    return _JUNCTION_LIST_FOR_ESTANCIA_ALL_SQL, [estancia_id]


def build_junction_deactivate(junction_id: str) -> tuple[str, list[Any]]:
    return _JUNCTION_DEACTIVATE_SQL, [junction_id]
