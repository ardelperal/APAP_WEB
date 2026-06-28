"""Tests for the semantic events translator (PR 2/6, T2.4–T2.6).

8 diff→event combinations from ``lifecycle-event-log-design.md §4`` and
``design.md §5``:

| Legacy table        | op     | Field transition                | Event              |
|---------------------|--------|---------------------------------|--------------------|
| ``TbEntradas``      | INSERT | ``FEntrada NOT NULL``           | ``INTAKE_STARTED`` |
| ``TbEntradas``      | UPDATE | ``FSalida: NULL → date``        | ``INTAKE_COMPLETED``|
| ``TbEntradas``      | UPDATE | ``FEntregaAPropietario: NULL → date`` | ``OWNER_RETURNED`` |
| ``TbAcogidaAnimal`` | INSERT | —                               | ``FOSTER_STARTED`` |
| ``TbAcogidaAnimal`` | UPDATE | ``FFinal: NULL → date``         | ``FOSTER_RETURNED``|
| ``TbAdopcion``      | INSERT | —                               | ``ADOPTION_STARTED``|
| ``TbAdopcion``      | UPDATE | ``FDevolucion: NULL → date``    | ``ADOPTION_RETURNED``|
| ``TbFichaAnimal``   | UPDATE | ``FDefuncion: NULL → date``     | ``DEATH_RECORDED`` |

Plus 12 negative-path / edge-case tests.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest


def _mapping_for(legacy_table: str) -> object:
    """Return a minimal TableMapping stub for ``translate_diff``.

    Tests do not exercise the full ColumnMapping machinery (PR 3); they
    only need ``mapping.legacy_table`` to be readable. Using the real
    YAMLs would couple these tests to PR 3 + 5; the stub keeps PR 2
    autonomous.
    """
    from migration.mappings import FkLookup, TableMapping

    return TableMapping(
        version="1.0",
        web_table=legacy_table.lower(),
        legacy_table=legacy_table,
        key_field="id",
        legacy_key="id",
        date_fields=[],
        columns=[],
        fk_lookups=[
            FkLookup(
                name="_dummy",
                web_column="_x",
                legacy_column="_x",
                lookup_table="_dummy",
                lookup_legacy_key="_x",
            )
        ],
    )


# --- TestSemanticEvents: 8 happy paths ----------------------------------


class TestSemanticEvents:
    """The 8 happy-path diff→event combinations."""

    @pytest.mark.parametrize(
        (
            "name",
            "legacy_table",
            "op",
            "legacy_row",
            "changed_fields",
            "expected_event_type",
            "expected_source_table",
            "expected_source_id",
            "expected_entity_type",
            "expected_timestamp_key",
            "expected_metadata_key",
        ),
        [
            # 1. TbEntradas INSERT (FEntrada set) → INTAKE_STARTED
            (
                "intake_insert",
                "TbEntradas",
                "INSERT",
                {
                    "IDEntrada": 1,
                    "NChip": "001",
                    "FEntrada": datetime(2024, 1, 1, tzinfo=UTC),
                    "FSalida": None,
                },
                ("FEntrada",),
                "INTAKE_STARTED",
                "TbEntradas",
                1,
                "intake",
                "FEntrada",
                None,
            ),
            # 2. TbEntradas UPDATE (FSalida NULL → date, no owner return) → INTAKE_COMPLETED
            (
                "intake_completed",
                "TbEntradas",
                "UPDATE",
                {
                    "IDEntrada": 1,
                    "FEntrada": datetime(2024, 1, 1, tzinfo=UTC),
                    "FSalida": datetime(2024, 2, 1, tzinfo=UTC),
                    "FEntregaAPropietario": None,
                },
                ("FSalida",),
                "INTAKE_COMPLETED",
                "TbEntradas",
                1,
                "intake",
                "FSalida",
                None,
            ),
            # 3. TbEntradas UPDATE (FEntregaAPropietario NULL → date) → OWNER_RETURNED
            (
                "owner_returned",
                "TbEntradas",
                "UPDATE",
                {
                    "IDEntrada": 1,
                    "FEntrada": datetime(2024, 1, 1, tzinfo=UTC),
                    "FSalida": datetime(2024, 2, 1, tzinfo=UTC),
                    "FEntregaAPropietario": datetime(2024, 3, 1, tzinfo=UTC),
                },
                ("FEntregaAPropietario",),
                "OWNER_RETURNED",
                "TbEntradas",
                1,
                "intake",
                "FEntregaAPropietario",
                None,
            ),
            # 4. TbAcogidaAnimal INSERT → FOSTER_STARTED
            (
                "foster_started",
                "TbAcogidaAnimal",
                "INSERT",
                {
                    "IDAcogida": 7,
                    "Nchip": "001",
                    "FInicio": datetime(2024, 4, 1, tzinfo=UTC),
                    "FFinal": None,
                },
                ("FInicio",),
                "FOSTER_STARTED",
                "TbAcogidaAnimal",
                7,
                "foster",
                "FInicio",
                None,
            ),
            # 5. TbAcogidaAnimal UPDATE (FFinal NULL → date) → FOSTER_RETURNED
            (
                "foster_returned",
                "TbAcogidaAnimal",
                "UPDATE",
                {"IDAcogida": 7, "FFinal": datetime(2024, 5, 1, tzinfo=UTC)},
                ("FFinal",),
                "FOSTER_RETURNED",
                "TbAcogidaAnimal",
                7,
                "foster",
                "FFinal",
                None,
            ),
            # 6. TbAdopcion INSERT → ADOPTION_STARTED
            (
                "adoption_started",
                "TbAdopcion",
                "INSERT",
                {
                    "IDAdopcion": 99,
                    "NCHIP": "001",
                    "FAdopcion": datetime(2024, 6, 1, tzinfo=UTC),
                    "FDevolucion": None,
                },
                ("FAdopcion",),
                "ADOPTION_STARTED",
                "TbAdopcion",
                99,
                "adoption",
                "FAdopcion",
                None,
            ),
            # 7. TbAdopcion UPDATE (FDevolucion NULL → date) → ADOPTION_RETURNED
            (
                "adoption_returned",
                "TbAdopcion",
                "UPDATE",
                {"IDAdopcion": 99, "FDevolucion": datetime(2024, 7, 1, tzinfo=UTC)},
                ("FDevolucion",),
                "ADOPTION_RETURNED",
                "TbAdopcion",
                99,
                "adoption",
                "FDevolucion",
                None,
            ),
            # 8. TbFichaAnimal UPDATE (FDefuncion NULL → date) → DEATH_RECORDED
            #    + pre_death_state in metadata.
            #
            #    P1 #2 fix: ``legacy_source_id`` is ``None`` for
            #    ``DEATH_RECORDED`` because ``NCHIP`` is a free-text
            #    string in the legacy mapping (animal.yaml key_field)
            #    and the chip identity is already carried on the
            #    parent FK ``animal_id`` after PR 4 resolves it. The
            #    applier no longer needs the int-coerced NCHIP as
            #    ``legacy_source_id``.
            (
                "death_recorded",
                "TbFichaAnimal",
                "UPDATE",
                {
                    "NCHIP": "001",
                    "FDefuncion": datetime(2024, 8, 1, tzinfo=UTC),
                    "Situacion": "Albergue",
                    "UltimoEstadoAntesDeFallecido": "Albergue",
                },
                ("FDefuncion",),
                "DEATH_RECORDED",
                "TbFichaAnimal",
                None,
                "death",
                "FDefuncion",
                "pre_death_state",
            ),
        ],
        ids=[
            "01_intake_insert",
            "02_intake_completed",
            "03_owner_returned",
            "04_foster_started",
            "05_foster_returned",
            "06_adoption_started",
            "07_adoption_returned",
            "08_death_recorded",
        ],
    )
    def test_diff_to_event_mapping(
        self,
        name: str,  # noqa: ARG002
        legacy_table: str,
        op: str,
        legacy_row: dict[str, object],
        changed_fields: tuple[str, ...],
        expected_event_type: str,
        expected_source_table: str,
        expected_source_id: int | None,
        expected_entity_type: str,
        expected_timestamp_key: str,
        expected_metadata_key: str | None,
    ) -> None:
        """One parametrized test per diff→event combination (8 cases)."""
        from migration.reporting import Diff
        from migration.semantic_events import translate_diff

        diff = Diff(
            op=op,  # type: ignore[arg-type]
            key=str(
                legacy_row.get("NCHIP")
                or legacy_row.get("IDEntrada")
                or legacy_row.get("IDAcogida")
                or legacy_row.get("IDAdopcion")
                or "x"
            ),
            legacy_row=legacy_row,  # type: ignore[arg-type]
            changed_fields=changed_fields,
        )
        events = translate_diff(diff, _mapping_for(legacy_table))
        assert len(events) == 1, (
            f"case {name!r}: expected exactly one event, got {len(events)}: {events!r}"
        )
        ev = events[0]
        assert ev.event_type == expected_event_type, (
            f"case {name!r}: expected event_type {expected_event_type!r}, got {ev.event_type!r}"
        )
        assert ev.legacy_source_table == expected_source_table
        assert ev.legacy_source_id == expected_source_id
        assert ev.source_entity_type == expected_entity_type
        # Timestamp must equal the field value the diff triggered on.
        assert ev.event_timestamp == legacy_row[expected_timestamp_key]
        # Metadata only populated for DEATH_RECORDED today.
        if expected_metadata_key is None:
            assert ev.metadata is None
        else:
            assert ev.metadata is not None
            assert ev.metadata[expected_metadata_key] == legacy_row["UltimoEstadoAntesDeFallecido"]


# --- TestSemanticEventsEdgeCases: negative paths -------------------------


class TestSemanticEventsEdgeCases:
    """Negative-path coverage for ``translate_diff``.

    Branches not exercised by the 8 happy-path tests: NOOP / DELETE
    ops, INSERTs on non-lifecycle tables or with missing timestamp,
    UPDATEs that don't transition the relevant end-date field, and
    malformed legacy values. Each test exercises exactly one branch so
    a regression points at the failing line.
    """

    def test_noop_diff_returns_empty_list(self) -> None:
        """A NOOP diff produces no event (diff engine already filtered)."""
        from migration.reporting import Diff
        from migration.semantic_events import translate_diff

        diff = Diff(op="NOOP", key="1")
        assert translate_diff(diff, _mapping_for("TbEntradas")) == []

    def test_delete_diff_returns_empty_list(self) -> None:
        """A DELETE diff produces no event (deletes are not lifecycle transitions)."""
        from migration.reporting import Diff
        from migration.semantic_events import translate_diff

        diff = Diff(op="DELETE", key="1", legacy_row={"IDEntrada": 1})
        assert translate_diff(diff, _mapping_for("TbEntradas")) == []

    def test_insert_ficha_without_fdefuncion_returns_empty(self) -> None:
        """INSERT on TbFichaAnimal without FDefuncion → no event.

        Ficha registration is not a lifecycle transition; only death
        registration triggers a DEATH_RECORDED event.
        """
        from migration.reporting import Diff
        from migration.semantic_events import translate_diff

        diff = Diff(
            op="INSERT",
            key="001",
            legacy_row={"NCHIP": "001", "FDefuncion": None},
            changed_fields=("NCHIP",),
        )
        assert translate_diff(diff, _mapping_for("TbFichaAnimal")) == []

    def test_insert_entrada_without_fentrada_returns_empty(self) -> None:
        """INSERT on TbEntradas with FEntrada missing → no event.

        The event timestamp MUST come from FEntrada; without it the
        translator refuses to invent one.
        """
        from migration.reporting import Diff
        from migration.semantic_events import translate_diff

        diff = Diff(
            op="INSERT",
            key="1",
            legacy_row={"IDEntrada": 1, "FEntrada": None},
            changed_fields=("FEntrada",),
        )
        assert translate_diff(diff, _mapping_for("TbEntradas")) == []

    def test_update_acogida_without_ffinal_returns_empty(self) -> None:
        """UPDATE on TbAcogidaAnimal without FFinal transition → no event."""
        from migration.reporting import Diff
        from migration.semantic_events import translate_diff

        diff = Diff(
            op="UPDATE",
            key="7",
            legacy_row={"IDAcogida": 7, "FFinal": None},
            changed_fields=("Observaciones",),
        )
        assert translate_diff(diff, _mapping_for("TbAcogidaAnimal")) == []

    def test_update_adopcion_without_fdevolucion_returns_empty(self) -> None:
        """UPDATE on TbAdopcion without FDevolucion transition → no event."""
        from migration.reporting import Diff
        from migration.semantic_events import translate_diff

        diff = Diff(
            op="UPDATE",
            key="99",
            legacy_row={"IDAdopcion": 99, "FDevolucion": None},
            changed_fields=("Observaciones",),
        )
        assert translate_diff(diff, _mapping_for("TbAdopcion")) == []

    def test_update_ficha_without_fdefuncion_returns_empty(self) -> None:
        """UPDATE on TbFichaAnimal without FDefuncion transition → no event."""
        from migration.reporting import Diff
        from migration.semantic_events import translate_diff

        diff = Diff(
            op="UPDATE",
            key="001",
            legacy_row={"NCHIP": "001", "FDefuncion": None},
            changed_fields=("Situacion",),
        )
        assert translate_diff(diff, _mapping_for("TbFichaAnimal")) == []

    def test_update_entrada_without_end_dates_returns_empty(self) -> None:
        """UPDATE on TbEntradas without FSalida and without FEntregaAPropietario → no event."""
        from migration.reporting import Diff
        from migration.semantic_events import translate_diff

        diff = Diff(
            op="UPDATE",
            key="1",
            legacy_row={"IDEntrada": 1, "FSalida": None, "FEntregaAPropietario": None},
            changed_fields=("Observaciones",),
        )
        assert translate_diff(diff, _mapping_for("TbEntradas")) == []

    def test_insert_with_iso_string_timestamp_is_parsed(self) -> None:
        """The translator parses ISO-8601 strings into ``datetime``.

        Mirrors what the Dysflow snapshot loader produces for Access
        date columns.
        """
        from migration.reporting import Diff
        from migration.semantic_events import translate_diff

        diff = Diff(
            op="INSERT",
            key="1",
            legacy_row={
                "IDEntrada": 1,
                "FEntrada": "2024-01-01T00:00:00+00:00",
            },
            changed_fields=("FEntrada",),
        )
        events = translate_diff(diff, _mapping_for("TbEntradas"))
        assert len(events) == 1
        assert events[0].event_timestamp == datetime(2024, 1, 1, tzinfo=UTC)

    def test_insert_with_malformed_timestamp_raises_value_error(self) -> None:
        """Unparseable timestamp strings raise ``ValueError`` (not silently dropped).

        The applier surfaces the error via
        ``MigrationReport.reconciliation_errors`` so the operator can
        fix the legacy data; a silent drop would hide a real bug.
        """
        from migration.reporting import Diff
        from migration.semantic_events import translate_diff

        diff = Diff(
            op="INSERT",
            key="1",
            legacy_row={"IDEntrada": 1, "FEntrada": "not-a-date"},
            changed_fields=("FEntrada",),
        )
        with pytest.raises(ValueError, match="FEntrada"):
            translate_diff(diff, _mapping_for("TbEntradas"))

    def test_insert_with_uncoerceable_int_raises_value_error(self) -> None:
        """A legacy PK that cannot be coerced to int raises ``ValueError``."""
        from migration.reporting import Diff
        from migration.semantic_events import translate_diff

        diff = Diff(
            op="INSERT",
            key="x",
            legacy_row={"IDEntrada": "not-an-int", "FEntrada": "2024-01-01"},
            changed_fields=("FEntrada",),
        )
        with pytest.raises(ValueError, match="IDEntrada"):
            translate_diff(diff, _mapping_for("TbEntradas"))

    def test_insert_on_unknown_table_returns_empty(self) -> None:
        """INSERT on a table not in the lifecycle catalog → no event.

        Defensive: only the 4 documented tables produce events.
        Anything else is silently dropped (the row still gets written
        via the regular applier; it just doesn't surface an event).
        """
        from migration.reporting import Diff
        from migration.semantic_events import translate_diff

        diff = Diff(
            op="INSERT",
            key="1",
            legacy_row={"IDVoluntario": 1},
            changed_fields=("IDVoluntario",),
        )
        assert translate_diff(diff, _mapping_for("TbVoluntariosParaAutorrellenables")) == []


# --- TestDeathRecordedChipNotInt (P1 #2 regression) ----------------------


class TestDeathRecordedChipNotInt:
    """P1 #2 regression: ``DEATH_RECORDED`` must not coerce ``NCHIP`` to int.

    ``TbFichaAnimal.key_field`` (= ``NCHIP``) is a free-text string in
    ``app/core/migration/mappings/animal.yaml`` (legacy PK preserved as
    identity transform; no int conversion). Real APAP values include
    alphanumeric forms like ``"2030A"``, ``"ES-12345"``, and the
    numeric-looking ``"001"`` (which is a chip label, not the integer
    ``1`` — the leading zero is part of the identity).

    The previous implementation called ``_read_int(row, "NCHIP")``
    which raised ``ValueError`` on alphanumeric values and silently
    truncated ``"001"`` to ``1``, losing the actual chip identity.

    Fix: ``DEATH_RECORDED`` events now carry ``legacy_source_id=None``
    because the chip identity is already on the parent FK
    (``animal_id``) after PR 4 resolves it. The applier no longer
    needs an int-coerced NCHIP on the event itself.
    """

    def test_alphanumeric_nchip_does_not_raise(self) -> None:
        """``NCHIP="ABC-123"`` → translation succeeds, ``legacy_source_id=None``.

        The pre-fix implementation raised
        ``ValueError: Cannot coerce legacy 'NCHIP' value 'ABC-123' into int``.
        """
        from migration.reporting import Diff
        from migration.semantic_events import translate_diff

        diff = Diff(
            op="UPDATE",
            key="ABC-123",
            legacy_row={
                "NCHIP": "ABC-123",
                "FDefuncion": datetime(2024, 8, 1, tzinfo=UTC),
                "Situacion": "Albergue",
                "UltimoEstadoAntesDeFallecido": "Albergue",
            },
            changed_fields=("FDefuncion",),
        )
        events = translate_diff(diff, _mapping_for("TbFichaAnimal"))
        assert len(events) == 1
        assert events[0].event_type == "DEATH_RECORDED"
        assert events[0].legacy_source_id is None
        assert events[0].metadata == {"pre_death_state": "Albergue"}

    def test_alphanumeric_nchip_with_year_prefix_does_not_raise(self) -> None:
        """``NCHIP="2030A"`` → translation succeeds (real APAP chip pattern).

        Mirrors a common APAP chip pattern (year prefix + letter
        suffix). Must NOT raise and must NOT silently truncate.
        """
        from migration.reporting import Diff
        from migration.semantic_events import translate_diff

        diff = Diff(
            op="UPDATE",
            key="2030A",
            legacy_row={
                "NCHIP": "2030A",
                "FDefuncion": datetime(2024, 9, 15, tzinfo=UTC),
                "UltimoEstadoAntesDeFallecido": "Acogida",
            },
            changed_fields=("FDefuncion",),
        )
        events = translate_diff(diff, _mapping_for("TbFichaAnimal"))
        assert len(events) == 1
        assert events[0].legacy_source_id is None
        assert events[0].metadata == {"pre_death_state": "Acogida"}

    def test_numeric_nchip_does_not_silently_coerce_to_int(self) -> None:
        """``NCHIP="001"`` → translation succeeds and ``legacy_source_id`` is None.

        Even when ``NCHIP`` looks numeric, ``legacy_source_id`` is
        ``None`` under fix (b) — we deliberately do NOT surface the
        coerced int because (1) the original string identity is lost
        on int coercion (the leading zero), and (2) the chip identity
        is already on the parent FK after PR 4.
        """
        from migration.reporting import Diff
        from migration.semantic_events import translate_diff

        diff = Diff(
            op="UPDATE",
            key="001",
            legacy_row={
                "NCHIP": "001",
                "FDefuncion": datetime(2024, 10, 1, tzinfo=UTC),
                "UltimoEstadoAntesDeFallecido": "Adoptado",
            },
            changed_fields=("FDefuncion",),
        )
        events = translate_diff(diff, _mapping_for("TbFichaAnimal"))
        assert len(events) == 1
        assert events[0].event_type == "DEATH_RECORDED"
        # Must NOT be the silently-coerced int(1) — must be None.
        assert events[0].legacy_source_id is None
        assert events[0].metadata == {"pre_death_state": "Adoptado"}
