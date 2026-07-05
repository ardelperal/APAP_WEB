"""Test package for the ``migration`` ETL tooling.

Issue #168 — ACCDB <-> InsForge sync end-to-end (apply + status CLI,
shadow-state bootstrap, atomic apply with advisory lock + audit log).

The tests live here (rather than mixed into ``tests/test_migration.py``)
because the apply slice ships its own contract — apply result counts,
audit-log emission, lock acquisition, idempotency — and bundling it with
the PR-1/2/3/4/5 tests would force the reviewer to skim ~2000 lines to
find the new atoms.

This ``__init__`` is intentionally empty: pytest auto-discovers the
package, and we don't want any cross-test imports.
"""
