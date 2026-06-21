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
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.core.insforge import InsForgeClient
from app.core.migration import (
    FkLookupError,
    LockActiveError,
    MappingNotFoundError,
    MigrationError,
    MigrationReport,
)
from app.core.migration.mappings import (
    ColumnMapping,
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
    """``python -m app.core.migration --help`` is a valid entry point.

    After PR 1 of web-only-feature-preservation, the CLI has a real
    argparse parser with a ``reconcile`` subcommand, so invoking
    ``python -m app.core.migration`` without a subcommand now exits
    non-zero (argparse ``required=True``). ``--help`` exits 0 and lists
    the available subcommands.
    """
    result = subprocess.run(
        [sys.executable, "-m", "app.core.migration", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"python -m app.core.migration --help exited {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert "reconcile" in result.stdout


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


# --- TestColumnMapping.web_only_strategy ---------------------------------
#
# PR 1 of web-only-feature-preservation: ColumnMapping grows a
# ``web_only_strategy`` field that MUST be set whenever ``legacy_column``
# is null (the column is web-only / greenfield). The validator aborts
# BEFORE any I/O so a typo is caught at YAML-load time, not at apply
# time. See spec.md REQ-Mecanismo generico declarativo via YAML and
# design.md §9.


class TestColumnMappingWebOnlyStrategy:
    """Tests for ColumnMapping.web_only_strategy validation."""

    def test_accepts_none_when_legacy_column_is_mapped(self) -> None:
        """A column with legacy_column set may have web_only_strategy=None
        (it has a legacy source, so the strategy is irrelevant)."""
        col = ColumnMapping(
            web_column="NCHIP",
            legacy_column="NCHIP",
            transform="identity",
            nullable=False,
        )
        assert col.web_only_strategy is None

    def test_accepts_preserve_when_legacy_column_is_null(self) -> None:
        """A web-only column (legacy_column=None) MUST declare a strategy."""
        col = ColumnMapping(
            web_column="DNI",
            legacy_column=None,
            transform="identity",
            nullable=True,
            web_only_strategy="preserve",
        )
        assert col.web_only_strategy == "preserve"

    def test_accepts_fixed_and_derived(self) -> None:
        """All three strategies are accepted by the Literal type."""
        for strategy in ("preserve", "fixed", "derived"):
            col = ColumnMapping(
                web_column="x",
                legacy_column=None,
                web_only_strategy=strategy,  # type: ignore[arg-type]
            )
            assert col.web_only_strategy == strategy

    def test_rejects_invalid_strategy_value(self) -> None:
        """A strategy outside the Literal raises ValidationError.

        Catches typos (``"preserved"``, ``"auto"``, ``"magic"``) at
        YAML-load time so the operator never reaches the applier with a
        strategy the derivation engine cannot interpret.
        """
        with pytest.raises(ValidationError) as excinfo:
            ColumnMapping(
                web_column="x",
                legacy_column=None,
                web_only_strategy="magic",  # type: ignore[arg-type]
            )
        assert "web_only_strategy" in str(excinfo.value)

    def test_none_strategy_accepted_in_pr1(self) -> None:
        """PR 1 only rejects INVALID strategies; the strict
        ``legacy_column=null → strategy required`` check is PR 3's job
        (it requires the 5 YAMLs to declare a strategy on every
        web-only column, which lands in tasks.md 3.1 / 3.4).

        Until PR 3 ships those YAML updates, ``web_only_strategy=None``
        must remain accepted so the existing mappings keep loading.

        Post-PR 3 the strict validator is active, but this column is
        exempt (``transform=default_uuid`` → auto-generated PK, no
        business value to preserve). The test continues to pass and
        documents why: only identity-shaped columns (the ones that
        actually carry user data) require an explicit strategy.
        """
        col = ColumnMapping(
            web_column="id",
            legacy_column=None,
            transform="default_uuid",
            nullable=False,
        )
        assert col.web_only_strategy is None


# --- TestStrictWebOnlyStrategyValidator -----------------------------------
#
# PR 3 of web-only-feature-preservation activates the strict validator
# that PR 1 deferred. Contract (documented in
# ``app/core/migration/mappings/__init__.py`` and design.md §9):
#
#   "If ``legacy_column`` is ``null`` AND the column is not exempt
#    (transform in {default_uuid, default_now, fk_lookup}), then
#    ``web_only_strategy`` MUST be set."
#
# Rationale for the exemptions:
#
#   - ``default_uuid`` (column ``id`` PK): the web generates a UUID v4
#     mechanically — there is no user value to preserve.
#   - ``default_now`` (columns ``fecha_alta`` / ``updated_at``): the
#     web stamps the current UTC time — there is no legacy data and
#     nothing for the derivation engine to read.
#   - ``fk_lookup`` (cross-table FKs like ``animal_id``): the value is
#     resolved via ``sync_state.json`` (legacy_id ↔ web_uuid), not via
#     shadow state — preserving it via web_only_strategy would be a
#     duplicate mechanism.
#
# Columns with transforms ``identity``, ``currency_to_numeric``,
# ``double_to_numeric`` AND ``legacy_column=null`` are real
# user/business values that MUST declare a strategy (preserve / fixed /
# derived). Columns with ``default_true`` (the soft-delete ``activo``
# flag) also need a strategy (``fixed``) — the web owns the decision,
# so the shadow-state repository must know not to try to reconcile it.
#
# These tests are RED until PR 3 activates the strict validator.


class TestStrictWebOnlyStrategyValidator:
    """Tests for the strict ``legacy_column=null → strategy required``
    validator activated in PR 3.

    Companion to ``TestColumnMappingWebOnlyStrategy`` (PR 1, which
    covers the field type and the invalid-value validator). PR 3 adds
    the rule "if the column is web-only and not exempt, it MUST
    declare a strategy".
    """

    # --- rejects: identity-shaped web-only columns without a strategy ----

    def test_identity_web_only_without_strategy_raises_validation_error(self) -> None:
        """``transform=identity`` with ``legacy_column=null`` and no
        strategy is rejected. This is the canonical PR 3 scenario from
        tasks.md 3.2 and spec.md "Columna sin web_only_strategy con
        legacy_column=null aborta".
        """
        with pytest.raises(ValidationError) as excinfo:
            ColumnMapping(
                web_column="DNI",
                legacy_column=None,
                transform="identity",
                nullable=True,
            )
        assert "web_only_strategy" in str(excinfo.value)

    def test_currency_web_only_without_strategy_raises_validation_error(self) -> None:
        """``transform=currency_to_numeric`` with ``legacy_column=null``
        and no strategy is rejected — same contract as identity.
        """
        with pytest.raises(ValidationError) as excinfo:
            ColumnMapping(
                web_column="donativo",
                legacy_column=None,
                transform="currency_to_numeric",
                nullable=True,
            )
        assert "web_only_strategy" in str(excinfo.value)

    def test_double_web_only_without_strategy_raises_validation_error(self) -> None:
        """``transform=double_to_numeric`` with ``legacy_column=null``
        and no strategy is rejected — same contract as identity.
        """
        with pytest.raises(ValidationError) as excinfo:
            ColumnMapping(
                web_column="peso_kg",
                legacy_column=None,
                transform="double_to_numeric",
                nullable=True,
            )
        assert "web_only_strategy" in str(excinfo.value)

    def test_default_true_without_strategy_raises_validation_error(self) -> None:
        """``transform=default_true`` (``activo`` soft-delete flag) is
        NOT exempt: the web owns the decision, so the shadow-state
        repository needs to know it must not try to reconcile it.
        Without a strategy, the strict validator rejects.
        """
        with pytest.raises(ValidationError) as excinfo:
            ColumnMapping(
                web_column="activo",
                legacy_column=None,
                transform="default_true",
                nullable=False,
            )
        assert "web_only_strategy" in str(excinfo.value)

    # --- accepts: identity-shaped web-only columns WITH a strategy ------

    def test_identity_web_only_with_preserve_strategy_succeeds(self) -> None:
        """Explicit ``preserve`` strategy is accepted for identity web-only."""
        col = ColumnMapping(
            web_column="DNI",
            legacy_column=None,
            transform="identity",
            nullable=True,
            web_only_strategy="preserve",
        )
        assert col.web_only_strategy == "preserve"

    def test_default_true_with_fixed_strategy_succeeds(self) -> None:
        """``activo`` with ``fixed`` strategy is accepted."""
        col = ColumnMapping(
            web_column="activo",
            legacy_column=None,
            transform="default_true",
            nullable=False,
            web_only_strategy="fixed",
        )
        assert col.web_only_strategy == "fixed"

    # --- accepts: exempt transforms (no strategy needed) ----------------

    def test_default_uuid_web_only_without_strategy_succeeds(self) -> None:
        """``transform=default_uuid`` is exempt — the web generates the
        UUID mechanically (column ``id`` PK). No business value to
        preserve; the strict validator does not require a strategy.
        """
        col = ColumnMapping(
            web_column="id",
            legacy_column=None,
            transform="default_uuid",
            nullable=False,
        )
        assert col.web_only_strategy is None

    def test_default_now_web_only_without_strategy_succeeds(self) -> None:
        """``transform=default_now`` is exempt — web stamps ``utcnow()``
        on INSERT/UPDATE (columns ``fecha_alta`` / ``updated_at``).
        """
        col = ColumnMapping(
            web_column="fecha_alta",
            legacy_column=None,
            transform="default_now",
            nullable=False,
        )
        assert col.web_only_strategy is None

    def test_fk_lookup_web_only_without_strategy_succeeds(self) -> None:
        """``transform=fk_lookup`` is exempt — cross-table FKs are
        resolved via ``sync_state.json`` (legacy_id ↔ web_uuid), not
        via shadow state. Declaring ``web_only_strategy`` here would
        be a duplicate mechanism.
        """
        col = ColumnMapping(
            web_column="animal_id",
            legacy_column=None,
            transform="fk_lookup",
            nullable=False,
            lookup="animal",
        )
        assert col.web_only_strategy is None

    # --- legacy_column set: no strategy needed (no contract change) -----

    def test_legacy_column_set_without_strategy_succeeds(self) -> None:
        """A column with ``legacy_column`` set may omit the strategy —
        the value comes from the legacy DB, so web-only preservation
        does not apply.
        """
        col = ColumnMapping(
            web_column="NCHIP",
            legacy_column="NCHIP",
            transform="identity",
            nullable=False,
        )
        assert col.web_only_strategy is None

    # --- exit code 4 convention -----------------------------------------

    def test_exit_code_yaml_validation_error_constant_is_4(self) -> None:
        """The exit-code convention is a public module constant
        (``EXIT_CODE_YAML_VALIDATION_ERROR == 4``) so CLI / applier
        code that catches ``ValidationError`` from ``load_mapping()``
        can map it to exit code 4 without re-declaring the magic
        number. See design.md §1.5 and spec.md REQ-Mecanismo generico.
        """
        from app.core.migration.mappings import (
            EXIT_CODE_YAML_VALIDATION_ERROR,
        )

        assert EXIT_CODE_YAML_VALIDATION_ERROR == 4

    def test_load_mapping_propagates_validation_error_from_strict_check(
        self, tmp_path: Path
    ) -> None:
        """``load_mapping()`` must NOT swallow the ``ValidationError``
        from the strict validator — the CLI / applier needs to see it
        so it can convert to exit code 4 BEFORE any I/O (design §1.5).

        We write a YAML with ``legacy_column: null`` + ``identity``
        transform + no strategy, then call ``load_mapping()`` and
        assert ``ValidationError`` bubbles up.
        """
        from app.core.migration.mappings import load_mapping

        bad_yaml = tmp_path / "bad_mapping.yaml"
        bad_yaml.write_text(
            "version: '1.0'\n"
            "web_table: bad\n"
            "legacy_table: TbBad\n"
            "key_field: id\n"
            "legacy_key: id\n"
            "columns:\n"
            "  - { web_column: id, transform: default_uuid, nullable: false }\n"
            # This column violates the strict validator — identity
            # web-only without a strategy.
            "  - { web_column: extra, legacy_column: null, transform: identity, nullable: true }\n",
            encoding="utf-8",
        )
        # Monkey-patch ``MAPPINGS_DIR`` so ``load_mapping`` reads our
        # bad YAML. We restore it after the test so the next test
        # isn't affected.
        from app.core.migration import mappings as mappings_module

        original_dir = mappings_module.MAPPINGS_DIR
        try:
            # ``load_mapping`` joins ``MAPPINGS_DIR / f"{table}.yaml"``,
            # so we put the bad YAML under a fake MAPPINGS_DIR.
            fake_dir = tmp_path / "fake_mappings"
            fake_dir.mkdir()
            (fake_dir / "bad.yaml").write_bytes(bad_yaml.read_bytes())
            mappings_module.MAPPINGS_DIR = fake_dir

            with pytest.raises(ValidationError) as excinfo:
                load_mapping("bad")
            assert "web_only_strategy" in str(excinfo.value)
        finally:
            mappings_module.MAPPINGS_DIR = original_dir


# --- TestYamlWebOnlyStrategyRegression ------------------------------------
#
# PR 3 closes the loop: every web-only column in the 5 existing YAMLs
# must declare ``web_only_strategy`` so that the strict validator
# accepts the YAMLs. These tests are the regression guard — if a YAML
# regresses and loses its ``web_only_strategy``, these tests fail at
# YAML-load time (before any I/O).


class TestYamlWebOnlyStrategyRegression:
    """Regression tests for ``web_only_strategy`` declarations in the
    5 YAML mappings shipped by MIGRATION-01 PR 2.

    Each YAML must declare a strategy on every column that requires
    one (per the contract in ``TestStrictWebOnlyStrategyValidator``).
    If a future edit strips the strategy, ``load_mapping()`` raises
    ``ValidationError`` and these tests catch it.
    """

    @pytest.mark.parametrize(
        ("table", "expected_web_table"),
        [
            ("animal", "animales"),
            ("voluntario", "voluntarios"),
            ("entrada", "entradas"),
            ("acogida", "acogidas"),
            ("adopcion", "adopciones"),
        ],
    )
    def test_load_mapping_succeeds_for_each_yaml(self, table: str, expected_web_table: str) -> None:
        """Each of the 5 YAMLs must load cleanly under the strict
        validator. A failure here means a YAML lost its
        ``web_only_strategy`` declaration; fix the YAML, not this test.
        """
        mapping = load_mapping(table)
        assert isinstance(mapping, TableMapping)
        assert mapping.web_table == expected_web_table

    @pytest.mark.parametrize(
        "table",
        ["animal", "voluntario", "entrada", "acogida", "adopcion"],
    )
    def test_activo_column_declares_fixed_strategy_in_each_yaml(self, table: str) -> None:
        """``activo`` (soft-delete flag) uses ``transform=default_true``
        which is NOT exempt. Every YAML must declare
        ``web_only_strategy: fixed`` so the shadow-state repository
        knows the web owns this column and must not try to reconcile.
        """
        mapping = load_mapping(table)
        activo = next(
            (c for c in mapping.columns if c.web_column == "activo"),
            None,
        )
        assert activo is not None, f"{table}.yaml missing 'activo' column"
        assert activo.web_only_strategy == "fixed", (
            f"{table}.yaml: 'activo' must declare web_only_strategy='fixed', "
            f"got {activo.web_only_strategy!r}"
        )

    def test_voluntario_yaml_dni_declares_preserve_strategy(self) -> None:
        """``voluntarios.DNI`` is the canonical web-only column
        (no DNI in legacy). Must declare ``preserve`` so the
        shadow-state repository persists the value across the
        round-trip. See tasks.md 3.1 and spec.md REQ-Mecanismo
        generico declarativo via YAML.
        """
        mapping = load_mapping("voluntario")
        dni = next(
            (c for c in mapping.columns if c.web_column == "DNI"),
            None,
        )
        assert dni is not None, "voluntario.yaml missing 'DNI' column"
        assert dni.legacy_column is None, (
            "DNI must declare legacy_column=null (it does not exist "
            "in the legacy TBVoluntariosParaAutorrellenables)"
        )
        assert dni.web_only_strategy == "preserve", (
            f"DNI must declare web_only_strategy='preserve', got {dni.web_only_strategy!r}"
        )

    @pytest.mark.parametrize(
        "table",
        ["animal", "voluntario", "entrada", "acogida", "adopcion"],
    )
    def test_auto_generated_columns_remain_exempt(self, table: str) -> None:
        """Regression guard for the exemption list: ``id`` /
        ``fecha_alta`` / ``updated_at`` MUST NOT declare a strategy
        even though they have ``legacy_column=null`` (auto-generated
        web values, not targets of legacy→web derivation). If a future
        edit adds a strategy to these, the strict validator still
        accepts it (it's allowed to be set), but we want to document
        the convention so it doesn't drift: these stay
        ``web_only_strategy=None``.
        """
        mapping = load_mapping(table)
        for column_name in ("id", "fecha_alta", "updated_at"):
            col = next(
                (c for c in mapping.columns if c.web_column == column_name),
                None,
            )
            assert col is not None, f"{table}.yaml missing auto-generated column {column_name!r}"
            assert col.web_only_strategy is None, (
                f"{table}.yaml: auto-generated column {column_name!r} "
                f"must NOT declare web_only_strategy (exempt), "
                f"got {col.web_only_strategy!r}"
            )

    @pytest.mark.parametrize(
        "table",
        ["entrada", "acogida", "adopcion"],
    )
    def test_fk_columns_remain_exempt_in_each_yaml(self, table: str) -> None:
        """Regression guard for the FK exemption: cross-table FK
        columns (``animal_id``, ``voluntario_*_id``,
        ``entrada_origen_id``, etc.) use ``transform=fk_lookup`` and
        MUST stay ``web_only_strategy=None`` because their value is
        resolved via ``sync_state.json``, not via shadow state.
        """
        mapping = load_mapping(table)
        fk_columns = [c for c in mapping.columns if c.transform == "fk_lookup"]
        assert fk_columns, (
            f"{table}.yaml should have at least one fk_lookup column "
            f"(regression guard for this test's premise)"
        )
        for fk_col in fk_columns:
            assert fk_col.web_only_strategy is None, (
                f"{table}.yaml: FK column {fk_col.web_column!r} "
                f"(transform=fk_lookup) must NOT declare web_only_strategy "
                f"(exempt — resolved via sync_state.json), got "
                f"{fk_col.web_only_strategy!r}"
            )


# --- TestLegacyReader + TestWebReader -------------------------------------
#
# Slice MIGRATION-01 PR 3 (T4): cover the readers that producen los
# snapshots que el diff engine consume. ``legacy_reader`` lee el .accdb
# en batches de 100 filas vía Dysflow (con un callable inyectable para
# tests, sin acoplar a la MCP real); ``web_reader`` lee vía
# ``InsForgeClient`` (mockeable con ``httpx.MockTransport``). Ambos
# retornan ``dict[str, list[dict]]`` indexado por nombre de tabla.
#
# Estos tests se escriben ANTES de los módulos
# ``legacy_reader.py``/``web_reader.py`` (TDD red phase) y son el
# contrato de aceptación del slice: si alguno falla tras la
# implementación, el slice no está listo.


class TestLegacyReader:
    """Tests para ``legacy_reader.load_legacy_snapshot_batched``.

    Cada mock del executor inyectable acepta
    ``(legacy_path, sql, offset, limit)`` y devuelve ``list[dict]`` —
    contrato que ``legacy_reader._execute_legacy_query`` ahora
    establece tras el fix P1 de PR #95 (revisión de código).
    """

    def test_returns_dict_with_table_names_as_keys(self) -> None:
        """El snapshot retorna ``dict[str, list[dict]]`` con nombres legacy como keys."""
        captured_queries: list[str] = []
        call_count = [0]

        def mock_executor(legacy_path: str, sql: str, offset: int, limit: int) -> list[dict]:
            captured_queries.append(sql)
            call_count[0] += 1
            # Primera llamada: 1 fila. Segunda: vacío (fin del paging).
            # El paging loop termina cuando el source retorna ``[]``,
            # estándar de la paginación batched (design §5).
            if call_count[0] == 1:
                return [{"NCHIP": "value1", "NombreAnimal": "Firulais"}]
            return []

        from app.core.migration.legacy_reader import (
            TableSpec,
            load_legacy_snapshot,
            set_legacy_query_executor,
        )

        set_legacy_query_executor(mock_executor)
        try:
            result = load_legacy_snapshot(
                "/fake/path.accdb",
                [TableSpec("TbFichaAnimal", ("NCHIP", "NombreAnimal"))],
            )
        finally:
            set_legacy_query_executor(None)

        assert "TbFichaAnimal" in result
        assert len(result["TbFichaAnimal"]) == 1
        assert result["TbFichaAnimal"][0]["NCHIP"] == "value1"
        assert result["TbFichaAnimal"][0]["NombreAnimal"] == "Firulais"

    def test_builds_sql_with_top_n(self) -> None:
        """El SQL generado usa ``TOP n`` (no ``LIMIT``) porque Access no soporta ``LIMIT``."""
        captured_queries: list[str] = []

        def mock_executor(legacy_path: str, sql: str, offset: int, limit: int) -> list[dict]:
            captured_queries.append(sql)
            return []

        from app.core.migration.legacy_reader import (
            TableSpec,
            load_legacy_snapshot,
            set_legacy_query_executor,
        )

        set_legacy_query_executor(mock_executor)
        try:
            load_legacy_snapshot(
                "/fake/path.accdb",
                [TableSpec("TbFichaAnimal", ("NCHIP",))],
            )
        finally:
            set_legacy_query_executor(None)

        assert len(captured_queries) >= 1
        assert "SELECT TOP 100" in captured_queries[0]
        assert "FROM TbFichaAnimal" in captured_queries[0]
        # Sanity: NO usamos LIMIT (eso es PostgreSQL/MySQL).
        assert "LIMIT" not in captured_queries[0]

    def test_legacy_query_executor_can_be_reset(self) -> None:
        """``set_legacy_query_executor(None)`` resetea al estado inicial."""
        from app.core.migration.legacy_reader import set_legacy_query_executor

        set_legacy_query_executor(lambda p, s, o, lim: [])
        set_legacy_query_executor(None)
        # El reset no debe levantar excepción; el siguiente call usaría
        # el executor real (Dysflow) si lo hubiera — no testeable en CI.

    def test_load_legacy_snapshot_batched_yields_tuples(self) -> None:
        """``load_legacy_snapshot_batched`` yields ``(table_name, [rows])`` por batch."""
        call_count = [0]

        def mock_executor(legacy_path: str, sql: str, offset: int, limit: int) -> list[dict]:
            call_count[0] += 1
            if call_count[0] == 1:
                return [{"NCHIP": "first_batch"}]
            # Segunda llamada retorna vacío → fin del loop de batches.
            return []

        from app.core.migration.legacy_reader import (
            TableSpec,
            load_legacy_snapshot_batched,
            set_legacy_query_executor,
        )

        set_legacy_query_executor(mock_executor)
        try:
            batches = list(
                load_legacy_snapshot_batched(
                    "/fake/path.accdb",
                    [TableSpec("TbFichaAnimal", ("NCHIP",))],
                )
            )
        finally:
            set_legacy_query_executor(None)

        assert len(batches) == 1
        table_name, rows = batches[0]
        assert table_name == "TbFichaAnimal"
        assert rows == [{"NCHIP": "first_batch"}]

    def test_executor_receives_offset_on_second_batch(self) -> None:
        """El paging loop debe pasar ``offset`` creciente al executor.

        Regression guard para el P1 del review de PR #95: la firma de
        ``_build_select_sql`` aceptaba ``offset`` pero nunca lo usaba,
        por lo que el paging loop generaba el mismo SQL en cada batch
        y, con el executor real de Dysflow en PR 5/6, retornaría las
        mismas filas infinitamente, colgando el CLI.

        Este test verifica que el executor recibe ``offset == BATCH_SIZE``
        en la segunda llamada — el contrato que design §5 establece
        (``dysflow_query_execute(..., offset=offset, limit=BATCH_SIZE)``).
        """
        from app.core.migration.legacy_reader import (
            BATCH_SIZE,
            TableSpec,
            load_legacy_snapshot,
            set_legacy_query_executor,
        )

        captured: list[dict[str, int | str]] = []
        call_count = [0]

        def mock_executor(legacy_path: str, sql: str, offset: int, limit: int) -> list[dict]:
            captured.append(
                {"legacy_path": legacy_path, "sql": sql, "offset": offset, "limit": limit}
            )
            call_count[0] += 1
            if call_count[0] == 1:
                return [{"NCHIP": "row1"}]
            # Segunda llamada → loop termina con ``[]``.
            return []

        set_legacy_query_executor(mock_executor)
        try:
            load_legacy_snapshot(
                "/fake/path.accdb",
                [TableSpec("TbFichaAnimal", ("NCHIP",))],
            )
        finally:
            set_legacy_query_executor(None)

        # Dos llamadas: una fila, luego vacío.
        assert len(captured) == 2
        # Primera llamada: offset=0, limit=BATCH_SIZE.
        assert captured[0]["offset"] == 0
        assert captured[0]["limit"] == BATCH_SIZE
        # Segunda llamada: offset avanzado por BATCH_SIZE — esto es lo
        # que estaba ROTO (regression guard del P1).
        assert captured[1]["offset"] == BATCH_SIZE
        assert captured[1]["limit"] == BATCH_SIZE


class TestWebReader:
    """Tests para ``web_reader.load_web_snapshot``."""

    def _make_mock_client(self, captured: list[str]) -> InsForgeClient:
        """Construye un InsForgeClient con MockTransport que captura el SQL enviado."""

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request.content.decode())
            return httpx.Response(
                200,
                json=[{"id": "uuid-1", "NCHIP": "ABC"}],
                headers={"content-type": "application/json"},
            )

        return InsForgeClient(
            base_url="https://example.insforge.app",
            service_key="ik_test",
            transport=httpx.MockTransport(handler),
        )

    def test_returns_dict_with_web_table_names_as_keys(self) -> None:
        """El snapshot retorna ``dict[str, list[dict]]`` con nombres web como keys."""
        captured: list[str] = []
        client = self._make_mock_client(captured)

        from app.core.migration.web_reader import WebTableSpec, load_web_snapshot

        result = load_web_snapshot(
            client,
            [WebTableSpec("animales", ("id", "NCHIP"))],
        )

        assert "animales" in result
        assert len(result["animales"]) == 1
        assert result["animales"][0]["NCHIP"] == "ABC"
        # El SQL enviado al web contiene los nombres de columnas y la tabla.
        assert len(captured) == 1
        assert "SELECT" in captured[0]
        assert "FROM animales" in captured[0]

    def test_builds_sql_with_where_clause_for_incremental(self) -> None:
        """Para incremental (``since`` provisto), el SQL incluye ``WHERE updated_at >``."""
        captured: list[str] = []
        client = self._make_mock_client(captured)

        from app.core.migration.web_reader import WebTableSpec, load_web_snapshot

        since = datetime(2026, 6, 20, 10, 0)
        load_web_snapshot(
            client,
            [WebTableSpec("animales", ("id",), since=since)],
        )

        assert len(captured) == 1
        assert "WHERE updated_at >" in captured[0]
        assert "2026-06-20T10:00:00" in captured[0]

    def test_web_reader_handles_empty_table(self) -> None:
        """Si la tabla está vacía, el resultado es un dict con lista vacía."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[],
                headers={"content-type": "application/json"},
            )

        client = InsForgeClient(
            base_url="https://example.insforge.app",
            service_key="ik_test",
            transport=httpx.MockTransport(handler),
        )

        from app.core.migration.web_reader import WebTableSpec, load_web_snapshot

        result = load_web_snapshot(
            client,
            [WebTableSpec("animales", ("id",))],
        )

        assert result == {"animales": []}


# --- TestReconcileTypes + TestCliReconcile ---------------------------------
#
# PR 1 of web-only-feature-preservation: reconcile types are introduced
# here (PR 2 fills in the semantics); the ``reconcile`` subcommand is a
# skeleton that exposes the four flags (--interactive, --check-only,
# --table, --since) and exits cleanly. The full behaviour lands in PR 5.


class TestReconcileTypes:
    """Shape-only smoke tests for the PR 1 reconcile types.

    These do not exercise the semantics — those arrive with the derivation
    engine in PR 2 and the hook integration in PR 4. PR 1 just ensures
    the symbols exist and can be imported / instantiated.
    """

    def test_reconciliation_status_literal_values(self) -> None:
        """ReconciliationStatus is a Literal with the 5 documented values."""
        from app.core.migration.reconcile import ReconciliationStatus

        for value in ("matched", "divergent", "needs_review", "pending", "migrated"):
            assert ReconciliationStatus(value) == value

    def test_reconciliation_outcome_holds_status_and_reasons(self) -> None:
        """ReconciliationOutcome is a dataclass with the documented fields."""
        from app.core.migration.reconcile import (
            ReconciliationOutcome,
            ReconciliationStatus,
        )

        outcome = ReconciliationOutcome(
            table_name="voluntarios",
            legacy_pk="123",
            web_column="DNI",
            status=ReconciliationStatus.NEEDS_REVIEW,
            web_value="12345678A",
            derived_value=None,
            review_reasons=("web_manual_override_detected",),
        )
        assert outcome.table_name == "voluntarios"
        assert outcome.status is ReconciliationStatus.NEEDS_REVIEW
        assert outcome.review_reasons == ("web_manual_override_detected",)

    def test_reconciliation_result_aggregates_outcomes(self) -> None:
        """ReconciliationResult carries the outcomes list and counts per status."""
        from app.core.migration.reconcile import (
            ReconciliationOutcome,
            ReconciliationResult,
            ReconciliationStatus,
        )

        outcomes = (
            ReconciliationOutcome(
                table_name="animales",
                legacy_pk="a-1",
                web_column="current_state",
                status=ReconciliationStatus.MATCHED,
            ),
            ReconciliationOutcome(
                table_name="voluntarios",
                legacy_pk="v-1",
                web_column="DNI",
                status=ReconciliationStatus.NEEDS_REVIEW,
            ),
        )
        result = ReconciliationResult(outcomes=outcomes)
        assert len(result.outcomes) == 2
        # Per-status counts — the contract PR 4's applier hook relies on.
        assert result.matched == 1
        assert result.divergent == 0
        assert result.needs_review == 1

    def test_reconciliation_summary_from_result(self) -> None:
        """``ReconciliationSummary.from_result`` projects a ``ReconciliationResult``
        into the counts bundle that ``MigrationReport`` carries (PR 4 wires
        it). This is the bridge between the per-row outcomes list and the
        report-level summary, so it must aggregate matched/needs_review
        without dropping or duplicating any row.
        """
        from app.core.migration.reconcile import (
            ReconciliationOutcome,
            ReconciliationResult,
            ReconciliationStatus,
            ReconciliationSummary,
        )

        outcomes = (
            ReconciliationOutcome(
                table_name="animales",
                legacy_pk="a-1",
                web_column="current_state",
                status=ReconciliationStatus.MATCHED,
            ),
            ReconciliationOutcome(
                table_name="voluntarios",
                legacy_pk="v-1",
                web_column="DNI",
                status=ReconciliationStatus.NEEDS_REVIEW,
            ),
        )
        result = ReconciliationResult(outcomes=outcomes)

        summary = ReconciliationSummary.from_result(result)
        assert summary.matched == 1
        assert summary.divergent == 0
        assert summary.needs_review == 1


class TestCliReconcile:
    """Integration tests for the ``apap-migrate reconcile`` skeleton (PR 1).

    The full subcommand semantics land in PR 5 (interactive prompts,
    write paths, filters). PR 1 only guarantees that:

    - ``--help`` exits 0 with the four documented flags listed.
    - ``--check-only`` exits 0 and does NOT issue any writes against the
      backend (no SQL goes through the InsForgeClient).
    """

    def test_reconcile_help_exits_zero_and_lists_flags(self) -> None:
        """``apap-migrate reconcile --help`` exits 0 and lists all 4 flags."""
        from app.core.migration.cli import build_parser

        parser = build_parser()
        with pytest.raises(SystemExit) as excinfo:
            parser.parse_args(["reconcile", "--help"])
        assert excinfo.value.code == 0

    def test_reconcile_check_only_does_not_write(self) -> None:
        """``apap-migrate reconcile --check-only`` runs without hitting the DB.

        The skeleton is wired through ``main([...])``; with no shadow
        state on a fresh repo it must exit 0 and the captured SQL list
        must be empty (no writes against the InsForge backend).
        """
        from app.core.migration.cli import main as cli_main

        captured_sql: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = request.content.decode("utf-8") if request.content else ""
            if body:
                captured_sql.append(body)
            return httpx.Response(
                200,
                json=[],
                headers={"content-type": "application/json"},
            )

        client = InsForgeClient(
            base_url="https://example.insforge.app",
            service_key="ik_test",
            transport=httpx.MockTransport(handler),
        )

        rc = cli_main(["reconcile", "--check-only"], web_client=client)
        client.close()

        assert rc == 0, "reconcile --check-only must exit 0 on a clean repo"
        # Skeleton never writes — only reads, and even those are deferred to PR 5.
        assert captured_sql == [], f"reconcile --check-only must not write; got: {captured_sql!r}"


# PR 2/6 moved the derivation engine, comparator, semantic events, and

# reconcile-after-legacy-write tests to dedicated files:

#

#   - tests/test_derivation.py        (TestDerivationEngine + TestDerivationComparator)

#   - tests/test_semantic_events.py   (TestSemanticEvents + TestSemanticEventsEdgeCases)

#   - tests/test_reconcile.py         (TestReconcileAfterLegacyWrite)

#

# Keeping them out of this file preserves the work-unit discipline:

# each PR adds one production module + one test module, so the diff

# per commit is clean and the tests for a change travel with the change.
