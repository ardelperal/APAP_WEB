"""VOL-04 (#37): volontario FK resolution in ``migration.apply``.

Tests the 4-level resolution strategy for volontario free-text columns
in ``acogida`` and ``adopcion`` tables:

  Level 1: exact normalised match in the in-memory index.
  Level 2: fuzzy match (rapidfuzz.WRatio >= threshold) via the index.
  Level 3: no match -> None (optional) or error path.

Coverage:
  - ``_VoluntariosIndex`` helpers.
  - ``_resolve_fk_value`` for exact + fuzzy lookups.
  - ``_legacy_to_web_row`` with ``transform: fk_lookup`` columns.
  - ``apply_legacy_to_web`` integration for ``acogida`` rows.
"""
from __future__ import annotations

from typing import Any

from migration.apply import (
    _legacy_to_web_row,
    _normalise_for_lookup,
    _resolve_fk_value,
    _strip_accents,
    _VoluntariosIndex,
)
from tests.migration.conftest import FakeSqlExecutor

# ---------------------------------------------------------------------------
# Helpers: pure functions (no I/O)
# ---------------------------------------------------------------------------


class TestNormaliseForLookup:
    def test_strips_and_lowercases(self) -> None:
        assert _normalise_for_lookup("  Maria Garcia  ") == "maria garcia"

    def test_collapse_whitespace(self) -> None:
        assert _normalise_for_lookup("Ana\tGarcia  Lopez") == "ana garcia lopez"

    def test_empty_string(self) -> None:
        assert _normalise_for_lookup("   ") == ""


class TestStripAccents:
    def test_strips_spanish_accents(self) -> None:
        assert _strip_accents("María") == "Maria"
        assert _strip_accents("José") == "Jose"
        assert _strip_accents("Ñoño") == "Nono"

    def test_no_change_without_accents(self) -> None:
        assert _strip_accents("Ana Garcia") == "Ana Garcia"


# ---------------------------------------------------------------------------
# _VoluntariosIndex
# ---------------------------------------------------------------------------


class TestVoluntariosIndex:
    def _make_fake_client(self, volontarios: list[dict[str, Any]]) -> FakeSqlExecutor:
        client = FakeSqlExecutor()
        client.seed("volontarios", volontarios)
        return client

    def test_load_from_db_populates_index(self) -> None:
        client = self._make_fake_client(
            [{"id": "v-1", "voluntario": "Ana Garcia"}, {"id": "v-2", "voluntario": "Rosa Martinez"}]
        )
        index = _VoluntariosIndex()
        index.load_from_db(client)

        # Exact normalised match.
        assert index.resolve("Ana Garcia") == "v-1"
        assert index.resolve("ana garcia") == "v-1"
        assert index.resolve("  ana  garcia  ") == "v-1"
        assert index.resolve("Rosa Martinez") == "v-2"

    def test_resolve_returns_none_for_unknown(self) -> None:
        client = self._make_fake_client([{"id": "v-1", "voluntario": "Ana Garcia"}])
        index = _VoluntariosIndex()
        index.load_from_db(client)

        assert index.resolve("Carlos Ruiz") is None

    def test_resolve_none_input_returns_none(self) -> None:
        index = _VoluntariosIndex()
        assert index.resolve(None) is None
        assert index.resolve("") is None
        assert index.resolve("   ") is None

    def test_fuzzy_match_above_threshold(self) -> None:
        """Maria Garcia / Maria Garcia (accent variant) fuzzy above 85."""
        client = self._make_fake_client([{"id": "v-1", "voluntario": "Maria Garcia"}])
        index = _VoluntariosIndex()
        index.load_from_db(client)

        # Accent variant -- normalised + stripped should match at 100.
        assert index.resolve("Maria Garcia", fuzzy_threshold=85) == "v-1"

    def test_fuzzy_match_below_threshold_returns_none(self) -> None:
        client = self._make_fake_client([{"id": "v-1", "voluntario": "Ana Garcia"}])
        index = _VoluntariosIndex()
        index.load_from_db(client)

        # Very different name -- should not fuzzy match above 85.
        assert index.resolve("Carlos Lopez", fuzzy_threshold=85) is None

    def test_fuzzy_match_best_above_threshold_wins(self) -> None:
        """When multiple entries score above threshold, return the best score."""
        client = self._make_fake_client(
            [
                {"id": "v-1", "voluntario": "Ana Garcia"},
                {"id": "v-2", "voluntario": "Ana Garcia Lopez"},
            ]
        )
        index = _VoluntariosIndex()
        index.load_from_db(client)

        # "Ana Garcia" should fuzzy-match v-1 (100%) better than v-2.
        result = index.resolve("Ana Garcia", fuzzy_threshold=85)
        assert result == "v-1"

    def test_record_adds_to_index(self) -> None:
        """A volontario migrated in the same run is registered (Level 2)."""
        index = _VoluntariosIndex()
        index.record("Rosa Martinez", "v-99")

        assert index.resolve("Rosa Martinez") == "v-99"

    def test_record_takes_precedence_over_db(self) -> None:
        """Level 2 (record) takes precedence over Level 1 (DB)."""
        client = self._make_fake_client(
            [{"id": "v-1", "voluntario": "Ana Garcia"}, {"id": "v-2", "voluntario": "Pedro Ruiz"}]
        )
        index = _VoluntariosIndex()
        index.record("Ana Garcia", "v-999")  # Level 2 wins over DB for this name.
        index.load_from_db(client)  # Level 1 adds entries not yet registered.

        # Level 2 (record) takes precedence.
        assert index.resolve("Ana Garcia") == "v-999"
        # Level 1 (DB) fills the gap.
        assert index.resolve("Pedro Ruiz") == "v-2"


# ---------------------------------------------------------------------------
# _resolve_fk_value
# ---------------------------------------------------------------------------


class TestResolveFkValue:
    def _make_client(
        self,
        volontarios: list[dict[str, Any]] | None = None,
        animales: list[dict[str, Any]] | None = None,
    ) -> FakeSqlExecutor:
        client = FakeSqlExecutor()
        if volontarios:
            client.seed("volontarios", volontarios)
        if animales:
            client.seed("animales", animales)
        return client

    def test_exact_lookup_finds_row(self) -> None:
        client = self._make_client(animales=[{"id": "a-1", "nchip": "X1"}])
        result = _resolve_fk_value(
            "X1",
            lookup_table="animales",
            lookup_key="nchip",
            client=client,
            vol_index=None,
            fuzzy_match=False,
            optional=True,
        )
        assert result == "a-1"

    def test_exact_lookup_miss_returns_none(self) -> None:
        client = self._make_client(animales=[{"id": "a-1", "nchip": "X1"}])
        result = _resolve_fk_value(
            "X2",
            lookup_table="animales",
            lookup_key="nchip",
            client=client,
            vol_index=None,
            fuzzy_match=False,
            optional=True,
        )
        assert result is None

    def test_voluntario_fuzzy_via_index(self) -> None:
        """Miss on exact lookup falls through to fuzzy in the volontario index."""
        client = self._make_client(volontarios=[{"id": "v-1", "voluntario": "Maria Garcia"}])
        index = _VoluntariosIndex()
        index.load_from_db(client)

        # No exact match for "Maria Garcia" in volontarios by exact lookup;
        # falls through to fuzzy in index.
        result = _resolve_fk_value(
            "Maria Garcia",
            lookup_table="volontarios",
            lookup_key="voluntario",
            client=client,
            vol_index=index,
            fuzzy_match=True,
            fuzzy_threshold=85,
            optional=True,
        )
        assert result == "v-1"

    def test_optional_returns_none_on_miss(self) -> None:
        client = self._make_client(volontarios=[{"id": "v-1", "voluntario": "Ana Garcia"}])
        index = _VoluntariosIndex()
        index.load_from_db(client)

        result = _resolve_fk_value(
            "Carlos Lopez",
            lookup_table="volontarios",
            lookup_key="voluntario",
            client=client,
            vol_index=index,
            fuzzy_match=True,
            fuzzy_threshold=85,
            optional=True,
        )
        assert result is None

    def test_empty_legacy_value_returns_none(self) -> None:
        client = self._make_client(volontarios=[{"id": "v-1", "voluntario": "Ana Garcia"}])
        index = _VoluntariosIndex()
        index.load_from_db(client)

        assert _resolve_fk_value(
            None,
            lookup_table="volontarios",
            lookup_key="voluntario",
            client=client,
            vol_index=index,
            fuzzy_match=True,
            optional=True,
        ) is None
        assert _resolve_fk_value(
            "",
            lookup_table="volontarios",
            lookup_key="voluntario",
            client=client,
            vol_index=index,
            fuzzy_match=True,
            optional=True,
        ) is None


# ---------------------------------------------------------------------------
# _legacy_to_web_row with FK columns
# ---------------------------------------------------------------------------


class TestLegacyToWebRowFk:
    def _make_mapping(
        self,
        fk_columns: list[dict[str, Any]],
        fk_lookups: list[dict[str, Any]],
    ) -> Any:
        from migration.mappings import ColumnMapping, FkLookup, TableMapping

        columns = [
            ColumnMapping(web_column="id", legacy_column=None, transform="default_uuid"),
            ColumnMapping(web_column="fecha_inicio", legacy_column="FFechaInicio", transform="identity"),
            ColumnMapping(web_column="animal_id", legacy_column="NCHIP", transform="fk_lookup", lookup="animal"),
        ]
        for fc in fk_columns:
            columns.append(
                ColumnMapping(
                    web_column=fc["web_column"],
                    legacy_column=fc.get("legacy_column"),
                    transform="fk_lookup",
                    lookup=fc["lookup"],
                )
            )

        lookups = [
            FkLookup(
                name="animal",
                web_column="animal_id",
                legacy_column="NCHIP",
                lookup_table="animales",
                lookup_legacy_key="nchip",
            )
        ]
        for fl in fk_lookups:
            lookups.append(FkLookup(**fl))

        return TableMapping(
            version="1.0",
            web_table="acogidas",
            legacy_table="TbAcogidaAnimal",
            key_field="id",
            legacy_key="IDAcogida",
            columns=columns,
            fk_lookups=lookups,
        )

    def test_fk_column_resolved_exact(self) -> None:
        """animal_id is resolved via exact lookup on NCHIP."""
        client = FakeSqlExecutor()
        client.seed("animales", [{"id": "a-1", "nchip": "X1"}])
        client.seed("volontarios", [])

        mapping = self._make_mapping(
            fk_columns=[],
            fk_lookups=[],
        )
        legacy_row = {"IDAcogida": "1", "FFechaInicio": "2024-01-01", "NCHIP": "X1"}

        index = _VoluntariosIndex()
        index.load_from_db(client)
        web_row = _legacy_to_web_row(legacy_row, mapping, client, index)

        assert web_row["animal_id"] == "a-1"

    def test_voluntario_fk_resolved_fuzzy(self) -> None:
        """voluntario_acogida_id uses fuzzy match when exact misses."""
        client = FakeSqlExecutor()
        client.seed("animales", [{"id": "a-1", "nchip": "X1"}])
        client.seed(
            "volontarios",
            [{"id": "v-1", "voluntario": "Maria Garcia", "activo": True}],
        )

        mapping = self._make_mapping(
            fk_columns=[
                {
                    "web_column": "voluntario_acogida_id",
                    "lookup": "voluntario_acogida",
                }
            ],
            fk_lookups=[
                {
                    "name": "voluntario_acogida",
                    "web_column": "voluntario_acogida_id",
                    "legacy_column": "VoluntarioAcogida",
                    "lookup_table": "volontarios",
                    "lookup_legacy_key": "voluntario",
                    "fuzzy_match": True,
                    "fuzzy_threshold": 85,
                    "optional": True,
                }
            ],
        )
        # Legacy has accent variant; DB has normalised name.
        legacy_row = {
            "IDAcogida": "1",
            "FFechaInicio": "2024-01-01",
            "NCHIP": "X1",
            "VoluntarioAcogida": "Maria Garcia",
        }

        index = _VoluntariosIndex()
        index.load_from_db(client)
        web_row = _legacy_to_web_row(legacy_row, mapping, client, index)

        assert web_row["voluntario_acogida_id"] == "v-1"

    def test_voluntario_fk_unmatched_optional_returns_none(self) -> None:
        """Unknown volontario with optional=True resolves to None."""
        client = FakeSqlExecutor()
        client.seed("animales", [{"id": "a-1", "nchip": "X1"}])
        client.seed("voluntarios", [{"id": "v-1", "voluntario": "Ana Garcia", "activo": True}])

        mapping = self._make_mapping(
            fk_columns=[
                {
                    "web_column": "voluntario_acogida_id",
                    "lookup": "voluntario_acogida",
                }
            ],
            fk_lookups=[
                {
                    "name": "voluntario_acogida",
                    "web_column": "voluntario_acogida_id",
                    "legacy_column": "VoluntarioAcogida",
                    "lookup_table": "volontarios",
                    "lookup_legacy_key": "voluntario",
                    "fuzzy_match": True,
                    "fuzzy_threshold": 85,
                    "optional": True,
                }
            ],
        )
        legacy_row = {
            "IDAcogida": "1",
            "FFechaInicio": "2024-01-01",
            "NCHIP": "X1",
            "VoluntarioAcogida": "Carlos Desconocido",
        }

        index = _VoluntariosIndex()
        index.load_from_db(client)
        web_row = _legacy_to_web_row(legacy_row, mapping, client, index)

        assert web_row["voluntario_acogida_id"] is None


# ---------------------------------------------------------------------------
# Integration: apply_legacy_to_web for acogida rows with volontario FK
# ---------------------------------------------------------------------------


class TestApplyAcogidaVoluntarioFk:
    """End-to-end tests: apply acogecha rows with volontario FK columns.

    Uses the ``apply_runner`` fixture which wires a FakeSqlExecutor and
    injects the Dysflow executor seam.
    """

    def test_acogida_insert_populates_voluntario_fk(self, apply_runner) -> None:
        """Applying an acogida row resolves volontario free-text to UUID via index."""
        captured = apply_runner(
            legacy_rows=[
                {
                    "IDAcogida": "1",
                    "FFechaInicio": "2024-01-01",
                    "NCHIP": "X1",
                    "VoluntarioAcogida": "Ana Garcia",
                }
            ],
            seed={
                "animales": [{"id": "a-1", "nchip": "X1", "activo": True}],
                "volontarios": [{"id": "v-1", "voluntario": "Ana Garcia", "activo": True}],
                # Seed acogidas so FakeSqlExecutor knows about the FK columns.
                "acogidas": [
                    {"id": "placeholder", "fecha_inicio": "", "animal_id": "", "voluntario_acogida_id": ""}
                ],
            },
            table_name="acogida",
        )

        result = captured["result"]
        assert result.applied == 1
        assert result.errors == []

        acogidas = captured["client"].all_rows("acogidas")
        applied = next(r for r in acogidas if r.get("id") != "placeholder")
        assert applied["voluntario_acogida_id"] == "v-1"

    def test_acogida_voluntario_fuzzy_match_falls_back_to_index(self, apply_runner) -> None:
        """When exact lookup misses, fuzzy in the volontario index resolves."""
        captured = apply_runner(
            legacy_rows=[
                {
                    "IDAcogida": "1",
                    "FFechaInicio": "2024-01-01",
                    "NCHIP": "X1",
                    # Legacy has accent variant; DB has normalised name.
                    "VoluntarioAcogida": "Maria Garcia",
                }
            ],
            seed={
                "animales": [{"id": "a-1", "nchip": "X1", "activo": True}],
                # DB has normalised name.
                "voluntarios": [{"id": "v-1", "voluntario": "Maria Garcia", "activo": True}],
                "acogidas": [
                    {"id": "placeholder", "fecha_inicio": "", "animal_id": "", "voluntario_acogida_id": ""}
                ],
            },
            table_name="acogida",
        )

        result = captured["result"]
        assert result.applied == 1

        acogidas = captured["client"].all_rows("acogidas")
        applied = next(r for r in acogidas if r.get("id") != "placeholder")
        assert applied["voluntario_acogida_id"] == "v-1"

    def test_acogida_voluntario_unknown_optional_returns_none(self, apply_runner) -> None:
        """An optional volontario FK with no match in DB resolves to NULL."""
        captured = apply_runner(
            legacy_rows=[
                {
                    "IDAcogida": "1",
                    "FFechaInicio": "2024-01-01",
                    "NCHIP": "X1",
                    "VoluntarioAcogida": "Nadie Conocido",
                }
            ],
            seed={
                "animales": [{"id": "a-1", "nchip": "X1", "activo": True}],
                "voluntarios": [{"id": "v-1", "voluntario": "Ana Garcia", "activo": True}],
                "acogidas": [
                    {"id": "placeholder", "fecha_inicio": "", "animal_id": "", "voluntario_acogida_id": ""}
                ],
            },
            table_name="acogida",
        )

        result = captured["result"]
        assert result.applied == 1

        acogidas = captured["client"].all_rows("acogidas")
        applied = next(r for r in acogidas if r.get("id") != "placeholder")
        assert applied["voluntario_acogida_id"] is None
