"""InsForge adapter implementing :class:`WebReaderPort`.

The adapter is the seam where the SQL string for ``load_web_snapshot``
is constructed and the executor round-trip happens. Use cases under
:mod:`migration.application.web_reader` are agnostic to which
backend backs the port; tests swap this adapter for an in-memory
fake.

Rule §22 (SQL/service separation): the SQL strings and the
``primary_key`` injection live here, not in the port or the use
case. The pure ``_build_web_select_sql`` helper is module-private so
tests can assert the exact query shape without spinning up transport.

Rule §31 (domain depends on Protocol): the constructor takes a
:class:`~app.core.data_access.SqlExecutor`, not an
:class:`~app.core.insforge.LocalPostgresExecutor`. The
:class:`~app.core.insforge.LocalPostgresExecutor` happens to satisfy the
Protocol structurally (it has ``execute_sql(query, params)``
returning ``list[dict]``), so the DI helper can pass either without
an explicit cast — no InsForge import leaks into the application
layer.
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
    can assert the exact query shape against a ``FakeInsForge``
    without spinning up transport.
    """
    # Import local: evita un ciclo con ``migration.apply``. Mismo patrón
    # que ``reverse_apply/io_helpers.py``.
    from migration.apply import _safe_table

    # Defensa en profundidad (issue #387): los identificadores se validan
    # aunque hoy vengan del YAML de mapeo. ``"*"`` es comodín legítimo.
    table = _safe_table(spec.web_table)
    cols = ", ".join(c if c == "*" else _safe_table(c) for c in spec.columns)
    where = ""
    if spec.since:
        # ``since`` es ``datetime``: ``isoformat()`` no puede inyectar.
        where = f" WHERE updated_at > '{spec.since.isoformat()}'"
    # noqa S608: tabla y columnas validadas contra
    # ``^[A-Za-z_][A-Za-z0-9_]*$``; el único valor interpolado es un
    # ``datetime.isoformat()``. Ningún operando viene de datos de request
    # (``app/`` no importa ``migration/``).
    return f"SELECT {cols} FROM {table}{where}"  # noqa: S608


class InsForgeWebReaderAdapter(WebReaderPort):
    """InsForge implementation of :class:`WebReaderPort`.

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
                :class:`~app.core.insforge.LocalPostgresExecutor` stored
                on the application lifespan state; in tests it can
                be an ``httpx.MockTransport``-backed fake or a
                plain in-memory stub.
        """
        self._executor = executor

    def load_web_snapshot(
        self,
        table_specs: list[WebTableSpec],
    ) -> dict[str, list[dict[str, Any]]]:
        """Read a snapshot of rows from the listed tables on InsForge.

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


__all__ = ["InsForgeWebReaderAdapter"]
