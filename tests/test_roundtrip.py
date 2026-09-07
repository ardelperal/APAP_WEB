"""Round-trip tests for ``web-only-feature-preservation`` (PR 6/6, T6.1-T6.3).

Verifies the end-to-end contract documented in spec.md REQ-Round-trip:

- T6.1: web->legacy->web round-trip preserves ``DNI``
  (strategy ``preserve``).
- T6.2: legacy->web re-derives ``estado_actual_animal`` after a
  legacy change and reaches ``matched``.
- T6.3: a manual web override + a legacy change lands in
  ``needs_review`` (Q2 path) so the CLI can surface it for
  operator resolution.

Each test follows the same conventions as the existing
``test_reconcile.py``: mocks for the web client + a fake
``ShadowStateRepository`` so the suite is fully deterministic
and never touches the network.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.local_backend.db import LocalPostgresExecutor

# --- helpers --------------------------------------------------------------


def _json_response(status_code: int, body: Any) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _make_web_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> LocalPostgresExecutor:
    return LocalPostgresExecutor(
        base_url="https://example.local_backend.app",
        service_key="ik_test",
        transport=httpx.MockTransport(handler),
    )


def _capture_prompt(responses: list[str]) -> Callable[[str], str]:
    """Build a list-driven prompt reader."""

    def _read(_prompt: str) -> str:
        if not responses:
            raise AssertionError("prompt called more times than test expected")
        return responses.pop(0)

    return _read


def _needs_review_row(
    *,
    table_name: str = "animales",
    legacy_pk: str = "a-1",
    web_pk: str = "00000000-0000-0000-0000-000000000001",
    web_column: str = "current_state",
    preserved_value: Any = None,
    strategy: str = "derived",
    last_legacy_snapshot_at: str | None = "2026-06-20T12:00:00+00:00",
    last_reconciled_at: str | None = None,
    review_reasons: list[str] | None = None,
    reconciliation_status: str = "needs_review",
    # PR 5 follow-up additions
    derived_value: Any = None,
    derived_at: str | None = None,
) -> dict[str, Any]:
    """One row in the shape ``ShadowStateRepository.list_needs_review`` returns.

    Includes the new ``derived_value`` / ``derived_at`` columns added
    in PR 6 (PR 5 follow-up #1).
    """
    return {
        "id": "00000000-0000-0000-0000-000000000aaa",
        "table_name": table_name,
        "legacy_pk": legacy_pk,
        "web_pk": web_pk,
        "web_column": web_column,
        "preserved_value": json.dumps(preserved_value) if preserved_value is not None else None,
        "strategy": strategy,
        "last_legacy_snapshot_at": last_legacy_snapshot_at,
        "last_web_edit_at": None,
        "last_reconciled_at": last_reconciled_at,
        "reconciliation_status": reconciliation_status,
        "review_reasons": json.dumps(review_reasons or ["web_manual_override_detected"]),
        # PR 5 follow-up columns
        "derived_value": json.dumps(derived_value) if derived_value is not None else None,
        "derived_at": derived_at,
    }


def _shadow_state_mapping_with_current_state_derived():
    """Synthetic ``animales`` TableMapping with ``current_state`` as derived."""
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


def _voluntario_mapping_with_dni_preserve():
    """Synthetic ``voluntarios`` TableMapping with ``DNI`` as preserve."""
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


def _empty_sync_state():
    from migration.sync_state import SyncState

    return SyncState()


# --- T6.1: Round-trip web->legacy->web preserves DNI ----------------------

# --- T6.1: Round-trip web->legacy->web preserves DNI ----------------------


class TestRoundTripPreservesDni:
    """T6.1: a full round-trip web->legacy->web on ``voluntarios.DNI``
    (strategy ``preserve``) preserves the initial web value verbatim.

    The legacy DB does NOT carry the DNI column (``legacy_column=null``
    on the YAML); the shadow state IS the persistence layer. A
    ``web->legacy`` apply is a no-op for the shadow (spec REQ-Hook: no
    re-derivation, no shadow mutation). A subsequent ``legacy->web``
    apply re-stamps ``last_legacy_snapshot_at`` but preserves the
    ``preserved_value`` (== the web value at apply-time).

    End state: the ``DNI`` value at the end of the round-trip equals
    the initial web value byte-for-byte. ``last_legacy_snapshot_at``
    is bumped to the legacy->web pass.
    """

    def test_dni_round_trip_preserves_value_and_bumps_snapshot(self) -> None:
        from migration.reconcile import post_apply_diff
        from migration.reporting import Diff

        upsert_calls: list[dict[str, object]] = []

        class _FakeShadow:
            def upsert(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                upsert_calls.append(kwargs)

            def update_reconciliation_status(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

        mapping = _voluntario_mapping_with_dni_preserve()
        initial_dni = "12345678A"
        # The web row at the start of the round-trip carries the DNI
        # value the operator typed in the form.
        web_row = {
            "id": "00000000-0000-0000-0000-000000000099",
            "DNI": initial_dni,
        }

        # --- Step 1: web->legacy (no-op per spec REQ-Hook) ---
        web_to_legacy_diff = Diff(
            op="INSERT",
            key="Pepe",
            table="voluntarios",
            legacy_pk=None,
            web_pk="00000000-0000-0000-0000-000000000099",
            legacy_row=None,
            web_row=web_row,
            changed_fields=("DNI",),
        )
        result_w2l = post_apply_diff(
            direction="web-to-legacy",
            applied_diffs=[web_to_legacy_diff],
            table_mappings={"voluntarios": mapping},
            web_client=None,  # type: ignore[arg-type]
            shadow_state=_FakeShadow(),  # type: ignore[arg-type]
            sync_state=_empty_sync_state(),
            now=datetime(2026, 6, 22, 10, 0, tzinfo=UTC),
        )
        # web->legacy is a no-op: no outcomes, no upserts.
        assert result_w2l.outcomes == ()
        assert result_w2l.errors == ()
        assert upsert_calls == [], (
            f"web->legacy must NOT touch the shadow state; got: {upsert_calls!r}"
        )

        # --- Step 2: legacy->web (preserves the value) ---
        # The applier stamps ``last_legacy_snapshot_at`` and writes
        # the preserved value into the shadow row. The web row stays
        # the same (the legacy DB doesn't carry DNI).
        legacy_to_web_diff = Diff(
            op="UPDATE",
            key="Pepe",
            table="voluntarios",
            legacy_pk="Pepe",
            web_pk="00000000-0000-0000-0000-000000000099",
            legacy_row={"Voluntario": "Pepe"},
            web_row=web_row,
            changed_fields=("Voluntario",),
        )
        result_l2w = post_apply_diff(
            direction="legacy-to-web",
            applied_diffs=[legacy_to_web_diff],
            table_mappings={"voluntarios": mapping},
            web_client=None,  # type: ignore[arg-type]
            shadow_state=_FakeShadow(),  # type: ignore[arg-type]
            sync_state=_empty_sync_state(),
            now=datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
        )
        # Round-trip ended with a MATCHED outcome for the DNI column.
        assert len(result_l2w.outcomes) == 1
        outcome = result_l2w.outcomes[0]
        assert outcome.web_column == "DNI"
        assert outcome.status.name == "MATCHED"
        assert outcome.web_value == initial_dni, (
            f"round-trip must preserve the initial DNI value; got: {outcome.web_value!r}"
        )
        # The shadow row was upserted with the legacy->web snapshot.
        assert len(upsert_calls) == 1
        upsert = upsert_calls[0]
        assert upsert["preserved_value"] == initial_dni
        assert upsert["last_legacy_snapshot_at"] == datetime(2026, 6, 22, 12, 0, tzinfo=UTC)
        assert upsert["strategy"] == "preserve"


# --- T6.2: legacy->web re-derives estado_actual_animal ------------------


class TestRoundTripLegacyToWebDerivesState:
    """T6.2: a legacy->web change that affects ``estado_actual_animal``
    triggers re-derivation; when derived == stored the verdict is
    ``matched``.
    """

    def test_death_in_legacy_re_derives_to_fallecido(self) -> None:
        """Setting ``FDefuncion`` in legacy (``TbFichaAnimal`` UPDATE)
        makes the derivation engine return ``Fallecido (Albergue)``;
        when the stored web value matches the derived value, the
        verdict is ``MATCHED``.
        """
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

        mapping = _shadow_state_mapping_with_current_state_derived()
        # Legacy UPDATE: ficha death date set + pre-death state.
        diff = Diff(
            op="UPDATE",
            key="a-42",
            table="animales",
            legacy_pk="a-42",
            web_pk="00000000-0000-0000-0000-000000000042",
            legacy_row={
                "NCHIP": "a-42",
                "FDefuncion": "2026-07-01",
                "UltimoEstadoAntesDeFallecido": "Albergue",
                "Situacion": "",
            },
            web_row=None,
            changed_fields=("FDefuncion",),
        )
        legacy_snapshot = {
            "TbFichaAnimal": [
                {
                    "NCHIP": "a-42",
                    "FDefuncion": "2026-07-01",
                    "UltimoEstadoAntesDeFallecido": "Albergue",
                    "Situacion": "",
                }
            ],
            "TbEntradas": [],
            "TbAcogidaAnimal": [],
            "TbAdopcion": [],
        }
        # Sentinels: stored = "Fallecido (Albergue)" (matches derived);
        # web_updated_at is None (no manual override).
        legacy_snapshot["_stored_state"] = "Fallecido (Albergue)"
        legacy_snapshot["_web_updated_at"] = None

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
        assert outcome.derived_value == "Fallecido (Albergue)"
        assert outcome.web_value == "Fallecido (Albergue)"
        # The shadow row was upserted.
        assert len(upsert_calls) == 1


# --- T6.3: manual override + legacy change -> needs_review --------------


class TestManualOverrideNeedsReview:
    """T6.3: when the operator manually overrode the web value AND the
    legacy DB changed to suggest a different value, the Q2 path marks
    the case as ``needs_review`` (not ``divergent``) so the CLI can
    surface it.
    """

    def test_web_override_after_sync_marks_needs_review(self) -> None:
        """The web value was manually set to ``Acogida`` AFTER the last
        sync (web_updated_at > last_legacy_snapshot_at). Legacy now
        records an active adoption (``TbAdopcion`` with
        ``FDevolucion=null``) that derives to ``Adoptado``. The
        comparator's Q2 path picks ``NEEDS_REVIEW`` and tags the
        outcome with ``web_manual_override_detected``.
        """
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

        mapping = _shadow_state_mapping_with_current_state_derived()
        # Legacy UPDATE: a new adoption was recorded.
        diff = Diff(
            op="INSERT",
            key="99",
            table="animales",  # mapped to animales for the derived column
            legacy_pk="a-7",
            web_pk="00000000-0000-0000-0000-000000000007",
            legacy_row={
                "NCHIP": "a-7",
                "FDefuncion": None,
                "UltimoEstadoAntesDeFallecido": None,
            },
            web_row=None,
            changed_fields=("NCHIP",),
        )
        legacy_snapshot = {
            "TbFichaAnimal": [
                {
                    "NCHIP": "a-7",
                    "FDefuncion": None,
                    "UltimoEstadoAntesDeFallecido": None,
                }
            ],
            "TbEntradas": [],
            "TbAcogidaAnimal": [],
            "TbAdopcion": [{"IDAdopcion": 99, "FDevolucion": None}],
        }
        legacy_snapshot["_stored_state"] = "Acogida"  # web was manually set
        legacy_snapshot["_web_updated_at"] = datetime(
            2026, 6, 22, 13, 0, tzinfo=UTC
        )  # AFTER sync at 12:00

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
        assert outcome.derived_value == "Adoptado"
        assert outcome.web_value == "Acogida"
        assert "web_manual_override_detected" in outcome.review_reasons
        # The secondary writer flipped the status to needs_review.
        assert len(update_calls) == 1
