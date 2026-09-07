"""Reconciliation types and the applier hook for ``web-only-feature-preservation``.

PR 1 of the change fixed the SHAPE of the dataclasses (types only).
PR 2 added the per-row dispatcher ``reconcile_after_legacy_write`` and
the comparator logic (Q2 rule).
PR 4 (this commit) lands the public seam ``post_apply_diff`` that the
MIGRATION-01 applier (PR 5/6) invokes after
``apply_diff_to_web_transactional()``. The hook:

1. For each diff in ``direction == "legacy-to-web"``:
   - Dispatches per-column on ``ColumnMapping.web_only_strategy``
     (``preserve`` / ``derived`` / ``fixed``) via
     ``reconcile_after_legacy_write``.
   - Calls ``semantic_events.translate_diff`` and persists the
     resulting ``LifecycleEvent`` rows into
     ``animal_lifecycle_events`` via the web DB.
2. For ``direction == "web-to-legacy"``: returns an empty
   ``ReconciliationResult`` (no-op — preserve shadow state, no
   re-derivation; spec REQ-Hook).

Mapping back to the spec (openspec/.../specs/web-only-feature-preservation/spec.md):

- ``ReconciliationStatus`` ↔ REQ-Hook ``reconciliation_status`` enum
  (``matched`` / ``divergent`` / ``needs_review`` / ``pending`` /
  ``migrated``).
- ``ReconciliationOutcome`` ↔ REQ-CLI subcommand case enumeration (one
  row per ``(table, legacy_pk, web_column)`` triple).
- ``ReconciliationResult`` ↔ ``MigrationReport.reconciliation_summary``
  contract (T4.6 wires it onto the existing ``MigrationReport``).
- ``post_apply_diff`` ↔ REQ-Hook public seam.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast
from uuid import UUID

if TYPE_CHECKING:
    # Solo para anotaciones; el import real se hace lazy dentro de
    # ``post_apply_diff`` y ``_persist_lifecycle_event`` para evitar
    # ciclos en el import graph (``reconcile`` → ``mappings`` →
    # ``__init__`` → ``reconcile``).
    from migration.mappings import ColumnMapping, TableMapping
    from migration.reporting import Diff
    from migration.semantic_events import LifecycleEvent


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
    ``MigrationReport`` in ``migration.reporting``).
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
    ``migration.shadow_state.ShadowStateRepository`` that
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

    def update_derived_value(
        self,
        *,
        table_name: str,
        legacy_pk: str,
        web_column: str,
        derived_value: Any,
    ) -> None: ...

    def update_derived_at(
        self,
        *,
        table_name: str,
        legacy_pk: str,
        web_column: str,
        derived_at: datetime | None,
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
    from migration.derivation import (
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

    # PR 5 follow-up: also persist ``derived_value`` + ``derived_at``
    # so the CLI's ``--interactive`` ``(b) accept derived`` prompt
    # pre-fills with the stored derivation result (the operator does
    # not have to retype it). These writes happen on every verdict
    # (matched / divergent / needs_review / pending) so the CLI
    # always has the latest derivation cache to display.
    shadow_state.update_derived_value(
        table_name=table_name,
        legacy_pk=legacy_pk,
        web_column=web_column,
        derived_value=derived.state,
    )
    shadow_state.update_derived_at(
        table_name=table_name,
        legacy_pk=legacy_pk,
        web_column=web_column,
        derived_at=last_legacy_snapshot_at,
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


# --- Public hook: post_apply_diff (PR 4/6, T4.1-T4.5) ----------------------
#
# The applier of MIGRATION-01 PR 5/6 calls this immediately after
# ``apply_diff_to_web_transactional`` and before returning the
# ``MigrationReport``. The signature mirrors the spec.md REQ-Hook
# contract verbatim (six required kwargs) plus three optional kwargs:
#
# - ``legacy_snapshot``: pre-fetched ``{legacy_table: [row, ...]}`` for
#   derived-column inputs to the derivation engine. Production code
#   may omit it (the applier then resolves via the web DB); tests pass
#   it directly to avoid a roundtrip.
# - ``now``: UTC timestamp for ``last_legacy_snapshot_at`` and
#   ``reconciled_at``. Defaults to ``datetime.now(UTC)``. Tests pass
#   a fixed value for determinism.
# - ``created_by``: ``UUID`` of the operator/automation triggering
#   the apply, written to ``animal_lifecycle_events.created_by``. If
#   ``None``, the hook skips persistence of lifecycle events (the
#   applier in MIGRATION-01 PR 5/6 will pass a value; tests can omit
#   it and assert against ``ReconciliationResult.errors``).


def post_apply_diff(
    *,
    direction: Literal["legacy-to-web", "web-to-legacy"],
    applied_diffs: Sequence[Diff],
    table_mappings: Mapping[str, TableMapping],
    web_client: SqlExecutor,
    shadow_state: _ShadowStateWriter,
    sync_state: SyncStateProtocol,
    created_by: str | None = None,
    legacy_snapshot: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    now: datetime | None = None,
) -> ReconciliationResult:
    """Applier hook: post-apply reconciliation pass.

    Called by the applier (MIGRATION-01 PR 5/6) immediately after
    ``apply_diff_to_web_transactional``. Iterates the diffs once for
    per-column reconciliation (shadow state + derivation engine) and
    once for semantic-event persistence (``animal_lifecycle_events``).

    Args:
        direction: ``"legacy-to-web"`` runs the full pass;
            ``"web-to-legacy"`` is a no-op (spec REQ-Hook).
        applied_diffs: the diffs the applier just committed to the
            web DB. NOOP and DELETE diffs are skipped (no
            reconciliation needed).
        table_mappings: ``{web_table: TableMapping}`` index used to
            resolve the ``ColumnMapping`` list and ``legacy_table``
            for each diff. A missing mapping for a diff's table
            produces an entry in ``errors`` (the batch continues —
            one bad mapping does NOT abort the run, regla #13474 v2).
        web_client: InsForge REST client used only for the
            ``animal_lifecycle_events`` INSERT path (per-column
            reconciliation writes via ``shadow_state``).
        shadow_state: writer for ``web_only_feature_shadow``. Must
            expose ``upsert`` + ``update_reconciliation_status``
            (see :class:`_ShadowStateWriter`).
        sync_state: ``SyncState`` used by the lifecycle-event
            persister to resolve ``legacy_pk -> web_pk`` for FK
            lookup when the source row is on a child table
            (``TbEntradas``, ``TbAcogidaAnimal``, ``TbAdopcion``).
        created_by: operator UUID written to
            ``animal_lifecycle_events.created_by``. When ``None`` the
            hook skips event persistence and records the skip in
            ``errors`` (so the applier can surface a configuration
            warning).
        legacy_snapshot: optional ``{legacy_table: [row, ...]}``
            input for ``derived`` columns. When ``None``, the hook
            builds inputs from ``diff.legacy_row`` + empty lists for
            the other tables — a degenerate but deterministic
            derivation (good enough for columns where the diff row
            is the only relevant input, e.g. ``TbFichaAnimal`` with
            ``FDefuncion``).
        now: UTC timestamp stamped on shadow rows
            (``last_legacy_snapshot_at``). Defaults to
            ``datetime.now(UTC)``.

    Returns:
        ``ReconciliationResult`` with one outcome per
        ``(table, legacy_pk, web_column)`` triple whose
        ``ColumnMapping.web_only_strategy`` is not ``None`` (the
        exempt transforms — ``default_uuid``, ``default_now``,
        ``fk_lookup`` — produce no outcomes). The applier projects
        the result into ``MigrationReport.reconciliation_summary`` via
        :meth:`ReconciliationSummary.from_result`.
    """
    if direction == "web-to-legacy":
        # No-op per spec REQ-Hook. The shadow state survives the
        # round-trip verbatim; re-derivation would only add I/O
        # without information.
        return ReconciliationResult(outcomes=(), errors=())

    snapshot_at = now if now is not None else datetime.now(UTC)
    outcomes: list[ReconciliationOutcome] = []
    errors: list[str] = []

    for diff in applied_diffs:
        if diff.op in ("NOOP", "DELETE"):
            # NOOP: no change → no reconciliation needed.
            # DELETE: orphan web row → CLI surfaces it; not a
            #   web-only column concern.
            continue

        mapping = table_mappings.get(diff.table)
        if mapping is None:
            errors.append(f"post_apply_diff:no_table_mapping:{diff.table}:{diff.key}")
            continue

        legacy_pk = str(diff.legacy_pk) if diff.legacy_pk is not None else ""

        for column in mapping.columns:
            # Skip columns that have a legacy source — those are
            # handled by the regular applier, not the web-only hook.
            if column.legacy_column is not None:
                continue
            strategy = column.web_only_strategy
            if strategy is None:
                # Exempt transform (default_uuid / default_now /
                # fk_lookup) — no shadow state, no derivation.
                continue

            outcome = _reconcile_column(
                diff=diff,
                column=column,
                mapping=mapping,
                shadow_state=shadow_state,
                sync_state=sync_state,
                legacy_snapshot=legacy_snapshot,
                snapshot_at=snapshot_at,
                errors=errors,
                legacy_pk=legacy_pk,
            )
            if outcome is not None:
                outcomes.append(outcome)

    # Phase 2: translate diffs into semantic events + persist.
    # Importación lazy: ``translate_diff`` vive en semantic_events.py
    # que importa ``Diff`` desde reporting.py. El import a runtime es
    # seguro (no hay ciclo), pero lo hacemos local para mantener el
    # patrón del módulo (derivation ya hace lo propio en
    # ``_reconcile_derived``).
    from migration.semantic_events import translate_diff

    for diff in applied_diffs:
        if diff.op in ("NOOP", "DELETE"):
            continue
        mapping = table_mappings.get(diff.table)
        if mapping is None:
            continue
        events = translate_diff(diff, mapping)
        if not events:
            continue
        if created_by is None:
            errors.append(
                f"post_apply_diff:missing_created_by:{diff.table}:{diff.key}:"
                f"{len(events)}_event(s)_skipped"
            )
            continue
        for event in events:
            try:
                _persist_lifecycle_event(
                    web_client=web_client,
                    event=event,
                    diff=diff,
                    created_by=created_by,
                )
            except Exception as exc:  # noqa: BLE001 — surface via errors
                errors.append(
                    f"post_apply_diff:lifecycle_event_insert_failed:"
                    f"{diff.table}:{diff.key}:{event.event_type}:{type(exc).__name__}:{exc}"
                )

    return ReconciliationResult(outcomes=tuple(outcomes), errors=tuple(errors))


def _reconcile_column(
    *,
    diff: Diff,
    column: ColumnMapping,
    mapping: TableMapping,
    shadow_state: _ShadowStateWriter,
    sync_state: SyncStateProtocol,
    legacy_snapshot: Mapping[str, Sequence[Mapping[str, Any]]] | None,
    snapshot_at: datetime,
    errors: list[str],
    legacy_pk: str,
) -> ReconciliationOutcome | None:
    """Dispatch one column through the right ``reconcile_after_legacy_write`` path.

    Extracted to keep :func:`post_apply_diff` readable and to make the
    per-column branch coverage explicit in tests.
    """
    strategy = column.web_only_strategy
    assert strategy is not None  # caller filters; assert for type checker
    web_column = column.web_column
    web_pk = diff.web_pk

    if strategy == "fixed":
        # No shadow state, no derivation — the YAML static value is
        # already in the web row from the applier pass.
        return _reconcile_fixed(
            table_name=diff.table,
            legacy_pk=legacy_pk,
            web_column=web_column,
            preserved_value=None,
        )

    if strategy == "preserve":
        # The web value (post-COMMIT) is what the shadow state must
        # keep verbatim. Read it from diff.web_row so we don't depend
        # on an extra DB roundtrip.
        web_row = diff.web_row or {}
        preserved_value = web_row.get(web_column) if web_row else None
        return reconcile_after_legacy_write(
            shadow_state=shadow_state,
            table_name=diff.table,
            legacy_pk=legacy_pk,
            web_pk=web_pk,
            web_column=web_column,
            strategy="preserve",
            preserved_value=preserved_value,
            last_legacy_snapshot_at=snapshot_at,
        )

    if strategy == "derived":
        # Read the sentinel comparator inputs (stored_state,
        # web_updated_at) from the snapshot BEFORE building the
        # derivation inputs. These are the values the comparator
        # (``compare_derived_to_stored``) needs to decide between
        # MATCHED / DIVERGENT / NEEDS_REVIEW — they are not part of
        # the derivation engine's input shape, so they live on the
        # snapshot as a side channel rather than inside derived_inputs.
        snapshot_dict = dict(legacy_snapshot) if legacy_snapshot else {}
        sentinel_stored = cast("str | None", snapshot_dict.pop("_stored_state", None))
        sentinel_updated_at = snapshot_dict.pop("_web_updated_at", None)
        if sentinel_updated_at is not None and not isinstance(sentinel_updated_at, datetime):
            errors.append(
                f"post_apply_diff:invalid_web_updated_at_type:{diff.table}:{legacy_pk}:"
                f"{type(sentinel_updated_at).__name__}"
            )
            sentinel_updated_at = None
        derived_inputs = _build_derived_inputs(
            diff=diff,
            mapping=mapping,
            legacy_snapshot=snapshot_dict,
        )
        return reconcile_after_legacy_write(
            shadow_state=shadow_state,
            table_name=diff.table,
            legacy_pk=legacy_pk,
            web_pk=web_pk,
            web_column=web_column,
            strategy="derived",
            preserved_value=None,
            last_legacy_snapshot_at=snapshot_at,
            derived_inputs=derived_inputs,
            stored_state=sentinel_stored,
            web_updated_at=sentinel_updated_at,
        )

    # Unknown strategy — treat as fixed (forward-compat with future
    # strategies added in later PRs without raising mid-batch).
    errors.append(f"post_apply_diff:unknown_strategy:{diff.table}:{web_column}:{strategy!r}")
    return _reconcile_fixed(
        table_name=diff.table,
        legacy_pk=legacy_pk,
        web_column=web_column,
        preserved_value=None,
    )


def _build_derived_inputs(
    *,
    diff: Diff,
    mapping: TableMapping,
    legacy_snapshot: Mapping[str, Sequence[Mapping[str, Any]]] | None,
) -> dict[str, Any]:
    """Build the ``derived_inputs`` dict for the derivation engine.

    The engine wants ``tb_ficha``, ``tb_entradas``, ``tb_acogidas``,
    ``tb_adopciones``. When the diff's legacy table IS one of those,
    that row goes into the matching key (it represents the latest
    snapshot of that side of the animal's lifecycle). The other keys
    fall back to ``legacy_snapshot`` (if provided) or empty lists.
    """
    legacy_table = mapping.legacy_table
    legacy_row = diff.legacy_row or {}

    if legacy_snapshot is None:
        legacy_snapshot = {}

    snapshot_lists = {
        "TbEntradas": list(legacy_snapshot.get("TbEntradas", ())),
        "TbAcogidaAnimal": list(legacy_snapshot.get("TbAcogidaAnimal", ())),
        "TbAdopcion": list(legacy_snapshot.get("TbAdopcion", ())),
    }
    ficha_list = list(legacy_snapshot.get("TbFichaAnimal", ()))

    if legacy_table == "TbFichaAnimal":
        tb_ficha = legacy_row or (ficha_list[0] if ficha_list else None)
        return {
            "tb_ficha": tb_ficha,
            "tb_entradas": snapshot_lists["TbEntradas"],
            "tb_acogidas": snapshot_lists["TbAcogidaAnimal"],
            "tb_adopciones": snapshot_lists["TbAdopcion"],
        }
    if legacy_table == "TbEntradas":
        return {
            "tb_ficha": ficha_list[0] if ficha_list else None,
            "tb_entradas": [legacy_row] if legacy_row else snapshot_lists["TbEntradas"],
            "tb_acogidas": snapshot_lists["TbAcogidaAnimal"],
            "tb_adopciones": snapshot_lists["TbAdopcion"],
        }
    if legacy_table == "TbAcogidaAnimal":
        return {
            "tb_ficha": ficha_list[0] if ficha_list else None,
            "tb_entradas": snapshot_lists["TbEntradas"],
            "tb_acogidas": [legacy_row] if legacy_row else snapshot_lists["TbAcogidaAnimal"],
            "tb_adopciones": snapshot_lists["TbAdopcion"],
        }
    if legacy_table == "TbAdopcion":
        return {
            "tb_ficha": ficha_list[0] if ficha_list else None,
            "tb_entradas": snapshot_lists["TbEntradas"],
            "tb_acogidas": snapshot_lists["TbAcogidaAnimal"],
            "tb_adopciones": [legacy_row] if legacy_row else snapshot_lists["TbAdopcion"],
        }
    # Fallback (non-lifecycle table): pass what we have.
    return {
        "tb_ficha": legacy_row or None,
        "tb_entradas": snapshot_lists["TbEntradas"],
        "tb_acogidas": snapshot_lists["TbAcogidaAnimal"],
        "tb_adopciones": snapshot_lists["TbAdopcion"],
    }


def _persist_lifecycle_event(
    *,
    web_client: SqlExecutor,
    event: LifecycleEvent,
    diff: Diff,
    created_by: str,
) -> None:
    """INSERT one ``LifecycleEvent`` into ``animal_lifecycle_events``.

    Resolves the ``animal_id`` FK via :func:`_resolve_animal_id`
    (which reads ``diff.web_pk`` for ``animales`` diffs and
    ``diff.web_row["animal_id"]`` for child-table diffs — the
    applier stamps the FK when it commits the child row).

    Idempotence (PR 4 follow-up, P1 #2): the INSERT is guarded with
    ``ON CONFLICT (animal_id, event_type, event_timestamp) DO NOTHING``
    so a retry apply after a ``sync_state.save()`` post-COMMIT
    failure does NOT create a duplicate event row. The
    ``animal_lifecycle_events_natural_key`` UNIQUE constraint on
    ``(animal_id, event_type, event_timestamp)`` (declared in
    ``app/core/domain.py::ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL``)
    is what makes the ``ON CONFLICT`` clause resolve to a no-op.
    Without it, a retry would create a duplicate row that the animal
    state machine would count as a second transition for the same
    logical event — silent data corruption. The constraint + DO
    NOTHING combo is the DB-level idempotence guard that complements
    the application-level idempotence of the derivation engine
    (design §8).
    """
    # Resolve animal_id. For an animales diff, web_pk is the animal's
    # own UUID. For child-table diffs, the applier stamps the FK on
    # ``diff.web_row["animal_id"]`` when it commits the child row.
    animal_id = _resolve_animal_id(diff=diff)
    if animal_id is None:
        # Child-table diff where the animal FK is not recorded on
        # the web row. Surface as a hard error so the caller can
        # decide (NOT a silent drop — that would lose a real event).
        raise ValueError(
            f"Cannot resolve animal_id for {diff.table} "
            f"(legacy_pk={diff.legacy_pk!r}); the applier must stamp "
            f"the FK on diff.web_row['animal_id'] before invoking "
            f"post_apply_diff."
        )

    # Validate created_by is a UUID.
    try:
        UUID(created_by)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"created_by must be a UUID string; got {created_by!r}") from exc

    sql = (
        "INSERT INTO animal_lifecycle_events ("
        "animal_id, event_type, event_timestamp, "
        "source_entity_type, source_entity_id, "
        "legacy_source_table, legacy_source_id, "
        "metadata, created_by"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
        # Idempotence guard: a retry of the same logical event (same
        # animal + same event_type + same event_timestamp) collapses to
        # a single row. The UNIQUE constraint on
        # (animal_id, event_type, event_timestamp) is the matching
        # arbiter. Spec: spec.md REQ-Capa Semantica de Eventos.
        "ON CONFLICT (animal_id, event_type, event_timestamp) DO NOTHING"
    )
    import json

    metadata_json = json.dumps(event.metadata) if event.metadata is not None else None
    params: list[Any] = [
        animal_id,
        event.event_type,
        event.event_timestamp.isoformat(),
        event.source_entity_type,
        # source_entity_id: prefer the web UUID of the source row
        # when the diff carries one; fall back to None.
        diff.web_pk,
        event.legacy_source_table,
        event.legacy_source_id,
        metadata_json,
        created_by,
    ]
    web_client.execute_sql(sql, params)


def _resolve_animal_id(
    *,
    diff: Diff,
) -> str | None:
    """Resolve the ``animal_id`` for a ``LifecycleEvent`` INSERT.

    Rules (kept simple to avoid coupling to MIGRATION-01 sync_state
    internals — the spec REQ-Hook mandates the persister but does
    NOT specify the FK-resolution mechanism):

      - ``diff.table == "animales"``: ``diff.web_pk`` IS the animal's
        web UUID.
      - Child tables (``TbEntradas``, ``TbAcogidaAnimal``,
        ``TbAdopcion``): the applier stamps the FK onto
        ``diff.web_row["animal_id"]`` when it commits the child row.
        The hook reads it from there.
      - If neither path yields a UUID, the event is dropped (and the
        persister raises — never silently).
    """
    if diff.table == "animales":
        return diff.web_pk
    web_row = diff.web_row or {}
    animal_id = web_row.get("animal_id") if web_row else None
    if isinstance(animal_id, str) and animal_id:
        return animal_id
    return None


# --- Public protocols -----------------------------------------------------
#
# The hook accepts two protocols (``web_client``, ``sync_state``) instead
# of the concrete classes so tests can pass lightweight fakes without
# importing the full machinery. The shapes mirror the methods the hook
# actually uses (``execute_sql`` for the web client; ``sync_state`` is
# accepted for future extensibility but is currently unused by the hook
# body because the animal_id FK is read from ``diff.web_row``). The
# real ``LocalPostgresExecutor`` + ``SyncState`` satisfy both protocols
# structurally (duck-typed; no inheritance required).


class SqlExecutor(Protocol):
    """Structural type for the web client passed to ``post_apply_diff``.

    Mirrors the ``execute_sql`` surface used by the lifecycle-event
    persister. The real ``LocalPostgresExecutor`` satisfies this without any
    inheritance (duck-typed).
    """

    def execute_sql(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]: ...


class SyncStateProtocol(Protocol):
    """Structural type for the sync_state passed to ``post_apply_diff``.

    Currently a marker protocol — the hook does NOT call any method
    on sync_state directly (the animal_id FK is read from
    ``diff.web_row``). The protocol is kept on the hook signature so
    MIGRATION-01 PR 5/6 (applier) can wire up the future "FK recorded
    in sync_state" path without breaking the public contract.
    """

    pass


__all__ = [
    "REVIEW_REASON_WEB_MANUAL_OVERRIDE",
    "ReconciliationOutcome",
    "ReconciliationResult",
    "ReconciliationStatus",
    "ReconciliationSummary",
    "post_apply_diff",
    "reconcile_after_legacy_write",
]
