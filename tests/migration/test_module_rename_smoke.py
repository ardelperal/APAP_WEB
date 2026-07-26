"""Module-path smoke test for issue #216 (architectural drift rename).

The rename ``migration/dysflow_client.py`` →
``migration/legacy_access_client.py`` must leave exactly one resolvable
module under ``migration`` for the pyodbc-backed legacy executor. A
regression that:

- leaves the old ``migration.dysflow_client`` module importable, or
- breaks the new ``migration.legacy_access_client`` import, or
- leaves either path empty,

silently breaks the apply / reverse-apply seams. This smoke test pins
the contract at the test level so a future regression in the rename
surfaces as a focused failure (Hard Rule 6 — refactor safety).

Hard Rules honoured (web-tdd-philosophy):

- Rule 1 (fixture gate): no fixtures; assertions only.
- Rule 2 (DI): the rename is a layout change, not a behavior change,
  so no DI surface is touched here.
- Rule 4 (no humo): assertions pin the resolvable module, not
  "no error".
- Rule 6 (refactor safety): this test is the one that guarantees the
  rename stayed a rename — it asserts the new path resolves and the
  old path no longer does.

The test lives under ``tests/migration/`` because it concerns the
``migration`` package surface; co-locating with
``test_runtime_boundary.py`` keeps the rename-related tests grouped.
"""

from __future__ import annotations

import importlib
import importlib.util


def test_legacy_access_client_module_is_importable() -> None:
    """``migration.legacy_access_client`` resolves via the standard importlib.

    The renamed module is the canonical seam-and-callers entry point
    for the legacy ``.accdb`` executor; the test asserts the package
    layout delivers the module at that path.
    """
    module = importlib.import_module("migration.legacy_access_client")
    assert module.__file__ is not None
    assert module.__file__.endswith("legacy_access_client.py"), (
        f"migration.legacy_access_client.__file__ is {module.__file__!r}; "
        f"expected a path ending in legacy_access_client.py"
    )


def test_legacy_access_client_exposes_expected_public_surface() -> None:
    """The renamed module keeps the same public symbols the seams consume.

    ``migration.legacy_reader`` and ``migration.apply`` import
    ``execute_legacy_sql`` / ``execute_legacy_write`` and read the
    typed error ``LegacyWriteRowcountUnknownError``; losing any of
    these would break the apply / reverse-apply paths.
    """
    module = importlib.import_module("migration.legacy_access_client")

    assert hasattr(module, "execute_legacy_sql"), (
        "migration.legacy_access_client.execute_legacy_sql must exist "
        "(consumed by migration.legacy_reader._execute_legacy_query)"
    )
    assert hasattr(module, "execute_legacy_write"), (
        "migration.legacy_access_client.execute_legacy_write must exist "
        "(consumed by migration.legacy_reader._execute_legacy_write)"
    )
    assert hasattr(module, "LegacyWriteRowcountUnknownError"), (
        "migration.legacy_access_client.LegacyWriteRowcountUnknownError "
        "must exist (raised by execute_legacy_write on -1 rowcount)"
    )
    assert hasattr(module, "DEFAULT_QUERY_TIMEOUT_SECONDS"), (
        "migration.legacy_access_client.DEFAULT_QUERY_TIMEOUT_SECONDS "
        "must exist (operator-visible pyodbc connect timeout contract)"
    )


def test_old_dysflow_client_module_path_no_longer_resolves() -> None:
    """``migration.dysflow_client`` raises ``ModuleNotFoundError``.

    The issue acceptance is ``grep -r dysflow_client migration/`` → 0
    hits AND the import path must also fail. A back-compat shim was
    intentionally rejected (see issue #216 design notes) so the
    old name is gone in production code paths; this test pins the
    layout-level contract.
    """
    spec = importlib.util.find_spec("migration.dysflow_client")
    assert spec is None, (
        "migration.dysflow_client is still resolvable "
        f"(spec={spec!r}); the rename in issue #216 requires this "
        "module to be removed. If a back-compat shim is added later, "
        "this test must be updated alongside it."
    )


__all__ = [
    "test_legacy_access_client_module_is_importable",
    "test_legacy_access_client_exposes_expected_public_surface",
    "test_old_dysflow_client_module_path_no_longer_resolves",
]
