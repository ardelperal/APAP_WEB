"""LocalBackend adapter implementing :class:`CatalogosPort` for catalog reads.

The adapter is the seam where SQL strings, parameter shaping, and the
row-to-entity mapping live. Tests swap the adapter for an in-memory
fake by implementing :class:`CatalogosPort` directly; the use cases
in :mod:`app.core.application.catalogos` are agnostic to which one
backs the port.

Rule §22 (SQL/service separation): the SQL string is constructed here
in the adapter, not interpolated inside validation/orchestration. The
row-to-entity mapping is a list comprehension over the raw rows; no
column-name aliases, no schema-shaping, no transport quirks — the
LocalBackend envelope unwrapping is owned by :class:`LocalPostgresExecutor` in
``app/core/local_backend.py``, and the adapter sees the canonical
``list[dict[str, Any]]`` shape.

Rule §31 (domain depends on Protocol): the adapter constructor takes
a :class:`SqlExecutor`, not an :class:`LocalPostgresExecutor`. The
:class:`LocalPostgresExecutor` happens to satisfy the Protocol structurally
(it has ``execute_sql(query, params)`` returning ``list[dict]``), so a
DI helper can pass either without an explicit cast.
"""



from __future__ import annotations

from typing import Any

from app.core.catalogos.motivo import Motivo
from app.core.catalogos.origen import Origen
from app.core.catalogos.periodicidad import Periodicidad
from app.core.catalogos.prueba import Prueba
from app.core.catalogos.tipo_contrato import TipoContrato
from app.core.data_access import SqlExecutor
from app.core.ports.catalogos_port import CatalogosPort

# SQL constants are module-level so tests can assert the exact query
# (the existing ``tests/test_catalogs.py`` pins the query shape; the
# new tests under ``tests/test_local_backend_catalogos_adapter.py`` pin the
# same shape against this adapter).

LIST_ORIGENES_SQL = """
SELECT id, codigo, nombre, descripcion, activo, orden
FROM catalogos_origenes
WHERE activo = true
ORDER BY orden NULLS LAST, codigo
"""

LIST_MOTIVOS_SQL = """
SELECT id, codigo, nombre, especie, activo, orden
FROM catalogos_motivos
WHERE activo = true
ORDER BY orden NULLS LAST, especie, codigo
"""

LIST_PRUEBAS_SQL = """
SELECT id, codigo, nombre, especie, observaciones, activo, orden
FROM catalogos_pruebas
WHERE activo = true
ORDER BY orden NULLS LAST, codigo
"""

LIST_PERIODICIDAD_SQL = """
SELECT id, codigo, nombre, especie, periodicidad_meses, activo, orden
FROM catalogos_periodicidad
WHERE activo = true
ORDER BY orden NULLS LAST, especie NULLS LAST, codigo
"""

LIST_TIPOS_CONTRATO_SQL = """
SELECT id, codigo, nombre, iniciales, descripcion, tabla_legacy, campo_legacy, activo, orden
FROM catalogos_tipos_contrato
WHERE activo = true
ORDER BY orden NULLS LAST, codigo
"""


def _coerce_bool(value: Any) -> bool:
    """Coerce a row value to ``bool`` for the catalog ``activo`` column.

    LocalBackend returns the boolean column as a JSON bool (``True``/``False``),
    but a future raw-SQL tool or a different transport may return a string
    (``"true"``/``"false"``) or an integer (``1``/``0``). This helper is the
    one place that owns the coercion contract; tests pin ``True``/``False``
    as the canonical shape.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "t", "1", "yes", "y"}
    return bool(value)


def _coerce_int_or_none(value: Any) -> int | None:
    """Coerce a row value to ``int`` or ``None`` for nullable integer columns.

    Used for ``orden`` (all 5 catalogs) and ``periodicidad_meses``. The
    SQL declares ``NULL`` as a valid value; the helper returns ``None``
    for ``None`` so the domain entity's ``int | None`` field is
    honoured.
    """
    if value is None:
        return None
    return int(value)


class LocalBackendCatalogosAdapter(CatalogosPort):
    """Implements :class:`CatalogosPort` by querying LocalBackend via ``SqlExecutor``.

    The adapter is stateless and thread-safe. It holds a single
    :class:`SqlExecutor` reference passed at construction time; the
    DI layer (``app/core/di/catalogos_di.py``) owns the executor's
    lifecycle, not the adapter.

    The :class:`CatalogosPort` base class makes the structural
    contract explicit: this class MUST satisfy every method declared
    on the Protocol (mypy enforces it; ruff also reject the unused
    import when the Protocol is not used as a base class).
    """

    def __init__(self, executor: SqlExecutor) -> None:
        """Store the executor used for every catalog read.

        Args:
            executor: Any object that satisfies the
                :class:`app.core.data_access.SqlExecutor` Protocol.
                In production this is the :class:`LocalPostgresExecutor`
                stored on ``app.state.local_backend_client``; in tests it
                can be an ``httpx.MockTransport``-backed fake.
        """
        self._executor = executor

    # --- read paths -------------------------------------------------

    def list_origenes(self) -> list[Origen]:
        """Return all active origenes ordered by ``orden`` then ``codigo``.

        Contract: matches the legacy SQL constant
        ``LIST_CATALOGOS_ORIGENES_SQL`` in ``app/core/catalogs.py``.
        """
        rows = self._executor.execute_sql(LIST_ORIGENES_SQL, [])
        return [
            Origen(
                id=str(row["id"]),
                codigo=str(row["codigo"]),
                nombre=str(row["nombre"]),
                descripcion=row.get("descripcion"),
                activo=_coerce_bool(row.get("activo")),
                orden=_coerce_int_or_none(row.get("orden")),
            )
            for row in rows
        ]

    def list_motivos(self) -> list[Motivo]:
        """Return all active motivos grouped by ``especie``.

        Contract: matches the legacy SQL constant
        ``LIST_CATALOGOS_MOTIVOS_SQL`` in ``app/core/catalogs.py``.
        ``especie`` is NOT NULL in the schema and the seed; it is
        coerced to ``str`` to defend against a NULL sneaking through
        a future schema drift.
        """
        rows = self._executor.execute_sql(LIST_MOTIVOS_SQL, [])
        return [
            Motivo(
                id=str(row["id"]),
                codigo=str(row["codigo"]),
                nombre=str(row["nombre"]),
                especie=str(row["especie"]),
                activo=_coerce_bool(row.get("activo")),
                orden=_coerce_int_or_none(row.get("orden")),
            )
            for row in rows
        ]

    def list_pruebas(self) -> list[Prueba]:
        """Return all active pruebas ordered by ``orden`` then ``codigo``.

        Contract: matches the legacy SQL constant
        ``LIST_CATALOGOS_PRUEBAS_SQL`` in ``app/core/catalogs.py``.
        ``especie`` is lowercase in the legacy (``'canina'``,
        ``'felina'``, ``'ambos'``); the row is preserved verbatim.
        """
        rows = self._executor.execute_sql(LIST_PRUEBAS_SQL, [])
        return [
            Prueba(
                id=str(row["id"]),
                codigo=str(row["codigo"]),
                nombre=str(row["nombre"]),
                especie=str(row["especie"]),
                observaciones=row.get("observaciones"),
                activo=_coerce_bool(row.get("activo")),
                orden=_coerce_int_or_none(row.get("orden")),
            )
            for row in rows
        ]

    def list_periodicidad(self) -> list[Periodicidad]:
        """Return all active periodicidades ordered by ``orden`` then ``codigo``.

        Contract: matches the legacy SQL constant
        ``LIST_CATALOGOS_PERIODICIDAD_SQL`` in ``app/core/catalogs.py``.
        ``especie`` may be ``NULL`` (for one-shot rules) and
        ``periodicidad_meses`` may be ``NULL`` (for one-shot
        operations like Esterilización). Both nullable columns are
        surfaced as ``None`` on the entity.
        """
        rows = self._executor.execute_sql(LIST_PERIODICIDAD_SQL, [])
        return [
            Periodicidad(
                id=str(row["id"]),
                codigo=str(row["codigo"]),
                nombre=str(row["nombre"]),
                especie=row.get("especie"),
                periodicidad_meses=_coerce_int_or_none(row.get("periodicidad_meses")),
                activo=_coerce_bool(row.get("activo")),
                orden=_coerce_int_or_none(row.get("orden")),
            )
            for row in rows
        ]

    def list_tipos_contrato(self) -> list[TipoContrato]:
        """Return all active contract-template types for Fase 7.

        Contract: matches the legacy SQL constant
        ``LIST_CATALOGOS_TIPOS_CONTRATO_SQL`` in ``app/core/catalogs.py``.
        ``iniciales``, ``descripcion``, ``tabla_legacy``, and
        ``campo_legacy`` are nullable; ``None`` propagates through.
        """
        rows = self._executor.execute_sql(LIST_TIPOS_CONTRATO_SQL, [])
        return [
            TipoContrato(
                id=str(row["id"]),
                codigo=str(row["codigo"]),
                nombre=str(row["nombre"]),
                iniciales=row.get("iniciales"),
                descripcion=row.get("descripcion"),
                tabla_legacy=row.get("tabla_legacy"),
                campo_legacy=row.get("campo_legacy"),
                activo=_coerce_bool(row.get("activo")),
                orden=_coerce_int_or_none(row.get("orden")),
            )
            for row in rows
        ]


__all__ = [
    "LocalBackendCatalogosAdapter",
    "LIST_MOTIVOS_SQL",
    "LIST_ORIGENES_SQL",
    "LIST_PERIODICIDAD_SQL",
    "LIST_PRUEBAS_SQL",
    "LIST_TIPOS_CONTRATO_SQL",
]
