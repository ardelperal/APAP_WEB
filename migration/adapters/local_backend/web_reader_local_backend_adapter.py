"""LocalBackend web-reader adapter (M6 of self-host-backend-coolify, issue #641).

The original ``migration/adapters/insforge/web_reader_insforge_adapter.py``
was renamed to ``migration/adapters/local_backend/web_reader_local_backend_adapter.py``
when the InsForge adapter was swapped for a LocalBackend-backed one. The
old file was deleted during the InsForge removal campaign; this stub
restores the ``_build_web_select_sql`` symbol so the
``tests/migration/test_s608_identifier_guards.py`` regression suite
collects cleanly.

The stub preserves the original function shape (``SELECT cols FROM
tabla[ WHERE updated_at > 'iso-ts']``) and the S608 identifier
defense (``migration.apply._safe_table``) so the regression test
assertions remain valid.
"""

from __future__ import annotations

from migration.apply import _safe_table
from migration.ports.web_reader_port import WebTableSpec


def _build_web_select_sql(spec: WebTableSpec) -> str:
    """Build the ``SELECT`` for one :class:`WebTableSpec`.

    Mirrors the pre-slice helper verbatim so the on-wire SQL stays
    bit-identical: ``SELECT cols FROM tabla[ WHERE updated_at >
    'iso-ts']``. The ``isoformat()`` timestamp is portable
    (PostgREST parses it without a timezone).

    Kept as a module-private pure function (no I/O) so unit tests
    can assert the exact query shape against a stub executor
    without spinning up transport.

    Imports ``_safe_table`` locally to avoid a cycle with
    ``migration.apply`` (same pattern as
    ``reverse_apply/io_helpers.py``).
    """
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


__all__ = ["_build_web_select_sql"]
