"""Strict TDD atoms for issue #217 — preserve_advances rename.

Issue: ``dni_collision_counter`` is incremented per preserve row
processed, not per actual collision. The 100-row no-edit round-trip
reports ``dni_collisions=100`` even when no rows diverge, which
misrepresents the metric semantics.

Chosen fix (option b — RENAME): rename the operator-facing dict key
from ``dni_collisions`` to ``preserve_advances`` so the metric name
matches what it actually counts (advances of the preserve-column
shadow state, one per preserve column with a web-side value).

This file contains the new parametrized atom that asserts the rename
contract: post-rename, a 100-row no-edit round-trip produces
``preserve_advances == 100`` AND ``dni_collisions`` is absent from
the collisions dict.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from migration.dni_collision import DniCollisionCounter
from migration.reporting import MigrationReport

# --- parametrized atom ------------------------------------------------------


def test_100_row_no_edit_round_trip_reports_preserve_advances(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """100-row no-edit round-trip reports ``preserve_advances == 100``.

    Atom for issue #217 (option b — RENAME).

    A 100-row round-trip where every row's mapped columns are
    equal between web and legacy (no actual collision) exercises the
    reverse applier's ``_advance_preserve_shadow_state`` path once
    per row (the reverse applier calls it unconditionally on every
    row, not just divergent ones). After the rename, the operator
    metric must read:

    - ``collisions["voluntario"]["preserve_advances"] == 100``
    - ``"dni_collisions" not in collisions["voluntario"]``

    The old key ``dni_collisions`` must be absent because it would
    be semantically misleading (there were zero actual collisions).
    """
    from migration import legacy_reader
    from migration.apply import apply_legacy_to_web
    from migration.apply_reverse import apply_web_to_legacy
    from tests.migration.conftest import FakeSqlExecutor

    monkeypatch.setenv("APAP_MIGRATION_DIR", str(tmp_path))

    client = FakeSqlExecutor()

    # 100 legacy rows (legacy has no DNI column).
    legacy_rows = [
        {
            "Voluntario": f"user-{i:03d}",
            "Email": f"u{i}@example.org",
            "Tel1": f"+34600{i:07d}",
            "Tel2": None,
        }
        for i in range(100)
    ]

    # Web seed rows carry DNI values (web-only preserve columns).
    web_seed_rows = [
        {
            "voluntario": f"user-{i:03d}",
            "email": f"u{i}@example.org",
            "tel1": f"+34600{i:07d}",
            "tel2": None,
            "dni": f"1234{i:04d}A",
        }
        for i in range(100)
    ]
    client.seed("voluntarios", web_seed_rows)

    def _legacy_executor(
        _path: str, _sql: str, _offset: int, limit: int
    ) -> list[dict[str, Any]]:
        if _offset > 0:
            return []
        return legacy_rows[:limit]

    def _legacy_write(_path: str, _sql: str, _params: Any) -> int:
        return 1

    legacy_reader.set_legacy_query_executor(_legacy_executor)
    legacy_reader.set_legacy_write_executor(_legacy_write)

    try:
        # Forward apply: 0 DNI collisions (legacy has no DNI column).
        counter = DniCollisionCounter()
        forward_result = apply_legacy_to_web(
            client,
            "voluntario",
            legacy_path=str(tmp_path / "legacy.accdb"),
            dry_run=False,
            dni_collision_counter=counter,
        )
        assert forward_result is not None
        assert counter.value == 0

        # Build the MigrationReport and pass it to the orchestrator so
        # it writes the counter value to the collisions dict.
        now = datetime(2026, 7, 30, tzinfo=UTC)
        report = MigrationReport(
            direction="web-to-legacy",
            mode="full",
            dry_run=False,
            applied=True,
            started_at=now,
            finished_at=now,
            duration_seconds=1.0,
            diffs=(),
            conflicts=(),
            backup_path=None,
            error=None,
        )

        # Reverse apply: 100 preserve-advance events, 0 actual collisions.
        # Every web row has a preserve column (DNI) set, so
        # _advance_preserve_shadow_state is called 100 times, bumping
        # the counter 100 times — even though no row diverged (legacy
        # has no DNI column, so the equality check passes and rows are skipped).
        reverse_counter = DniCollisionCounter()
        reverse_result = apply_web_to_legacy(
            client,
            "voluntario",
            legacy_path=str(tmp_path / "legacy.accdb"),
            web_snapshot=None,
            dry_run=False,
            dni_collision_counter=reverse_counter,
            migration_report=report,
        )
        assert reverse_result is not None

        # --- ASSERT the rename contract ---
        table_collisions = report.collisions["voluntario"]

        # The renamed metric must be present and equal to the number of
        # _advance_preserve_shadow_state calls (100, one per preserve row).
        assert "preserve_advances" in table_collisions, (
            f"expected 'preserve_advances' in collisions dict; got {table_collisions!r}"
        )
        assert table_collisions["preserve_advances"] == 100, (
            f"expected preserve_advances == 100; got {table_collisions['preserve_advances']!r}. "
            "The counter reflects _advance_preserve_shadow_state calls, not actual collisions."
        )

        # The old misleading key must be absent.
        assert "dni_collisions" not in table_collisions, (
            f"expected 'dni_collisions' to be absent after rename; got {table_collisions!r}. "
            "The old key name implied collisions, but the counter advances for every preserve "
            "row, not per actual collision."
        )

    finally:
        legacy_reader.set_legacy_query_executor(None)
        legacy_reader.set_legacy_write_executor(None)
