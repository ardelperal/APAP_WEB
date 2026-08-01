"""Service layer for minimal intake entries.

This module is deliberately framework-agnostic: routes parse HTTP and render
templates, while the service owns SQL, validation, duplicate handling, mapping,
and soft-delete behavior for the public ``entradas`` CRUD contract.

The public contract intentionally excludes the migration-compatibility physical
columns ``voluntario_salida_id``, ``fecha_salida``,
``fecha_entrega_propietario``, and ``donativo_entregador``. Those fields remain
in the table for legacy import compatibility but are not written by this slice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.data_access import SqlExecutor
from app.core.forms import optional_text as _optional_text
from app.core.forms import required_text as _required_text
from app.core.insforge import InsForgeError


class EntradaConflictError(ValueError):
    """Raised when an intake entry conflicts with the natural key."""


@dataclass(frozen=True, slots=True)
class Entrada:
    """A public service-row representation for ``entradas``."""

    id: str
    animal_id: str
    fecha_entrada: str
    activo: bool = True
    voluntario_entrada_id: str | None = None
    origen: str | None = None
    motivo: str | None = None
    observaciones: str | None = None
    fecha_alta: str | None = None
    updated_at: str | None = None


_WRITE_COLUMNS = (
    "animal_id",
    "voluntario_entrada_id",
    "fecha_entrada",
    "origen",
    "motivo",
    "observaciones",
)

_SELECT_COLUMNS = (
    "id",
    "animal_id",
    "voluntario_entrada_id",
    "fecha_entrada",
    "origen",
    "motivo",
    "observaciones",
    "fecha_alta",
    "updated_at",
    "activo",
)


_CHECK_ANIMAL_SQL = """
SELECT id, activo
FROM animales
WHERE id = $1
"""

_CHECK_ACTIVE_VOLUNTEER_SQL = """
SELECT id, activo
FROM voluntarios
WHERE id = $1
  AND activo = true
"""

_INSERT_ENTRADA_SQL = f"""
INSERT INTO entradas ({", ".join(_WRITE_COLUMNS)})
VALUES ({", ".join(f"${i+1}" for i in range(len(_WRITE_COLUMNS)))})
RETURNING {", ".join(_SELECT_COLUMNS)}
"""  # noqa: S608 constant col names only; all user data is $N params

_LIST_ENTRADAS_SQL = f"""
SELECT {", ".join(_SELECT_COLUMNS)}
FROM entradas
WHERE activo = true
ORDER BY fecha_alta DESC
"""  # noqa: S608 constant column lists only

_GET_ENTRADA_BY_ID_SQL = f"""
SELECT {", ".join(_SELECT_COLUMNS)}
FROM entradas
WHERE id = $1
"""  # noqa: S608 constant column lists only

_UPDATE_ENTRADA_SQL = (
    "UPDATE entradas SET "  # noqa: S608 constant col names only; all user values are $N params
    + ", ".join(f"{col} = ${i+2}" for i, col in enumerate(_WRITE_COLUMNS))
    + ", updated_at = now() "
    + "WHERE id = $1 "
    + "RETURNING "
    + ", ".join(_SELECT_COLUMNS)
)

_DELETE_ENTRADA_SQL = """
UPDATE entradas
SET activo = false,
    updated_at = now()
WHERE id = $1
RETURNING id, activo
"""


def _row_to_entrada(row: dict[str, Any]) -> Entrada:
    return Entrada(
        id=str(row["id"]),
        animal_id=str(row["animal_id"]),
        voluntario_entrada_id=(
            str(row["voluntario_entrada_id"])
            if row.get("voluntario_entrada_id")
            else None
        ),
        fecha_entrada=str(row["fecha_entrada"]),
        origen=row.get("origen"),
        motivo=row.get("motivo"),
        observaciones=row.get("observaciones"),
        fecha_alta=str(row["fecha_alta"]) if row.get("fecha_alta") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
        activo=bool(row.get("activo", True)),
    )


def _build_write_params(params: dict[str, Any]) -> list[Any]:
    return [
        _required_text(params, "animal_id"),
        _optional_text(params, "voluntario_entrada_id"),
        _required_text(params, "fecha_entrada"),
        _optional_text(params, "origen"),
        _optional_text(params, "motivo"),
        _optional_text(params, "observaciones"),
    ]


def _validate_references(client: SqlExecutor, params: dict[str, Any]) -> None:
    animal_id = _required_text(params, "animal_id")
    if not client.execute_sql(_CHECK_ANIMAL_SQL, [animal_id]):
        raise ValueError("animal_id does not reference an existing animal")

    voluntario_id = _optional_text(params, "voluntario_entrada_id")
    if voluntario_id and not client.execute_sql(_CHECK_ACTIVE_VOLUNTEER_SQL, [voluntario_id]):
        raise ValueError("voluntario_entrada_id must reference an active volunteer")


def _is_duplicate_error(exc: InsForgeError) -> bool:
    body = str(exc.body).lower()
    return exc.status_code == 409 and (
        "duplicate" in body or "entradas_natural_key" in body or "unique" in body
    )


# Explicit intra-package contracts. The private implementation names remain
# stable for the critical-helper coverage gate while sibling modules import
# only these intentional public aliases.
row_to_entrada = _row_to_entrada
is_duplicate_error = _is_duplicate_error


def create_entrada(client: SqlExecutor, params: dict[str, Any]) -> Entrada:
    """Create an intake entry and return the persisted row."""
    _build_write_params(params)
    _validate_references(client, params)

    try:
        rows = client.execute_sql(_INSERT_ENTRADA_SQL, _build_write_params(params))
    except InsForgeError as exc:
        if _is_duplicate_error(exc):
            raise EntradaConflictError("entrada duplicada para animal_id y fecha_entrada") from exc
        raise
    return _row_to_entrada(rows[0])


def list_entradas(client: SqlExecutor) -> list[Entrada]:
    """Return active intake entries, newest first."""
    rows = client.execute_sql(_LIST_ENTRADAS_SQL)
    return [_row_to_entrada(row) for row in rows]


def get_entrada_by_id(client: SqlExecutor, entrada_id: str) -> Entrada | None:
    """Return one intake entry by id, or ``None`` when it does not exist."""
    rows = client.execute_sql(_GET_ENTRADA_BY_ID_SQL, [entrada_id])
    return _row_to_entrada(rows[0]) if rows else None


def update_entrada(
    client: SqlExecutor,
    entrada_id: str,
    params: dict[str, Any],
) -> Entrada | None:
    """Update the public intake-entry fields and return the updated row."""
    write_params = _build_write_params(params)
    _validate_references(client, params)

    try:
        rows = client.execute_sql(_UPDATE_ENTRADA_SQL, [entrada_id, *write_params])
    except InsForgeError as exc:
        if _is_duplicate_error(exc):
            raise EntradaConflictError("entrada duplicada para animal_id y fecha_entrada") from exc
        raise
    return _row_to_entrada(rows[0]) if rows else None


def delete_entrada(client: SqlExecutor, entrada_id: str) -> bool:
    """Soft-delete an intake entry. Physical deletes are intentionally forbidden."""
    rows = client.execute_sql(_DELETE_ENTRADA_SQL, [entrada_id])
    return bool(rows)
