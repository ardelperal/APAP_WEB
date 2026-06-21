"""Reconciliation types for ``web-only-feature-preservation``.

PR 1 of the change. The dataclasses / types here are the
contract surface used by:

- the CLI ``apap-migrate reconcile`` (this PR — skeleton; PR 5 fills
  in the interactive prompt loop),
- the applier hook ``post_apply_diff`` (PR 4 — uses ``ReconciliationResult``
  as the return type),
- the derivation engine + semantic-events pipeline (PR 2 — populates
  ``ReconciliationOutcome``).

The semantics of ``ReconciliationStatus`` and the reconciliation
algorithm itself arrive with PR 2 (derivation engine) and PR 4 (hook).
This module only fixes the SHAPE of the types so downstream slices can
import them without circular dependencies.

Mapping back to the spec (openspec/.../specs/web-only-feature-preservation/spec.md):

- ``ReconciliationStatus`` ↔ REQ-Hook ``reconciliation_status`` enum
  (``matched`` / ``divergent`` / ``needs_review`` / ``pending`` /
  ``migrated``).
- ``ReconciliationOutcome`` ↔ REQ-CLI subcommand case enumeration (one
  row per ``(table, legacy_pk, web_column)`` triple).
- ``ReconciliationResult`` ↔ ``MigrationReport.reconciliation_summary``
  contract (PR 4 wires it onto the existing ``MigrationReport``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol


class ReconciliationStatus(StrEnum):
    """Per-row reconciliation verdict (spec.md REQ-Hook).

    Values:

    - ``matched`` — the derived value equals the stored web value.
    - ``divergent`` — derived ≠ stored AND no manual web override; the
      applier has already overwritten the stored value with the derived
      one (info-only, no operator action required).
    - ``needs_review`` — derived ≠ stored AND a manual web override
      was detected (``updated_at > last_legacy_snapshot_at``); the
      stored value is preserved and the case surfaces in the CLI
      ``reconcile --check-only`` / ``--interactive`` flow.
    - ``pending`` — initial state; the row was never reconciled.
    - ``migrated`` — initial import from the legacy DB; awaiting the
      first derivation pass.
    """

    MATCHED = "matched"
    DIVERGENT = "divergent"
    NEEDS_REVIEW = "needs_review"
    PENDING = "pending"
    MIGRATED = "migrated"


@dataclass(frozen=True, slots=True)
class ReconciliationOutcome:
    """One row's reconciliation verdict.

    Fields mirror what the CLI prints in ``reconcile --check-only`` so
    the dataclass is the single source of truth for the operator
    surface (no parallel dicts).

    ``web_value`` is the value currently stored in the web DB.
    ``derived_value`` is the result of the derivation engine on the
    most recent legacy snapshot. ``review_reasons`` is a tuple of
    short tags (``"web_manual_override_detected"``,
    ``"pre_death_state_missing"``, etc.) the operator can match
    against the docs.
    """

    table_name: str
    legacy_pk: str
    web_column: str
    status: ReconciliationStatus
    web_value: Any | None = None
    derived_value: Any | None = None
    review_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """Aggregate result of one ``reconcile`` run.

    Returned by the applier hook (PR 4) and printed by the CLI (PR 5).
    Immutable so the audit trail stays tamper-evident (same rule as
    ``MigrationReport`` in ``app.core.migration.reporting``).
    """

    outcomes: tuple[ReconciliationOutcome, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def matched(self) -> int:
        return sum(1 for o in self.outcomes if o.status is ReconciliationStatus.MATCHED)

    @property
    def divergent(self) -> int:
        return sum(1 for o in self.outcomes if o.status is ReconciliationStatus.DIVERGENT)

    @property
    def needs_review(self) -> int:
        return sum(1 for o in self.outcomes if o.status is ReconciliationStatus.NEEDS_REVIEW)


@dataclass(frozen=True, slots=True)
class ReconciliationSummary:
    """Counts bundle used by the ``MigrationReport`` (PR 4 wires this).

    Decoupled from ``ReconciliationResult`` so the applier can attach
    counts to its existing ``MigrationReport`` dataclass without
    dragging the full list of outcomes into the report.
    """

    matched: int = 0
    divergent: int = 0
    needs_review: int = 0
    errors: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_result(cls, result: ReconciliationResult) -> ReconciliationSummary:
        return cls(
            matched=result.matched,
            divergent=result.divergent,
            needs_review=result.needs_review,
            errors=result.errors,
        )


# --- ShadowStateRepository protocol --------------------------------------
#
# PR 2 only needs the two write methods (upsert + update_reconciliation_status)
# from the real ``ShadowStateRepository`` (PR 1). Defining a protocol lets
# the helper accept either the concrete class or a fake in tests without
# pulling the dependency into this module's import graph.


class _ShadowStateWriter(Protocol):
    """Minimal surface required by ``reconcile_after_legacy_write``.

    Matches the public methods of
    ``app.core.migration.shadow_state.ShadowStateRepository`` that
    PR 2 actually calls; defined as a Protocol so tests can pass a
    ``FakeShadow`` without subclassing the real repository.
    """

    def upsert(
        self,
        *,
        table_name: str,
        legacy_pk: str,
        web_pk: str | None,
        web_column: str,
        preserved_value: Any,
        strategy: str,
        last_legacy_snapshot_at: datetime | None = None,
        reconciliation_status: str = "pending",
    ) -> None: ...

    def update_reconciliation_status(
        self,
        *,
        table_name: str,
        legacy_pk: str,
        web_column: str,
        status: str,
        review_reasons: list[str] | None = None,
        last_reconciled_at: datetime | None = None,
    ) -> None: ...


# --- Per-row reconciliation dispatcher (PR 2/6, T2.8) ---------------------
#
# Called by the applier hook (PR 4) once per affected row in the
# ``legacy-to-web`` direction. Dispatches on
# ``ColumnMapping.web_only_strategy``:
#
# - ``preserve`` → upsert shadow row + stamp ``last_legacy_snapshot_at``.
#   The web value is preserved verbatim across the round-trip.
# - ``derived``  → invoke the derivation engine on the supplied legacy
#   snapshots, compare to the stored web value, and persist the verdict
#   into the shadow row's ``reconciliation_status``. When the comparator
#   flags a web manual override (``NEEDS_REVIEW``), the stored value is
#   preserved and the operator surfaces the case via the CLI in PR 5.
# - ``fixed``    → no-op (the value is declared statically in YAML and
#   never re-derived; the applier already writes the static value into
#   the web row at INSERT/UPDATE time).


# Review-reason tags that surface in the CLI and in
# ``web_only_feature_shadow.review_reasons``. Keep these short and
# searchable so the operator can grep the migration reports.
REVIEW_REASON_WEB_MANUAL_OVERRIDE = "web_manual_override_detected"


def reconcile_after_legacy_write(
    *,
    shadow_state: _ShadowStateWriter,
    table_name: str,
    legacy_pk: str,
    web_pk: str | None,
    web_column: str,
    strategy: str,
    preserved_value: Any,
    last_legacy_snapshot_at: datetime | None,
    derived_inputs: dict[str, Any] | None = None,
    stored_state: str | None = None,
    web_updated_at: datetime | None = None,
) -> ReconciliationOutcome:
    """Per-row reconciliation outcome for the applier hook (PR 4).

    Args:
        shadow_state: writer that persists the shadow row. Must expose
            ``upsert`` and ``update_reconciliation_status`` (see the
            ``_ShadowStateWriter`` protocol above).
        table_name, legacy_pk, web_column: the unique key.
        web_pk: optional UUID of the web row (NULL when the row hasn't
            been linked yet).
        strategy: ``"preserve"`` / ``"derived"`` / ``"fixed"``. Unknown
            values are treated as ``"fixed"`` (no-op) to keep the
            applier hook forward-compatible with new strategies
            added in future PRs without raising mid-batch.
        preserved_value: the value to upsert for ``preserve`` /
            ``fixed``; ignored for ``derived`` (the value lives in
            ``animal_current_state``, not the shadow row).
        last_legacy_snapshot_at: UTC timestamp of the legacy snapshot
            that produced this write; stamped onto the shadow row.
        derived_inputs: ``{"tb_ficha", "tb_entradas", "tb_acogidas",
            "tb_adopciones"}`` legacy collections forwarded to the
            derivation engine. Required when ``strategy == "derived"``;
            ignored otherwise.
        stored_state: the current web value (``animal_current_state.current_state``
            for the ``derived`` path). ``None`` → ``PENDING``.
        web_updated_at: timestamp of the last web edit on this column.
            ``None`` when the column is shadow-managed and the web has
            never been edited. Drives the Q2 path
            (``web_updated_at >= last_legacy_snapshot_at → NEEDS_REVIEW``).

    Returns:
        ``ReconciliationOutcome`` with the verdict + the values the CLI
        prints in ``--check-only`` and ``--interactive`` (PR 5).
    """
    if strategy == "preserve":
        return _reconcile_preserve(
            shadow_state=shadow_state,
            table_name=table_name,
            legacy_pk=legacy_pk,
            web_pk=web_pk,
            web_column=web_column,
            preserved_value=preserved_value,
            last_legacy_snapshot_at=last_legacy_snapshot_at,
        )
    if strategy == "derived":
        return _reconcile_derived(
            shadow_state=shadow_state,
            table_name=table_name,
            legacy_pk=legacy_pk,
            web_pk=web_pk,
            web_column=web_column,
            last_legacy_snapshot_at=last_legacy_snapshot_at,
            derived_inputs=derived_inputs or {},
            stored_state=stored_state,
            web_updated_at=web_updated_at,
        )
    # ``fixed`` and any unknown strategy → no-op.
    return _reconcile_fixed(
        table_name=table_name,
        legacy_pk=legacy_pk,
        web_column=web_column,
        preserved_value=preserved_value,
    )


def _reconcile_preserve(
    *,
    shadow_state: _ShadowStateWriter,
    table_name: str,
    legacy_pk: str,
    web_pk: str | None,
    web_column: str,
    preserved_value: Any,
    last_legacy_snapshot_at: datetime | None,
) -> ReconciliationOutcome:
    """``preserve`` path: upsert shadow row + stamp the snapshot timestamp.

    A ``preserve`` reconciliation is trivially ``MATCHED``: the value
    is preserved verbatim across the round-trip, so there is nothing
    to compare or reconcile. The outcome reports ``MATCHED`` so the
    CLI does not surface the row in ``--check-only``; the shadow row
    stores the same status for consistency.
    """
    shadow_state.upsert(
        table_name=table_name,
        legacy_pk=legacy_pk,
        web_pk=web_pk,
        web_column=web_column,
        preserved_value=preserved_value,
        strategy="preserve",
        last_legacy_snapshot_at=last_legacy_snapshot_at,
        reconciliation_status=ReconciliationStatus.MATCHED.value,
    )
    return ReconciliationOutcome(
        table_name=table_name,
        legacy_pk=legacy_pk,
        web_column=web_column,
        status=ReconciliationStatus.MATCHED,
        web_value=preserved_value,
        derived_value=preserved_value,
    )


def _reconcile_fixed(
    *,
    table_name: str,
    legacy_pk: str,
    web_column: str,
    preserved_value: Any,
) -> ReconciliationOutcome:
    """``fixed`` path: no-op. The static YAML value is already in the web row.

    We DO NOT upsert the shadow row for ``fixed`` — the spec reserves
    shadow state for ``preserve`` (round-tripped values) and ``derived``
    (derivation engine cache). A ``fixed`` value is declared statically
    in YAML and re-applied by the applier on every write; persisting it
    to the shadow table would only duplicate the source of truth.
    """
    return ReconciliationOutcome(
        table_name=table_name,
        legacy_pk=legacy_pk,
        web_column=web_column,
        status=ReconciliationStatus.MATCHED,
        web_value=preserved_value,
        derived_value=preserved_value,
    )


def _reconcile_derived(
    *,
    shadow_state: _ShadowStateWriter,
    table_name: str,
    legacy_pk: str,
    web_pk: str | None,
    web_column: str,
    last_legacy_snapshot_at: datetime | None,
    derived_inputs: dict[str, Any],
    stored_state: str | None,
    web_updated_at: datetime | None,
) -> ReconciliationOutcome:
    """``derived`` path: invoke the derivation engine + comparator.

    The shadow row is still upserted (so the operator can see the
    per-row ``last_legacy_snapshot_at`` in the CLI dashboard), but the
    ``preserved_value`` field stays ``NULL`` — the derived value lives
    in ``animal_current_state`` (NOT in the shadow row). When the
    comparator flags a manual web override, ``update_reconciliation_status``
    stamps the row with ``needs_review`` so the CLI lists the case in
    PR 5's ``--check-only`` / ``--interactive`` modes.
    """
    # Local import to avoid a circular dependency: derivation.py imports
    # ReconciliationStatus from this module. The function is called only
    # from the applier hook (PR 4) at runtime, so the import cost is
    # negligible.
    from app.core.migration.derivation import (
        compare_derived_to_stored,
        derive_estado_actual_animal,
    )

    derived = derive_estado_actual_animal(
        tb_ficha=derived_inputs.get("tb_ficha"),
        tb_entradas=derived_inputs.get("tb_entradas") or [],
        tb_acogidas=derived_inputs.get("tb_acogidas") or [],
        tb_adopciones=derived_inputs.get("tb_adopciones") or [],
    )

    status = compare_derived_to_stored(
        derived_state=derived.state,
        stored_state=stored_state,
        web_updated_at=web_updated_at,
        last_legacy_snapshot_at=last_legacy_snapshot_at,
    )

    # Stamp the shadow row with the snapshot timestamp regardless of
    # the verdict so the CLI dashboard can show "last seen" progress.
    # The ``preserved_value`` stays NULL — the derived value lives in
    # ``animal_current_state``, not in the shadow row.
    shadow_state.upsert(
        table_name=table_name,
        legacy_pk=legacy_pk,
        web_pk=web_pk,
        web_column=web_column,
        preserved_value=None,
        strategy="derived",
        last_legacy_snapshot_at=last_legacy_snapshot_at,
        reconciliation_status=status.value,
    )

    review_reasons: tuple[str, ...] = ()
    if status is ReconciliationStatus.NEEDS_REVIEW:
        review_reasons = (REVIEW_REASON_WEB_MANUAL_OVERRIDE,)
        # Stamp the needs-review status with a reason; the operator
        # can grep for ``review_reasons @> '["web_manual_override_detected"]'``
        # in the web DB.
        shadow_state.update_reconciliation_status(
            table_name=table_name,
            legacy_pk=legacy_pk,
            web_column=web_column,
            status=ReconciliationStatus.NEEDS_REVIEW.value,
            review_reasons=list(review_reasons),
            last_reconciled_at=last_legacy_snapshot_at,
        )

    return ReconciliationOutcome(
        table_name=table_name,
        legacy_pk=legacy_pk,
        web_column=web_column,
        status=status,
        web_value=stored_state,
        derived_value=derived.state,
        review_reasons=review_reasons,
    )


__all__ = [
    "REVIEW_REASON_WEB_MANUAL_OVERRIDE",
    "ReconciliationOutcome",
    "ReconciliationResult",
    "ReconciliationStatus",
    "ReconciliationSummary",
    "reconcile_after_legacy_write",
]
