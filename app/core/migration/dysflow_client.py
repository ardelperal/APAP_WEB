"""Cliente Dysflow para migración legacy (LIFECYCLE-03 / migration-01).

Este módulo aísla la dependencia con Dysflow MCP detrás de una función
``execute_legacy_sql(path, sql) -> list[dict]`` para que ``legacy_reader``
no importe el cliente MCP directamente. La implementación real (que
envuelve ``dysflow_query_execute`` con el proyecto + access path) llega
en PR 5/6 cuando se conecte a la MCP; por ahora solo provee el stub
para que ``legacy_reader`` compile y los tests puedan inyectar un
ejecutor alternativo.

Convenciones:
    - ``path`` es la ruta absoluta al .accdb legacy (protegido por
      contraseña — la password viene del env ``DYSFLOW_ACCESS_PASSWORD``,
      regla #13518: NO hardcodearla).
    - ``sql`` es la query Access SQL (usa ``TOP n`` en lugar de ``LIMIT``).
    - Retorna ``list[dict[str, Any]]`` con las filas resultantes. Una
      lista vacía significa "sin resultados" (o end-of-batch en paging).
"""

from __future__ import annotations

from typing import Any


def execute_legacy_sql(path: str, sql: str) -> list[dict[str, Any]]:
    """Ejecuta ``sql`` contra el .accdb en ``path`` y retorna las filas.

    Args:
        path: ruta absoluta al .accdb legacy.
        sql: query Access SQL (usa ``TOP n``, no ``LIMIT``).

    Returns:
        Lista de filas como ``dict``. Lista vacía si no hay resultados.

    Raises:
        NotImplementedError: hasta que se conecte Dysflow en PR 5/6.
    """
    raise NotImplementedError(
        "execute_legacy_sql will be implemented when Dysflow MCP is wired "
        "in a later slice (PR 5/6). For now, legacy_reader must inject a "
        "callable via set_legacy_query_executor(...) before calling "
        "load_legacy_snapshot(...)."
    )


__all__ = ["execute_legacy_sql"]
