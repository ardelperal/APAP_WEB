"""DI helper for the migration web-reader port.

Stub placeholder: the concrete web_reader adapter was retired with the
InsForge runtime (issue #5). Until the migration package rewrite lands a
LocalBackend-backed :class:`LocalBackendWebReaderAdapter` (issue #8),
every method on the returned port raises
:class:`NotImplementedError` so the migration CLI fails loud per call.

Rule §2 (resources that own ``.close()`` use ``yield``): the
adapter is cheap to construct (no I/O) and holds no resources of
its own. The executor is owned by the caller's lifespan / test
fixture, not by this dependency.
"""

from __future__ import annotations

from app.core.data_access import SqlExecutor
from migration.ports.web_reader_port import WebReaderPort


def build_web_reader_port(executor: SqlExecutor) -> WebReaderPort:
    """Bind :class:`WebReaderPort` to the LocalBackend adapter.

    Returns the stub placeholder until a real ``LocalBackendWebReaderAdapter``
    lands (issue #8); the stub raises :class:`NotImplementedError` on every
    method so the migration CLI fails loud per call.
    """
    from migration.adapters.stubs.web_reader_stub import StubWebReaderPort

    del executor  # unused — kept for signature compatibility.
    return StubWebReaderPort()


__all__ = ["build_web_reader_port"]
