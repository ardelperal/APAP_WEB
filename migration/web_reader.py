"""Lectura del snapshot web vía InsForgeClient (LIFECYCLE-03 / migration-01).

Este módulo produce el **snapshot web** que el diff engine consume. El
snapshot es un ``dict[str, list[dict]]`` indexado por nombre de tabla
web (``animales``, ``voluntarios``, ``entradas``, ``acogidas``,
``adopciones``).

**Estrategia de I/O** (design §1.4):
    - Una sola query ``SELECT ... FROM tabla[ WHERE updated_at > since]``
      por tabla vía ``InsForgeClient.execute_sql``.
    - En full sync no se pasa ``since`` → trae toda la tabla.
    - En incremental sync (``--since``) se filtra por ``updated_at`` para
      reducir el ancho de banda (PostgREST soporta el predicado).
    - No usamos batching en el lado web porque el result set se espera
      chico en incremental (< 200 filas) y manejable en full sync
      (~5.000 filas × ~10 cols ≈ 60 MB, design §12).

**Compatibilidad con tests**:
    - ``InsForgeClient`` acepta un ``httpx.BaseTransport`` inyectable
      (``httpx.MockTransport``), por lo que los tests no tocan la red.
      Ver ``tests/test_insforge.py`` para el patrón.

**Atomicidad**:
    - Este módulo es SOLO LECTURA. No hay transacción aquí — el
      ``BEGIN/COMMIT/ROLLBACK`` del lado web es responsabilidad del
      applier (PR 8).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.insforge import InsForgeClient


@dataclass(frozen=True, slots=True)
class WebTableSpec:
    """Especificación de una tabla web a leer.

    ``web_table`` es el nombre de la tabla en el web (``animales``,
    ``voluntarios``, etc.). ``columns`` son las columnas a proyectar en
    el ``SELECT``. ``since`` es el cursor de incremental sync: si está
    seteado, el SQL incluye ``WHERE updated_at > since`` para traer
    solo las filas modificadas desde el último sync.

    En full sync (``since is None``) se trae toda la tabla.
    """

    web_table: str
    columns: tuple[str, ...]
    since: datetime | None = None


def load_web_snapshot(
    client: InsForgeClient,
    table_specs: list[WebTableSpec],
) -> dict[str, list[dict[str, Any]]]:
    """Lee del web vía ``InsForgeClient`` y devuelve ``dict`` ``{table: [rows]}``.

    Args:
        client: cliente InsForge (privado o de servicio).
        table_specs: specs de tablas a leer.

    Returns:
        Dict ``{web_table_name: [row_dict, ...]}``. Una tabla vacía
        retorna ``[]`` (no ``None``) para uniformidad con el caller.

    Raises:
        WebReaderError: si la query falla (red, timeout, 5xx). El
            ``InsForgeError`` subyacente se propaga como ``__cause__``.
    """
    result: dict[str, list[dict[str, Any]]] = {}
    for spec in table_specs:
        sql = _build_web_select_sql(spec)
        try:
            rows = client.execute_sql(sql)
        except Exception as exc:  # noqa: BLE001 — wrap unexpected errors
            raise WebReaderError(f"Web query failed for {spec.web_table!r}: {exc}") from exc
        result[spec.web_table] = rows
    return result


def _build_web_select_sql(spec: WebTableSpec) -> str:
    """Construye un ``SELECT`` para PostgreSQL vía PostgREST.

    A diferencia del legacy, PostgREST/PostgreSQL usa sintaxis estándar:
    ``SELECT cols FROM tabla WHERE updated_at > 'iso-ts'``. No usamos
    ``TOP n`` ni ``LIMIT`` — la idea es traer TODO lo que cambió desde
    ``since`` (o toda la tabla si ``since is None``).
    """
    cols = ", ".join(spec.columns)
    where = ""
    if spec.since:
        # ISO-8601 con ``T`` como separador (PostgREST parsea sin zona,
        # pero usamos ``isoformat()`` que es portable).
        where = f" WHERE updated_at > '{spec.since.isoformat()}'"
    return f"SELECT {cols} FROM {spec.web_table}{where}"


class WebReaderError(Exception):
    """Error al leer del web.

    Mismo criterio que ``LegacyReaderError``: hereda de ``Exception``
    para no crear ciclos de import con ``reporting``. El applier lo
    captura y reporta al usuario (exit code 1: error recuperable
    agotado, design §1.5).
    """
