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
from datetime import datetime as _dt  # alias local para los tests de diff/conflict
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from migration import (
    FkLookupError,
    LockActiveError,
    MappingNotFoundError,
    MigrationError,
    MigrationReport,
)
from migration.mappings import (
    ColumnMapping,
    FkLookup,
    TableMapping,
    list_available_tables,
    load_mapping,
)
from migration.reporting import Conflict, Diff
from tests.sql_executor_fake import HandlerSqlExecutor

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
    # Diff shape extendida en PR 4/6 (T5 — diff engine): se agregaron
    # ``table``, ``legacy_pk``, ``web_pk``, ``conflict``, ``reason``.
    # El sample no los popula, así que caen a sus defaults.
    assert payload["diffs"] == [
        {
            "op": "INSERT",
            "key": "animal-001",
            "table": "",
            "legacy_pk": None,
            "web_pk": None,
            "legacy_row": {"NCHIP": "001"},
            "web_row": {"NCHIP": "001"},
            "changed_fields": ["NombreAnimal"],
            "conflict": False,
            "reason": "",
        },
        {
            "op": "UPDATE",
            "key": "animal-002",
            "table": "",
            "legacy_pk": None,
            "web_pk": None,
            "legacy_row": {"NCHIP": "001"},
            "web_row": {"NCHIP": "001"},
            "changed_fields": ["NombreAnimal"],
            "conflict": False,
            "reason": "",
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
    """``python -m migration --help`` is a valid entry point.

    After PR 1 of web-only-feature-preservation, the CLI has a real
    argparse parser with a ``reconcile`` subcommand, so invoking
    ``python -m migration`` without a subcommand now exits
    non-zero (argparse ``required=True``). ``--help`` exits 0 and lists
    the available subcommands.
    """
    result = subprocess.run(
        [sys.executable, "-m", "migration", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"python -m migration --help exited {result.returncode}\n"
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
        from migration.mappings import (
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
        from migration.mappings import load_mapping

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
        from migration import mappings as mappings_module

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
# ``LocalPostgresExecutor`` (mockeable con ``httpx.MockTransport``). Ambos
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

        from migration.legacy_reader import (
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

        from migration.legacy_reader import (
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
        from migration.legacy_reader import set_legacy_query_executor

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

        from migration.legacy_reader import (
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
        from migration.legacy_reader import (
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
    """Tests para ``migration.application.web_reader.load_web_snapshot``.

    La hexagonal slice (``refactor/hexagonal-slice-migration-web``)
    mueve el read-side a ``migration/application/web_reader/`` con
    un Protocol port y un adapter LocalBackend. Los tests siguen
    importando ``WebTableSpec`` + ``load_web_snapshot`` desde el
    shim ``migration.web_reader`` (backwards compat), pero el
    cliente ahora se inyecta via :class:`WebReaderPort`
    (concretamente el :class:`LocalBackendWebReaderAdapter`) en lugar
    del :class:`LocalPostgresExecutor` raw — el Protocol port es el seam
    que oculta el transporte al use case.
    """

    def _make_mock_client(self, captured: list[str]) -> HandlerSqlExecutor:
        """Construye un SqlExecutor falso que captura el SQL enviado."""

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request.content.decode())
            return httpx.Response(
                200,
                json=[{"id": "uuid-1", "NCHIP": "ABC"}],
                headers={"content-type": "application/json"},
            )

        return HandlerSqlExecutor(
            base_url="https://example.local_backend.app",
            service_key="ik_test",
            transport=httpx.MockTransport(handler),
        )

    def test_returns_dict_with_web_table_names_as_keys(self) -> None:
        """El snapshot retorna ``dict[str, list[dict]]`` con nombres web como keys."""
        captured: list[str] = []
        client = self._make_mock_client(captured)

        from migration.adapters.local_backend.web_reader_local_backend_adapter import (
            LocalBackendWebReaderAdapter,
        )

        from migration.web_reader import WebTableSpec, load_web_snapshot

        port = LocalBackendWebReaderAdapter(client)

        result = load_web_snapshot(
            port,
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

        from migration.adapters.local_backend.web_reader_local_backend_adapter import (
            LocalBackendWebReaderAdapter,
        )

        from migration.web_reader import WebTableSpec, load_web_snapshot

        since = datetime(2026, 6, 20, 10, 0)
        port = LocalBackendWebReaderAdapter(client)

        load_web_snapshot(
            port,
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

        client = HandlerSqlExecutor(
            base_url="https://example.local_backend.app",
            service_key="ik_test",
            transport=httpx.MockTransport(handler),
        )

        from migration.adapters.local_backend.web_reader_local_backend_adapter import (
            LocalBackendWebReaderAdapter,
        )

        from migration.web_reader import WebTableSpec, load_web_snapshot

        port = LocalBackendWebReaderAdapter(client)

        result = load_web_snapshot(
            port,
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
        from migration.reconcile import ReconciliationStatus

        for value in ("matched", "divergent", "needs_review", "pending", "migrated"):
            assert ReconciliationStatus(value) == value

    def test_reconciliation_outcome_holds_status_and_reasons(self) -> None:
        """ReconciliationOutcome is a dataclass with the documented fields."""
        from migration.reconcile import (
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
        from migration.reconcile import (
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
        from migration.reconcile import (
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


# --- TestMigrationReportReconciliationSummary -----------------------------
#
# Slice PR 4/6 of web-only-feature-preservation (T4.6): wire
# ``ReconciliationSummary`` onto ``MigrationReport`` so the applier
# (MIGRATION-01 PR 5/6) can attach the reconciliation verdict bundle
# the hook returns to the immutable migration report. The summary is
# ``None`` by default so MIGRATION-01 PR 1–3 (which don't run the hook
# yet) keep producing valid reports. Once the applier lands and wires
# the hook, the field becomes ``ReconciliationSummary(...)`` populated
# from ``ReconciliationResult.from_result()``.
#
# Tests verify:
#   - The field exists on ``MigrationReport`` (default ``None``).
#   - to_json() includes the field (serialized as ``null`` when unset).
#   - to_markdown() emits a "## Reconciliation" section when the
#     summary is set; omits it when ``None``.
#   - The summary is ``frozen=True`` (the report is immutable; the
#     summary must be too — see ``reporting.py::MigrationReport``).


class TestMigrationReportReconciliationSummary:
    """Tests for ``MigrationReport.reconciliation_summary`` (PR 4/6 — T4.6)."""

    def test_reconciliation_summary_defaults_to_none(self) -> None:
        """A freshly-built MigrationReport has ``reconciliation_summary=None``.

        Pre-PR 4 reports (MIGRATION-01 PR 1–3) keep working because the
        field is optional. The applier (MIGRATION-01 PR 5/6) sets it
        after running ``post_apply_diff``.
        """
        report = _sample_report()
        assert hasattr(report, "reconciliation_summary"), (
            "MigrationReport must expose a reconciliation_summary field "
            "(T4.6 of web-only-feature-preservation PR 4/6)"
        )
        assert report.reconciliation_summary is None

    def test_reconciliation_summary_is_set_when_applied(self) -> None:
        """The applier can attach a populated ``ReconciliationSummary``.

        Wire-up smoke test: build a report with a non-None summary and
        assert the field carries the count bundle without mutation
        (``MigrationReport`` is ``frozen=True``).
        """
        from migration.reconcile import ReconciliationSummary

        summary = ReconciliationSummary(matched=10, divergent=2, needs_review=1)
        report = dataclasses.replace(_sample_report(), reconciliation_summary=summary)
        assert report.reconciliation_summary is summary
        assert report.reconciliation_summary.matched == 10
        assert report.reconciliation_summary.divergent == 2
        assert report.reconciliation_summary.needs_review == 1

    def test_reconciliation_summary_to_json_is_serializable(self) -> None:
        """``to_json`` includes ``reconciliation_summary`` as a JSON object.

        The summary dataclass is plain (no nested datetimes) so it
        serializes via ``asdict`` without needing the ``default``
        encoder. ``None`` must serialize as JSON ``null`` so the field
        stays self-describing across the wire.
        """
        from migration.reconcile import ReconciliationSummary

        report_with = dataclasses.replace(
            _sample_report(),
            reconciliation_summary=ReconciliationSummary(matched=10, divergent=2, needs_review=1),
        )
        report_without = _sample_report()

        payload_with = json.loads(report_with.to_json())
        payload_without = json.loads(report_without.to_json())

        assert "reconciliation_summary" in payload_with, (
            "to_json() must include reconciliation_summary when set"
        )
        assert payload_with["reconciliation_summary"] == {
            "matched": 10,
            "divergent": 2,
            "needs_review": 1,
            "errors": [],
        }
        # When unset, the field serializes as JSON null (self-describing
        # rather than omitted — keeps the schema explicit).
        assert payload_without["reconciliation_summary"] is None

    def test_reconciliation_summary_to_markdown_renders_when_set(self) -> None:
        """``to_markdown`` emits a ``## Reconciliation`` section when the
        summary is set, with the exact count rows.

        Regression guard so the operator-facing report shows the
        reconciliation verdict bundle next to the diff metrics.
        """
        from migration.reconcile import ReconciliationSummary

        report = dataclasses.replace(
            _sample_report(),
            reconciliation_summary=ReconciliationSummary(matched=10, divergent=2, needs_review=1),
        )
        md = report.to_markdown()
        assert "## Reconciliation" in md, (
            "to_markdown() must emit a Reconciliation section when the summary is set; got: " + md
        )
        # Per-status rows are exact (matches the metrics table style).
        assert "| Matched | 10 |" in md
        assert "| Divergent | 2 |" in md
        assert "| Needs review | 1 |" in md

    def test_reconciliation_summary_to_markdown_omits_when_none(self) -> None:
        """``to_markdown`` does NOT emit a ``## Reconciliation`` section
        when the summary is ``None`` (MIGRATION-01 PR 1–3 reports).

        Backward compat: pre-PR 4 reports don't have the field; their
        markdown output must stay free of an empty section header.
        """
        report = _sample_report()
        assert report.reconciliation_summary is None
        md = report.to_markdown()
        assert "## Reconciliation" not in md


class TestCliReconcile:
    """Integration tests for the ``apap-migrate reconcile`` skeleton (PR 1)
    + the read path that PR 5 added.

    PR 1 only guaranteed that ``--help`` lists the four documented
    flags and that ``--check-only`` exits 0. PR 5 fills in the read
    path (``list_needs_review`` is now a real SELECT, no longer a
    stub) but keeps the no-write invariant for ``--check-only``
    (the operator must explicitly pass ``--interactive`` to issue
    ``UPDATE`` / ``INSERT`` SQL). The full interactive / write-path
    coverage lives in ``tests/test_migration_cli.py``.
    """

    def test_reconcile_help_exits_zero_and_lists_flags(self) -> None:
        """``apap-migrate reconcile --help`` exits 0 and lists all 4 flags."""
        from migration.cli import build_parser

        parser = build_parser()
        with pytest.raises(SystemExit) as excinfo:
            parser.parse_args(["reconcile", "--help"])
        assert excinfo.value.code == 0

    def test_reconcile_check_only_does_not_write(self) -> None:
        """``apap-migrate reconcile --check-only`` runs end-to-end and
        never issues a write SQL (``UPDATE`` / ``INSERT`` / ``DELETE``).

        PR 5 added a real read path (``ShadowStateRepository.list_needs_review``
        issues one ``SELECT`` against ``web_only_feature_shadow``), so
        the captured SQL list is NOT empty anymore — but it is still
        pure-SELECT. The invariant this test guards is the no-write
        promise: ``--check-only`` is the safe default for unattended
        monitoring / cron jobs, and the operator must opt in to
        ``--interactive`` to mutate the database.
        """
        from migration.cli import main as cli_main

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

        client = HandlerSqlExecutor(
            base_url="https://example.local_backend.app",
            service_key="ik_test",
            transport=httpx.MockTransport(handler),
        )

        rc = cli_main(["reconcile", "--check-only"], web_client=client)
        client.close()

        assert rc == 0, "reconcile --check-only must exit 0 on a clean repo"
        # PR 5 invariant: --check-only never issues a write. The
        # SELECT against web_only_feature_shadow is the only statement
        # the operator should see.
        for body in captured_sql:
            upper = body.upper()
            assert "INSERT" not in upper, f"--check-only must not INSERT; got: {body!r}"
            assert "UPDATE" not in upper, f"--check-only must not UPDATE; got: {body!r}"
            assert "DELETE" not in upper, f"--check-only must not DELETE; got: {body!r}"


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

# --- TestSyncState --------------------------------------------------------
#
# Slice MIGRATION-01 PR 4/6 (T7): ``app/core/migration/sync_state.py``
# implementa la persistencia del estado del sync para soportar sync
# incremental. El estado es un JSON en disco que guarda, por tabla:
#
# - ``last_sync_at``: cuándo terminó el último sync de esa tabla.
# - ``legacy_to_web_id``: mapping ``str(legacy_pk) -> web_uuid`` para
#   tablas sin natural key (entradas/acogidas/adopciones usan el
#   ``IdEntrada`` legacy como PK y el ``id`` UUID como clave web).
#
# Garantías clave:
# - Escritura atómica (write-then-rename vía ``os.replace``) para no
#   corromper el JSON si el proceso muere a mitad (regla #13474 v2:
#   función de migración atómica — el sync_state es la pieza que
#   permite reintentar).
# - File not found → estado vacío (NO falla; primer run legítimo).
# - JSON malformado → ``SyncStateError`` (operador debe mirar).
# - Lookups por legacy_pk y web_pk retornan ``None`` en miss (no raise).


class TestSyncState:
    """Tests para ``migration.sync_state`` (PR 4/6 — T7)."""

    # --- dataclass shape -----------------------------------------------

    def test_sync_state_default_construction(self) -> None:
        """``SyncState()`` produce un estado vacío (tables={}, version='1.0')."""
        from migration.sync_state import SyncState

        state = SyncState()
        assert state.version == "1.0"
        assert state.tables == {}

    def test_table_state_default_construction(self) -> None:
        """``TableState()`` produce una tabla vacía (last_sync_at=None, mapping={})."""
        from migration.sync_state import TableState

        ts = TableState()
        assert ts.last_sync_at is None
        assert ts.legacy_to_web_id == {}

    def test_table_state_is_immutable_mapping(self) -> None:
        """``TableState.legacy_to_web_id`` es un dict[str, str] editable (no frozen)."""
        from migration.sync_state import TableState

        ts = TableState()
        ts.legacy_to_web_id["42"] = "uuid-42"
        assert ts.legacy_to_web_id["42"] == "uuid-42"

    # --- load_sync_state -----------------------------------------------

    def test_load_sync_state_missing_file_returns_empty(self, tmp_path) -> None:
        """load_sync_state sobre path inexistente devuelve SyncState() vacío (NO falla)."""
        from migration.sync_state import load_sync_state

        state = load_sync_state(tmp_path / "does-not-exist.json")
        assert state.tables == {}
        assert state.version == "1.0"

    def test_load_sync_state_round_trip(self, tmp_path) -> None:
        """load → save → load preserva todos los campos del estado."""
        from migration.sync_state import (
            SyncState,
            TableState,
            load_sync_state,
            save_sync_state,
        )

        path = tmp_path / "sync_state.json"
        original = SyncState(
            version="1.0",
            tables={
                "animales": TableState(
                    last_sync_at=_dt(2026, 6, 20, 12, 0, 0),
                    legacy_to_web_id={"001": "uuid-001"},
                ),
            },
        )
        save_sync_state(original, path)
        reloaded = load_sync_state(path)
        assert reloaded == original

    def test_load_sync_state_corrupted_json_raises(self, tmp_path) -> None:
        """load_sync_state sobre JSON malformado levanta ``SyncStateError``."""
        from migration.sync_state import SyncStateError, load_sync_state

        path = tmp_path / "bad.json"
        path.write_text("{ this is not valid json", encoding="utf-8")
        with pytest.raises(SyncStateError):
            load_sync_state(path)

    # --- save_sync_state atomicity -------------------------------------

    def test_save_sync_state_writes_atomically(self, tmp_path) -> None:
        """save_sync_state no deja archivos ``.tmp`` parciales al terminar OK.

        Implementación: escribe a ``sync_state.json.tmp`` y luego
        ``os.replace(tmp, target)``. Después del replace, NO debe quedar
        un ``.tmp`` huérfano (la atómica es la rename).
        """
        from migration.sync_state import SyncState, save_sync_state

        path = tmp_path / "sync_state.json"
        save_sync_state(SyncState(), path)
        leftover = list(tmp_path.glob("*.tmp"))
        assert leftover == [], f"Atomic write left tmp files: {leftover}"

    def test_save_sync_state_creates_parent_dirs(self, tmp_path) -> None:
        """save_sync_state crea el directorio padre si no existe."""
        from migration.sync_state import SyncState, save_sync_state

        nested = tmp_path / "a" / "b" / "sync_state.json"
        save_sync_state(SyncState(), nested)
        assert nested.exists()

    # --- get_or_create_table_state -------------------------------------

    def test_get_or_create_table_state_creates_on_miss(self) -> None:
        """get_or_create_table_state crea la TableState si la tabla no existe."""
        from migration.sync_state import (
            SyncState,
            TableState,
            get_or_create_table_state,
        )

        state = SyncState()
        ts = get_or_create_table_state(state, "animales")
        assert isinstance(ts, TableState)
        assert "animales" in state.tables
        # Idempotencia: segunda llamada devuelve la misma TableState.
        ts2 = get_or_create_table_state(state, "animales")
        assert ts2 is ts

    # --- legacy↔web mapping helpers ------------------------------------

    def test_record_legacy_to_web_mapping_round_trip(self) -> None:
        """record_legacy_to_web_mapping persiste el mapping (consultable luego)."""
        from migration.sync_state import (
            SyncState,
            lookup_legacy_pk,
            lookup_web_pk,
            record_legacy_to_web_mapping,
        )

        state = SyncState()
        record_legacy_to_web_mapping(state, "entradas", 42, "uuid-42")

        assert lookup_web_pk(state, "entradas", 42) == "uuid-42"
        assert lookup_legacy_pk(state, "entradas", "uuid-42") == 42

    def test_lookup_web_pk_returns_none_on_miss(self) -> None:
        """lookup_web_pk retorna ``None`` cuando no hay mapping (no raise)."""
        from migration.sync_state import SyncState, lookup_web_pk

        state = SyncState()
        assert lookup_web_pk(state, "animales", 999) is None

    def test_lookup_legacy_pk_returns_none_on_miss(self) -> None:
        """lookup_legacy_pk retorna ``None`` cuando no hay mapping (no raise)."""
        from migration.sync_state import SyncState, lookup_legacy_pk

        state = SyncState()
        assert lookup_legacy_pk(state, "animales", "uuid-missing") is None

    def test_record_legacy_to_web_mapping_coerces_to_string(self) -> None:
        """record_legacy_to_web_mapping coacciona legacy_pk a str (lookup key).

        Importante: ``legacy_pk`` puede venir como ``int`` (legacy pk
        nativo de Access) pero el mapping se guarda con key ``str``.
        El lookup también acepta ``int`` y lo coacciona antes de
        consultar el dict (regla del design §4).
        """
        from migration.sync_state import (
            SyncState,
            lookup_web_pk,
            record_legacy_to_web_mapping,
        )

        state = SyncState()
        record_legacy_to_web_mapping(state, "entradas", 7, "uuid-7")
        # Lookup con int debe encontrar el mapping.
        assert lookup_web_pk(state, "entradas", 7) == "uuid-7"
        # Y el dict interno usa str como key.
        assert state.tables["entradas"].legacy_to_web_id["7"] == "uuid-7"

    # --- update_last_sync_at -------------------------------------------

    def test_update_last_sync_at_sets_field(self) -> None:
        """update_last_sync_at popula ``last_sync_at`` de la tabla indicada."""
        from migration.sync_state import (
            SyncState,
            update_last_sync_at,
        )

        state = SyncState()
        ts = _dt(2026, 6, 21, 14, 30, 0)
        update_last_sync_at(state, "animales", ts)
        assert state.tables["animales"].last_sync_at == ts

    # --- JSON shape on disk --------------------------------------------

    def test_save_writes_canonical_json_shape(self, tmp_path) -> None:
        """save_sync_state produce JSON con la forma canónica (version, tables)."""
        from migration.sync_state import SyncState, save_sync_state

        path = tmp_path / "sync_state.json"
        save_sync_state(SyncState(), path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert "version" in raw
        assert "tables" in raw
        assert raw["version"] == "1.0"
        assert raw["tables"] == {}

    def test_multi_table_state_round_trip(self, tmp_path) -> None:
        """Round-trip con múltiples tablas preserva TODAS las tablas (no overwrite)."""
        from migration.sync_state import (
            SyncState,
            load_sync_state,
            record_legacy_to_web_mapping,
            save_sync_state,
            update_last_sync_at,
        )

        path = tmp_path / "sync_state.json"
        state = SyncState()
        # Animales: mapping + last_sync.
        record_legacy_to_web_mapping(state, "animales", "001", "uuid-001")
        update_last_sync_at(state, "animales", _dt(2026, 6, 20, 12, 0, 0))
        # Entradas: mapping only.
        record_legacy_to_web_mapping(state, "entradas", 42, "uuid-42")

        save_sync_state(state, path)
        reloaded = load_sync_state(path)

        # Las dos tablas pobladas deben sobrevivir el round-trip; el
        # sync_state nunca debe sobreescribir una tabla con la info de
        # otra (regla #13474 v2: el sync_state es el contrato durable
        # entre runs).
        assert set(reloaded.tables) == {"animales", "entradas"}
        assert reloaded.tables["animales"].last_sync_at == _dt(2026, 6, 20, 12, 0, 0)
        assert reloaded.tables["animales"].legacy_to_web_id == {"001": "uuid-001"}
        assert reloaded.tables["entradas"].legacy_to_web_id == {"42": "uuid-42"}
        assert reloaded.tables["entradas"].last_sync_at is None

    def test_get_or_create_preserves_existing_last_sync_at(self) -> None:
        """get_or_create NO resetea ``last_sync_at`` si la tabla ya existe.

        Importante para no introducir un bug silencioso: si el applier
        llama ``get_or_create_table_state`` antes de update_last_sync_at,
        el ``last_sync_at`` previo debe sobrevivir (de lo contrario
        perderíamos el cursor del incremental sync en cada re-run).
        """
        from migration.sync_state import (
            SyncState,
            get_or_create_table_state,
            update_last_sync_at,
        )

        state = SyncState()
        update_last_sync_at(state, "animales", _dt(2026, 6, 15, 0, 0, 0))

        # Llamada idempotente — no debe clonar la TableState.
        ts = get_or_create_table_state(state, "animales")
        assert ts.last_sync_at == _dt(2026, 6, 15, 0, 0, 0)

    def test_lookup_web_pk_coerces_string_legacy_pk(self) -> None:
        """lookup_web_pk acepta ``str`` para legacy_pk (consistente con record_)."""
        from migration.sync_state import (
            SyncState,
            lookup_web_pk,
            record_legacy_to_web_mapping,
        )

        state = SyncState()
        record_legacy_to_web_mapping(state, "animales", "001", "uuid-001")
        # Pasamos str en vez de int — debe encontrar el mapping.
        assert lookup_web_pk(state, "animales", "001") == "uuid-001"


# --- TestDiffEngine -------------------------------------------------------
#
# Slice MIGRATION-01 PR 4/6 (T5): ``app/core/migration/diff_engine.py``
# clasifica cada fila en INSERT/UPDATE/DELETE/NOOP comparando el
# snapshot legacy contra el snapshot web (o viceversa). Detecta
# conflictos ``modified_both_sides`` cuando AMBAS partes cambiaron
# desde el ``last_sync_at``.
#
# Reglas operativas:
# - animales + voluntarios: match por natural key (NCHIP / Voluntario).
# - entradas/acogidas/adopciones: match por ``sync_state`` mapping
#   legacy_id ↔ web_uuid (no tienen natural key compartido).
# - ``updated_at`` en web + ``date_fields`` en legacy (YAML) proveen
#   las fechas candidatas para ``modified_both_sides``.
# - ``ignore_fields`` (ej: ``updated_at``) no genera UPDATE si solo
#   cambia ese campo.
#
# Esta sección NO toca readers ni applier — es lógica pura con
# snapshots ``dict[str, list[dict]]`` ya materializados.


class TestDiffEngine:
    """Tests para ``migration.diff_engine`` (PR 4/6 — T5)."""

    # --- helpers -------------------------------------------------------

    @staticmethod
    def _animal_mapping():
        """Mapping sintético para animales (key=NCHIP)."""
        from migration.mappings import TableMapping

        return TableMapping.model_validate(
            {
                "web_table": "animales",
                "legacy_table": "TbFichaAnimal",
                "key_field": "NCHIP",
                "legacy_key": "NCHIP",
                "date_fields": ["FIMPLANTACIONCHIP", "FDefuncion"],
                "columns": [],
                "fk_lookups": [],
            }
        )

    @staticmethod
    def _entrada_mapping():
        """Mapping sintético para entradas (key=IDEntrada legacy → id web)."""
        from migration.mappings import TableMapping

        return TableMapping.model_validate(
            {
                "web_table": "entradas",
                "legacy_table": "TbEntradas",
                "key_field": "id",
                "legacy_key": "IDEntrada",
                "date_fields": ["FechaEntrada", "FSalida"],
                "columns": [],
                "fk_lookups": [],
            }
        )

    # --- INSERT (legacy tiene, web no) ---------------------------------

    def test_diff_legacy_to_web_inserts_new_legacy_rows(self) -> None:
        """Filas solo en legacy → INSERT al web."""
        from migration.diff_engine import diff_legacy_to_web
        from migration.sync_state import SyncState

        legacy = {"animales": [{"NCHIP": "001", "NombreAnimal": "Rex"}]}
        web: dict = {"animales": []}
        sync_state = SyncState()

        diffs = diff_legacy_to_web(legacy, web, self._animal_mapping(), sync_state)
        assert len(diffs) == 1
        assert diffs[0].op == "INSERT"
        assert diffs[0].legacy_pk == "001"
        assert diffs[0].web_pk is None

    # --- DELETE (web tiene, legacy no) ---------------------------------

    def test_diff_legacy_to_web_deletes_missing_legacy_rows(self) -> None:
        """Filas solo en web (legacy ya no las tiene) → DELETE en web.

        CUIDADO: en producción el DELETE requiere ``--delete-orphans``
        (regla #13474 v2: nunca borrar datos sin confirmación). El
        diff engine las clasifica como DELETE para que el applier las
        pueda skipear si el flag no está activo. Aquí solo verificamos
        la clasificación.
        """
        from migration.diff_engine import diff_legacy_to_web
        from migration.sync_state import SyncState

        legacy: dict = {"animales": []}
        web = {"animales": [{"id": "uuid-001", "NCHIP": "001"}]}
        sync_state = SyncState()

        diffs = diff_legacy_to_web(legacy, web, self._animal_mapping(), sync_state)
        assert len(diffs) == 1
        assert diffs[0].op == "DELETE"

    # --- NOOP ----------------------------------------------------------

    def test_diff_legacy_to_web_noop_when_identical(self) -> None:
        """Misma fila en ambos lados, sin cambios → NOOP (no UPDATE)."""
        from migration.diff_engine import diff_legacy_to_web
        from migration.sync_state import SyncState

        legacy = {
            "animales": [
                {
                    "NCHIP": "001",
                    "NombreAnimal": "Rex",
                    "updated_at": "2026-06-01T00:00:00",
                }
            ]
        }
        web = {
            "animales": [
                {
                    "id": "uuid-001",
                    "NCHIP": "001",
                    "NombreAnimal": "Rex",
                    "updated_at": "2026-06-01T00:00:00",
                }
            ]
        }
        sync_state = SyncState()

        diffs = diff_legacy_to_web(legacy, web, self._animal_mapping(), sync_state)
        assert len(diffs) == 1
        assert diffs[0].op == "NOOP"

    # --- UPDATE --------------------------------------------------------

    def test_diff_legacy_to_web_updates_when_field_changes(self) -> None:
        """Mismo NCHIP, distinto NombreAnimal → UPDATE con changed_fields."""
        from migration.diff_engine import diff_legacy_to_web
        from migration.sync_state import SyncState

        legacy = {"animales": [{"NCHIP": "001", "NombreAnimal": "Rex-NEW"}]}
        web = {"animales": [{"id": "uuid-001", "NCHIP": "001", "NombreAnimal": "Rex-OLD"}]}
        sync_state = SyncState()

        diffs = diff_legacy_to_web(legacy, web, self._animal_mapping(), sync_state)
        assert len(diffs) == 1
        diff = diffs[0]
        assert diff.op == "UPDATE"
        assert diff.legacy_pk == "001"
        assert diff.web_pk == "uuid-001"
        assert "NombreAnimal" in diff.changed_fields

    # --- ignore_fields -------------------------------------------------

    def test_diff_legacy_to_web_ignores_updated_at(self) -> None:
        """Si solo cambia ``updated_at`` (no dato de negocio), el diff es NOOP.

        El applier reescribe ``updated_at`` en cada write, por lo que
        comparar ese campo siempre daría UPDATE → falsa señal de
        cambio. El diff engine debe ignorarlo por default.
        """
        from migration.diff_engine import diff_legacy_to_web
        from migration.sync_state import SyncState

        legacy = {
            "animales": [
                {
                    "NCHIP": "001",
                    "NombreAnimal": "Rex",
                    "updated_at": "2026-06-21T12:00:00",
                }
            ]
        }
        web = {
            "animales": [
                {
                    "id": "uuid-001",
                    "NCHIP": "001",
                    "NombreAnimal": "Rex",
                    "updated_at": "2026-06-20T00:00:00",
                }
            ]
        }
        sync_state = SyncState()

        diffs = diff_legacy_to_web(legacy, web, self._animal_mapping(), sync_state)
        assert len(diffs) == 1
        assert diffs[0].op == "NOOP"

    # --- modified_both_sides conflict ----------------------------------

    def test_diff_detects_modified_both_sides_conflict(self) -> None:
        """Si legacy.updated > last_sync_at Y web.updated > last_sync_at → conflicto."""
        from migration.diff_engine import diff_legacy_to_web
        from migration.sync_state import (
            SyncState,
            update_last_sync_at,
        )

        last_sync = _dt(2026, 6, 15, 0, 0, 0)
        legacy = {
            "animales": [
                {
                    "NCHIP": "001",
                    "NombreAnimal": "Rex-LEGACY",
                    "FIMPLANTACIONCHIP": _dt(2026, 6, 20, 0, 0, 0),
                }
            ]
        }
        web = {
            "animales": [
                {
                    "id": "uuid-001",
                    "NCHIP": "001",
                    "NombreAnimal": "Rex-WEB",
                    "updated_at": _dt(2026, 6, 18, 0, 0, 0),
                }
            ]
        }
        sync_state = SyncState()
        update_last_sync_at(sync_state, "animales", last_sync)

        diffs = diff_legacy_to_web(legacy, web, self._animal_mapping(), sync_state)
        assert len(diffs) == 1
        diff = diffs[0]
        # El diff engine marca la fila con conflict=True y clasifica la
        # op como UPDATE (la intención del applier si el operador
        # resuelve con --conflict web|legacy), pero el operador decide
        # vía ``--conflict abort`` antes de aplicar.
        assert diff.conflict is True
        assert diff.op == "UPDATE"

    def test_diff_no_conflict_when_only_one_side_changed(self) -> None:
        """Si SOLO el legacy cambió → no hay conflict (aplica UPDATE)."""
        from migration.diff_engine import diff_legacy_to_web
        from migration.sync_state import (
            SyncState,
            update_last_sync_at,
        )

        last_sync = _dt(2026, 6, 15, 0, 0, 0)
        legacy = {
            "animales": [
                {
                    "NCHIP": "001",
                    "NombreAnimal": "Rex-NEW",
                    "FIMPLANTACIONCHIP": _dt(2026, 6, 20, 0, 0, 0),
                }
            ]
        }
        web = {
            "animales": [
                {
                    "id": "uuid-001",
                    "NCHIP": "001",
                    "NombreAnimal": "Rex-OLD",
                    "updated_at": _dt(2026, 6, 10, 0, 0, 0),
                }
            ]
        }
        sync_state = SyncState()
        update_last_sync_at(sync_state, "animales", last_sync)

        diffs = diff_legacy_to_web(legacy, web, self._animal_mapping(), sync_state)
        assert len(diffs) == 1
        assert diffs[0].conflict is False
        assert diffs[0].op == "UPDATE"

    # --- entradas/acogidas/adopciones match by sync_state --------------

    def test_diff_entradas_matches_by_sync_state_mapping(self) -> None:
        """Para entradas (sin natural key), el match es legacy_id ↔ web_uuid via sync_state."""
        from migration.diff_engine import diff_legacy_to_web
        from migration.sync_state import (
            SyncState,
            record_legacy_to_web_mapping,
        )

        legacy = {
            "entradas": [
                {
                    "IDEntrada": 42,
                    "FechaEntrada": "2026-06-01",
                    "motivo": "abandono",
                }
            ]
        }
        web = {
            "entradas": [
                {
                    "id": "uuid-42",
                    "fecha_entrada": "2026-06-01",
                    "motivo": "abandono",
                }
            ]
        }
        sync_state = SyncState()
        record_legacy_to_web_mapping(sync_state, "entradas", 42, "uuid-42")

        diffs = diff_legacy_to_web(legacy, web, self._entrada_mapping(), sync_state)
        assert len(diffs) == 1
        assert diffs[0].op == "NOOP"

    def test_diff_entradas_insert_when_no_mapping_for_legacy_pk(self) -> None:
        """Si legacy tiene una fila sin mapping en sync_state → INSERT al web."""
        from migration.diff_engine import diff_legacy_to_web
        from migration.sync_state import SyncState

        legacy = {"entradas": [{"IDEntrada": 99, "FechaEntrada": "2026-06-01"}]}
        web: dict = {"entradas": []}
        sync_state = SyncState()  # vacía — sin mapping

        diffs = diff_legacy_to_web(legacy, web, self._entrada_mapping(), sync_state)
        assert len(diffs) == 1
        assert diffs[0].op == "INSERT"
        assert diffs[0].legacy_pk == 99

    # --- inverse direction ---------------------------------------------

    def test_diff_web_to_legacy_classifies_inserts(self) -> None:
        """diff_web_to_legacy clasifica INSERTs para filas web sin contraparte legacy."""
        from migration.diff_engine import diff_web_to_legacy

        legacy: dict = {"animales": []}
        web = {"animales": [{"id": "uuid-1", "NCHIP": "X1"}]}

        diffs = diff_web_to_legacy(web, legacy, self._animal_mapping())
        assert len(diffs) == 1
        assert diffs[0].op == "INSERT"

    def test_diff_web_to_legacy_classifies_deletes(self) -> None:
        """diff_web_to_legacy clasifica DELETEs para filas legacy sin contraparte web."""
        from migration.diff_engine import diff_web_to_legacy

        legacy = {"animales": [{"NCHIP": "X1", "NombreAnimal": "Rex"}]}
        web: dict = {"animales": []}

        diffs = diff_web_to_legacy(web, legacy, self._animal_mapping())
        assert len(diffs) == 1
        assert diffs[0].op == "DELETE"

    def test_diff_web_to_legacy_noop_on_identical(self) -> None:
        """diff_web_to_legacy NOOP cuando ambos lados coinciden."""
        from migration.diff_engine import diff_web_to_legacy

        legacy = {"animales": [{"NCHIP": "X1", "NombreAnimal": "Rex"}]}
        web = {"animales": [{"id": "uuid-1", "NCHIP": "X1", "NombreAnimal": "Rex"}]}

        diffs = diff_web_to_legacy(web, legacy, self._animal_mapping())
        assert len(diffs) == 1
        assert diffs[0].op == "NOOP"

    # --- mixed ops in one snapshot -------------------------------------

    def test_diff_classifies_each_row_independently(self) -> None:
        """Múltiples filas: cada una se clasifica independientemente."""
        from migration.diff_engine import diff_legacy_to_web
        from migration.sync_state import SyncState

        legacy = {
            "animales": [
                {"NCHIP": "A", "NombreAnimal": "Rex-A"},  # INSERT (no en web)
                {"NCHIP": "B", "NombreAnimal": "Rex-B-NEW"},  # UPDATE
                {"NCHIP": "C", "NombreAnimal": "Rex-C"},  # NOOP
            ]
        }
        web = {
            "animales": [
                {"id": "uuid-B", "NCHIP": "B", "NombreAnimal": "Rex-B-OLD"},
                {"id": "uuid-C", "NCHIP": "C", "NombreAnimal": "Rex-C"},
                {"id": "uuid-D", "NCHIP": "D", "NombreAnimal": "Rex-D"},  # DELETE
            ]
        }
        sync_state = SyncState()

        diffs = diff_legacy_to_web(legacy, web, self._animal_mapping(), sync_state)
        ops_by_chip = {d.legacy_pk: d.op for d in diffs}
        assert ops_by_chip["A"] == "INSERT"
        assert ops_by_chip["B"] == "UPDATE"
        assert ops_by_chip["C"] == "NOOP"
        assert ops_by_chip["D"] == "DELETE"
        assert len(diffs) == 4

    # --- empty snapshots -----------------------------------------------

    def test_diff_with_empty_snapshots_returns_empty(self) -> None:
        """Snapshots vacíos en ambos lados → lista vacía de diffs (sin errores)."""
        from migration.diff_engine import diff_legacy_to_web
        from migration.sync_state import SyncState

        diffs = diff_legacy_to_web(
            {"animales": []},
            {"animales": []},
            self._animal_mapping(),
            SyncState(),
        )
        assert diffs == []


# --- TestLock -------------------------------------------------------------
#
# Slice MIGRATION-01 PR 4/6 (T6): ``app/core/migration/lock.py``
# implementa el lock file con PID + timestamp + TTL + stale recovery.
# El lock previene runs concurrentes de migración (regla #13474 v2:
# función de migración atómica).
#
# Reglas operativas:
# - El lock file contiene ``{pid, acquired_at, ttl_seconds=1800}`` (JSON).
# - Si el proceso del PID ya no está vivo → stale → se sobrescribe.
# - Pre-flight: ``psutil.process_iter()`` para detectar ``MSACCESS.EXE``
#   activos (regla #13474 v2). Si Access está abierto y el destino es
#   legacy → warn (no abortar — depende del flag del CLI).
# - ``psutil`` es dependencia soft: si no está instalado, el pre-flight
#   es no-op y se loggea un warning.


class TestLock:
    """Tests para ``migration.lock`` (PR 4/6 — T6)."""

    # --- dataclass shape ----------------------------------------------

    def test_lock_info_default_construction(self) -> None:
        """LockInfo tiene pid, acquired_at, ttl_seconds (default 1800)."""
        from migration.lock import LockInfo

        info = LockInfo(pid=1234, acquired_at=_dt(2026, 6, 21, 0, 0, 0))
        assert info.pid == 1234
        assert info.ttl_seconds == 1800

    def test_lock_info_serializes_to_json(self) -> None:
        """LockInfo.to_json() produce JSON con la forma canónica (pid, acquired_at, ttl_seconds)."""
        from migration.lock import LockInfo

        info = LockInfo(pid=1234, acquired_at=_dt(2026, 6, 21, 0, 0, 0), ttl_seconds=900)
        raw = json.loads(info.to_json())
        assert raw["pid"] == 1234
        assert raw["ttl_seconds"] == 900
        assert "acquired_at" in raw

    # --- acquire + release round-trip ----------------------------------

    def test_acquire_lock_creates_file(self, tmp_path) -> None:
        """acquire_lock crea el lock file con JSON válido."""
        from migration.lock import acquire_lock, check_lock, release_lock

        lock_path = tmp_path / "sync.lock"
        try:
            acquire_lock(lock_path)
            assert lock_path.exists()
            info = check_lock(lock_path)
            assert info is not None
            assert info.pid == __import__("os").getpid()
        finally:
            release_lock(lock_path)

    def test_acquire_lock_blocks_when_active(self, tmp_path) -> None:
        """Segundo acquire_lock sobre lock activo → ``LockActiveError``."""
        from migration.lock import acquire_lock, release_lock

        lock_path = tmp_path / "sync.lock"
        try:
            acquire_lock(lock_path)
            with pytest.raises(LockActiveError):
                acquire_lock(lock_path)
        finally:
            release_lock(lock_path)

    def test_release_lock_removes_file(self, tmp_path) -> None:
        """release_lock borra el lock file (idempotente: missing → no raise)."""
        from migration.lock import acquire_lock, release_lock

        lock_path = tmp_path / "sync.lock"
        acquire_lock(lock_path)
        release_lock(lock_path)
        assert not lock_path.exists()
        # Idempotente.
        release_lock(lock_path)
        assert not lock_path.exists()

    # --- check_lock read-only ------------------------------------------

    def test_check_lock_returns_none_when_missing(self, tmp_path) -> None:
        """check_lock retorna ``None`` si el archivo no existe."""
        from migration.lock import check_lock

        assert check_lock(tmp_path / "missing.lock") is None

    # --- stale lock recovery -------------------------------------------

    def test_acquire_lock_recovers_from_stale_lock(self, tmp_path) -> None:
        """acquire_lock sobrescribe un lock cuyo PID ya no existe.

        Caso típico: el proceso dueño del lock murió (kill -9, OOM, etc.)
        dejando el archivo en disco. Si TTL expiró o el PID está muerto,
        acquire_lock debe sobrescribirlo sin raise.
        """
        from migration.lock import (
            LockInfo,
            acquire_lock,
            check_lock,
            release_lock,
        )

        lock_path = tmp_path / "sync.lock"
        # Simular un lock antiguo de un proceso muerto (PID 999999
        # casi con certeza NO está corriendo).
        stale = LockInfo(
            pid=999_999_999,
            acquired_at=_dt(2026, 6, 20, 0, 0, 0),
            ttl_seconds=1800,
        )
        lock_path.write_text(stale.to_json(), encoding="utf-8")

        try:
            acquire_lock(lock_path)
            # Ahora el lock es nuestro.
            current = check_lock(lock_path)
            assert current is not None
            assert current.pid != stale.pid
        finally:
            release_lock(lock_path)

    def test_acquire_lock_recovers_from_expired_ttl(self, tmp_path) -> None:
        """acquire_lock sobrescribe un lock con TTL expirado y PID muerto.

        Caso típico: el proceso dueño del lock murió (kill -9, OOM, crash)
        dejando el archivo en disco con TTL ya expirado. El stale-recovery
        debe detectar el PID muerto y sobrescribir sin raise.

        Construimos un LockInfo con ``acquired_at`` 2 horas en el pasado
        y TTL de 30 minutos — naturalmente expirado — con un PID dummy
        que no está vivo (``999_999_999``).
        """
        from migration.lock import (
            LockInfo,
            acquire_lock,
            release_lock,
        )

        lock_path = tmp_path / "sync.lock"
        # Lock de hace 2 horas con TTL de 30 min → expirado + PID muerto.
        two_hours_ago = datetime.now(tz=UTC).replace(microsecond=0)
        from datetime import timedelta

        two_hours_ago = two_hours_ago - timedelta(hours=2)
        expired = LockInfo(
            pid=999_999_999,
            acquired_at=two_hours_ago,
            ttl_seconds=1800,
        )
        lock_path.write_text(expired.to_json(), encoding="utf-8")

        try:
            acquire_lock(lock_path)
            # Si llegamos aquí sin raise, el stale-recovery funcionó.
            assert lock_path.exists()
        finally:
            release_lock(lock_path)

    def test_acquire_lock_raises_when_pid_alive_and_ttl_expired(self, tmp_path) -> None:
        """acquire_lock levanta LockActiveError cuando el PID está vivo y el TTL expiró.

        Caso split-brain: un proceso vivo dejó un lock hace horas (ej: el
        operador dejó una ventana con el sync corriendo, volvió al día
        siguiente, y el PID sigue vivo pero el lock tiene horas de
        antigüedad). NO debemos sobrescribir porque el proceso vivo podría
        continuar la migración en cualquier momento — sobrescribir causaría
        split-brain.

        Usamos el PID del propio proceso (alive por definición) con un lock
        de TTL expirado. ``acquire_lock`` debe levantar ``LockActiveError``.
        """
        import os

        from migration.lock import (
            LockInfo,
            acquire_lock,
            release_lock,
        )

        lock_path = tmp_path / "sync.lock"
        # Lock de hace 2 horas con TTL de 30 min → expirado.
        # PID es el nuestro (vivo).
        two_hours_ago = datetime.now(tz=UTC).replace(microsecond=0)
        from datetime import timedelta

        two_hours_ago = two_hours_ago - timedelta(hours=2)
        expired = LockInfo(
            pid=os.getpid(),
            acquired_at=two_hours_ago,
            ttl_seconds=1800,
        )
        lock_path.write_text(expired.to_json(), encoding="utf-8")

        try:
            with pytest.raises(LockActiveError, match="pid="):
                acquire_lock(lock_path)
        finally:
            release_lock(lock_path)

    # --- psutil fallback -----------------------------------------------

    def test_is_process_alive_returns_true_for_self(self) -> None:
        """``_is_process_alive(os.getpid())`` retorna ``True`` (proceso actual)."""
        import os

        from migration.lock import _is_process_alive

        assert _is_process_alive(os.getpid()) is True

    def test_is_process_alive_returns_false_for_nonexistent_pid(self) -> None:
        """``_is_process_alive(999_999_999)`` retorna ``False`` (PID inventado)."""
        from migration.lock import _is_process_alive

        assert _is_process_alive(999_999_999) is False

    def test_windows_psutil_fallback_does_not_use_os_kill(self, monkeypatch) -> None:
        """Regression: Windows fallback must not use ``os.kill(pid, 0)``.

        On Windows, signal 0 is ``CTRL_C_EVENT`` rather than a POSIX-style
        no-op liveness probe, so calling it can interrupt the pytest process.
        """
        import os

        if os.name != "nt":
            pytest.skip("Windows-specific os.kill fallback regression")

        from migration import lock as lock_mod

        monkeypatch.setattr(lock_mod, "_PSUTIL_AVAILABLE", False, raising=False)

        def fail_if_called(pid: int, signal: int) -> None:
            raise AssertionError(f"os.kill must not probe Windows PID liveness: {pid}, {signal}")

        monkeypatch.setattr(lock_mod.os, "kill", fail_if_called)

        assert lock_mod._is_process_alive(999_999_999) is False

    def test_check_msaccess_returns_list_of_pids_when_psutil_available(self, monkeypatch) -> None:
        """``check_msaccess_running`` retorna lista de PIDs cuando psutil está disponible."""
        from migration import lock as lock_mod

        class _FakeProcess:
            def __init__(self, pid: int, name: str) -> None:
                self.pid = pid
                self._name = name

            def info(self, attrs):
                return {"pid": self.pid, "name": self._name}

        # Forzar psutil disponible.
        fake_psutil = type(
            "Ps",
            (),
            {
                "process_iter": staticmethod(
                    lambda attrs: [
                        _FakeProcess(100, "MSACCESS.EXE"),
                        _FakeProcess(200, "chrome.exe"),
                        _FakeProcess(300, "MSACCESS.EXE"),
                    ]
                )
            },
        )
        monkeypatch.setattr(lock_mod, "psutil", fake_psutil, raising=False)
        # Resetear el cacheado de disponibilidad.
        monkeypatch.setattr(lock_mod, "_PSUTIL_AVAILABLE", True, raising=False)

        pids = lock_mod.check_msaccess_running()
        assert sorted(pids) == [100, 300]

    def test_check_msaccess_uses_module_level_psutil_attribute(self, monkeypatch) -> None:
        """P0 regression: ``psutil`` debe estar bound a nivel módulo.

        Pre-fix: el módulo importaba psutil como ``_psutil_module`` pero la
        función buscaba ``psutil`` en el namespace (``getattr(sys.modules[
        __name__], "psutil", None)``) — el nombre nunca existía, así que
        ``psutil_obj`` siempre era ``None`` y la función retornaba ``[]``
        aunque psutil estuviera instalado. Esto rompía silenciosamente el
        pre-flight de MSACCESS (regla #13474 v2 / design §14).

        Post-fix: ``psutil`` está bound a nivel módulo (``psutil =
        _psutil_module``) por lo que ``raising=True`` en
        ``monkeypatch.setattr`` funciona y la función usa el atributo
        directamente sin necesidad del ``getattr`` lookup.
        """
        real_psutil = pytest.importorskip("psutil")

        from migration import lock as lock_mod

        # ``raising=True`` fuerza a pytest a exigir que ``psutil`` exista
        # como atributo del módulo. Pre-fix: AttributeError (regression).
        # Post-fix: el setattr funciona porque ``psutil`` está bound.
        assert hasattr(lock_mod, "psutil"), (
            "psutil debe estar bound a nivel módulo (P0 #1 regression)"
        )
        # Y debe ser el módulo real (no None).
        assert lock_mod.psutil is real_psutil, (
            "lock_mod.psutil debe referenciar el módulo psutil real"
        )

        # Ahora monkeypatcheamos con un fake para verificar que la
        # función usa el atributo del módulo (no sys.modules.get('psutil')
        # ni nada raro). Con raising=True, esto requiere que ``psutil``
        # ya exista como atributo del módulo.
        class _FakeProcess:
            def __init__(self, pid: int, name: str) -> None:
                self.pid = pid
                self._name = name

            def info(self, attrs):
                return {"pid": self.pid, "name": self._name}

        fake_psutil = type(
            "Ps",
            (),
            {
                "process_iter": staticmethod(
                    lambda attrs: [
                        _FakeProcess(700, "MSACCESS.EXE"),
                        _FakeProcess(800, "notepad.exe"),
                        _FakeProcess(900, "msaccess.exe"),  # lowercase — case-insensitive
                    ]
                )
            },
        )
        monkeypatch.setattr(lock_mod, "psutil", fake_psutil, raising=True)
        monkeypatch.setattr(lock_mod, "_PSUTIL_AVAILABLE", True, raising=False)

        pids = lock_mod.check_msaccess_running()
        assert sorted(pids) == [700, 900]

    def test_check_msaccess_works_with_real_psutil_no_msaccess(self) -> None:
        """P0 regression: con psutil REAL instalado, la función debe ejecutarse.

        Pre-fix: ``check_msaccess_running()`` retornaba ``[]`` siempre
        (incluso con MSACCESS abierto) porque el módulo ``psutil`` nunca
        estaba bound al namespace. Post-fix: con psutil real, la función
        itera procesos reales y retorna ``[]`` legítimamente cuando no hay
        MSACCESS abierto (este test asume que ningún test runner tiene
        Access abierto, que es el caso normal en CI/dev).

        El test verifica:
          1. La función retorna una ``list[int]`` (no ``None`` ni excepción).
          2. La función usa el módulo psutil real (no retorna ``[]`` por un
             bug de ``psutil_obj is None``).
          3. No crashea con ``PermissionError`` ni ``AttributeError``.
        """
        pytest.importorskip("psutil")

        from migration import lock as lock_mod

        # Garantizar que psutil está bound — si no, esto falla con el bug P0 #1.
        assert hasattr(lock_mod, "psutil"), (
            "psutil debe estar bound a nivel módulo (P0 #1 regression)"
        )

        pids = lock_mod.check_msaccess_running()
        assert isinstance(pids, list)
        assert all(isinstance(p, int) for p in pids)
        # Si MSACCESS está abierto en este entorno (poco probable en CI
        # pero posible en dev), la lista puede no ser vacía. En cualquier
        # caso, la función DEBE haber ejecutado process_iter, no retornado
        # [] por el bug del lookup.

    # --- concurrent acquire (P0 #2 regression) -------------------------

    def test_acquire_lock_atomic_concurrent_first_acquire(self, tmp_path) -> None:
        """P0 regression: dos ``acquire_lock`` concurrentes sobre un lock inexistente.

        Contrato del docstring de ``acquire_lock``:
          "Two concurrent acquires must result in one success, one LockActiveError".

        Pre-fix: ambos hilos observaban ``not exists``, ambos escribían al
        mismo ``.tmp`` filename, y el segundo writer se llevaba un
        ``PermissionError: [WinError 32]`` en lugar del esperado
        ``LockActiveError``. En Windows esto se reproduce 10/10 trials.

        Post-fix: ``os.open(tmp, O_CREAT|O_EXCL|O_WRONLY)`` garantiza que
        solo un hilo gana el slot; el otro obtiene ``FileExistsError``
        y re-lee el lock file para evaluar staleness → ``LockActiveError``.

        El test corre 10 trials para garantizar determinismo (el race
        window es estrecho pero existe).
        """
        import threading
        from concurrent.futures import ThreadPoolExecutor

        from migration.lock import (
            acquire_lock,
            release_lock,
        )

        lock_path = tmp_path / "concurrent.lock"
        barrier = threading.Barrier(2)

        def attempt() -> str:
            barrier.wait()
            try:
                info = acquire_lock(lock_path)
            except LockActiveError:
                return "LockActiveError"
            except Exception as exc:  # noqa: BLE001 — capturamos para diagnóstico
                return f"UNEXPECTED:{type(exc).__name__}:{exc}"
            else:
                # Devolvemos el PID del ganador para verificar.
                return f"ACQUIRED:{info.pid}"

        try:
            for trial in range(10):
                # Resetear el lock file antes de cada trial.
                if lock_path.exists():
                    lock_path.unlink()

                results: list[str] = []
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(attempt) for _ in range(2)]
                    for f in futures:
                        results.append(f.result())

                acquired = [r for r in results if r.startswith("ACQUIRED")]
                lock_active = [r for r in results if r == "LockActiveError"]
                unexpected = [r for r in results if r.startswith("UNEXPECTED")]

                assert len(acquired) == 1, (
                    f"Trial {trial}: expected exactly 1 acquire, got {len(acquired)}: {results}"
                )
                assert len(lock_active) == 1, (
                    f"Trial {trial}: expected exactly 1 LockActiveError, "
                    f"got {len(lock_active)}: {results}"
                )
                assert len(unexpected) == 0, (
                    f"Trial {trial}: unexpected errors (regression of PermissionError): {unexpected}"
                )

                # Liberar antes del próximo trial para que el archivo
                # arranque limpio.
                release_lock(lock_path)
        finally:
            if lock_path.exists():
                release_lock(lock_path)

    def test_check_msaccess_raises_unavailable_when_psutil_missing(
        self, monkeypatch
    ) -> None:
        """``check_msaccess_running`` raises ``MsAccessPreflightUnavailableError`` when psutil is missing.

        PR3 verification remediation (per user directive 2026-07-11):
        the pre-flight MUST fail closed. Returning ``[]`` on missing
        ``psutil`` would silently claim "no MSACCESS live" while the
        check was unable to actually run — a misleading fail-open
        that could let an apply proceed against a held ``.accdb``.

        Now the function raises ``MsAccessPreflightUnavailableError``
        with reason ``psutil_missing``; the apply layer catches it,
        emits ``log_safe("apply.preflight_unavailable", reason=<cat>)``,
        and re-raises; the CLI converts it to exit 5 with reason
        ``msaccess_preflight_unavailable``.
        """
        from migration import (
            MsAccessPreflightUnavailableError,
        )
        from migration import (
            lock as lock_mod,
        )

        # Forzar el camino "psutil no disponible".
        monkeypatch.setattr(lock_mod, "_PSUTIL_AVAILABLE", False, raising=False)
        with pytest.raises(MsAccessPreflightUnavailableError) as excinfo:
            lock_mod.check_msaccess_running()
        assert excinfo.value.reason == (
            MsAccessPreflightUnavailableError.REASON_PSUTIL_MISSING
        )

    # --- Edge cases para cobertura de paths de error -------------------

    def test_check_lock_returns_none_for_malformed_json(self, tmp_path) -> None:
        """check_lock retorna ``None`` si el lock file está corrupto (NO raise).

        Cobertura: paths de error de ``_read_lock_unverified`` + ``from_json``.
        Un lock corrupto no se auto-recupera en ``acquire_lock``: puede
        ser un writer pausado a mitad de escritura y requiere limpieza manual.
        """
        from migration.lock import check_lock

        bad_path = tmp_path / "bad.lock"
        bad_path.write_text("not a valid json{", encoding="utf-8")
        assert check_lock(bad_path) is None

    def test_acquire_lock_raises_on_fresh_empty_lock(self, tmp_path) -> None:
        """Fresh empty lock file → ``LockActiveError`` (not unlinked).

        An empty lock file is always treated as an in-flight writer (never
        auto-recovered), regardless of age. A writer can be paused between
        os.open(O_CREAT|O_EXCL) and fdopen/write for arbitrarily long.
        """
        from migration.lock import acquire_lock, release_lock

        lock_path = tmp_path / "fresh_empty.lock"
        # Crear archivo vacío (simula caller A en medio de os.fdopen)
        lock_path.touch()
        try:
            with pytest.raises(LockActiveError, match="empty or corrupt"):
                acquire_lock(lock_path)
            # El archivo sigue ahí (no fue borrado)
            assert lock_path.exists()
        finally:
            release_lock(lock_path)

    def test_acquire_lock_raises_on_fresh_corrupt_json_lock(self, tmp_path) -> None:
        """Fresh corrupt JSON lock file → ``LockActiveError`` (not unlinked).

        Same principle as empty lock: partial JSON written by an in-flight
        writer is never auto-recovered. Manual cleanup required when the
        writer process is confirmed dead.
        """
        from migration.lock import acquire_lock, release_lock

        lock_path = tmp_path / "fresh_corrupt.lock"
        # Partial JSON (simula writer matado entre open y write)
        lock_path.write_text("{", encoding="utf-8")
        try:
            with pytest.raises(LockActiveError, match="empty or corrupt"):
                acquire_lock(lock_path)
            # Archivo sigue intacto
            assert lock_path.exists()
        finally:
            release_lock(lock_path)

    def test_acquire_lock_raises_on_old_corrupt_lock(self, tmp_path) -> None:
        """Old corrupt lock file → ``LockActiveError`` (never auto-recovered).

        A corrupt/empty lock file is NEVER auto-unlinked, regardless of age.
        A live writer can be paused after os.open(O_CREAT|O_EXCL) and
        before/during JSON write for longer than any grace period; another
        process must not treat the file as garbage and acquire over it.
        Manual cleanup is required when no other process is running.
        """
        from migration.lock import acquire_lock, release_lock

        lock_path = tmp_path / "old_corrupt.lock"
        lock_path.write_text("{invalid", encoding="utf-8")
        # Mover mtime al pasado: incluso un lock corrupto viejo bloquea.
        import os as _os
        import time as _time
        old_mtime = _time.time() - 10
        _os.utime(lock_path, times=(old_mtime, old_mtime))

        try:
            with pytest.raises(LockActiveError, match="empty or corrupt"):
                acquire_lock(lock_path)
            # Archivo preservado — requiere limpieza manual
            assert lock_path.exists()
        finally:
            release_lock(lock_path)

    def test_lock_info_from_json_rejects_missing_fields(self) -> None:
        """``LockInfo.from_json`` levanta ``ValueError`` si falta ``pid``."""
        from migration.lock import LockInfo

        with pytest.raises(ValueError, match="pid"):
            LockInfo.from_json('{"acquired_at": "2026-06-21T00:00:00+00:00"}')

    def test_lock_info_from_json_rejects_non_integer_ttl(self) -> None:
        """``LockInfo.from_json`` levanta ``ValueError`` si ttl_seconds no es int."""
        from migration.lock import LockInfo

        with pytest.raises(ValueError, match="ttl_seconds"):
            LockInfo.from_json(
                '{"pid": 1, "acquired_at": "2026-06-21T00:00:00+00:00", '
                '"ttl_seconds": "not-an-int"}'
            )

    # --- helpers (Path A refactor: acquire_lock split into 4 helpers) ------

    def test_ensure_parent_dir_creates_missing_parents(self, tmp_path) -> None:
        """``_ensure_parent_dir`` crea el directorio padre si no existe.

        Cobertura para ``acquire_lock`` Fase 0: cuando el lock file vive
        en un directorio que aún no existe (primer run post-deploy, o un
        ``tmp_path/nested/`` creado por el test), el helper lo crea con
        ``parents=True``. Sin este path cubierto, CRAP del helper
        subía.
        """
        from migration.lock import _ensure_parent_dir

        nested = tmp_path / "a" / "b" / "c" / "sync.lock"
        assert not nested.parent.exists()
        _ensure_parent_dir(nested)
        assert nested.parent.is_dir()

    def test_ensure_parent_dir_is_noop_when_parent_exists(self, tmp_path) -> None:
        """``_ensure_parent_dir`` no raise si el padre ya existe."""
        from migration.lock import _ensure_parent_dir

        lock_path = tmp_path / "sync.lock"
        assert lock_path.parent.exists()
        # No raise, no error.
        _ensure_parent_dir(lock_path)
        assert lock_path.parent.is_dir()

    def test_ensure_parent_dir_handles_path_with_no_parent(self) -> None:
        """``_ensure_parent_dir`` tolera paths sin componente padre (p.ej. ``Path('lock')``)."""
        from migration.lock import _ensure_parent_dir

        bare = Path("lock")
        # No raise: el helper detecta ``parent`` vacío como no-op.
        _ensure_parent_dir(bare)

    def test_check_and_clear_existing_lock_noop_when_missing(self, tmp_path) -> None:
        """``_check_and_clear_existing_lock`` no raise cuando no hay lock file."""
        from migration.lock import _check_and_clear_existing_lock

        lock_path = tmp_path / "missing.lock"
        assert not lock_path.exists()
        # No raise, no side effect.
        _check_and_clear_existing_lock(lock_path)
        assert not lock_path.exists()

    def test_check_and_clear_existing_lock_raises_on_corrupt(self, tmp_path) -> None:
        """``_check_and_clear_existing_lock`` raises ``LockActiveError`` si el lock está corrupto.

        Cobertura para el path "lock existe pero _read_lock_unverified
        retorna None" (vacío, JSON parcial, mtime antiguo). El helper
        nunca auto-recupera: podría ser un writer pausado entre
        ``os.open(O_CREAT|O_EXCL)`` y ``f.write()``.
        """
        from migration.lock import _check_and_clear_existing_lock

        lock_path = tmp_path / "corrupt.lock"
        lock_path.write_text("{", encoding="utf-8")
        with pytest.raises(LockActiveError, match="empty or corrupt"):
            _check_and_clear_existing_lock(lock_path)
        # El archivo NO se borra (auto-recovery prohibido para corrupt).
        assert lock_path.exists()

    def test_check_and_clear_existing_lock_raises_on_active(self, tmp_path) -> None:
        """``_check_and_clear_existing_lock`` raises si el lock es parseable y dueño vivo."""
        import os

        from migration.lock import LockInfo, _check_and_clear_existing_lock

        lock_path = tmp_path / "active.lock"
        active = LockInfo(
            pid=os.getpid(),
            acquired_at=datetime.now(tz=UTC).replace(microsecond=0),
            ttl_seconds=1800,
        )
        lock_path.write_text(active.to_json(), encoding="utf-8")
        with pytest.raises(LockActiveError, match=f"pid={os.getpid()}"):
            _check_and_clear_existing_lock(lock_path)
        # El archivo no se borra (es un lock activo, no stale).
        assert lock_path.exists()

    def test_check_and_clear_existing_lock_unlinks_stale(self, tmp_path) -> None:
        """``_check_and_clear_existing_lock`` unlinka un lock parseable con dueño muerto."""
        from migration.lock import LockInfo, _check_and_clear_existing_lock

        lock_path = tmp_path / "stale.lock"
        # PID inexistente → dueño muerto.
        stale = LockInfo(
            pid=999_999_999,
            acquired_at=datetime.now(tz=UTC).replace(microsecond=0),
            ttl_seconds=1800,
        )
        lock_path.write_text(stale.to_json(), encoding="utf-8")
        # No raise.
        _check_and_clear_existing_lock(lock_path)
        # El lock stale fue removido.
        assert not lock_path.exists()

    def test_unlink_stale_lock_tolerates_already_gone(self, tmp_path) -> None:
        """``_unlink_stale_lock`` no raise si el archivo ya no existe.

        Race condition: otro proceso pudo haber unlinkado entre el
        ``_read_lock_unverified`` y el ``unlink``. El helper debe ser
        idempotente.
        """
        from migration.lock import _unlink_stale_lock

        lock_path = tmp_path / "ghost.lock"
        # No crear el archivo: simula la race donde ya no está.
        _unlink_stale_lock(lock_path)
        # No raise.

    def test_raise_after_concurrent_acquire_raises_for_active_winner(
        self, tmp_path
    ) -> None:
        """``_raise_after_concurrent_acquire`` raises con pid del ganador si el lock es activo."""
        import os

        from migration.lock import LockInfo, _raise_after_concurrent_acquire

        lock_path = tmp_path / "winner.lock"
        winner = LockInfo(
            pid=os.getpid(),
            acquired_at=datetime.now(tz=UTC).replace(microsecond=0),
            ttl_seconds=1800,
        )
        lock_path.write_text(winner.to_json(), encoding="utf-8")
        with pytest.raises(LockActiveError, match=f"pid={os.getpid()}"):
            _raise_after_concurrent_acquire(lock_path)

    def test_raise_after_concurrent_acquire_raises_generic_for_corrupt(
        self, tmp_path
    ) -> None:
        """``_raise_after_concurrent_acquire`` raises ``LockActiveError`` con mensaje genérico si el ganador no terminó de escribir.

        Cuando el ganador está entre ``os.open(O_CREAT|O_EXCL)`` y
        ``f.write()`` (race window), el segundo acquire concurrente
        ve JSON inválido y debe recibir un error genérico "retry
        shortly" — nunca un error de I/O o de parseo JSON.
        """
        from migration.lock import _raise_after_concurrent_acquire

        lock_path = tmp_path / "mid_write.lock"
        # JSON parcial: el ganador está escribiendo.
        lock_path.write_text("{", encoding="utf-8")
        with pytest.raises(LockActiveError, match="in flight"):
            _raise_after_concurrent_acquire(lock_path)

    def test_raise_after_concurrent_acquire_raises_generic_for_stale_winner(
        self, tmp_path
    ) -> None:
        """``_raise_after_concurrent_acquire`` raises genérico si el ganador ya es stale.

        Cuando el ganador quedó stale justo en la race window
        (el proceso murió entre ``os.open`` y ``f.write``), el
        segundo acquire todavía ve el lock como "en vuelo" desde
        su ventana de carrera, no como stale reusable. Se preserva
        el contrato: el segundo caller hace retry shortly.
        """
        from migration.lock import LockInfo, _raise_after_concurrent_acquire

        lock_path = tmp_path / "stale_winner.lock"
        # Ganador ya muerto: el lock es stale, pero desde la race window
        # el segundo caller no puede distinguir "ganador está escribiendo"
        # de "ganador murió escribiendo" — reintenta.
        stale_winner = LockInfo(
            pid=999_999_999,
            acquired_at=datetime.now(tz=UTC).replace(microsecond=0),
            ttl_seconds=1800,
        )
        lock_path.write_text(stale_winner.to_json(), encoding="utf-8")
        with pytest.raises(LockActiveError, match="in flight"):
            _raise_after_concurrent_acquire(lock_path)

    def test_claim_new_lock_writes_lock_info_atomically(self, tmp_path) -> None:
        """``_claim_new_lock`` crea el lock file y escribe el JSON del ``LockInfo`` dado."""
        from migration.lock import LockInfo, _claim_new_lock

        lock_path = tmp_path / "claim.lock"
        info = LockInfo(
            pid=42,
            acquired_at=datetime(2026, 6, 21, 0, 0, 0, tzinfo=UTC),
            ttl_seconds=900,
        )
        result = _claim_new_lock(lock_path, info)
        assert result is info
        assert lock_path.exists()
        assert json.loads(lock_path.read_text(encoding="utf-8")) == json.loads(
            info.to_json()
        )

    def test_claim_new_lock_raises_when_file_already_exists(self, tmp_path) -> None:
        """``_claim_new_lock`` raises ``LockActiveError`` si el lock ya existe (race)."""
        from migration.lock import LockInfo, _claim_new_lock

        lock_path = tmp_path / "claimed.lock"
        # Simular que otro proceso ya creó el lock.
        lock_path.write_text("placeholder", encoding="utf-8")
        info = LockInfo(
            pid=42,
            acquired_at=datetime(2026, 6, 21, 0, 0, 0, tzinfo=UTC),
            ttl_seconds=900,
        )
        with pytest.raises(LockActiveError):
            _claim_new_lock(lock_path, info)

    def test_claim_new_lock_cleans_up_on_write_failure(
        self, tmp_path, monkeypatch
    ) -> None:
        """``_claim_new_lock`` unlinka el lock file si ``f.write`` falla.

        Cobertura del path de cleanup (disco lleno, proceso matado entre
        ``os.open`` y ``f.write``): el lock creado por ``O_EXCL`` se
        borra para no dejar basura que confunda el próximo acquire.
        """
        from migration import lock as lock_mod
        from migration.lock import LockInfo, _claim_new_lock

        lock_path = tmp_path / "cleanup.lock"
        info = LockInfo(
            pid=42,
            acquired_at=datetime(2026, 6, 21, 0, 0, 0, tzinfo=UTC),
            ttl_seconds=900,
        )

        class _FailingFile:
            """Mock que cierra el fd en ``__exit__`` y falla en ``write``.

            El ``os.fdopen`` real crea un Python file object que posee
            el fd; en este test simulamos que la escritura falla
            (disco lleno) pero el ``__exit__`` cierra el fd igual que
            el ``os.fdopen`` real.
            """

            def __init__(self, fd, *_args, **_kwargs) -> None:
                self._fd = fd

            def __enter__(self) -> _FailingFile:
                return self

            def __exit__(self, *_args) -> None:
                lock_mod.os.close(self._fd)

            def write(self, _payload: str) -> None:
                raise OSError("simulated disk full")

        monkeypatch.setattr(lock_mod.os, "fdopen", _FailingFile)
        with pytest.raises(OSError, match="simulated disk full"):
            _claim_new_lock(lock_path, info)
        # Cleanup: el lock file creado por O_EXCL se eliminó.
        assert not lock_path.exists(), (
            "_claim_new_lock must unlink the O_EXCL-created file when write fails"
        )

    def test_claim_new_lock_cleans_up_tolerates_file_already_gone(
        self, tmp_path, monkeypatch
    ) -> None:
        """``_claim_new_lock`` tolera que el lock ya haya desaparecido al hacer cleanup.

        Race: si el write falla Y simultáneamente otro actor borró el
        lock file, el cleanup ``os.unlink`` debe tolerar
        ``FileNotFoundError`` (idempotente). Mockeamos ``os.unlink`` para
        que retorne ``FileNotFoundError`` en lugar de borrar — esto evita
        la carrera con el file locking de Windows donde un fd abierto no
        puede ser unlinkeado.
        """
        from migration import lock as lock_mod
        from migration.lock import LockInfo, _claim_new_lock

        lock_path = tmp_path / "cleanup_race.lock"
        info = LockInfo(
            pid=42,
            acquired_at=datetime(2026, 6, 21, 0, 0, 0, tzinfo=UTC),
            ttl_seconds=900,
        )

        class _FailingFile:
            def __init__(self, fd, *_args, **_kwargs) -> None:
                self._fd = fd

            def __enter__(self) -> _FailingFile:
                return self

            def __exit__(self, *_args) -> None:
                lock_mod.os.close(self._fd)

            def write(self, _payload: str) -> None:
                raise OSError("simulated mid-write failure")

        real_unlink = lock_mod.os.unlink

        def fake_unlink(path) -> None:
            # El cleanup ``try: os.unlink() except FileNotFoundError: pass``
            # solo llama a ``unlink`` sobre ``lock_path``. Simulamos que
            # el archivo ya no está.
            if str(path) == str(lock_path):
                raise FileNotFoundError(2, "simulated already gone", str(path))
            real_unlink(path)

        monkeypatch.setattr(lock_mod.os, "fdopen", _FailingFile)
        monkeypatch.setattr(lock_mod.os, "unlink", fake_unlink)
        # No raise de FileNotFoundError en el cleanup.
        with pytest.raises(OSError, match="simulated mid-write failure"):
            _claim_new_lock(lock_path, info)
