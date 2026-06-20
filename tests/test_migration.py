"""Tests for the migration module skeleton (LIFECYCLE-03 / migration-01).

This is the **first slice** of the bidirectional migration module:
the skeleton, the public exports, and the reporting dataclasses
(``MigrationReport``, ``Diff``, ``Conflict``). The full CLI, readers,
diff engine, applier and YAML mappings land in later PRs (PR 2..6).

The reporting layer is the foundation every other migration slice will
build on: ``Diff`` is the atomic unit of change, ``Conflict`` is the
atomic unit of disagreement, and ``MigrationReport`` is the immutable
record of one migration run that the operator inspects after the fact.
Keeping ``MigrationReport`` frozen + serializable is non-negotiable
because the audit trail must be tamper-evident.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from datetime import UTC, datetime

import pytest

from app.core.migration import (
    FkLookupError,
    LockActiveError,
    MappingNotFoundError,
    MigrationError,
    MigrationReport,
)
from app.core.migration.reporting import Conflict, Diff

# --- helpers --------------------------------------------------------------


def _sample_diff(op: str = "INSERT", key: str = "animal-001") -> Diff:
    return Diff(
        op=op,  # type: ignore[arg-type]
        key=key,
        legacy_row={"NCHIP": "001"},
        web_row={"NCHIP": "001"},
        changed_fields=("NombreAnimal",),
    )


def _sample_conflict(table: str = "animales") -> Conflict:
    return Conflict(
        table=table,
        key="animal-001",
        reason="modified_both_sides",
        legacy_state={"NombreAnimal": "Rex-legacy"},
        web_state={"NombreAnimal": "Rex-web"},
        last_sync_at=datetime(2026, 6, 20, 12, 0, tzinfo=UTC),
    )


def _sample_report() -> MigrationReport:
    return MigrationReport(
        direction="legacy-to-web",
        mode="dry-run",
        dry_run=True,
        applied=False,
        started_at=datetime(2026, 6, 20, 12, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 6, 20, 12, 0, 5, 250000, tzinfo=UTC),
        duration_seconds=5.25,
        diffs=(_sample_diff("INSERT", "animal-001"), _sample_diff("UPDATE", "animal-002")),
        conflicts=(_sample_conflict(),),
        backup_path=None,
        error=None,
    )


# --- TestReporting dataclass shape ----------------------------------------


def test_diff_dataclass_fields() -> None:
    """Diff carries the four required fields and a changed_fields tuple."""
    diff = _sample_diff()
    assert diff.op == "INSERT"
    assert diff.key == "animal-001"
    assert diff.legacy_row == {"NCHIP": "001"}
    assert diff.web_row == {"NCHIP": "001"}
    assert diff.changed_fields == ("NombreAnimal",)


def test_conflict_dataclass_fields() -> None:
    """Conflict carries table, key, reason, legacy/web state and last_sync_at."""
    conflict = _sample_conflict()
    assert conflict.table == "animales"
    assert conflict.key == "animal-001"
    assert conflict.reason == "modified_both_sides"
    assert conflict.legacy_state == {"NombreAnimal": "Rex-legacy"}
    assert conflict.web_state == {"NombreAnimal": "Rex-web"}
    assert conflict.last_sync_at == datetime(2026, 6, 20, 12, 0, tzinfo=UTC)


def test_migration_report_is_frozen() -> None:
    """The report is immutable: any field mutation raises FrozenInstanceError."""
    report = _sample_report()
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.applied = True  # type: ignore[misc]


def test_migration_report_to_json_basic_shape() -> None:
    """to_json returns valid JSON with the canonical top-level keys."""
    report = _sample_report()
    rendered = report.to_json()
    payload = json.loads(rendered)

    expected_keys = {
        "direction",
        "mode",
        "dry_run",
        "applied",
        "started_at",
        "finished_at",
        "duration_seconds",
        "diffs",
        "conflicts",
        "backup_path",
        "error",
    }
    assert expected_keys.issubset(payload.keys()), (
        f"missing keys in MigrationReport.to_json(): {expected_keys - payload.keys()}"
    )
    assert payload["direction"] == "legacy-to-web"
    assert payload["mode"] == "dry-run"
    assert payload["dry_run"] is True
    assert payload["applied"] is False
    assert payload["duration_seconds"] == 5.25
    assert payload["diffs"] == [
        {
            "op": "INSERT",
            "key": "animal-001",
            "legacy_row": {"NCHIP": "001"},
            "web_row": {"NCHIP": "001"},
            "changed_fields": ["NombreAnimal"],
        },
        {
            "op": "UPDATE",
            "key": "animal-002",
            "legacy_row": {"NCHIP": "001"},
            "web_row": {"NCHIP": "001"},
            "changed_fields": ["NombreAnimal"],
        },
    ]
    assert len(payload["conflicts"]) == 1
    assert payload["conflicts"][0]["table"] == "animales"


def test_migration_report_to_json_serializes_datetime_as_iso() -> None:
    """datetime fields are serialized as ISO-8601 strings (JSON-compatible)."""
    report = _sample_report()
    payload = json.loads(report.to_json())
    # ISO-8601 with timezone offset: e.g. "2026-06-20T12:00:00+00:00"
    assert payload["started_at"].startswith("2026-06-20T12:00:00")
    assert payload["finished_at"].startswith("2026-06-20T12:00:05")


def test_migration_report_to_markdown_contains_summary_table() -> None:
    """to_markdown produces a markdown table with the exact per-op counts.

    The sample report has 1 INSERT, 1 UPDATE, 0 DELETE, 0 NOOP, 1 conflict.
    Assertions target the exact metric rows (not arbitrary digits) so the
    test catches drift in the renderer instead of silently passing on any
    ``2`` / ``1`` that happens to appear in the markdown.
    """
    report = _sample_report()
    md = report.to_markdown()
    assert isinstance(md, str)
    # Header line identifies the report
    assert "Migration Report" in md
    # Direction and mode are surfaced
    assert "legacy-to-web" in md
    assert "dry-run" in md
    # Per-op metric rows are exact (the renderer emits ``| OP | N |``).
    assert "| INSERT | 1 |" in md
    assert "| UPDATE | 1 |" in md
    assert "| DELETE | 0 |" in md
    assert "| NOOP | 0 |" in md
    assert "| Conflict | 1 |" in md
    # Total row counts all diffs (PR-review P2 #3).
    assert "| Total | 2 |" in md


# --- TestMigrationModule public exports ----------------------------------


def test_migration_module_exports_report() -> None:
    """``MigrationReport`` is importable from the package root."""
    assert MigrationReport is not None
    assert callable(MigrationReport)


def test_migration_module_exports_error_hierarchy() -> None:
    """All four exception types are exported and inherit from MigrationError."""
    assert issubclass(MigrationError, Exception)
    assert issubclass(MappingNotFoundError, MigrationError)
    assert issubclass(LockActiveError, MigrationError)
    assert issubclass(FkLookupError, MigrationError)


def test_migration_module_exports_reporting_dataclasses() -> None:
    """``Diff`` and ``Conflict`` are importable from the reporting submodule."""
    assert Diff is not None
    assert Conflict is not None


def test_migration_module_main_runs_without_error() -> None:
    """``python -m app.core.migration`` is a valid entry point.

    The skeleton does not yet implement argparse, so the entry point
    must either print a help message (exit 0) or print a placeholder
    and exit 0 cleanly. We do NOT assert that ``--help`` works because
    the full CLI lands in a later slice.
    """
    result = subprocess.run(
        [sys.executable, "-m", "app.core.migration"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"python -m app.core.migration exited {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
