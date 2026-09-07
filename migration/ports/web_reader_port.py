"""Hexagonal port for reading from the web (LocalBackend) backend during migration.

Defines the abstract surface that the migration use cases depend on
when they need to fetch rows from the web backend. Adapters under
:mod:`migration.adapters.local_backend` implement this Protocol; tests
substitute in-memory fakes that satisfy it structurally.

Hexagonal taxonomy (mirrors :mod:`app.core.ports.catalogos_port`):

- **Domain**      (:class:`WebTableSpec` here)          — input shape.
- **Port**        (this module)                          — abstract surface.
- **Application** (:mod:`migration.application.web_reader`) — use case.
- **Adapter**     (:mod:`migration.adapters.local_backend.web_reader_local_backend_adapter`)
                                                       — LocalBackend impl.
- **DI**          (:mod:`migration.di.web_reader_di`)   — wiring.

Rule §31 (domain services depend on Protocol abstractions): every
method here takes no concrete backend client; the adapter chooses its
own transport. Rule §22 (SQL/service separation): the SQL lives in the
adapter, not in the port.

Why this port is narrower than the apply layer's ``_LocalBackendLike``
==============================================================================

``_LocalBackendLike`` (in :mod:`migration.apply`) declares
``execute_sql`` + ``get_bucket`` + ``ensure_bucket`` because
``apply_legacy_to_web`` is a write pipeline that bootstraps the
shadow table and the private photo bucket before any per-row INSERT.

``WebReaderPort`` is intentionally narrower — it only declares the
read surface used by reconciliation. The two contracts are not
interchangeable: a caller that needs bucket bootstrap cannot use a
``WebReaderPort``. The slice that ports ``apply_legacy_to_web`` to a
named Protocol will introduce a separate ``WebWriterPort`` (or
``WebSyncPort``) carrying the full write+bootstrap surface; that
slice is intentionally NOT in this PR's scope.

Catching :class:`WebReaderError`
=================================

Adapters raise :class:`WebReaderError` on transport failure so the
caller sees a domain-level exception (not the raw transport shape).
The exception deliberately inherits from ``Exception`` rather than
:class:`~app.core.data_access.DataAccessError` to avoid pulling the
data-access module into this package's import graph and to mirror
``LegacyReaderError``'s precedent (the legacy reader predates the
Protocol-level exception hierarchy).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class WebTableSpec:
    """Specification of a web table to read during migration.

    ``web_table`` is the table name on the LocalBackend side
    (``animales``, ``voluntarios``, ...). ``columns`` are the
    columns to project in the ``SELECT``. ``since`` is the
    incremental-sync cursor: when set, the SQL includes
    ``WHERE updated_at > since`` so only rows modified after the
    last sync come back.

    In full sync (``since is None``) the adapter reads the entire
    table.
    """

    web_table: str
    columns: tuple[str, ...]
    since: datetime | None = None


class WebReaderPort(Protocol):
    """Abstract surface for reading a web-side row snapshot.

    Implementations issue one ``SELECT`` per :class:`WebTableSpec`
    and return a mapping ``{web_table_name: [row_dict, ...]}``.
    An empty table maps to ``[]`` (never ``None``) so callers can
    iterate uniformly.

    Implementations:

    - :class:`migration.adapters.local_backend.web_reader_local_backend_adapter.LocalBackendWebReaderAdapter`
      — production adapter, talks to LocalBackend via
      :class:`~app.core.data_access.SqlExecutor`.
    - Test fakes (in ``tests/``) — in-memory list-backed fakes for
      unit tests on the application layer.
    """

    def load_web_snapshot(
        self,
        table_specs: list[WebTableSpec],
    ) -> dict[str, list[dict[str, Any]]]:
        """Load a snapshot of rows from the listed tables on the web backend.

        Args:
            table_specs: ordered list of tables to read; the
                ``web_table`` attribute of each entry is the
                snapshot's key in the returned dict.

        Returns:
            Mapping ``{web_table_name: [row_dict, ...]}``. An
            empty table maps to ``[]`` (never ``None``) so callers
            can iterate uniformly without a special-case.

        Raises:
            WebReaderError: on transport failure (network, timeout,
                5xx, malformed envelope). The underlying transport
                error is preserved as ``__cause__`` for postmortem
                tracebacks.
        """
        ...


class WebReaderError(Exception):
    """Raised when the web read port cannot satisfy a request.

    Mirrors :class:`migration.legacy_reader.LegacyReaderError`'s
    precedent: inherits from bare ``Exception`` so it does not pull
    the Protocol-level :class:`~app.core.data_access.DataAccessError`
    into this package's import graph. Adapters wrap transport
    failures (e.g. :class:`~app.core.data_access.BackendError`) in
    this exception so the use case catches a domain-level error
    without inspecting the envelope shape.

    The ``__cause__`` chain preserves the original transport
    exception for operators reading the traceback.
    """


__all__ = ["WebReaderError", "WebReaderPort", "WebTableSpec"]
