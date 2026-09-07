"""DI helper for the migration web-reader port.

Constructs the per-run :class:`migration.ports.web_reader_port.WebReaderPort`
backed by the InsForge client. Use cases under
:mod:`migration.application.web_reader` depend only on the port —
this helper is the seam that hides the concrete
:class:`~app.core.insforge.LocalPostgresExecutor`.

Rule §2 (resources that own ``.close()`` use ``yield``): the
adapter is cheap to construct (no I/O) and holds no resources of
its own. The executor is owned by the caller's lifespan / test
fixture, not by this dependency.
"""

from __future__ import annotations

from app.core.data_access import SqlExecutor
from migration.adapters.insforge.web_reader_insforge_adapter import (
    InsForgeWebReaderAdapter,
)
from migration.ports.web_reader_port import WebReaderPort


def build_web_reader_port(executor: SqlExecutor) -> WebReaderPort:
    """Bind :class:`WebReaderPort` to the InsForge adapter.

    Args:
        executor: A :class:`~app.core.data_access.SqlExecutor`
            (the production :class:`~app.core.insforge.LocalPostgresExecutor`
            satisfies this structurally; tests pass a fake).

    Returns:
        The :class:`WebReaderPort` interface, not the concrete
        adapter — use cases should not need to import
        :class:`InsForgeWebReaderAdapter` directly.
    """
    return InsForgeWebReaderAdapter(executor)


__all__ = ["build_web_reader_port"]
