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
from enum import StrEnum
from typing import Any


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


__all__ = [
    "ReconciliationOutcome",
    "ReconciliationResult",
    "ReconciliationStatus",
    "ReconciliationSummary",
]
