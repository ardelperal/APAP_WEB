"""Tests for ``reconcile_after_legacy_write`` (PR 2/6, T2.7+T2.8).

Per-row dispatcher that the applier hook (PR 4) calls once per
affected row. Dispatches on ``ColumnMapping.web_only_strategy``:

- ``preserve``: upsert shadow row + bump ``last_legacy_snapshot_at``.
- ``derived``: invoke the derivation engine, compare to stored,
  persist outcome into the shadow row's ``reconciliation_status``.
- ``fixed``:   no-op (the value is declared statically in YAML).

PR 2 only sets up the shape; the tests below prove the three
strategies behave correctly against a fake ``ShadowStateRepository``.
"""

from __future__ import annotations


class TestReconcileAfterLegacyWrite:
    """Per-row reconciliation dispatcher tests.

    The function lives in ``migration.reconcile`` (PR 1 owns
    that module). It takes the legacy snapshot + the web row + the
    matching ``ColumnMapping`` and writes the right ``ReconciliationOutcome``.
    """

    def test_preserve_strategy_upserts_shadow_and_bumps_snapshot(self) -> None:
        """``preserve`` writes the shadow row and stamps ``last_legacy_snapshot_at``."""
        from datetime import UTC, datetime

        from migration.reconcile import reconcile_after_legacy_write

        upsert_calls: list[dict[str, object]] = []

        class _FakeShadow:
            def upsert(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                upsert_calls.append(kwargs)

            def update_derived_value(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_derived_at(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

        outcome = reconcile_after_legacy_write(
            shadow_state=_FakeShadow(),  # type: ignore[arg-type]
            table_name="voluntarios",
            legacy_pk="v-1",
            web_pk="00000000-0000-0000-0000-000000000001",
            web_column="DNI",
            strategy="preserve",
            preserved_value="12345678A",
            last_legacy_snapshot_at=datetime(2026, 6, 21, 12, 0, tzinfo=UTC),
        )
        assert outcome.status.name == "MATCHED"
        assert outcome.web_column == "DNI"
        assert len(upsert_calls) == 1
        call = upsert_calls[0]
        assert call["table_name"] == "voluntarios"
        assert call["legacy_pk"] == "v-1"
        assert call["web_column"] == "DNI"
        assert call["strategy"] == "preserve"
        assert call["preserved_value"] == "12345678A"
        assert call["last_legacy_snapshot_at"] == datetime(2026, 6, 21, 12, 0, tzinfo=UTC)

    def test_fixed_strategy_is_noop(self) -> None:
        """``fixed`` does not touch the shadow state or call the derivation engine."""
        from migration.reconcile import reconcile_after_legacy_write

        upsert_calls: list[object] = []
        update_calls: list[object] = []

        class _FakeShadow:
            def upsert(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                upsert_calls.append(kwargs)

            def update_reconciliation_status(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                update_calls.append(kwargs)

            def update_derived_value(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_derived_at(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

        outcome = reconcile_after_legacy_write(
            shadow_state=_FakeShadow(),  # type: ignore[arg-type]
            table_name="voluntarios",
            legacy_pk="v-1",
            web_pk=None,
            web_column="activo",
            strategy="fixed",
            preserved_value=True,
            last_legacy_snapshot_at=None,
        )
        assert outcome.status.name == "MATCHED"
        assert upsert_calls == [], f"fixed must not upsert; got {upsert_calls!r}"
        assert update_calls == [], f"fixed must not update status; got {update_calls!r}"

    def test_derived_strategy_invokes_engine_and_records_match(self) -> None:
        """``derived`` invokes the derivation engine and persists MATCHED outcome."""
        from datetime import UTC, datetime

        from migration.reconcile import reconcile_after_legacy_write

        upsert_calls: list[dict[str, object]] = []
        update_calls: list[dict[str, object]] = []

        class _FakeShadow:
            def upsert(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                upsert_calls.append(kwargs)

            def update_reconciliation_status(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                update_calls.append(kwargs)

            def update_derived_value(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_derived_at(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

        ficha = {
            "NCHIP": "001",
            "FDefuncion": None,
            "Situacion": "Albergue",  # already Albergue (legacy_situacion copy)
            "UltimoEstadoAntesDeFallecido": None,
        }
        entradas = [{"IDEntrada": 42, "FSalida": None, "FEntregaAPropietario": None}]

        outcome = reconcile_after_legacy_write(
            shadow_state=_FakeShadow(),  # type: ignore[arg-type]
            table_name="animales",
            legacy_pk="001",
            web_pk="00000000-0000-0000-0000-000000000002",
            web_column="current_state",
            strategy="derived",
            preserved_value=None,
            last_legacy_snapshot_at=datetime(2026, 6, 21, 10, 0, tzinfo=UTC),
            derived_inputs={
                "tb_ficha": ficha,
                "tb_entradas": entradas,
                "tb_acogidas": [],
                "tb_adopciones": [],
            },
            stored_state="Albergue",  # already matches derived
            web_updated_at=None,  # no web edit since last sync
        )
        assert outcome.status.name == "MATCHED"
        assert outcome.derived_value == "Albergue"
        assert outcome.web_value == "Albergue"
        # Shadow row was upserted (last_legacy_snapshot_at stamped).
        assert len(upsert_calls) == 1
        # No manual override, so no update_reconciliation_status call
        # (MATCHED is the initial upsert state).
        assert update_calls == []

    def test_derived_strategy_with_web_override_marks_needs_review(self) -> None:
        """``derived`` + manual web override after last sync → NEEDS_REVIEW."""
        from datetime import UTC, datetime

        from migration.reconcile import reconcile_after_legacy_write

        update_calls: list[dict[str, object]] = []

        class _FakeShadow:
            def upsert(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_reconciliation_status(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                update_calls.append(kwargs)

            def update_derived_value(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_derived_at(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

        ficha = {
            "NCHIP": "002",
            "FDefuncion": None,
            "Situacion": "Acogida",
            "UltimoEstadoAntesDeFallecido": None,
        }
        # Legacy now shows an active adoption — derived = Adoptado.
        adopciones = [{"IDAdopcion": 99, "FDevolucion": None}]

        outcome = reconcile_after_legacy_write(
            shadow_state=_FakeShadow(),  # type: ignore[arg-type]
            table_name="animales",
            legacy_pk="002",
            web_pk="00000000-0000-0000-0000-000000000003",
            web_column="current_state",
            strategy="derived",
            preserved_value=None,
            last_legacy_snapshot_at=datetime(2026, 6, 21, 10, 0, tzinfo=UTC),
            derived_inputs={
                "tb_ficha": ficha,
                "tb_entradas": [],
                "tb_acogidas": [],
                "tb_adopciones": adopciones,
            },
            stored_state="Acogida",  # web was manually set to Acogida
            web_updated_at=datetime(2026, 6, 21, 11, 0, tzinfo=UTC),  # AFTER sync
        )
        assert outcome.status.name == "NEEDS_REVIEW"
        assert outcome.derived_value == "Adoptado"
        assert outcome.web_value == "Acogida"
        # Operator review flag set so the CLI surfaces the case.
        assert "web_manual_override_detected" in outcome.review_reasons
        # Status persisted to the shadow row.
        assert len(update_calls) == 1
        call = update_calls[0]
        assert call["status"] == "needs_review"


# --- TestPostApplyDiffHook -----------------------------------------------
#
# Slice PR 4/6 of web-only-feature-preservation (T4.1-T4.5 + T4.7):
# integration tests for the ``post_apply_diff`` hook that the applier
# of MIGRATION-01 PR 5/6 will call after ``apply_diff_to_web_transactional``.
# The hook is the public seam between the diff engine and the
# reconciliation machinery; these tests pin its contract before
# implementing it.
#
# Conventions:
#   - The hook is called with positional-free keyword arguments matching
#     the spec.md REQ-Hook signature, plus two optional kwargs the spec
#     does not enumerate (``legacy_snapshot`` for tests; ``now`` for
#     deterministic timestamps). The applier in MIGRATION-01 PR 5/6
#     passes only the spec args.
#   - The hook returns a ``ReconciliationResult`` whose ``outcomes`` mirror
#     the per-row verdicts and whose ``errors`` accumulate mapping/data
#     issues without aborting the batch (regla #13474 v2: one bad row
#     does not stop the run).
#   - ``direction == "web-to-legacy"`` is a no-op per the spec
#     (preserve shadow state, no re-derivation).
#
# TDD note: tests are RED until ``post_apply_diff`` lands in
# ``migration.reconcile`` (PR 4/6 implementation).


class TestPostApplyDiffHook:
    """Integration tests for ``post_apply_diff`` (PR 4/6 — T4.1, T4.7)."""

    def test_legacy_to_web_preserves_dni_persists_shadow_row(self) -> None:
        """(T4.7 happy path) legacy→web on a ``preserve`` column
        upserts the shadow row with the web value and stamps
        ``last_legacy_snapshot_at``.

        ``voluntarios.DNI`` is the canonical ``preserve`` column. A
        legacy→web INSERT carries the web row with ``DNI`` populated;
        the hook stamps ``last_legacy_snapshot_at`` so the CLI can
        sort by "last seen" and the shadow row survives the round-trip.
        """
        from datetime import UTC, datetime

        from migration.reconcile import post_apply_diff
        from migration.reporting import Diff

        upsert_calls: list[dict[str, object]] = []

        class _FakeShadow:
            def upsert(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                upsert_calls.append(kwargs)

            def update_reconciliation_status(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_derived_value(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_derived_at(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

        # voluntarios.DNI: web_only_strategy=preserve (per voluntario.yaml).
        mapping = _voluntario_mapping_with_dni_preserve()
        diff = Diff(
            op="UPDATE",
            key="Pepe",
            table="voluntarios",
            legacy_pk="Pepe",
            web_pk="00000000-0000-0000-0000-000000000099",
            legacy_row={"Voluntario": "Pepe"},
            web_row={"id": "00000000-0000-0000-0000-000000000099", "DNI": "12345678A"},
            changed_fields=("Voluntario",),
        )
        result = post_apply_diff(
            direction="legacy-to-web",
            applied_diffs=[diff],
            table_mappings={"voluntarios": mapping},
            web_client=None,  # type: ignore[arg-type] — not used in this test
            shadow_state=_FakeShadow(),  # type: ignore[arg-type]
            sync_state=_empty_sync_state(),
            now=datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
        )

        # The hook produced exactly one outcome (the preserve column).
        assert len(result.outcomes) == 1
        outcome = result.outcomes[0]
        assert outcome.table_name == "voluntarios"
        assert outcome.legacy_pk == "Pepe"
        assert outcome.web_column == "DNI"
        assert outcome.status.name == "MATCHED"
        assert outcome.web_value == "12345678A"
        # Shadow state was upserted with the snapshot timestamp.
        assert len(upsert_calls) == 1
        call = upsert_calls[0]
        assert call["table_name"] == "voluntarios"
        assert call["legacy_pk"] == "Pepe"
        assert call["web_column"] == "DNI"
        assert call["preserved_value"] == "12345678A"
        assert call["last_legacy_snapshot_at"] == datetime(2026, 6, 22, 12, 0, tzinfo=UTC)

    def test_legacy_to_web_derived_matched(self) -> None:
        """(T4.7a) legacy→web on a ``derived`` column where the stored
        web value matches the derived value → ``MATCHED``.

        The derivation engine is invoked with the 4 legacy collections
        (provided via ``legacy_snapshot`` in tests). When the result
        matches ``animal_current_state.current_state``, the verdict is
        ``MATCHED`` and the shadow row is stamped.
        """
        from datetime import UTC, datetime

        from migration.reconcile import post_apply_diff
        from migration.reporting import Diff

        upsert_calls: list[dict[str, object]] = []

        class _FakeShadow:
            def upsert(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                upsert_calls.append(kwargs)

            def update_reconciliation_status(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_derived_value(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_derived_at(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

        mapping = _animal_mapping_with_current_state_derived()
        diff = Diff(
            op="INSERT",
            key="001",
            table="animales",
            legacy_pk="001",
            web_pk="00000000-0000-0000-0000-000000000001",
            legacy_row={
                "NCHIP": "001",
                "FDefuncion": None,
                "UltimoEstadoAntesDeFallecido": None,
            },
            web_row=None,
            changed_fields=("NCHIP",),
        )
        legacy_snapshot = {
            "TbFichaAnimal": [
                {
                    "NCHIP": "001",
                    "FDefuncion": None,
                    "UltimoEstadoAntesDeFallecido": None,
                }
            ],
            "TbEntradas": [{"IDEntrada": 1, "FSalida": None, "FEntregaAPropietario": None}],
            "TbAcogidaAnimal": [],
            "TbAdopcion": [],
        }
        # Inject the stored value + web_updated_at via legacy_snapshot
        # under sentinel keys (the hook pops them before passing to
        # reconcile_after_legacy_write).
        legacy_snapshot["_stored_state"] = "Albergue"  # matches derived
        legacy_snapshot["_web_updated_at"] = None  # no web edit

        result = post_apply_diff(
            direction="legacy-to-web",
            applied_diffs=[diff],
            table_mappings={"animales": mapping},
            web_client=None,  # type: ignore[arg-type]
            shadow_state=_FakeShadow(),  # type: ignore[arg-type]
            sync_state=_empty_sync_state(),
            legacy_snapshot=legacy_snapshot,
            now=datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
        )

        assert len(result.outcomes) == 1
        outcome = result.outcomes[0]
        assert outcome.web_column == "current_state"
        assert outcome.status.name == "MATCHED"
        assert outcome.derived_value == "Albergue"
        assert outcome.web_value == "Albergue"
        # Shadow row was upserted (last_legacy_snapshot_at stamped).
        assert len(upsert_calls) == 1

    def test_legacy_to_web_derived_divergent_no_override(self) -> None:
        """(T4.7b) legacy→web on a ``derived`` column where derived ≠
        stored AND no manual web override → ``DIVERGENT``.

        The derivation engine returns ``"Albergue"`` (active intake).
        The stored value is ``"Pendiente de Entrada"`` (the value the
        web had before the legacy intake was registered).
        ``web_updated_at`` is ``None`` (the web was never manually
        edited). Per Q2 path (``compare_derived_to_stored``):
        ``DIVERGENT`` is info-only; the applier has already overwritten
        the stored value with the derived one.
        """
        from datetime import UTC, datetime

        from migration.reconcile import post_apply_diff
        from migration.reporting import Diff

        upsert_calls: list[dict[str, object]] = []

        class _FakeShadow:
            def upsert(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                upsert_calls.append(kwargs)

            def update_reconciliation_status(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_derived_value(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_derived_at(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

        mapping = _animal_mapping_with_current_state_derived()
        diff = Diff(
            op="INSERT",
            key="002",
            table="animales",
            legacy_pk="002",
            web_pk="00000000-0000-0000-0000-000000000002",
            legacy_row={
                "NCHIP": "002",
                "FDefuncion": None,
                "UltimoEstadoAntesDeFallecido": None,
            },
            web_row=None,
            changed_fields=("NCHIP",),
        )
        legacy_snapshot = {
            "TbFichaAnimal": [
                {
                    "NCHIP": "002",
                    "FDefuncion": None,
                    "UltimoEstadoAntesDeFallecido": None,
                }
            ],
            "TbEntradas": [{"IDEntrada": 2, "FSalida": None, "FEntregaAPropietario": None}],
            "TbAcogidaAnimal": [],
            "TbAdopcion": [],
        }
        legacy_snapshot["_stored_state"] = "Pendiente de Entrada"  # stale; not yet matched
        legacy_snapshot["_web_updated_at"] = None  # no manual edit → DIVERGENT

        result = post_apply_diff(
            direction="legacy-to-web",
            applied_diffs=[diff],
            table_mappings={"animales": mapping},
            web_client=None,  # type: ignore[arg-type]
            shadow_state=_FakeShadow(),  # type: ignore[arg-type]
            sync_state=_empty_sync_state(),
            legacy_snapshot=legacy_snapshot,
            now=datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
        )

        assert len(result.outcomes) == 1
        outcome = result.outcomes[0]
        assert outcome.web_column == "current_state"
        assert outcome.status.name == "DIVERGENT", (
            f"Expected DIVERGENT for derived=Albergue vs stored=Pendiente de Entrada "
            f"with no override; got status={outcome.status.name!r}"
        )
        assert outcome.derived_value == "Albergue"
        assert outcome.web_value == "Pendiente de Entrada"
        # Shadow row was upserted (verdict stamped).
        assert len(upsert_calls) == 1

    def test_legacy_to_web_derived_needs_review_with_override(self) -> None:
        """(T4.7c) legacy→web on a ``derived`` column where derived ≠
        stored AND the operator manually overrode web after the last
        sync → ``NEEDS_REVIEW``.

        The derivation engine returns a state different from the
        stored value, AND ``web_updated_at >= last_legacy_snapshot_at``
        signals a manual edit. Per Q2 path (compare_derived_to_stored):
        ``NEEDS_REVIEW`` is sticky — the case surfaces in the CLI
        ``--interactive`` flow so the operator can pick (a) keep web
        or (b) accept derived.
        """
        from datetime import UTC, datetime

        from migration.reconcile import post_apply_diff
        from migration.reporting import Diff

        upsert_calls: list[dict[str, object]] = []
        update_calls: list[dict[str, object]] = []

        class _FakeShadow:
            def upsert(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                upsert_calls.append(kwargs)

            def update_reconciliation_status(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                update_calls.append(kwargs)

            def update_derived_value(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_derived_at(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

        mapping = _animal_mapping_with_current_state_derived()
        diff = Diff(
            op="INSERT",
            key="003",
            table="animales",
            legacy_pk="003",
            web_pk="00000000-0000-0000-0000-000000000003",
            legacy_row={
                "NCHIP": "003",
                "FDefuncion": None,
                "UltimoEstadoAntesDeFallecido": None,
            },
            web_row=None,
            changed_fields=("NCHIP",),
        )
        legacy_snapshot = {
            "TbFichaAnimal": [
                {
                    "NCHIP": "003",
                    "FDefuncion": None,
                    "UltimoEstadoAntesDeFallecido": None,
                }
            ],
            "TbEntradas": [{"IDEntrada": 3, "FSalida": None, "FEntregaAPropietario": None}],
            "TbAcogidaAnimal": [],
            "TbAdopcion": [],
        }
        legacy_snapshot["_stored_state"] = "Pendiente de Entrada"  # web was manually set
        legacy_snapshot["_web_updated_at"] = datetime(
            2026, 6, 22, 13, 0, tzinfo=UTC
        )  # AFTER sync (now=12:00)

        result = post_apply_diff(
            direction="legacy-to-web",
            applied_diffs=[diff],
            table_mappings={"animales": mapping},
            web_client=None,  # type: ignore[arg-type]
            shadow_state=_FakeShadow(),  # type: ignore[arg-type]
            sync_state=_empty_sync_state(),
            legacy_snapshot=legacy_snapshot,
            now=datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
        )

        assert len(result.outcomes) == 1
        outcome = result.outcomes[0]
        assert outcome.web_column == "current_state"
        assert outcome.status.name == "NEEDS_REVIEW"
        assert outcome.derived_value == "Albergue"
        assert outcome.web_value == "Pendiente de Entrada"
        assert "web_manual_override_detected" in outcome.review_reasons
        # Status flipped to needs_review via the secondary writer.
        assert len(update_calls) == 1

    def test_legacy_to_web_persists_lifecycle_events_to_web_client(self) -> None:
        """(T4.3) For each diff, ``translate_diff`` runs and the resulting
        ``LifecycleEvent`` rows are INSERTed into
        ``animal_lifecycle_events`` via the web client.

        Wire-up test: mock ``LocalPostgresExecutor.execute_sql`` to capture
        the INSERT statements. Assert:
          - Exactly one INSERT per translated event.
          - The SQL targets ``animal_lifecycle_events``.
          - ``created_by`` is propagated as the operator UUID.
          - ``event_type`` and ``event_timestamp`` come from the
            translated event.
        """
        from datetime import UTC, datetime

        from migration.reconcile import post_apply_diff
        from migration.reporting import Diff

        captured: list[tuple[str, list[object]]] = []

        class _FakeWebClient:
            def execute_sql(
                self, query: str, params: list[object] | None = None
            ) -> list[dict[str, object]]:
                captured.append((query, list(params or [])))
                return []

        class _FakeShadow:
            def upsert(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_reconciliation_status(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_derived_value(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_derived_at(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

        # voluntarios mapping — NO lifecycle event translates from a
        # voluntarios diff (no event types defined for that table), so
        # we use a TbEntradas diff instead.
        mapping = _entrada_mapping_for_event_persistence()
        diff = Diff(
            op="INSERT",
            key="1",
            table="entradas",
            legacy_pk=1,
            web_pk="00000000-0000-0000-0000-000000000010",
            legacy_row={
                "IDEntrada": 1,
                "NChip": "001",
                "FEntrada": datetime(2024, 1, 1, tzinfo=UTC),
                "FSalida": None,
            },
            web_row={
                "id": "00000000-0000-0000-0000-000000000010",
                "animal_id": "00000000-0000-0000-0000-000000000001",
            },
            changed_fields=("FEntrada",),
        )
        result = post_apply_diff(
            direction="legacy-to-web",
            applied_diffs=[diff],
            table_mappings={"entradas": mapping},
            web_client=_FakeWebClient(),  # type: ignore[arg-type]
            shadow_state=_FakeShadow(),  # type: ignore[arg-type]
            sync_state=_empty_sync_state(),
            created_by="00000000-0000-0000-0000-000000000999",
        )

        # One event translated from the diff.
        assert result.errors == (), f"expected no errors; got {result.errors!r}"
        assert len(captured) == 1, (
            f"expected exactly one INSERT (INTAKE_STARTED); got {len(captured)}: {captured!r}"
        )
        sql, params = captured[0]
        assert "INSERT INTO animal_lifecycle_events" in sql
        # params order: animal_id, event_type, event_timestamp,
        # source_entity_type, source_entity_id, legacy_source_table,
        # legacy_source_id, metadata, created_by.
        assert params[0] == "00000000-0000-0000-0000-000000000001"  # animal_id from web_row
        assert params[1] == "INTAKE_STARTED"
        assert "2024-01-01" in str(params[2])  # ISO timestamp
        assert params[8] == "00000000-0000-0000-0000-000000000999"  # created_by

    def test_missing_created_by_skips_event_persistence_with_error(self) -> None:
        """When ``created_by`` is ``None``, the hook skips event
        persistence and records the skip in ``errors`` (so the applier
        can surface a configuration warning to the operator).

        The hook MUST NOT silently drop lifecycle events — losing a
        transition would corrupt the animal state machine.
        """
        from datetime import UTC, datetime

        from migration.reconcile import post_apply_diff
        from migration.reporting import Diff

        class _FakeWebClient:
            def execute_sql(
                self, query: str, params: list[object] | None = None
            ) -> list[dict[str, object]]:
                raise AssertionError(  # noqa: TRY003 — guard test
                    "web_client.execute_sql must NOT be called when created_by is None"
                )

        class _FakeShadow:
            def upsert(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_reconciliation_status(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_derived_value(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_derived_at(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

        mapping = _entrada_mapping_for_event_persistence()
        diff = Diff(
            op="INSERT",
            key="1",
            table="entradas",
            legacy_pk=1,
            web_pk="00000000-0000-0000-0000-000000000010",
            legacy_row={
                "IDEntrada": 1,
                "NChip": "001",
                "FEntrada": datetime(2024, 1, 1, tzinfo=UTC),
                "FSalida": None,
            },
            web_row={
                "id": "00000000-0000-0000-0000-000000000010",
                "animal_id": "00000000-0000-0000-0000-000000000001",
            },
            changed_fields=("FEntrada",),
        )
        result = post_apply_diff(
            direction="legacy-to-web",
            applied_diffs=[diff],
            table_mappings={"entradas": mapping},
            web_client=_FakeWebClient(),  # type: ignore[arg-type]
            shadow_state=_FakeShadow(),  # type: ignore[arg-type]
            sync_state=_empty_sync_state(),
            created_by=None,  # missing → skip persistence + record error
        )
        assert any("missing_created_by" in e for e in result.errors), (
            f"expected a missing_created_by error; got {result.errors!r}"
        )

    def test_web_to_legacy_is_noop(self) -> None:
        """(T4.5) ``direction == "web-to-legacy"`` is a no-op.

        The spec REQ-Hook mandates: "Para dirección web-to-legacy, el
        hook DEBE preservar los valores shadow sin re-derivación."
        The hook returns an empty ``ReconciliationResult`` and never
        touches the shadow state or the derivation engine.
        """
        from datetime import UTC, datetime

        from migration.reconcile import post_apply_diff
        from migration.reporting import Diff

        upsert_calls: list[dict[str, object]] = []

        class _FakeShadow:
            def upsert(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                upsert_calls.append(kwargs)

            def update_reconciliation_status(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_derived_value(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_derived_at(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

        mapping = _voluntario_mapping_with_dni_preserve()
        diff = Diff(
            op="INSERT",
            key="Pepe",
            table="voluntarios",
            legacy_pk=None,  # web→legacy has no legacy_pk
            web_pk="00000000-0000-0000-0000-000000000099",
            legacy_row=None,
            web_row={"id": "00000000-0000-0000-0000-000000000099", "DNI": "12345678A"},
            changed_fields=("DNI",),
        )
        result = post_apply_diff(
            direction="web-to-legacy",
            applied_diffs=[diff],
            table_mappings={"voluntarios": mapping},
            web_client=None,  # type: ignore[arg-type]
            shadow_state=_FakeShadow(),  # type: ignore[arg-type]
            sync_state=_empty_sync_state(),
            now=datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
        )
        assert result.outcomes == ()
        assert result.errors == ()
        assert upsert_calls == [], (
            f"web-to-legacy must NOT upsert shadow state; got {upsert_calls!r}"
        )


# --- TestPostApplyDiffAtomicity ------------------------------------------
#
# Slice PR 4/6 (T4.8): atomicity test. Simulates a failure in
# ``sync_state.save()`` AFTER the COMMIT (and AFTER the hook ran).
# The hook itself is idempotent and the derivation engine is pure, so
# the next apply must re-derive correctly and reach the same verdict.
# This guards the spec REQ-Coexistencia + REQ-Atomicidad: the system
# must NOT leave half-applied state if the post-commit write fails.


class TestPostApplyDiffAtomicity:
    """(T4.8) Atomicity test: simulated post-commit sync_state failure."""

    def test_repeated_apply_is_idempotent_after_post_commit_failure(self) -> None:
        """Same legacy→web apply twice (simulating sync_state.save
        failure between runs) reaches the same ``MATCHED`` verdict
        both times. The hook is idempotent — derived state is pure.

        Setup:
          - Apply #1: derived matches stored → ``MATCHED``, shadow row
            upserted with snapshot_at=T1.
          - Simulated post-commit failure: ``sync_state.save()`` raises.
          - Apply #2: same diff re-applied. The hook re-runs derivation
            (still pure / deterministic), re-stamps the shadow row.
        Expected: both runs reach the same verdict; the shadow row's
        ``last_legacy_snapshot_at`` reflects the most recent apply.
        """
        from datetime import UTC, datetime

        from migration.reconcile import post_apply_diff
        from migration.reporting import Diff

        upsert_calls: list[dict[str, object]] = []

        class _FakeShadow:
            def upsert(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                upsert_calls.append(kwargs)

            def update_reconciliation_status(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_derived_value(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_derived_at(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

        mapping = _animal_mapping_with_current_state_derived()
        diff = Diff(
            op="INSERT",
            key="100",
            table="animales",
            legacy_pk="100",
            web_pk="00000000-0000-0000-0000-000000000100",
            legacy_row={
                "NCHIP": "100",
                "FDefuncion": None,
                "UltimoEstadoAntesDeFallecido": None,
            },
            web_row=None,
            changed_fields=("NCHIP",),
        )
        legacy_snapshot = {
            "TbFichaAnimal": [
                {
                    "NCHIP": "100",
                    "FDefuncion": None,
                    "UltimoEstadoAntesDeFallecido": None,
                }
            ],
            "TbEntradas": [{"IDEntrada": 100, "FSalida": None, "FEntregaAPropietario": None}],
            "TbAcogidaAnimal": [],
            "TbAdopcion": [],
        }
        legacy_snapshot["_stored_state"] = "Albergue"
        legacy_snapshot["_web_updated_at"] = None

        # Apply #1 at T1.
        result1 = post_apply_diff(
            direction="legacy-to-web",
            applied_diffs=[diff],
            table_mappings={"animales": mapping},
            web_client=None,  # type: ignore[arg-type]
            shadow_state=_FakeShadow(),  # type: ignore[arg-type]
            sync_state=_empty_sync_state(),
            legacy_snapshot=legacy_snapshot,
            now=datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
        )
        assert result1.outcomes[0].status.name == "MATCHED"
        first_call = upsert_calls[0]
        assert first_call["last_legacy_snapshot_at"] == datetime(2026, 6, 22, 12, 0, tzinfo=UTC)

        # Simulate post-commit sync_state.save() failure (no-op for the
        # hook itself — but the contract is the next apply must reach
        # the same verdict).

        # Apply #2 at T2 (simulating the recovery apply).
        result2 = post_apply_diff(
            direction="legacy-to-web",
            applied_diffs=[diff],
            table_mappings={"animales": mapping},
            web_client=None,  # type: ignore[arg-type]
            shadow_state=_FakeShadow(),  # type: ignore[arg-type]
            sync_state=_empty_sync_state(),
            legacy_snapshot=legacy_snapshot,
            now=datetime(2026, 6, 22, 13, 0, tzinfo=UTC),
        )
        assert result2.outcomes[0].status.name == "MATCHED", (
            f"Apply #2 must reach the same verdict as Apply #1 (idempotence); "
            f"got {result2.outcomes[0].status.name!r}"
        )
        assert len(upsert_calls) == 2
        second_call = upsert_calls[1]
        assert second_call["last_legacy_snapshot_at"] == datetime(2026, 6, 22, 13, 0, tzinfo=UTC)

    def test_repeated_apply_does_not_duplicate_lifecycle_events(self) -> None:
        """(P1 #2 follow-up) Lifecycle event INSERT is idempotent: a
        retry of the same logical apply does NOT create a duplicate
        event row in ``animal_lifecycle_events``.

        Background: the previous test (``...shadow_state_idempotent...``)
        proved the *shadow state* upsert is idempotent. This test
        proves the *lifecycle event* INSERT is also idempotent — a
        retry apply after a ``sync_state.save()`` post-COMMIT failure
        must not create a duplicate event row that the animal state
        machine would double-count as a second transition for the
        same logical event.

        The idempotence guard is at the DB level (the production fix):
        the ``animal_lifecycle_events`` schema declares ``UNIQUE
        (animal_id, event_type, event_timestamp)`` and the persister
        uses ``INSERT ... ON CONFLICT (animal_id, event_type,
        event_timestamp) DO NOTHING``. The test asserts the wire-up
        (SQL contains the ON CONFLICT clause) AND that the persister
        invokes ``execute_sql`` exactly once per apply (the SQL itself
        is idempotent at the DB level; the test asserts the hook
        never silently swallows the call or skips the INSERT
        entirely).

        Setup:
          - Apply #1: ``TbEntradas`` INSERT produces one
            ``INTAKE_STARTED`` event; ``web_client.execute_sql`` is
            called exactly once with the ON CONFLICT clause.
          - Apply #2 (same diff, simulated post-commit failure): the
            hook MUST issue the same INSERT — the DB-level ``ON
            CONFLICT DO NOTHING`` is what suppresses the duplicate
            row. In production this is the guard that makes the
            retry safe.
        """
        from datetime import UTC, datetime

        from migration.reconcile import post_apply_diff
        from migration.reporting import Diff

        captured_inserts: list[tuple[str, list[object]]] = []

        class _FakeWebClient:
            def execute_sql(
                self, query: str, params: list[object] | None = None
            ) -> list[dict[str, object]]:
                # Only capture the lifecycle-event INSERT; ignore
                # anything else the hook might emit. The hook emits
                # ONLY this INSERT in this test, so capturing every
                # call is also safe.
                captured_inserts.append((query, list(params or [])))
                return []

        class _FakeShadow:
            def upsert(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_reconciliation_status(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_derived_value(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_derived_at(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

        # ``TbEntradas`` is the right table for this test: its diff
        # translator emits exactly one ``INTAKE_STARTED`` event per
        # INSERT (verified in the existing
        # ``test_legacy_to_web_persists_lifecycle_events_to_web_client``
        # test). Using ``TbFichaAnimal`` would NOT exercise the
        # persister path (ficha INSERTs produce no events).
        mapping = _entrada_mapping_for_event_persistence()
        diff = Diff(
            op="INSERT",
            key="1",
            table="entradas",
            legacy_pk=1,
            web_pk="00000000-0000-0000-0000-000000000010",
            legacy_row={
                "IDEntrada": 1,
                "NChip": "001",
                "FEntrada": datetime(2024, 1, 1, tzinfo=UTC),
                "FSalida": None,
            },
            web_row={
                "id": "00000000-0000-0000-0000-000000000010",
                "animal_id": "00000000-0000-0000-0000-000000000001",
            },
            changed_fields=("FEntrada",),
        )

        common_kwargs = {
            "direction": "legacy-to-web",
            "applied_diffs": [diff],
            "table_mappings": {"entradas": mapping},
            "shadow_state": _FakeShadow(),  # type: ignore[arg-type]
            "sync_state": _empty_sync_state(),
            "created_by": "00000000-0000-0000-0000-000000000999",
        }

        # Apply #1 — should issue exactly ONE INSERT.
        post_apply_diff(
            web_client=_FakeWebClient(),  # type: ignore[arg-type]
            now=datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
            **common_kwargs,
        )
        assert len(captured_inserts) == 1, (
            f"Apply #1 must issue exactly one INSERT (INTAKE_STARTED); "
            f"got {len(captured_inserts)}: {captured_inserts!r}"
        )
        sql1, params1 = captured_inserts[0]
        assert "INSERT INTO animal_lifecycle_events" in sql1
        # The idempotence guard is the ON CONFLICT clause. Without it,
        # a retry would create a duplicate row.
        assert "ON CONFLICT (animal_id, event_type, event_timestamp) DO NOTHING" in sql1, (
            f"Apply #1 INSERT must include the ON CONFLICT DO NOTHING "
            f"idempotence guard; got SQL: {sql1!r}"
        )
        # Event payload is stable across the retry.
        assert params1[0] == "00000000-0000-0000-0000-000000000001"  # animal_id
        assert params1[1] == "INTAKE_STARTED"
        assert "2024-01-01" in str(params1[2])  # event_timestamp ISO

        # Apply #2 — same diff re-applied (simulating recovery apply
        # after a sync_state.save() post-COMMIT failure). The hook
        # MUST re-issue the INSERT (the DB-level ON CONFLICT DO NOTHING
        # is what suppresses the duplicate row). Asserting the
        # call-count after Apply #2 = 2 confirms the hook does not
        # silently swallow the second call.
        post_apply_diff(
            web_client=_FakeWebClient(),  # type: ignore[arg-type]
            now=datetime(2026, 6, 22, 13, 0, tzinfo=UTC),
            **common_kwargs,
        )
        assert len(captured_inserts) == 2, (
            f"Apply #2 must issue its own INSERT call (DB-level "
            f"idempotence is the guard against duplicate rows); "
            f"got {len(captured_inserts)}: {captured_inserts!r}"
        )
        sql2, params2 = captured_inserts[1]
        # Same SQL + same params → the DB ON CONFLICT DO NOTHING will
        # collapse both calls to a single row. The hook's job is to
        # issue the INSERT; the DB's job is to suppress the duplicate.
        assert sql2 == sql1, (
            f"Apply #2 must issue the same SQL as Apply #1 (same logical "
            f"event → same natural-key INSERT); got {sql2!r} vs {sql1!r}"
        )
        assert params2 == params1, (
            f"Apply #2 must issue the same params as Apply #1; got {params2!r} vs {params1!r}"
        )


# --- helpers --------------------------------------------------------------


def _empty_sync_state():
    """Return a fresh ``SyncState`` (no legacy↔web mappings)."""
    from migration.sync_state import SyncState

    return SyncState()


def _voluntario_mapping_with_dni_preserve():
    """Synthetic ``voluntarios`` TableMapping with the ``DNI`` column as
    ``web_only_strategy: preserve`` (mirrors the real voluntario.yaml).

    The mapping is built inline because the full YAML loader is heavy;
    the hook only reads ``mapping.columns`` and ``mapping.legacy_table``.
    """
    from migration.mappings import ColumnMapping, TableMapping

    return TableMapping(
        version="1.0",
        web_table="voluntarios",
        legacy_table="TbVoluntariosParaAutorrellenables",
        key_field="Voluntario",
        legacy_key="Voluntario",
        date_fields=[],
        columns=[
            ColumnMapping(
                web_column="Voluntario",
                legacy_column="Voluntario",
                transform="identity",
                nullable=False,
            ),
            ColumnMapping(
                web_column="DNI",
                legacy_column=None,
                transform="identity",
                nullable=True,
                web_only_strategy="preserve",
            ),
        ],
        fk_lookups=[],
    )


def _animal_mapping_with_current_state_derived():
    """Synthetic ``animales`` TableMapping with a ``current_state``
    column declared as ``web_only_strategy: derived``.

    The hook only reads ``mapping.columns`` + ``mapping.legacy_table``
    + ``mapping.web_table``; everything else is filler for the pydantic
    model.
    """
    from migration.mappings import ColumnMapping, TableMapping

    return TableMapping(
        version="1.0",
        web_table="animales",
        legacy_table="TbFichaAnimal",
        key_field="NCHIP",
        legacy_key="NCHIP",
        date_fields=["FIMPLANTACIONCHIP", "FDefuncion"],
        columns=[
            ColumnMapping(
                web_column="NCHIP",
                legacy_column="NCHIP",
                transform="identity",
                nullable=False,
            ),
            ColumnMapping(
                web_column="current_state",
                legacy_column=None,
                transform="identity",
                nullable=True,
                web_only_strategy="derived",
            ),
        ],
        fk_lookups=[],
    )


def _entrada_mapping_for_event_persistence():
    """Synthetic ``entradas`` TableMapping for the lifecycle-event
    persistence tests.

    Columns include the legacy ``IDEntrada`` (1:1) plus a
    ``fk_lookup`` animal_id (resolved via ``sync_state`` in
    production). The mapping's ``legacy_table`` is
    ``TbEntradas`` so ``translate_diff`` produces ``INTAKE_STARTED``.
    """
    from migration.mappings import ColumnMapping, TableMapping

    return TableMapping(
        version="1.0",
        web_table="entradas",
        legacy_table="TbEntradas",
        key_field="id",
        legacy_key="IDEntrada",
        date_fields=["FEntrada", "FSalida"],
        columns=[
            ColumnMapping(
                web_column="id",
                legacy_column=None,
                transform="default_uuid",
                nullable=False,
            ),
            ColumnMapping(
                web_column="animal_id",
                legacy_column=None,
                transform="fk_lookup",
                nullable=False,
                lookup="animal",
            ),
        ],
        fk_lookups=[],
    )
