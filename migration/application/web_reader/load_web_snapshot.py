"""Use cases for reading the web backend during migration.

Thin orchestrators over :class:`migration.ports.web_reader_port.WebReaderPort`.
Each function depends only on the port (never on
:class:`~app.core.insforge.InsForgeClient` or any other transport),
so the body is a one-liner that can be tested against an in-memory
fake without HTTP or InsForge SDK involvement.
"""

from __future__ import annotations

from typing import Any

from migration.ports.web_reader_port import WebReaderPort, WebTableSpec


def load_web_snapshot(
    port: WebReaderPort,
    table_specs: list[WebTableSpec],
) -> dict[str, list[dict[str, Any]]]:
    """Read a snapshot of the listed tables from the web backend.

    Args:
        port: A :class:`WebReaderPort` implementation injected by
            the DI layer (:mod:`migration.di.web_reader_di`). In
            production the InsForge adapter wraps the per-request
            :class:`~app.core.data_access.SqlExecutor`; in tests a
            plain in-memory fake works.
        table_specs: tables to read, in the order they appear in
            the returned dict.

    Returns:
        Mapping ``{web_table_name: [row_dict, ...]}`` as produced
        by the port. An empty table maps to ``[]``.

    Raises:
        WebReaderError: propagated from the port when the adapter
            cannot satisfy the read. The transport-layer
            ``__cause__`` is preserved.
    """
    return port.load_web_snapshot(table_specs)


__all__ = ["load_web_snapshot"]
