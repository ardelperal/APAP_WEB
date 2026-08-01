"""Service layer for FOSTER-01 casas de acogida.

Owns SQL, validation, mapping, and soft-delete for the
``casas_acogida`` table (legacy ``TbAcogidaCasas`` mirror, verified
via Dysflow ``projectId=apap`` on 2026-07-04, 19 legacy columns + 2
justified improvements — see ``app/core/domain.py``).

Validation contract (mirrors INTAKE-01 style):

- Required: ``nombre``, ``apellidos``, ``calle``, ``telefono``, ``coche``,
  ``capacidad``.
- ``coche`` MUST be exactly ``"Sí"`` or ``"No"`` (Spanish tilde preserved,
  same pattern as ``cesiones_propietario``).
- ``especie_preferente`` MUST be ``None`` or one of
  ``{"CANINA", "FELINA"}`` (legacy enum).
- ``capacidad`` MUST be a positive integer.
- Empty strings (after ``.strip()``) count as missing for required
  fields.
- Soft-delete via ``activo = false`` + ``fecha_baja = now()``; physical
  deletes are forbidden (project-wide pattern).
- Search by especie: a house with ``especie_preferente IS NULL`` counts
  as match for any filter value (the operator's "cualquier especie"
  pattern, faithful to legacy).

Framework-agnostic: routes are thin HTTP glue; SQL, validation, and
mapping all live here.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Any, Final

from app.core.data_access import SqlExecutor
from app.core.forms import optional_text as _optional_text
from app.core.forms import required_text
from app.core.logging import log_safe

_required_text = partial(
    required_text, error_template="{field} es obligatorio y no puede estar vacío"
)

VALID_COCHE_VALUES: Final[frozenset[str]] = frozenset({"Sí", "No"})
VALID_ESPECIE_VALUES: Final[frozenset[str]] = frozenset({"CANINA", "FELINA"})


@dataclass(frozen=True, slots=True)
class CasaAcogida:
    """A public service-row representation for ``casas_acogida``."""

    id: str
    nombre: str
    apellidos: str
    calle: str
    telefono: str
    coche: str
    capacidad: int
    activo: bool = True
    dni_acogedor: str | None = None
    numero: str | None = None
    piso: str | None = None
    letra: str | None = None
    localidad: str | None = None
    provincia: str | None = None
    cp: str | None = None
    telefono2: str | None = None
    email: str | None = None
    vinculacion: str | None = None
    caracteristicas: str | None = None
    especie_preferente: str | None = None
    observaciones: str | None = None
    fecha_alta: str | None = None
    fecha_baja: str | None = None
    updated_at: str | None = None


_WRITE_COLUMNS: Final[tuple[str, ...]] = (
    "nombre",
    "apellidos",
    "dni_acogedor",
    "calle",
    "numero",
    "piso",
    "letra",
    "localidad",
    "provincia",
    "cp",
    "telefono",
    "telefono2",
    "email",
    "vinculacion",
    "caracteristicas",
    "coche",
    "especie_preferente",
    "observaciones",
    "capacidad",
)


_SELECT_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "nombre",
    "apellidos",
    "dni_acogedor",
    "calle",
    "numero",
    "piso",
    "letra",
    "localidad",
    "provincia",
    "cp",
    "telefono",
    "telefono2",
    "email",
    "vinculacion",
    "caracteristicas",
    "coche",
    "especie_preferente",
    "observaciones",
    "capacidad",
    "fecha_alta",
    "fecha_baja",
    "updated_at",
    "activo",
)


_INSERT_CASA_SQL: Final[str] = (
    f"INSERT INTO casas_acogida ({', '.join(_WRITE_COLUMNS)}) "  # noqa: S608 constant col names only; all user values are $N params
    f"VALUES ({', '.join(f'${i + 1}' for i in range(len(_WRITE_COLUMNS)))}) "
    f"RETURNING {', '.join(_SELECT_COLUMNS)}"
)


_LIST_CASAS_SQL: Final[str] = (
    f"SELECT {', '.join(_SELECT_COLUMNS)} "  # noqa: S608 constant column list only
    "FROM casas_acogida "
    "WHERE activo = true "
    "ORDER BY fecha_alta DESC"
)


_LIST_CASAS_BY_ESPECIE_SQL: Final[str] = (
    f"SELECT {', '.join(_SELECT_COLUMNS)} "  # noqa: S608 constant column list only
    "FROM casas_acogida "
    "WHERE activo = true "
    "AND (especie_preferente = $1 OR especie_preferente IS NULL) "
    "ORDER BY fecha_alta DESC"
)


_GET_CASA_BY_ID_SQL: Final[str] = (
    f"SELECT {', '.join(_SELECT_COLUMNS)} FROM casas_acogida WHERE id = $1"  # noqa: S608 constant column list only
)


_UPDATE_CASA_SQL: Final[str] = (
    "UPDATE casas_acogida SET "  # noqa: S608 constant col names only; all user values are $N params
    + ", ".join(f"{col} = ${i + 2}" for i, col in enumerate(_WRITE_COLUMNS))
    + ", updated_at = now() "
    + "WHERE id = $1 "
    + "RETURNING "
    + ", ".join(_SELECT_COLUMNS)
)


# Atomic soft-delete: existence check + deactivation in one statement
# under PostgreSQL's row lock. Mirrors
# ``app/modules/voluntarios/service.py::_DEACTIVATE_VOLUNTARIO_SQL``.
_DELETE_CASA_SQL: Final[str] = """
UPDATE casas_acogida
SET activo = false,
    fecha_baja = now(),
    updated_at = now()
WHERE id = $1 AND activo = true
RETURNING id
"""


def _row_to_casa_acogida(row: dict[str, Any]) -> CasaAcogida:
    return CasaAcogida(
        id=str(row["id"]),
        nombre=str(row["nombre"]),
        apellidos=str(row["apellidos"]),
        dni_acogedor=row.get("dni_acogedor"),
        calle=str(row["calle"]),
        numero=row.get("numero"),
        piso=row.get("piso"),
        letra=row.get("letra"),
        localidad=row.get("localidad"),
        provincia=row.get("provincia"),
        cp=row.get("cp"),
        telefono=str(row["telefono"]),
        telefono2=row.get("telefono2"),
        email=row.get("email"),
        vinculacion=row.get("vinculacion"),
        caracteristicas=row.get("caracteristicas"),
        coche=str(row["coche"]),
        especie_preferente=row.get("especie_preferente"),
        observaciones=row.get("observaciones"),
        capacidad=int(row["capacidad"]),
        fecha_alta=str(row["fecha_alta"]) if row.get("fecha_alta") else None,
        fecha_baja=str(row["fecha_baja"]) if row.get("fecha_baja") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
        activo=bool(row.get("activo", True)),
    )


def _validate_coche(value: Any) -> str:
    if not isinstance(value, str) or value not in VALID_COCHE_VALUES:
        raise ValueError(
            "coche debe ser 'Sí' o 'No' (con tilde en la primera opción)"
        )
    return value


def _validate_especie_preferente(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if value not in VALID_ESPECIE_VALUES:
        raise ValueError(
            "especie_preferente debe ser 'CANINA', 'FELINA' o null"
        )
    return value


def _validate_capacidad(value: Any) -> int:
    # ``bool`` is a subclass of ``int`` in Python, so we must reject it
    # explicitly — ``True`` would otherwise pass as ``1``.
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("capacidad debe ser un entero positivo (>= 1)")
    return value


def _build_write_params(params: dict[str, Any]) -> list[Any]:
    """Order matches ``_WRITE_COLUMNS`` for the INSERT/UPDATE placeholders."""
    return [
        _required_text(params, "nombre"),
        _required_text(params, "apellidos"),
        _optional_text(params, "dni_acogedor"),
        _required_text(params, "calle"),
        _optional_text(params, "numero"),
        _optional_text(params, "piso"),
        _optional_text(params, "letra"),
        _optional_text(params, "localidad"),
        _optional_text(params, "provincia"),
        _optional_text(params, "cp"),
        _required_text(params, "telefono"),
        _optional_text(params, "telefono2"),
        _optional_text(params, "email"),
        _optional_text(params, "vinculacion"),
        _optional_text(params, "caracteristicas"),
        _validate_coche(params.get("coche")),
        _validate_especie_preferente(params.get("especie_preferente")),
        _optional_text(params, "observaciones"),
        _validate_capacidad(params.get("capacidad")),
    ]


def create_casa_acogida(
    client: SqlExecutor, params: dict[str, Any]
) -> CasaAcogida:
    """Insert a new casa de acogida and return the persisted row."""
    write_params = _build_write_params(params)
    rows = client.execute_sql(_INSERT_CASA_SQL, write_params)
    casa = _row_to_casa_acogida(rows[0])
    log_safe(
        "foster.casa_acogida.created",
        casa_acogida_id=casa.id,
        capacidad=casa.capacidad,
    )
    return casa


def list_casas_acogida(
    client: SqlExecutor, especie: str | None = None
) -> list[CasaAcogida]:
    """Return active casas de acogida, optionally filtered by especie.

    When ``especie`` is ``None``, returns all active houses. When a value
    is provided, returns houses whose ``especie_preferente`` is the
    value OR is NULL (the operator's "cualquier especie" pattern).
    """
    if especie:
        rows = client.execute_sql(_LIST_CASAS_BY_ESPECIE_SQL, [especie])
    else:
        rows = client.execute_sql(_LIST_CASAS_SQL)
    return [_row_to_casa_acogida(row) for row in rows]


def get_casa_acogida_by_id(
    client: SqlExecutor, casa_id: str
) -> CasaAcogida | None:
    """Return one casa de acogida by id (active or inactive), or None."""
    rows = client.execute_sql(_GET_CASA_BY_ID_SQL, [casa_id])
    return _row_to_casa_acogida(rows[0]) if rows else None


def update_casa_acogida(
    client: SqlExecutor, casa_id: str, params: dict[str, Any]
) -> CasaAcogida | None:
    """Update a casa de acogida and return the updated row, or None."""
    write_params = _build_write_params(params)
    rows = client.execute_sql(_UPDATE_CASA_SQL, [casa_id, *write_params])
    if not rows:
        return None
    casa = _row_to_casa_acogida(rows[0])
    log_safe("foster.casa_acogida.updated", casa_acogida_id=casa.id)
    return casa


def delete_casa_acogida(client: SqlExecutor, casa_id: str) -> bool:
    """Atomically soft-delete a casa de acogida.

    Returns ``True`` if the row was active and was deactivated.
    Returns ``False`` if the row does not exist OR was already inactive.

    The ``WHERE id = $1 AND activo = true`` filter folds the existence
    check into the same statement under PostgreSQL's row lock; two
    concurrent calls produce exactly one ``True`` and one ``False``.
    Pattern mirrors
    ``app/modules/voluntarios/service.py::deactivate_voluntario``.
    """
    rows = client.execute_sql(_DELETE_CASA_SQL, [casa_id])
    deactivated = bool(rows)
    if deactivated:
        log_safe("foster.casa_acogida.deleted", casa_acogida_id=casa_id)
    return deactivated
