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

    The function lives in ``app.core.migration.reconcile`` (PR 1 owns
    that module). It takes the legacy snapshot + the web row + the
    matching ``ColumnMapping`` and writes the right ``ReconciliationOutcome``.
    """

    def test_preserve_strategy_upserts_shadow_and_bumps_snapshot(self) -> None:
        """``preserve`` writes the shadow row and stamps ``last_legacy_snapshot_at``."""
        from datetime import UTC, datetime

        from app.core.migration.reconcile import reconcile_after_legacy_write

        upsert_calls: list[dict[str, object]] = []

        class _FakeShadow:
            def upsert(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                upsert_calls.append(kwargs)

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
        from app.core.migration.reconcile import reconcile_after_legacy_write

        upsert_calls: list[object] = []
        update_calls: list[object] = []

        class _FakeShadow:
            def upsert(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                upsert_calls.append(kwargs)

            def update_reconciliation_status(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                update_calls.append(kwargs)

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

        from app.core.migration.reconcile import reconcile_after_legacy_write

        upsert_calls: list[dict[str, object]] = []
        update_calls: list[dict[str, object]] = []

        class _FakeShadow:
            def upsert(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                upsert_calls.append(kwargs)

            def update_reconciliation_status(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                update_calls.append(kwargs)

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

        from app.core.migration.reconcile import reconcile_after_legacy_write

        update_calls: list[dict[str, object]] = []

        class _FakeShadow:
            def upsert(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_reconciliation_status(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                update_calls.append(kwargs)

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
