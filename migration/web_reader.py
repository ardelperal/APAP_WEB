"""Backward-compat shim for the migration web-reader module.

The web-reader concern has been migrated to a hexagonal slice
(``refactor/hexagonal-slice-migration-web``, AGENTS.md §31 + §18):

- :class:`WebTableSpec` lives in
  :mod:`migration.ports.web_reader_port` (the domain entity).
- :class:`WebReaderPort` lives in
  :mod:`migration.ports.web_reader_port` (the Protocol).
- :class:`WebReaderError` lives in
  :mod:`migration.ports.web_reader_port` (the port-level exception).
- The use case :func:`load_web_snapshot` lives in
  :mod:`migration.application.web_reader.load_web_snapshot`.
- The InsForge adapter
  (:class:`migration.adapters.insforge.web_reader_insforge_adapter.InsForgeWebReaderAdapter`)
  talks to InsForge via a
  :class:`~app.core.data_access.SqlExecutor`; the use case never
  imports :class:`~app.core.insforge.InsForgeClient` directly.

This module is the single re-export point that preserves the
pre-slice import surface so existing callers
(``migration.__init__``, ``tests/test_migration.py``, ...) keep
working without change. New code MUST import from the canonical
homes above; this shim exists only for backwards compatibility.

History (non-contract): the pre-slice module imported
:class:`~app.core.insforge.InsForgeClient` directly, which judgment-day
2026-08-04 flagged as CRITICAL because it violated §31 (domain
depends on Protocol, not on a concrete client). The hexagonal
slice restores the boundary.
"""

from __future__ import annotations

from migration.application.web_reader.load_web_snapshot import load_web_snapshot
from migration.ports.web_reader_port import WebReaderError, WebReaderPort, WebTableSpec

__all__ = [
    "WebReaderError",
    "WebReaderPort",
    "WebTableSpec",
    "load_web_snapshot",
]
