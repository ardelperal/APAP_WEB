from typing import TYPE_CHECKING
from app.core.data_access import SqlExecutor
if TYPE_CHECKING:
    from app.core.data_access import SqlExecutor  # noqa: F401
"""Shadow-state helpers for the reverse applier.

Two helpers live here:

- :func:`_advance_preserve_shadow_state` — bumps
  ``last_legacy_snapshot_at`` for every ``preserve`` column (web-only
  shadow) and routes the per-row collision via ``record_dni_collision``
  so the operator can resolve it via ``apap-migrate reconcile``.
- :func:`_record_drift_needs_review` — records a ``needs_review`` row
  when the legacy write seam returns ``rowcount=0`` (drift detection).

The derivation engine (``migration.derivation``) is NEVER called by
the reverse applier — the spec scenario
``derived column with state change emits LIFECYCLE_REVERSED``
is observational only. This module only touches the shadow table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from migration import dni_collision as dni_collision_mod
from migration.dni_collision import DniCollisionCounter
from migration.reverse_apply.types import SqlExecutor
from migration.shadow_state import ShadowStateRepository

DIRECTION_WEB_TO_LEGACY = "web-to-legacy"


def _advance_preserve_shadow_state(
    *,
    client: SqlExecutor,
    mapping: Any,
    web_row: dict[str, Any],
    legacy_pk: str,
    direction: str,
    dni_collision_counter: DniCollisionCounter | None,
) -> None:
    """Advance the per-row preserve-column shadow state.

    For each column with ``web_only_strategy == "preserve"`` whose
    web-side value is set, call :func:`record_dni_collision` with
    ``direction`` so the operator can resolve the row via
    ``apap-migrate reconcile --filter-direction web-to-legacy`` AND
    the per-strategy contract ``Reverse: advance last_legacy_snapshot_at``
    is honoured (``record_dni_collision`` updates
    ``last_legacy_snapshot_at`` and stamps the categorical
    ``dni_collision`` review reason via
    ``update_reconciliation_status``).

    Bumps ``dni_collision_counter`` once per preserve-column
    advance so the PR7 reconcile CLI can surface the count via
    ``MigrationReport.collisions[<table>]["preserve_advances"]``.
    Note: this counter reflects the number of preserve-column
    advances (one per preserve column with a web-side value),
    not the number of actual collisions. The key was renamed from
    ``dni_collisions`` to ``preserve_advances`` in issue #217.

    Note: column names are looked up case-insensitively against
    the web row (the YAML carries CamelCase names like ``DNI``;
    the web side stores lowercase keys). The ``web_column`` name
    stamped on the shadow row is the canonical YAML form so the
    operator CLI's filter (``--column dni`` or ``DNI``) keeps
    working through future lowercase naming migrations.
    """
    from migration.reverse_apply.io_helpers import _case_insensitive_get

    repo = ShadowStateRepository(client)
    for col in mapping.columns:
        if getattr(col, "web_only_strategy", None) != "preserve":
            continue
        value = _case_insensitive_get(web_row, col.web_column)
        if value is None:
            continue
        dni_collision_mod.record_dni_collision(
            shadow_state=repo,
            table_name=mapping.web_table,
            legacy_pk=legacy_pk,
            web_pk=legacy_pk,
            web_column=col.web_column,
            direction=direction,  # type: ignore[arg-type]
        )
        if dni_collision_counter is not None:
            dni_collision_counter.bump()


def _record_drift_needs_review(
    *,
    client: SqlExecutor,
    mapping: Any,
    web_row: dict[str, Any],
    legacy_pk: str,
    source_hash: str,
    target_hash: str,
) -> None:
    """Record a ``needs_review`` shadow row when the reverse write can't land.

    PR6 spec scenario ``Round-trip detects drift as needs_review``:
    when the legacy executor returns ``rowcount == 0`` after an
    UPDATE (i.e., the natural-key row was deleted in legacy between
    forward and reverse), the reverse applier records the divergence
    in ``web_only_feature_shadow`` so the operator can resolve it
    via ``apap-migrate reconcile --filter-direction web-to-legacy``.
    The ``preserved_value`` carries the pre/post hashes (NOT the
    raw payload — count + hash evidence only, per the PII audit
    doc's ``Count + Hash Evidence`` invariant).
    """
    repo = ShadowStateRepository(client)
    repo.upsert(
        table_name=mapping.web_table,
        legacy_pk=legacy_pk,
        web_pk=legacy_pk,
        web_column="__row__",
        preserved_value={
            "source_hash": source_hash,
            "target_hash": target_hash,
            "drift_kind": "reverse_legacy_row_missing",
        },
        strategy="preserve",
        reconciliation_status="needs_review",
        origin_direction=DIRECTION_WEB_TO_LEGACY,
    )
    repo.update_reconciliation_status(
        table_name=mapping.web_table,
        legacy_pk=legacy_pk,
        web_column="__row__",
        status="needs_review",
        review_reasons=["reverse_drift_legacy_row_missing"],
    )


__all__ = [
    "DIRECTION_WEB_TO_LEGACY",
    "_advance_preserve_shadow_state",
    "_record_drift_needs_review",
]
