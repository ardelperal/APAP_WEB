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
from pydantic import ValidationError

from app.core.migration import (
    FkLookupError,
    LockActiveError,
    MappingNotFoundError,
    MigrationError,
    MigrationReport,
)
from app.core.migration.mappings import (
    FkLookup,
    TableMapping,
    list_available_tables,
    load_mapping,
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


# --- TestMappings: YAML loader + 5 mappings ------------------------------
#
# Slice MIGRATION-01 PR 2: cover the TableMapping pydantic model,
# the load_mapping() loader (raises MappingNotFoundError for unknown
# tables), the list_available_tables() helper, and the 5 YAML files
# (animal, voluntario, entrada, acogida, adopcion).
#
# These tests are written BEFORE the YAMLs and the loader module
# exist (TDD red phase). They are the acceptance contract for the
# slice: if any of them fails after the implementation, the slice is
# not done. The tests target SPECIFIC facts of each YAML (not just
# "is the file loadable") so they catch silent drift.


class TestMappings:
    """Tests for the YAML mappings loader and the 5 table mappings."""

    # --- load_mapping returns the right TableMapping per table ---------

    def test_load_mapping_animales(self) -> None:
        """load_mapping('animal') returns animales ↔ TbFichaAnimal."""
        mapping = load_mapping("animal")
        assert isinstance(mapping, TableMapping)
        assert mapping.web_table == "animales"
        assert mapping.legacy_table == "TbFichaAnimal"

    def test_load_mapping_voluntarios(self) -> None:
        """load_mapping('voluntario') returns voluntarios ↔ TbVoluntariosParaAutorrellenables."""
        mapping = load_mapping("voluntario")
        assert isinstance(mapping, TableMapping)
        assert mapping.web_table == "voluntarios"
        assert mapping.legacy_table == "TbVoluntariosParaAutorrellenables"

    def test_load_mapping_entradas(self) -> None:
        """load_mapping('entrada') returns entradas ↔ TbEntradas with FK lookups."""
        mapping = load_mapping("entrada")
        assert isinstance(mapping, TableMapping)
        assert mapping.web_table == "entradas"
        assert mapping.legacy_table == "TbEntradas"
        # entradas has FK lookups to animales + 2 voluntarios
        assert len(mapping.fk_lookups) >= 1
        names = {fk.name for fk in mapping.fk_lookups}
        assert "animal" in names

    def test_load_mapping_acogidas(self) -> None:
        """load_mapping('acogida') returns acogidas ↔ TbAcogidaAnimal."""
        mapping = load_mapping("acogida")
        assert isinstance(mapping, TableMapping)
        assert mapping.web_table == "acogidas"
        assert mapping.legacy_table == "TbAcogidaAnimal"

    def test_load_mapping_adopciones(self) -> None:
        """load_mapping('adopcion') returns adopciones ↔ TbAdopcion."""
        mapping = load_mapping("adopcion")
        assert isinstance(mapping, TableMapping)
        assert mapping.web_table == "adopciones"
        assert mapping.legacy_table == "TbAdopcion"

    # --- error handling for unknown tables -----------------------------

    def test_load_mapping_unknown_table_raises_mapping_not_found_error(self) -> None:
        """load_mapping('desconocida') raises MappingNotFoundError."""
        with pytest.raises(MappingNotFoundError):
            load_mapping("desconocida")

    # --- list_available_tables -----------------------------------------

    def test_list_available_tables_returns_five_tables(self) -> None:
        """list_available_tables() returns the 5 tables in alphabetical order."""
        tables = list_available_tables()
        assert tables == ["acogida", "adopcion", "animal", "entrada", "voluntario"]

    # --- specific YAML facts (regression guard) -----------------------

    def test_animal_yaml_key_field_is_NCHIP(self) -> None:
        """animal.yaml uses NCHIP as the natural key for matching rows."""
        mapping = load_mapping("animal")
        assert mapping.key_field == "NCHIP"
        assert mapping.legacy_key == "NCHIP"

    def test_entrada_yaml_has_fk_lookup_for_animal_id(self) -> None:
        """entrada.yaml has an FK lookup named 'animal' pointing to animales.NCHIP."""
        mapping = load_mapping("entrada")
        animal_fk = next(
            (fk for fk in mapping.fk_lookups if fk.name == "animal"),
            None,
        )
        assert animal_fk is not None, "entrada.yaml missing fk_lookups[name='animal']"
        assert animal_fk.lookup_table == "animales"
        assert animal_fk.lookup_legacy_key == "NCHIP"
        assert animal_fk.web_column == "animal_id"

    def test_voluntario_yaml_fuzzy_match_enabled(self) -> None:
        """FK lookups to voluntarios use fuzzy_match=True with threshold 85.

        Voluntario names are free-text, so the FK resolver must enable
        fuzzy matching to recover from typos / trailing whitespace. This
        test scans all 5 mappings and asserts that any fk_lookup whose
        ``lookup_table`` is ``voluntarios`` is configured with
        ``fuzzy_match=True`` and ``fuzzy_threshold=85`` (the conservative
        default documented in the design). Optional lookups must also
        have ``optional=True`` so a missing match does not abort the run.
        """
        voluntary_fks: list[FkLookup] = []
        for table in list_available_tables():
            mapping = load_mapping(table)
            voluntary_fks.extend(
                fk for fk in mapping.fk_lookups if fk.lookup_table == "voluntarios"
            )
        # Sanity: at least one mapping references voluntarios as a lookup target.
        assert voluntary_fks, "No fk_lookups target voluntarios across the 5 YAMLs"
        for fk in voluntary_fks:
            assert fk.fuzzy_match is True, (
                f"FK lookup {fk.name!r} → voluntarios must enable fuzzy_match"
            )
            assert fk.fuzzy_threshold == 85, (
                f"FK lookup {fk.name!r} → voluntarios must use threshold 85"
            )
            assert fk.optional is True, f"FK lookup {fk.name!r} → voluntarios must be optional"

    def test_table_mapping_pydantic_validates_required_fields(self) -> None:
        """TableMapping rejects a YAML that omits required fields.

        We build a minimal malformed dict (no ``web_table``) and try to
        validate it directly via the pydantic model. Pydantic must raise
        ``ValidationError`` (NOT silently coerce or accept). The error
        message must mention the missing field.
        """
        bad_payload = {
            # web_table intentionally missing
            "legacy_table": "TbAlgo",
            "key_field": "id",
            "legacy_key": "id",
            "columns": [],
            "fk_lookups": [],
        }
        with pytest.raises(ValidationError) as excinfo:
            TableMapping.model_validate(bad_payload)
        # The error must surface 'web_table' so the operator can fix it.
        assert "web_table" in str(excinfo.value), (
            f"ValidationError did not mention missing field 'web_table': {excinfo.value!r}"
        )
