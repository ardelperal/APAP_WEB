"""Lectura batched del .accdb legacy vía Dysflow (LIFECYCLE-03 / migration-01).

Este módulo produce el **snapshot legacy** que el diff engine consume
para calcular INSERTs/UPDATEs/DELETEs. El snapshot es un
``dict[str, list[dict]]`` indexado por nombre de tabla legacy
(``TbFichaAnimal``, ``TbVoluntariosParaAutorrellenables``, etc.).

**Estrategia de batching** (design §5):
    - Se leen las tablas en orden (secuencial, una a la vez).
    - Cada tabla se pagina en chunks de ``BATCH_SIZE = 100`` filas usando
      ``SELECT TOP n`` (Access no soporta ``LIMIT``).
    - El generator ``load_legacy_snapshot_batched`` produce tuplas
      ``(table_name, rows)`` por cada batch, permitiendo al consumer
      procesar sin cargar todo en memoria (v2). La versión 1 (esta)
      usa ``load_legacy_snapshot`` que materializa todo el snapshot en
      memoria — aceptable para ~5.000 filas × ~10 cols (≈ 60 MB,
      design §12).

**Desacople de Dysflow**:
    - La función privada ``_execute_legacy_query`` usa un callable
      inyectable (``_legacy_query_executor``) que los tests pueden
      setear con ``set_legacy_query_executor(...)``. Esto evita
      acoplar ``legacy_reader`` al MCP de Dysflow y permite tests
      deterministas sin abrir Access.
    - En producción, si no hay executor inyectado, se delega a
      ``execute_legacy_sql`` del módulo ``dysflow_client`` (stub en
      este slice; implementación real en PR 5/6).

**Atomicidad y errores**:
    - No se hace commit a la base (es solo lectura).
    - ``LegacyReaderError`` se levanta si Dysflow falla; el caller
      decide cómo continuar (regla #13474 v2: función de migración
      atómica → si falla la lectura, abortar antes de calcular diffs).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from app.core.migration.dysflow_client import execute_legacy_sql

# Tamaño del batch (design §5): 100 filas × ~10 cols × ~50 bytes ≈ 50 KB.
# Permite granularidad razonable para retry y encaja en memoria.
BATCH_SIZE = 100

# Tipo del executor inyectable: ``Callable[[str, str, int, int], list[dict]]``.
# Recibe ``(legacy_path, sql, offset, limit)`` — el ``offset`` es la
# clave del fix P1: thread el offset del paging loop al executor real
# (``dysflow_query_execute(..., offset=offset, limit=BATCH_SIZE)``,
# design §5). Sin esto, el paging retorna el mismo batch en cada
# iteración y el CLI se cuelga (review PR #95).
LegacyQueryExecutor = Callable[
    [str, str, int, int], list[dict[str, Any]]
]  # alias semántico (Callable subscriptable desde 3.9)


@dataclass(frozen=True, slots=True)
class TableSpec:
    """Especificación de una tabla legacy a leer.

    ``legacy_table`` es el nombre de la tabla en el .accdb (ej:
    ``TbFichaAnimal``). ``columns`` son las columnas a proyectar en el
    ``SELECT`` (no usar ``*`` — el diff engine solo necesita las
    columnas mapeadas en el YAML). ``where`` es un filtro SQL opcional
    (ej: ``"FDefuncion IS NOT NULL"`` para excluir filas activas en una
    sync de histórico).
    """

    legacy_table: str
    columns: tuple[str, ...]
    where: str | None = None


def load_legacy_snapshot_batched(
    legacy_path: str,
    table_specs: list[TableSpec],
) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """Lee del .accdb en batches de ``BATCH_SIZE`` filas vía Dysflow.

    Args:
        legacy_path: ruta absoluta al .accdb (protegido por contraseña).
        table_specs: lista de specs (``legacy_table``, ``columns``).

    Yields:
        Tuplas ``(legacy_table_name, [row_dict, ...])`` por cada batch.

    Raises:
        LegacyReaderError: si Dysflow falla (propaga cualquier error
            subyacente como ``LegacyReaderError`` para que el caller
            pueda distinguir errores de lectura de errores de diff).
    """
    for spec in table_specs:
        offset = 0
        while True:
            sql = _build_select_sql(spec, offset, BATCH_SIZE)
            try:
                rows = _execute_legacy_query(legacy_path, sql, offset, BATCH_SIZE)
            except LegacyReaderError:
                raise
            except Exception as exc:  # noqa: BLE001 — wrap unexpected errors
                raise LegacyReaderError(
                    f"Dysflow query failed for {spec.legacy_table!r}: {exc}"
                ) from exc
            if not rows:
                break
            yield (spec.legacy_table, rows)
            offset += BATCH_SIZE


def load_legacy_snapshot(
    legacy_path: str,
    table_specs: list[TableSpec],
) -> dict[str, list[dict[str, Any]]]:
    """Lee el .accdb completo y devuelve un ``dict`` ``{table_name: [rows]}``.

    Convenience wrapper sobre ``load_legacy_snapshot_batched`` que
    materializa todo el snapshot en memoria. Para v1 (~5.000 filas)
    es aceptable; v2 debería procesar on-stream.

    Args:
        legacy_path: ruta absoluta al .accdb.
        table_specs: lista de specs a leer.

    Returns:
        Dict ``{legacy_table_name: [row_dict, ...]}`` con todas las
        filas de todas las tablas pedidas.
    """
    result: dict[str, list[dict[str, Any]]] = {}
    for table_name, rows in load_legacy_snapshot_batched(legacy_path, table_specs):
        result.setdefault(table_name, []).extend(rows)
    return result


# --- Internals inyectables para tests -------------------------------------


# Callable ``[[str, str, int, int], list[dict]]`` inyectable. ``None``
# significa "usar el cliente Dysflow real" (que en este slice es un stub).
_legacy_query_executor: LegacyQueryExecutor | None = None


def _execute_legacy_query(
    legacy_path: str,
    sql: str,
    offset: int,
    limit: int,
) -> list[dict[str, Any]]:
    """Ejecuta SQL contra el .accdb vía Dysflow (con executor inyectable).

    Usa el callable inyectado por ``set_legacy_query_executor`` si está
    seteado (path usado en tests). Si no, delega a
    ``execute_legacy_sql`` del módulo ``dysflow_client`` (en este slice
    es un stub que levanta ``NotImplementedError``; la implementación
    real con ``dysflow_query_execute`` llega en PR 5/6).

    Args:
        legacy_path: ruta absoluta al .accdb legacy.
        sql: query Access SQL (usa ``TOP n``).
        offset: número de filas a saltar (paginación) — clave del fix
            P1 (review PR #95): sin pasar el offset, el executor real
            retornaría el mismo batch en cada iteración.
        limit: máximo de filas a retornar (``BATCH_SIZE`` típico).
    """
    if _legacy_query_executor is not None:
        return _legacy_query_executor(legacy_path, sql, offset, limit)
    return execute_legacy_sql(legacy_path, sql, offset, limit)


def set_legacy_query_executor(executor: LegacyQueryExecutor | None) -> None:
    """Inyecta un callable ``(legacy_path, sql, offset, limit) -> list[dict]`` para tests.

    Pasar ``None`` resetea al estado por defecto (usar Dysflow real).
    Esta función existe para evitar acoplar ``legacy_reader`` al MCP
    de Dysflow: los tests deterministas pueden setear un mock que
    devuelve filas hardcoded, sin necesidad de abrir Access.
    """
    global _legacy_query_executor
    _legacy_query_executor = executor


def _build_select_sql(spec: TableSpec, offset: int, limit: int) -> str:
    """Construye un ``SELECT TOP n`` compatible con Access.

    Access NO soporta ``LIMIT`` — usamos ``TOP n``. El ``offset`` NO se
    embebe en el SQL (Access requiere subqueries ``WHERE key NOT IN
    (SELECT TOP offset ...)`` para OFFSET, que depende del key column
    — algo que el executor concreto, no este helper, conoce). El
    ``offset`` se pasa como parámetro separado al executor
    (``dysflow_query_execute(..., offset=offset, limit=BATCH_SIZE)``,
    design §5), que es responsable de aplicar la paginación en el
    dialecto correcto (Access, ODBC directo, etc.).

    Args:
        spec: spec de la tabla (tabla + columnas + where opcional).
        offset: hook para paginación; se pasa al executor, no al SQL.
            El caller (``load_legacy_snapshot_batched``) lo incrementa
            en ``BATCH_SIZE`` por iteración.
        limit: número de filas a traer (``BATCH_SIZE`` por default),
            embebido como ``TOP n`` en el SQL.

    Returns:
        SQL formateado como string (sin punto y coma final).
    """
    cols = ", ".join(spec.columns)
    where = f" WHERE {spec.where}" if spec.where else ""
    # Access requiere ``TOP n`` justo después de ``SELECT``. ``n`` debe
    # ser un literal entero (no se puede parametrizar).
    return f"SELECT TOP {limit} {cols} FROM {spec.legacy_table}{where}"


class LegacyReaderError(Exception):
    """Error al leer del legacy.

    Hereda de ``Exception`` (no de ``MigrationError``) para no crear
    ciclos de import (``reporting.py`` no depende de ``legacy_reader``).
    El applier / CLI lo captura y lo reporta al usuario con exit code 5
    (design §1.5: I/O error en legacy → código 5).
    """
