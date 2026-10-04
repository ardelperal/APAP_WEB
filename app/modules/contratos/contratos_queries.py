"""Canonical SQL owner for the ``contratos`` table (DOC-01 SLICE 2, #1109).

This module is the single source of truth for SQL that reads or writes
the ``contratos`` table. The cesiones slice (issue #1066) writes a
``contratos`` row as a side effect of owner-surrender creation, but
that INSERT is cesion-tied and lives in
``app.modules.cesiones.service`` because the cesion transaction owns
the entire (cesion + contrato) atomic unit. Every OTHER read or write
against ``contratos`` belongs here:

- ``exists_for_entity`` -- UNIQUE enforcement of the legacy
  ``TbContratosAnexos`` rule "un único contrato por tipo por entidad"
  (``docs/legacy-signed-contract-flow.md`` §5). The check is the
  pre-flight before the INSERT; the DB UNIQUE constraint is the
  defence-in-depth that translates 409 to ``DuplicateKeyError`` if a
  race slips through.
- ``get_contrato_for_entity`` -- the download-route lookup; returns
  the ``(id, tipo_contrato_id, ...)`` row so the storage port can
  stream the PDF. The bucket/key for the stored PDF live in MinIO,
  not in the ``contratos`` table (the legacy ``TbContratosAnexos``
  ``NombreArchivo`` column is reconstructed at request time from the
  ``(Tipo, ID)`` pair).
- ``insert_contrato`` -- writes a new ``contratos`` row for any of
  the four entity FKs (entrada / adopcion / acogida / cesion). The
  ``contratos_exactly_one_entity`` CHECK enforces exactly one FK;
  this module is the only caller that touches the table from the
  contratos slice.

The catalog lookup (resolving ``tipo_contrato_id`` from
``catalogos_tipos_contrato.codigo``) lives here too so the
``generate_contrato`` use case can stay transport-free of
``catalogos_tipos_contrato`` SQL.

Architectural notes (AGENTS.md §22, §33.4):

- HR-5: SQL is confined to this module. Routes, use cases and
  ports only import the helper functions, never the SQL strings.
- HR-15: this module is NOT called ``service.py`` on purpose --
  the slice's public service surface is the use case
  ``app.modules.contratos.application.generate_contrato``.
- Layer discipline: the module is NOT under ``adapters/`` because
  the adapter pattern is reserved for transport boundaries
  (HTTP / S3 / filesystem). The contratos table is part of the
  domain's persistence surface, the same way the cesiones
  service module owns its table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.core.data_access import BackendError, SqlExecutor

#: Entity types the contratos table can point at. Mirrors the legacy
#: ``TbContratosAnexos`` ``IDEntrada / IDAcogida / IDAdopcion`` /
#: ``cesion_id`` FKs and the ``contratos_exactly_one_entity`` CHECK
#: constraint.
EntityType = Literal["entrada", "adopcion", "acogida", "cesion"]

#: Mapping from the public ``EntityType`` to the actual ``contratos``
#: column the row is anchored on. Lives here (not in the use case) so
#: the SQL knows which FK column to filter / insert.
_ENTITY_COLUMN: dict[str, str] = {
    "entrada": "entrada_id",
    "adopcion": "adopcion_id",
    "acogida": "acogida_id",
    "cesion": "cesion_id",
}


# --- Errors ---------------------------------------------------------------


class ContratoConflictError(ValueError):
    """Raised when a (tipo, entity) contract already exists.

    The legacy ``TbContratosAnexos`` rule is "un único contrato por
    tipo por entidad" (``docs/legacy-signed-contract-flow.md`` §5);
    the use case translates this to HTTP 409 at the route boundary.
    Subclasses :class:`ValueError` so legacy ``except ValueError``
    clauses keep working.
    """


# --- Public dataclass -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class ContratoRecord:
    """A persisted ``contratos`` row.

    The slice composes this from the SQL result plus the inputs the
    use case already knows (``entity_type``, ``entity_id``,
    ``tipo_codigo``). The bucket/key for the stored PDF live in
    MinIO; the download route reconstructs them from the legacy
    ``{Tipo}_{ID}.pdf`` naming convention so the contratos table
    does not need a storage pointer column.
    """

    id: str
    tipo_contrato_id: str
    tipo_codigo: str
    entity_type: str
    entity_id: str
    numero_contrato: str
    fecha: str | None = None


# --- SQL constants --------------------------------------------------------

_LOOKUP_TIPO_CONTRATO_SQL = (
    "SELECT id, codigo FROM catalogos_tipos_contrato WHERE codigo = $1"
)

#: INSERT statement for the contratos table. The ``entity_column``
#: is interpolated as an identifier (constrained to
#: :data:`_ENTITY_COLUMN`); the entity value is always a parameter.
_INSERT_CONTRATO_SQL_TEMPLATE = (
    "INSERT INTO contratos ("
    "tipo_contrato_id, numero_contrato, fecha, {entity_column}"
    ") VALUES ($1, $2, $3, $4) RETURNING id, tipo_contrato_id, "
    "numero_contrato, fecha"
)

#: Lookup used by the download route. Filters by tipo_codigo
#: (joined to ``catalogos_tipos_contrato``) and the entity FK
#: column. The slice composes ``entity_type`` and ``entity_id``
#: from the inputs that produced the row, so the SQL only returns
#: the columns it knows about server-side.
_SELECT_CONTRATO_SQL_TEMPLATE = (
    "SELECT c.id, c.tipo_contrato_id, c.numero_contrato, c.fecha "
    "FROM contratos c "
    "JOIN catalogos_tipos_contrato tc ON tc.id = c.tipo_contrato_id "
    "WHERE tc.codigo = $1 AND c.{entity_column} = $2"
)

#: Pre-INSERT existence check. Mirrors the SELECT above but with
#: ``SELECT 1`` so the result can short-circuit on the first row.
#: The DB UNIQUE constraint is the defence-in-depth; this check
#: exists only to produce a clean 409 message for the operator.
_EXISTS_FOR_ENTITY_SQL_TEMPLATE = (
    "SELECT 1 FROM contratos c "
    "JOIN catalogos_tipos_contrato tc ON tc.id = c.tipo_contrato_id "
    "WHERE tc.codigo = $1 AND c.{entity_column} = $2 LIMIT 1"
)


# --- Public API -----------------------------------------------------------


def entity_column(entity_type: str) -> str:
    """Return the contratos-table FK column for ``entity_type``.

    Raises:
        ValueError: ``entity_type`` is not one of the four supported
            types. The route uses this to fail fast (422) before any
            SQL runs.
    """
    column = _ENTITY_COLUMN.get(entity_type)
    if column is None:
        raise ValueError(  # noqa: TRY003 -- operator-facing diagnostic
            f"entity_type invalido: {entity_type!r} "
            f"(esperado uno de {sorted(_ENTITY_COLUMN)})"
        )
    return column


def resolve_tipo_contrato_id(
    client: SqlExecutor,
    *,
    tipo: str,
) -> str:
    """Return the ``catalogos_tipos_contrato.id`` for the given codigo.

    Raises:
        ValueError: the catalog does not carry ``tipo`` (lifecycle
            configuration drift; should never happen in a
            well-seeded env).
    """
    rows = client.execute_sql(_LOOKUP_TIPO_CONTRATO_SQL, [tipo])
    if not rows:
        raise ValueError(  # noqa: TRY003 -- operator-facing diagnostic
            f"catalogos_tipos_contrato no contiene el tipo {tipo!r}; "
            "re-ejecutar ensure_catalogs() o seed CATALOG-01"
        )
    return str(rows[0]["id"])


def exists_for_entity(
    client: SqlExecutor,
    *,
    tipo: str,
    entity_type: str,
    entity_id: str,
) -> bool:
    """Return True when a contrato for ``(tipo, entity)`` already exists.

    The legacy rule "un único contrato por tipo por entidad" is
    enforced here as a pre-flight check before the INSERT; the DB
    UNIQUE constraint catches the race that slips between the check
    and the write.
    """
    column = entity_column(entity_type)
    sql = _EXISTS_FOR_ENTITY_SQL_TEMPLATE.format(entity_column=column)
    rows = client.execute_sql(sql, [tipo, entity_id])
    return bool(rows)


def insert_contrato(
    client: SqlExecutor,
    *,
    tipo: str,
    entity_type: str,
    entity_id: str,
    numero_contrato: str,
    fecha: str | None = None,
) -> ContratoRecord:
    """Insert a new ``contratos`` row and return the persisted record.

    The caller MUST have validated ``tipo`` against
    :class:`~app.modules.contratos.domain.tipos_contrato.TipoContrato`
    and ``entity_type`` against :data:`EntityType`. The function
    looks up the FK against ``catalogos_tipos_contrato`` so the
    application layer does not need to know the catalog schema.

    Raises:
        ContratoConflictError: another contrato already exists for
            the same ``(tipo, entity)`` pair (UNIQUE violation
            translated to a domain-meaningful exception).
    """
    column = entity_column(entity_type)
    tipo_contrato_id = resolve_tipo_contrato_id(client, tipo=tipo)
    sql = _INSERT_CONTRATO_SQL_TEMPLATE.format(entity_column=column)
    params: list[Any] = [
        tipo_contrato_id,
        numero_contrato,
        fecha,
        entity_id,
    ]
    try:
        rows = client.execute_sql(sql, params)
    except BackendError as exc:
        if _is_duplicate(exc):
            raise ContratoConflictError(  # noqa: TRY003
                f"ya existe un contrato de tipo {tipo!r} para "
                f"la entidad {entity_type}={entity_id!r}"
            ) from exc
        raise
    if not rows:
        raise RuntimeError(  # noqa: TRY003 -- defensive; INSERT...RETURNING always returns a row
            "INSERT INTO contratos returned no rows; "
            "check the SQL template and the schema"
        )
    return _row_to_record(
        rows[0],
        tipo_codigo=tipo,
        entity_type=entity_type,
        entity_id=entity_id,
    )


def get_contrato_for_entity(
    client: SqlExecutor,
    *,
    tipo: str,
    entity_type: str,
    entity_id: str,
) -> ContratoRecord | None:
    """Return the persisted contrato for ``(tipo, entity)`` or ``None``.

    Used by the download route to confirm the contrato row exists
    before calling the storage port. Returns ``None`` when the
    operator asks for a contract that was never generated; the
    route translates that into a 404.
    """
    column = entity_column(entity_type)
    sql = _SELECT_CONTRATO_SQL_TEMPLATE.format(entity_column=column)
    rows = client.execute_sql(sql, [tipo, entity_id])
    if not rows:
        return None
    return _row_to_record(
        rows[0],
        tipo_codigo=tipo,
        entity_type=entity_type,
        entity_id=entity_id,
    )


# --- helpers --------------------------------------------------------------


def _is_duplicate(exc: BackendError) -> bool:
    """Detect the UNIQUE-FK violation on the ``contratos`` table.

    Mirrors the heuristic in
    :func:`app.modules.cesiones.service._is_unique_conflict` so the
    contratos module is a sibling, not a re-invention. The
    substring match on the table name keeps the heuristic
    scoped: a duplicate on a different table does NOT fire here.
    """
    body = str(exc.body).lower()
    return exc.status_code == 409 and (
        "contratos" in body
        or "duplicate" in body
        or "unique" in body
    )


def _row_to_record(
    row: dict[str, Any],
    *,
    tipo_codigo: str,
    entity_type: str,
    entity_id: str,
) -> ContratoRecord:
    """Build a :class:`ContratoRecord` from a SQL row + caller-known fields.

    The contratos table does not store ``entity_type``, ``entity_id``
    or ``tipo_codigo`` as columns (the entity is one of four FK
    columns, and the codigo lives in the catalog). The caller knows
    them already; this helper just stitches the dataclass together.
    """
    return ContratoRecord(
        id=str(row["id"]),
        tipo_contrato_id=str(row["tipo_contrato_id"]),
        tipo_codigo=tipo_codigo,
        entity_type=entity_type,
        entity_id=entity_id,
        numero_contrato=str(row["numero_contrato"]),
        fecha=str(row["fecha"]) if row.get("fecha") else None,
    )


__all__ = [
    "ContratoConflictError",
    "ContratoRecord",
    "EntityType",
    "entity_column",
    "exists_for_entity",
    "get_contrato_for_entity",
    "insert_contrato",
    "resolve_tipo_contrato_id",
]
