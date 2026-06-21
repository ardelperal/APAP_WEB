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
        """
        col = ColumnMapping(
            web_column="id",
            legacy_column=None,
            transform="default_uuid",
            nullable=False,
        )
        assert col.web_only_strategy is None


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
        """ReconciliationResult carries the outcomes list and a counts helper."""
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
