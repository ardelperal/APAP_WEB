"""LocalBackend web-reader adapter (M6 of self-host-backend-coolify, issue #641).

The original ``migration/adapters/insforge/web_reader_insforge_adapter.py``
was renamed to ``migration/adapters/local_backend/web_reader_local_backend_adapter.py``
when the InsForge adapter was swapped for a LocalBackend-backed one. The
old file was deleted during the InsForge removal campaign; this stub
restores both the pure ``_build_web_select_sql`` helper (so the
``tests/migration/test_s608_identifier_guards.py`` regression suite
collects cleanly) and the ``LocalBackendWebReaderAdapter`` class (so
``tests/test_migration.py::TestWebReader`` can import the production
class under test).

The stub preserves the original function and class shapes (``SELECT
cols FROM tabla[ WHERE updated_at > 'iso-ts']`` for the SQL builder,
``load_web_snapshot`` that wraps transport errors in ``WebReaderError``)
and the S608 identifier defence (``migration.apply._safe_table``) so
the regression test assertions remain valid.
"""

from __future__ import annotations

from typing import Any

from app.core.data_access import SqlExecutor
from migration.ports.web_reader_port import WebReaderError, WebReaderPort, WebTableSpec


def _build_web_select_sql(spec: WebTableSpec) -> str:
    """Build the ``SELECT`` for one :class:`WebTableSpec`.

    Mirrors the pre-slice helper verbatim so the on-wire SQL stays
    bit-identical: ``SELECT cols FROM tabla[ WHERE updated_at >
    'iso-ts']``. The ``isoformat()`` timestamp is portable
    (PostgREST parses it without a timezone).

    Kept as a module-private pure function (no I/O) so unit tests
    can assert the exact query shape against a ``FakeLocalBackend``
    without spinning up transport.

    Import-local rationale: avoids a cycle with ``migration.apply``
    (same pattern as ``reverse_apply/io_helpers.py``).
    """
    from migration.apply import _safe_table

    # Defense in depth (issue #387): identifiers are validated even
    # though today they come from the mapping YAML. ``"*"`` is a
    # legitimate wildcard.
    table = _safe_table(spec.web_table)
    cols = ", ".join(c if c == "*" else _safe_table(c) for c in spec.columns)
    where = ""
    if spec.since:
        # ``since`` is a ``datetime``: ``isoformat()`` cannot inject.
        where = f" WHERE updated_at > '{spec.since.isoformat()}'"
    # noqa S608: table and columns validated against
    # ``^[A-Za-z_][A-Za-z0-9_]*$``; the only interpolated value is a
    # ``datetime.isoformat()``. No operand comes from request data
    # (``app/`` does not import ``migration/``).
    return f"SELECT {cols} FROM {table}{where}"  # noqa: S608


class LocalBackendWebReaderAdapter(WebReaderPort):
    """LocalBackend implementation of :class:`WebReaderPort`.

    Stateless and thread-safe: holds only the executor reference
    passed at construction time. The DI layer
    (:mod:`migration.di.web_reader_di`) owns the executor's
    lifecycle, not the adapter.

    Transport errors (any exception raised by ``execute_sql`` —
    :class:`~app.core.data_access.BackendError`,
    :class:`httpx.TimeoutException`, etc.) are wrapped in
    :class:`WebReaderError` so the use case catches a
    domain-level error without inspecting the envelope. The
    underlying exception is preserved as ``__cause__`` for the
    operator postmortem traceback.

    The :class:`WebReaderPort` base class makes the structural
    contract explicit: this class MUST satisfy every method declared
    on the Protocol (mypy enforces it; ruff also rejects the unused
    import when the Protocol is not used as a base class).
    """

    def __init__(self, executor: SqlExecutor) -> None:
        """Store the executor used for every web snapshot read.

        Args:
            executor: Any object that satisfies the
                :class:`~app.core.data_access.SqlExecutor` Protocol.
                In production this is the
                :class:`~app.core.local_backend.LocalPostgresExecutor` stored
                on the application lifespan state; in tests it can
                be an ``httpx.MockTransport``-backed fake or a
                plain in-memory stub.
        """
        self._executor = executor

    def load_web_snapshot(
        self,
        table_specs: list[WebTableSpec],
    ) -> dict[str, list[dict[str, Any]]]:
        """Read a snapshot of rows from the listed tables on LocalBackend.

        Iterates ``table_specs`` in order, issuing one ``SELECT``
        per spec and storing the rows under the spec's
        ``web_table`` key in the returned dict. An executor
        failure on any spec raises :class:`WebReaderError`
        (the underlying transport error is preserved via
        ``raise ... from``).
        """
        result: dict[str, list[dict[str, Any]]] = {}
        for spec in table_specs:
            sql = _build_web_select_sql(spec)
            try:
                rows = self._executor.execute_sql(sql)
            except Exception as exc:  # noqa: BLE001 — wrap transport-layer errors
                raise WebReaderError(
                    f"Web query failed for {spec.web_table!r}: {exc}"
                ) from exc
            result[spec.web_table] = rows
        return result


__all__ = ["LocalBackendWebReaderAdapter", "_build_web_select_sql"]
